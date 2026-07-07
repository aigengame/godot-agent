"""Integration seam (e2e) for the Panda Adventure Editor's DEBUG PALETTE (#441).

The palette's play-mode debug ops driven END TO END through gda live ops against
a running Engine session — proving the palette DOGFOODS gda's live layer
(gADR-0012): its whole control surface is runtime-drivable state an agent (here,
the test) reaches with the exact same commands a human's overlay buttons write.

The daemon boots the EDITOR entry scene (the copy's ``run/main_scene`` is
reconfigured to ``scenes/editor.tscn``; the editor is stripped from player builds,
not from a dev-machine daemon run), then every step is one gda live command:

- ``gda game set /root/Editor/DebugPalette --property play_active --value true``
  enters play mode (main.tscn instanced under PlayHost) — Wave 1 boots.
- ``gda game set … --property jump_to_wave --value 3`` clears the live enemies and
  (re)starts Wave 3 through the game's OWN wave director — asserted from the
  monotonic ``gda logger tail`` records (the #406 lesson: records, not position
  polls) AND the ``gda game tree`` (Wave 3's named spawn present, Wave 1's gone).
- ``gda game set … --property spawn --value true`` spawns one enemy on demand —
  the addressable ``DebugSpawn0`` appears in ``gda game tree`` + a ``debug_spawn``
  record.
- ``gda game set … --property god_mode --value true`` toggles god-mode, read back
  with ``gda game get … --property last_action`` (dogfooding the live READ too).

Isolation matches the other daemon e2e (a throwaway COPY; ``gda daemon start``
mutates ``project.godot``). posix-only (the live stack uses ``AF_UNIX``, ADR-0021)
and HEADLESS (no windowed/display gate — the palette ops are observed through the
tree/logger, not a screenshot).
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

GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

# The editor scene starts in EDIT mode; the palette node hangs off its root.
_PALETTE = "/root/Editor/DebugPalette"

_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)


def _make_editor_project(dst: Path) -> Path:
    """Copy the game, build its config, and boot the EDITOR scene by default.

    The editor is the daemon's ``run/main_scene`` here (a dev-machine tool run,
    gADR-0012) so the palette node is in the session's tree for gda live ops. The
    reconfig is a one-line text swap on the throwaway copy — the same
    reconfigure-the-copy pattern the waves e2e uses for its enemies config.
    """
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    build_config.build_all(root=dst)
    project_godot = dst / "project.godot"
    text = project_godot.read_text(encoding="utf-8")
    assert 'run/main_scene="res://scenes/main.tscn"' in text, "unexpected main_scene"
    project_godot.write_text(
        text.replace(
            'run/main_scene="res://scenes/main.tscn"',
            'run/main_scene="res://scenes/editor.tscn"',
        ),
        encoding="utf-8",
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


class _Session:
    """A tiny per-scenario harness over the gda CLI (the waves e2e idioms)."""

    def __init__(self, project: Path):
        self.project = project
        self.env = {**os.environ}

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(self.project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=90,
        )

    def records(self, message: str) -> list[dict]:
        proc = self.run("logger", "tail")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return [
            r
            for r in json.loads(proc.stdout)["records"]
            if r["message"] == message and r["origin"] == "gda_log"
        ]

    def poll(self, predicate, timeout: float = 20.0, interval: float = 0.5):
        deadline = time.monotonic() + timeout
        result = predicate()
        while not result and time.monotonic() < deadline:
            time.sleep(interval)
            result = predicate()
        return result

    def tree_root(self) -> dict:
        tree = self.run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        return json.loads(tree.stdout)["root"]

    def node_in_tree(self, name: str) -> dict | None:
        return _find_node(self.tree_root(), name)

    def set_palette(self, prop: str, value: str) -> None:
        """One ``gda game set`` on a palette property — the drivable op surface."""
        proc = self.run("game", "set", _PALETTE, "--property", prop, "--value", value)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def get_palette(self, prop: str):
        """One ``gda game get`` on a palette property (the live READ dogfood)."""
        proc = self.run("game", "get", _PALETTE, "--property", prop)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        for p in json.loads(proc.stdout)["properties"]:
            if p["name"] == prop:
                return p["value"]
        raise AssertionError(f"palette property {prop} not returned")


@pytest.mark.e2e
def test_palette_ops_drive_the_running_game(tmp_path, daemon_runtime_dir):
    """Every palette op functions when driven through the gda daemon (gADR-0012)."""
    project = _make_editor_project(tmp_path / "game")
    enemies = build_config.load_composed("data/json/enemies_config.json")
    waves = enemies["waves"]
    wave_one_name = waves[0]["spawns"][0]["name"]  # "Enemy"
    wave_three_name = waves[2]["spawns"][0]["name"]  # "SwarmMeleeA"
    total_waves = len(waves)
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # The first live op launches the session: the editor boots in EDIT mode
        # (no play instance, so no game tree under PlayHost yet).
        assert s.poll(lambda: bool(s.records("editor_ready"))), "editor never booted"

        # --- edit<->play switch: play_active drives main.tscn under PlayHost.
        s.set_palette("play_active", "true")
        first = s.poll(lambda: bool(s.records("wave_started")))
        assert first, "entering play did not boot the wave schedule"
        assert s.records("wave_started")[0]["fields"]["wave"] == 1
        assert s.poll(lambda: s.node_in_tree(wave_one_name) is not None), (
            "Wave 1's spawn never entered the running tree"
        )

        # --- WAVE JUMP: clear the live enemies + (re)start Wave 3 via the game's
        # own director. Assert from the monotonic records AND the runtime tree.
        s.set_palette("jump_to_wave", "3")
        assert s.poll(
            lambda: any(
                r["fields"]["wave"] == 3 for r in s.records("debug_wave_jump")
            )
        ), "no debug_wave_jump record for wave 3"
        jump = s.records("debug_wave_jump")[-1]["fields"]
        assert jump == {"wave": 3, "total": total_waves}
        assert s.records("wave_started")[-1]["fields"]["wave"] == 3, (
            "the game director did not (re)start Wave 3"
        )
        assert s.poll(lambda: s.node_in_tree(wave_three_name) is not None), (
            "Wave 3's named spawn never materialized after the jump"
        )
        assert s.poll(lambda: s.node_in_tree(wave_one_name) is None), (
            "the jump did not clear Wave 1's live enemy"
        )

        # --- SPAWN ON DEMAND: one addressable enemy at the default lane.
        s.set_palette("spawn", "true")
        assert s.poll(lambda: bool(s.records("debug_spawn"))), "no debug_spawn record"
        assert s.node_in_tree("DebugSpawn0") is not None, (
            "the on-demand spawn never entered the runtime tree"
        )
        assert s.records("debug_spawn")[0]["fields"]["name"] == "DebugSpawn0"

        # --- GOD MODE: toggle, then read the op back through gda's live READ.
        s.set_palette("god_mode", "true")
        god = s.poll(lambda: bool(s.records("debug_god_mode")))
        assert god and s.records("debug_god_mode")[-1]["fields"]["on"] is True, (
            "god-mode toggle produced no debug_god_mode record"
        )
        assert s.get_palette("last_action") == "god_mode:true", (
            "gda game get did not read the palette's op back"
        )
    finally:
        s.run("daemon", "stop")
