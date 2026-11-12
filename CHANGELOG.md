# Changelog

## 0.3.1

- New mutations: `//` -> `/`, `%` -> `*`, `**` -> `*` in Python (string formatting with `%` is left alone), `%` -> `*` and `**` -> `*` in JavaScript and TypeScript, plus their `%=` and `**=` forms.
- When your tests already fail before any mutant is tried, the end of the test output is shown, so you can see why.

## 0.3.0

- JavaScript and TypeScript support (#4): `pip install "wouldcatch[js]"`. Covers `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.mts`, `.cts`.
- Code is parsed with tree-sitter, so operators inside strings, comments, regexes, template literals, type annotations, generics and JSX tags are never mutated.
- The default test command for JS/TS is the `package.json` test script, run with npm, pnpm, yarn or bun depending on the lockfile.
- Test, spec, config, story and `.d.ts` files are never mutated.
- A repo with Python and JS/TS changes gets both checked in one run, each with its own test command.
- Without the `js` extra, JS/TS files are skipped with a hint. The Python core still has zero dependencies.

## 0.2.2

- Timeouts are no longer counted as caught. They get their own count (`"timeout"` in JSON) and a line in the summary.
- A run that `--max` cut short now exits with code 3 instead of 0, so CI can't pass on a partial check. `--allow-partial` (Action input `allow-partial`) restores the old behavior.

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
