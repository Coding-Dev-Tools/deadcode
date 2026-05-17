# DeadCode

[![GitHub stars](https://img.shields.io/github/stars/Coding-Dev-Tools/deadcode?style=social)](https://github.com/Coding-Dev-Tools/deadcode/stargazers)

**Detect and remove unused exports, dead routes, orphaned CSS, and unreferenced components in TypeScript/React/Next.js projects.**

> â­ **Star this repo** if you care about bundle size â€” it helps other devs find DeadCode!

[![PyPI](https://img.shields.io/pypi/v/deadcode)](https://pypi.org/project/deadcode/)
[![Python](https://img.shields.io/pypi/pyversions/deadcode)](https://pypi.org/project/deadcode/)
[![License](https://img.shields.io/pypi/l/deadcode)](https://github.com/Coding-Dev-Tools/deadcode/blob/main/LICENSE)
[![CI](https://github.com/Coding-Dev-Tools/deadcode/actions/workflows/test.yml/badge.svg)](https://github.com/Coding-Dev-Tools/deadcode/actions/workflows/test.yml)
[![Open Source Alternative](https://img.shields.io/badge/Open_Source_Alternative-%E2%87%92-blue?logo=opensourceinitiative)](https://www.opensourcealternative.to/project/deadcode)
[![LibHunt](https://img.shields.io/badge/LibHunt-%E2%87%92-blue?logo=codeigniter)](https://www.libhunt.com/r/Coding-Dev-Tools/deadcode)
[![Awesome Python](https://img.shields.io/badge/Awesome_Python-%E2%87%92-blue?logo=python)](https://github.com/uhub/awesome-python)

**Why DeadCode?**

## Quick Start

```bash
pip install deadcode

# Scan current project
deadcode scan

# Scan a specific project
deadcode scan -p /path/to/project

# Preview removable dead code
deadcode remove --dry-run

# Remove confirmed dead code
deadcode remove
```

## Commands

### `deadcode scan`

Scan a TypeScript/React/Next.js project for all categories of dead code.

```bash
deadcode scan                          # Scan current directory
deadcode scan -p /path/to/project      # Scan specific project
deadcode scan --json-output            # Machine-readable JSON
deadcode scan -c unused_export         # Filter by category
deadcode scan -i "generated/"          # Ignore paths
```

### `deadcode remove`

Remove dead code after previewing. Always preview with `--dry-run` first.

```bash
deadcode remove --dry-run              # Preview changes (no writes)
deadcode remove                        # Apply removals
deadcode remove -c orphaned_css        # Remove only orphaned CSS
```

### `deadcode stats`

Quick overview of dead code in your project.

```bash
deadcode stats
```

## Categories

| Category | Description | Example |
|----------|-------------|---------|
| `unused_export` | Exported names never imported elsewhere | `export function oldHelper()` with zero consumers |
| `dead_route` | Next.js routes with no internal links | `app/legacy/page.tsx` no longer linked from navigation |
| `orphaned_css` | CSS classes not referenced in JSX | `.oldClass` in `styles.module.css` with zero usages |
| `unreferenced_component` | React components defined but never imported | A `<LegacyWidget>` component with no import sites |

## Features

- **Unused export detection** â€” finds functions, types, classes, interfaces, enums, and consts that are exported but never imported within your project
- **Dead route detection** â€” detects unreachable page components in Next.js App Router projects
- **Orphaned CSS detection** â€” finds CSS module classes that are defined but never referenced in TSX/JSX files
- **Safe auto-removal** â€” `--dry-run` preview mode shows exactly what will be deleted before making changes
- **Full-project AST analysis** â€” regex-based scanning covers export/import patterns, route detection, CSS class usage, and component references across your entire codebase
- **Monorepo support** â€” handles large projects efficiently with ignore patterns
- **CI integration** â€” JSON output for automated pipelines and gating

## Ignore Patterns

```bash
deadcode scan -i "generated/" -i "**/*.generated.ts"
```

Default ignores: `node_modules/`, `.git/`, `.next/`, `dist/`, `build/`, `public/`, `static/`

## Pricing

DeadCode is one of eight tools in the Revenue Holdings suite. One license covers all CLI tools.

| Plan | Price | Best For |
|------|-------|----------|
| **Free** | $0 | Individual devs, OSS â€” CLI only, rate-limited |
| **DeadCode Individual** | **$12/mo** ($10 billed annually) | Professional devs â€” unlimited scans, auto-removal, CI integration |
| **Suite (all 8 tools)** | **$49/mo** ($39 billed annually) | Full Revenue Holdings toolkit â€” 40% savings |
| **Team** | **$79/mo** ($63 billed annually) | Up to 5 devs â€” trend analytics, shared baselines, alerts |
| **Enterprise** | Custom | SSO, RBAC, compliance reports, dedicated support |

ðŸ”¹ **No lock-in**: CLI works fully offline on the free tier â€” no telemetry, no phone-home.
ðŸ”¹ **Annual billing**: Save 20%.

### Per-Tier Features

| Feature | Free | Individual | Suite | Team | Enterprise |
|---------|:----:|:----------:|:-----:|:----:|:----------:|
| CLI: scan, stats | âœ“ | âœ“ | âœ“ | âœ“ | âœ“ |
| All 3 scanner categories | â€” | âœ“ | âœ“ | âœ“ | âœ“ |
| Auto-removal (`deadcode remove`) | â€” | âœ“ | âœ“ | âœ“ | âœ“ |
| Unlimited file scanning | â€” | âœ“ | âœ“ | âœ“ | âœ“ |
| CI/CD integration (JSON output) | â€” | âœ“ | âœ“ | âœ“ | âœ“ |
| Project trend baselines | â€” | â€” | â€” | âœ“ | âœ“ |
| Dashboard & analytics | â€” | â€” | â€” | âœ“ | âœ“ |
| Compliance reports | â€” | â€” | â€” | â€” | âœ“ |
| RBAC / SSO / SAML / OIDC | â€” | â€” | â€” | â€” | âœ“ |
| Priority support | Community | 24h | 24h | 8h | Dedicated |

---

<p align="center">
  <sub>Part of <a href="https://coding-dev-tools.github.io/revenueholdings.dev/">Revenue Holdings</a> â€” CLI tools built by autonomous AI.</sub>
</p>

## CI/CD Integration

```bash
# Generate report for CI
deadcode scan --json-output > deadcode-report.json

# Fail CI if any dead routes found
deadcode scan -c dead_route --fail 1

# Fail CI if total findings exceed threshold
deadcode scan --fail 10

# Track dead code trends over time
deadcode scan --json-output > baseline-$(date +%Y-%m-%d).json
```

## Configuration (.deadcode.yml)

Create a `.deadcode.yml` file in your project root:

```yaml
# .deadcode.yml
ignore:
  - "generated/"
  - "**/*.generated.ts"
  - "src/legacy/"

categories:
  - unused_export
  - dead_route
  - orphaned_css
  - unreferenced_component

# Exit with code 1 if findings >= this number (for CI gating)
fail_threshold: 10
```

CLI flags override config file settings.

## Storage

- `.deadcode.yml` â€” project configuration (ignore patterns, categories)
- `deadcode-baseline.json` â€” saved scan results for trend tracking

## Roadmap

- [ ] VS Code extension with inline decorations showing dead code
- [ ] ESLint plugin integration with auto-fix
- [ ] Webpack/Rollup bundle analysis hooks
- [ ] MCP server for AI-assisted cleanup
- [ ] Incremental scanning with cache
- [ ] GitHub Actions annotator for PR comments

## License

MIT â€” see [LICENSE](LICENSE)



## Install via npm

```bash
npm install -g deadcode-cli
```

Or install via Homebrew (macOS/Linux):
```bash
brew tap Coding-Dev-Tools/tap
brew install deadcode
```

Or install via Scoop (Windows):
```bash
scoop bucket add Coding-Dev-Tools https://github.com/Coding-Dev-Tools/scoop-bucket
scoop install deadcode
```

Then run: `deadcode --help`
