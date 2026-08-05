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
RUNTIME_SUFFIXES = {".gd", ".tscn", ".tres"}
RESOURCE_PATH = re.compile(r"res://([A-Za-z0-9_./%{}-]+)")
CLASS_NAME = re.compile(r"^\s*class_name\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
UID_LOAD = re.compile(r"(?:preload|load)\(\s*[\"']uid://")


def _runtime_files(root: Path = GAME_DIR) -> list[Path]:
    return sorted(
        path
        for source_root in LAYERS
        for path in (root / source_root).rglob("*")
        if path.suffix in RUNTIME_SUFFIXES
    )


def _runtime_references(text: str) -> set[str]:
    return {match.group(1).split("/", 1)[0] for match in RESOURCE_PATH.finditer(text)}


def _gd_without_comments(text: str, *, blank_strings: bool) -> str:
    """Blank comments and optionally strings while preserving source positions."""
    code: list[str] = []
    index = 0
    delimiter: str | None = None
    while index < len(text):
        if delimiter is not None:
            if text.startswith(delimiter, index):
                code.extend(" " * len(delimiter) if blank_strings else delimiter)
                index += len(delimiter)
                delimiter = None
            elif text[index] == "\\" and index + 1 < len(text):
                code.extend("  " if blank_strings else text[index : index + 2])
                index += 2
            else:
                if blank_strings:
                    code.append("\n" if text[index] == "\n" else " ")
                else:
                    code.append(text[index])
                index += 1
            continue

        if text[index] in {'"', "'"}:
            quote = text[index]
            delimiter = quote * 3 if text.startswith(quote * 3, index) else quote
            code.extend(" " * len(delimiter) if blank_strings else delimiter)
            index += len(delimiter)
        elif text[index] == "#":
            while index < len(text) and text[index] != "\n":
                code.append(" ")
                index += 1
        else:
            code.append(text[index])
            index += 1
    return "".join(code)


def _dependency_violations(root: Path = GAME_DIR) -> list[str]:
    files = _runtime_files(root)
    class_layers: dict[str, str] = {}
    for path in files:
        if path.suffix != ".gd":
            continue
        declaration = CLASS_NAME.search(path.read_text("utf-8"))
        if declaration is not None:
            class_layers[declaration.group(1)] = path.relative_to(root).parts[0]

    violations: list[str] = []
    for path in files:
        rel = path.relative_to(root)
        source_root = rel.parts[0]
        source_rank = LAYERS[source_root]
        text = path.read_text("utf-8")
        code = (
            _gd_without_comments(text, blank_strings=False)
            if path.suffix == ".gd"
            else text
        )
        for target_root in _runtime_references(code):
            target_rank = LAYERS.get(target_root)
            if target_rank is not None and target_rank > source_rank:
                violations.append(f"{rel} -> res://{target_root}/")

        if path.suffix != ".gd":
            continue
        if UID_LOAD.search(code):
            violations.append(f"{rel} -> uid:// (unresolved runtime resource)")
        identifiers = _gd_without_comments(text, blank_strings=True)
        for class_name, target_root in class_layers.items():
            if LAYERS[target_root] <= source_rank:
                continue
            if re.search(rf"\b{re.escape(class_name)}\b", identifiers):
                violations.append(f"{rel} -> {class_name} ({target_root} class)")

    return sorted(set(violations))


def test_runtime_dependencies_point_downward() -> None:
    violations = _dependency_violations()

    assert not violations, "runtime dependency violations:\n" + "\n".join(violations)


def _editor_tool_violations(root: Path = GAME_DIR) -> list[str]:
    violations: list[str] = []
    for path in _runtime_files(root):
        text = path.read_text("utf-8")
        code = (
            _gd_without_comments(text, blank_strings=False)
            if path.suffix == ".gd"
            else text
        )
        if "res://tools/editor/" in code:
            violations.append(str(path.relative_to(root)))
    return violations


def test_runtime_does_not_depend_on_editor_tools() -> None:
    violations = _editor_tool_violations()

    assert not violations, "runtime references development editor tools: " + ", ".join(
        violations
    )


def test_game_shell_is_the_runtime_composition_root() -> None:
    project = (GAME_DIR / "project.godot").read_text("utf-8")

    assert 'run/main_scene="res://ui/game_shell.tscn"' in project


def test_dependency_guard_rejects_each_supported_upward_reference(
    tmp_path: Path,
) -> None:
    for layer in LAYERS:
        (tmp_path / layer).mkdir()
    (tmp_path / "ui/hud.gd").write_text(
        "class_name FakeHud\nextends Node\n", encoding="utf-8"
    )
    (tmp_path / "systems/bad.gd").write_text(
        "\n".join(
            (
                "extends RefCounted",
                'const HUD = preload("res://ui/hud.gd")',
                'const OPAQUE = preload("uid://fake")',
                "var hud: FakeHud",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "systems/allowed.gd").write_text(
        '''extends RefCounted
const LABEL = "FakeHud"
const MULTILINE = """FakeHud
is text here too"""
# FakeHud in a comment is not a dependency.
# preload("res://ui/hud.gd") in a comment is not a dependency either.
# preload("res://tools/editor/editor.gd") is also only a comment.
''',
        encoding="utf-8",
    )

    assert _dependency_violations(tmp_path) == [
        "systems/bad.gd -> FakeHud (ui class)",
        "systems/bad.gd -> res://ui/",
        "systems/bad.gd -> uid:// (unresolved runtime resource)",
    ]
    assert _editor_tool_violations(tmp_path) == []


def test_editor_guard_rejects_runtime_tool_references(tmp_path: Path) -> None:
    for layer in LAYERS:
        (tmp_path / layer).mkdir()
    (tmp_path / "ui/bad.gd").write_text(
        'const EDITOR = preload("res://tools/editor/editor_controller.gd")\n',
        encoding="utf-8",
    )

    assert _editor_tool_violations(tmp_path) == ["ui/bad.gd"]
