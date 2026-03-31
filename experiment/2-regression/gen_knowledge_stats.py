#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt

BLUE_EDGE = "#1D73DD"
BLUE_FILL = "#E2EFFF"


def read_text_len(path: Path) -> int:
  if not path.exists():
    return 0
  return len(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict:
  with path.open("r", encoding="utf-8") as f:
    return json.load(f)


def component_knowledge_len(issue_data: dict, knowledge_dir: Path) -> int:
  components = issue_data.get("history", {}).get("components", [])
  total = 0
  for comp in components:
    total += read_text_len(knowledge_dir / f"{comp}.md")
  return total


def rag_knowledge_len(
  issue_id: str, rag_result_dir: Path, rag_dataset_dir: Path
) -> int:
  result_path = rag_result_dir / f"{issue_id}.json"
  if not result_path.exists():
    return 0

  result = load_json(result_path)
  rag_retrieval = result.get("rag_retrieval", {})
  matches = rag_retrieval.get("matches", [])

  total = 0
  for m in matches:
    matched_id = str(m.get("id", m.get("bug_id", ""))).strip()
    if not matched_id:
      continue
    rag_issue_path = rag_dataset_dir / f"{matched_id}.json"
    if not rag_issue_path.exists():
      continue
    rag_issue = load_json(rag_issue_path)
    total += len(rag_issue.get("patch", ""))
  return total


def collect_lengths(base: Path) -> tuple[list[int], list[int], list[int], list[str]]:
  dataset_dir = base / "dataset"
  summary_non_reg = base.parent / "1-pass-knowledge" / "summary" / "non-regression"
  summary_passes_non_reg = (
    base.parent / "1-pass-knowledge" / "summary" / "passes-non-regression"
  )
  rag_result_dir = base / "results" / "archer-deepseek-chat-rag"
  rag_dataset_dir = base / "dataset-regression-rag"

  issue_files = sorted(dataset_dir.glob("*.json"))

  by_component = []
  by_rag = []
  by_all = []
  issue_ids = []

  for issue_path in issue_files:
    issue = load_json(issue_path)
    issue_id = str(issue.get("bug_id", issue_path.stem))

    by_component.append(component_knowledge_len(issue, summary_non_reg))
    by_all.append(component_knowledge_len(issue, summary_passes_non_reg))
    by_rag.append(rag_knowledge_len(issue_id, rag_result_dir, rag_dataset_dir))
    issue_ids.append(issue_id)

  return by_component, by_rag, by_all, issue_ids


def plot_boxplot(
  component_vals: list[int],
  rag_vals: list[int],
  all_vals: list[int],
  out_dir: Path,
) -> None:
  out_dir.mkdir(parents=True, exist_ok=True)

  fig, (ax_top, ax_bottom) = plt.subplots(
    2,
    1,
    sharex=True,
    figsize=(4.6, 4.0),
    gridspec_kw={"height_ratios": [1.0, 2.2], "hspace": 0.12},
  )
  fig = cast(Any, fig)
  ax_top = cast(Any, ax_top)
  ax_bottom = cast(Any, ax_bottom)

  positions = [1.0, 1.6, 2.2]
  box_kwargs = {
    "positions": positions,
    "widths": 0.24,
    "patch_artist": True,
    "showmeans": True,
    "meanline": True,
    "boxprops": {"facecolor": BLUE_FILL, "edgecolor": BLUE_EDGE, "linewidth": 1.4},
    "whiskerprops": {"color": BLUE_EDGE, "linewidth": 1.2},
    "capprops": {"color": BLUE_EDGE, "linewidth": 1.2},
    "medianprops": {"color": BLUE_EDGE, "linewidth": 1.4},
    "meanprops": {
      "color": BLUE_EDGE,
      "linewidth": 1.5,
      "linestyle": "-",
    },
    "flierprops": {
      "marker": "o",
      "markerfacecolor": BLUE_EDGE,
      "markeredgecolor": BLUE_EDGE,
      "markersize": 3,
      "alpha": 0.65,
    },
  }

  data = [component_vals, rag_vals, all_vals]
  ax_top.boxplot(data, **box_kwargs)
  ax_bottom.boxplot(data, **box_kwargs)

  ax_bottom.set_ylabel("Knowledge Length (chars)")
  ax_bottom.set_xlim(0.75, 2.45)
  ax_bottom.set_ylim(0, 30000)
  ax_top.set_ylim(80000, 140000)
  ax_bottom.tick_params(axis="y", pad=2)
  ax_top.tick_params(axis="y", pad=2)

  ax_top.spines["bottom"].set_visible(False)
  ax_top.spines["top"].set_visible(False)
  ax_bottom.spines["top"].set_visible(False)
  ax_top.spines["right"].set_visible(False)
  ax_bottom.spines["right"].set_visible(False)

  ax_top.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
  ax_bottom.set_xticks(positions)
  ax_bottom.set_xticklabels(["Base", "RAG", "All"])

  ax_top.grid(False)
  ax_bottom.grid(False)

  d = 0.012
  kwargs_top = {
    "transform": ax_top.transAxes,
    "color": BLUE_EDGE,
    "clip_on": False,
    "linewidth": 1.1,
  }
  kwargs_bottom = {
    "transform": ax_bottom.transAxes,
    "color": BLUE_EDGE,
    "clip_on": False,
    "linewidth": 1.1,
  }
  ax_top.plot((-d, +d), (-d, +d), **kwargs_top)
  ax_top.plot((1 - d, 1 + d), (-d, +d), **kwargs_top)
  ax_bottom.plot((-d, +d), (1 - d, 1 + d), **kwargs_bottom)
  ax_bottom.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs_bottom)

  fig.subplots_adjust(left=0.16, right=0.98, bottom=0.14, top=0.98)
  png_path = out_dir / "knowledge_length_boxplot.png"
  pdf_path = out_dir / "knowledge_length_boxplot.pdf"
  fig.savefig(png_path, dpi=300, bbox_inches="tight")
  fig.savefig(pdf_path, bbox_inches="tight")
  plt.close(fig)

  print(f"Saved: {png_path}")
  print(f"Saved: {pdf_path}")


def print_summary(name: str, values: list[int]) -> None:
  n = len(values)
  if n == 0:
    print(f"{name:10s} n=0")
    return
  values_sorted = sorted(values)
  avg = sum(values) / n
  if n % 2 == 1:
    mid = float(values_sorted[n // 2])
  else:
    mid = (values_sorted[n // 2 - 1] + values_sorted[n // 2]) / 2
  print(
    f"{name:10s} n={n:2d} min={values_sorted[0]:6d} median={mid:8.1f} mean={avg:8.1f} max={values_sorted[-1]:6d}"
  )


def main() -> None:
  base = Path(__file__).parent
  component_vals, rag_vals, all_vals, issue_ids = collect_lengths(base)

  print(f"Total issues: {len(issue_ids)}")
  print_summary("Base", component_vals)
  print_summary("RAG", rag_vals)
  print_summary("All", all_vals)

  plot_boxplot(component_vals, rag_vals, all_vals, base / "figures")


if __name__ == "__main__":
  main()
