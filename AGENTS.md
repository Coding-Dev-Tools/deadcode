# deadcode

Repo guide for agents.

## Workflow
- Use `pytest` for tests.
- Use `ruff` for lint/format.
- Build/publish via GitHub Actions in `.github/workflows/`.

## Conventions
- Package code under `src/deadcode` per `pyproject.toml` packaging config.
- Keep branches `improve/<repo>-<timestamp>` for structural fixes.
- Do not modify dependencies without updating `pyproject.toml`.
