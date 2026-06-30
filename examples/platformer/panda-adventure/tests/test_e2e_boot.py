"""Integration seam (c) for the S0 walking skeleton — THE gate.

The full live loop through the gda CLI: a real ``gda daemon start`` installs the
GdaHarness and launches an Engine session on the first live op; ``gda game tree``
returns the running scene tree (the data-driven Block is present); ``gda game
get`` reads the Block's runtime color (applied from the GameConfig Resource in
``_ready``); and ``gda logger tail`` reads back the RICH ``<<<GDA:LOG>>>`` boot
record that ``GameLog.emit`` routed through the harness now that the session is
daemon-launched. Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: ``gda daemon start`` MUTATES ``project.godot`` (installs the autoload)
and copies harness files into ``res://``, so this runs against a throwaway COPY
of the committed project and never touches the real one. posix-only — the live
stack uses ``AF_UNIX`` (ADR-0021).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary

import build_config

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

# Same-environment gda resolution (ADR-0011): the module in this interpreter.
GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

# Not copied into the throwaway project: the test suite itself, import/build
# artifacts, and the derived .tres (rebuilt into the copy below).
_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)


def _make_project_copy(dst: Path) -> Path:
    """Copy the committed game into a throwaway dir and build its config there."""
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    build_config.build(
        json_path=dst / "data" / "json" / "boot_config.json",
        schema_path=dst / "data" / "schema" / "boot_config.schema.json",
        out_path=dst / "data" / "generated" / "boot_config.tres",
    )
    return dst


def _find_node(node: dict, name: str) -> dict | None:
    """Depth-first search a ``game tree`` subtree for a node by name."""
    if node.get("name") == name:
        return node
    for child in node.get("children", []):
        found = _find_node(child, name)
        if found is not None:
            return found
    return None


@pytest.mark.e2e
def test_daemon_serves_data_driven_block_and_boot_log(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    # Compare against the AUTHORITATIVE JSON, not hardcoded expectations.
    config = build_config.load_json(GAME_DIR / "data" / "json" / "boot_config.json")
    env = {**os.environ}

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    def poll_boot_record(timeout: float = 20.0) -> dict | None:
        # The session is already launched + warmed by `game tree`; this short poll
        # is a belt-and-suspenders for the log flush, not for launching the session.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            proc = run("logger", "tail")
            assert proc.returncode == 0, proc.stdout + proc.stderr
            for record in json.loads(proc.stdout)["records"]:
                if record["message"] == "boot" and record["origin"] == "gda_log":
                    return record
            time.sleep(1.0)
        return None

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        assert json.loads(started.stdout)["installed_harness"] is True

        # First live op launches the Engine session; the result is the RUNNING
        # game's runtime scene tree — the data-driven Block must be present.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        assert root["name"] == "Main"
        block = _find_node(root, "Block")
        assert block is not None, root
        assert block["type"] == "ColorRect"

        # The Block's runtime color was applied from the Resource in _ready (a
        # STABLE property — not position, which a tween is animating). Color is
        # float32 in Godot, so compare with a tolerance.
        got = run("game", "get", "/root/Main/Block", "--property", "color")
        assert got.returncode == 0, got.stdout + got.stderr
        props = json.loads(got.stdout)["properties"]
        color = next(p for p in props if p["name"] == "color")
        assert color["type"] == "Color"
        assert color["value"] == pytest.approx(config["block_color"], abs=1e-5)

        # The boot line is now a RICH gda_log record: with the session
        # daemon-launched, GameLog.emit routed through GdaHarness.gda_log.
        boot = poll_boot_record()
        assert boot is not None, "no gda_log 'boot' record found in the session log"
        assert boot["level"] == "info"
        assert boot["fields"]["scene"] == "main"
        assert boot["fields"]["tween_duration"] == pytest.approx(
            config["tween_duration"]
        )
    finally:
        run("daemon", "stop")
