"""DeadCode configuration loader.

Reads .deadcode.yml from the project root. Supports:
  ignore: list of gitignore-style patterns
  categories: list of categories to enable (default: all)
  fail_threshold: max findings before CI fails (default: -1 = disabled)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DeadCodeConfig:
    """Configuration loaded from .deadcode.yml."""

    ignore: list[str] = field(default_factory=list)
    categories: list[str] = field(
        default_factory=lambda: [
            "unused_export",
            "dead_route",
            "orphaned_css",
            "unreferenced_component",
        ]
    )
    fail_threshold: int = -1  # -1 means disabled

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeadCodeConfig:
        """Create config from a parsed dict."""
        return cls(
            ignore=data.get("ignore", []),
            categories=data.get(
                "categories",
                [
                    "unused_export",
                    "dead_route",
                    "orphaned_css",
                    "unreferenced_component",
                ],
            ),
            fail_threshold=data.get("fail_threshold", -1),
        )

    @classmethod
    def load(cls, project_dir: str | Path) -> DeadCodeConfig:
        """Load config from .deadcode.yml in project root, or return defaults."""
        config_path = Path(project_dir) / ".deadcode.yml"
        if not config_path.exists():
            return cls()

        try:
            import yaml
        except ImportError:
            return cls()

        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return cls()

        if not isinstance(data, dict):
            return cls()

        return cls.from_dict(data)
