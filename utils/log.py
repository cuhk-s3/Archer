import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import json_repair


@dataclass
class Bug:
  original_ir: str
  transformed_ir: str
  log: str
  thoughts: Optional[str] = None


@dataclass
class RunStats:
  command: dict
  error: Optional[str] = None
  errmsg: Optional[str] = None
  traceback: Optional[str] = None
  input_tokens: int = 0
  output_tokens: int = 0
  cached_tokens: int = 0
  total_tokens: int = 0
  chat_cost: float = 0.0
  chat_rounds: int = 0
  phase1_round: int = 0
  phase2_round: int = 0
  total_time_sec: float = 0.0
  tool_usage: List[dict] = field(default_factory=list)
  strategies: List[dict] = field(
    default_factory=lambda *_, **__: [
      {
        "name": "<not-provided>",
        "target": "<not-provided>",
        "rationale": "<not-provided>",
        "expected_issue": "<not-provided>",
      }
    ]
  )
  reason_thou: str = "<not-provided>"
  bugs: List[Bug] = field(default_factory=list)
  test_traj: List[str] = field(default_factory=list)
  report: Optional[str] = None

  def as_dict(self) -> dict:
    return asdict(self)


def generate_review(pr_info: Any, stats: RunStats) -> str:
  """Generate a markdown review from the PR review results"""
  report_lines = []

  # Title
  report_lines.append(f"# PR Review Report: #{pr_info.pr_id}\n")

  # PR Information
  report_lines.append("## PR Information\n")
  report_lines.append(f"- **Title**: {pr_info.title}")
  report_lines.append(f"- **Author**: {pr_info.author}")
  report_lines.append(f"- **State**: {pr_info.state}")
  report_lines.append(f"- **URL**: {pr_info.pr_url}")
  report_lines.append(f"- **Base Commit**: `{pr_info.base_commit[:10]}`")
  report_lines.append(f"- **Fix Commit**: `{pr_info.fix_commit[:10]}`")
  report_lines.append(f"- **Components**: {', '.join(pr_info.components)}\n")

  # Executive Summary
  report_lines.append("## Executive Summary\n")
  report_lines.append(f"- **Bugs Found**: {len(stats.bugs)}")
  report_lines.append(f"- **Total Time**: {stats.total_time_sec:.2f} seconds")
  report_lines.append(
    f"- **Chat Rounds**: {stats.chat_rounds} (Phase 1: {stats.phase1_round}, Phase 2: {stats.phase2_round})"
  )
  report_lines.append(
    f"- **Tokens Used**: {stats.total_tokens:,} (Input: {stats.input_tokens:,}, Output: {stats.output_tokens:,}, Cached: {stats.cached_tokens:,})"
  )
  report_lines.append(f"- **Estimated Cost**: ${stats.chat_cost:.4f}\n")

  # Test Strategies
  if stats.strategies:
    report_lines.append("## Test Strategies\n")
    for idx, strategy in enumerate(stats.strategies, 1):
      report_lines.append(f"### Strategy {idx}: {strategy['name']}\n")
      report_lines.append(f"- **Target**: {strategy['target']}")
      report_lines.append(f"- **Rationale**: {strategy['rationale']}")
      report_lines.append(f"- **Expected Issue**: {strategy['expected_issue']}\n")

  # Bugs Found
  if stats.bugs:
    report_lines.append("## Bugs Found\n")
    for idx, bug in enumerate(stats.bugs, 1):
      report_lines.append(f"### Bug #{idx}\n")

      if bug.thoughts:
        report_lines.append(f"**Analysis:**\n{bug.thoughts}\n")

      report_lines.append("**Original LLVM IR:**")
      report_lines.append("```llvm")
      report_lines.append(bug.original_ir)
      report_lines.append("```\n")

      report_lines.append("**Transformed LLVM IR:**")
      report_lines.append("```llvm")
      report_lines.append(bug.transformed_ir)
      report_lines.append("```\n")

      report_lines.append("**Verification Log:**")
      report_lines.append("```")
      report_lines.append(bug.log)
      report_lines.append("```\n")
  else:
    report_lines.append("## Bugs Found\n")
    report_lines.append("No bugs were found during the review.\n")

  # Agent Report
  if stats.report:
    report_lines.append("## Agent Review\n")
    parsed_report = None
    if isinstance(stats.report, str):
      try:
        parsed_report = json_repair.loads(stats.report)
      except Exception:
        parsed_report = None

    if isinstance(parsed_report, dict):
      test_payload = parsed_report.get("test")
      if isinstance(test_payload, list) and len(test_payload) >= 2:
        report_lines.append("### Reproducer\n")
        report_lines.append("**LLVM IR:**")
        ir_text = test_payload[0]
        if isinstance(ir_text, str):
          if ir_text.strip().startswith("```"):
            report_lines.append(ir_text.strip())
          else:
            report_lines.append("```llvm")
            report_lines.append(ir_text.strip())
            report_lines.append("```")
        report_lines.append("")
        report_lines.append("**Command:**")
        report_lines.append("```bash")
        report_lines.append(str(test_payload[1]).strip())
        report_lines.append("```\n")

      args_text = parsed_report.get("args")
      if args_text is not None:
        report_lines.append(f"- **Args**: `{args_text}`")

      force_flag = parsed_report.get("force")
      if force_flag is not None:
        report_lines.append(f"- **Force Stop**: {force_flag}")

      thoughts_text = parsed_report.get("thoughts")
      if thoughts_text:
        report_lines.append("\n### Analysis\n")
        report_lines.append(thoughts_text.strip())
        report_lines.append("\n")
    else:
      report_lines.append(str(stats.report))
      report_lines.append("\n")

  # Tool Usage Statistics
  if stats.tool_usage:
    report_lines.append("## Tool Usage\n")
    report_lines.append("| Tool | Usage Count |")
    report_lines.append("|------|-------------|")
    for tool in stats.tool_usage:
      report_lines.append(f"| {tool['name']} | {tool['usage']} |")
    report_lines.append("\n")

  # Errors (if any)
  if stats.error:
    report_lines.append("## Errors\n")
    report_lines.append(f"**Error Type**: {stats.error}\n")
    report_lines.append(f"**Error Message**: {stats.errmsg}\n")
    if stats.traceback:
      report_lines.append("**Traceback:**")
      report_lines.append("```")
      report_lines.append(stats.traceback)
      report_lines.append("```\n")

  return "\n".join(report_lines)


def collect_agent_stats(stats: RunStats, agent) -> None:
  """Populate stats with token/round/tool-usage data from the agent."""
  stats.chat_rounds = agent.chat_stats["chat_rounds"]
  stats.input_tokens = agent.chat_stats["input_tokens"]
  stats.output_tokens = agent.chat_stats["output_tokens"]
  stats.cached_tokens = agent.chat_stats["cached_tokens"]
  stats.total_tokens = agent.chat_stats["total_tokens"]
  stats.chat_cost = agent.chat_stats["total_cost"]

  # Source of truth: full chat history (covers both phases and removed tools such as `stop`).
  history_usage = {}
  for message in agent.get_history():
    if getattr(message, "type", None) != "function_call":
      continue
    tool_name = getattr(message, "name", None)
    if not tool_name:
      continue
    history_usage[tool_name] = history_usage.get(tool_name, 0) + 1

  # Keep currently registered tools in output even if their usage is zero.
  all_tool_names = set(agent.tools.list(ignore_budget=True)) | set(history_usage.keys())
  stats.tool_usage = [
    {"name": name, "usage": history_usage.get(name, 0)}
    for name in sorted(all_tool_names)
  ]


def save_outputs(
  stats: RunStats,
  pr_info: Any,
  agent,
  console,
  stats_path: Optional[Path],
  history_path: Optional[Path],
  review_path: Optional[Path],
) -> None:
  """Write stats JSON, chat history JSON, and review Markdown to disk."""
  if stats_path:
    with stats_path.open("w") as fout:
      json.dump(stats.as_dict(), fout, indent=2)
    console.print(f"Generation statistics saved to {stats_path}.")

  if history_path:
    with history_path.open("w") as fout:
      json.dump([asdict(m) for m in agent.get_history()], fout, indent=2)
    console.print(f"Chat history saved to {history_path}.")

  if review_path:
    review_content = generate_review(pr_info, stats)
    with review_path.open("w", encoding="utf-8") as fout:
      fout.write(review_content)
    console.print(f"Review saved to {review_path}.")


def print_results(stats: RunStats, console) -> None:
  """Print a human-readable summary of the run to the console."""
  console.print("Bugs Found")
  console.print("----------")
  for idx, bug in enumerate(stats.bugs):
    console.print(f"Bug #{idx + 1}:")
    if bug.thoughts:
      console.print("Thoughts:")
      console.print(bug.thoughts)
    console.print("Original LLVM IR:")
    console.print(bug.original_ir)
    console.print("Transformed LLVM IR:")
    console.print(bug.transformed_ir)
    console.print("Verification Log:")
    console.print(bug.log)
    console.print("----------")
  console.print("Report")
  console.print("----------")
  console.print(stats.report)
  console.print("Statistics")
  console.print("----------")
  console.print(json.dumps(stats.as_dict(), indent=2))
