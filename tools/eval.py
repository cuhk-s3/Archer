from llvm.debugger import DebuggerBase
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class EvalTool(FuncToolBase):
  def __init__(self, debugger: DebuggerBase):
    self.debugger = debugger

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "eval",
      "Evaluate an expression in the debugger and obtain its value. Please make sure that you have set the correct frame in the debugger before using this tool.",
      [
        FuncToolSpec.Param(
          "expr",
          "string",
          True,
          "The expression that you'd like to evaluate and obtain its value",
        ),
      ],
    )

  def _call(self, *, expr: str, **kwargs) -> str:
    """
    Get the value of the expression
    """
    try:
      symbol = self.debugger.eval_symbol(expr)
      if symbol:
        return str(symbol)
      return self.debugger.execute_custom_command(f"print {expr}")
    except Exception as e:
      raise FuncToolCallException(str(e))
