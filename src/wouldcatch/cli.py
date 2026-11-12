"""wouldcatch: would your tests catch a bug in the lines you just changed?"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .diff import changed_lines, git, pick_base, repo_root
from .mutate import find_mutants

OLD_BACKUP = ".wouldcatch-backup.json"  # where versions up to 0.2.0 kept it


def use_color(stream):
    return stream.isatty() and not os.environ.get("NO_COLOR")


COLOR = use_color(sys.stdout)
if COLOR and os.name == "nt":
    os.system("")  # turns on ANSI colors in the classic Windows console
PYTEST_ARGS = "-m pytest -x -q -p no:cacheprovider"


def venv_python(venv):
    return os.path.join(venv, "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")


def find_python(root):
    """The interpreter that has the project's pytest. With pipx, wouldcatch's own
    interpreter is an isolated venv without pytest, so look at the project first."""
    candidates = [os.environ.get("VIRTUAL_ENV") and venv_python(os.environ["VIRTUAL_ENV"]),
                  venv_python(root / ".venv"), venv_python(root / "venv"),
                  shutil.which("python"), shutil.which("python3"), sys.executable]
    for py in candidates:
        if py and os.path.isfile(py) and subprocess.run(
                [py, "-c", "import pytest"], capture_output=True).returncode == 0:
            return py
    return None


def positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def read(path):
    with open(path, encoding="utf-8", newline="") as f:  # keep CRLF as-is
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def run_tests(cmd, root, timeout):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # A fresh bytecode cache per run, so a stale .pyc can never hide a mutant.
    with tempfile.TemporaryDirectory() as cache:
        env["PYTHONPYCACHEPREFIX"] = cache
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, env=env, timeout=timeout,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return "timeout"
    return "passed" if p.returncode == 0 else "failed"


def git_path(root, name):
    """A file inside .git, so it never shows up in the working tree or a commit."""
    return Path(root, git("rev-parse", "--git-path", name, cwd=root).strip())


def lock_repo(root):
    """Hold an OS lock for the whole run; the OS frees it if the process dies.
    Returns the open file (keep it), or None if another run holds the lock."""
    f = open(git_path(root, "wouldcatch.lock"), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def inside(root, rel):
    """The real path of `rel` if it is a .py file inside the repo, else None."""
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target if target.suffix == ".py" and target.is_file() else None


def restore_stale_backup(root, backup):
    """If a previous run was killed mid-mutation, put the original file back.
    The backup is untrusted input: only .py files inside this repo are written."""
    for b in (backup, root / OLD_BACKUP):
        if not b.exists():
            continue
        try:
            entries = json.loads(b.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            entries = {}
        for rel, text in entries.items() if isinstance(entries, dict) else ():
            target = inside(root, rel) if isinstance(text, str) else None
            if target is None:
                print(f"wouldcatch: ignored unsafe backup entry {rel!r}", file=sys.stderr)
                continue
            write(target, text)
            print(f"wouldcatch: restored {rel} from an interrupted run", file=sys.stderr)
        b.unlink()


def save_backup(backup, rel, text):
    tmp = backup.with_name(backup.name + ".tmp")
    tmp.write_text(json.dumps({rel: text}), encoding="utf-8")
    os.replace(tmp, backup)  # atomic: a crash leaves the old backup or the new one, never half


def test_mutant(m, root, cmd, timeout, backup):
    target = root / m.path
    original = read(target)
    save_backup(backup, m.path, original)
    try:
        write(target, m.apply(original))
        result = run_tests(cmd, root, timeout)
    finally:
        write(target, original)
        backup.unlink()
    return {"passed": "missed", "failed": "caught", "timeout": "timeout"}[result]


def duration(seconds):
    return f"{seconds:.0f}s" if seconds < 90 else f"{seconds / 60:.0f} min"


def timeout_for(baseline):
    return max(10.0, 3 * baseline)


def annotation(m):
    """A GitHub Actions workflow command: shows up on that line of the PR diff."""
    msg = f"No test fails if {m.describe()} here. Add a test that catches it.".replace("%", "%25")
    path = m.path.replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
    return f"::warning file={path},line={m.line},title=wouldcatch - untested change::{msg}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wouldcatch", description=__doc__)
    ap.add_argument("--base", help="git ref to diff against (default: uncommitted changes, else last commit)")
    ap.add_argument("--cmd", help="test command (default: pytest, run with your project's Python)")
    ap.add_argument("--max", type=positive, default=50, help="max mutants to try (default: 50)")
    ap.add_argument("--json", action="store_true", help="print results as JSON (for scripts and AI agents)")
    ap.add_argument("--all", action="store_true", help="list caught mutants too")
    ap.add_argument("--github", action="store_true",
                    help="also print GitHub Actions annotations (on by default inside GitHub Actions)")
    ap.add_argument("--version", action="version", version=f"wouldcatch {__version__}")
    args = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # still runs the restore in `finally`
    log = (lambda *a, **k: None) if args.json else (lambda *a, **k: print(*a, file=sys.stderr, **k))

    try:
        root = repo_root()
    except RuntimeError as e:
        print(f"wouldcatch: {e}", file=sys.stderr)
        return 2
    lock = lock_repo(root)
    if lock is None:
        print("wouldcatch: another wouldcatch run is already working in this repo.", file=sys.stderr)
        return 2
    backup = git_path(root, "wouldcatch-backup.json")
    restore_stale_backup(root, backup)
    base = args.base or pick_base(root)
    try:
        changes = changed_lines(root, base)
    except RuntimeError as e:
        print(f"wouldcatch: {e}", file=sys.stderr)
        return 2

    mutants = []
    for path, lines in sorted(changes.items()):
        text = read(root / path)
        mutants += find_mutants(path, text, lines)
    skipped = max(0, len(mutants) - args.max)
    mutants = mutants[: args.max]

    if not mutants:
        msg = f"no mutable Python lines changed since {base}"
        print(json.dumps({"base": base, "mutants": [], "message": msg}) if args.json else f"wouldcatch: {msg}")
        return 0

    if args.cmd is None:
        py = find_python(root)
        if py is None:
            print("wouldcatch: couldn't find a Python with pytest installed. Activate your project's\n"
                  "virtual environment, install pytest, or pass --cmd \"your test command\".", file=sys.stderr)
            return 2
        args.cmd = f'"{py}" {PYTEST_ARGS}'
    log(f"wouldcatch: {len(mutants)} mutants on {sum(map(len, changes.values()))} changed lines "
        f"in {len(changes)} file(s), base {base}")
    t0 = time.time()
    if run_tests(args.cmd, root, None) != "passed":
        print("wouldcatch: your tests fail before any change. Fix them first.\n"
              f"  command: {args.cmd}", file=sys.stderr)
        return 2
    baseline = time.time() - t0  # wouldcatch: ignore (wall-clock time, not testable exactly)
    timeout = timeout_for(baseline)
    log(f"wouldcatch: tests take {duration(baseline)}, so about {duration(baseline * len(mutants))} "  # wouldcatch: ignore (log text)
        f"for {len(mutants)} mutants. Narrow --cmd to go faster.")

    for i, m in enumerate(mutants, 1):
        log(f"  [{i}/{len(mutants)}] {m.path}:{m.line} {m.describe()}", end="\r" if sys.stderr.isatty() else "\n")
        m.status = test_mutant(m, root, args.cmd, timeout, backup)
    if sys.stderr.isatty() and not args.json:
        print(" " * 100, end="\r", file=sys.stderr)

    missed = [m for m in mutants if m.status == "missed"]
    caught = len(mutants) - len(missed)
    if args.json:
        print(json.dumps({
            "base": base, "caught": caught, "missed": len(missed), "skipped": skipped,
            "complete": skipped == 0,
            "mutants": [{"file": m.path, "line": m.line, "original": m.original,
                         "mutated": m.replacement, "status": m.status} for m in mutants],
        }, indent=2))
    else:
        for m in mutants:
            if m.status == "missed" or args.all:
                label = {"missed": paint("MISSED", "1;31"), "timeout": paint("timeout", "33")}.get(
                    m.status, paint("caught", "32"))
                print(f"  {label}  {paint(f'{m.path}:{m.line}', '36')}  {m.describe()}")
        print(paint(f"\n{caught}/{len(mutants)} caught.", "1;32" if not missed else "1"), end=" ")
        if missed:
            print(paint(f"{len(missed)} bug(s) your tests would not notice.", "31"),
                  "Add a test that fails for each MISSED line.")
        else:
            print("Your tests would notice every one of these bugs.")
        timeouts = sum(m.status == "timeout" for m in mutants)
        if timeouts:
            print(f"({timeouts} counted as caught because the tests hung or ran too long.)")
        if skipped:
            print(paint(f"Partial result: {skipped} more mutants not tried. Raise --max to try them.", "33"))
        if args.github or os.environ.get("GITHUB_ACTIONS") == "true":
            for m in missed:
                print(annotation(m))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
