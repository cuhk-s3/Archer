#!/usr/bin/env python3
"""Generate an UpSet-style plot for overlap of Gemini/DeepSeek/Qwen findings."""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import gridspec

MODEL_ORDER = ["Gemini-3.1-Pro", "DeepSeek-V3.2", "Qwen3.5-Plus"]
HATCH_BY_MASK = {
  (True, False, False): "",
  (True, True, False): "..",
  (True, False, True): "xx",
  (True, True, True): "///",
}


def extract_base_findings():
  """Extract which bugs were found by each base model."""
  csv_path = Path(__file__).parent / "results.csv"

  gemini_found = set()
  deepseek_found = set()
  qwen_found = set()

  with csv_path.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
      issue_id = row["Issue ID"]

      if row.get("Gemini", "").strip() == "Found":
        gemini_found.add(issue_id)

      if row.get("DeepSeek", "").strip() == "Found":
        deepseek_found.add(issue_id)

      if row.get("Qwen", "").strip() == "Found":
        qwen_found.add(issue_id)

  return gemini_found, deepseek_found, qwen_found


def build_intersection_counts(gemini_found, deepseek_found, qwen_found):
  """Build aggregated intersection counts keyed by membership tuple (G, D, Q)."""
  all_issues = sorted(gemini_found | deepseek_found | qwen_found)
  counts: dict[tuple[bool, bool, bool], int] = {}

  for issue_id in all_issues:
    mask = (
      issue_id in gemini_found,
      issue_id in deepseek_found,
      issue_id in qwen_found,
    )
    counts[mask] = counts.get(mask, 0) + 1

  ordered = sorted(
    counts.items(),
    key=lambda kv: (kv[1], sum(kv[0]), kv[0]),
    reverse=True,
  )
  return ordered


def print_region_summary(ordered_counts):
  print("\nIntersection counts:")
  print("  G D Q : count")
  for (g, d, q), cnt in ordered_counts:
    print(f"  {int(g)} {int(d)} {int(q)} : {cnt}")


def main():
  gemini_found, deepseek_found, qwen_found = extract_base_findings()

  print(f"Gemini base found: {len(gemini_found)} bugs")
  print(f"DeepSeek base found: {len(deepseek_found)} bugs")
  print(f"Qwen base found: {len(qwen_found)} bugs")

  ordered_counts = build_intersection_counts(
    gemini_found,
    deepseek_found,
    qwen_found,
  )
  print(
    f"Universe size (union): {len(gemini_found | deepseek_found | qwen_found)} issues"
  )
  print_region_summary(ordered_counts)

  plt.rcParams.update(
    {
      "font.size": 12,
      "axes.titlesize": 12,
      "axes.labelsize": 12,
    }
  )

  # Keep canvas compact to avoid excessive blank space.
  fig_width = max(4.3, 3.0 + 0.48 * len(ordered_counts))
  fig = plt.figure(figsize=(fig_width, 4.2), facecolor="white")
  gs = gridspec.GridSpec(2, 1, height_ratios=[2.9, 1.35], hspace=0.02)
  ax_bar = fig.add_subplot(gs[0])
  ax_matrix = fig.add_subplot(gs[1], sharex=ax_bar)

  x_step = 0.46
  x = [i * x_step for i in range(len(ordered_counts))]
  counts = [cnt for _mask, cnt in ordered_counts]

  bars = ax_bar.bar(
    x,
    counts,
    color="#E2EFFF",
    edgecolor="#1D73DD",
    alpha=0.9,
    width=0.24,
    linewidth=1.5,
  )
  for bar, (mask, _cnt) in zip(bars.patches, ordered_counts):
    bar.set_hatch(HATCH_BY_MASK.get(mask, ""))
  ax_bar.set_ylabel("Intersection Size")
  ax_bar.set_xticks([])
  ax_bar.spines["top"].set_visible(False)
  ax_bar.spines["right"].set_visible(False)
  ymax = max(counts) if counts else 1
  ax_bar.set_ylim(0, ymax + 0.8)

  y_positions = {
    "Gemini-3.1-Pro": 2,
    "DeepSeek-V3.2": 1,
    "Qwen3.5-Plus": 0,
  }

  for xi in x:
    for y in y_positions.values():
      ax_matrix.scatter(xi, y, s=60, color="#D9D9D9", zorder=1)

  for xi, (mask, _cnt) in zip(x, ordered_counts):
    ys = []
    for active, model in zip(mask, MODEL_ORDER):
      if active:
        y = y_positions[model]
        ys.append(y)
        ax_matrix.scatter(xi, y, s=60, color="#C55A11", zorder=3)
    if len(ys) >= 2:
      ax_matrix.plot(
        [xi, xi],
        [min(ys), max(ys)],
        color="#C55A11",
        linewidth=1,
        zorder=2,
      )

  ax_matrix.set_yticks([2, 1, 0])
  ax_matrix.set_yticklabels(MODEL_ORDER)
  ax_matrix.set_ylim(-0.45, 2.45)
  if x:
    ax_matrix.set_xlim(x[0] - x_step * 0.45, x[-1] + x_step * 0.45)
  ax_matrix.set_xticks(x)
  ax_matrix.set_xticklabels([""] * len(x))
  ax_matrix.tick_params(axis="x", length=0)
  ax_matrix.spines["top"].set_visible(False)
  ax_matrix.spines["right"].set_visible(False)
  ax_matrix.spines["bottom"].set_visible(False)

  output_dir = Path(__file__).parent / "figures"
  output_dir.mkdir(exist_ok=True)

  png_path = output_dir / "upset_base.png"
  pdf_path = output_dir / "upset_base.pdf"

  fig.subplots_adjust(left=0.26, right=0.99, top=0.995, bottom=0.07)
  fig.savefig(
    png_path, dpi=300, bbox_inches="tight", pad_inches=0.02, facecolor="white"
  )
  fig.savefig(pdf_path, bbox_inches="tight", pad_inches=0.02, facecolor="white")

  print("\nUpSet plot saved to:")
  print(f"  PNG: {png_path}")
  print(f"  PDF: {pdf_path}")

  plt.close(fig)


if __name__ == "__main__":
  main()
