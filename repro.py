"""Minimal persisted reproducer shared by review storage and VeIR replay."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Reproducer:
  kind: str
  original_ir: str
  args: str
  call_instr: Optional[str] = None

  def is_runnable(self) -> bool:
    return bool(self.original_ir and self.args)
