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
import re
import sys

from gda.runner import RunResult

# Typer renders help and usage errors through Rich, which colorizes when it
# believes it is on a terminal — under GitHub Actions it does, while a local
# `uv run pytest` usually does not. So the same assertion can pass locally and
# fail in CI on escape sequences alone. Every assertion on help/usage TEXT goes
# through `plain_text` (issue #671); assertions on a command's JSON result do
# not need it (a JSON result is echoed verbatim, never Rich-rendered).
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def plain_text(text: str) -> str:
    """Return ``text`` with any ANSI escape sequences removed."""
    return ANSI_ESCAPE.sub("", text)


# The box-drawing characters Rich uses to frame a Click usage-error panel
# (``╭─...─╮`` etc.) — a SEPARATE concern from `ANSI_ESCAPE` above, since a
# usage error's border survives even where color does not.
_RICH_PANEL_BORDER = re.compile(r"[─-╿]")


def panel_text(text: str) -> str:
    """Normalize Rich-rendered TEXT to one line of prose.

    The text-level half of :func:`usage_error_text`, taking a plain string rather
    than a ``CliRunner`` result, because Rich frames HELP the same way it frames a
    usage error: ANSI color, box-drawing borders, and hard wraps that land in the
    middle of a sentence. Any assertion on rendered gda text — help from a
    ``CliRunner`` result, or a subprocess ``CompletedProcess`` stream in an e2e —
    goes through this, so no test re-derives the same normalization (#770 review).
    """
    return re.sub(r"\s+", " ", _RICH_PANEL_BORDER.sub(" ", plain_text(text))).strip()


def usage_error_text(result) -> str:
    """Normalize a CliRunner ``Result``'s Click usage-error panel to plain text.

    A model refusal on the argv path (``gda.dispatch.params_or_bad_parameter``,
    ADR-0015) is a Click usage error: exit 2, the message inside a Rich panel on
    stderr. This asserts that exit status and returns the whole collapsed panel
    (the ``Usage: ...`` preamble, the ``Error`` heading, and the ``Invalid value:
    <message>`` body) through :func:`panel_text`, so a caller matches whichever
    substring it needs, or extracts the message itself. Shared by every test
    asserting on an argv usage error's text, instead of each redefining the same
    normalization (#713 review).
    """
    assert result.exit_code == 2, result.stdout + result.stderr
    return panel_text(result.stderr)


# The gda CLI invocation prefix for e2e subprocess tests. Resolved as the gda
# MODULE in *this* interpreter's environment — `[sys.executable, "-m", "gda"]` —
# never a PATH-resolved global. This is the same same-environment resolution
# ADR-0011 (Design decision 3) mandates for gda-mcp ("never a wrong global `gda` a
# PATH lookup might resolve"); a `which`-style PATH lookup would instead run whatever
# is first on PATH (e.g. a uv-tool global, or another worktree's editable install).
# Under `uv run pytest`, sys.executable is this checkout's venv, so `-m gda` runs
# this checkout's editable gda deterministically. Spread it: `[*GDA_CMD, *args]`.
GDA_CMD = [sys.executable, "-m", "gda"]


def templates_installed(gda, preset: str = "Linux/X11") -> bool:
    """Whether the running engine has export templates, via ``gda export get``.

    ``gda`` is a bound ``gda <args> --json`` callable (e.g. the e2e tests'
    ``_gda_project``). The single source of truth for the e2e template-presence
    policy, shared by the export-run happy-path skip and the harness template-gate
    behavioural proof (#301). ``preset`` only needs to NAME a preset that exists in
    the project so ``export get`` succeeds; the verdict itself is preset-independent
    — ``export get`` checks only that the engine's per-version templates DIRECTORY
    exists, not the platform-specific template files — so a caller on a host with the
    version dir present but the host platform's file missing still sees ``True`` and
    must tolerate the export failing later.
    """
    got = gda("export", "get", "--preset", preset, "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    return json.loads(got.stdout)["templates_installed"]


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
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)
    return fake


def no_engine_teardown(monkeypatch) -> None:
    """No-op the engine teardown for a test whose session process is a stand-in (#725).

    ``_terminate`` signals a REAL child and reaps it; a fake process has no ``pid``
    to signal, so a test that fakes one must neutralize it. Named and shared rather
    than open-coded per test because this mock HIDES a real interaction — teardown
    is charged to the caller's readiness deadline (#725 re-review), and a suite that
    only ever mocks it cannot see that. A test that exercises teardown itself takes
    a real child and must NOT call this.
    """
    monkeypatch.setattr(
        "gda.daemon.session._terminate",
        lambda proc, deadline=None, owned_pgid=None: None,
    )


def inject_live_runner(monkeypatch, result: RunResult) -> FakeRunner:
    """Swap the CLI's LIVE (daemon) runner seam for a ``FakeRunner`` (#7).

    The ``kind = LIVE`` twin of :func:`inject_runner`: live commands route through
    ``gda.dispatch.make_live_runner`` (the daemon IPC client), so a fake injected
    here exercises the full Typer→classify_live→JSON pipeline without a real daemon.
    """
    fake = FakeRunner(result)
    monkeypatch.setattr(
        "gda.dispatch.make_live_runner", lambda binary, project=None: fake
    )
    return fake


def capture_receipt_reply(**overrides) -> dict:
    """A canned harness-side capture receipt (#660), with per-test overrides.

    The identity half the harness stamps into every capture reply; the CLI adds
    ``sha256`` after writing the file. Defaults describe a plain capture of a
    gda-authored scene (no uid, no predicate echo).
    """
    receipt = {
        "session_id": "a1b2c3d4e5f60718",
        "scene_path": "res://main.tscn",
        "scene_uid": None,
        "engine_frame": 400,
        "observed": None,
    }
    receipt.update(overrides)
    return receipt


# A 1x1 transparent PNG, base64 as the harness sends it: valid bytes, so a
# recipe that decodes and WRITES the file drives its real path. Lives here
# because two suites now capture through the same helpers.
PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def screen_capture_reply(png_base64: str, *, width: int, height: int) -> dict:
    """A canned ``screen capture`` HARNESS reply payload (#222).

    The wire shape the gda harness emits in the ADR-0002 sentinel for a single
    frame: the PNG bytes base64-encoded plus the frame's dims and format — and,
    since #660, the capture ``receipt`` (always present on the wire; a test
    exercising the missing-receipt violation deletes the key explicitly). The
    CLI recipe decodes ``png_base64`` and WRITES a file, so a command test
    drives the real decode/write path with a tiny real PNG.
    """
    import base64

    raw = base64.b64decode(png_base64)
    return {
        "width": width,
        "height": height,
        "format": "png",
        "bytes": len(raw),
        "png_base64": png_base64,
        "receipt": capture_receipt_reply(),
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
    "verified": True,
}

# Sample ``gda game call`` result — the projected return of a method the node's
# class declared callable in its ``GDA_CALLABLE`` script constant (#673).
GAME_CALL_RESULT = {
    "path": "/root/Main/QA",
    "name": "QA",
    "type": "Node2D",
    "method": "qa_current_state_contract",
    "value": {"phase": 3, "ready": True, "labels": ["a", "b"]},
}

# Sample ``gda game rect`` result — a running Control's rendered viewport-space
# rectangle, addressed by the absolute runtime path (#419).
GAME_RECT_RESULT = {
    "path": "/root/Main/HUD/Stats",
    "name": "Stats",
    "type": "VBoxContainer",
    "position": [24.0, 24.0],
    "size": [160.0, 48.0],
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
            "level": "info",
            "message": "ERROR: boom",
            "source": None,
            "origin": None,
            "fields": {},
        },
        {
            "seq": 2,
            "level": "info",
            "message": "   at: _ready (res://main.gd:9)",
            "source": None,
            "origin": None,
            "fields": {},
        },
        {
            "seq": 3,
            "level": "info",
            "message": "another line",
            "source": None,
            "origin": None,
            "fields": {},
        },
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

# A ``perf-sample`` WIRE reply (#662) — what the harness returns: raw per-frame
# rows only. Statistics and budget verdicts are computed CLI-side by the recipe,
# so the values here are chosen to make the aggregates exactly checkable:
# fps sorted = [55, 58, 60, 60, 62] -> mean 59, p50 60, p95 62 (nearest-rank);
# draw_calls sorted = [90, 95, 100, 110, 120] -> mean 103, p50 100, p95 120.
PERF_SAMPLE_REPLY = {
    "kind": "sample",
    "frames": 5,
    "monitors": ["fps", "draw_calls"],
    "samples": [
        {"frame": 0, "timestamp": 100, "values": {"fps": 60.0, "draw_calls": 100.0}},
        {"frame": 1, "timestamp": 116, "values": {"fps": 55.0, "draw_calls": 120.0}},
        {"frame": 2, "timestamp": 132, "values": {"fps": 62.0, "draw_calls": 90.0}},
        {"frame": 3, "timestamp": 148, "values": {"fps": 58.0, "draw_calls": 110.0}},
        {"frame": 4, "timestamp": 164, "values": {"fps": 60.0, "draw_calls": 95.0}},
    ],
}


def perf_sample_reply_all_monitors(names) -> dict:
    """A 1-frame ``perf-sample`` reply covering EVERY mirrored monitor name.

    The default (empty) selection samples ALL monitors, and the recipe
    correlates the reply's monitor list with that expectation — so the fake
    reply must cover the whole table for the default-selection test.
    """
    return {
        "kind": "sample",
        "frames": 1,
        "monitors": list(names),
        "samples": [
            {
                "frame": 0,
                "timestamp": 100,
                "values": {name: 1.0 for name in names},
            }
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

# A click is the COMPLETE activation gesture (#652): the harness reports the
# move/press/release phases at their window frames plus the focus evidence
# around the gesture.
INPUT_MOUSE_CLICK_RESULT = {
    "kind": "mouse_click",
    "position": [100.0, 200.0],
    "button": "left",
    "double": False,
    "phases": [
        {"frame": 0, "phase": "move"},
        {"frame": 1, "phase": "press"},
        {"frame": 2, "phase": "release"},
    ],
    "focus_before": None,
    "focus_after": "/root/Main/Btn",
}

# A tap is the press-hold-release gesture for one key or one action (#652); the
# key form echoes key/keycode/modifiers, the action form action/strength.
INPUT_TAP_KEY_RESULT = {
    "kind": "tap",
    "key": "Right",
    "keycode": 4194321,
    "modifiers": [],
    "hold_frames": 2,
    "settle_frames": 2,
    "frames": 5,
    "phases": [
        {"frame": 0, "phase": "press"},
        {"frame": 2, "phase": "release"},
    ],
    "focus_before": "/root/Main/A",
    "focus_after": "/root/Main/B",
}

INPUT_TAP_ACTION_RESULT = {
    "kind": "tap",
    "action": "jump",
    "strength": 1.0,
    "hold_frames": 2,
    "settle_frames": 2,
    "frames": 5,
    "phases": [
        {"frame": 0, "phase": "press"},
        {"frame": 2, "phase": "release"},
    ],
    "focus_before": None,
    "focus_after": None,
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


# --- The windowed-display test gate (#345, #667) -----------------------------
#
# One owner PER PYTEST ROOT for the reaction policy, because the reaction is NOT
# uniform and scattered per-test sets are what let the wrong one spread: the gates
# used to skip on every no-display code, so a confined run greened the suite with
# the rendered acceptance unexecuted — the exact GDA-DF-029 behaviour #667 exists
# to stop. A second, deliberate copy of this policy lives in
# examples/platformer/panda-adventure/tests/display_gate.py (a separate pytest
# root that cannot import this package) — keep the two in step when editing
# either side.
#
# The two reactions, and why they differ:
#
# - CAPABILITY (`live_windowed_unavailable`, `live_display_unavailable`): the host
#   genuinely cannot show a window. There is nothing to run, so SKIP is honest and a
#   visible `-rs` line records it.
# - PERMISSION (`live_windowed_permission_denied`): the host may well be able to —
#   this RUN is confined. The verdict is about the whole environment, not a
#   momentary display state, so it cannot be waited out or retried into passing.
#   Skipping would hide unexecuted rendered acceptance behind a green suite, so it
#   FAILS, carrying the remediation the error itself gives: re-run outside the
#   restriction.
WINDOWED_CAPABILITY_CODES = frozenset(
    {"live_windowed_unavailable", "live_display_unavailable"}
)
WINDOWED_PERMISSION_DENIED_CODE = "live_windowed_permission_denied"

_CONFINED_REMEDIATION = (
    "the windowed session was refused because this RUN is confined "
    "({detail}). Rendered acceptance did NOT execute; this is a loud failure "
    "rather than a skip so a sandboxed run cannot green the suite with it "
    "unexecuted (#667). Re-run outside the sandbox/restriction."
)


def handle_no_display_code(code, detail=""):
    """Apply the reaction policy to a gda error ``code``, if it is a display refusal.

    Skips on a capability refusal, FAILS on a permission refusal, and returns
    normally for anything else so the caller can raise its own assertion. Used on the
    post-start race path, where a live call reports the refusal even though the
    pre-flight probe passed.
    """
    import pytest

    if code == WINDOWED_PERMISSION_DENIED_CODE:
        pytest.fail(_CONFINED_REMEDIATION.format(detail=detail or code))
    if code in WINDOWED_CAPABILITY_CODES:
        pytest.skip(f"windowed session unavailable in this environment ({code})")


def require_windowed_host():
    """Pre-flight the host display probe with the same reaction policy.

    ``None`` verdict → return and run the test. A capability verdict → skip. A
    permission verdict → fail: a confined run must be loud, not green.
    """
    import pytest

    from gda.display import windowed_unavailable

    verdict = windowed_unavailable()
    if verdict is None:
        return
    # ONE cascade owner per root: delegate to handle_no_display_code so the
    # cross-root parity test covers the preflight too (PR #702 recheck). The
    # trailing skip is the conservative fallback for a verdict code the handler
    # does not classify — a non-None verdict must never proceed to a spawn.
    handle_no_display_code(verdict.code, verdict.reason)
    pytest.skip(verdict.reason)


def gda_error_code(stdout):
    """The ``error.code`` of a gda ``--json`` failure envelope, or ``None``."""
    try:
        return json.loads(stdout).get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


def assert_windowed_ok(result):
    """Assert a windowed-tier command succeeded, applying the display policy FIRST.

    The post-start race path for the repo's own e2e tiers. A windowed session can be
    refused *after* the pre-flight probe passed — the daemon re-checks at its
    authoritative launch boundary, and a live op can hit that on the lazy launch — and
    when it is, the reaction has to be the SAME one the pre-flight would have applied:
    a capability refusal skips, a permission refusal fails loudly with the
    remediation. Asserting ``returncode == 0`` straight away instead turned a
    capability verdict into a false RED here while the game's tiers skipped on it —
    one verdict, two meanings (#667 recheck).

    Anything that is not a display refusal falls through to the ordinary assertion,
    so a real regression still fails with the command's own output.
    """
    if result.returncode != 0:
        handle_no_display_code(gda_error_code(result.stdout))
    assert result.returncode == 0, result.stdout + result.stderr
    return result
