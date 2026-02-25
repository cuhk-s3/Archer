from pathlib import Path

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.llvm_mixins import LlvmDirMixin


class ListNTool(FuncToolBase, LlvmDirMixin):
  def __init__(self, llvm_dir: str, n: int):
    self.llvm_dir = Path(llvm_dir).resolve().absolute()
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      f"list{self.n}",
      f"List up to {self.n} contents of a directory. All contents of the directory will be sorted alphabetically and only up to {self.n} of them are returned starting from a given index.",
      [
        FuncToolSpec.Param(
          "directory",
          "string",
          True,
          "The relative path (starting with llvm/) to the directory to list.",
        ),
        FuncToolSpec.Param(
          "k",
          "integer",
          True,
          f"The index to start returning the contents from (1-based index). For example, when k=10, it will return the 10th content and the next {self.n - 1} results.",
        ),
      ],
    )

  def _call(self, *, directory: str, k: int, **kwargs) -> str:
    if k < 1:
      raise FuncToolCallException(
        f"The index k must be a positive integer, but {k} was given."
      )
    k -= 1  # Convert to 0-based index
    dir_full_path = self.check_llvm_dir(directory)
    try:
      contents = [path for path in dir_full_path.iterdir()]
      files = [path for path in contents if path.is_file()]
      dirs = [path for path in contents if path.is_dir()]
      results = [str(path.relative_to(self.llvm_dir)) + "/" for path in dirs] + [
        str(path.relative_to(self.llvm_dir)) for path in files
      ]
      results.sort()  # Sort the results alphabetically
    except Exception as e:
      raise FuncToolCallException(f"Failed to list the directory {directory}. {e}")
    if k >= len(results):
      raise FuncToolCallException(
        f"Index {k + 1} is out of bounds for the contents (total contents: {len(results)}). It must be between 1 and {len(results)}."
      )
    return "\n".join(results[k : k + self.n]) or "The directory is empty."
