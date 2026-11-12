"""Run wouldcatch on real merged commits from popular Python projects.

Usage (Windows PowerShell, macOS or Linux):
    py scripts/try_real_prs.py          # Windows
    python3 scripts/try_real_prs.py     # macOS / Linux

Needs Python 3.10+ and git. Everything goes into a "wouldcatch-real" folder
next to this script. Results are written to wouldcatch-real/results.md.
Expect 20 to 60 minutes: each mutant is one run of the project's tests.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# repo: (source folder, extra test dependencies). Small, popular, quick to install.
REPOS = {
    "pallets/click": ("src/click", []),
    "pallets/itsdangerous": ("src/itsdangerous", ["freezegun"]),
    "python-humanize/humanize": ("src/humanize", ["freezegun"]),
    "more-itertools/more-itertools": ("more_itertools", []),
}
SKIP = re.compile(r"doc|changelog|typo|typing|\btype\b|mypy|flake8|lint|format|readme|comment|deprecat", re.I)
PER_REPO = 3  # commits to try per repo
MAX_MUTANTS = 15
WOULDCATCH = "git+https://github.com/Sahil-u07/wouldcatch"
HERE = Path(__file__).resolve().parent / "wouldcatch-real"


def run(cmd, cwd=None, check=True):
    print("  $", " ".join(map(str, cmd)))
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def venv_python(venv):
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def setup(repo):
    name = repo.split("/")[1]
    src, venv = HERE / name, HERE / f"venv-{name}"
    if not src.exists():
        run(["git", "clone", "-q", f"https://github.com/{repo}", str(src)])
    ready = venv / "installed.ok"  # only trust a venv whose install finished
    if not ready.exists():
        run([sys.executable, "-m", "venv", "--clear", str(venv)])
        extra = REPOS[repo][1]
        run([venv_python(venv), "-m", "pip", "install", "-q", "-e", str(src), "pytest", WOULDCATCH, *extra])
        ready.touch()
    return src, venv_python(venv)


def is_test(path):
    p = Path(path)
    return "tests" in p.parts or p.name.startswith("test_") or p.name == "conftest.py"


def untested_commits(repo, src):
    """Recent commits that changed source code but no test file: where gaps hide."""
    folder = REPOS[repo][0]
    # origin/HEAD, not HEAD: an earlier run may have left the clone on an old commit
    log = run(["git", "log", "origin/HEAD", "--no-merges", "--format=%h %s", "-n", "200", "--", folder],
              cwd=src).stdout.splitlines()
    picked = []
    for entry in log:
        commit, _, subject = entry.partition(" ")
        if SKIP.search(subject):
            continue
        stat = run(["git", "diff", "--numstat", f"{commit}^", commit], cwd=src, check=False).stdout
        rows = [line.split("\t") for line in stat.splitlines() if line.count("\t") == 2]
        files = [path for _, _, path in rows]
        added = sum(int(a) for a, _, path in rows
                    if a.isdigit() and path.endswith(".py") and path.startswith(folder) and not is_test(path))
        if added >= 3 and not any(is_test(f) for f in files):
            picked.append(commit)
        if len(picked) == PER_REPO:
            break
    return picked


def try_commit(src, py, commit):
    run(["git", "checkout", "-q", "--force", commit], cwd=src)
    cmd = f'"{py}" -m pytest -q -x -p no:cacheprovider tests'
    out = run([py, "-m", "wouldcatch", "--base", f"{commit}^", "--cmd", cmd, "--json", "--max", str(MAX_MUTANTS)],
              cwd=src, check=False)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": (out.stderr or out.stdout).strip()[-500:]}


def main():
    HERE.mkdir(exist_ok=True)
    lines = ["# wouldcatch on real commits\n"]
    for repo in REPOS:
        try:
            src, py = setup(repo)
            commits = untested_commits(repo, src)
        except subprocess.CalledProcessError as e:
            lines.append(f"\n## {repo}\n\nCould not set up: `{(e.stderr or str(e)).strip()[-300:]}`\n")
            continue
        for commit in commits:
            print(f"\n== {repo} @ {commit}")
            subject = run(["git", "log", "-1", "--format=%s", commit], cwd=src).stdout.strip()
            res = try_commit(src, py, commit)
            url = f"https://github.com/{repo}/commit/{commit}"
            lines.append(f"\n## [{repo} {commit}]({url}) {subject}\n")
            if "error" in res:
                lines.append(f"Could not run: `{res['error']}`\n")
            elif not res.get("mutants"):
                lines.append(f"No mutable lines. {res.get('message', '')}\n")
            else:
                lines.append(f"{res['caught']}/{res['caught'] + res['missed']} caught.\n")
                for m in res["mutants"]:
                    if m["status"] == "missed":
                        lines.append(f"- MISSED `{m['file']}:{m['line']}` `{m['original'].strip()}` -> `{m['mutated'].strip()}`")
                lines.append("")
            print("  ", lines[-1] if lines[-1] else lines[-2])
            (HERE / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDone. Results: {HERE / 'results.md'}")


if __name__ == "__main__":
    main()
