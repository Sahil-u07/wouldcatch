import json
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


def test_strong_tests_catch_everything(repo, capsys):
    (repo / "test_calc.py").write_text(STRONG_TEST)
    code, out = run(capsys)
    assert out["missed"] == 0, [m for m in out["mutants"] if m["status"] == "missed"]
    assert code == 0


def test_failing_baseline_stops(repo, capsys):
    (repo / "test_calc.py").write_text("def test_bad():\n    assert False\n")
    assert main(["--cmd", f'"{sys.executable}" -m pytest -q']) == 2


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
