# Contributing

Contributions of docs, tests, or code are welcome. Please open an issue first to discuss substantial changes.

## Workflow

1. Fork the repo
2. Clone your fork (`git clone <your_fork_url>`)
3. Create a branch (`git checkout -b my_branch`)
4. Install dependencies: `uv sync`
5. Make your changes
6. Run the [verification pipeline](#verification-pipeline) and fix any issues
7. Commit using [Conventional Commits](#commit-style)
8. Push your branch (`git push origin my_branch`)
9. Open a [Pull Request](https://github.com/Solganis/SteamCleaner/pulls)

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) as the package manager

## Verification pipeline

Run all checks before submitting a PR. Every step must pass, and CI runs the same commands.

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --cov=steamcleaner --cov-report=term-missing --cov-fail-under=100
```

### Details that cost time if you meet them the hard way

- `ty check` covers the whole tree, tests and `scripts/` included. It runs with `python-platform = "all"`, so the code for one OS has to type-check on the others too.
- The suite turns every warning into an error. Fix the cause, or add a targeted `"ignore::<Category>"` entry to `filterwarnings` in `pyproject.toml` when a third-party warning forces it.
- Coverage stays at 100%. A line that can be tested gets a test. A line that cannot (GUI paint, a branch for another OS, an entry point) gets `# pragma: no cover` with the reason on the same line, and the PR names the lines it excluded.
- A suppression names its rule and says why: `# noqa: RULE` or `# ty: ignore[rule]`. ty ignores `# type: ignore`.

### Windows release build

The Windows binary is built in two steps, so the window stays hidden until Python is ready to show it:

```bash
uv run flet build windows --yes
uv run python scripts/build_windows.py --skip-flet-build
```

The script stops if `hide_window_on_start` from `[tool.flet.windows.app]` did not reach the generated sources.

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`, `style:`, etc.

## Tests

Write tests for every new feature or bug fix. Use `assertpy2` assertions (`assert_that`) in tests. Tests are OS-independent: inject `FakePlatformAdapter` from `tests/helpers.py` instead of touching the real registry or home directory.
