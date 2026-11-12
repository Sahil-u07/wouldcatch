"""Plant small bugs in JavaScript and TypeScript, only on the lines you choose.

Needs the optional tree-sitter packages: pip install "wouldcatch[js]".
Same idea as mutate.py: each mutant is a text edit, the rest of the file is untouched.
"""

from pathlib import PurePath

from .mutate import IGNORE, Mutant

SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
TYPED = {".ts", ".tsx", ".mts", ".cts"}

BINARY = {
    "===": "!==", "!==": "===", "==": "!=", "!=": "==",
    "<": "<=", "<=": "<", ">": ">=", ">=": ">",
    "+": "-", "-": "+", "*": "/", "/": "*", "%": "*", "**": "*",
    "&&": "||", "||": "&&",
}
AUGMENTED = {"+=": "-=", "-=": "+=", "*=": "/=", "/=": "*=", "%=": "*=", "**=": "*="}
SWAP_CALL = {"min": "max", "max": "min"}
LOOPS = {"for_statement", "for_in_statement", "while_statement", "do_statement"}
# A `break` directly inside one of these is not a loop exit (or has no loop at all).
NOT_A_LOOP = {"switch_statement", "function_declaration", "function_expression", "arrow_function",
              "method_definition", "generator_function", "generator_function_declaration"}

_parsers = {}


def available():
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_javascript  # noqa: F401
        import tree_sitter_typescript  # noqa: F401
    except ImportError:
        return False
    return True


def _parser(suffix):
    kind = "tsx" if suffix == ".tsx" else "ts" if suffix in TYPED else "js"
    if kind not in _parsers:
        import tree_sitter_javascript
        import tree_sitter_typescript
        from tree_sitter import Language, Parser
        grammar = {"js": tree_sitter_javascript.language, "ts": tree_sitter_typescript.language_typescript,
                   "tsx": tree_sitter_typescript.language_tsx}[kind]
        _parsers[kind] = Parser(Language(grammar()))
    return _parsers[kind]


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _in_loop(node):
    """True if the nearest enclosing loop/switch/function is a loop."""
    node = node.parent
    while node is not None:
        if node.type in LOOPS:
            return True
        if node.type in NOT_A_LOOP:
            return False
        node = node.parent
    return False


def find_mutants(path, text, lines):
    """All mutants whose changed code sits on one of `lines` (a set of 1-based ints)."""
    suffix = PurePath(path).suffix
    parser = _parser(suffix)
    data = text.encode("utf-8")
    tree = parser.parse(data)
    if tree.root_node.has_error:
        return []
    src = data.split(b"\n")
    out = []

    def char(byte):  # tree-sitter counts bytes, Mutant counts characters
        return len(data[:byte].decode("utf-8", errors="replace"))

    def add(node, replacement, end=None):
        line = node.start_point[0] + 1
        if line in lines and IGNORE.encode() not in src[line - 1]:
            start, stop = char(node.start_byte), char(end if end is not None else node.end_byte)
            out.append(Mutant(path, line, start, stop, text[start:stop], replacement))

    for node in _walk(tree.root_node):
        kind = node.type
        if kind == "binary_expression":
            op = node.child_by_field_name("operator")
            if op is not None and op.type in BINARY:
                texty = any(c.type in ("string", "template_string") for c in node.named_children)
                if not (op.type == "+" and texty and suffix in TYPED):  # "a" - b is a TS type error
                    add(op, BINARY[op.type])
        elif kind == "augmented_assignment_expression":
            op = node.child_by_field_name("operator")
            if op is not None and op.type in AUGMENTED:
                add(op, AUGMENTED[op.type])
        elif kind in ("true", "false"):
            add(node, "false" if kind == "true" else "true")
        elif kind == "number":
            digits = text[char(node.start_byte):char(node.end_byte)]
            if digits.isdigit() and (digits == "0" or not digits.startswith("0")):
                add(node, str(int(digits) + 1))
        elif kind == "unary_expression":
            op, arg = node.child_by_field_name("operator"), node.child_by_field_name("argument")
            if op is not None and op.type == "!" and arg is not None:
                add(node, text[char(arg.start_byte):char(arg.end_byte)])
        elif kind == "return_statement" and suffix not in TYPED:
            # In TypeScript, `return undefined` is often a type error, which ts-jest reports
            # as a failing test: that would be a fake "caught".
            value = next((c for c in node.named_children if c.type != "comment"), None)
            if value is not None and value.type not in ("undefined", "null"):
                add(value, "undefined")
        elif kind == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "member_expression":
                obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
                if obj is not None and prop is not None and obj.type == "identifier" \
                        and data[obj.start_byte:obj.end_byte] == b"Math":
                    name = data[prop.start_byte:prop.end_byte].decode()
                    if name in SWAP_CALL:
                        add(prop, SWAP_CALL[name])
        elif kind in ("break_statement", "continue_statement"):
            # Only unlabeled ones in a real loop: `continue` inside a switch is a syntax error.
            if node.named_child_count == 0 and _in_loop(node):
                word = node.child(0)
                add(word, "continue" if kind == "break_statement" else "break")
        elif kind in ("if_statement", "while_statement"):
            cond = node.child_by_field_name("condition")
            if cond is not None and cond.type == "parenthesized_expression":
                inner = text[char(cond.start_byte) + 1:char(cond.end_byte) - 1]
                add(cond, f"(!({inner}))")

    seen, result = set(), []
    for m in sorted(out, key=lambda m: (m.line, m.start)):
        key = (m.start, m.end, m.replacement)
        if key in seen:
            continue
        seen.add(key)
        if parser.parse(m.apply(text).encode("utf-8")).root_node.has_error:
            continue
        result.append(m)
    return result
