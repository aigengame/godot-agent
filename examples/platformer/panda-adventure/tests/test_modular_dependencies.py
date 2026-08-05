"""Mechanical checks for the runtime module dependency direction.

The production roots form one downward dependency chain::

    UI -> Content -> Systems -> Add-ons

Same-layer references are allowed. Upward references are not. Development tools
and tests sit outside the shipped runtime and may depend on production modules.
"""

from __future__ import annotations

import re
from pathlib import Path


GAME_DIR = Path(__file__).resolve().parents[1]
LAYERS = {"addons": 0, "systems": 1, "content": 2, "ui": 3}
RESOURCE_PATH = re.compile(r"res://([A-Za-z0-9_./%{}-]+)")


def _runtime_references(path: Path) -> set[str]:
    return {
        match.group(1).split("/", 1)[0]
        for match in RESOURCE_PATH.finditer(path.read_text("utf-8"))
    }


def test_runtime_dependencies_point_downward() -> None:
    violations: list[str] = []
    for source_root, source_rank in LAYERS.items():
        for path in (GAME_DIR / source_root).rglob("*"):
            if path.suffix not in {".gd", ".tscn", ".tres"}:
                continue
            for target_root in _runtime_references(path):
                target_rank = LAYERS.get(target_root)
                if target_rank is not None and target_rank > source_rank:
                    rel = path.relative_to(GAME_DIR)
                    violations.append(f"{rel} -> res://{target_root}/")

    assert not violations, "upward runtime dependencies:\n" + "\n".join(sorted(violations))


def test_runtime_does_not_depend_on_editor_tools() -> None:
    violations: list[str] = []
    for source_root in LAYERS:
        for path in (GAME_DIR / source_root).rglob("*"):
            if path.suffix not in {".gd", ".tscn", ".tres"}:
                continue
            if "res://tools/editor/" in path.read_text("utf-8"):
                violations.append(str(path.relative_to(GAME_DIR)))

    assert not violations, "runtime references development editor tools: " + ", ".join(
        violations
    )


def test_game_shell_is_the_runtime_composition_root() -> None:
    project = (GAME_DIR / "project.godot").read_text("utf-8")
    gameplay = (GAME_DIR / "content/scenes/gameplay.tscn").read_text("utf-8")

    assert 'run/main_scene="res://ui/game_shell.tscn"' in project
    assert "res://ui/" not in gameplay
