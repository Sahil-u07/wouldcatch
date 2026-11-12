import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_javascript")
pytest.importorskip("tree_sitter_typescript")

from wouldcatch.mutate_js import find_mutants  # noqa: E402


def muts(src, path="x.js", lines=None):
    lines = lines or set(range(1, src.count("\n") + 2))
    return {(m.line, m.original.strip(), m.replacement.strip()) for m in find_mutants(path, src, lines)}


def test_operators_constants_and_returns():
    got = muts(
        "function f(a, b) {\n"
        "  if (a >= 100 && b) {\n"
        "    return a - 10;\n"
        "  }\n"
        "  total += 1;\n"
        "  return a === b ? true : !a;\n"
        "}\n"
    )
    assert (2, ">=", ">") in got
    assert (2, "&&", "||") in got
    assert (2, "100", "101") in got
    assert (2, "(a >= 100 && b)", "(!(a >= 100 && b))") in got
    assert (3, "-", "+") in got
    assert (3, "a - 10", "undefined") in got
    assert (5, "+=", "-=") in got
    assert (6, "===", "!==") in got
    assert (6, "true", "false") in got
    assert (6, "!a", "a") in got


def test_only_code_is_mutated_not_comments_strings_regex_or_templates():
    src = (
        "// a + b === c\n"
        "const s = 'x < y && z';\n"
        "const r = /a+b*/;\n"
        "const t = `1 + ${n}`;\n"
        "/* 5 > 3 */\n"
    )
    assert muts(src) == set()


def test_only_changed_lines_and_ignore_comment():
    src = "let a = 1;\nlet b = 2; // wouldcatch: ignore\nlet c = 3;\n"
    assert {line for line, _, _ in muts(src)} == {1, 3}
    assert {line for line, _, _ in muts(src, lines={3})} == {3}


def test_operator_on_its_own_line_is_attributed_to_that_line():
    src = "const x = (\n  a\n  + b\n);\n"
    assert muts(src, lines={3}) == {(3, "+", "-")}
    assert muts(src, lines={2}) == set()


def test_math_min_max_and_loop_break_continue():
    got = muts(
        "for (const i of xs) {\n"
        "  if (i) break;\n"
        "  continue;\n"
        "}\n"
        "const m = Math.max(a, b);\n"
        "const n = other.max(a, b);\n"
    )
    assert (2, "break", "continue") in got
    assert (3, "continue", "break") in got
    assert (5, "max", "min") in got
    assert not any(line == 6 for line, _, _ in got)


def test_break_in_switch_is_left_alone():
    # `continue` inside a switch that is not in a loop is a syntax error, not a mutant.
    src = "switch (x) {\n  case 1:\n    break;\n}\n"
    assert not any(orig == "break" for _, orig, _ in muts(src))
    looped = "for (;;) {\n  switch (x) {\n    case 1:\n      break;\n  }\n}\n"
    assert not any(orig == "break" for _, orig, _ in muts(looped))


def test_typescript_generics_types_and_jsx_are_not_operators():
    ts = "function f<T extends object>(a: Array<number>, b: number): boolean {\n  return a.length > b;\n}\n"
    got = muts(ts, path="x.ts")
    assert {(line, orig) for line, orig, _ in got} == {(2, ">")}
    tsx = "const el = <div className=\"a\">{n > 1 ? <b>x</b> : null}</div>;\n"
    assert {orig for _, orig, _ in muts(tsx, path="x.tsx")} == {">", "1"}


def test_typescript_skips_mutants_that_would_only_be_type_errors():
    ts = "function f(a: number): string {\n  return 'n=' + a;\n}\n"
    assert muts(ts, path="x.ts") == set()
    assert (2, "+", "-") in muts("function f(a) {\n  return 'n=' + a;\n}\n")


def test_unicode_offsets_and_formatting_kept():
    src = "const name = 'héllo'; const ok = name.length > 3; // keep me\n"
    (m,) = [m for m in find_mutants("x.js", src, {1}) if m.original == ">"]
    assert m.apply(src) == "const name = 'héllo'; const ok = name.length >= 3; // keep me\n"


def test_file_with_syntax_error_gives_nothing():
    assert muts("function (((\n") == set()


def test_typescript_number_arithmetic_is_still_mutated():
    ts = "function f(a: number, b: number): number {\n  return a + b;\n}\n"
    assert muts(ts, path="x.ts") == {(2, "+", "-")}


def test_integer_constants_only():
    got = muts("const a = 0;\nconst b = 1.5;\nconst c = 0x10;\nconst d = 1_000;\n")
    assert got == {(1, "0", "1")}


def test_modulo_and_exponent():
    got = muts("const a = x % 2;\nconst b = x ** 2;\ny %= 3;\n")
    assert (1, "%", "*") in got
    assert (2, "**", "*") in got
    assert (3, "%=", "*=") in got
