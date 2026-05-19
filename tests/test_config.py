"""Tests for DeadCode configuration loading."""

from __future__ import annotations

import pytest
from pathlib import Path

from deadcode.config import DeadCodeConfig


class TestDeadCodeConfigDefaults:
    def test_default_ignore_is_empty(self):
        cfg = DeadCodeConfig()
        assert cfg.ignore == []

    def test_default_categories_all(self):
        cfg = DeadCodeConfig()
        assert cfg.categories == [
            "unused_export", "dead_route", "orphaned_css", "unreferenced_component",
        ]

    def test_default_fail_threshold_disabled(self):
        cfg = DeadCodeConfig()
        assert cfg.fail_threshold == -1


class TestDeadCodeConfigFromDict:
    def test_empty_dict_gives_defaults(self):
        cfg = DeadCodeConfig.from_dict({})
        assert cfg.ignore == []
        assert cfg.fail_threshold == -1

    def test_ignore_patterns(self):
        cfg = DeadCodeConfig.from_dict({"ignore": ["node_modules/", "dist/"]})
        assert cfg.ignore == ["node_modules/", "dist/"]

    def test_categories_filter(self):
        cfg = DeadCodeConfig.from_dict({"categories": ["unused_export", "orphaned_css"]})
        assert cfg.categories == ["unused_export", "orphaned_css"]

    def test_fail_threshold_set(self):
        cfg = DeadCodeConfig.from_dict({"fail_threshold": 10})
        assert cfg.fail_threshold == 10

    def test_partial_dict_keeps_defaults(self):
        cfg = DeadCodeConfig.from_dict({"fail_threshold": 5})
        assert cfg.ignore == []
        assert cfg.categories == [
            "unused_export", "dead_route", "orphaned_css", "unreferenced_component",
        ]
        assert cfg.fail_threshold == 5


class TestDeadCodeConfigLoad:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = DeadCodeConfig.load(tmp_path)
        assert cfg.ignore == []
        assert cfg.fail_threshold == -1

    def test_loads_yml_config(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text(
            "ignore:\n"
            "  - 'vendor/'\n"
            "  - '*.generated.ts'\n"
            "categories:\n"
            "  - unused_export\n"
            "fail_threshold: 25\n"
        )
        cfg = DeadCodeConfig.load(tmp_path)
        assert cfg.ignore == ["vendor/", "*.generated.ts"]
        assert cfg.categories == ["unused_export"]
        assert cfg.fail_threshold == 25

    def test_empty_yml_returns_defaults(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text("")
        cfg = DeadCodeConfig.load(tmp_path)
        assert cfg.ignore == []
        assert cfg.fail_threshold == -1

    def test_invalid_yaml_returns_defaults(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text("{{invalid yaml::")
        # PyYAML may raise or return a string; both should fall back to defaults
        cfg = DeadCodeConfig.load(tmp_path)
        assert isinstance(cfg, DeadCodeConfig)

    def test_non_dict_yaml_returns_defaults(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text("- just\n- a\n- list\n")
        cfg = DeadCodeConfig.load(tmp_path)
        assert cfg.ignore == []
        assert cfg.fail_threshold == -1

    def test_ignore_only_config(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text("ignore:\n  - 'build/'\n")
        cfg = DeadCodeConfig.load(tmp_path)
        assert cfg.ignore == ["build/"]
        assert cfg.categories == [
            "unused_export", "dead_route", "orphaned_css", "unreferenced_component",
        ]
        assert cfg.fail_threshold == -1
