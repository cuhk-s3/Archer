from pathlib import Path

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.llvm_mixins import LlvmDirMixin


class ListTool(FuncToolBase, LlvmDirMixin):
  def __init__(self, llvm_dir: str):
    self.llvm_dir = Path(llvm_dir).resolve().absolute()

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "list",
      "List the contents of a directory.",
      [
        FuncToolSpec.Param(
          "directory",
          "string",
          True,
          "The relative path (starting with llvm/) to the directory to list.",
        ),
      ],
    )

  def _call(self, *, directory: str, **kwargs) -> str:
    dir_full_path = self.check_llvm_dir(directory)
    try:
      contents = [path for path in dir_full_path.iterdir()]
      files = [path for path in contents if path.is_file()]
      dirs = [path for path in contents if path.is_dir()]
      results = [str(path.relative_to(self.llvm_dir)) + "/" for path in dirs] + [
        str(path.relative_to(self.llvm_dir)) for path in files
      ]
    except Exception as e:
      raise FuncToolCallException(f"Failed to list the directory {directory}. {e}")
    return "\n".join(results) or "The directory is empty."
