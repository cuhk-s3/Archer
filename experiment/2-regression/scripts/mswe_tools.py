"""Optional function tools for mini-swe-agent."""

import json

from tools.findn import FindNTool
from tools.grepn import GrepNTool
from tools.listn import ListNTool
from tools.readn import ReadNTool
from tools.report import ReportTool
from tools.stop import StopTool
from tools.tests import Test, TestsTool


class ExtraTools:
  def __init__(self, llvm_dir, history_env, stats, *, page_size=250):
    # LangRefTool imports the LLVM environment; defer until a run is configured.
    from tools.langref import LangRefTool

    tests = [
      Test(
        test_name=test.get("test_name", f"test_{index}"),
        test_body=test.get("test_body", ""),
        commands=test_file.get("commands", []),
      )
      for test_file in history_env.get_tests()
      for index, test in enumerate(test_file.get("tests", []))
    ]
    # Explicit allowlist: validation tools must never enter this experiment.
    tools = [
      FindNTool(llvm_dir, page_size),
      GrepNTool(llvm_dir, page_size),
      ListNTool(llvm_dir, page_size),
      ReadNTool(llvm_dir, page_size),
      LangRefTool(history_env),
      TestsTool(tests),
      StopTool(),
      ReportTool(),
    ]
    self.tools = {tool.name(): tool for tool in tools}
    self.stats = stats

  def specs(self):
    specs = [tool.spec().render_in_openai_format() for tool in self.tools.values()]
    # Describe the tools' behavior in this single-agent environment without
    # importing the multi-phase workflow used by other callers of these tools.
    for spec in specs:
      function = spec["function"]
      properties = function["parameters"]["properties"]
      if function["name"] == "tests_manager":
        function["description"] = (
          "List test cases, read their details, or record completion."
        )
      elif function["name"] == "stop":
        function["description"] = "Save analysis and test strategies."
        properties["thoughts"]["description"] = "Analysis of the patch."
      elif function["name"] == "report":
        function["description"] = "Submit the review and finish."
        properties["force"]["description"] = "Optional submission flag."
    return specs

  def parse_actions(self, tool_calls, *, format_error_template):
    from minisweagent.models.utils.actions_toolcall import parse_toolcall_actions

    if not tool_calls:
      return parse_toolcall_actions([], format_error_template=format_error_template)
    actions = []
    for call in tool_calls:
      if call.function.name == "bash":
        actions.extend(
          parse_toolcall_actions([call], format_error_template=format_error_template)
        )
      else:
        actions.append(
          {
            "tool": call.function.name,
            "arguments": call.function.arguments,
            "tool_call_id": call.id,
          }
        )
    return actions

  def execute(self, action):
    """Return None for bash; otherwise return a local-environment result."""
    if "tool" not in action:
      return None
    name = action["tool"]
    submitted = False
    try:
      if name not in self.tools:
        raise ValueError(f"Tool {name} is not available.")
      args = json.loads(action["arguments"])
      if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object.")
      output = self.tools[name].call(**args)
      if name == "stop":
        self.stats.strategies = [
          dict(zip(("name", "target", "rationale", "expected_issue"), strategy))
          for strategy in json.loads(output)["strategies"]
        ]
      submitted = name == "report"
      returncode = 0
    except Exception as exc:
      output = f"Error: {exc}"
      returncode = 1
    self.stats.test_traj.append({**action, "output": output, "returncode": returncode})
    return {
      "output": output,
      "returncode": returncode,
      "exception_info": "",
      "submitted": submitted,
    }
