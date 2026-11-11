# Changelog

## 0.1.0

First release.

- Mutates only the Python lines in your git diff (uncommitted changes, the last commit, or `--base REF`).
- Mutations: comparison operators, `+ - * /` and their `+=` forms, `and`/`or`, `not` removal, `True`/`False`, integer constants, return values, `if`/`while` conditions.
- Restores every file after each run, including after Ctrl+C or a killed process.
- `--json` output for scripts and AI agents, exit code `1` when a bug is missed.
- `# wouldcatch: ignore` skips a line.
