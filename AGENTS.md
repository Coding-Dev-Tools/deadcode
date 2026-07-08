# deadcode

## Purpose
Detect and remove unused exports, dead routes, orphaned CSS, and unreferenced components in TypeScript/React/Next.js projects.

## Build & Test Commands
- Install: `pip install -e .` or `pip install deadcode-cli`
- Test: `pytest tests/` (or `python -m pytest tests/ -v --tb=short`)
- Lint: `ruff check .`
- Build: `pip install build twine && python -m build && twine check dist/*`
- CLI check: `deadcode --help`

## Architecture
Key directories:
- `src/deadcode/` — Main package (CLI, analyzers for TS/JS/CSS/React/Next.js)
- `tests/` — Test suite
- `.github/workflows/` — CI/CD (ci.yml, pages.yml, publish.yml)
- `dist/` — Built distributions

## Conventions
- Language: Python 3.10+ (with Node.js for TS analysis)
- Test framework: pytest
- CI: GitHub Actions (ci.yml, pages.yml, publish.yml)
- Linting: ruff
- Build system: setuptools
- Package layout: src/ layout
- Dependencies: click, rich, tree-sitter, tree-sitter-typescript, esprima
- CLI entry point: deadcode.cli:cli
- Default branch: main