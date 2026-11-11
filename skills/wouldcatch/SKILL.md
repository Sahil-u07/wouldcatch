---
name: wouldcatch
description: After changing Python code, check that the tests would catch a bug in the changed lines, and add tests for any they would miss. Use after writing or editing Python code, before committing.
---

# wouldcatch

1. Run `wouldcatch --json` in the repo root. If it is not installed, run `pipx install git+https://github.com/Sahil-u07/wouldcatch` first.
2. If it exits with code 2, the tests already fail or this is not a git repo. Fix that first.
3. For each mutant with `"status": "missed"`: read the `file`, `line`, `original` and `mutated` fields. Write a test that passes on the real code and would fail if `original` were replaced by `mutated`.
4. Run `wouldcatch --json` again. Repeat until `"missed"` is 0.

Rules:
- Never change the source code to make a mutant disappear. Only add or improve tests.
- If a missed mutant changes nothing observable (for example a log interval), add `# wouldcatch: ignore` to that line and say why in your reply.
- Use `--cmd` to run only the relevant test file when the full suite is slow.
