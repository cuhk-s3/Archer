import tree_sitter_cpp
from tree_sitter import Language, Parser, Tree
from unidiff import Hunk, PatchedFile

CXX_LANGUAGE = Language(tree_sitter_cpp.language())
cxx_parser = Parser(CXX_LANGUAGE)


def traverse_tree(tree: Tree):
  cursor = tree.walk()

  reached_root = False
  while not reached_root:
    yield cursor.node

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


def intersect_location(ranges, beg, end):
  for b, e in ranges:
    if max(beg, b) <= min(end, e):
      return True
  return False


def is_valid_hunk(hunk: Hunk):
  if hunk.removed != 0:
    return True
  for line in hunk:
    if line.is_added and not line.value.strip().startswith("//"):
      return True
  return False


def get_line_loc(patch: PatchedFile):
  line_location = []
  for hunk in patch:
    if not is_valid_hunk(hunk):
      continue
    min_lineno = min(x.source_line_no for x in hunk.source_lines())
    max_lineno = max(x.source_line_no for x in hunk.source_lines())
    line_location.append([min_lineno, max_lineno])
  return line_location


def get_funcname_loc(patch: PatchedFile, source_code: str):
  line_location = []
  for hunk in patch:
    if not is_valid_hunk(hunk):
      continue
    min_lineno = min(x.source_line_no for x in hunk.source_lines())
    max_lineno = max(x.source_line_no for x in hunk.source_lines())
    line_location.append([min_lineno, max_lineno])
  tree = cxx_parser.parse(bytes(source_code, "utf-8"))
  modified_funcs = set()
  for node in traverse_tree(tree):
    if node.type == "function_definition" and intersect_location(
      line_location, node.start_point.row, node.end_point.row
    ):
      func_name_node = node.children_by_field_name("declarator")[0]
      while True:
        decl = func_name_node.children_by_field_name("declarator")
        if len(decl) == 0:
          if func_name_node.type == "reference_declarator":
            func_name_node = func_name_node.child(1)
            continue
          break
        func_name_node = decl[0]
      func_name = func_name_node.text.decode("utf-8")
      modified_funcs.add(func_name)
  modified_funcs_valid = list()
  for func in modified_funcs:
    substr = False
    for rhs in modified_funcs:
      if func != rhs and func in rhs:
        substr = True
        break
    if not substr:
      modified_funcs_valid.append(func)

  return modified_funcs_valid
