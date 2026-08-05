"""Integration seam (c) for S3 Gravity Gun / Gravity Field / MP economy — THE gate.

The full change-gravity loop through the gda CLI against a running Engine
session:

- ``gda game tree`` shows the scene-authored Obstacle; ``gda logger tail``
  returns its data-driven ``obstacle_ready`` record;
- ``fire`` fires the CURRENT weapon: before any switch it spawns a Laser bolt
  (``laser_fired``), never a Gravity Field — the spawn default;
- ``switch_weapon`` toggles to the Gravity Gun (``weapon_switched``) and
  ``fire`` now spends MP (``gravity_fired {mp_before, mp_after}``) and spawns
  a Gravity Field: the field is in the runtime tree, its ``gravity_field_
  spawned`` record carries the data-driven velocity/radius/duration, the
  in-range Obstacle is lifted, the out-of-range Enemy does NOT move (the field
  is LOCAL), and the Player never moves off its resting y (never affected —
  the collision mask, gADR-0002);
- walking in engages the S4 mobile Enemy, and a live-position retreat →
  re-face → fire choreography (ONE physics_frame input sequence, so its
  timing is engine-deterministic) drops the field on the chasing Enemy; the
  per-episode ``enemy_suspended`` peak-displacement record proves the lift
  (gADR-0002 suspension) — a monotonic observable, immune to CI pacing
  (#406). The clamp math itself is pinned headless in the logic seam;
- repeated fires drain MP to 0; at 0 MP the fire is refused
  (``gravity_blocked``, no new field) — the MP gate;
- with no Wine held, ``drink_wine`` is REFUSED too (``consumable_blocked`` —
  the S7 supply gate, gADR-0008): MP stays drained and the Gravity Gun stays
  blocked. The restore/re-arm half of the economy loop lives in
  ``test_items_e2e.py``, where the supply exists;
- switching back re-arms the Laser Gun (``laser_fired`` again) — the weapon
  toggle round-trips.

Every expectation derives from the AUTHORITATIVE JSON configs, never
hardcoded. Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_player_e2e`` (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX); headless —
Linux-CI-friendly.
"""

from __future__ import annotations

import json
import math
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


def _make_project_copy(dst: Path) -> Path:
    """Copy the committed game into a throwaway dir and build its config there."""
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    build_config.build_all(root=dst)
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
def test_daemon_serves_gravity_loop(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    # Every expectation derives from the AUTHORITATIVE JSON, never hardcoded.
    gravity = build_config.load_composed("content/data/json/gravity_config.json")
    combat = build_config.load_composed("content/data/json/combat_config.json")
    enemies = build_config.load_composed("content/data/json/enemies_config.json")
    player_cfg = build_config.load_composed("content/data/json/player_config.json")
    level_cfg = build_config.load_composed("content/data/json/level_config.json")
    rampart = next(p for p in level_cfg["platforms"] if p["name"] == "Rampart")
    mp_max = combat["player_stats"]["max_mp"]
    mp_cost = gravity["mp_cost"]
    obstacle_pos = gravity["obstacle_position"]
    # The Wave-1 spawn is the position authority (gADR-0005); the duplicated
    # legacy combat enemy_position was deleted by gADR-0013.
    enemy_pos = enemies["waves"][0]["spawns"][0]["position"]
    enemy_clamp = gravity["enemy_max_gravity_offset"]
    # The field velocity the runtime derives from the data (direction x strength).
    direction = gravity["field_direction"]
    length = math.hypot(*direction)
    field_velocity = [c / length * gravity["field_strength"] for c in direction]
    rest_y = (
        rampart["position"][1]
        - rampart["size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
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

    def records(message: str) -> list[dict]:
        proc = run("logger", "tail")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return [
            r
            for r in json.loads(proc.stdout)["records"]
            if r["message"] == message and r["origin"] == "gda_log"
        ]

    def poll(predicate, timeout: float = 20.0, interval: float = 0.5):
        deadline = time.monotonic() + timeout
        result = predicate()
        while not result and time.monotonic() < deadline:
            time.sleep(interval)
            result = predicate()
        return result

    def node_position(path: str) -> list[float]:
        got = run("game", "get", path, "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == "position":
                return p["value"]
        raise AssertionError(f"position not returned for {path}")

    def tap(action: str) -> None:
        """One press+release of an InputMap action (one is_action_just_pressed).

        physics_frame offsets: the game consumes input in _physics_process, and
        the idle-frame clock drifts against the physics clock on loaded CI
        runners, so all injected input rides the physics clock (#406).
        """
        seq = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": action, "physics_frame": 0},
                    {
                        "type": "action",
                        "action": action,
                        "release": True,
                        "physics_frame": 4,
                    },
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # The scene-authored Obstacle is in the live tree; no field exists yet.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        obstacle = _find_node(root, "Obstacle")
        assert obstacle is not None and obstacle["type"] == "StaticBody2D", root
        assert _find_node(root, "GravityField") is None, root

        # Its boot record carries the data-driven placement.
        ready = poll(lambda: records("obstacle_ready"))
        assert ready, "no gda_log 'obstacle_ready' record"
        assert ready[0]["fields"]["x"] == pytest.approx(obstacle_pos[0])
        assert ready[0]["fields"]["y"] == pytest.approx(obstacle_pos[1])

        # Let the Player settle on the platform before firing (S1-proven poll).
        assert poll(
            lambda: abs(node_position("/root/Main/Gameplay/Player")[1] - rest_y) <= 2.0
        ), "Player did not land before firing"

        # --- Default weapon: `fire` fires the CURRENT weapon, and the spawn
        # default is the Laser Gun — a bolt, never a Gravity Field, no MP spent.
        tap("fire")
        assert poll(lambda: records("laser_fired")), (
            "the default-weapon fire should spawn a Laser bolt"
        )
        assert not records("gravity_fired"), (
            "the default-weapon fire must not fire the Gravity Gun"
        )

        # --- Switch to the Gravity Gun.
        tap("switch_weapon")
        switched = poll(lambda: records("weapon_switched"))
        assert switched, "no gda_log 'weapon_switched' record"
        assert switched[-1]["fields"]["weapon"] == "gravity_gun"

        # --- First gravity fire: spends MP from the S2 StatsSystem and spawns
        # a field whose params are the authoritative data.
        obstacle_before = node_position("/root/Main/Gameplay/Obstacle")
        tap("fire")
        fired = poll(lambda: records("gravity_fired"))
        assert fired, "no gda_log 'gravity_fired' record"
        assert fired[0]["fields"]["mp_before"] == pytest.approx(mp_max)
        assert fired[0]["fields"]["mp_after"] == pytest.approx(mp_max - mp_cost)

        spawned = poll(lambda: records("gravity_field_spawned"))
        assert spawned, "no gda_log 'gravity_field_spawned' record"
        assert spawned[0]["fields"]["velocity_x"] == pytest.approx(field_velocity[0])
        assert spawned[0]["fields"]["velocity_y"] == pytest.approx(field_velocity[1])
        assert spawned[0]["fields"]["radius"] == pytest.approx(gravity["field_radius"])
        assert spawned[0]["fields"]["duration"] == pytest.approx(
            gravity["field_duration"]
        )

        # The field is a real node in the runtime tree (checked within its
        # config lifetime).
        def field_in_tree() -> bool:
            t = run("game", "tree")
            assert t.returncode == 0, t.stdout + t.stderr
            return _find_node(json.loads(t.stdout)["root"], "GravityField") is not None

        assert poll(field_in_tree, timeout=gravity["field_duration"], interval=0.2), (
            "the Gravity Field never appeared in the runtime scene tree"
        )

        # The in-range Obstacle is lifted (its y decreases: lift is the shipped
        # upward default) without horizontal drift.
        assert poll(
            lambda: (
                node_position("/root/Main/Gameplay/Obstacle")[1]
                < obstacle_before[1] - 10.0
            )
        ), "the Gravity Field did not lift the in-range Obstacle"
        assert node_position("/root/Main/Gameplay/Obstacle")[0] == pytest.approx(
            obstacle_before[0], abs=1.0
        )

        # The field is LOCAL: the far-away Enemy does not move...
        assert node_position("/root/Main/Gameplay/Enemy") == pytest.approx(
            enemy_pos, abs=1.0
        ), "the out-of-range Enemy must not be affected"
        # ...and it NEVER acts on the Player (mask guarantee): still resting.
        assert node_position("/root/Main/Gameplay/Player")[1] == pytest.approx(
            rest_y, abs=2.0
        )

        # --- Engage the Enemy and lift it with a field (gADR-0002 suspension).
        #
        # Since S4 the Enemy is a mobile melee CharacterBody2D (gADR-0003): it
        # aggros as the Player nears, chases into its keep band (a 2D distance
        # <= keep_range_max), and enemy bodies do not collide with the Player,
        # so by fire time it may stand ON the Player — while the field spawns
        # field_spawn_offset in FRONT of the facing. A shot aimed by the
        # CONFIG spawn window can then miss the Enemy entirely (#406, CI run
        # 28703817301: enemy 4.7 px behind the Player, field center 124.7 px
        # away, zero suspension frames). So walk in only until ENGAGED (live
        # gap <= the spawn offset), and aim the shot from LIVE positions.
        enemies_cfg = build_config.load_composed(
            "content/data/json/enemies_config.json"
        )
        enemy_spawn = next(
            s
            for wave in enemies_cfg["waves"]
            for s in wave["spawns"]
            if s["name"] == "Enemy"
        )
        enemy_speed = enemies_cfg["kinds"][enemy_spawn["kind"]]["move_speed"]
        player_speed = player_cfg["move_speed"]
        spawn_offset_x = gravity["field_spawn_offset"][0]
        platform_left = rampart["position"][0] - rampart["size"][0] / 2.0
        platform_right = rampart["position"][0] + rampart["size"][0] / 2.0
        # Godot's default fixed physics tick rate; project.godot does not
        # override physics/common/physics_ticks_per_second.
        physics_fps = 60.0

        def burst_right() -> None:
            seq = run(
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
                            "physics_frame": 12,
                        },
                    ]
                ),
            )
            assert seq.returncode == 0, seq.stdout + seq.stderr

        def live_gap() -> float:
            """Signed Enemy-minus-Player x gap from live positions."""
            return (
                node_position("/root/Main/Gameplay/Enemy")[0]
                - node_position("/root/Main/Gameplay/Player")[0]
            )

        gap = live_gap()
        for _ in range(40):
            if abs(gap) <= spawn_offset_x:
                break
            burst_right()
            gap = live_gap()
        assert abs(gap) <= spawn_offset_x, (
            f"the Player never engaged the Enemy: gap={gap}"
        )

        # The suspension shot: retreat AWAY from the chasing Enemy until the
        # gap reopens to ~field_spawn_offset, re-face, and fire — the field
        # then spawns on the Enemy. The whole choreography is ONE input
        # sequence on the physics clock, so its geometry cannot be stretched
        # by CLI round-trip latency; only the pre-read gap is approximate
        # (bounded by the keep band), and the field radius absorbs it.
        reface_frames = 4

        def suspension_shot() -> None:
            px = node_position("/root/Main/Gameplay/Player")[0]
            ex = node_position("/root/Main/Gameplay/Enemy")[0]
            # Retreat away from the Enemy; an overlapped (on-Player) Enemy
            # goes left, where the walk-in left the most platform room.
            away = -1.0 if ex >= px - 10.0 else 1.0
            open_rate = (player_speed - enemy_speed) / physics_fps
            close_rate = (player_speed + enemy_speed) / physics_fps
            # The gap the retreat must open so the Enemy sits on the field
            # center at the fire frame, after the re-face tap (and the fire
            # press two frames later) close part of it again.
            target_gap = spawn_offset_x + close_rate * (reface_frames + 2.0)
            retreat_frames = math.ceil(max(0.0, target_gap - abs(ex - px)) / open_rate)
            # Never retreat off the platform.
            room = (
                px - platform_left - 60.0 if away < 0.0 else platform_right - 60.0 - px
            )
            retreat_frames = max(
                0, min(retreat_frames, int(room * physics_fps / player_speed))
            )
            move_action = "move_left" if away < 0.0 else "move_right"
            face_action = "move_right" if away < 0.0 else "move_left"
            t0 = retreat_frames
            seq = run(
                "input",
                "sequence",
                "--events",
                json.dumps(
                    [
                        {"type": "action", "action": move_action, "physics_frame": 0},
                        {
                            "type": "action",
                            "action": move_action,
                            "release": True,
                            "physics_frame": t0,
                        },
                        {
                            "type": "action",
                            "action": face_action,
                            "physics_frame": t0 + 1,
                        },
                        {
                            "type": "action",
                            "action": face_action,
                            "release": True,
                            "physics_frame": t0 + 1 + reface_frames,
                        },
                        {
                            "type": "action",
                            "action": "fire",
                            "physics_frame": t0 + 2 + reface_frames,
                        },
                        {
                            "type": "action",
                            "action": "fire",
                            "release": True,
                            "physics_frame": t0 + 6 + reface_frames,
                        },
                    ]
                ),
            )
            assert seq.returncode == 0, seq.stdout + seq.stderr

        # The lift observable is the MONOTONIC per-episode `enemy_suspended`
        # record the Enemy emits when a suspension episode ends, carrying the
        # episode's peak clamped displacement from the real integration — a
        # positional snapshot of the transient suspension would race the
        # field_duration window against CLI latency (#406). The lift direction
        # and the clamp math stay pinned headless in the logic seam
        # (GravitySystem).
        min_rise = 0.5 * min(enemy_clamp, gravity["field_radius"])
        suspended_before = len(records("enemy_suspended"))

        def enemy_lifted() -> bool:
            episodes = records("enemy_suspended")[suspended_before:]
            return any(-r["fields"]["peak_offset_y"] >= min_rise for r in episodes)

        def lift_evidence() -> str:
            """One-shot scene forensics for the failure message (lazy: assert msg)."""
            try:
                return (
                    f"min_rise={min_rise} "
                    f"fires={[r['fields'] for r in records('gravity_fired')]} "
                    f"episodes={[r['fields'] for r in records('enemy_suspended')]} "
                    f"player_hits={len(records('player_hit'))} "
                    f"player_died={bool(records('player_died'))} "
                    f"player={node_position('/root/Main/Gameplay/Player')} "
                    f"enemy={node_position('/root/Main/Gameplay/Enemy')}"
                )
            except Exception as exc:  # forensics must not mask the assertion
                return f"evidence collection failed: {exc!r}"

        # The pre-read gap can be stale by one chase step, so allow a couple
        # of re-aimed shots; each spends one mp_cost and the MP ledger below
        # is count-agnostic.
        lifted = False
        for _ in range(3):
            suspension_shot()
            if poll(enemy_lifted, timeout=8.0):
                lifted = True
                break
        assert lifted, (
            "the in-range Enemy should be lifted by the Gravity Field "
            "(no enemy_suspended episode with peak rise >= min_rise): "
            + lift_evidence()
        )

        # Every fire so far spent exactly one mp_cost from the S2 StatsSystem,
        # however many shots the lift needed.
        for i, r in enumerate(records("gravity_fired")):
            assert r["fields"]["mp_after"] == pytest.approx(mp_max - (i + 1) * mp_cost)

        # --- Drain the MP budget: every remaining full-cost fire succeeds...
        fires_so_far = len(records("gravity_fired"))
        n_more = int((mp_max - fires_so_far * mp_cost) // mp_cost)
        leftover = mp_max - (fires_so_far + n_more) * mp_cost  # < mp_cost by def
        for _ in range(n_more):
            tap("fire")
        total_fires = fires_so_far + n_more
        assert poll(lambda: len(records("gravity_fired")) >= total_fires), (
            f"expected {total_fires} gravity fires before the budget runs dry"
        )
        fired = records("gravity_fired")
        assert len(fired) == total_fires
        assert fired[-1]["fields"]["mp_after"] == pytest.approx(leftover)

        # ...and the next fire is REFUSED: blocked record, no new field, MP intact.
        tap("fire")
        blocked = poll(lambda: records("gravity_blocked"))
        assert blocked, "at insufficient MP the Gravity Gun must refuse to fire"
        assert blocked[-1]["fields"]["mp"] == pytest.approx(leftover)
        assert blocked[-1]["fields"]["mp_cost"] == pytest.approx(mp_cost)
        assert len(records("gravity_fired")) == total_fires, (
            "a refused fire must not spawn a field"
        )

        # --- With no Wine held, drink_wine is REFUSED (the S7 supply gate,
        # gADR-0008): nothing restored, the budget stays drained, and the
        # Gravity Gun stays blocked. The restore/re-arm half lives in
        # test_items_e2e.py, where the supply exists.
        tap("drink_wine")
        wine_blocked = poll(
            lambda: [
                r
                for r in records("consumable_blocked")
                if r["fields"]["item"] == "wine"
            ]
        )
        assert wine_blocked, "no gda_log 'consumable_blocked' record for wine"
        assert wine_blocked[-1]["fields"]["count"] == 0
        assert not records("wine_drunk"), "a refused drink must not restore MP"
        tap("fire")
        assert poll(lambda: len(records("gravity_blocked")) >= 2), (
            "with the budget still drained the Gravity Gun must stay blocked"
        )
        assert len(records("gravity_fired")) == total_fires, (
            "a refused drink must not re-arm the Gravity Gun"
        )

        # --- Switch back: `fire` drives the Laser Gun again (the toggle
        # round-trips; existing combat flows stay reachable).
        tap("switch_weapon")
        assert poll(
            lambda: (
                records("weapon_switched")
                and records("weapon_switched")[-1]["fields"]["weapon"] == "laser_gun"
            )
        ), "switching back should re-arm the Laser Gun"
        tap("fire")
        assert poll(lambda: len(records("laser_fired")) >= 2), (
            "after switching back, fire should spawn a Laser bolt again"
        )
    finally:
        run("daemon", "stop")
