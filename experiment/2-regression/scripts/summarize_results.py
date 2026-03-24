#!/usr/bin/env python3
import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MILLION = 1_000_000


# Costs are USD per 1M tokens.
DEEPSEEK_PRICING = {
  "input_cache_hit": 0.028,
  "input_cache_miss": 0.28,
  "output": 0.42,
}

QWEN_PRICING = {
  "input": 0.115,
  "output": 0.688,
}


@dataclass
class Totals:
  files: int = 0
  input_tokens: int = 0
  cached_tokens: int = 0
  output_tokens: int = 0
  total_tokens: int = 0
  total_time_sec: float = 0.0
  raw_chat_cost: float = 0.0
  computed_cost: float = 0.0

  def add(self, entry: dict[str, Any]) -> None:
    self.files += 1
    self.input_tokens += int(entry.get("input_tokens", 0) or 0)
    self.cached_tokens += int(entry.get("cached_tokens", 0) or 0)
    self.output_tokens += int(entry.get("output_tokens", 0) or 0)
    self.total_tokens += int(entry.get("total_tokens", 0) or 0)
    self.total_time_sec += float(entry.get("total_time_sec", 0.0) or 0.0)
    self.raw_chat_cost += float(entry.get("chat_cost", 0.0) or 0.0)
    self.computed_cost += float(entry.get("computed_cost", 0.0) or 0.0)

  def to_dict(self) -> dict[str, float | int]:
    files = self.files if self.files > 0 else 1
    return {
      "files": self.files,
      "input_tokens": self.input_tokens,
      "cached_tokens": self.cached_tokens,
      "output_tokens": self.output_tokens,
      "total_tokens": self.total_tokens,
      "total_time_sec": self.total_time_sec,
      "raw_chat_cost": self.raw_chat_cost,
      "computed_cost": self.computed_cost,
      "avg_input_tokens": self.input_tokens / files,
      "avg_cached_tokens": self.cached_tokens / files,
      "avg_output_tokens": self.output_tokens / files,
      "avg_total_tokens": self.total_tokens / files,
      "avg_time_sec": self.total_time_sec / files,
      "avg_raw_chat_cost": self.raw_chat_cost / files,
      "avg_computed_cost": self.computed_cost / files,
    }


def compute_cost(
  model_name: str,
  input_tokens: int,
  cached_tokens: int,
  output_tokens: int,
  raw_chat_cost: float,
) -> tuple[float, str]:
  model = (model_name or "").lower()

  if "deepseek" in model:
    cache_hit = max(cached_tokens, 0)
    cache_miss = max(input_tokens - cached_tokens, 0)
    cost = (
      (cache_hit / MILLION) * DEEPSEEK_PRICING["input_cache_hit"]
      + (cache_miss / MILLION) * DEEPSEEK_PRICING["input_cache_miss"]
      + (output_tokens / MILLION) * DEEPSEEK_PRICING["output"]
    )
    return cost, "deepseek_pricing"

  if "qwen" in model:
    # Use only regular pricing (no batch/cache tiers).
    cost = (input_tokens / MILLION) * QWEN_PRICING["input"] + (
      output_tokens / MILLION
    ) * QWEN_PRICING["output"]
    return cost, "qwen_pricing"

  # Gemini and any other model use recorded cost in JSON.
  return raw_chat_cost, "raw_chat_cost"


def is_stats_json(data: dict[str, Any]) -> bool:
  required = ["input_tokens", "output_tokens", "total_tokens", "total_time_sec"]
  return all(key in data for key in required)


def relative_group_name(results_dir: Path, json_path: Path) -> str:
  rel = json_path.relative_to(results_dir)
  if len(rel.parts) <= 1:
    return "."
  return rel.parts[0]


def format_seconds(seconds: float) -> str:
  return f"{seconds:.2f}s ({seconds / 60.0:.2f}m)"


def print_table(title: str, rows: list[tuple[str, Totals]]) -> None:
  if not rows:
    print(f"\n{title}\n(no data)")
    return

  print(f"\n{title}")
  print("-" * len(title))
  header = (
    f"{'group':40} {'files':>6} {'input':>12} {'cached':>12} {'output':>12} "
    f"{'total':>12} {'time':>18} {'raw_cost($)':>14} {'computed($)':>14} {'avg_comp($)':>14}"
  )
  print(header)
  print("-" * len(header))

  for name, total in sorted(rows, key=lambda item: item[0]):
    avg_comp = (total.computed_cost / total.files) if total.files > 0 else 0.0
    print(
      f"{name:40} {total.files:6d} {total.input_tokens:12d} {total.cached_tokens:12d} "
      f"{total.output_tokens:12d} {total.total_tokens:12d} {format_seconds(total.total_time_sec):>18} "
      f"{total.raw_chat_cost:14.6f} {total.computed_cost:14.6f} {avg_comp:14.6f}"
    )


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Summarize tokens, time, and cost from results JSON files."
  )
  parser.add_argument(
    "--results-dir",
    type=Path,
    default=Path(__file__).resolve().parent.parent / "results",
    help="Path to results directory (default: experiment/2-regression/results)",
  )
  parser.add_argument(
    "--output-json",
    type=Path,
    default=None,
    help="Optional path to save machine-readable summary JSON.",
  )
  return parser.parse_args()


def main() -> None:
  args = parse_args()
  results_dir = args.results_dir.resolve()

  if not results_dir.exists() or not results_dir.is_dir():
    raise SystemExit(f"Invalid results directory: {results_dir}")

  by_folder: dict[str, Totals] = defaultdict(Totals)
  by_model: dict[str, Totals] = defaultdict(Totals)
  overall = Totals()

  parsed_files = 0
  skipped_files = 0
  source_files = sorted(results_dir.rglob("*.json"))

  for json_path in source_files:
    try:
      with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception:
      skipped_files += 1
      continue

    if not isinstance(data, dict) or not is_stats_json(data):
      skipped_files += 1
      continue

    command = data.get("command", {})
    model_name = ""
    if isinstance(command, dict):
      model_name = str(command.get("model", "") or "")
    model_name = model_name or "unknown"

    input_tokens = int(data.get("input_tokens", 0) or 0)
    cached_tokens = int(data.get("cached_tokens", 0) or 0)
    output_tokens = int(data.get("output_tokens", 0) or 0)
    raw_chat_cost = float(data.get("chat_cost", 0.0) or 0.0)

    computed_cost, _ = compute_cost(
      model_name=model_name,
      input_tokens=input_tokens,
      cached_tokens=cached_tokens,
      output_tokens=output_tokens,
      raw_chat_cost=raw_chat_cost,
    )

    enriched_entry = dict(data)
    enriched_entry["computed_cost"] = computed_cost

    group_name = relative_group_name(results_dir, json_path)
    by_folder[group_name].add(enriched_entry)
    by_model[model_name].add(enriched_entry)
    overall.add(enriched_entry)
    parsed_files += 1

  print(f"Results dir: {results_dir}")
  print(f"JSON files found: {len(source_files)}")
  print(f"Stats files parsed: {parsed_files}")
  print(f"Skipped files: {skipped_files}")

  print_table("Summary by Folder", list(by_folder.items()))
  print_table("Summary by Model", list(by_model.items()))
  print_table("Overall", [("all", overall)])

  if args.output_json:
    output = {
      "results_dir": str(results_dir),
      "files_found": len(source_files),
      "files_parsed": parsed_files,
      "files_skipped": skipped_files,
      "by_folder": {k: v.to_dict() for k, v in sorted(by_folder.items())},
      "by_model": {k: v.to_dict() for k, v in sorted(by_model.items())},
      "overall": overall.to_dict(),
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("w", encoding="utf-8") as f:
      json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved JSON summary to: {args.output_json}")


if __name__ == "__main__":
  main()
