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

from gda.export_runner import ExportRunOutput
from gda.runner import RunResult


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
    a canned :class:`~gda.export_runner.ExportRunOutput`, so the native-export
    pipeline is exercised without a real engine, mirroring :class:`FakeRunner` for
    the sentinel channel.
    """

    def __init__(self, output: ExportRunOutput) -> None:
        self.output = output
        self.calls: list[tuple[str, str, str]] = []

    def run(self, preset: str, mode: str, output_path: str) -> ExportRunOutput:
        self.calls.append((preset, mode, output_path))
        return self.output


def sentinel(payload: dict) -> str:
    """Wrap ``payload`` in the ADR-0002 result sentinels, as operations.gd emits."""
    return f"<<<GDA:RESULT>>>{json.dumps(payload)}<<<GDA:END>>>\n"


def error_sentinel(code: str, message: str) -> str:
    """Wrap a minimal ADR-0002 operation error envelope in result sentinels."""
    return sentinel({"error": {"code": code, "message": message}})


def inject_runner(monkeypatch, result: RunResult) -> FakeRunner:
    """Swap the CLI's runner seam for a ``FakeRunner`` returning ``result``."""
    fake = FakeRunner(result)
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)
    return fake


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
