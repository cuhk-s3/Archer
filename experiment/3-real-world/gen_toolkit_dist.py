#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description=(
      "Summarize selected tool calls and draw three horizontal bars: "
      "context, verification, workflow."
    )
  )
  parser.add_argument(
    "--results-dir",
    type=Path,
    default=Path(__file__).resolve().parents[2] / "record",
    help="Path to results directory containing stats JSON files.",
  )
  parser.add_argument(
    "--output-png",
    type=Path,
    default=Path(__file__).resolve().parents[2] / "record" / "toolkit_dist.png",
    help="Output path of the bar chart PNG.",
  )
  parser.add_argument(
    "--output-json",
    type=Path,
    default=Path(__file__).resolve().parents[2] / "record" / "toolkit_dist.json",
    help="Output path of aggregated statistics JSON.",
  )
  parser.add_argument(
    "--output-pdf",
    type=Path,
    default=Path(__file__).resolve().parents[2] / "record" / "toolkit_dist.pdf",
    help="Output path of the bar chart PDF.",
  )
  return parser.parse_args()


def is_stats_json(data: dict[str, Any]) -> bool:
  required = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "total_time_sec",
    "tool_usage",
  ]
  return all(key in data for key in required)


def normalized_tool_calls(tool_usage: Any) -> dict[str, int]:
  out: dict[str, int] = {}
  if not isinstance(tool_usage, list):
    return out
  for item in tool_usage:
    if not isinstance(item, dict):
      continue
    name = str(item.get("name", "") or "").strip().lower()
    calls = int(item.get("usage", 0) or 0)
    if not name:
      continue
    out[name] = out.get(name, 0) + calls
  return out


def collect_search_calls(tool_calls: dict[str, int]) -> int:
  # Search tools in this project are typically *250 variants.
  search_names = {"find250", "grep250", "list250", "read250"}
  return sum(c for n, c in tool_calls.items() if n in search_names)


def main() -> None:
  args = parse_args()
  results_dir = args.results_dir.resolve()
  if not results_dir.exists() or not results_dir.is_dir():
    raise SystemExit(f"Invalid results directory: {results_dir}")

  files_found = 0
  files_parsed = 0
  files_skipped = 0
  files_with_selected_calls = 0

  context_parts = {
    "search": 0,
    "langref": 0,
  }
  verification_parts = {
    "trans": 0,
    "difftest": 0,
    "verify": 0,
  }
  workflow_parts = {
    "tests_manager": 0,
    "stop": 0,
    "review": 0,
  }
  group_share_sum_percent = {
    "context": 0.0,
    "verification": 0.0,
    "workflow": 0.0,
  }
  tool_share_sum_percent = {
    "context": {"search": 0.0, "langref": 0.0},
    "verification": {"trans": 0.0, "difftest": 0.0, "verify": 0.0},
    "workflow": {"tests_manager": 0.0, "stop": 0.0, "review": 0.0},
  }

  for json_path in sorted(results_dir.rglob("*.json")):
    files_found += 1
    try:
      with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception:
      files_skipped += 1
      continue

    if not isinstance(data, dict) or not is_stats_json(data):
      files_skipped += 1
      continue

    tool_calls = normalized_tool_calls(data.get("tool_usage", []))
    file_context = {
      "search": collect_search_calls(tool_calls),
      "langref": tool_calls.get("langref", 0),
    }
    file_verification = {
      "trans": tool_calls.get("trans", 0),
      "difftest": tool_calls.get("difftest", 0),
      "verify": tool_calls.get("verify", 0),
    }
    file_workflow = {
      "tests_manager": tool_calls.get("tests_manager", 0),
      "stop": tool_calls.get("stop", 0),
      "review": tool_calls.get("review", 0) + tool_calls.get("report", 0),
    }

    context_parts["search"] += file_context["search"]
    context_parts["langref"] += file_context["langref"]

    verification_parts["trans"] += file_verification["trans"]
    verification_parts["difftest"] += file_verification["difftest"]
    verification_parts["verify"] += file_verification["verify"]

    workflow_parts["tests_manager"] += file_workflow["tests_manager"]
    workflow_parts["stop"] += file_workflow["stop"]
    workflow_parts["review"] += file_workflow["review"]

    file_group_totals = {
      "context": sum(file_context.values()),
      "verification": sum(file_verification.values()),
      "workflow": sum(file_workflow.values()),
    }
    file_selected_total = sum(file_group_totals.values())
    if file_selected_total > 0:
      files_with_selected_calls += 1
      for group_name, group_total in file_group_totals.items():
        group_share_sum_percent[group_name] += group_total * 100.0 / file_selected_total

      for tool_name, val in file_context.items():
        tool_share_sum_percent["context"][tool_name] += (
          val * 100.0 / file_selected_total
        )
      for tool_name, val in file_verification.items():
        tool_share_sum_percent["verification"][tool_name] += (
          val * 100.0 / file_selected_total
        )
      for tool_name, val in file_workflow.items():
        tool_share_sum_percent["workflow"][tool_name] += (
          val * 100.0 / file_selected_total
        )
    files_parsed += 1

  group_totals = {
    "context": sum(context_parts.values()),
    "verification": sum(verification_parts.values()),
    "workflow": sum(workflow_parts.values()),
  }
  total_selected_calls = sum(group_totals.values())
  group_avg_calls_per_file = {
    k: (v / files_parsed if files_parsed > 0 else 0.0) for k, v in group_totals.items()
  }
  tool_avg_calls_per_file = {
    "context": {
      k: (v / files_parsed if files_parsed > 0 else 0.0)
      for k, v in context_parts.items()
    },
    "verification": {
      k: (v / files_parsed if files_parsed > 0 else 0.0)
      for k, v in verification_parts.items()
    },
    "workflow": {
      k: (v / files_parsed if files_parsed > 0 else 0.0)
      for k, v in workflow_parts.items()
    },
  }
  group_share_percent = {
    k: ((v * 100.0 / total_selected_calls) if total_selected_calls > 0 else 0.0)
    for k, v in group_totals.items()
  }
  tool_share_percent_overall = {
    "context": {
      k: ((v * 100.0 / total_selected_calls) if total_selected_calls > 0 else 0.0)
      for k, v in context_parts.items()
    },
    "verification": {
      k: ((v * 100.0 / total_selected_calls) if total_selected_calls > 0 else 0.0)
      for k, v in verification_parts.items()
    },
    "workflow": {
      k: ((v * 100.0 / total_selected_calls) if total_selected_calls > 0 else 0.0)
      for k, v in workflow_parts.items()
    },
  }
  tool_share_in_group_percent = {
    "context": {
      k: ((v * 100.0 / group_totals["context"]) if group_totals["context"] > 0 else 0.0)
      for k, v in context_parts.items()
    },
    "verification": {
      k: (
        (v * 100.0 / group_totals["verification"])
        if group_totals["verification"] > 0
        else 0.0
      )
      for k, v in verification_parts.items()
    },
    "workflow": {
      k: (
        (v * 100.0 / group_totals["workflow"]) if group_totals["workflow"] > 0 else 0.0
      )
      for k, v in workflow_parts.items()
    },
  }
  group_avg_share_percent = {
    k: (
      group_share_sum_percent[k] / files_with_selected_calls
      if files_with_selected_calls > 0
      else 0.0
    )
    for k in group_share_sum_percent
  }
  tool_avg_share_percent = {
    "context": {
      k: (
        tool_share_sum_percent["context"][k] / files_with_selected_calls
        if files_with_selected_calls > 0
        else 0.0
      )
      for k in tool_share_sum_percent["context"]
    },
    "verification": {
      k: (
        tool_share_sum_percent["verification"][k] / files_with_selected_calls
        if files_with_selected_calls > 0
        else 0.0
      )
      for k in tool_share_sum_percent["verification"]
    },
    "workflow": {
      k: (
        tool_share_sum_percent["workflow"][k] / files_with_selected_calls
        if files_with_selected_calls > 0
        else 0.0
      )
      for k in tool_share_sum_percent["workflow"]
    },
  }

  summary = {
    "results_dir": str(results_dir),
    "files_found": files_found,
    "files_parsed": files_parsed,
    "files_skipped": files_skipped,
    "total_selected_tool_calls": total_selected_calls,
    "tool_calls": {
      "context": context_parts,
      "verification": verification_parts,
      "workflow": workflow_parts,
    },
    "group_totals": group_totals,
    "averages": {
      "files_parsed": files_parsed,
      "files_with_selected_calls": files_with_selected_calls,
      "selected_tool_calls_per_file": (
        total_selected_calls / files_parsed if files_parsed > 0 else 0.0
      ),
      "group_calls_per_file": group_avg_calls_per_file,
      "tool_calls_per_file": tool_avg_calls_per_file,
    },
    "share_percent": {
      "group_overall": group_share_percent,
      "tool_overall": tool_share_percent_overall,
      "tool_within_group": tool_share_in_group_percent,
      "group_avg_across_files": group_avg_share_percent,
      "tool_avg_across_files": tool_avg_share_percent,
    },
  }

  args.output_json.parent.mkdir(parents=True, exist_ok=True)
  with args.output_json.open("w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

  try:
    import matplotlib.pyplot as plt
  except ImportError as exc:
    raise SystemExit(
      "matplotlib is required for plotting. Install it with: pip install matplotlib"
    ) from exc

  plt.rcParams.update(
    {
      "font.size": 12,
      "axes.titlesize": 12,
      "axes.labelsize": 12,
    }
  )

  fig, ax = plt.subplots(figsize=(7.2, 3.6))
  label_fontsize = 12
  axis_fontsize = 12
  tick_fontsize = 12
  base_face = "#E2EFFF"
  base_edge = "#1D73DD"
  hatch_by_label = {
    "search": "",
    "langref": "xx",
    "trans": "",
    "difftest": "xx",
    "verify": "//",
    "workflow": "",
  }

  # Context: stacked horizontal bar.
  left = 0
  langref_center = None
  langref_value = 0
  for key in ["search", "langref"]:
    val = context_parts[key]
    if val > 0 and key == "search":
      ax.text(
        left + val / 2,
        "context",
        "search",
        ha="center",
        va="center",
        fontsize=label_fontsize,
      )
    if key == "langref":
      langref_center = left + val / 2
      langref_value = val
    left += val

  if langref_value > 0 and langref_center is not None:
    ax.annotate(
      "langref",
      xy=(langref_center, 0.0),
      xytext=(langref_center + 500, 0.14),
      textcoords="data",
      ha="left",
      va="bottom",
      fontsize=label_fontsize,
      arrowprops={"arrowstyle": "-", "color": base_edge, "lw": 1.0},
    )

  # Verification: stacked horizontal bar.
  left = 0
  for key in ["trans", "difftest", "verify"]:
    val = verification_parts[key]
    ax.barh(
      "verification",
      val,
      left=left,
      color=base_face,
      edgecolor=base_edge,
      alpha=0.9,
      linewidth=1.4,
      hatch=hatch_by_label[key],
      label=key,
      height=0.5,
    )
    if val > 0:
      ax.text(
        left + val / 2,
        "verification",
        f"{key}",
        ha="center",
        va="center",
        fontsize=label_fontsize,
      )
    left += val

  # Workflow: single horizontal bar (aggregated from three tools).
  workflow_total = group_totals["workflow"]
  ax.barh(
    "workflow",
    workflow_total,
    color=base_face,
    edgecolor=base_edge,
    alpha=0.9,
    linewidth=1.4,
    hatch=hatch_by_label["workflow"],
    label="workflow",
    height=0.5,
  )
  if workflow_total > 0:
    ax.text(
      workflow_total / 2,
      "workflow",
      "workflow",
      ha="center",
      va="center",
      fontsize=label_fontsize,
    )

  ax.set_xlabel("Calls", fontsize=axis_fontsize)
  ax.set_ylabel("")
  ax.tick_params(axis="both", labelsize=tick_fontsize)
  ax.set_axisbelow(True)

  # Keep left/bottom, remove only top/right frame as requested.
  ax.spines["top"].set_visible(False)
  ax.spines["right"].set_visible(False)

  # No numeric labels and no legend as requested.

  plt.tight_layout()
  args.output_png.parent.mkdir(parents=True, exist_ok=True)
  args.output_pdf.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(args.output_png, dpi=200)
  plt.savefig(args.output_pdf)
  plt.close(fig)

  print(f"Results dir: {results_dir}")
  print(f"JSON files found: {files_found}")
  print(f"Stats files parsed: {files_parsed}")
  print(f"Skipped files: {files_skipped}")
  print(f"Saved stats JSON to: {args.output_json}")
  print(f"Saved bar chart PNG to: {args.output_png}")
  print(f"Saved bar chart PDF to: {args.output_pdf}")
  print("context:")
  print(f"  search: {context_parts['search']}")
  print(f"  langref: {context_parts['langref']}")
  print("verification:")
  print(f"  trans: {verification_parts['trans']}")
  print(f"  difftest: {verification_parts['difftest']}")
  print(f"  verify: {verification_parts['verify']}")
  print("workflow:")
  print(f"  tests_manager: {workflow_parts['tests_manager']}")
  print(f"  stop: {workflow_parts['stop']}")
  print(f"  review: {workflow_parts['review']}")


if __name__ == "__main__":
  main()
