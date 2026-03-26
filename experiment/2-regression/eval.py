#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Run regression batch experiments with one unified entrypoint.",
  )
  parser.add_argument(
    "--experiment",
    type=str,
    required=True,
    choices=["archer", "mswe", "direct-llm"],
    help="Experiment type to run.",
  )
  parser.add_argument(
    "--dataset-dir",
    type=Path,
    default=Path("dataset"),
    help="Directory containing issue JSON files.",
  )
  parser.add_argument(
    "--model",
    type=str,
    required=True,
    help="Model name for the selected experiment.",
  )
  parser.add_argument(
    "--model-dir",
    type=str,
    default=None,
    help=(
      "Output folder suffix override. Uses model name with '/' replaced by '-' when omitted."
    ),
  )
  parser.add_argument(
    "--output-dir",
    type=Path,
    default=Path("results"),
    help="Directory to store experiment outputs.",
  )
  parser.add_argument(
    "--python",
    type=str,
    default=sys.executable,
    help="Python executable used to launch experiment scripts.",
  )
  parser.add_argument(
    "--limit",
    type=int,
    default=None,
    help="Optional max number of dataset items to run.",
  )
  parser.add_argument(
    "--dry-run",
    action="store_true",
    default=False,
    help="Print commands without executing.",
  )
  parser.add_argument(
    "--no-debug",
    action="store_true",
    default=False,
    help="Disable passing --debug to experiment scripts.",
  )
  parser.add_argument(
    "--knowledge-source",
    type=str,
    default="summary",
    choices=["summary", "passes"],
    help=(
      "Knowledge source for archer: 'summary' -> 1-pass-knowledge/summary/non-regression, "
      "'passes' -> 1-pass-knowledge/passes-non-regression."
    ),
  )
  parser.add_argument(
    "--no-knowledge",
    action="store_true",
    default=False,
    help="Disable passing subsystem knowledge when the experiment supports it.",
  )
  return parser.parse_args()


def resolve_experiment_config(name: str) -> dict[str, str | bool]:
  if name == "archer":
    return {
      "script": "scripts/archer.py",
      "needs_review": True,
      "output_prefix": "archer",
      "supports_no_knowledge": True,
    }
  if name == "mswe":
    return {
      "script": "scripts/mswe.py",
      "needs_review": False,
      "output_prefix": "mswe",
      "supports_no_knowledge": False,
    }
  if name == "direct-llm":
    return {
      "script": "scripts/direct_llm.py",
      "needs_review": False,
      "output_prefix": "direct-llm",
      "supports_no_knowledge": False,
    }
  raise ValueError(f"Unsupported experiment: {name}")


def resolve_model_dir(model: str, model_dir: str | None) -> str:
  if model_dir:
    return model_dir

  # Normalize provider/model into model for directory naming.
  # Example: google/gemini-3.1-pro-preview-customtools -> gemini-3.1-pro-preview-customtools
  mapped = model.split("/")[-1]
  return mapped.replace("/", "-")


def collect_issue_files(dataset_dir: Path) -> list[Path]:
  if not dataset_dir.exists() or not dataset_dir.is_dir():
    raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
  return sorted(dataset_dir.glob("*.json"))


def build_command(
  python_bin: str,
  script_path: Path,
  issue: str,
  model: str,
  stats_path: Path,
  history_path: Path,
  review_path: Path | None,
  knowledge_dir: Path | None,
  debug_enabled: bool,
  no_knowledge_enabled: bool,
) -> list[str]:
  cmd = [
    python_bin,
    str(script_path),
    "--issue",
    issue,
    "--model",
    model,
    "--stats",
    str(stats_path),
    "--history",
    str(history_path),
  ]
  if review_path is not None:
    cmd.extend(["--review", str(review_path)])
  if knowledge_dir is not None:
    cmd.extend(["--knowledge-dir", str(knowledge_dir)])
  if debug_enabled:
    cmd.append("--debug")
  if no_knowledge_enabled:
    cmd.append("--no-knowledge")
  return cmd


def resolve_knowledge_dir(base_dir: Path, source: str) -> Path:
  if source == "summary":
    return base_dir.parent / "1-pass-knowledge" / "summary" / "non-regression"
  if source == "passes":
    return base_dir.parent / "1-pass-knowledge" / "summary" / "passes-non-regression"
  raise ValueError(f"Unsupported knowledge source: {source}")


def run() -> int:
  args = parse_args()
  experiment = args.experiment
  config = resolve_experiment_config(experiment)

  base_dir = Path(__file__).resolve().parent
  dataset_dir = args.dataset_dir
  if not dataset_dir.is_absolute():
    dataset_dir = base_dir / dataset_dir

  model = args.model
  model_dir = resolve_model_dir(model, args.model_dir)
  if experiment == "archer" and args.knowledge_source == "passes":
    model_dir = f"{model_dir}-all-knowledge"
  output_dir = args.output_dir
  if not output_dir.is_absolute():
    output_dir = base_dir / output_dir

  output_root = output_dir / f"{config['output_prefix']}-{model_dir}"
  history_dir = output_root / "history"
  review_dir = output_root / "review"

  if not args.dry_run:
    output_root.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    if config["needs_review"]:
      review_dir.mkdir(parents=True, exist_ok=True)

  script_path = base_dir / config["script"]
  if not script_path.exists():
    raise FileNotFoundError(f"Experiment script not found: {script_path}")

  issue_files = collect_issue_files(dataset_dir)
  if args.limit is not None:
    issue_files = issue_files[: args.limit]

  no_knowledge_enabled = bool(
    args.no_knowledge and config.get("supports_no_knowledge", False)
  )
  if no_knowledge_enabled:
    output_root = output_dir / f"{config['output_prefix']}-{model_dir}-wo-knowledge"
    history_dir = output_root / "history"
    review_dir = output_root / "review"
    if not args.dry_run:
      output_root.mkdir(parents=True, exist_ok=True)
      history_dir.mkdir(parents=True, exist_ok=True)
      if config["needs_review"]:
        review_dir.mkdir(parents=True, exist_ok=True)
  if args.no_knowledge and not no_knowledge_enabled:
    print(
      f"Warning: --no-knowledge is not supported for experiment '{experiment}', ignoring."
    )

  if not issue_files:
    print(f"No dataset files found in {dataset_dir}")
    return 0

  print(f"Experiment: {experiment}")
  print(f"Model: {model}")
  print(f"Dataset: {dataset_dir}")
  print(f"Issues: {len(issue_files)}")

  failed_issues: list[str] = []
  debug_enabled = not args.no_debug
  knowledge_dir: Path | None = None
  if experiment == "archer":
    knowledge_dir = resolve_knowledge_dir(base_dir, args.knowledge_source)

  for dataset_file in issue_files:
    issue = dataset_file.stem
    stats_path = output_root / f"{issue}.json"
    history_path = history_dir / f"{issue}.json"
    review_path = review_dir / f"{issue}.md" if config["needs_review"] else None

    cmd = build_command(
      python_bin=args.python,
      script_path=script_path,
      issue=issue,
      model=model,
      stats_path=stats_path,
      history_path=history_path,
      review_path=review_path,
      knowledge_dir=knowledge_dir,
      debug_enabled=debug_enabled,
      no_knowledge_enabled=no_knowledge_enabled,
    )

    print(f"[{issue}] running...")
    if args.dry_run:
      print(" ".join(cmd))
      continue

    proc = subprocess.run(cmd, cwd=base_dir, check=False)
    if proc.returncode != 0:
      failed_issues.append(issue)
      print(f"[{issue}] failed with exit code {proc.returncode}")
    else:
      print(f"[{issue}] done")

  if args.dry_run:
    print("Dry run completed.")
    return 0

  if failed_issues:
    print(f"Failed issues ({len(failed_issues)}): {', '.join(failed_issues)}")
    return 1

  print("All issues completed successfully.")
  return 0


if __name__ == "__main__":
  raise SystemExit(run())
