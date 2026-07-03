"""Bug reproduction primitive.

Given a captured bug reproducer (original IR + opt args, plus an optional call
instruction for difftest bugs), re-run it against an *arbitrary* LLVM build and
report whether the bug still triggers. This single primitive powers two flows:

  * Baseline check    -- re-run a freshly found bug on the baseline build
                         (base commit, no patch). If it triggers there too the
                         bug is not patch-specific.
  * Regression gate   -- re-run a previous version's bugs on the current version.
                         If any still triggers, the PR has not fixed it yet.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple

from llvm.llvm_helper import strip_llvm_fence
from tools.trans import is_opt_crash

_DIFFTEST_TEMPLATE = """
{ir}

define {type} @main(i32 %argc, ptr %argv) {{
entry:
  {call_instr}
  {ret_instr}
}}
"""


@dataclass
class Reproducer:
  """The minimal, re-runnable description of a bug."""

  kind: str  # "verify" | "trans" | "difftest"
  original_ir: str  # LLVM IR (fenced or raw); the target function/module
  args: str  # opt arguments, e.g. "-passes=instcombine"
  call_instr: Optional[str] = None  # difftest only

  def is_runnable(self) -> bool:
    if not self.original_ir or not self.args:
      return False
    return True


def _fenced(ir: str) -> str:
  ir = (ir or "").strip()
  if ir.startswith("```"):
    return ir
  return f"```llvm\n{ir}\n```"


def _opt_path(build_dir) -> Path:
  return Path(build_dir).resolve() / "bin" / "opt"


def _run(cmd, timeout: int = 60):
  return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _reproduce_transform(
  build_dir, repro: Reproducer, alive_path: Optional[str]
) -> Tuple[bool, str]:
  """verify/trans reproducer: opt crash or alive-tv 'incorrect transformations'."""
  opt_path = _opt_path(build_dir)
  if not opt_path.is_file():
    return False, f"opt not found at {opt_path}"

  orig_code = strip_llvm_fence(_fenced(repro.original_ir))
  with TemporaryDirectory() as tmp:
    orig = Path(tmp) / "orig.ll"
    transformed = Path(tmp) / "transformed.ll"
    orig.write_text(orig_code, encoding="utf-8")

    args = (repro.args or "").split()
    proc = _run([str(opt_path), "-S", *args, str(orig), "-o", str(transformed)])
    if proc.returncode != 0:
      err = proc.stderr.decode("utf-8", errors="replace")
      if is_opt_crash(err):
        return True, f"opt crashed during transformation:\n{err.strip()}"
      return False, f"opt failed (non-crash):\n{err.strip()}"

    # No crash: fall back to alive-tv correctness check when available.
    if not alive_path or not Path(alive_path).is_file():
      return False, "no crash; alive-tv unavailable, treated as not triggered"

    alive = _run(
      [str(alive_path), *args, "--disable-undef-input", str(orig), str(transformed)]
    )
    out = (alive.stdout.decode("utf-8", errors="replace")).strip()
    m = re.search(r"(\d+)\s+incorrect transformations", out)
    triggered = bool(m and int(m.group(1)) > 0)
    return triggered, out


def _reproduce_difftest(
  build_dir, repro: Reproducer, llubi_path: Optional[str], use_lli: bool
) -> Tuple[bool, str]:
  """difftest reproducer: opt-transform then execute orig vs transformed and diff.

  Two shapes are supported:
    * ``call_instr`` present -> ``original_ir`` is a function/module snippet and
      is wrapped in a driver ``@main`` that performs ``call_instr``.
    * ``call_instr`` absent  -> ``original_ir`` is already a complete, runnable
      program (this is what difftest 'confirm' bugs store).
  """
  opt_path = _opt_path(build_dir)
  if not opt_path.is_file():
    return False, f"opt not found at {opt_path}"

  orig_body = strip_llvm_fence(_fenced(repro.original_ir))
  call = (repro.call_instr or "").strip()

  with TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    orig_prog = tmp / "orig.ll"
    trans_prog = tmp / "transformed.ll"
    src = tmp / "src.ll"
    args = (repro.args or "").split()

    if call:
      m = re.fullmatch(
        r"\s*call\s+(.+?)\s+@(?:[-$._A-Za-z0-9]+|\"(?:[^\"\\]|\\.)+\")\s*\(.*\)\s*$",
        call,
      )
      if not m:
        return False, f"invalid call instruction for difftest: {call}"
      call_type = m.group(1).strip()
      if call_type != "void":
        call_line = f"%r = {call}"
        ret_line = f"ret {call_type} %r"
      else:
        call_line = call
        ret_line = "ret void"
      program_body = _DIFFTEST_TEMPLATE.format(
        ir=orig_body, type=call_type, call_instr=call_line, ret_instr=ret_line
      )
    else:
      # original_ir is already a full runnable program.
      program_body = orig_body

    src.write_text(program_body, encoding="utf-8")
    proc = subprocess.run(
      [str(opt_path), "-S", *args, str(src)], capture_output=True, timeout=60
    )
    if proc.returncode != 0:
      err = proc.stderr.decode("utf-8", errors="replace")
      if is_opt_crash(err):
        return True, f"opt crashed during transformation:\n{err.strip()}"
      return False, f"opt failed (non-crash):\n{err.strip()}"
    transformed_body = proc.stdout.decode("utf-8", errors="replace").strip()

    orig_prog.write_text(program_body, encoding="utf-8")
    trans_prog.write_text(transformed_body, encoding="utf-8")

    lli_path = _opt_path(build_dir).parent / "lli"
    executor = str(lli_path) if use_lli else (llubi_path or str(lli_path))
    if not Path(executor).is_file():
      return False, f"executor not found: {executor}"

    def exec_prog(path):
      try:
        r = _run([str(executor), str(path)], timeout=10)
        return (r.returncode, r.stdout.decode("utf-8", errors="replace").strip())
      except subprocess.TimeoutExpired:
        return (None, "<timeout>")

    o1 = exec_prog(orig_prog)
    o2 = exec_prog(trans_prog)
    triggered = o1 != o2
    return triggered, f"orig={o1}\ntransformed={o2}"


def reproduce(
  build_dir,
  repro: Reproducer,
  alive_path: Optional[str] = None,
  llubi_path: Optional[str] = None,
  use_lli: bool = False,
) -> Tuple[bool, str]:
  """Re-run ``repro`` against the LLVM build at ``build_dir``.

  Returns ``(triggered, log)``. ``triggered`` is True when the bug still
  manifests (opt crash, alive-tv incorrect transformation, or an execution
  divergence for difftest reproducers).
  """
  if not repro.is_runnable():
    return False, "reproducer is not runnable (missing ir/args/call_instr)"
  try:
    if repro.kind == "difftest":
      return _reproduce_difftest(build_dir, repro, llubi_path, use_lli)
    return _reproduce_transform(build_dir, repro, alive_path)
  except subprocess.TimeoutExpired:
    return False, "reproduction timed out"
  except Exception as e:  # never let a repro failure break the pipeline
    return False, f"reproduction error: {type(e).__name__}: {e}"
