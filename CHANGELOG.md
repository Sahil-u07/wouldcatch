# Changelog

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
