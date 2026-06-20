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

Run all checks before submitting a PR. Every step must pass.

```bash
# lint
uv run ruff check src/ tests/

# format
uv run ruff format --check src/ tests/

# type check
uv run ty check src/

# tests with coverage (must be 100%)
uv run pytest tests/ -v --cov=steamcleaner --cov-report=term-missing
```

CI requires 100% code coverage.

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`, `style:`, etc.

## Tests

Write tests for every new feature or bug fix. Use `assertpy2` assertions (`assert_that`) in tests.
