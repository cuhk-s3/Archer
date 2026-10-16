#!/usr/bin/env python3
# Vendored from connglli/veir commit 3270989b462f7aa7e1c368e8fcddf9754a9b0acf,
# Tools/rwenum. Keep behavioral changes in the Archer wrapper when possible.
"""
Generate small LLVM integer tests and check llrwt with Alive2.

Usage:
  # Multiply by a literal; enumerate input widths from 1 through 8.
  python rwenum 'x * 2 => x << 1' \
    --max-width 8 --outdir out-mul-shift

  # Enumerate every value of C1 at each inferred width.
  python rwenum 'x + C1 => C1 + x' \
    --max-width 4 --outdir out-add-constant

  # Enumerate two independent constant parameters of the same type.
  python rwenum '(x * C1) + (x * C2) => x * (C1 + C2)' \
    --max-width 3 --outdir out-factor

  # Restrict constant enumeration to selected values, wrapped to each width.
  python rwenum '(x & C1) | (x & C2) => x & (C1 | C2)' \
    --constants='0,1,-1,0xff' \
    --max-width 8 --outdir out-constant-subset

  # Use unary operators and bitwise operations.
  python rwenum '~(x & y) => (~x) | (~y)' \
    --max-width 8 --outdir out-demorgan

  # Infer an i1 condition and independently enumerate the width of x.
  python rwenum 'select(condition, x, x) => x' \
    --max-width 8 --outdir out-select

  # Use an unsigned comparison to express a minimum operation.
  python rwenum 'select(icmp_ult(x, y), x, y) => umin(x, y)' \
    --max-width 8 --outdir out-unsigned-min

  # Enumerate x's width independently from the shared width of y and z.
  python rwenum 'select(icmp_eq(x, 0), y, z) => select(icmp_ne(x, 0), z, y)' \
    --max-width 4 --outdir out-independent-widths

  # Tie x to W1 and enumerate legal extension widths W2 greater than W1.
  python rwenum 'trunc(zext(x, W2), W1) => x' \
    --input-width x=W1 \
    --max-width 8 --outdir out-cast-roundtrip

  # Fix x to i4 and use a fixed i8 cast destination.
  python rwenum 'sext(x, 8) + 0 => sext(x, 8)' \
    --input-width x=4 \
    --max-width 8 --outdir out-fixed-widths

  # Nest intrinsic calls.
  python rwenum 'bitreverse(bitreverse(x)) => x' \
    --max-width 8 --outdir out-bitreverse

  # Enumerate both poison-control immediate values for ctlz.
  python rwenum 'ctlz(x) + 0 => ctlz(x)' \
    --max-width 8 --outdir out-ctlz

  # bswap requires a width divisible by 16; this command generates i16 tests.
  python rwenum 'bswap(bswap(x)) => x' \
    --max-width 16 --outdir out-bswap

For each case, it runs:
  llrwt before.ll > after.ll
  alive-tv --disable-undef-input before.ll after.ll

The RHS is a label only. It is not parsed or used to build after.ll.
Alive2 checks the transformation that llrwt actually makes. An unchanged
function can pass. This checks correctness, not whether a rewrite fired.

DSL:
  Inputs:       x, y, condition, or other identifiers except C<number>/W<number>
  Constants:    C1, C2, ... enumerate all values of their inferred type
  Widths:       W1, W2, ...; no other symbolic width names are accepted
  Literals:     0, 1, -1, 0xff
  Operators:    + - * & | ^ << >>, unary + - ~
  Binary calls: add, sub, mul, shl, lshr, ashr, xor,
                udiv, sdiv, urem, srem
  Casts:        zext(x, W1), sext(x, W1), trunc(x, W1)
  Comparisons:  icmp_eq, icmp_ne, icmp_ult, icmp_ule, icmp_ugt, icmp_uge,
                icmp_slt, icmp_sle, icmp_sgt, icmp_sge
  Other:        select(condition, true_value, false_value), freeze(x)
  Intrinsics:   ctpop, ctlz, cttz, bswap, bitreverse, abs,
                fshl, fshr, smin, smax, umin, umax,
                sadd_sat, uadd_sat, ssub_sat, usub_sat

Operator precedence follows Python. >> means lshr, not ashr.
Use & and | rather than and(...) and or(...), which are Python keywords.

Types:
  Types are inferred from uses. For example, a select condition is i1.
  Each independent unresolved type gets its own width dimension.
  Automatically generated width names are W1, W2, W3, ...; existing explicit
  width names are never reused for an unrelated unresolved type.
  --input-width x=W1 explicitly connects an input to width W1.
  Cast destinations are W<number> symbols or positive integers.
  C<number> names are reserved for constant parameters.
  W<number> names are reserved for widths and cannot be used as values.
  Each free width ranges from 1 through --max-width.
  --additional-widths (default 32,64) adds extra bit widths beyond
  --max-width, so common power-of-two widths are tested even with a small bound.
  Fixed widths must also fit within --max-width or appear in --additional-widths.
  Only legal type and cast assignments are generated.
  Repeated C1 occurrences have the same type and value.
  Integer literals wrap to their inferred width.

  Example: select(icmp_eq(x, 0), y, z) independently enumerates the width
  of x and the shared width of y/z.

  Example: trunc(x, W1) independently enumerates x's width and W1, subject
  to x being wider than W1. Use --input-width to express additional width
  equalities when needed.

Flags:
  Every instruction gets each legal flag subset independently.
  "modern" is the default profile. It includes newer flags and requires
  matching support in both llrwt's LLVM and Alive2.
  "core" omits disjoint, nneg, trunc overflow flags, and icmp samesign.
  ctlz, cttz, and abs also enumerate both poison-control immediate values.
  Poison-producing cases are not removed.

Enumeration and counting:
  Exact counting is optional: use --count or --dry-run.
  --limit does not implicitly count the unrestricted domain.
  Cast inequalities and intrinsic width restrictions prune partial width
  assignments. Cycles of strict cast inequalities are rejected.
  Reaching --limit without an exact count is conservatively reported as a
  limited run, even if the last checked case happened to exhaust the domain.

Limits:
  Scalar integers only. No memory, pointers, vectors, floating-point,
  control flow, preconditions, or shared temporary bindings.
  Repeated subexpressions produce separate instructions.
  The generator does not invent other expression shapes.
  bswap requires widths divisible by 16.
"""

import argparse
import ast
import itertools
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CONSTANT_NAME = re.compile(r"C[0-9]+")
WIDTH_NAME = re.compile(r"W[0-9]+")

BINOPS = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.BitAnd: "and",
    ast.BitOr: "or",
    ast.BitXor: "xor",
    ast.LShift: "shl",
    ast.RShift: "lshr",
}

BINARY_OPS = {
    "add",
    "sub",
    "mul",
    "and",
    "or",
    "xor",
    "shl",
    "lshr",
    "ashr",
    "udiv",
    "sdiv",
    "urem",
    "srem",
}

CASTS = {"zext", "sext", "trunc"}

PREDICATES = {
    "eq",
    "ne",
    "ult",
    "ule",
    "ugt",
    "uge",
    "slt",
    "sle",
    "sgt",
    "sge",
}

# DSL name -> (LLVM intrinsic name, number of data operands).
INTRINSICS = {
    "ctpop": ("ctpop", 1),
    "ctlz": ("ctlz", 1),
    "cttz": ("cttz", 1),
    "bswap": ("bswap", 1),
    "bitreverse": ("bitreverse", 1),
    "abs": ("abs", 1),
    "fshl": ("fshl", 3),
    "fshr": ("fshr", 3),
    "smin": ("smin", 2),
    "smax": ("smax", 2),
    "umin": ("umin", 2),
    "umax": ("umax", 2),
    "sadd_sat": ("sadd.sat", 2),
    "uadd_sat": ("uadd.sat", 2),
    "ssub_sat": ("ssub.sat", 2),
    "usub_sat": ("usub.sat", 2),
}

POISON_IMMEDIATE = {"ctlz", "cttz", "abs"}

CORE_FLAGS = {
    "add": ("nsw", "nuw"),
    "sub": ("nsw", "nuw"),
    "mul": ("nsw", "nuw"),
    "shl": ("nsw", "nuw"),
    "lshr": ("exact",),
    "ashr": ("exact",),
    "udiv": ("exact",),
    "sdiv": ("exact",),
}

NEW_FLAGS = {
    "or": ("disjoint",),
    "zext": ("nneg",),
    "trunc": ("nsw", "nuw"),
    "icmp": ("samesign",),
}


def enum_subsets(items):
    """Return every subset of the items, including the empty subset."""
    return [
        tuple(item for i, item in enumerate(items) if mask & (1 << i))
        for mask in range(1 << len(items))
    ]


def iter_cartesian_product(domains):
    """Cartesian product without copying domain contents into tuples."""
    values = [None] * len(domains)

    def visit(index):
        if index == len(domains):
            yield tuple(values)
            return
        for value in domains[index]:
            values[index] = value
            yield from visit(index + 1)

    yield from visit(0)


class Types:
    """Join equal-width types and track any known fixed width."""

    def __init__(self):
        """Initialize empty type-equivalence and fixed-width tables."""
        self.parent_id = []  # [type ID]: parent type ID
        self.fixed_width = []  # [type ID]: fixed width or None

    def new(self, width=None):
        """Create a type with an optional fixed bit width and return its type ID."""
        ty_id = len(self.parent_id)
        self.parent_id.append(ty_id)
        self.fixed_width.append(width)
        return ty_id

    def root(self, ty_id):
        """Find a type's equivalence-class root while compressing its parent path."""
        while self.parent_id[ty_id] != ty_id:
            self.parent_id[ty_id] = self.parent_id[self.parent_id[ty_id]]
            ty_id = self.parent_id[ty_id]
        return ty_id

    def join(self, ty_a, ty_b):
        """Merge equal-width type classes, rejecting conflicting fixed widths."""
        ra, rb = self.root(ty_a), self.root(ty_b)
        if ra == rb:
            return

        wa, wb = self.fixed_width[ra], self.fixed_width[rb]
        if wa is not None and wb is not None and wa != wb:
            raise ValueError(f"type mismatch: i{wa} and i{wb}")

        self.parent_id[rb] = ra
        self.fixed_width[ra] = wa if wa is not None else wb


@dataclass(frozen=True)
class Reference:
    kind: str
    value: object
    ty: int


@dataclass(frozen=True)
class Instruction:
    op: str
    args: tuple
    ty: int


class Pattern:
    def __init__(self, text, input_widths=None):
        self.types = Types()
        self.width_symbols = {}
        self.fixed_width_types = {}
        self.variables = {}
        self.constants = {}
        self.instructions = []
        self.cast_constraints = []
        self.bswap_types = []
        self.input_widths = dict(input_widths or {})

        for name in self.input_widths:
            if (
                not IDENTIFIER.fullmatch(name)
                or CONSTANT_NAME.fullmatch(name)
                or WIDTH_NAME.fullmatch(name)
            ):
                raise ValueError(
                    f"invalid input name: {name!r}; "
                    "C<number> and W<number> are reserved for constants and widths"
                )

        # Parse the expression and lower it into instructions.
        # This will also populate self.variables, self.constants, etc.
        self.result = self.lower(ast.parse(text.strip(), mode="eval").body)

        unused = self.input_widths.keys() - self.variables.keys()
        if unused:
            raise ValueError(
                "width annotations for unused inputs: " + ", ".join(sorted(unused))
            )

        # Preserve equalities established by actual uses, but do not equate
        # otherwise independent unresolved types.
        roots = list(
            dict.fromkeys(
                self.types.root(ty) for ty in range(len(self.types.parent_id))
            )
        )
        named = {self.types.root(ty) for ty in self.width_symbols.values()}
        unknown = [
            root
            for root in roots
            if self.types.fixed_width[root] is None and root not in named
        ]

        generated_index = 1
        for root in unknown:
            while True:
                name = f"W{generated_index}"
                generated_index += 1
                if name not in self.width_symbols:
                    break

            # Name the existing type class without joining it to another.
            self.width_symbols[name] = root

        # Equal named width classes share one enumeration dimension.
        self.free_roots = list(
            dict.fromkeys(
                self.types.root(ty)
                for ty in self.width_symbols.values()
                if self.types.fixed_width[self.types.root(ty)] is None
            )
        )

    # -----------------------------------------------------------------
    # Parsing and instruction construction
    # -----------------------------------------------------------------

    def width_ty(self, value):
        """Get or create the type associated with a fixed width or width symbol."""
        if isinstance(value, str) and value.isdecimal():
            value = int(value)

        if type(value) is int:
            if value < 1:
                raise ValueError("widths must be positive")
            if value not in self.fixed_width_types:
                self.fixed_width_types[value] = self.types.new(value)
            return self.fixed_width_types[value]

        if not isinstance(value, str) or not WIDTH_NAME.fullmatch(value):
            raise ValueError(
                f"invalid width name: {value!r}; "
                "expected W<number> or a positive integer"
            )

        if value not in self.width_symbols:
            self.width_symbols[value] = self.types.new()
        return self.width_symbols[value]

    def width(self, node):
        """Parse a cast destination AST node and return its associated type ID."""
        if isinstance(node, ast.Name):
            return self.width_ty(node.id)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return self.width_ty(node.value)
        raise ValueError("cast width must be W<number> or a positive integer")

    def literal(self, value):
        """Create an integer literal reference with a fresh unresolved type."""
        return Reference("literal", value, self.types.new())

    def instruction(self, op, args, ty):
        """Append an instruction and return a reference to its result."""
        index = len(self.instructions)
        self.instructions.append(Instruction(op, tuple(args), ty))
        return Reference("temporary", index, ty)

    def binary(self, op, lhs, rhs):
        """Unify operand types and append a binary instruction."""
        self.types.join(lhs.ty, rhs.ty)
        return self.instruction(op, (lhs, rhs), lhs.ty)

    def lower(self, node):
        """Lower an expression AST node into references, instructions, and type constraints."""
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return self.literal(node.value)

        if isinstance(node, ast.Name):
            name = node.id
            if not IDENTIFIER.fullmatch(name):
                raise ValueError(f"invalid identifier: {name!r}")

            if WIDTH_NAME.fullmatch(name):
                raise ValueError(
                    f"width symbol {name!r} cannot be used as a value; "
                    "use it as a cast destination or in --input-width"
                )

            if CONSTANT_NAME.fullmatch(name):
                if name not in self.constants:
                    self.constants[name] = Reference("constant", name, self.types.new())
                return self.constants[name]

            if name not in self.variables:
                ty = (
                    self.width_ty(self.input_widths[name])
                    if name in self.input_widths
                    else self.types.new()
                )
                self.variables[name] = Reference("variable", name, ty)
            return self.variables[name]

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert)):
                raise ValueError("unsupported unary operator")

            # Do not create an instruction for a signed literal.
            if (
                isinstance(node.op, (ast.UAdd, ast.USub))
                and isinstance(node.operand, ast.Constant)
                and type(node.operand.value) is int
            ):
                value = node.operand.value
                return self.literal(-value if isinstance(node.op, ast.USub) else value)

            arg = self.lower(node.operand)
            if isinstance(node.op, ast.UAdd):
                return arg
            if isinstance(node.op, ast.USub):
                return self.binary("sub", self.literal(0), arg)
            return self.binary("xor", arg, self.literal(-1))

        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            return self.binary(
                BINOPS[type(node.op)],
                self.lower(node.left),
                self.lower(node.right),
            )

        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and not node.keywords
        ):
            raise ValueError(f"unsupported expression: {ast.dump(node)}")

        op = node.func.id
        if op in CASTS:
            if len(node.args) != 2:
                raise ValueError(f"{op} expects (value, destination_width)")
            source = self.lower(node.args[0])
            dest = self.width(node.args[1])
            self.cast_constraints.append((op, source.ty, dest))
            return self.instruction(op, (source,), dest)

        comparison = op.startswith("icmp_") and op[5:] in PREDICATES
        if op in BINARY_OPS or comparison:
            arity = 2
        elif op == "select":
            arity = 3
        elif op == "freeze":
            arity = 1
        elif op in INTRINSICS:
            arity = INTRINSICS[op][1]
        else:
            raise ValueError(f"unsupported operation: {op}")

        if len(node.args) != arity:
            raise ValueError(f"{op} expects {arity} operand(s)")
        args = tuple(self.lower(arg) for arg in node.args)

        if op in BINARY_OPS:
            return self.binary(op, *args)

        if comparison:
            self.types.join(args[0].ty, args[1].ty)
            return self.instruction(op, args, self.width_ty(1))

        if op == "select":
            self.types.join(args[0].ty, self.width_ty(1))
            self.types.join(args[1].ty, args[2].ty)
            return self.instruction(op, args, args[1].ty)

        if op == "freeze":
            return self.instruction(op, args, args[0].ty)

        for arg in args[1:]:
            self.types.join(args[0].ty, arg.ty)
        if op == "bswap":
            self.bswap_types.append(args[0].ty)
        return self.instruction(op, args, args[0].ty)

    # -----------------------------------------------------------------
    # Enumeration and counting
    # -----------------------------------------------------------------

    def bits(self, ty, assignment):
        """Resolve a type's bit width from its fixed width or the current assignment."""
        root = self.types.root(ty)
        fixed = self.types.fixed_width[root]
        return fixed if fixed is not None else assignment[root]

    def named_widths(self, assignment):
        """Map each width symbol to its resolved bit width."""
        return {
            name: self.bits(ty, assignment) for name, ty in self.width_symbols.items()
        }

    def width_assignments(self, max_width, additional_widths=()):
        """Enumerate legal widths with partial-assignment constraint pruning.

        Candidate widths are 1..max_width (inclusive) plus any
        additional_widths, deduplicated and sorted.  This lets small bounds
        still reach common power-of-two widths like 32 and 64.
        """
        candidate_widths = sorted(set(range(1, max_width + 1)) | set(additional_widths))
        roots = list(
            dict.fromkeys(
                self.types.root(ty) for ty in range(len(self.types.parent_id))
            )
        )

        # An edge u -> v represents bits(u) < bits(v).
        successors = {root: set() for root in roots}
        indegree = {root: 0 for root in roots}

        for op, source, dest in self.cast_constraints:
            source = self.types.root(source)
            dest = self.types.root(dest)

            smaller, larger = (dest, source) if op == "trunc" else (source, dest)

            if smaller == larger:
                return

            if larger not in successors[smaller]:
                successors[smaller].add(larger)
                indegree[larger] += 1

        # Strict width inequalities cannot contain a cycle.
        ready = deque(root for root in roots if indegree[root] == 0)
        order = []

        while ready:
            root = ready.popleft()
            order.append(root)
            for other in sorted(successors[root]):
                indegree[other] -= 1
                if indegree[other] == 0:
                    ready.append(other)

        if len(order) != len(roots):
            return

        # Each domain is an interval, optionally restricted to multiples of 16.
        step = {root: 1 for root in roots}
        for ty in self.bswap_types:
            step[self.types.root(ty)] = 16

        lower = {}
        upper = {}
        for root in roots:
            fixed = self.types.fixed_width[root]
            if fixed is not None:
                if fixed < 1 or (fixed > max_width and fixed not in additional_widths):
                    return
                lower[root] = upper[root] = fixed
            else:
                lower[root] = 1
                upper[root] = candidate_widths[-1] if candidate_widths else max_width

        def propagate(lo, hi):
            # Forward propagation accounts for predecessor lower bounds and
            # rounds each lower bound to a legal value of its domain.
            for root in order:
                stride = step[root]
                lo[root] = ((lo[root] + stride - 1) // stride) * stride
                if lo[root] > hi[root]:
                    return False

                for other in successors[root]:
                    lo[other] = max(lo[other], lo[root] + 1)

            # Backward propagation accounts for successor upper bounds.
            for root in reversed(order):
                for other in successors[root]:
                    hi[root] = min(hi[root], hi[other] - 1)

                stride = step[root]
                hi[root] = (hi[root] // stride) * stride
                if lo[root] > hi[root]:
                    return False

            return True

        if not propagate(lower, upper):
            return

        assignment = {}

        def visit(index, lo, hi):
            if index == len(self.free_roots):
                yield dict(assignment)
                return

            root = self.free_roots[index]
            stride = step[root]
            for value in candidate_widths:
                if value < lo[root] or value > hi[root]:
                    continue
                if value % stride != 0:
                    continue

                next_lo = lo.copy()
                next_hi = hi.copy()
                next_lo[root] = next_hi[root] = value

                if not propagate(next_lo, next_hi):
                    continue

                assignment[root] = value
                yield from visit(index + 1, next_lo, next_hi)
                del assignment[root]

        yield from visit(0, lower, upper)

    def flag_assignments(self, profile):
        """Return each instruction's flag subsets or poison-control immediate choices."""
        if profile not in {"core", "modern"}:
            raise ValueError(f"unknown flag profile: {profile}")

        result = []
        for instruction in self.instructions:
            op = instruction.op
            if op in POISON_IMMEDIATE:
                result.append([("false",), ("true",)])
                continue

            key = "icmp" if op.startswith("icmp_") else op
            flags = CORE_FLAGS.get(key, ())
            if profile == "modern":
                flags += NEW_FLAGS.get(key, ())
            result.append(enum_subsets(flags))
        return result

    def constant_domains(self, assignment, candidates):
        """Return constant domains, wrapping and deduplicating any candidate values."""
        domains = []
        for ref in self.constants.values():
            modulus = 1 << self.bits(ref.ty, assignment)
            domains.append(
                range(modulus)
                if candidates is None
                else sorted({value % modulus for value in candidates})
            )
        return domains

    def count_cases(
        self, max_width, candidates=None, profile="modern", additional_widths=()
    ):
        """Count the selected domain exactly; may be expensive."""
        variants = math.prod(map(len, self.flag_assignments(profile)))
        total = 0
        for assignment in self.width_assignments(max_width, additional_widths):
            count = 1
            for ref in self.constants.values():
                modulus = 1 << self.bits(ref.ty, assignment)
                count *= (
                    modulus
                    if candidates is None
                    else len({value % modulus for value in candidates})
                )
            total += count * variants
        return total

    def iter_cases(
        self, max_width, candidates=None, profile="modern", additional_widths=()
    ):
        """Yield test cases combining legal widths, constants, and instruction variants."""
        choices = self.flag_assignments(profile)
        for assignment in self.width_assignments(max_width, additional_widths):
            domains = self.constant_domains(assignment, candidates)
            for values in iter_cartesian_product(domains):
                constants = dict(zip(self.constants, values))
                # Each flag pool is small; product is safe here.
                for variants in itertools.product(*choices):
                    yield assignment, constants, variants

    def emit_ll(self, assignment, constants, variants):
        def ty(type_id):
            return f"i{self.bits(type_id, assignment)}"

        def operand(ref):
            if ref.kind == "variable":
                return f"%{ref.value}"
            if ref.kind == "temporary":
                return f"%fuzz.{ref.value}"

            value = constants[ref.value] if ref.kind == "constant" else ref.value
            modulus = 1 << self.bits(ref.ty, assignment)
            value %= modulus
            if value >= modulus // 2:
                value -= modulus
            return str(value)

        def typed(ref):
            return f"{ty(ref.ty)} {operand(ref)}"

        declarations = {}
        body = []

        for index, (instruction, variant) in enumerate(
            zip(self.instructions, variants)
        ):
            op, args = instruction.op, instruction.args
            result_type = ty(instruction.ty)
            flags = " " + " ".join(variant) if variant else ""

            if op in BINARY_OPS:
                expression = f"{op}{flags} {typed(args[0])}, {operand(args[1])}"
            elif op in CASTS:
                expression = f"{op}{flags} {typed(args[0])} to {result_type}"
            elif op.startswith("icmp_"):
                expression = (
                    f"icmp{flags} {op[5:]} {typed(args[0])}, {operand(args[1])}"
                )
            elif op == "select":
                expression = "select " + ", ".join(map(typed, args))
            elif op == "freeze":
                expression = f"freeze {typed(args[0])}"
            else:
                intrinsic, _ = INTRINSICS[op]
                name = f"llvm.{intrinsic}.{result_type}"
                call_args = [typed(arg) for arg in args]
                declaration_args = [ty(arg.ty) for arg in args]

                if op in POISON_IMMEDIATE:
                    call_args.append(f"i1 {variant[0]}")
                    declaration_args.append("i1 immarg")

                declarations[name] = (
                    f"declare {result_type} @{name}" f"({', '.join(declaration_args)})"
                )
                expression = f"call {result_type} @{name}({', '.join(call_args)})"

            body.append(f"  %fuzz.{index} = {expression}")

        lines = [declarations[name] for name in sorted(declarations)]
        if lines:
            lines.append("")

        params = ", ".join(typed(ref) for ref in self.variables.values())
        lines.append(f"define {ty(self.result.ty)} @test({params}) {{")
        lines.extend(body)
        lines.append(f"  ret {typed(self.result)}")
        lines.append("}")
        return "\n".join(lines) + "\n"


class CheckFailure(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def check_alive2(returncode, log):
    """Accept only the standard summary for one successful function check."""
    if "Summary:" not in log:
        raise CheckFailure(
            "unvalidated",
            f"Alive2 has no recognized summary (exit {returncode})",
        )

    summary = log.rsplit("Summary:", 1)[1]
    labels = (
        r"correct transformations?",
        r"incorrect transformations?",
        r"failed-to-prove transformations?",
        r"Alive2 errors?",
    )
    counts = []

    for label in labels:
        matches = re.findall(
            rf"^\s*(\d+)\s+{label}\s*$",
            summary,
            flags=re.MULTILINE,
        )
        if len(matches) != 1:
            raise CheckFailure("unvalidated", "unknown Alive2 summary format")
        counts.append(int(matches[0]))

    if counts[1]:
        raise CheckFailure(
            "counterexample", "Alive2 reported an incorrect transformation"
        )
    if returncode != 0 or counts[3]:
        raise CheckFailure(
            "tool_error",
            f"Alive2 error: exit={returncode}, summary={counts}",
        )
    if counts[2]:
        raise CheckFailure("unproved", "Alive2 could not finish the proof")
    if counts != [1, 0, 0, 0]:
        raise CheckFailure(
            "unvalidated",
            f"expected exactly one successful proof; summary={counts}",
        )


def run_tool(command, stdout_path, stderr_path, timeout):
    """Run a tool in a fresh POSIX session.

    On timeout, interruption, or another exception while waiting, kill its
    entire process group and reap the direct child before propagating the
    exception.

    Descendants that deliberately detach require stronger containment,
    such as a cgroup.
    """
    if os.name != "posix":
        raise ValueError("run_tool requires POSIX process-group support")

    # Commands use an argument list, never a shell.
    with ExitStack() as stack:
        output = stack.enter_context(stdout_path.open("wb"))
        errors = (
            subprocess.STDOUT
            if stderr_path is None
            else stack.enter_context(stderr_path.open("wb"))
        )

        process = subprocess.Popen(
            command,
            stdout=output,
            stderr=errors,
            start_new_session=True,
        )

        try:
            return process.wait(timeout=timeout)
        except BaseException:
            # Kill the group even if the direct child has just exited:
            # descendants may still belong to that group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                process.wait()
            raise


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def find_tool(name):
    path = shutil.which(name)
    if path is None:
        raise ValueError(f"executable not found: {name}")
    return str(Path(path).resolve())


def take_cases(cases, limit):
    """Take at most limit cases without prefetching beyond the limit.

    Unlike itertools.islice's stop argument, this also accepts arbitrarily
    large Python integers.
    """
    if limit is None:
        yield from cases
        return

    for _ in range(limit):
        try:
            case = next(cases)
        except StopIteration:
            return
        yield case


def main():
    parser = argparse.ArgumentParser(
        description="Enumerate LLVM integer tests and check llrwt with Alive2."
    )
    parser.add_argument("rewrite", help="'LHS => RHS'; RHS is a label only")
    parser.add_argument("--max-width", type=positive_int, default=3)
    parser.add_argument(
        "--additional-widths",
        default="32,64",
        help="extra bit widths beyond 1..max-width, e.g. '32,64' (default: 32,64)",
    )
    parser.add_argument(
        "--input-width",
        action="append",
        default=[],
        metavar="NAME=WIDTH",
        help="set an input width to W<number> or a positive integer, e.g. x=W1",
    )
    parser.add_argument(
        "--constants",
        help="restrict constant parameters, e.g. --constants='0,1,-1,2'",
    )
    parser.add_argument(
        "--llvm-profile",
        choices=("core", "modern"),
        default="modern",
        help="flag profile for the LLVM IR",
    )
    parser.add_argument("--limit", type=positive_int, help="stop after this many cases")
    parser.add_argument("--outdir", required=True, type=Path, help="output directory")
    parser.add_argument("--llrwt", default="llrwt", help="executable path")
    parser.add_argument("--rules", help="path passed to llrwt via --rules")
    parser.add_argument("--alive2", default="alive-tv", help="executable path")
    parser.add_argument(
        "--timeout", type=positive_int, default=60, help="per-tool timeout in seconds"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count the selected domain without creating files or running tools",
    )
    args = parser.parse_args()

    parts = args.rewrite.split("=>")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        parser.error("expected a nonempty LHS and RHS separated by =>")

    try:
        input_widths = {}
        for annotation in args.input_width:
            name, separator, width = annotation.partition("=")
            name, width = name.strip(), width.strip()
            if not separator or not name or not width:
                raise ValueError(f"invalid input annotation: {annotation!r}")
            if name in input_widths:
                raise ValueError(f"duplicate input annotation: {name}")
            input_widths[name] = width

        candidates = None
        if args.constants is not None:
            candidates = [int(value.strip(), 0) for value in args.constants.split(",")]

        additional_widths = tuple(
            sorted(
                {
                    int(w.strip(), 0)
                    for w in args.additional_widths.split(",")
                    if w.strip()
                }
            )
        )
        for w in additional_widths:
            if w < 1:
                raise ValueError(f"additional width must be positive: {w}")

        pattern = Pattern(parts[0], input_widths)

        no_cases_message = (
            "no legal cases; check types, cast widths, "
            "intrinsic width rules, --max-width, and --additional-widths"
        )

        # Do not traverse the whole width domain unless explicitly requested.
        total = pattern.count_cases(
            args.max_width, candidates, args.llvm_profile, additional_widths
        )
        if total == 0:
            raise ValueError(no_cases_message)
        planned = min(total, args.limit) if args.limit is not None else total
        print(
            f"{total:,} cases in the selected domain; would run {planned:,} cases",
            flush=True,
        )

        if args.dry_run:
            return 0

        llrwt = find_tool(args.llrwt)
        alive2 = find_tool(args.alive2)

        # Prefetch only one case to detect an empty domain without counting it.
        # Preserve that case for execution.
        cases = pattern.iter_cases(
            args.max_width, candidates, args.llvm_profile, additional_widths
        )
        first_case = next(cases, None)
        if first_case is None:
            raise ValueError(no_cases_message)
        cases = itertools.chain((first_case,), cases)
    except (SyntaxError, ValueError, RecursionError) as error:
        parser.error(str(error))

    root = args.outdir.resolve()
    root.mkdir(parents=True, exist_ok=False)

    run_info = {
        "rewrite": args.rewrite,
        "max_width": args.max_width,
        "additional_widths": list(additional_widths),
        "rules": args.rules,
        "input_widths": input_widths,
        "constant_candidates": candidates,
        "llvm_profile": args.llvm_profile,
        "limit": args.limit,
        "total_counted": total is not None,
        "total_cases": total,
        "planned_cases": planned,
        "completed_cases": 0,
        "status": "running",
    }
    save_json(root / "run.json", run_info)

    for number, (assignment, constants, variants) in enumerate(
        take_cases(cases, planned), start=1
    ):
        case_dir = root / f"case-{number:09d}"
        case_dir.mkdir()

        before = case_dir / "before.ll"
        after = case_dir / "after.ll"
        rewrite_command = [llrwt, str(before)]
        if args.rules is not None:
            rewrite_command += ["--rules", args.rules]
        alive_command = [
            alive2,
            "--disable-undef-input",
            str(before),
            str(after),
        ]

        metadata = {
            "widths": pattern.named_widths(assignment),
            "input_widths": {
                name: pattern.bits(ref.ty, assignment)
                for name, ref in pattern.variables.items()
            },
            "constant_widths": {
                name: pattern.bits(ref.ty, assignment)
                for name, ref in pattern.constants.items()
            },
            "constants_unsigned": constants,
            "instructions": [
                {
                    "op": instruction.op,
                    "flags": (
                        list(variant) if instruction.op not in POISON_IMMEDIATE else []
                    ),
                    **(
                        {"poison_immediate": variant[0] == "true"}
                        if instruction.op in POISON_IMMEDIATE
                        else {}
                    ),
                }
                for instruction, variant in zip(pattern.instructions, variants)
            ],
            "llrwt_command": rewrite_command,
            "alive2_command": alive_command,
            "status": "running",
        }

        try:
            before.write_text(
                pattern.emit_ll(assignment, constants, variants),
                encoding="utf-8",
            )
            save_json(case_dir / "case.json", metadata)

            code = run_tool(
                rewrite_command,
                after,
                case_dir / "llrwt.log",
                args.timeout,
            )
            if code != 0:
                raise CheckFailure("tool_error", f"llrwt exited with status {code}")
            if after.stat().st_size == 0:
                raise CheckFailure("tool_error", "llrwt produced empty output")

            # Information only, not evidence that the intended rewrite fired.
            metadata["text_changed"] = before.read_bytes() != after.read_bytes()

            alive_log = case_dir / "alive2.log"
            code = run_tool(
                alive_command,
                alive_log,
                None,
                args.timeout,
            )
            check_alive2(
                code,
                alive_log.read_text(encoding="utf-8", errors="replace"),
            )

        except (
            CheckFailure,
            subprocess.TimeoutExpired,
            OSError,
            KeyboardInterrupt,
        ) as error:
            if isinstance(error, CheckFailure):
                status = error.status
            elif isinstance(error, subprocess.TimeoutExpired):
                status = "timeout"
            elif isinstance(error, KeyboardInterrupt):
                status = "interrupted"
            else:
                status = "tool_error"

            metadata.update(status=status, error=str(error) or status)
            run_info.update(
                status=status,
                completed_cases=number - 1,
                failing_case=str(case_dir),
            )
            save_json(case_dir / "case.json", metadata)
            save_json(root / "run.json", run_info)

            print(
                f"STOP: {status}: {error}\nSaved case: {case_dir}",
                file=sys.stderr,
            )
            return (
                130
                if status == "interrupted"
                else 1 if status == "counterexample" else 2
            )

        metadata["status"] = "proved"
        save_json(case_dir / "case.json", metadata)
        run_info["completed_cases"] = number

        if number % 100 == 0:
            save_json(root / "run.json", run_info)
            progress = (
                f"{number:,}/{planned:,}" if planned is not None else f"{number:,}"
            )
            print(f"Proved {progress}", flush=True)

    completed = run_info["completed_cases"]

    # Without an exact count, reaching the limit does not establish whether
    # more cases exist. Do not generate another case merely to find out.
    limited = (
        args.limit is not None
        and completed == args.limit
        and (total is None or completed < total)
    )

    run_info["status"] = "limited" if limited else "complete"
    save_json(root / "run.json", run_info)

    print(f"Proved {completed:,} cases. Results: {root}")

    if limited:
        if total is None:
            print(
                "LIMITED RUN: reached --limit; "
                "exhaustion of the selected domain was not established."
            )
        else:
            print("LIMITED RUN: some cases were not checked.")

    if candidates is not None and pattern.constants:
        print("Constant values were restricted by --constants.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RecursionError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
