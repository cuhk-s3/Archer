#!/usr/bin/env python3
"""Reuse saved A analyses and optionally run C, bypassing verification B."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent


def collect_analyses(log_dir: Path, dataset_dir: Path, excluded: set[str]):
  logs = sorted(log_dir.glob("*.json"))
  if not logs:
    raise ValueError(f"No collect logs found in {log_dir}")
  grouped = defaultdict(list)
  records = []
  skipped = []
  for log_path in logs:
    issue = log_path.stem
    if issue in excluded:
      skipped.append({"issue": issue, "reason": "regression"})
      continue
    data = json.loads(log_path.read_text())
    analyses = [
      item["content"]
      for item in data.get("strategies", [])
      if isinstance(item, dict)
      and isinstance(item.get("content"), str)
      and item["content"].strip()
    ]
    if not analyses:
      skipped.append({"issue": issue, "reason": "no_A_output"})
      continue
    issue_path = dataset_dir / "issues" / f"{issue}.json"
    if not issue_path.exists():
      issue_path = dataset_dir / f"{issue}.json"
    issue_data = json.loads(issue_path.read_text())
    components = issue_data.get("hints", {}).get("components", []) or ["unknown"]
    components = sorted({re.sub(r"[^a-zA-Z0-9_\-]", "_", c) for c in components})
    # Only A's natural-language analysis is passed to C. In particular, neither
    # B's success/failure nor its generated examples affect inclusion or content.
    section = f"# Issue {issue}\n\n" + "\n\n".join(analyses) + "\n"
    for component in components:
      grouped[component].append(section)
    records.append(
      {
        "issue": issue,
        "components": components,
        "source_log": str(log_path.resolve()),
        "analysis_model": data.get("command", {}).get("model"),
      }
    )
  if not grouped:
    raise ValueError("No usable A outputs remain after filtering.")
  passes = {name: "\n---\n\n".join(parts) for name, parts in sorted(grouped.items())}
  return passes, {"pipeline": "A-C", "records": records, "skipped": skipped}


def prepare_inputs(output_dir: Path, passes: dict[str, str], manifest: dict):
  passes_dir = output_dir / "passes"
  existing = {p.stem: p.read_text() for p in passes_dir.glob("*.md")}
  if existing != passes and any((output_dir / "summary").rglob("*.md")):
    raise ValueError("A inputs changed after C was run; choose a new --output-dir.")
  if existing != passes and any((output_dir / "log").rglob("*.json")):
    raise ValueError("A inputs changed after C was run; choose a new --output-dir.")
  passes_dir.mkdir(parents=True, exist_ok=True)
  for name, content in passes.items():
    (passes_dir / f"{name}.md").write_text(content)
  # This directory is dedicated to generated A inputs. Remove obsolete component
  # files when re-preparing before C has run, so C cannot consume stale inputs.
  for name in existing.keys() - passes.keys():
    (passes_dir / f"{name}.md").unlink()
  (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def summary_commands(output_dir: Path, components, model: str, python: str):
  model_dir = re.sub(r"[^a-zA-Z0-9_.-]", "-", model)
  for component in components:
    yield (
      component,
      [
        python,
        str(ROOT / "subsystem" / "summary.py"),
        "--component",
        component,
        "--model",
        model,
        "--passes-dir",
        str(output_dir / "passes"),
        "--output-dir",
        str(output_dir / "summary" / model_dir),
        "--log-dir",
        str(output_dir / "log" / model_dir),
      ],
    )


def parse_args(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--analysis-log-dir", type=Path, default=EXPERIMENT_DIR / "collect" / "log"
  )
  parser.add_argument("--dataset-dir", type=Path, default=ROOT / "dataset")
  parser.add_argument(
    "--regression-dir",
    type=Path,
    default=ROOT / "experiment" / "2-regression" / "dataset",
  )
  parser.add_argument(
    "--include-regression",
    action="store_true",
    help="Include regression issues (excluded by default).",
  )
  parser.add_argument(
    "--output-dir", type=Path, default=EXPERIMENT_DIR / "no-verification"
  )
  parser.add_argument(
    "--summarize",
    action="store_true",
    help="Run C after preparing A inputs. Default: prepare only, no API calls.",
  )
  parser.add_argument("--model", help="Model for C; required with --summarize.")
  parser.add_argument("--python", default=sys.executable)
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Show input counts and C commands without writing files or calling APIs.",
  )
  args = parser.parse_args(argv)
  if args.summarize and not args.model:
    parser.error("--summarize requires --model")
  return args


def run(argv=None):
  args = parse_args(argv)
  if not args.include_regression and not list(args.regression_dir.glob("*.json")):
    raise ValueError(
      f"Regression exclusion dataset is missing or empty: {args.regression_dir}"
    )
  excluded = (
    set()
    if args.include_regression
    else {p.stem for p in args.regression_dir.glob("*.json")}
  )
  passes, manifest = collect_analyses(args.analysis_log_dir, args.dataset_dir, excluded)
  manifest["excluded_regression"] = sorted(excluded)
  output_dir = args.output_dir.resolve()
  print("Pipeline: A -> C (reuse saved A outputs; B is not run)")
  print(
    f"A outputs: {len(manifest['records'])}; skipped: {len(manifest['skipped'])}; components: {len(passes)}"
  )
  print(f"Output: {output_dir}")
  if not args.dry_run:
    prepare_inputs(output_dir, passes, manifest)
  if not args.summarize:
    print("Preparation only; no API calls. Use --summarize --model MODEL to run C.")
    return 0
  failed = []
  for component, cmd in summary_commands(output_dir, passes, args.model, args.python):
    if args.dry_run:
      print(shlex.join(cmd))
      continue
    log_path = Path(cmd[-1]) / f"{component}.json"
    summary_path = Path(cmd[cmd.index("--output-dir") + 1]) / f"{component}.md"
    if log_path.exists():
      log = json.loads(log_path.read_text())
      if not log.get("error") and summary_path.exists():
        print(f"[{component}] existing summary; skipping.")
        continue
      print(
        f"[{component}] incomplete/failed C record: {log_path}. Move it aside before retrying."
      )
      failed.append(component)
      continue
    if summary_path.exists():
      print(
        f"[{component}] summary exists without log; refusing to overwrite {summary_path}."
      )
      failed.append(component)
      continue
    print(f"[{component}] running C...", flush=True)
    if subprocess.run(cmd, cwd=ROOT, check=False).returncode:
      failed.append(component)
  if failed:
    print(f"Failed components: {', '.join(failed)}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(run())
