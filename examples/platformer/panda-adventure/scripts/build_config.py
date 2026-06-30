#!/usr/bin/env python3
"""JSON -> Resource build pipeline for Panda Adventure (gADR-0000).

The authoritative config lives in ``data/json/boot_config.json``. This step
validates it against ``data/schema/boot_config.schema.json`` (raising on invalid
input) and emits the *derived* Godot Resource ``data/generated/boot_config.tres``
that the runtime ``load()``s. The ``.tres`` is a build artifact (gitignored),
never hand-edited: changing config means changing the JSON.

Dogfooding note: ``gda resource create --type GameConfig`` cannot instantiate a
GDScript ``class_name`` global (gda's ClassDB lookup only knows built-in Resource
classes), so this converter emits the ``.tres`` text directly — an ``ext_resource``
to the script plus the ``[resource]`` field assignments. The emitted file still
loads through gda/Godot, which the data-seam round-trip test proves.

Run standalone: ``python scripts/build_config.py`` (writes the .tres, prints a
one-line summary).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

# Resolve paths relative to this file so the script works from any CWD.
GAME_DIR = Path(__file__).resolve().parent.parent
JSON_PATH = GAME_DIR / "data" / "json" / "boot_config.json"
SCHEMA_PATH = GAME_DIR / "data" / "schema" / "boot_config.schema.json"
GENERATED_TRES = GAME_DIR / "data" / "generated" / "boot_config.tres"

# The res:// path of the GameConfig script the generated .tres references.
SCRIPT_RES_PATH = "res://src/resources/game_config.gd"
_EXT_ID = "1_gameconfig"


def load_json(path: Path) -> Any:
    """Parse a JSON file into Python data."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Load the boot-config JSON Schema."""
    return load_json(path)


def validate_config(config: Any, schema: dict[str, Any] | None = None) -> Any:
    """Validate ``config`` against the schema; raise on invalid, else return it.

    Raises :class:`jsonschema.ValidationError` for any schema violation (missing
    key, wrong type, out-of-range component, wrong array length).
    """
    jsonschema.validate(
        instance=config, schema=schema if schema is not None else load_schema()
    )
    return config


def _num(value: float) -> str:
    """Format a JSON number the way a Godot ``.tres`` literal expects.

    Renders an integral float without a trailing ``.0`` (``1.0`` -> ``1``),
    matching Godot's own serializer; non-integral values keep full precision.
    Godot's parser accepts either form for ``Color``/``Vector2``/``float``.
    """
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError("boolean is not a numeric config value")
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def render_tres(config: dict[str, Any]) -> str:
    """Render a validated boot config as ``GameConfig`` ``.tres`` text.

    Pure function (no IO): the JSON->Resource conversion seam. Maps the JSON
    arrays to their Godot types — ``block_color`` -> ``Color(r,g,b,a)``, the two
    positions -> ``Vector2(x,y)``, ``tween_duration`` -> a bare number.
    """
    r, g, b, a = config["block_color"]
    sx, sy = config["start_position"]
    tx, ty = config["target_position"]
    color = f"Color({_num(r)}, {_num(g)}, {_num(b)}, {_num(a)})"
    start = f"Vector2({_num(sx)}, {_num(sy)})"
    target = f"Vector2({_num(tx)}, {_num(ty)})"
    duration = _num(config["tween_duration"])
    return (
        f'[gd_resource type="Resource" script_class="GameConfig" '
        f"load_steps=2 format=3]\n\n"
        f'[ext_resource type="Script" path="{SCRIPT_RES_PATH}" id="{_EXT_ID}"]\n\n'
        f"[resource]\n"
        f'script = ExtResource("{_EXT_ID}")\n'
        f"block_color = {color}\n"
        f"start_position = {start}\n"
        f"target_position = {target}\n"
        f"tween_duration = {duration}\n"
    )


def build(
    json_path: Path = JSON_PATH,
    schema_path: Path = SCHEMA_PATH,
    out_path: Path = GENERATED_TRES,
) -> Path:
    """Validate the authoritative JSON and write the derived ``.tres``.

    Returns the path written. Raises :class:`jsonschema.ValidationError` if the
    JSON is invalid, so a bad config fails the build loudly.
    """
    config = load_json(json_path)
    validate_config(config, load_schema(schema_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_tres(config), encoding="utf-8")
    return out_path


def main() -> None:
    written = build()
    print(f"build_config: wrote {written.relative_to(GAME_DIR)} from {JSON_PATH.name}")


if __name__ == "__main__":
    main()
