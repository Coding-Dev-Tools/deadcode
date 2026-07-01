# Agent Instructions for deadcode

## Project Overview
CLI tool to detect and auto-remove unused exports, dead routes, orphaned CSS in TS/React/Next.js projects.

## Build & Test Commands
- **Install dev dependencies**: `pip install -e ".[dev]"`
- **Run tests**: `python -m pytest tests/ -x -q`
- **Lint**: `ruff check .`
- **Build**: `python -m build`

## Code Style
- Python 3.10+ target
- Line length: 120 chars (ruff config)
- Import sorting: isort with known-first-party = ["deadcode"]
- Lint rules: E, F, W, I, UP, B, SIM (ignore E501)

## Key Files
- `src/deadcode/cli.py` - Main CLI entry point
- `src/deadcode/scanner.py` - Core scanning logic
- `src/deadcode/config.py` - Configuration handling
- `tests/` - Test suite (3 test files)
- `pyproject.toml` - Project configuration

## CI/CD
- GitHub Actions workflow in `.github/workflows/ci.yml`
- Tests run on Python 3.10, 3.11, 3.12, 3.13
- Lint with ruff, test with pytest
- Publish to PyPI on version tags (v*)

## Contribution Guidelines
1. Run `ruff check .` before committing
2. Run `python -m pytest tests/ -x -q` to verify tests pass
3. Follow conventional commits
4. Update CHANGELOG.md for notable changes