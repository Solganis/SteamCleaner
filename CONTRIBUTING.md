# Contributing

Open an issue before a substantial change.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Workflow

1. Fork, clone, create a branch
2. `uv sync`
3. Make the change, with tests
4. Run the [checks](#checks)
5. Commit in [Conventional Commits](https://www.conventionalcommits.org/) style: `feat:`, `fix:`, `docs:`, `test:`, `build:`, `ci:`, `refactor:`, `perf:`, `style:`, `chore:`
6. Open a [pull request](https://github.com/Solganis/SteamCleaner/pulls)

## Checks

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --cov=steamcleaner --cov-report=term-missing --cov-fail-under=100
```

CI runs the first four on Linux and the tests on Linux, Windows and macOS.

- `ty` checks the whole tree, `tests/` and `scripts/` included, for every platform (`python-platform = "all"`).
- A warning in the test run is an error (`filterwarnings = ["error"]`).
- Coverage is 100%, line and branch. A line that cannot be tested gets `# pragma: no cover` with the reason, and the pull request lists such lines.
- A suppression names its rule and its reason: `# noqa: RULE`, `# ty: ignore[rule]`. `# type: ignore` is not honored.

## Tests

- Assertions go through `assertpy2` (`assert_that`).
- `FakePlatformAdapter` from `tests/helpers.py` stands in for the registry and the home directory.
- A test that needs one OS is marked `skipif`.

## Windows release build

```bash
uv run flet build windows --yes
uv run python scripts/build_windows.py --skip-flet-build
uv run python scripts/prune_bundle.py build/windows
```

- `build_windows.py` keeps the window hidden until Python shows it. It stops if `hide_window_on_start` from `[tool.flet.windows.app]` did not reach the generated sources.
- `prune_bundle.py` removes debug builds of extension modules, Tcl/Tk, SQLite and the standard-library modules it lists. A module goes on that list only after the bundled app started, scanned and ran a dry-run clean without it.
