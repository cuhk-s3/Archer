import re
from pathlib import Path
from typing import List, Tuple


class VeIR:
  """Small adapter exposing the bits of VeIR needed by the review loop."""

  def __init__(self, repo: str):
    self.repo = Path(repo).resolve()

  def resolve_pass_name(self, args: str) -> Tuple[str, List[str]]:
    pipelines = re.findall(r"(?:^|\s)-p(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", args)
    names = [next(part for part in match if part) for match in pipelines]
    return ",".join(names) if names else "unknown", []

  def resolve_pass_opts(self, pass_name: str) -> List[str]:
    return []

