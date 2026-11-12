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
from . import mutate_js
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


def is_js(path):
    return Path(path).suffix in mutate_js.SUFFIXES


def js_test_cmd(root):
    """The project's own test script, run with whichever package manager it uses."""
    if not (root / "package.json").is_file():
        return None  # shortcut: only a package.json at the repo root; monorepos pass --cmd
    for lockfile, cmd in (("pnpm-lock.yaml", "pnpm test"), ("yarn.lock", "yarn test"),
                          ("bun.lock", "bun test"), ("bun.lockb", "bun test")):
        if (root / lockfile).is_file():
            return cmd
    return "npm test"


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


def run_tests(cmd, root, timeout, js=False, show_failure=False):
    """Run the test command. With show_failure, print the end of its output if it fails."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if js:
        env.setdefault("CI", "true")  # stops jest and vitest from starting watch mode
    # A fresh bytecode cache per run, so a stale .pyc can never hide a mutant.
    with tempfile.TemporaryDirectory() as cache:
        env["PYTHONPYCACHEPREFIX"] = cache
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, env=env, timeout=timeout,
                               stdout=subprocess.PIPE if show_failure else subprocess.DEVNULL,
                               stderr=subprocess.STDOUT if show_failure else subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return "timeout"
    if p.returncode != 0 and show_failure:
        tail = p.stdout.decode("utf-8", errors="replace").splitlines()[-15:]
        print("\n".join("  | " + line for line in tail), file=sys.stderr)
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
    """The real path of `rel` if it is a source file inside the repo, else None."""
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target if (target.suffix == ".py" or is_js(target)) and target.is_file() else None


def restore_stale_backup(root, backup):
    """If a previous run was killed mid-mutation, put the original file back.
    The backup is untrusted input: only source files inside this repo are written."""
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
        result = run_tests(cmd, root, timeout, is_js(m.path))
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
    ap.add_argument("--cmd", help="test command (default: pytest for Python, the package.json test script for JS/TS)")
    ap.add_argument("--max", type=positive, default=50, help="max mutants to try (default: 50)")
    ap.add_argument("--allow-partial", action="store_true",
                    help="exit 0 even if --max left some mutants untried (default: exit 3)")
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

    mutants, no_parser = [], []
    for path, lines in sorted(changes.items()):
        if is_js(path) and not mutate_js.available():
            no_parser.append(path)
            continue
        finder = mutate_js.find_mutants if is_js(path) else find_mutants
        mutants += finder(path, read(root / path), lines)
    if no_parser:
        log(f"wouldcatch: skipped {len(no_parser)} JavaScript/TypeScript file(s). "
            'To check them too: pip install "wouldcatch[js]"')
    skipped = max(0, len(mutants) - args.max)
    mutants = mutants[: args.max]

    if not mutants:
        msg = f"no mutable lines changed since {base}"
        print(json.dumps({"base": base, "mutants": [], "message": msg}) if args.json else f"wouldcatch: {msg}")
        return 0

    # One test command per language, unless --cmd overrides both.
    cmds = {}
    for js in sorted({is_js(m.path) for m in mutants}):
        if args.cmd is not None:
            cmds[js] = args.cmd
        elif js:
            cmds[js] = js_test_cmd(root)
            if cmds[js] is None:
                print("wouldcatch: no package.json at the repo root, so I don't know how to run your "
                      'JavaScript tests. Pass --cmd "your test command".', file=sys.stderr)
                return 2
        else:
            py = find_python(root)
            if py is None:
                print("wouldcatch: couldn't find a Python with pytest installed. Activate your project's\n"
                      "virtual environment, install pytest, or pass --cmd \"your test command\".", file=sys.stderr)
                return 2
            cmds[js] = f'"{py}" {PYTEST_ARGS}'
    log(f"wouldcatch: {len(mutants)} mutants on {sum(map(len, changes.values()))} changed lines "
        f"in {len(changes)} file(s), base {base}")
    baselines = {}
    for js, cmd in cmds.items():
        if cmd in baselines:
            continue
        t0 = time.time()
        if run_tests(cmd, root, None, js, show_failure=True) != "passed":
            print("wouldcatch: your tests fail before any change (output above). Fix them first.\n"
                  f"  command: {cmd}", file=sys.stderr)
            return 2
        baselines[cmd] = time.time() - t0  # wouldcatch: ignore (wall-clock time, not testable exactly)
    total = sum(baselines[cmds[is_js(m.path)]] for m in mutants)
    log(f"wouldcatch: about {duration(total)} for {len(mutants)} mutants. Narrow --cmd to go faster.")  # wouldcatch: ignore (log text)

    for i, m in enumerate(mutants, 1):
        log(f"  [{i}/{len(mutants)}] {m.path}:{m.line} {m.describe()}", end="\r" if sys.stderr.isatty() else "\n")
        cmd = cmds[is_js(m.path)]
        m.status = test_mutant(m, root, cmd, timeout_for(baselines[cmd]), backup)
    if sys.stderr.isatty() and not args.json:
        print(" " * 100, end="\r", file=sys.stderr)

    missed = [m for m in mutants if m.status == "missed"]
    timeouts = sum(m.status == "timeout" for m in mutants)
    caught = len(mutants) - len(missed) - timeouts  # a timeout is not proof a test caught it
    if args.json:
        print(json.dumps({
            "base": base, "caught": caught, "missed": len(missed), "timeout": timeouts, "skipped": skipped,
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
            print("No mutant got past your tests." if timeouts else "Your tests would notice every one of these bugs.")
        if timeouts:
            print(paint(f"{timeouts} timed out: the tests hung or ran too long, so those are inconclusive, "
                        "not caught. Use --all to see them.", "33"))
        if skipped:
            print(paint(f"Partial result: {skipped} more mutants not tried. Raise --max to try them"
                        + (" (exit code 3)." if not args.allow_partial else "."), "33"))
        if args.github or os.environ.get("GITHUB_ACTIONS") == "true":
            for m in missed:
                print(annotation(m))
    if missed:
        return 1
    return 3 if skipped and not args.allow_partial else 0


if __name__ == "__main__":
    sys.exit(main())
