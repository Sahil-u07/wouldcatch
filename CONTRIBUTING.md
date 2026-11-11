# Contributing

Thanks for helping. Small PRs get merged fastest.

## Run it locally

```bash
git clone https://github.com/Sahil-u07/wouldcatch
cd wouldcatch
pip install -e . pytest
pytest
```

## Where things live

- `src/wouldcatch/diff.py` finds the changed lines with `git diff`.
- `src/wouldcatch/mutate.py` finds mutants. Each one is a text edit, so formatting and comments stay as written.
- `src/wouldcatch/cli.py` runs the tests per mutant and prints the report.

## Adding a mutation

Add a case in `find_mutants` and a test in `tests/test_mutate.py` that checks the exact `(line, original, replacement)` it produces. Then run `wouldcatch --cmd "pytest -q tests/test_mutate.py"` on your branch: the tool should catch every bug in its own new code.

## Opening a PR

- One change per PR.
- Tests pass (`pytest`).
- Say in the description what you changed and why.
