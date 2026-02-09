import sys
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import List


class FuncToolSpec:
  @dataclass
  class Param:
    name: str  # Name of the parameter
    type: str  # Type of the parameter (e.g., "string", "integer", "list[integer]" etc.)
    req: bool  # Whether the parameter is required
    desc: str  # Description of the parameter

  def __init__(self, name: str, desc: str, parameters: List[Param]):
    self.name = name
    self.desc = desc
    self.params = parameters

  def render_in_claude_format(self) -> dict:
    return {
      "name": self.name,
      "description": self.desc,
      "input_schema": {
        "type": "object",
        "properties": {
          p.name: {"type": p.type, "description": p.desc} for p in self.params
        },
        "required": [p.name for p in self.params if p.req],
        "additionalProperties": False,
      },
    }

  def render_in_openai_format(self) -> dict:
    return {
      "type": "function",
      "function": {
        "name": self.name,
        "description": self.desc,
        "parameters": {
          "type": "object",
          "properties": {
            p.name: {"type": p.type, "description": p.desc} for p in self.params
          },
          "required": [p.name for p in self.params if p.req],
          "additionalProperties": False,
        },
      },
    }

  def render_in_simple_format(self) -> dict:
    return {
      "name": self.name,
      "description": self.desc,
      "parameters": {
        p.name: {"type": p.type, "required": p.req, "description": p.desc}
        for p in self.params
      },
    }


class FuncToolCallException(Exception):
  pass


class FuncToolBase(ABC):
  def name(self) -> str:
    """The unique name of the tool"""
    return self.spec().name

  def desc(self) -> str:
    return self.spec().desc

  @abstractmethod
  def spec(self) -> FuncToolSpec:
    """
    Return the specification of this tool.
    """
    ...

  def call(self, **kwargs) -> str:
    """
    Run the tool using the given arguments.
    Return the result of the tool call as a string if successful.
    Otherwise, raise a FuncToolCallException.
    """
    self._check(**kwargs)
    return self._call(**kwargs)

  def _check(self, **kwargs):
    """
    Check if the tool can be called with the given arguments.
    Raise a FuncToolCallException if there are any issues.
    """
    # Check if all required parameters are present
    required_params = [p.name for p in self.spec().params if p.req]
    missing_params = [p for p in required_params if p not in kwargs]
    if missing_params:
      raise FuncToolCallException(
        f"The following required parameters are missing: {', '.join(missing_params)}"
      )
    return None  # By default, only check for required parameters

  @abstractmethod
  def _call(self, **kwargs) -> str:
    """
    Run the tool using the given arguments.
    Return the result of the tool call as a string if successful.
    Otherwise, raise a FuncToolCallException.
    """
    ...


class ToolRegistry:
  def __init__(self):
    self.tools = OrderedDict()

  def copy(self) -> "ToolRegistry":
    registry = ToolRegistry()
    for name, (tool, _, total_budget) in self.tools.items():
      registry.tools[name] = [tool, total_budget, total_budget]
    return registry

  def register(self, tool: FuncToolBase, budget: int = sys.maxsize):
    if tool.name() in self.tools:
      raise ValueError(f"Tool with name {tool.name()} is already registered.")
    self.tools[tool.name()] = [
      tool,  # The tool itself
      budget,  # Remaining budget
      budget,  # Total budget
    ]

  def get(self, name: str) -> FuncToolBase:
    self._ensure_registered(name)
    return self.tools[name][0]

  def get_remaining_budget(self, name: str) -> int:
    self._ensure_registered(name)
    return self.tools[name][1]

  def get_total_budget(self, name: str) -> int:
    self._ensure_registered(name)
    return self.tools[name][2]

  def list(self, ignore_budget=True) -> List[str]:
    if ignore_budget:
      return list(self.tools.keys())
    else:
      return [name for name in self.tools if self.tools[name][1] > 0]

  def call(self, name: str, **kwargs) -> str:
    try:
      self._ensure_remaining_budget(name)
      result = self.tools[name][0].call(**kwargs)
    except FuncToolCallException as e:
      result = f"Error: {e}"
    except Exception as e:
      result = f"Error: {e}"
    finally:
      if name in self.tools:
        self.tools[name][1] -= 1
    result = result.strip()
    if result == "":
      result = "Success: <No output>"
    return result

  def _ensure_remaining_budget(self, name: str):
    self._ensure_registered(name)
    if self.tools[name][1] <= 0:
      raise FuncToolCallException(f"Tool {name} has no remaining budget left.")

  def _ensure_registered(self, name: str):
    if name not in self.tools:
      raise FuncToolCallException(f"Tool {name} is not available.")
