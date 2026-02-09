from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Symbol:
  name: str
  type: str
  line: int
  val: str
  is_arg: bool

  def __str__(self) -> str:
    if self.is_arg:
      return f"arg {self.type} {self.name} = {self.val} (line {self.line})"
    return f"var {self.type} {self.name} = {self.val} (line {self.line})"


@dataclass
class TraceItem:
  file: Path
  func: str
  func_start: int
  line: int
  level: int
  symbols: List[Symbol]

  def as_tuple(self) -> Tuple[str, str, int]:
    return (str(self.file), self.func, self.line)

  def __str__(self) -> str:
    return f"(frame {self.level}) {self.file}:{self.line} in {self.func}"


class StackTrace(List[TraceItem]):
  def clone(self):
    return StackTrace(self)


# Possible debuggers:
# - LLDB (LLVM Debugger)
#   - https://lldb.llvm.org/use/python-reference
#   - https://github.com/llvm/llvm-project/blob/main/lldb/examples/python/types.py
# - GDB (GNU Debugger)
#   - https://sourceware.org/gdb/onlinedocs/gdb/Python-API.html


class DebuggerBase(ABC):
  def __init__(self):
    pass

  @abstractmethod
  def run(
    self,
    src_path: Path,
    locations: List[str],
    is_miscompilation: bool,
    frame_limit: int = 0,
  ) -> Tuple[StackTrace, Optional[str]]:
    """Run the debugger on the given source path until one of the breakpoint locations is reached, returning the stack trace at that breakpoint, limited by frame_limit. When frame_limit is non-positive, all frames are returned."""
    ...

  @abstractmethod
  def execute_custom_command(self, command: str) -> str:
    """Execute a custom command in the debugger and return its output"""
    ...

  @abstractmethod
  def reset_frame(self):
    """Reset to the newest frame"""
    ...

  @abstractmethod
  def select_frame(self, func_name: str) -> bool:
    """
    Select an old frame with the same function name, starting from the currently selected frame.
    Return True if found and selected, False otherwise.
    """
    ...

  @abstractmethod
  def backtrack(self, num_frames: int):
    """
    Backtrack a certain number of frames from the current selected frame.
    Stop either when reaching the oldest frame or when the number of frames is reached.
    """
    ...

  @abstractmethod
  def eval_symbol(self, symbol_name: str) -> Optional[str]:
    """
    Evaluate a symbol in the current frame.
    If found, return a string representation of the symbol.
    """
    ...
