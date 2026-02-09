from pathlib import Path

from lms.tool import FuncToolCallException


class LlvmDirMixin:
  def check_llvm_dir(self, subdir: str) -> Path:
    """
    Check if the given directory is a subdirectory of the llvm/ directory.
    Raises FuncToolCallException if the directory is not valid.
    """
    if not subdir.startswith("llvm"):
      raise FuncToolCallException(
        "The directory path must start with llvm/. Please provide a valid relative path."
      )
    full_path = (self.llvm_dir / subdir).resolve().absolute()
    if not full_path.is_relative_to(self.llvm_dir / "llvm"):
      raise FuncToolCallException(
        "The directory path must be relative to the llvm/ directory. Please provide a valid relative path."
      )
    if not full_path.exists():
      raise FuncToolCallException(f"The directory {subdir} does not exist.")
    if not full_path.is_dir():
      raise FuncToolCallException(f"The path {subdir} is not a directory.")
    return full_path

  def check_llvm_file(self, file: str) -> Path:
    """
    Check if the given file is a valid file in the llvm directory.
    Raises FuncToolCallException if the file is not valid.
    """
    if not file.startswith("llvm"):
      raise FuncToolCallException(
        "The file path must start with llvm/. Please provide a valid relative path."
      )
    full_path = (self.llvm_dir / file).resolve().absolute()
    if not full_path.is_relative_to(self.llvm_dir / "llvm"):
      raise FuncToolCallException(
        "The file path must be relative to the llvm/ directory. Please provide a valid relative path."
      )
    if not full_path.exists():
      raise FuncToolCallException(f"The file {file} does not exist.")
    if not full_path.is_file():
      raise FuncToolCallException(f"The path {file} is not a file.")
    return full_path  # Return the resolved path for further use
