from pathlib import Path

from lms.tool import FuncToolCallException


class RepoDirMixin:
  def check_repo_dir(self, subdir: str) -> Path:
    path = (self.repo_dir / subdir).resolve()
    if not path.is_relative_to(self.repo_dir) or not path.is_dir():
      raise FuncToolCallException(f"Invalid repository directory: {subdir}")
    return path

  def check_repo_file(self, filename: str) -> Path:
    path = (self.repo_dir / filename).resolve()
    if not path.is_relative_to(self.repo_dir) or not path.is_file():
      raise FuncToolCallException(f"Invalid repository file: {filename}")
    return path
