import glob
from pathlib import Path

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.llvm_mixins import LlvmDirMixin


class FindNTool(FuncToolBase, LlvmDirMixin):
  def __init__(self, llvm_dir: str, n: int):
    self.llvm_dir = Path(llvm_dir).resolve().absolute()
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      f"find{self.n}",
      f"Find all files following a specified pattern (e.g., `src/**/*.cpp`, `**/*.h`) in the specified directory. The results will be sorted alphabetically and only {self.n} results will be returned starting from a given index.",
      [
        FuncToolSpec.Param(
          "k",
          "integer",
          True,
          f"The index to start returning the results from (1-based index). For example, when k=10, it will return the 10th result and the next {self.n - 1} results.",
        ),
        FuncToolSpec.Param("pattern", "string", True, "The pattern of the files."),
        FuncToolSpec.Param(
          "directory",
          "string",
          True,
          "Find files in this directory (a relative path starting with llvm/).",
        ),
      ],
    )

  def _call(self, *, k: int, pattern: str, directory: str, **kwargs) -> str:
    if k < 1:
      raise FuncToolCallException(
        f"The index k must be a positive integer, but {k} was given."
      )
    dir_full_path = self.check_llvm_dir(directory)
    try:
      results = glob.glob(pattern, root_dir=dir_full_path, recursive=True)
    except Exception as e:
      raise FuncToolCallException(f"Failed to find files with pattern {pattern}. {e}")
    if not results:
      return f"No files found matching the pattern {pattern}."
    results = [f"{path}" for path in results if (dir_full_path / path).is_file()]
    results.sort()  # Sort the results alphabetically
    k -= 1  # Convert to 0-based index
    if k >= len(results):
      raise FuncToolCallException(
        f"Index {k + 1} is out of bounds for the results (total results: {len(results)})."
      )
    selected = results[k : k + self.n]
    return "\n".join(selected)  # Return the selected files as a single string
