# Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

## Getting started

1. Fork the repository
2. Clone your fork and create a feature branch
3. Install dependencies: `uv sync`
4. Make your changes

## Code style

- Python 3.14+
- Format and lint with [Ruff](https://github.com/astral-sh/ruff): `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/`
- Type check with [ty](https://github.com/astral-sh/ty): `uv run ty check src/`
- Run tests: `uv run pytest tests/ -v`

## Pull requests

- Keep PRs focused on a single change
- Ensure all checks pass (lint, format, type check, tests)
- Follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description`
