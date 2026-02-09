import re
from pathlib import Path

from llvm.debugger import DebuggerBase
from llvm.llvm import LLVM
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class DocsTool(FuncToolBase):
  def __init__(self, llvm: LLVM, debugger: DebuggerBase):
    self.llvm = llvm
    self.debugger = debugger
    self.pattern = re.compile('Line (\\d+) of "([^"]+)" starts at')

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "docs",
      "Obtain the documentation of a function in LLVM",
      [FuncToolSpec.Param("func", "string", True, "Name of the function")],
    )

  def _call(self, *, func: str, **kwargs) -> str:
    """
    Get the document from LLVM, perhaps we should build a database
    We use the header comments of the function for now.
    """
    try:
      res = self.debugger.execute_custom_command(f"info line {func}")
      match = re.search(self.pattern, res)
      if match:
        return self.llvm.render_func_code(
          func, int(match.group(1)), Path(match.group(2)).relative_to(self.llvm.repo)
        ).header
      return "Unavailable"
    except Exception as e:
      raise FuncToolCallException(str(e))
