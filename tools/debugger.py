from llvm.debugger import DebuggerBase
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class DebuggerTool(FuncToolBase):
  def __init__(self, debugger: DebuggerBase):
    self.debugger = debugger

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "debug",
      "Execute a GDB command and obtain the results from gdb, stdout, and stderr.\n"
      "Initially the debugger is stopped at the first transformation/crash breakpoint.\n"
      "Note that you are not allowed to start a new session or close the current session (i.e., executing run/start/quit/exit).\n"
      "Shell commands (shell/make/pipe) are also forbidden due to security reasons.",
      [
        FuncToolSpec.Param("cmd", "string", True, "The GDB command"),
      ],
    )

  def _call(self, *, cmd: str, **kwargs) -> str:
    """
    Execute the debugger command
    """
    try:
      return self.debugger.execute_custom_command(cmd)
    except Exception as e:
      raise FuncToolCallException(str(e))
