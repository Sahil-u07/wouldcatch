"""wouldcatch: would your tests catch a bug in the lines you just changed?"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

from . import __version__
from .diff import changed_lines, pick_base, repo_root
from .mutate import find_mutants

BACKUP = ".wouldcatch-backup.json"
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
if COLOR and os.name == "nt":
    os.system("")  # turns on ANSI colors in the classic Windows console
DEFAULT_CMD = f'"{sys.executable}" -m pytest -x -q -p no:cacheprovider'


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


def restore_stale_backup(root):
    """If a previous run was killed mid-mutation, put the original file back."""
    backup = root / BACKUP
    if backup.exists():
        for path, text in json.loads(backup.read_text(encoding="utf-8")).items():
            write(root / path, text)
            print(f"wouldcatch: restored {path} from an interrupted run", file=sys.stderr)
        backup.unlink()


def test_mutant(m, root, cmd, timeout):
    target, backup = root / m.path, root / BACKUP
    original = read(target)
    backup.write_text(json.dumps({m.path: original}), encoding="utf-8")
    try:
        write(target, m.apply(original))
        result = run_tests(cmd, root, timeout)
    finally:
        write(target, original)
        backup.unlink()
    return {"passed": "missed", "failed": "caught", "timeout": "caught"}[result]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wouldcatch", description=__doc__)
    ap.add_argument("--base", help="git ref to diff against (default: uncommitted changes, else last commit)")
    ap.add_argument("--cmd", default=DEFAULT_CMD, help="test command (default: pytest)")
    ap.add_argument("--max", type=int, default=50, help="max mutants to try (default: 50)")
    ap.add_argument("--json", action="store_true", help="print results as JSON (for scripts and AI agents)")
    ap.add_argument("--all", action="store_true", help="list caught mutants too")
    ap.add_argument("--version", action="version", version=f"wouldcatch {__version__}")
    args = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # still runs the restore in `finally`
    log = (lambda *a, **k: None) if args.json else (lambda *a, **k: print(*a, file=sys.stderr, **k))

    try:
        root = repo_root()
    except RuntimeError as e:
        print(f"wouldcatch: {e}", file=sys.stderr)
        return 2
    restore_stale_backup(root)
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

    log(f"wouldcatch: {len(mutants)} mutants on {sum(map(len, changes.values()))} changed lines "
        f"in {len(changes)} file(s), base {base}")
    t0 = time.time()
    if run_tests(args.cmd, root, None) != "passed":
        print("wouldcatch: your tests fail before any change. Fix them first.\n"
              f"  command: {args.cmd}", file=sys.stderr)
        return 2
    timeout = max(10.0, 3 * (time.time() - t0))

    for i, m in enumerate(mutants, 1):
        log(f"  [{i}/{len(mutants)}] {m.path}:{m.line} {m.describe()}", end="\r" if sys.stderr.isatty() else "\n")
        m.status = test_mutant(m, root, args.cmd, timeout)
    if sys.stderr.isatty() and not args.json:
        print(" " * 100, end="\r", file=sys.stderr)

    missed = [m for m in mutants if m.status == "missed"]
    caught = len(mutants) - len(missed)
    if args.json:
        print(json.dumps({
            "base": base, "caught": caught, "missed": len(missed), "skipped": skipped,
            "mutants": [{"file": m.path, "line": m.line, "original": m.original,
                         "mutated": m.replacement, "status": m.status} for m in mutants],
        }, indent=2))
    else:
        for m in mutants:
            if m.status == "missed" or args.all:
                label = paint("MISSED", "1;31") if m.status == "missed" else paint("caught", "32")
                print(f"  {label}  {paint(f'{m.path}:{m.line}', '36')}  {m.describe()}")
        print(paint(f"\n{caught}/{len(mutants)} caught.", "1;32" if not missed else "1"), end=" ")
        if missed:
            print(paint(f"{len(missed)} bug(s) your tests would not notice.", "31"),
                  "Add a test that fails for each MISSED line.")
        else:
            print("Your tests would notice every one of these bugs.")
        if skipped:
            print(f"({skipped} more mutants not tried; raise --max to try them.)")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
