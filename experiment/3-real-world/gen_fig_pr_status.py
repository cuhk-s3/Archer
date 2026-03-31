#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import MaxNLocator


def parse_args() -> argparse.Namespace:
  root = Path(__file__).resolve().parents[2]
  parser = argparse.ArgumentParser(
    description="Generate PR patch-size and test-count histograms."
  )
  parser.add_argument(
    "--dataset-dir",
    type=Path,
    default=root / "dataset",
    help="Path to dataset directory (default: <repo>/dataset).",
  )
  parser.add_argument(
    "--output-png",
    type=Path,
    default=root / "record" / "pr_patch_test_hist.png",
    help="Output PNG path (default: <repo>/record/pr_patch_test_hist.png).",
  )
  parser.add_argument(
    "--output-pdf",
    type=Path,
    default=root / "record" / "pr_patch_test_hist.pdf",
    help="Output PDF path (default: <repo>/record/pr_patch_test_hist.pdf).",
  )
  parser.add_argument(
    "--show",
    action="store_true",
    help="Display the figure window after saving.",
  )
  return parser.parse_args()


def count_changed_lines_from_patch(patch: str) -> int:
  if not isinstance(patch, str) or not patch:
    return 0

  changed = 0
  for line in patch.splitlines():
    # Unified diff file headers start with +++/--- and are not code changes.
    if line.startswith("+++") or line.startswith("---"):
      continue
    if line.startswith("+") or line.startswith("-"):
      changed += 1
  return changed


def count_tests(item: dict) -> int:
  tests = item.get("tests", [])
  if not isinstance(tests, list):
    return 0

  total = 0
  for entry in tests:
    subtests = entry.get("tests", []) if isinstance(entry, dict) else []
    if isinstance(subtests, list) and subtests:
      total += len(subtests)
    elif isinstance(entry, dict):
      # Fallback for records without a nested test list.
      total += 1
  return total


def load_pr_records(dataset_dir: Path) -> list[dict]:
  records: list[dict] = []
  for state in ("open", "closed"):
    state_dir = dataset_dir / state
    if not state_dir.exists():
      continue
    for file in sorted(state_dir.glob("*.json")):
      with file.open("r", encoding="utf-8") as f:
        records.append(json.load(f))
  return records


def main() -> None:
  args = parse_args()
  dataset_dir = args.dataset_dir.resolve()
  if not dataset_dir.exists() or not dataset_dir.is_dir():
    raise SystemExit(f"Invalid dataset directory: {dataset_dir}")

  records = load_pr_records(dataset_dir)
  patch_changed_lines = [
    count_changed_lines_from_patch(item.get("patch", "")) for item in records
  ]
  test_counts = [count_tests(item) for item in records]

  PATCH_TAIL_THRESHOLD = 300
  TEST_TAIL_THRESHOLD = 90

  patch_plot_values = [min(v, PATCH_TAIL_THRESHOLD) for v in patch_changed_lines]
  test_plot_values = [min(v, TEST_TAIL_THRESHOLD) for v in test_counts]

  print("Dataset dir:", dataset_dir)
  print("Total number of PRs:", len(records))
  avg_patch = (
    sum(patch_changed_lines) / len(patch_changed_lines) if patch_changed_lines else 0
  )
  print(f"Average number of changed lines per PR: {avg_patch:.2f}")
  avg_tests = sum(test_counts) / len(test_counts) if test_counts else 0
  print(f"Average number of tests per PR: {avg_tests:.2f}")

  # Custom plot settings
  custom_params = {
    "axes.spines.right": False,
    "axes.spines.top": False,
  }
  sns.set_theme(style="white", rc=custom_params, font_scale=4)

  fig, axes = plt.subplots(2, 1, figsize=(22, 18))
  custom_blue = "#E2EFFF"  # Updated color from reference image
  line_blue = "#1D73DD"
  custom_red = "#C55A11"

  # Create histograms
  plot_line = sns.histplot(
    patch_plot_values,
    kde=False,
    bins=range(0, PATCH_TAIL_THRESHOLD + 9, 8),
    color=custom_blue,
    alpha=1,
    discrete=False,
    ax=axes[0],
  )
  # Set edge color for top plot
  for patch in axes[0].patches:
    patch.set_edgecolor(line_blue)
    patch.set_linewidth(5)

  plot_branch = sns.histplot(
    test_plot_values,
    kde=False,
    bins=range(0, TEST_TAIL_THRESHOLD + 4, 3),
    color=custom_blue,
    alpha=1,
    discrete=False,
    ax=axes[1],
  )
  # Set edge color for bottom plot
  for patch in axes[1].patches:
    patch.set_edgecolor(line_blue)
    patch.set_linewidth(5)

  plt.subplots_adjust(
    wspace=0.2, hspace=0.5, left=0.20, right=0.93, bottom=0.15, top=0.95
  )

  # Set labels and limits
  plot_line.set(
    xlabel="Patch changed lines per PR",
    ylabel="Frequency",
    xlim=[0, PATCH_TAIL_THRESHOLD + 8],
  )
  plot_line.set_xlabel("Patch changed lines per PR", fontsize=52)
  plot_line.set_ylabel("Frequency", fontsize=68)
  plot_branch.set(
    xlabel="Number of tests per PR",
    ylabel="Frequency",
    xlim=[0, TEST_TAIL_THRESHOLD + 6],
  )
  plot_branch.set_xlabel("Number of tests per PR", fontsize=52)
  plot_branch.set_ylabel("Frequency", fontsize=68)
  axes[0].set_xticks([0, 60, 120, 180, 240, 300])
  axes[0].set_xticklabels(["0", "60", "120", "180", "240", "300+"])
  axes[1].set_xticks([0, 10, 20, 30, 40, 50, 60, 70, 80, 90])
  axes[1].set_xticklabels(["0", "10", "20", "30", "40", "50", "60", "70", "80", "90+"])

  # Use integer y-axis ticks since the dataset size is small.
  axes[0].yaxis.set_major_locator(MaxNLocator(integer=True))
  axes[1].yaxis.set_major_locator(MaxNLocator(integer=True))
  axes[0].grid(False)
  axes[1].grid(False)

  # Draw vertical average lines and labels
  axes[0].axvline(x=avg_patch, color=custom_red, linestyle="--", linewidth=5)
  axes[0].text(
    avg_patch + 1,
    axes[0].get_ylim()[1] * 0.95,
    f"Avg: {avg_patch:.1f} lines",
    color=custom_red,
    fontsize=52,
    verticalalignment="top",
  )

  axes[1].axvline(x=avg_tests, color=custom_red, linestyle="--", linewidth=5)
  axes[1].text(
    avg_tests + 0.5,
    axes[1].get_ylim()[1] * 0.95,
    f"Avg: {avg_tests:.1f} tests",
    color=custom_red,
    fontsize=52,
    verticalalignment="top",
  )

  output_png = args.output_png.resolve()
  output_pdf = args.output_pdf.resolve()
  output_png.parent.mkdir(parents=True, exist_ok=True)
  output_pdf.parent.mkdir(parents=True, exist_ok=True)

  fig.savefig(output_png, dpi=300, transparent=False)
  fig.savefig(output_pdf, transparent=False)
  print(f"Saved PNG to: {output_png}")
  print(f"Saved PDF to: {output_pdf}")

  if args.show:
    plt.show()
  else:
    plt.close(fig)


if __name__ == "__main__":
  main()
