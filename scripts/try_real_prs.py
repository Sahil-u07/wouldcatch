"""Run wouldcatch on real merged commits from popular Python projects.

Usage (Windows PowerShell, macOS or Linux):
    py scripts/try_real_prs.py          # Windows
    python3 scripts/try_real_prs.py     # macOS / Linux

Needs Python 3.10+ and git. Everything goes into a "wouldcatch-real" folder
next to this script. Results are written to wouldcatch-real/results.md.
Expect 10 to 40 minutes: each mutant is one run of the project's tests.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# (repo, commit). Each commit changes real logic, not docs or typing.
TARGETS = [
    ("pallets/click", "c53d373"),  # Fix show_envvar output for a sequence or an empty envvar
    ("pallets/click", "f8c5a8e"),  # Print \x04 and \x1a input bytes as ^D and ^Z in CliRunner
    ("pallets/click", "90a2973"),  # Add context_settings parameter to CliRunner.invoke
    ("Textualize/rich", "7ef2d05"),  # fix inline code in table cells
    ("Textualize/rich", "69cee6e"),  # preserve newlines
]
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
        run([venv_python(venv), "-m", "pip", "install", "-q", "-e", str(src), "pytest", WOULDCATCH])
        ready.touch()
    return src, venv_python(venv)


def try_commit(repo, commit):
    src, py = setup(repo)
    run(["git", "checkout", "-q", "--force", commit], cwd=src)
    changed = run(["git", "diff", "--name-only", f"{commit}^", commit], cwd=src).stdout.split()
    tests = [f for f in changed if f.endswith(".py") and "test" in Path(f).name]
    target = " ".join(tests) if tests else "tests"
    cmd = f'"{py}" -m pytest -q -x -p no:cacheprovider {target}'
    out = run([py, "-m", "wouldcatch", "--base", f"{commit}^", "--cmd", cmd, "--json", "--max", "40"],
              cwd=src, check=False)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": (out.stderr or out.stdout).strip()[-500:]}


def main():
    HERE.mkdir(exist_ok=True)
    lines = ["# wouldcatch on real commits\n"]
    for repo, commit in TARGETS:
        print(f"\n== {repo} @ {commit}")
        subject = ""
        try:
            res = try_commit(repo, commit)
            subject = run(["git", "log", "-1", "--format=%s", commit], cwd=HERE / repo.split("/")[1]).stdout.strip()
        except subprocess.CalledProcessError as e:
            res = {"error": (e.stderr or str(e)).strip()[-500:]}
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
