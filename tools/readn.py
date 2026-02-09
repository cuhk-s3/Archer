from pathlib import Path

from lms.tool import FuncToolBase, FuncToolCallException, FuncToolSpec
from tools.llvm_mixins import LlvmDirMixin


class ReadNTool(FuncToolBase, LlvmDirMixin):
  def __init__(self, llvm_dir: str, n: int):
    self.llvm_dir = Path(llvm_dir).resolve().absolute()
    self.n = n

  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      f"read{self.n}",
      f"Read the next {self.n} lines of content of a file starting a specific line.",
      [
        FuncToolSpec.Param(
          "file",
          "string",
          True,
          "The relative path to the file to read. The path should start with llvm/.",
        ),
        FuncToolSpec.Param(
          "position",
          "integer",
          True,
          "The line number to start reading from (1-based index).",
        ),
      ],
    )

  def _call(self, *, file: str, position: int, **kwargs) -> str:
    if position < 1:
      raise FuncToolCallException(
        f"Position must be a positive integer, but {position} was given."
      )
    file_full_path = self.check_llvm_file(file)
    try:
      lines = file_full_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception as e:
      raise FuncToolCallException(f"Failed to read the file {file}. {e}")
    start_pos = position - 1  # Convert to 0-based index
    if start_pos >= len(lines):
      raise FuncToolCallException(
        f"Position {position} is out of bounds for the file {file} (total lines: {len(lines)})."
      )
    end_pos = min(start_pos + self.n, len(lines))
    selected = lines[start_pos:end_pos]
    header = f"file: {file}:{position}-{end_pos + 1}\n"
    separator = "-" * (len(header) - 1)
    lno_fmt = "{:>" + str(len(str(end_pos + 1))) + "}"
    return (
      header
      + separator
      + "\n"
      + "".join(
        [
          lno_fmt.format(lno + position) + " " + line
          for lno, line in enumerate(selected)
        ]
      )
      + separator
    )
