# wouldcatch

**Would your tests catch a bug in the lines you just changed?** wouldcatch plants small bugs in your git diff, runs your tests, and lists the bugs they miss.

```bash
pipx install git+https://github.com/Sahil-u07/wouldcatch
wouldcatch
```

![wouldcatch finds 3 bugs the tests miss, then 0 after one more test](docs/demo.gif)

Green tests tell you the code ran. They don't tell you the tests would fail if the code were wrong. Coverage has the same blind spot: a line can be "covered" by a test that checks nothing.

Mutation testing answers the real question, but running it on a whole project is slow, so most people never do. wouldcatch only touches the lines in your diff, which makes it fast enough to run before every commit or on every PR.

## How it works

1. Reads `git diff` to find the Python lines you changed (tests are skipped).
2. Makes one small change at a time on those lines: `<` becomes `<=`, `and` becomes `or`, `True` becomes `False`, `100` becomes `101`, a return value becomes `None`, an `if` is flipped.
3. Runs your tests after each change. If they still pass, that bug would have gotten through. That's a **MISSED** line.
4. Puts your file back exactly as it was, every time, even if you hit Ctrl+C.

## Usage

```bash
wouldcatch                          # uncommitted changes, or the last commit if the tree is clean
wouldcatch --base main              # everything on this branch since main
wouldcatch --cmd "pytest tests/unit -x -q"   # your own test command
wouldcatch --json                   # machine-readable, for scripts and AI agents
wouldcatch --all                    # show caught mutants too
```

Exit code is `1` when any bug is missed, `0` when all are caught, `2` on setup errors (not a git repo, tests already failing). That makes it a drop-in CI check.

Skip a line on purpose:

```python
LOG_EVERY = 100  # wouldcatch: ignore
```

## In CI (GitHub Actions)

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- run: pip install git+https://github.com/Sahil-u07/wouldcatch
- run: wouldcatch --base origin/${{ github.base_ref }}
```

## With AI coding agents

Agents write tests that pass, which is not the same as tests that check something. Point your agent at wouldcatch and let the MISSED list tell it which tests to write.

For Claude Code, copy [`skills/wouldcatch`](skills/wouldcatch) into `.claude/skills/` in your project. For other agents, add this to `AGENTS.md`:

```
After changing Python code, run `wouldcatch --json`. For every mutant with
"status": "missed", add a test that fails for that change. Re-run until none are missed.
Do not change the source code to make a mutant go away.
```

## FAQ

**How is this different from mutmut or cosmic-ray?** Those mutate the whole project and are built for full audits. wouldcatch mutates only your diff and needs no config, so you can run it on every change.

**Is it slow?** Each mutant is one run of your test command. A typical change produces 5 to 30 mutants. Use `--cmd` to run only the relevant tests and `--max` to cap the count.

**Will it touch my files?** It edits one file at a time and restores it right after. If the process is killed, the next run restores the file from `.wouldcatch-backup.json` first.

**Other languages?** Python only for now. JS/TS is the next target; see the issues if you want to help.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues labeled [good first issue](https://github.com/Sahil-u07/wouldcatch/labels/good%20first%20issue) are small and scoped.

## License

[MIT](LICENSE)
