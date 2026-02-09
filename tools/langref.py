from llvm.lab_env import Environment
from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec


class LangRefTool(FuncToolBase):
  def __init__(self, env: Environment):
    self.env = env

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "langref",
      "Get the detailed description of an LLVM instruction/intrinsic from the LLVM Language Reference Manual.",
      [
        FuncToolSpec.Param(
          "inst",
          "string",
          True,
          "The instruction/intrinsic that you'd like to get the description for.\n"
          "For instructions, please provide the instruction name (e.g., `add`, `mul`, etc.).\n"
          "For intrinsics, please provide the intrinsic name (e.g., `llvm.sadd.with.overflow`, `llvm.memcpy`, etc.).\n"
          "Do not include type mangling suffix or operands in the name.",
        ),
      ],
    )

  def _call(self, *, inst: str, **kwargs) -> str:
    res = self.env.get_langref_desc([inst])
    if inst in res:
      return res[inst]
    raise FuncToolCallException(
      f"'{inst}' is not found in the LLVM Language Reference Manual."
    )
