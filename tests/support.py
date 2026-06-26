"""Shared test support for driving gda commands without a real engine (S3).

``FakeRunner`` satisfies the ``GodotRunner`` protocol with a canned raw
``RunResult`` and records dispatched ``(operation, params)`` calls, so command
tests exercise the full Typer→classify→JSON pipeline engine-free. ``sentinel``
wraps a payload in the ADR-0002 result sentinels the way ``operations.gd``
emits it.

Canned result payloads shared by more than one test module live here too, so a
sample ``--json`` payload has a single source of truth rather than being copied
between modules or imported test-module-to-test-module (issue #39).
"""

import json
import sys

from gda.runner import RunResult

# The gda CLI invocation prefix for e2e subprocess tests. Resolved as the gda
# MODULE in *this* interpreter's environment — `[sys.executable, "-m", "gda"]` —
# never a PATH-resolved global. This is the same same-environment resolution
# ADR-0011 (Design decision 3) mandates for gda-mcp ("never a wrong global `gda` a
# PATH lookup might resolve"); a `which`-style PATH lookup would instead run whatever
# is first on PATH (e.g. a uv-tool global, or another worktree's editable install).
# Under `uv run pytest`, sys.executable is this checkout's venv, so `-m gda` runs
# this checkout's editable gda deterministically. Spread it: `[*GDA_CMD, *args]`.
GDA_CMD = [sys.executable, "-m", "gda"]


class FakeRunner:
    """A fakeable GodotRunner that records its calls and returns a canned result."""

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    def run(self, operation: str, params: dict) -> RunResult:
        self.calls.append((operation, params))
        return self.result


class FakeExportRunner:
    """A fakeable ExportRunner for ``export run`` (issue #121).

    Records each ``(preset, mode, output_path)`` it is asked to export and returns
    a canned :class:`~gda.runner.RunResult`, so the native-export pipeline is
    exercised without a real engine, mirroring :class:`FakeRunner` for the
    sentinel channel. Both channels share the one raw-run dataclass (#185).
    """

    def __init__(self, output: RunResult) -> None:
        self.output = output
        self.calls: list[tuple[str, str, str]] = []

    def run(self, preset: str, mode: str, output_path: str) -> RunResult:
        self.calls.append((preset, mode, output_path))
        return self.output


def sentinel(payload: dict) -> str:
    """Wrap ``payload`` in the ADR-0002 result sentinels, as operations.gd emits."""
    return raw_sentinel(json.dumps(payload))


def raw_sentinel(body: str) -> str:
    """Wrap a RAW string ``body`` in the ADR-0002 result sentinels.

    The escape hatch for frames :func:`sentinel` cannot build from a ``dict`` —
    notably an intentionally malformed-JSON payload — so tests exercising the
    parse-error path don't hand-build the sentinel markers inline.
    """
    return f"<<<GDA:RESULT>>>{body}<<<GDA:END>>>\n"


def error_sentinel(code: str, message: str) -> str:
    """Wrap a minimal ADR-0002 operation error envelope in result sentinels."""
    return sentinel({"error": {"code": code, "message": message}})


def inject_runner(monkeypatch, result: RunResult) -> FakeRunner:
    """Swap the CLI's runner seam for a ``FakeRunner`` returning ``result``."""
    fake = FakeRunner(result)
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)
    return fake


def inject_live_runner(monkeypatch, result: RunResult) -> FakeRunner:
    """Swap the CLI's LIVE (daemon) runner seam for a ``FakeRunner`` (#7).

    The ``kind = LIVE`` twin of :func:`inject_runner`: live commands route through
    ``gda.cli._make_live_runner`` (the daemon IPC client), so a fake injected here
    exercises the full Typer→classify_live→JSON pipeline without a real daemon.
    """
    fake = FakeRunner(result)
    monkeypatch.setattr("gda.cli._make_live_runner", lambda binary, project=None: fake)
    return fake


def screen_capture_reply(png_base64: str, *, width: int, height: int) -> dict:
    """A canned ``screen capture`` HARNESS reply payload (#222).

    The wire shape the gda harness emits in the ADR-0002 sentinel for a single
    frame: the PNG bytes base64-encoded plus the frame's dims and format. The CLI
    recipe decodes ``png_base64`` and WRITES a file, so a command test drives the
    real decode/write path with a tiny real PNG.
    """
    import base64

    raw = base64.b64decode(png_base64)
    return {
        "width": width,
        "height": height,
        "format": "png",
        "bytes": len(raw),
        "png_base64": png_base64,
    }


def screen_frames_reply(
    png_base64s: list[str], *, width: int = 16, height: int = 16
) -> dict:
    """A canned ``screen frames`` HARNESS reply payload (#222).

    The wire shape the gda harness emits for a multi-frame window: a list of
    per-frame entries, each carrying its PNG base64 + dims + format, plus the
    window's frame ``count``. The CLI recipe writes one PNG file per frame.
    """
    import base64

    frames = [
        {
            "width": width,
            "height": height,
            "format": "png",
            "bytes": len(base64.b64decode(b64)),
            "png_base64": b64,
        }
        for b64 in png_base64s
    ]
    return {"count": len(frames), "frames": frames}


# A sample ``gda info`` result, shaped as ``Engine.get_version_info()`` reports
# it. Shared by the info success/schema tests so the canned engine version has a
# single source of truth (issue #39).
VERSION_INFO = {
    "major": 4,
    "minor": 6,
    "patch": 3,
    "hex": 0x040603,
    "status": "stable",
    "build": "official",
    "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
    "string": "4.6.3-stable (official)",
    "timestamp": 0,
}

# Canned ``gda scene <command> --json`` result payloads. Defined here so the
# scene command tests and the --schema sample-validation tests share one source
# rather than the latter importing them from the former (issue #39).
SCENE_CREATE_RESULT = {
    "path": "/tmp/proj/main.tscn",
    "root_name": "main",
    "root_type": "Node2D",
    "created_dirs": [],
}

SCENE_GET_RESULT = {
    "path": "/tmp/proj/main.tscn",
    "root": {
        "name": "main",
        "type": "Node2D",
        "children": [
            {
                "name": "Hero",
                "type": "Sprite2D",
                "children": [{"name": "Hitbox", "type": "Area2D", "children": []}],
            }
        ],
    },
}

SCENE_LIST_RESULT = {
    "scenes": [
        {"path": "res://main.tscn", "root_name": "main", "root_type": "Node2D"},
        {"path": "res://ui/menu.tscn", "root_name": "Menu", "root_type": "Control"},
        {"path": "res://broken.tscn", "root_name": None, "root_type": None},
    ]
}

SCENE_DELETE_RESULT = {
    "path": "/tmp/proj/old.tscn",
    "root_name": "old",
    "root_type": "Node2D",
}

# Canned ``gda node <command> --json`` result payloads. Defined here so the node
# command tests and the --schema sample-validation tests share one source rather
# than the latter importing them from the former (issue #178).
NODE_ADD_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "name": "Hero",
    "type": "Sprite2D",
    "script_class": None,
}

NODE_LIST_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "root": {
        "name": "main",
        "type": "Node2D",
        "path": ".",
        "children": [
            {
                "name": "Hero",
                "type": "Sprite2D",
                "path": "Hero",
                "children": [
                    {
                        "name": "Hitbox",
                        "type": "Area2D",
                        "path": "Hero/Hitbox",
                        "children": [],
                    }
                ],
            }
        ],
    },
}

NODE_GET_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "name": "Hero",
    "type": "Sprite2D",
    "properties": [
        {"name": "position", "type": "Vector2", "value": [10.0, 20.0]},
        {"name": "visible", "type": "bool", "value": True},
    ],
}

NODE_SET_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "property": "position",
    "type": "Vector2",
    "value": [3.0, 4.0],
}

NODE_REMOVE_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "name": "Hero",
    "type": "Sprite2D",
}

NODE_DUPLICATE_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "source_path": "Hero",
    "path": "Hero2",
    "name": "Hero2",
    "type": "Sprite2D",
}

NODE_MOVE_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "source_path": "Hero",
    "new_parent": "Enemies",
    "path": "Enemies/Hero",
    "name": "Hero",
    "type": "Sprite2D",
}

NODE_CONNECT_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "from": "Emitter",
    "signal": "timeout",
    "to": "Receiver",
    "method": "on_timeout",
}

# Canned ``gda script <command> --json`` result payloads (issue #178).
SCRIPT_CREATE_RESULT = {
    "path": "/tmp/proj/hero.gd",
    "class_name": "Hero",
    "extends": "Node2D",
    "created_dirs": [],
}

SCRIPT_GET_RESULT = {
    "path": "/tmp/proj/hero.gd",
    "source": "class_name Hero\nextends Node2D\n",
    "class_name": "Hero",
    "extends": "Node2D",
}

SCRIPT_LIST_RESULT = {
    "scripts": [
        {"path": "res://hero.gd", "class_name": "Hero", "extends": "Node2D"},
        {"path": "res://util.gd", "class_name": None, "extends": "RefCounted"},
        {"path": "res://empty.gd", "class_name": None, "extends": None},
    ]
}

SCRIPT_SET_RESULT = {
    "path": "/tmp/proj/hero.gd",
    "class_name": "Hero",
    "extends": "Node2D",
}

# Canned ``gda resource <command> --json`` result payloads (issue #178). For
# ``resource uid``, both directions converge on one ``{queried, uid, path}``
# shape, so ``UID``/``PATH`` are shared constants too.
RESOURCE_CREATE_RESULT = {
    "path": "/tmp/proj/palette.tres",
    "type": "Gradient",
    "created_dirs": [],
}

RESOURCE_GET_RESULT = {
    "path": "/tmp/proj/palette.tres",
    "type": "Gradient",
    "properties": [
        {"name": "resource_name", "type": "String", "value": ""},
        {"name": "interpolation_mode", "type": "int", "value": 0},
    ],
}

RESOURCE_SET_RESULT = {
    "path": "/tmp/proj/palette.tres",
    "property": "interpolation_mode",
    "type": "int",
    "value": 1,
}

RESOURCE_DELETE_RESULT = {
    "path": "/tmp/proj/palette.tres",
    "type": "Gradient",
}

UID = "uid://caax1gby1api1"
PATH = "res://data.tres"

UID_TO_PATH_RESULT = {"queried": "uid", "uid": UID, "path": PATH}
PATH_TO_UID_RESULT = {"queried": "path", "uid": UID, "path": PATH}

# Canned ``gda export <command> --json`` result payloads (issue #178).
EXPORT_LIST_RESULT = {
    "presets": [
        {"index": 0, "name": "Linux/X11", "platform": "Linux/X11", "runnable": True},
        {"index": 1, "name": "Web", "platform": "Web", "runnable": False},
    ]
}

EXPORT_GET_RESULT = {
    "index": 1,
    "name": "Web",
    "platform": "Web",
    "runnable": False,
    "export_path": "build/index.html",
    "templates_installed": True,
    "templates_version": "4.6.3.stable",
}

# Canned ``gda project <command> --json`` analysis result payloads (issue #178).
DEPENDENCIES_RESULT = {
    "dependencies": [
        {
            "path": "res://main.tscn",
            "depends_on": [
                {"path": "res://hero.tscn", "kind": "ext_resource"},
                {"path": "res://icon.png", "kind": "ext_resource"},
            ],
        },
        {"path": "res://hero.tscn", "depends_on": []},
    ]
}

FIND_REFERENCES_RESULT = {
    "target": "res://hero.gd",
    "references": [
        {
            "path": "res://hero.tscn",
            "kind": "ext_resource",
            "context": 'res://hero.gd type="Script"',
        }
    ],
}

UNUSED_RESULT = {"unused": ["res://orphan.png", "res://orphan.tres"]}

STATISTICS_RESULT = {
    "total_files": 5,
    "total_lines": 120,
    "by_extension": [
        {"extension": "gd", "files": 2, "lines": 100},
        {"extension": "tscn", "files": 2, "lines": 20},
    ],
    "autoloads": [{"name": "GameState", "path": "res://game_state.gd"}],
    "plugins": ["res://addons/widget/plugin.cfg"],
    "scene_count": 2,
    "script_count": 2,
    "resource_count": 1,
}

# Canned ``gda shader``/``gda theme`` asset-file ``--json`` result payloads
# (issue #178).
SHADER_CREATE_RESULT = {
    "path": "/tmp/proj/wave.gdshader",
    "shader_type": "canvas_item",
    "created_dirs": [],
}

SHADER_GET_RESULT = {
    "path": "/tmp/proj/wave.gdshader",
    "source": "shader_type canvas_item;\n",
    "shader_type": "canvas_item",
}

SHADER_SET_RESULT = {"path": "/tmp/proj/wave.gdshader", "shader_type": "spatial"}

THEME_CREATE_RESULT = {
    "path": "/tmp/proj/ui.tres",
    "type": "Theme",
    "created_dirs": [],
}

# A sample ``gda game tree`` result — the running game's runtime scene tree
# (ADR-0019). Shared by the game-command success/schema tests.
GAME_TREE_RESULT = {
    "root": {
        "name": "Main",
        "type": "Node2D",
        "path": "/root/Main",
        "children": [
            {
                "name": "Player",
                "type": "CharacterBody2D",
                "path": "/root/Main/Player",
                "children": [],
            }
        ],
    }
}

# Sample ``gda game get`` / ``gda game set`` results — a running node's runtime
# properties, addressed by the absolute runtime path (#220). Shared by the
# game-command success/schema tests; the value projection mirrors NodeProperty,
# the same shape ``node get`` reports.
GAME_GET_RESULT = {
    "path": "/root/Main/Player",
    "name": "Player",
    "type": "CharacterBody2D",
    "properties": [
        {"name": "position", "type": "Vector2", "value": [10.0, 20.0]},
        {"name": "visible", "type": "bool", "value": True},
    ],
}

GAME_SET_RESULT = {
    "path": "/root/Main/Player",
    "property": "position",
    "type": "Vector2",
    "value": [10.0, 20.0],
}

# Sample ``gda diag errors`` result — the running game's runtime errors,
# daemon-served from the Session log (#224). Shared by the diag-command
# success/schema/render tests. ``errors`` carries warnings too, distinguished by
# ``level``; a bare error may omit the location fields. (The raw ``diag log`` is
# superseded by ``gda logger tail`` — see ``LOGGER_TAIL_RAW_RESULT``, #281.)
DIAG_ERRORS_RESULT = {
    "errors": [
        {
            "level": "error",
            "message": "boom",
            "function": "_ready",
            "file": "res://main.gd",
            "line": 9,
            # A runtime GDScript error carries its ordered call stack (#283),
            # most-recent-first; frame [0] equals the top {function,file,line}.
            "callstack": [
                {"function": "_ready", "file": "res://main.gd", "line": 9},
                {"function": "a", "file": "res://main.gd", "line": 6},
            ],
        },
        {
            "level": "warning",
            "message": "careful",
            "function": "_process",
            "file": "res://main.gd",
            "line": 20,
            "callstack": [],  # a warning has no backtrace
        },
        {
            "level": "error",
            "message": "no location here",
            "function": None,
            "file": None,
            "line": None,
            "callstack": [],
        },
    ]
}

# Sample ``gda logger tail`` results — the running game's STRUCTURED runtime log,
# daemon-served from the Session log (#281, ADR-0026). Shared by the
# logger-command success/schema/render tests. The default carries typed
# ``records`` (the closed level enum, sub-kind in ``origin``, ``source`` when
# known, ``fields`` present-but-empty); ``--raw`` is the SAME ``records`` shape
# with every line an unclassified ``info`` record (verbatim message).
LOGGER_TAIL_RESULT = {
    "records": [
        {
            "seq": 0,
            "level": "info",
            "message": "known line",
            "source": None,
            "origin": None,
            "fields": {},
        },
        {
            "seq": 1,
            "level": "error",
            "message": "boom",
            "source": {"function": "_ready", "file": "res://main.gd", "line": 9},
            "origin": "engine",
            "fields": {},
        },
        {
            "seq": 2,
            "level": "warning",
            "message": "careful",
            "source": {"function": "_process", "file": "res://main.gd", "line": 20},
            "origin": "engine",
            "fields": {},
        },
    ],
}

# ``--raw``: the same ``records`` shape, every line an unclassified ``info`` record
# carrying its verbatim text (even an ``ERROR:`` header stays a plain info line).
LOGGER_TAIL_RAW_RESULT = {
    "records": [
        {"seq": 0, "level": "info", "message": "known line",
         "source": None, "origin": None, "fields": {}},
        {"seq": 1, "level": "info", "message": "ERROR: boom",
         "source": None, "origin": None, "fields": {}},
        {"seq": 2, "level": "info", "message": "   at: _ready (res://main.gd:9)",
         "source": None, "origin": None, "fields": {}},
        {"seq": 3, "level": "info", "message": "another line",
         "source": None, "origin": None, "fields": {}},
    ],
}

# Sample ``gda perf monitors`` / ``gda perf monitor`` results — the running game's
# runtime performance, served LIVE through gda-daemon (#223). Shared by the
# perf-command success/schema tests. ``monitors`` is keyed by monitor name; the
# timeline carries one of ``samples`` (property watch) or ``emissions`` (signal).
PERF_MONITORS_RESULT = {
    "timestamp": 12345,
    "monitors": {
        "fps": {"name": "fps", "type": "float", "value": 60.0},
        "static_memory": {"name": "static_memory", "type": "float", "value": 1048576.0},
        "node_count": {"name": "node_count", "type": "float", "value": 3.0},
    },
}

PERF_MONITOR_PROPERTY_RESULT = {
    "node": "/root/Main/Player",
    "kind": "property",
    "property": "position",
    "frames": 3,
    "samples": [
        {"frame": 0, "timestamp": 100, "value": [0.0, 0.0]},
        {"frame": 1, "timestamp": 116, "value": [1.0, 0.0]},
        {"frame": 2, "timestamp": 132, "value": [2.0, 0.0]},
    ],
    "emissions": [],
}

PERF_MONITOR_SIGNAL_RESULT = {
    "node": "/root/Main/Player",
    "kind": "signal",
    "signal": "hit",
    "frames": 3,
    "samples": [],
    "emissions": [
        {"frame": 1, "timestamp": 116, "args": [42]},
        {"frame": 2, "timestamp": 132, "args": []},
    ],
}

# Sample ``gda input`` results — the events the gda harness injected into the
# running game, served LIVE through gda-daemon (#221). Shared by the input-command
# success/schema tests. A key echoes the resolved keycode + modifiers; a mouse
# event echoes its viewport position; an action echoes the press strength; a
# sequence echoes the event count and the window length.
INPUT_KEY_RESULT = {
    "kind": "key",
    "key": "Right",
    "keycode": 4194321,
    "modifiers": [],
    "pressed": True,
}

INPUT_MOUSE_CLICK_RESULT = {
    "kind": "mouse_click",
    "position": [100.0, 200.0],
    "button": "left",
    "double": False,
}

INPUT_MOUSE_MOVE_RESULT = {
    "kind": "mouse_move",
    "position": [50.0, 60.0],
    "button": None,
    "double": None,
}

INPUT_ACTION_RESULT = {
    "kind": "action",
    "action": "jump",
    "pressed": True,
    "strength": 1.0,
}

INPUT_SEQUENCE_RESULT = {
    "kind": "sequence",
    "events": 3,
    "frames": 5,
}
