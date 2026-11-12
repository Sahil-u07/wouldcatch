import json
import os
import subprocess
import sys

import pytest

from wouldcatch.cli import main

CALC = "def discount(price, is_member):\n    return price\n"
CALC_NEW = (
    "def discount(price, is_member):\n"
    "    if is_member and price >= 100:\n"
    "        return price - 10\n"
    "    return price\n"
)
WEAK_TEST = "from calc import discount\n\ndef test_member():\n    assert discount(200, True) == 190\n"
STRONG_TEST = WEAK_TEST + (
    "\ndef test_edges():\n"
    "    assert discount(100, True) == 90\n"
    "    assert discount(99, True) == 99\n"
    "    assert discount(200, False) == 200\n"
)


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    sh("git", "init", "-q", cwd=tmp_path)
    sh("git", "config", "user.email", "t@t", cwd=tmp_path)
    sh("git", "config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "calc.py").write_text(CALC)
    (tmp_path / "test_calc.py").write_text("from calc import discount\n\ndef test_x():\n    assert discount(5, False) == 5\n")
    sh("git", "add", ".", cwd=tmp_path)
    sh("git", "commit", "-qm", "init", cwd=tmp_path)
    (tmp_path / "calc.py").write_text(CALC_NEW)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *args):
    code = main(["--json", "--cmd", f'"{sys.executable}" -m pytest -q -p no:cacheprovider', *args])
    return code, json.loads(capsys.readouterr().out)


def test_weak_tests_miss_bugs_and_file_is_restored(repo, capsys):
    (repo / "test_calc.py").write_text(WEAK_TEST)
    code, out = run(capsys)
    assert code == 1
    assert out["base"] == "HEAD"
    assert out["missed"] > 0
    assert {m["line"] for m in out["mutants"]} <= {2, 3}  # only the changed lines
    assert (repo / "calc.py").read_text() == CALC_NEW
    assert not (repo / ".wouldcatch-backup.json").exists()
    assert not (repo / ".git" / "wouldcatch-backup.json").exists()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                          text=True).stdout.split() == ["M", "calc.py", "M", "test_calc.py"]  # nothing left behind


def test_strong_tests_catch_everything(repo, capsys):
    (repo / "test_calc.py").write_text(STRONG_TEST)
    code, out = run(capsys)
    assert out["missed"] == 0, [m for m in out["mutants"] if m["status"] == "missed"]
    assert code == 0


def test_failing_baseline_stops(repo, capsys):
    (repo / "test_calc.py").write_text("def test_bad():\n    assert False\n")
    assert main(["--cmd", f'"{sys.executable}" -m pytest -q']) == 2
    err = capsys.readouterr().err
    assert "  | " in err and "test_bad" in err  # shows why the tests failed


def test_last_commit_used_when_tree_is_clean(repo, capsys):
    (repo / "test_calc.py").write_text(STRONG_TEST)
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "feat", cwd=repo)
    code, out = run(capsys)
    assert out["base"] == "HEAD~1" and code == 0 and out["mutants"]


def test_interrupted_run_is_restored(repo, capsys):
    (repo / ".wouldcatch-backup.json").write_text(json.dumps({"calc.py": CALC_NEW}))
    (repo / "calc.py").write_text("broken = (")
    (repo / "test_calc.py").write_text(STRONG_TEST)
    run(capsys)
    assert (repo / "calc.py").read_text() == CALC_NEW


def test_crlf_file_restored_byte_for_byte(repo, capsys):
    crlf = CALC_NEW.replace("\n", "\r\n").encode()
    (repo / "calc.py").write_bytes(crlf)
    (repo / "test_calc.py").write_text(WEAK_TEST)
    run(capsys)
    assert (repo / "calc.py").read_bytes() == crlf


def test_feature_branch_uses_fork_point(repo, capsys):
    (repo / "test_calc.py").write_text(STRONG_TEST)
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "base", cwd=repo)
    trunk = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True).stdout.strip()
    sh("git", "checkout", "-qb", "feature", cwd=repo)
    (repo / "calc.py").write_text(CALC_NEW.replace("10", "20").replace("190", "180"))
    sh("git", "commit", "-qam", "one", cwd=repo)
    (repo / "notes.py").write_text("X = 1\n")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "two", cwd=repo)
    from wouldcatch.diff import changed_lines, pick_base
    base = pick_base(repo)
    fork = subprocess.run(["git", "rev-parse", trunk], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert fork == base
    assert set(changed_lines(repo, base)) == {"calc.py", "notes.py"}  # both commits, not just the last


def test_github_annotations(repo, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    (repo / "test_calc.py").write_text(WEAK_TEST)
    main(["--github", "--cmd", f'"{sys.executable}" -m pytest -q -p no:cacheprovider'])
    out = capsys.readouterr()
    lines = [l for l in out.out.splitlines() if l.startswith("::warning ")]
    assert lines and all("file=calc.py,line=" in l for l in lines)
    assert "about" in out.err  # timing estimate


def test_json_has_no_annotations_even_in_actions(repo, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (repo / "test_calc.py").write_text(WEAK_TEST)
    code, out = run(capsys)  # would raise if annotations broke the JSON
    assert code == 1


def test_no_color_rules():
    from wouldcatch.cli import use_color

    class Tty:
        def isatty(self):
            return True

    class Pipe:
        def isatty(self):
            return False

    import os
    old = os.environ.pop("NO_COLOR", None)
    try:
        assert use_color(Tty()) and not use_color(Pipe())
        os.environ["NO_COLOR"] = "1"
        assert not use_color(Tty())
    finally:
        os.environ.pop("NO_COLOR", None)
        if old is not None:
            os.environ["NO_COLOR"] = old


def test_duration_and_timeout():
    from wouldcatch.cli import duration, timeout_for
    assert duration(89) == "89s"
    assert duration(90) == "2 min"
    assert duration(3000) == "50 min"
    assert timeout_for(1) == 10.0
    assert timeout_for(5) == 15.0


def test_annotations_turn_on_inside_github_actions(repo, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (repo / "test_calc.py").write_text(WEAK_TEST)
    main(["--cmd", f'"{sys.executable}" -m pytest -q -p no:cacheprovider', "--max", "3"])
    assert "::warning " in capsys.readouterr().out


def test_branch_on_trunk_uses_last_commit(repo):
    # HEAD is on "main"; another trunk name ("master") points further back.
    # Being on a trunk must win, so the base is the last commit, not the old fork point.
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "b", cwd=repo)
    (repo / "x.py").write_text("X = 1\n")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "c", cwd=repo)
    sh("git", "branch", "-M", "main", cwd=repo)
    sh("git", "branch", "-f", "master", "HEAD~2", cwd=repo)
    from wouldcatch.diff import pick_base
    assert pick_base(repo) == "HEAD~1"


def test_backup_outside_repo_is_ignored(repo, tmp_path, capsys):
    outside = tmp_path.parent / "victim.py"
    outside.write_text("keep me")
    (repo / ".git" / "wouldcatch-backup.json").write_text(json.dumps({
        "../victim.py": "pwned", "notes.txt": "pwned", "calc.py": CALC_NEW}))
    (repo / "notes.txt").write_text("keep me")
    (repo / "calc.py").write_text("broken = (")
    (repo / "test_calc.py").write_text(STRONG_TEST)
    run(capsys)
    assert outside.read_text() == "keep me"
    assert (repo / "notes.txt").read_text() == "keep me"
    assert (repo / "calc.py").read_text() == CALC_NEW


def test_second_run_is_refused_while_one_is_active(repo, capsys):
    from wouldcatch.cli import lock_repo
    held = lock_repo(repo)
    assert held is not None
    try:
        assert main(["--json"]) == 2
        assert "already working" in capsys.readouterr().err
    finally:
        held.close()
    assert lock_repo(repo) is not None


def test_max_must_be_positive(repo):
    with pytest.raises(SystemExit):
        main(["--max", "0"])


def test_timeout_is_reported_separately(repo, capsys):
    (repo / "test_calc.py").write_text(STRONG_TEST)
    (repo / "original.txt").write_text(CALC_NEW)
    # hangs whenever calc.py is mutated, passes on the original
    slow = (f'"{sys.executable}" -c "import time,pathlib as p; '
            f"time.sleep(30) if p.Path('calc.py').read_text() != p.Path('original.txt').read_text() else None\"")
    main(["--json", "--cmd", slow, "--max", "1"])
    (m,) = json.loads(capsys.readouterr().out)["mutants"]
    assert m["status"] == "timeout"


def test_finds_a_python_with_pytest_even_from_pipx(repo, tmp_path, monkeypatch):
    import venv
    from wouldcatch.cli import find_python, venv_python
    bare = tmp_path / "pipx-like"
    venv.create(bare, with_pip=False)
    monkeypatch.setattr(sys, "executable", venv_python(bare))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "missing"))
    monkeypatch.setenv("PATH", os.path.dirname(sys.__dict__.get("_base_executable", "")) + os.pathsep + os.environ["PATH"])
    py = find_python(repo)
    assert py and py != venv_python(bare)


def test_partial_run_exits_3_unless_allowed(repo, capsys):
    (repo / "test_calc.py").write_text(STRONG_TEST)
    code, out = run(capsys, "--max", "1")
    assert out["missed"] == 0 and out["skipped"] > 0 and out["complete"] is False
    assert code == 3
    code, _ = run(capsys, "--max", "1", "--allow-partial")
    assert code == 0


def test_timeouts_are_not_counted_as_caught(repo, capsys, monkeypatch):
    import wouldcatch.cli as cli
    (repo / "test_calc.py").write_text(STRONG_TEST)
    monkeypatch.setattr(cli, "test_mutant", lambda *a: "timeout")
    code, out = run(capsys)
    assert out["caught"] == 0 and out["missed"] == 0
    assert out["timeout"] == len(out["mutants"]) > 0
    assert code == 0
    main(["--cmd", f'"{sys.executable}" -m pytest -q -p no:cacheprovider'])
    text = capsys.readouterr().out
    assert "0/" in text and "timed out" in text and "would notice every" not in text
