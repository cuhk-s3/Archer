#!/usr/bin/env python3
"""
Generate a Venn diagram showing the overlap of bugs found by Gemini, DeepSeek, and Qwen base models.
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib_venn import venn3, venn3_circles


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


def shift_label(venn, region_id: str, dx: float = 0.0, dy: float = 0.0):
  """Shift a subset label by (dx, dy) in data coordinates."""
  label = venn.get_label_by_id(region_id)
  if label is not None:
    x, y = label.get_position()
    label.set_position((x + dx, y + dy))


def main():
  gemini_found, deepseek_found, qwen_found = extract_base_findings()

  print(f"Gemini base found: {len(gemini_found)} bugs")
  print(f"DeepSeek base found: {len(deepseek_found)} bugs")
  print(f"Qwen base found: {len(qwen_found)} bugs")

  # Create Venn diagram
  fig, ax = plt.subplots(figsize=(6.6, 6.1))
  fig.patch.set_facecolor("white")
  ax.set_facecolor("white")

  venn = venn3(
    [gemini_found, deepseek_found, qwen_found],
    set_labels=("", "", ""),
    set_colors=("#4E79A7", "#E15759", "#59A14F"),
    alpha=0.58,
    ax=ax,
  )

  circles = venn3_circles(
    [gemini_found, deepseek_found, qwen_found],
    ax=ax,
    linewidth=1.8,
    color="#4A4A4A",
    linestyle="solid",
  )

  # Remove patch edges; keep only circle outlines.
  for patch in venn.patches:
    if patch:
      patch.set_edgecolor("none")

  # Style numbers.
  for text in venn.subset_labels:
    if text:
      text.set_fontsize(24)
      # text.set_fontweight("bold")
      text.set_color("black")

  # Region ids:
  # 100 = Gemini only
  # 010 = DeepSeek only
  # 001 = Qwen only
  # 110 = Gemini & DeepSeek only
  # 101 = Gemini & Qwen only
  # 011 = DeepSeek & Qwen only
  # 111 = all three

  # Manually adjust label positions for cleaner placement.
  shift_label(venn, "100", dx=-0.05, dy=0.02)  # 10
  shift_label(venn, "010", dx=0.08, dy=0.08)  # 1
  shift_label(venn, "001", dx=-0.05, dy=-0.10)  # 2
  shift_label(venn, "111", dx=0.02, dy=-0.01)  # 5

  legend_handles = [
    Patch(facecolor="#4E79A7", edgecolor="#4A4A4A", alpha=0.58, label="Gemini-3.1-Pro"),
    Patch(facecolor="#E15759", edgecolor="#4A4A4A", alpha=0.58, label="DeepSeek-V3.2"),
    Patch(facecolor="#59A14F", edgecolor="#4A4A4A", alpha=0.58, label="Qwen3.5-Plus"),
  ]
  # ax.legend(
  #     handles=legend_handles,
  #     loc="upper center",
  #     bbox_to_anchor=(0.5, 0.05),
  #     ncol=3,
  #     frameon=False,
  #     fontsize=18,
  #     handlelength=1.8,
  #     columnspacing=1.8,
  # )

  ax.legend(
    handles=legend_handles,
    loc="upper right",
    bbox_to_anchor=(1.5, 1.00),
    ncol=1,
    frameon=False,
    fontsize=18,
    handlelength=1.8,
    labelspacing=0.8,
    borderaxespad=0.2,
  )

  # Tighten the visible area so the circles fill the figure more naturally.
  all_centers_x = [c.center[0] for c in circles]
  all_centers_y = [c.center[1] for c in circles]
  all_radii = [c.radius for c in circles]

  xmin = min(x - r for x, r in zip(all_centers_x, all_radii))
  xmax = max(x + r for x, r in zip(all_centers_x, all_radii))
  ymin = min(y - r for y, r in zip(all_centers_y, all_radii))
  ymax = max(y + r for y, r in zip(all_centers_y, all_radii))

  xpad = (xmax - xmin) * 0.04
  ypad_top = (ymax - ymin) * 0.04
  ypad_bottom = (ymax - ymin) * 0.10

  ax.set_xlim(xmin - xpad, xmax + xpad)
  ax.set_ylim(ymin - ypad_bottom, ymax + ypad_top)

  ax.set_title("")
  ax.set_axis_off()

  plt.subplots_adjust(left=0.04, right=0.96, top=0.97, bottom=0.10)

  output_dir = Path(__file__).parent / "figures"
  output_dir.mkdir(exist_ok=True)

  png_path = output_dir / "venn_diagram_base.png"
  pdf_path = output_dir / "venn_diagram_base.pdf"

  fig.savefig(png_path, dpi=300, bbox_inches="tight")
  fig.savefig(pdf_path, bbox_inches="tight")

  print("\nVenn diagram saved to:")
  print(f"  PNG: {png_path}")
  print(f"  PDF: {pdf_path}")

  plt.close(fig)


if __name__ == "__main__":
  main()
