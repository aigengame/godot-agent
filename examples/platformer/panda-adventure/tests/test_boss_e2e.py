"""Integration seam (c) for the S8 Boss Warp kit (gADR-0009) — THE gate.

The live Warp rotation through the gda CLI against a running Engine session,
on a throwaway copy whose enemies JSON is reconfigured wholesale (the
waves-e2e precedent): Wave 1 IS the Boss, its rotation numbers shrunk and
determinized by data (huge aggro so the gate opens from spawn, one warp per
session via a long cooldown, zero move speed so every position is
formula-exact).

What the session proves, in causal order:

- **The rotation fires and telegraphs**: ``warp_tell`` -> ``warp_blink`` ->
  ``time_field_spawned`` walk the monotonic log in order (#406 lesson:
  state from records, not polls).
- **The landing is the pure formula**: ``warp_blink.to_x`` equals the
  far-side clamp computed from the copy's OWN config (player start, offset,
  platform extent) — never a hardcoded number.
- **The field is the warp's wake**: spawned at the landing with the copy's
  radius/factor/duration.
- **The Player actually slows** — the dilation edge record fires, and a
  physics-clocked held walk inside the zone covers ~factor x the distance
  the SAME walk covers after expiry (a relative proof, insulated from
  absolute speed drift).
- **Tank melee is un-deferred**: the adjacent Boss lands ``enemy_attack``
  records with ``archetype == "tank"`` and the Player takes hits.
- **Expiry releases**: ``time_field_expired`` fires and the Player's
  dilation edge returns to 1.0.

Every expectation derives from the copy's authoritative JSON, never
hardcoded. Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_waves_e2e`` (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX); headless.
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

_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)

_BOSS_KIND = "alien_boss_tank"
_BOSS_SPAWN = [700.0, 412.0]
# The held-walk length used for both displacement probes, in physics ticks.
_WALK_TICKS = 30


def _reconfigure(config: dict) -> dict:
    """Wave 1 IS the Boss; the rotation determinized by data (never code).

    - ``aggro_range`` huge: the warp gate opens from the spawn distance.
    - ``warp_cooldown`` a minute: exactly ONE rotation per session (the
      first is -INF-sentinel-gated by distance alone).
    - ``move_speed`` 0: the Boss holds its landing, so every distance is
      formula-exact for the whole session.
    - short tell/recovery, a session-length field, and a radius wide enough
      that both the landing-adjacent Player AND the whole slowed walk stay
      inside the zone.
    """
    boss = config["kinds"][_BOSS_KIND]
    boss["aggro_range"] = 3000.0
    boss["move_speed"] = 0.0
    boss["warp_cooldown"] = 60.0
    boss["warp_trigger_range"] = 120.0
    boss["warp_tell_duration"] = 0.3
    boss["warp_recovery_duration"] = 0.2
    boss["time_field_radius"] = 400.0
    boss["time_field_duration"] = 6.0
    config["waves"] = [
        {"spawns": [{"kind": _BOSS_KIND, "name": "Boss", "position": _BOSS_SPAWN}]}
    ]
    return config


def _make_project_copy(dst: Path) -> Path:
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    enemies_path = dst / "data" / "json" / "enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    enemies_path.write_text(
        json.dumps(_reconfigure(config), indent=2) + "\n", encoding="utf-8"
    )
    build_config.build_all(root=dst)
    return dst


def _expected_landing_x(player_x: float, enemies: dict, level_cfg: dict) -> float:
    """The gADR-0009 landing formula, replicated from the copy's config.

    The Boss spawns to the Player's RIGHT, so the far side is the LEFT
    (sign(player.x - boss.x) = -1), clamped to the AUTHORED Arena interval —
    the level authority's arena_min_x/arena_max_x, gADR-0010 — inset by half
    the Boss's width.
    """
    boss = enemies["kinds"][_BOSS_KIND]
    half_body = boss["size"][0] / 2.0
    arena_min = level_cfg["arena_min_x"] + half_body
    arena_max = level_cfg["arena_max_x"] - half_body
    return min(max(player_x - boss["warp_offset"][0], arena_min), arena_max)


class _Session:
    """A tiny per-scenario harness over the gda CLI (the S4 e2e idioms)."""

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

    def launch(self) -> None:
        tree = self.run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr

    def position(self, node: str) -> list[float]:
        got = self.run("game", "get", node, "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == "position":
                return p["value"]
        raise AssertionError("position not returned")

    def held_walk(self, ticks: int) -> float:
        """Hold move_right for ``ticks`` physics frames; return the x covered.

        Input rides the physics clock (#406); the walk is measured after the
        release settles so the instantaneous-horizontal blockout yields an
        exact ticks * speed / 60 displacement.
        """
        before = self.position("/root/Main/Player")[0]
        seq = self.run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": "move_right", "physics_frame": 0},
                    {
                        "type": "action",
                        "action": "move_right",
                        "release": True,
                        "physics_frame": ticks,
                    },
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr
        # The sequence op returns when injected; wait for the hold to play out.
        moved = self.poll(
            lambda: self.position("/root/Main/Player")[0],
            timeout=5.0,
            interval=0.25,
        )
        assert moved is not None
        # Poll until x stabilizes (two consecutive equal reads).
        last = moved
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.25)
            now_x = self.position("/root/Main/Player")[0]
            if now_x == last:
                break
            last = now_x
        return last - before


@pytest.mark.e2e
def test_boss_warp_rotation_slows_the_player_and_releases(tmp_path, daemon_runtime_dir):
    """One full Warp rotation, live: tell -> formula blink -> zone -> release."""
    project = _make_project_copy(tmp_path / "game")
    enemies = json.loads(
        (project / "data" / "json" / "enemies_config.json").read_text()
    )
    boss = enemies["kinds"][_BOSS_KIND]
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    level_cfg = build_config.load_json(GAME_DIR / "data" / "json" / "level_config.json")
    move_speed = player_cfg["move_speed"]
    factor = boss["time_field_factor"]
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        # The rotation telegraphs, blinks, and drops the field — in order.
        assert s.poll(lambda: s.records("warp_tell")), "warp never telegraphed"
        tell = s.records("warp_tell")[0]["fields"]
        assert tell["x"] == pytest.approx(_BOSS_SPAWN[0]), (
            "the tell must fire at the spawn (cooldown-stamped at decision)"
        )
        assert s.poll(lambda: s.records("warp_blink")), "warp never blinked"
        blink = s.records("warp_blink")[0]["fields"]
        assert blink["from_x"] == pytest.approx(_BOSS_SPAWN[0])
        # The landing is the pure far-side formula over the copy's config:
        # the resting Player has no input, so its x is the config start.
        expected_x = _expected_landing_x(
            player_cfg["player_start"][0], enemies, level_cfg
        )
        assert blink["to_x"] == pytest.approx(expected_x), (
            f"landing must be the gADR-0009 formula: {blink}"
        )

        # The field is the warp's wake: spawned AT the landing, with the
        # copy's own numbers.
        assert s.poll(lambda: s.records("time_field_spawned")), "no field spawned"
        field = s.records("time_field_spawned")[0]["fields"]
        assert field["x"] == pytest.approx(blink["to_x"])
        assert field["y"] == pytest.approx(blink["to_y"])
        assert field["radius"] == pytest.approx(boss["time_field_radius"])
        assert field["factor"] == pytest.approx(factor)
        assert field["duration"] == pytest.approx(boss["time_field_duration"])

        # The Boss actually moved in the runtime tree, not just in the log.
        assert s.position("/root/Main/Boss")[0] == pytest.approx(blink["to_x"], abs=2.0)

        # The Player is inside the zone: the dilation EDGE record fires with
        # the config factor.
        dilated = s.poll(lambda: s.records("player_time_dilated"))
        assert dilated, "the Player never dilated inside the zone"
        assert dilated[0]["fields"]["factor"] == pytest.approx(factor)

        # The slowed walk: a physics-clocked hold inside the zone. The
        # instantaneous-horizontal blockout makes the full-speed cover
        # ticks * move_speed / 60; dilation scales it by the factor.
        slow_dx = s.held_walk(_WALK_TICKS)
        full_cover = _WALK_TICKS * move_speed / 60.0
        assert slow_dx == pytest.approx(full_cover * factor, rel=0.2), (
            f"walk inside the zone should cover ~{factor} x {full_cover}, got {slow_dx}"
        )

        # Tank melee is un-deferred: the landing-adjacent Boss swings and
        # the Player takes symmetric-formula hits (the S2 pipeline).
        attacks = s.poll(lambda: s.records("enemy_attack"))
        assert attacks, "the Tank Boss never attacked"
        assert attacks[0]["fields"]["archetype"] == "tank"
        assert s.records("player_hit"), "the Boss's melee never landed"

        # Expiry releases: the field reports it, and the Player's edge
        # returns to 1.0 (the copy's duration bounds the wait).
        assert s.poll(
            lambda: s.records("time_field_expired"),
            timeout=boss["time_field_duration"] + 10.0,
        ), "the field never expired"
        assert s.poll(
            lambda: any(
                r["fields"]["factor"] == pytest.approx(1.0)
                for r in s.records("player_time_dilated")
            )
        ), "the Player was never released to full speed"

        # The released walk covers the FULL distance: the relative proof
        # that the zone (not drift) was what slowed the Player.
        full_dx = s.held_walk(_WALK_TICKS)
        assert full_dx == pytest.approx(full_cover, rel=0.2), (
            f"walk after expiry should cover ~{full_cover}, got {full_dx}"
        )
        assert slow_dx < full_dx * 0.75, (
            "the zoned walk must be clearly slower than the released walk"
        )

        # Exactly one rotation this session (the minute-long cooldown).
        assert len(s.records("warp_blink")) == 1
    finally:
        s.run("daemon", "stop")
