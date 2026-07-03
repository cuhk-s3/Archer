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
  if lower.startswith("codex"):
    return "Codex"
  if lower.startswith("copilot"):
    return "Copilot"
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
  stats: list[tuple[str, str, float, int, int]],
  out_png: Path,
  out_pdf: Path,
  *,
  figsize: tuple[float, float] = (5.2, 3.5),
  bar_width: float = 0.25,
  bar_step: float = 0.25,
  default_group_gap: float = 0.24,
  group_gaps: dict[str, float] | None = None,
  show_legend: bool = True,
  group_label_rotation: float = 23,
  group_label_fontsize: float = 9,
  group_label_y: float = -0.06,
) -> None:
  grouped: OrderedDict[str, list[tuple[str, float, int, int]]] = OrderedDict()
  for group, variant, rate, found, total in stats:
    grouped.setdefault(group, []).append((variant, rate, found, total))

  ordered_groups = list(grouped.keys())

  # Put Codex/Copilot immediately before CodeRabbit in the commercial-tools block.
  commercial_front = [name for name in ["Codex", "Copilot"] if name in grouped]
  if commercial_front and "CodeRabbit" in grouped:
    ordered_groups = [name for name in ordered_groups if name not in commercial_front]
    coderabbit_idx = ordered_groups.index("CodeRabbit")
    ordered_groups[coderabbit_idx:coderabbit_idx] = commercial_front

  # Keep MSWE before Direct when both are shown.
  if "Direct" in ordered_groups and "MSWE" in ordered_groups:
    direct_idx = ordered_groups.index("Direct")
    mswe_idx = ordered_groups.index("MSWE")
    if direct_idx < mswe_idx:
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

  custom_group_gaps = {
    "Gemini-3.1-Pro": 0.25,
    "DeepSeek-V3.2": 0.2,
    "Qwen3.5-Plus": 0.2,
    "Codex": 0.25,
    "Copilot": 0.25,
    "CodeRabbit": 0.25,
    "Greptile": 0.25,
    "Optimuzz": 0.25,
    "Direct": 0.2,
    "MSWE": 0.2,
  }
  if group_gaps:
    custom_group_gaps.update(group_gaps)

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

  fig, ax = plt.subplots(figsize=figsize)

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
      group_label_y,
      group,
      ha="center" if group_label_rotation == 0 else "right",
      va="top",
      rotation=group_label_rotation,
      rotation_mode="anchor",
      transform=ax.get_xaxis_transform(),
      fontsize=group_label_fontsize,
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
  if show_legend:
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


def filter_stats(
  stats: list[tuple[str, str, float, int, int]],
  groups: list[str],
) -> list[tuple[str, str, float, int, int]]:
  group_order = {group: idx for idx, group in enumerate(groups)}
  selected = [item for item in stats if item[0] in group_order]
  return sorted(selected, key=lambda item: group_order[item[0]])


def with_aegis_reference(
  stats: list[tuple[str, str, float, int, int]],
) -> list[tuple[str, str, float, int, int]]:
  aegis = [
    ("Archer", variant, rate, found, total)
    for group, variant, rate, found, total in stats
    if group == "Gemini-3.1-Pro" and variant == "base"
  ]
  comparison_groups = [
    "Codex",
    "Copilot",
    "CodeRabbit",
    "Greptile",
    "Optimuzz",
    "MSWE",
    "Direct",
  ]
  return aegis + filter_stats(stats, comparison_groups)


def plot_split_charts(
  stats: list[tuple[str, str, float, int, int]], figures_dir: Path
) -> None:
  model_stats = filter_stats(stats, ["Gemini-3.1-Pro", "DeepSeek-V3.2", "Qwen3.5-Plus"])
  comparison_stats = with_aegis_reference(stats)

  plot_grouped_chart(
    model_stats,
    figures_dir / "regression_model_backbones_bar.png",
    figures_dir / "regression_model_backbones_bar.pdf",
    figsize=(3.35, 2.9),
    bar_width=0.16,
    bar_step=0.18,
    default_group_gap=0.12,
    group_gaps={
      "Gemini-3.1-Pro": 0.12,
      "DeepSeek-V3.2": 0.10,
      "Qwen3.5-Plus": 0.10,
    },
    group_label_rotation=0,
    group_label_fontsize=8.2,
    group_label_y=-0.08,
  )
  plot_grouped_chart(
    comparison_stats,
    figures_dir / "regression_tool_baselines_bar.png",
    figures_dir / "regression_tool_baselines_bar.pdf",
    figsize=(3.25, 2.7),
    bar_width=0.12,
    bar_step=0.14,
    default_group_gap=0.01,
    group_gaps={
      "Archer": 0.02,
      "Codex": 0.01,
      "Copilot": 0.01,
      "CodeRabbit": 0.01,
      "Greptile": 0.01,
      "Optimuzz": 0.01,
      "MSWE": 0.01,
      "Direct": 0.01,
    },
    show_legend=False,
    group_label_fontsize=8.0,
  )


def print_summary(stats: list[tuple[str, str, float, int, int]]) -> None:
  print("Model Variant Summary:")
  for group, variant, rate, found, total in stats:
    print(f"- {group:14s} {variant:5s}: {found:2d}/{total:2d} ({rate:5.1f}%)")


if __name__ == "__main__":
  base = Path(__file__).parent
  csv_path = base / "results.csv"
  out_png = base / "figures" / "regression_model_grouped_bar.png"
  out_pdf = base / "figures" / "regression_model_grouped_bar.pdf"
  figures_dir = base / "figures"

  stats, _total = compute_success_rates(csv_path)
  print_summary(stats)
  plot_grouped_chart(stats, out_png, out_pdf)
  plot_split_charts(stats, figures_dir)
  print(f"\nSaved: {out_png}")
  print(f"Saved: {out_pdf}")
  for split_name in ["regression_model_backbones_bar", "regression_tool_baselines_bar"]:
    print(f"Saved: {figures_dir / f'{split_name}.png'}")
    print(f"Saved: {figures_dir / f'{split_name}.pdf'}")
