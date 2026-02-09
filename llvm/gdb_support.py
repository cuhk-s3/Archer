import os
import platform
import time
from pathlib import Path
from typing import List, Optional, Tuple

from pwnlib import gdb, tubes
from pwnlib.context import context
from pwnlib.util.misc import which

from llvm.debugger import DebuggerBase, StackTrace, Symbol, TraceItem
from llvm.llvm_helper import llvm_dir

INIT_GDB_SCRIPT = f"""
set confirm off
set verbose off
set pagination off
set breakpoint pending on
set unwindonsignal on
set startup-with-shell off
tbreak llvm::runPassPipeline
source {llvm_dir}/llvm/utils/gdb-scripts/prettyprinters.py
set print pretty on
continue
"""


class GDB(DebuggerBase):
  process: tubes.process.process
  gdb_api: gdb.Gdb

  def __init__(self, arguments: list[str]):
    super().__init__()

    gdb_python_path = (
      tubes.process.process(
        [
          gdb.binary(),
          "--nx",
          "-batch",
          "-ex",
          'python import sys; print(":".join(sys.path))',
        ]
      )
      .recvall()
      .strip()
      .decode()
    )
    if "TMUX" in os.environ and which("tmux"):
      print("Tmux detected.")
      # FIX: pwnlib spawns a tmux terminal to call gdb, however the environment variables were not passed.
      # This is a workaround to pass the PYTHONPATH and other variables to the tmux terminal.
      print("GDB Python path:", gdb_python_path)
      context.terminal = [
        "tmux",
        "splitw",
        "-h",
        "-e",
        f"PYTHONPATH={gdb_python_path}",
      ]
    elif which("tmux"):
      print("Create a background tmux session for GDB.")
      context.terminal = [
        "tmux",
        "new-session",
        "-d",
        "-e",
        f"PYTHONPATH={gdb_python_path}",
      ]
    else:
      raise RuntimeError("Unsupported terminal; please use tmux. Quit for now.")

    version_check = [
      gdb.binary(),
      "--nx",
      "-batch",
      "-ex",
      "python import platform; print(platform.python_version())",
    ]
    gdb_python_version = tubes.process.process(version_check).recvall().strip().decode()
    print("GDB Python version:", gdb_python_version)
    print("Expected Python version:", platform.python_version())

    self.process = gdb.debug(
      args=arguments, gdbscript=INIT_GDB_SCRIPT, aslr=False, api=True, sysroot="/"
    )
    self.gdb_api = self.process.gdb
    # Disable remote trackback
    self.gdb_api.conn._config["include_local_traceback"] = False

  def cont(self):
    self.gdb_api.write("continue\n")
    self.gdb_api.continue_and_wait()

  def execute_custom_command(self, command: str) -> str:
    try:
      command = command.lstrip()
      for keyword in ["shell", "make", "pipe", "q", "exit", "r", "start", "!", "|"]:
        if command.startswith(keyword):
          return f"Error: Command '{command}' is not allowed due to security reasons."

      if "$_shell" in command:
        return "Error: Command with $_shell is not allowed due to security reasons."

      self.gdb_api.write(command + "\n")
      res = self.gdb_api.execute(command, to_string=True).strip() + "\n"
      self.gdb_api.write(res)
      return res + self.process.recv(numb=1e9, timeout=0.1).decode().strip() + "\n"
    except Exception as e:
      if hasattr(e, "_remote_tb"):
        del e._remote_tb
      raise e

  def execute_gdb_command(self, command: str):
    self.gdb_api.write(command + "\n")
    self.gdb_api.execute(command)

  def query_gdb_command(self, command: str) -> str:
    self.gdb_api.write(command + "\n")
    return self.gdb_api.execute(command, to_string=True)

  def is_scalar_type(self, ty) -> bool:
    return ty.code in [
      self.gdb_api.TYPE_CODE_PTR,
      self.gdb_api.TYPE_CODE_INT,
      self.gdb_api.TYPE_CODE_FLT,
      self.gdb_api.TYPE_CODE_CHAR,
      self.gdb_api.TYPE_CODE_BOOL,
      self.gdb_api.TYPE_CODE_REF,
      self.gdb_api.TYPE_CODE_RVALUE_REF,
      self.gdb_api.TYPE_CODE_ENUM,
    ]

  def decay_type(self, ty):
    while True:
      ty = ty.unqualified()
      try:
        ty = ty.target()
      except Exception:
        break

    return ty

  def has_dump(self, val, ty) -> bool:
    if ty.code not in [
      self.gdb_api.TYPE_CODE_PTR,
      self.gdb_api.TYPE_CODE_REF,
      self.gdb_api.TYPE_CODE_RVALUE_REF,
      self.gdb_api.TYPE_CODE_STRUCT,
    ]:
      return False

    decay_ty = self.decay_type(ty)
    CLASSES_WITH_DUMP = [
      "llvm::APFixedPoint",
      "llvm::APFloat",
      "llvm::APInt",
      "llvm::APSInt",
      "llvm::Value",
      "llvm::User",
      "llvm::Constant",
      "llvm::Instruction",
      "llvm::KnownBits",
      "llvm::ConstantRange",
      "llvm::Type",
      "llvm::IntegerType",
      "llvm::PointerType",
      "llvm::FunctionType",
      "llvm::StructType",
      "llvm::ArrayType",
      "llvm::VectorType",
      "llvm::FixedVectorType",
      "llvm::ScalableVectorType",
    ]
    if str(decay_ty) in CLASSES_WITH_DUMP:
      return True
    if str(decay_ty) in ["llvm::BasicBlock", "llvm::Function"]:
      return False

    # Check if the value can convert to the root class llvm::Value
    try:
      if "*" in str(ty):
        val = val.dereference()
      func_subclassid = self.gdb_api.parse_and_eval("(int)llvm::Value::FunctionVal")
      bb_subclassid = self.gdb_api.parse_and_eval("(int)llvm::Value::BasicBlockVal")
      subclassid = val["SubclassID"].cast(self.gdb_api.lookup_type("int"))
      _ = val["HasValueHandle"]
      return str(subclassid) not in [str(func_subclassid), str(bb_subclassid)]
    except Exception:
      pass

    return False

  def dump_llvm_symbol(self, sym, is_pointer) -> Optional[str]:
    try:
      access = "->" if is_pointer else "."
      print(f"Dumping symbol {sym.name} ... ", end="", flush=True)
      self.execute_gdb_command(f"call {sym.name}{access}dump()")
      print("dumped")
      return self.process.recv(timeout=0.1).decode().strip()
    except Exception:
      return None

  def has_print(self, val, ty) -> bool:
    if ty.code not in [
      self.gdb_api.TYPE_CODE_PTR,
      self.gdb_api.TYPE_CODE_REF,
      self.gdb_api.TYPE_CODE_RVALUE_REF,
      self.gdb_api.TYPE_CODE_STRUCT,
    ]:
      return False

    decay_ty = self.decay_type(ty)
    CLASSES_WITH_PRINT = [
      "llvm::InstructionCost",
    ]
    return str(decay_ty) in CLASSES_WITH_PRINT

  def print_llvm_symbol(self, sym, is_pointer) -> Optional[str]:
    try:
      access = "->" if is_pointer else "."
      self.execute_gdb_command(
        f"call {sym.name}{access}print(*(llvm::raw_ostream*)(&llvm::errs()))"
      )
      return self.process.recv(timeout=0.1).decode().strip()
    except Exception:
      return None

  def parse_symbol(self, sym, frame) -> Optional[Symbol]:
    if sym.is_constant:
      return None
    if sym.type is None:
      return None
    if sym.type.code == self.gdb_api.TYPE_CODE_FUNC:
      return None
    if sym.name == "__PRETTY_FUNCTION__":
      return None
    render_type = str(sym.type)
    render_str = "<optimized out>"
    try:
      value = sym.value(frame)
      is_nonnull = True
      if self.is_scalar_type(sym.type):
        render_str = str(value)
        is_nonnull = not render_str.strip().endswith("0x0")
      if is_nonnull:
        if self.has_dump(value, sym.type):
          res = self.dump_llvm_symbol(
            sym, value.type.code == self.gdb_api.TYPE_CODE_PTR
          )
          if res:
            render_str = res
        elif self.has_print(value, sym.type):
          res = self.print_llvm_symbol(
            sym, value.type.code == self.gdb_api.TYPE_CODE_PTR
          )
          if res:
            render_str = res
    except Exception:
      pass
    return Symbol(
      name=sym.print_name,
      type=render_type,
      line=sym.line,
      val=render_str,
      is_arg=sym.is_argument,
    )

  def eval_symbol(self, symbol_name: str) -> Optional[str]:
    try:
      current_frame = self.gdb_api.selected_frame()
      block = current_frame.block()
      while block:
        if block.is_global or block.is_static:
          break
        for sym in block:
          if hasattr(sym, "name") and sym.name == symbol_name:
            parsed = self.parse_symbol(sym, current_frame)
            if parsed and parsed.val != "<optimized out>":
              return str(parsed)
        block = block.superblock
      return None
    except Exception:
      return None

  def is_interesting_frame(self, file: str) -> bool:
    if not file.startswith("llvm/"):
      return False
    unrelated_dirs = ["ADT", "Support", "CodeGen", "Target"]
    for dir_name in unrelated_dirs:
      if f"llvm/{dir_name}" in file or f"llvm/lib/{dir_name}" in file:
        return False
    return True

  def is_interesting_breakpoint(self, frame, is_miscompilation: bool):
    if not is_miscompilation:
      return True
    top_bp_name = frame.name()
    if not top_bp_name:
      return True
    if not top_bp_name.startswith("llvm::Use::"):
      return True
    while True:
      frame = frame.older()
      if not frame:
        return True
      func = frame.name()
      if not func:
        func = "<unknown>"

      if func.startswith("llvm::ConstantAggregate::ConstantAggregate"):
        return False

      if func.startswith("llvm::MemoryUseOrDef::setOperand"):
        return False

      if func.startswith("llvm::MemoryDef::setOperand"):
        return False

      if func.startswith("llvm::MemorySSAUpdater::removeMemoryAccess"):
        return False

      if "Pass::run" in func or "llvm::runPassPipeline" in func:
        break
    return True

  def run(
    self,
    src_path: Path,
    locations: List[str],
    is_miscompilation: bool,
    frame_limit: int = 0,
  ) -> Tuple[StackTrace, Optional[str]]:
    # Stop at crash/edit point
    self.gdb_api.wait()
    print("Adding breakpoints")
    self.execute_gdb_command("set breakpoint pending off")
    # rbreak is very time-consuming, so we increase the timeout.
    self.gdb_api.conn._config["sync_request_timeout"] = 600
    start_time = time.time()
    for loc in locations:
      print(f"Setting breakpoint at {loc} ... ", end="", flush=True)
      try:
        if loc.startswith("*"):
          self.execute_gdb_command(f"rbreak {loc[1:]}")
        else:
          self.execute_gdb_command(f"break {loc}")
        print("succeeded")
      except Exception as e:
        print(f"failed (skip): {e}")
    end_time = time.time()
    print("Number of breakpoints:", self.gdb_api.parse_and_eval("$bpnum"))
    self.gdb_api.conn._config["sync_request_timeout"] = 30
    print(f"Time used in setting up breakpoints: {end_time - start_time:.2f}s")
    while True:
      self.cont()
      if self.is_interesting_breakpoint(self.gdb_api.newest_frame(), is_miscompilation):
        break
    # Clean up previous output
    self.process.recv(numb=10**9, timeout=0.5)
    print("Parsing frames and their symbols ...")
    frames = StackTrace()
    current_frame = self.gdb_api.newest_frame()
    stoppoint = None
    level = 0
    while current_frame and (frame_limit <= 0 or len(frames) < frame_limit):
      current_frame.select()
      func = current_frame.name()
      if stoppoint is None:
        stoppoint = func
      if not func:
        func = "<unknown>"
      loc = current_frame.find_sal()
      line = 0
      file = "<unknown>"
      if loc:
        line = loc.line
        if loc.symtab:
          file = loc.symtab.filename
      file = Path(file)
      try:
        file = file.relative_to(src_path)
      except Exception:
        pass
      if self.is_interesting_frame(str(file)):
        available_symbols = []
        # print(f"Parsing level-{level} frame {func}() at {file}:{line}")
        func_start = int(1e10)
        try:
          block = current_frame.block()
          func_symbol = block.function
          if func_symbol and func_symbol.is_function:
            func_start = func_symbol.line
        except Exception:
          pass
        # We defer symbol parsing into the eval tool.
        # try:
        #   block = current_frame.block()
        #   while block:
        #     if block.is_global or block.is_static:
        #       break
        #     for sym in block:
        #       parsed = self.parse_symbol(sym, current_frame)
        #       if parsed:
        #         available_symbols.append(parsed)
        #     block = block.superblock
        # except Exception:
        #   pass
        frames.append(
          TraceItem(
            file=file,
            func=func,
            func_start=func_start,
            line=line,
            level=level,
            symbols=available_symbols,
          )
        )
        print(frames[-1])
        for sym in available_symbols:
          print(f"  {sym}")
      if "Pass::run" in func or "llvm::runPassPipeline" in func:
        break
      current_frame = current_frame.older()
      level += 1
    frames.reverse()
    self.gdb_api.newest_frame().select()

    return frames, stoppoint

  def reset_frame(self):
    # Selected thread may be still running (e.g, LLM uses the continue command), wait for it to stop.
    while True:
      try:
        self.gdb_api.newest_frame().select()
        break
      except Exception as e:
        if "Selected thread is running" in str(e):
          time.sleep(10)
          continue
        raise e

  def select_frame(self, func_name: str) -> bool:
    current_frame = self.gdb_api.selected_frame()
    while current_frame and current_frame.name() != func_name:
      current_frame = current_frame.older()
    if current_frame and current_frame.name() == func_name:
      current_frame.select()
      return True
    else:
      return False

  def backtrack(self, steps: int):
    current_frame = self.gdb_api.selected_frame()
    for _ in range(steps):
      if current_frame.older():
        current_frame = current_frame.older()
      else:
        break
    current_frame.select()
