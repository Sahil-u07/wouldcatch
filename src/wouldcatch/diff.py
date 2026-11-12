"""Find which Python lines changed, using git."""

import re
import subprocess
from pathlib import Path

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git(*args, cwd="."):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def repo_root(cwd="."):
    return Path(git("rev-parse", "--show-toplevel", cwd=cwd).strip())


def is_test_file(path):
    p = Path(path)
    return (
        p.name.startswith("test_")
        or p.name in ("test.py", "tests.py")
        or p.name.endswith("_test.py")
        or p.name == "conftest.py"
        or any(part in ("tests", "test") for part in p.parts[:-1])
    )


def untracked(root):
    out = git("ls-files", "--others", "--exclude-standard", "--", "*.py", cwd=root)
    return [line for line in out.splitlines() if line]


def pick_base(root):
    """Uncommitted changes if there are any; on a feature branch, everything since
    it split from main; otherwise the last commit."""
    dirty = git("diff", "--name-only", "HEAD", "--", "*.py", cwd=root).strip()
    if dirty or untracked(root):
        return "HEAD"
    head = git("rev-parse", "HEAD", cwd=root).strip()
    for trunk in ("main", "master", "origin/main", "origin/master"):
        try:
            fork = git("merge-base", "HEAD", trunk, cwd=root).strip()
        except RuntimeError:
            continue
        if fork != head:
            return fork
        break  # HEAD is on the trunk itself
    return "HEAD~1"


def changed_lines(root, base):
    """Return {path: set of changed line numbers} for non-test .py files."""
    out = git("diff", "-U0", "--no-color", "--no-ext-diff", base, "--", "*.py", cwd=root)
    changes, path = {}, None
    for line in out.splitlines():
        if line.startswith("+++ "):
            path = None if line == "+++ /dev/null" else line[6:]
        elif path and (m := HUNK.match(line)):
            start, count = int(m.group(1)), int(m.group(2) or 1)
            changes.setdefault(path, set()).update(range(start, start + count))
    if base == "HEAD":
        for path in untracked(root):
            n = len((root / path).read_text(encoding="utf-8", errors="replace").splitlines())
            changes[path] = set(range(1, n + 1))
    return {p: ls for p, ls in changes.items() if ls and not is_test_file(p)}
