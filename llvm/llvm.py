import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

import tree_sitter_cpp
from tree_sitter import Language, Parser, Tree, TreeCursor

from llvm.llvm_helper import (
  get_llvm_build_dir,
  llvm_dir,
)
from utils import cmdline


@dataclass
class Code:
  line_number: int
  code: str
  annotation: str = ""


class CodeSnippet:
  header: str
  lines: Dict[int, Code]

  def __init__(self):
    self.header = ""
    self.lines = dict()

  def add_line(self, line: Code):
    line.code = line.code.rstrip("\n")
    self.lines[line.line_number] = line

  def add_annotation(self, line_number: int, annotation: str):
    if line_number in self.lines:
      self.lines[line_number].annotation = annotation
    else:
      self.lines[line_number] = Code(line_number, "", annotation)

  def set_header(self, header: str):
    self.header = header

  def render(self) -> str:
    rendered = self.header
    if len(self.lines) == 0:
      return rendered

    left_width = len(str(max(self.lines.keys()))) + 1
    line_count = 0
    for line_number in sorted(self.lines.keys()):
      line = self.lines[line_number]
      rendered += f"{line_number:<{left_width}}{line.code}"
      if line.annotation:
        rendered += f"// {line.annotation}"
      rendered += "\n"
      line_count += 1
      if line_count >= 250:
        rendered += "// ... (truncated)\n"
        break

    return rendered


class LLVM:
  def __init__(self):
    self.opt = Path(get_llvm_build_dir()) / "bin" / "opt"
    self.repo = Path(llvm_dir)
    CXX_LANGUAGE = Language(tree_sitter_cpp.language())
    self.cxx_parser = Parser(CXX_LANGUAGE)

  def resolve_pass_name(self, args: str) -> Tuple[str, List[str]]:
    """Resolve the pass name(s) of the given llvm file"""
    # TODO: Support more closely-bound analysis passes
    pos = args.find("passes=")
    next = args.find(" ", pos)
    pass_name = args[pos + 7 : next]
    USEFUL_ANALYSIS_PASSES = {
      "print<scalar-evolution>": [
        "constraint-elimination",
        "irce",
        "indvars",
        "licm",
        "loop-delete",
        "loop-distribute",
        "loop-flatten",
        "loop-fusion",
        "loop-idiom",
        "loop-interchange",
        "loop-load-elim",
        "loop-predication",
        "loop-rotate",
        "loop-simplifycfg",
        "loopsink",
        "loop-reduce",
        "loop-term-fold",
        "loop-unroll-and-jam",
        "loop-unroll",
        "loop-versioning-licm",
        "nary-reassociate",
        "simple-loop-unswitch",
        "canon-freeze",
        "lcssa",
        "loop-constrainer",
        "loop-peel",
        "loop-simplify",
        "load-store-vectorizer",
        "loop-vectorize",
        "slp-vectorizer",
      ],
      "aa-eval": [
        "aggressive-instcombine",
        "coro-elide",
        "instcombine",
        "inline",
        "dse",
        "flatten-cfg",
        "gvn",
        "gvn-hoist",
        "jump-threading",
        "licm",
        "loop-idiom",
        "loop-predication",
        "loop-versioning",
        "memcpyopt",
        "mergeicmps",
        "newgvn",
        "tailcallelim",
        "load-store-vectorizer",
      ],
    }

    analysis_passes = []

    for name, keys in USEFUL_ANALYSIS_PASSES.items():
      for key in keys:
        if key in pass_name:
          analysis_passes.append(name)
          break

    return pass_name, analysis_passes

  def resolve_pass_opts(self, pass_name: str) -> List[str]:
    """Resolve the useful options of a given pass"""
    if pass_name == "aa-eval":
      return ["-aa-pipeline=basic-aa", "-print-all-alias-modref-info"]
    return []

  def resolve_debug_types(self, files: Set[Path]) -> List[str]:
    """Resolve debug types of given files"""
    # FIXME: This is not always safe, an edge case: https://github.com/llvm/llvm-project/blob/4f8597f071bab5113a945bd653bec84bd820d4a3/llvm/lib/Transforms/Scalar/LoopLoadElimination.cpp#L64-L65
    pattern = re.compile(r'#define DEBUG_TYPE "(.+)"')
    debug_types = set()
    for file in files:
      if file.match("llvm/lib/Analysis/*.cpp") or file.match(
        "llvm/lib/Transforms/*/*.cpp"
      ):
        content = (self.repo / file).read_text()
        match = pattern.search(content)
        if match:
          debug_type = match.group(1)
          debug_types.add(debug_type.strip())
    return list(debug_types)

  def run_opt(
    self, reprod: Path, options: List[str], check=True, **kwargs
  ) -> Tuple[str, str]:
    cmd = " ".join([str(self.opt.absolute())] + options + [str(reprod.absolute())])
    return cmd, cmdline.getoutput(cmd, check=check, **kwargs).decode()

  def find_function(
    self, tree: Tree, start_line: int, end_line: int, func_name: str
  ) -> TreeCursor:
    cursor = tree.walk()

    reached_root = False
    while not reached_root:
      # Extra one line for return type which is not in the same line as the function name
      if (
        cursor.node.type == "function_definition"
        and cursor.node.start_point.row + 1 + 1 >= start_line
        and cursor.node.end_point.row + 1 <= end_line
      ):
        func_name_node = cursor.node.children_by_field_name("declarator")[0]
        while True:
          decl = func_name_node.children_by_field_name("declarator")
          if len(decl) == 0:
            if func_name_node.type == "reference_declarator":
              func_name_node = func_name_node.child(1)
              continue
            break
          func_name_node = decl[0]
        cur_func_name = func_name_node.text.decode("utf-8")
        if func_name in cur_func_name:
          return cursor

      if cursor.goto_first_child():
        continue

      if cursor.goto_next_sibling():
        continue

      retracing = True
      while retracing:
        if not cursor.goto_parent():
          retracing = False
          reached_root = True

        if cursor.goto_next_sibling():
          retracing = False

    return None

  def get_full_func_def(
    self, code: CodeSnippet, lines: List[str], start_line: int, end_line: int
  ) -> CodeSnippet:
    for line in range(start_line, end_line + 1):
      code.add_line(Code(line, lines[line]))
    return code

  def collect_header_comments(self, lines: List[str], start_lineno: int) -> str:
    header_comments = ""
    for i in range(start_lineno - 1, 0, -1):
      line = lines[i].lstrip()
      if line.startswith("//"):
        header_comments = line + header_comments
      elif i != start_lineno - 1:
        # Extra one line for return type which is not in the same line as the function name
        break
    return header_comments

  def get_func_stem(self, func_name: str) -> str:
    if "(" in func_name:
      func_name = func_name[: func_name.index("(")]

    if "::" in func_name:
      func_name = func_name[func_name.rindex("::") + 2 :]

    return func_name

  def render_func_code(
    self, func_name: str, start_line: int, file_name: str
  ) -> CodeSnippet:
    code = CodeSnippet()

    with open(self.repo / file_name, "r") as f:
      src = f.read()
    lines = [""] + src.splitlines(keepends=True)
    if start_line >= len(lines):
      code.set_header("Unavailable")
      return code

    tree = self.cxx_parser.parse(bytes(src, "utf8"))
    cursor = self.find_function(
      tree, start_line, int(1e10), self.get_func_stem(func_name)
    )
    if not cursor:
      code.set_header("Unavailable")
      return code
    header_comments = self.collect_header_comments(lines, start_line)
    code.set_header(header_comments)
    start_line = min(cursor.node.start_point.row + 1, start_line)
    end_line = cursor.node.end_point.row
    return self.get_full_func_def(code, lines, start_line, end_line + 1)
