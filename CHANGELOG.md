# Changelog

## 0.2.1

Fixes from an outside code review. Every item has a regression test.

- Operators are now found with Python's tokenizer, not a text search. An operator inside a comment can no longer be "mutated" (which gave a false MISSED), and an operator on a continuation line of a multi-line expression is mutated when that line changes.
- Works when installed with pipx: the default test command now uses the project's Python (active virtualenv, `.venv`/`venv` in the repo, or `python` on PATH) instead of wouldcatch's own isolated interpreter.
- Crash recovery is safer: the backup now lives inside `.git`, is written atomically, and restoring it only ever writes `.py` files inside the repo.
- Two runs in the same repo can't collide: a second run stops with a clear message.
- Timeouts show as `timeout` instead of `caught`, and a run cut short by `--max` says it's a partial result (`"complete": false` in JSON).
- `--max` must be at least 1.
- `test.py` and `tests.py` count as test files and are never mutated.

## 0.2.0

- GitHub Action: `uses: Sahil-u07/wouldcatch@v0.2.0`. Missed mutants show up as warnings on the exact lines of the pull request.
- `--github` prints GitHub annotations; it turns on by itself inside GitHub Actions (never in `--json` mode).
- On a clean feature branch, the default base is now the point where the branch left `main` or `master`, so every commit on the branch is checked, not just the last one.
- New mutations: `min` <-> `max` (#1), `break` <-> `continue` (#3).
- Prints a time estimate before running mutants (#2).

## 0.1.0

First release.

- Mutates only the Python lines in your git diff (uncommitted changes, the last commit, or `--base REF`).
- Mutations: comparison operators, `+ - * /` and their `+=` forms, `and`/`or`, `not` removal, `True`/`False`, integer constants, return values, `if`/`while` conditions.
- Restores every file after each run, including after Ctrl+C or a killed process.
- `--json` output for scripts and AI agents, exit code `1` when a bug is missed.
- `# wouldcatch: ignore` skips a line.
