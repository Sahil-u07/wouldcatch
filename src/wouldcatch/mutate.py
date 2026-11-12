"""Plant small bugs in Python source, only on the lines you choose.

Each mutant is a text edit (start, end, replacement) so the rest of the
file, comments and formatting included, stays exactly as written.
"""

import ast
import bisect
import io
import re
import tokenize
from dataclasses import dataclass

IGNORE = "wouldcatch: ignore"

# operator -> (the tokens it is written as, what to write instead)
COMPARE = {
    ast.Eq: (["=="], "!="), ast.NotEq: (["!="], "=="),
    ast.Lt: (["<"], "<="), ast.LtE: (["<="], "<"),
    ast.Gt: ([">"], ">="), ast.GtE: ([">="], ">"),
    ast.Is: (["is"], "is not"), ast.IsNot: (["is", "not"], "is"),
    ast.In: (["in"], "not in"), ast.NotIn: (["not", "in"], "in"),
}
BINARY = {ast.Add: (["+"], "-"), ast.Sub: (["-"], "+"), ast.Mult: (["*"], "/"), ast.Div: (["/"], "*")}
BOOL = {ast.And: (["and"], "or"), ast.Or: (["or"], "and")}
SWAP_CALL = {"min": "max", "max": "min"}


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

    def describe(self, width=40):
        short = lambda s: s if len(s) <= width else s[: width - 3] + "..."
        return f"`{short(' '.join(self.original.split()))}` -> `{short(' '.join(self.replacement.split()))}`"


class _Offsets:
    """ast columns are UTF-8 byte offsets; convert them to str indexes."""

    def __init__(self, text):
        # Only \r\n, \r and \n end a line for ast; str.splitlines also splits on \f etc.
        self.lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    def __call__(self, lineno, col):
        line = self.lines[lineno - 1].encode("utf-8")
        return self.starts[lineno - 1] + len(line[:col].decode("utf-8", errors="replace"))


def _span(off, node):
    return off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)


def _code_tokens(text, off):
    """Operator and keyword tokens as (start, end, string). Comments and strings are
    their own token types, so an operator inside them is never picked."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text, newline="").readline):
        if tok.type in (tokenize.OP, tokenize.NAME):
            (r1, c1), (r2, c2) = tok.start, tok.end
            out.append((off.starts[r1 - 1] + c1, off.starts[r2 - 1] + c2, tok.string))
    return out


def find_mutants(path, text, lines):
    """All mutants whose changed code sits on one of `lines` (a set of 1-based ints)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    off = _Offsets(text)
    tokens = _code_tokens(text, off)  # ast.parse accepted it, so tokenizing can't fail
    token_starts = [t[0] for t in tokens]  # wouldcatch: ignore (ends would find the same operator)
    src = [line.rstrip("\r\n") for line in off.lines]
    out = []

    def add(start, end, replacement):
        line = bisect.bisect_right(off.starts, start)  # the line the edited code is on
        if line in lines and IGNORE not in src[line - 1]:
            out.append(Mutant(path, line, start, end, text[start:end], replacement))

    def swap_in_gap(left, right, words, replacement):
        """Replace the operator between two nodes. Between the left operand's end and
        the right's start there are only brackets and the operator itself, so the
        first matching token run after the left operand is the operator."""
        n = len(words)
        for i in range(bisect.bisect_left(token_starts, _span(off, left)[1]), len(tokens)):
            if [t[2] for t in tokens[i : i + n]] == words:
                add(tokens[i][0], tokens[i + n - 1][1], replacement)
                return

    for node in ast.walk(tree):
        if not hasattr(node, "lineno"):
            continue
        if isinstance(node, ast.Compare):
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                if type(op) in COMPARE:
                    swap_in_gap(left, right, *COMPARE[type(op)])
                left = right
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            swap_in_gap(node.left, node.right, *BINARY[type(node.op)])
        elif isinstance(node, ast.AugAssign) and type(node.op) in BINARY:
            (sym,), rep = BINARY[type(node.op)]
            swap_in_gap(node.target, node.value, [sym + "="], rep + "=")
        elif isinstance(node, ast.BoolOp):
            for left, right in zip(node.values, node.values[1:]):
                swap_in_gap(left, right, *BOOL[type(node.op)])
        elif isinstance(node, ast.Constant):
            if node.value is True or node.value is False:
                add(*_span(off, node), str(not node.value))
            elif type(node.value) is int:
                add(*_span(off, node), str(node.value + 1))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            a, b = _span(off, node.operand)
            add(*_span(off, node), text[a:b])
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                add(*_span(off, node.value), "None")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SWAP_CALL:
            add(*_span(off, node.func), SWAP_CALL[node.func.id])
        elif isinstance(node, ast.Break):
            add(*_span(off, node), "continue")
        elif isinstance(node, ast.Continue):
            add(*_span(off, node), "break")
        elif isinstance(node, (ast.If, ast.While)):
            a, b = _span(off, node.test)
            add(a, b, f"not ({text[a:b]})")

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
