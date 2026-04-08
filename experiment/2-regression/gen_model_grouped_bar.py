#!/usr/bin/env python3
from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator

DISABLED_GROUPS = {}


def normalize_group_name(column: str) -> str:
  lower = column.lower().strip()
  if lower.startswith("gemini"):
    return "Gemini-3.1-Pro"
  if lower.startswith("deepseek"):
    return "DeepSeek-V3.2"
  if lower.startswith("qwen"):
    return "Qwen3.5-Plus"
  if lower.startswith("direct llm"):
    return "Direct"
  if lower.startswith("mini swe agent"):
    return "MSWE"
  if lower.startswith("coderabbit"):
    return "CodeRabbit"
  if lower.startswith("greptile"):
    return "Greptile"
  return column.strip()


def short_variant_name(column: str, group: str) -> str:
  if column == group:
    return "base"
  lower = column.lower().strip()
  if lower.endswith("-wo"):
    return "wo"
  if lower.endswith("-all"):
    return "all"
  if lower.endswith("-rag"):
    return "rag"
  return "base"


def compute_success_rates(
  csv_path: Path,
) -> tuple[list[tuple[str, str, float, int, int]], int]:
  with csv_path.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    columns = [c for c in reader.fieldnames if c != "Issue ID"]
    rows = list(reader)

  total_issues = len(rows)
  stats = []
  for col in columns:
    group = normalize_group_name(col)
    if group in DISABLED_GROUPS:
      continue

    found_count = 0
    for row in rows:
      if row[col].strip().lower() == "found":
        found_count += 1
    rate = (found_count / total_issues) * 100 if total_issues > 0 else 0.0
    variant = short_variant_name(col, group)
    stats.append((group, variant, rate, found_count, total_issues))
  return stats, total_issues


def plot_grouped_chart(
  stats: list[tuple[str, str, float, int, int]], out_png: Path, out_pdf: Path
) -> None:
  grouped: OrderedDict[str, list[tuple[str, float, int, int]]] = OrderedDict()
  for group, variant, rate, found, total in stats:
    grouped.setdefault(group, []).append((variant, rate, found, total))

  # Keep source order but swap Direct/MSWE display positions.
  if "Direct" in grouped and "MSWE" in grouped:
    ordered_groups = list(grouped.keys())
    direct_idx = ordered_groups.index("Direct")
    mswe_idx = ordered_groups.index("MSWE")
    ordered_groups[direct_idx], ordered_groups[mswe_idx] = (
      ordered_groups[mswe_idx],
      ordered_groups[direct_idx],
    )
    grouped = OrderedDict((name, grouped[name]) for name in ordered_groups)

  variant_colors = {
    "base": ("#1D73DD", "#E2EFFF"),
    "wo": ("#1D73DD", "#E2EFFF"),
    "rag": ("#1D73DD", "#E2EFFF"),
    "all": ("#1D73DD", "#E2EFFF"),
  }
  variant_hatches = {
    "base": "",
    "wo": "///",
    "all": "xx",
    "rag": "..",
  }

  bar_width = 0.25
  bar_step = 0.25

  custom_group_gaps = {
    "Gemini-3.1-Pro": 0.25,
    "DeepSeek-V3.2": 0.2,
    "Qwen3.5-Plus": 0.2,
    "CodeRabbit": 0.25,
    "Greptile": 0.25,
    "Optimuzz": 0.25,
    "Direct": 0.2,
    "MSWE": 0.2,
  }
  default_group_gap = 0.24

  x_positions = []
  labels = []
  heights = []
  edge_colors = []
  fill_colors = []
  bar_hatches = []
  group_centers = []

  cursor = 0.0
  for group, items in grouped.items():
    start = cursor
    for variant, _rate, found, _total in items:
      x_positions.append(cursor)
      labels.append(variant)
      heights.append(found)
      edge_color, fill_color = variant_colors.get(variant, ("#777777", "#DDDDDD"))
      edge_colors.append(edge_color)
      fill_colors.append(fill_color)
      bar_hatches.append(variant_hatches.get(variant, ""))
      cursor += bar_step
    end = cursor - bar_step
    group_centers.append((group, (start + end) / 2.0))
    cursor += custom_group_gaps.get(group, default_group_gap)

  fig, ax = plt.subplots(figsize=(5.2, 3.5))

  bars = ax.bar(
    x_positions,
    heights,
    width=bar_width,
    color=fill_colors,
    edgecolor=edge_colors,
    linewidth=1,
  )
  for patch, hatch in zip(bars.patches, bar_hatches):
    patch.set_hatch(hatch)

  max_found = max(heights) if heights else 1
  ax.set_ylabel("Found Cases (#)")
  ax.set_ylim(0, max_found + 2)
  ax.yaxis.set_major_locator(MaxNLocator(integer=True))

  ax.set_xticks(x_positions)
  ax.set_xticklabels([""] * len(x_positions))
  ax.tick_params(axis="x", length=2.5, width=0.8)

  ax.set_axisbelow(True)
  ax.margins(x=0.01)

  ax.spines["top"].set_visible(False)
  ax.spines["right"].set_visible(False)

  for group, center in group_centers:
    ax.text(
      center,
      -0.06,
      group,
      ha="right",
      va="top",
      rotation=23,
      rotation_mode="anchor",
      transform=ax.get_xaxis_transform(),
      fontsize=9,
    )

  legend_elems = [
    Patch(
      facecolor=variant_colors["base"][1],
      edgecolor=variant_colors["base"][0],
      hatch=variant_hatches["base"],
      label="base",
    ),
    Patch(
      facecolor=variant_colors["wo"][1],
      edgecolor=variant_colors["wo"][0],
      hatch=variant_hatches["wo"],
      label="wo",
    ),
    Patch(
      facecolor=variant_colors["all"][1],
      edgecolor=variant_colors["all"][0],
      hatch=variant_hatches["all"],
      label="all",
    ),
    Patch(
      facecolor=variant_colors["rag"][1],
      edgecolor=variant_colors["rag"][0],
      hatch=variant_hatches["rag"],
      label="rag",
    ),
  ]
  ax.legend(
    handles=legend_elems,
    loc="upper right",
    frameon=False,
    borderaxespad=0.4,
    labelspacing=0.4,
    handletextpad=0.6,
  )

  fig.tight_layout()
  fig.subplots_adjust(bottom=0.33, top=0.88, left=0.09, right=0.98)

  out_png.parent.mkdir(parents=True, exist_ok=True)
  fig.savefig(out_png, dpi=300, bbox_inches="tight")
  fig.savefig(out_pdf, bbox_inches="tight")
  plt.close(fig)


def print_summary(stats: list[tuple[str, str, float, int, int]]) -> None:
  print("Model Variant Summary:")
  for group, variant, rate, found, total in stats:
    print(f"- {group:14s} {variant:5s}: {found:2d}/{total:2d} ({rate:5.1f}%)")


if __name__ == "__main__":
  base = Path(__file__).parent
  csv_path = base / "results.csv"
  out_png = base / "figures" / "regression_model_grouped_bar.png"
  out_pdf = base / "figures" / "regression_model_grouped_bar.pdf"

  stats, _total = compute_success_rates(csv_path)
  print_summary(stats)
  plot_grouped_chart(stats, out_png, out_pdf)
  print(f"\nSaved: {out_png}")
  print(f"Saved: {out_pdf}")
