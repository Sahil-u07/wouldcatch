from wouldcatch.mutate import find_mutants


def muts(src, lines=None):
    lines = lines or set(range(1, src.count("\n") + 2))
    return {(m.line, m.original.strip(), m.replacement.strip()) for m in find_mutants("x.py", src, lines)}


def test_compare_ops():
    got = muts("a < b\na <= b\na == b\na is not b\na not in b\n")
    assert (1, "<", "<=") in got
    assert (2, "<=", "<") in got
    assert (3, "==", "!=") in got
    assert (4, "is not", "is") in got
    assert (5, "not in", "in") in got


def test_lt_does_not_match_inside_lte_or_star_inside_pow():
    got = muts("a <= b\nc = a ** b\n")
    assert (1, "<", "<=") not in got
    assert not any(orig == "*" for _, orig, _ in got)


def test_arith_bool_const_return_if():
    got = muts("def f(a, b):\n    x = a + b\n    x += 1\n    if a and b:\n        return True\n    return x\n")
    assert (2, "+", "-") in got
    assert (3, "+=", "-=") in got
    assert (3, "1", "2") in got
    assert (4, "and", "or") in got
    assert (4, "a and b", "not (a and b)") in got
    assert (5, "True", "False") in got
    assert (6, "x", "None") in got


def test_only_changed_lines_and_ignore_pragma():
    src = "a = 1\nb = 2  # wouldcatch: ignore\nc = 3\n"
    assert {line for line, _, _ in muts(src)} == {1, 3}
    assert {line for line, _, _ in muts(src, {3})} == {3}


def test_unicode_columns_and_formatting_kept():
    src = 'name = "héllo"; ok = len(name) > 3  # keep me\n'
    (m,) = [m for m in find_mutants("x.py", src, {1}) if m.original == ">"]
    assert m.apply(src) == 'name = "héllo"; ok = len(name) >= 3  # keep me\n'


def test_syntax_error_file_gives_nothing():
    assert muts("def (:\n") == set()


def test_false_and_return_constants():
    got = muts("def f():\n    if x:\n        return 5\n    return None\nok = False\n")
    assert (3, "5", "None") in got
    assert not any(line == 4 and rep == "None" for line, _, rep in got)
    assert (5, "False", "True") in got


def test_describe_shortens_long_code():
    (m,) = [m for m in find_mutants("x.py", "def f():\n    return " + "a" * 80 + "\n", {2})]
    assert len(m.describe()) < 100 and "..." in m.describe()


def test_crlf_and_form_feed_offsets():
    src = "a = 1\r\n\x0cb = x < y\r\n"
    (m,) = [m for m in find_mutants("x.py", src, {2}) if m.original == "<"]
    assert m.apply(src) == "a = 1\r\n\x0cb = x <= y\r\n"


def test_min_max_swap():
    got = muts("a = max(x, y)\nb = min(x, y)\nc = mymax(x)\n")
    assert (1, "max", "min") in got
    assert (2, "min", "max") in got
    assert not any(line == 3 for line, _, _ in got)


def test_break_continue_swap():
    got = muts("for i in x:\n    if i:\n        break\n    continue\n")
    assert (3, "break", "continue") in got
    assert (4, "continue", "break") in got
