# deadcode

## Purpose
CLI tool to detect and auto-remove unused exports, dead routes, and orphaned CSS in TypeScript/React/Next.js projects.

## Build & Test Commands
- Install: `pip install -e .` or `pip install git+https://github.com/Coding-Dev-Tools/deadcode.git`
- Test: `pytest tests/` (or `python -m pytest tests/ -v --tb=short`)
- Lint: `ruff check src/ tests/`
- Format: `ruff format src/ tests/`
- Build: `pip install build twine && python -m build && twine check dist/*`
- CLI check: `deadcode --help`

## Architecture
Key directories:
- `src/deadcode/` — Main package (CLI, scanner, config)
- `tests/` — Test suite
- `.github/workflows/` — CI/CD (auto-code-review.yml, ci.yml, publish.yml)

## Conventions
- Language: Python 3.10+
- Test framework: pytest (with coverage)
- CI: GitHub Actions (matrix: Python 3.10, 3.11, 3.12, 3.13)
- Linting/formatting: ruff (line-length 120, target py310)
- Package layout: src/ layout with setuptools
- Type checking: py.typed included
- Dependencies: click, rich, pathspec, pyyaml
- CLI entry point: deadcode.cli:cli
- Default branch: master
- Branch naming: `improve/<repo>-<timestamp>` for structural fixes
