"""Plant small bugs in Python source, only on the lines you choose.

Each mutant is a text edit (start, end, replacement) so the rest of the
file, comments and formatting included, stays exactly as written.
"""

import ast
import re
from dataclasses import dataclass

IGNORE = "wouldcatch: ignore"

COMPARE = {
    ast.Eq: ("==", "!="), ast.NotEq: ("!=", "=="),
    ast.Lt: ("<", "<="), ast.LtE: ("<=", "<"),
    ast.Gt: (">", ">="), ast.GtE: (">=", ">"),
    ast.Is: (r"\bis\b", "is not"), ast.IsNot: (r"\bis\s+not\b", "is"),
    ast.In: (r"\bin\b", "not in"), ast.NotIn: (r"\bnot\s+in\b", "in"),
}
BINARY = {ast.Add: ("+", "-"), ast.Sub: ("-", "+"), ast.Mult: ("*", "/"), ast.Div: ("/", "*")}
BOOL = {ast.And: (r"\band\b", "or"), ast.Or: (r"\bor\b", "and")}


@dataclass
class Mutant:
    path: str
    line: int
    start: int
    end: int
    original: str
    replacement: str
    status: str = "pending"

    def apply(self, text):
        return text[: self.start] + self.replacement + text[self.end :]

    def describe(self):
        return f"`{self.original.strip()}` -> `{self.replacement.strip()}`"


class _Offsets:
    """ast columns are UTF-8 byte offsets; convert them to str indexes."""

    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    def __call__(self, lineno, col):
        line = self.lines[lineno - 1].encode("utf-8")
        return self.starts[lineno - 1] + len(line[:col].decode("utf-8", errors="replace"))


def _span(off, node):
    return off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)


def find_mutants(path, text, lines):
    """All mutants whose node starts on one of `lines` (a set of 1-based ints)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    off = _Offsets(text)
    src = text.splitlines()
    out = []

    def add(line, start, end, replacement):
        if line in lines and IGNORE not in src[line - 1]:
            out.append(Mutant(path, line, start, end, text[start:end], replacement))

    def swap_in_gap(line, left, right, pattern, replacement):
        """Replace the operator that sits between two nodes."""
        a, b = _span(off, left)[1], _span(off, right)[0]
        gap = text[a:b]
        m = re.search(pattern if pattern.startswith("\\") else re.escape(pattern), gap)
        # "<" must not match the "<" inside "<=", nor "*" inside "**"
        if m and gap[m.end() : m.end() + 1] not in ("=", "*") and gap[m.start() - 1 : m.start()] != "*":
            add(line, a + m.start(), a + m.end(), replacement)

    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line is None:
            continue
        if isinstance(node, ast.Compare):
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                if type(op) in COMPARE:
                    swap_in_gap(line, left, right, *COMPARE[type(op)])
                left = right
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            swap_in_gap(line, node.left, node.right, *BINARY[type(node.op)])
        elif isinstance(node, ast.AugAssign) and type(node.op) in BINARY:
            sym, rep = BINARY[type(node.op)]
            swap_in_gap(line, node.target, node.value, sym + "=", rep + "=")
        elif isinstance(node, ast.BoolOp):
            for left, right in zip(node.values, node.values[1:]):
                swap_in_gap(line, left, right, *BOOL[type(node.op)])
        elif isinstance(node, ast.Constant):
            if node.value is True or node.value is False:
                add(line, *_span(off, node), str(not node.value))
            elif type(node.value) is int:
                add(line, *_span(off, node), str(node.value + 1))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            a, b = _span(off, node.operand)
            add(line, *_span(off, node), text[a:b])
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                add(line, *_span(off, node.value), "None")
        elif isinstance(node, (ast.If, ast.While)):
            a, b = _span(off, node.test)
            add(line, a, b, f"not ({text[a:b]})")

    seen, result = set(), []
    for m in sorted(out, key=lambda m: (m.line, m.start)):
        key = (m.start, m.end, m.replacement)
        if key in seen:
            continue
        seen.add(key)
        try:
            compile(m.apply(text), path, "exec")
        except (SyntaxError, ValueError):
            continue
        result.append(m)
    return result
