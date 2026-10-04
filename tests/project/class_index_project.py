"""The project fixture the class-index e2e stand on (#1073).

A project the editor never opened: no `.godot/`, so no class index. Two
Resource classes (`FireAttack extends AttackComponent`), one Node class, a
script typed with a project class, and an empty scene. `rename_class` edits a
script's `class_name` line in place with no scan, which leaves the index entry
stale: the script still compiles, under another name.
"""

from pathlib import Path

from tests.conftest import project_godot

ATTACK_COMPONENT_GD = (
    "class_name AttackComponent extends Resource\n"
    "\n"
    "func attack():\n"
    '\tprint("Default attack")\n'
)
FIRE_ATTACK_GD = (
    "class_name FireAttack extends AttackComponent\n"
    "\n"
    "func attack():\n"
    '\tprint("Fire attack")\n'
)
MOVER_GD = "class_name Mover extends Node\n"
HOLDER_GD = "extends Node\n@export var c: AttackComponent\n"
MAIN_TSCN = '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n'


def components_project(directory: Path) -> Path:
    """Write the never-opened components project into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "project.godot").write_text(
        project_godot(name="gda-class-index"), encoding="utf-8"
    )
    files = {
        "attack_component.gd": ATTACK_COMPONENT_GD,
        "fire_attack.gd": FIRE_ATTACK_GD,
        "mover.gd": MOVER_GD,
        "holder.gd": HOLDER_GD,
        "main.tscn": MAIN_TSCN,
    }
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def rename_class(project: Path, script: str, old: str, new: str) -> None:
    """Rename ``old`` to ``new`` in ``script``'s `class_name` line, with no scan."""
    path = project / script
    text = path.read_text(encoding="utf-8")
    assert f"class_name {old} " in text or text.startswith(f"class_name {old}\n")
    path.write_text(
        text.replace(f"class_name {old}", f"class_name {new}", 1), encoding="utf-8"
    )
