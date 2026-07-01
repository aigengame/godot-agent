#!/usr/bin/env python3
"""JSON -> Resource build pipeline for Panda Adventure (gADR-0000).

The authoritative config lives in ``data/json/player_config.json``. This step
validates it against ``data/schema/player_config.schema.json`` (raising on
invalid input) and emits the *derived* Godot Resource
``data/generated/player_config.tres`` that the runtime ``load()``s. The ``.tres``
is a committed derived artifact (a freshness gate keeps it byte-identical to a
fresh build), never hand-edited: changing config means changing the JSON.

Dogfooding note: ``gda resource create --type PlayerConfig`` cannot instantiate a
GDScript ``class_name`` for THIS project, because gda resolves a registered
class_name through ``ProjectSettings.get_global_class_list()`` — which is only
populated once the project has been imported/scanned by the editor
(``.godot/global_script_class_cache.cfg``). This project is agent-driven and never
opened in the editor, so that cache does not exist and the class is invisible. So
this converter emits the ``.tres`` text directly — an ``ext_resource`` to the
script plus the ``[resource]`` field assignments. The emitted file still loads
through gda/Godot, which the data-seam round-trip test proves.

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
JSON_PATH = GAME_DIR / "data" / "json" / "player_config.json"
SCHEMA_PATH = GAME_DIR / "data" / "schema" / "player_config.schema.json"
GENERATED_TRES = GAME_DIR / "data" / "generated" / "player_config.tres"

# The res:// path + script_class of the Resource the generated .tres references.
SCRIPT_RES_PATH = "res://src/resources/player_config.gd"
SCRIPT_CLASS = "PlayerConfig"
_EXT_ID = "1_playerconfig"

# The .tres field layout: (json key, Godot type). Rendered in THIS order, so a
# rebuild is byte-stable (the freshness gate depends on it) and adding a config
# field is a one-line change. Types: "color" (4-array -> Color), "vec2" (2-array
# -> Vector2), "float" (scalar -> bare number). The schema is the validation
# authority; this list is the render authority — keep them in step.
_FIELDS: list[tuple[str, str]] = [
    ("player_color", "color"),
    ("player_size", "vec2"),
    ("player_start", "vec2"),
    ("move_speed", "float"),
    ("jump_velocity", "float"),
    ("gravity", "float"),
    ("max_fall_speed", "float"),
    ("platform_color", "color"),
    ("platform_size", "vec2"),
    ("platform_position", "vec2"),
    ("camera_smoothing_speed", "float"),
]


def load_json(path: Path) -> Any:
    """Parse a JSON file into Python data."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Load the player-config JSON Schema."""
    return load_json(path)


def validate_config(config: Any, schema: dict[str, Any] | None = None) -> Any:
    """Validate ``config`` against the schema; raise on invalid, else return it.

    Raises :class:`jsonschema.ValidationError` for any schema violation (missing
    key, wrong type, out-of-range component, wrong array length, wrong sign).
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


def _render_field(key: str, kind: str, value: Any) -> str:
    """Render one config value as its Godot ``.tres`` literal for the given kind."""
    if kind == "color":
        r, g, b, a = value
        return f"Color({_num(r)}, {_num(g)}, {_num(b)}, {_num(a)})"
    if kind == "vec2":
        x, y = value
        return f"Vector2({_num(x)}, {_num(y)})"
    if kind == "float":
        return _num(value)
    raise ValueError(f"unknown field kind {kind!r} for {key!r}")


def render_tres(config: dict[str, Any]) -> str:
    """Render a validated player config as ``PlayerConfig`` ``.tres`` text.

    Pure function (no IO): the JSON->Resource conversion seam. Walks ``_FIELDS``
    in declaration order, mapping each JSON value to its Godot type.
    """
    body = "".join(
        f"{key} = {_render_field(key, kind, config[key])}\n" for key, kind in _FIELDS
    )
    return (
        f'[gd_resource type="Resource" script_class="{SCRIPT_CLASS}" '
        f"load_steps=2 format=3]\n\n"
        f'[ext_resource type="Script" path="{SCRIPT_RES_PATH}" id="{_EXT_ID}"]\n\n'
        f"[resource]\n"
        f'script = ExtResource("{_EXT_ID}")\n'
        f"{body}"
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
