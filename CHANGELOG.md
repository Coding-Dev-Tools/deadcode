# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- MCP server integration via `mcp` subcommand
- `__main__.py` for `python -m deadcode` support
- CLI test suite covering all subcommands
- npm wrapper (`package.json` + `cli.js`) for npm publishing
- GitHub Actions: npm publish workflow (release or manual dispatch)
- GitHub Actions: PyPI publish workflow
- GitHub Actions: GitHub Pages deployment workflow
- `CONTRIBUTING.md` with development setup and PR guidelines
- `SECURITY.md` with security policy
- Homebrew and Scoop install methods
- Directory listing badges: Open Source Alternative, LibHunt, Awesome Python
- `revenueholdings-license` gating on all CLI commands
- Beta badge and star CTA in README header
- npm keywords optimized for discoverability (15 terms)

### Fixed

- Re-exported symbols are no longer reported as unused dead code. Barrel/index
  files that forward exports (`export { X } from './mod'`, `export { X as Y } from
  './mod'`, `export { type X } from './mod'`, and `export * from './mod'`) now mark
  the forwarded symbols as used, preventing false-positive `removable` findings that
  could delete live public API.

### Changed

- npm package renamed for consistency
- CI test matrix expanded to include Python 3.13
- CI security hardened: `persist-credentials: false`, restricted permissions
- Documentation branding updated from DevForge to Revenue Holdings
- README tool count updated (8 → 11)
- `project.urls` metadata added to `pyproject.toml`

### Fixed

- CI badge updated to reference correct workflow file
- UTF-8 encoding (mojibake) in file output
- Ruff lint issues: `datetime.UTC`, `X | None` syntax, `E501`, `B904`, `F821`
- Missing `ruff` dev dependency in `pyproject.toml`
- Duplicate `test.yml` workflow removed
- `revenueholdings-license` import made optional (fixes CI failures on open-source PRs)
- Dependencies bumped via Dependabot (checkout@v6, setup-node@v6, setup-python@v6, rich, pyyaml)
- Orphaned npm install section removed from README
- Scanner category count corrected (3 → 4)