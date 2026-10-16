import json

from repro import Reproducer
from tools.veir_verify import VerifyTool


def reproduce(build_dir, repro: Reproducer):
  """Re-run a stored VeIR reproducer using veir-opt and veir-interpret."""
  if not repro.is_runnable():
    return False, "incomplete reproducer"
  try:
    result = json.loads(VerifyTool(build_dir).call(
      orig_ir=repro.original_ir, args=repro.args, thoughts="regression replay"
    ))
    return bool(result.get("found")), result.get("log", "")
  except Exception as exc:
    return False, str(exc)
