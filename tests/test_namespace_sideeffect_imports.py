"""Regression tests: namespace and side-effect imports consume a module's exports.

``import * as Utils from './utils'`` binds every export of ``./utils`` behind a
single object, and ``import './polyfill'`` loads a module purely for its side
effects. In both cases individual exported names cannot be attributed to usage
sites, so the scanner must treat the target module's whole export surface as
used. Before this fix, exports reachable ONLY through such imports were falsely
reported as unused with removable=True — i.e. live code flagged for deletion.
"""

from __future__ import annotations

from pathlib import Path

from deadcode.scanner import DeadCodeScanner


def _make_project(tmp_path: Path, consumer_source: str) -> Path:
    """utils.ts defines two exports; main.ts consumes it per consumer_source."""
    utils = tmp_path / "src" / "utils.ts"
    utils.parent.mkdir(parents=True, exist_ok=True)
    utils.write_text(
        "export function helper() { return 1; }\nexport const RATE = 2;\n"
    )
    main = tmp_path / "src" / "main.ts"
    main.write_text(consumer_source)
    return tmp_path


def _unused_names(project: Path) -> set[tuple[str, str]]:
    result = DeadCodeScanner(project).scan()
    return {(f.name, f.file) for f in result.unused_exports}


def _flagged_names(project: Path) -> set[str]:
    return {name for name, _file in _unused_names(project)}


class TestNamespaceImports:
    def test_namespace_import_marks_all_exports_used(self, tmp_path):
        project = _make_project(
            tmp_path,
            "import * as Utils from './utils';\n\n"
            "const total = Utils.helper() + Utils.RATE;\nexport default total;\n",
        )
        # Neither utils.ts export may be flagged: both are consumed via the
        # namespace binding.
        assert not [f for _n, f in _unused_names(project) if f.endswith("utils.ts")]

    def test_export_star_as_reexport_marks_all_exports_used(self, tmp_path):
        project = _make_project(
            tmp_path,
            "export * as internals from './utils';\n",
        )
        assert not list(_unused_names(project))

    def test_bare_specifier_namespace_import_cannot_mark_used(self, tmp_path):
        # A namespace import from an unresolvable package ('lodash') says
        # nothing about local modules — utils.ts must still be reported.
        project = _make_project(
            tmp_path,
            "import * as _ from 'lodash';\n",
        )
        flagged = _flagged_names(project)
        assert "helper" in flagged
        assert "RATE" in flagged


class TestSideEffectImports:
    def test_side_effect_import_marks_all_exports_used(self, tmp_path):
        project = _make_project(tmp_path, "import './utils';\n\nconst app = 'app';\n")
        assert not [f for _n, f in _unused_names(project) if f.endswith("utils.ts")]

    def test_no_consumer_still_flags_exports(self, tmp_path):
        # Control: without any consumer, the exports must still be detected —
        # guards against the fix over-marking everything as used.
        project = _make_project(tmp_path, "export const unrelated = 1;\n")
        flagged = _flagged_names(project)
        assert "helper" in flagged
        assert "RATE" in flagged
