"""Integration seam (c) for the S5 Wave spawn system (gADR-0005) — THE gate.

The live Wave schedule through the gda CLI against a running Engine session:

- **Non-default wave counts play through end to end** (parametrized at 3 AND
  5 — the issue-#334 no-hardcoded-count proof at the live tier): a throwaway
  copy reconfigures ``waves`` to N one-minion waves on the S2-proven shooting
  lane (dormant, one-shot-kill — pure data tuning), then spaced Laser shots
  drain the schedule; the monotonic ``wave_started`` / ``wave_cleared`` /
  ``all_waves_cleared`` records must walk 1..N in order and the next wave's
  named spawn must materialize in the runtime tree after each clear.
- **The SHIPPED default config plays the demo arc's first advance**: boot
  spawns Wave 1 ONLY (the legacy dormant minion; no ``EliteRobot`` yet), the
  reward-flow kill choreography clears it, and Wave 2's ranged Elite spawns
  — visible in the tree with its data-driven kind — while staying DORMANT
  (the gADR-0005 by-data compatibility contract: aggro short of the gap, so
  the pre-S5 flows keep their post-kill assertions).

Every expectation derives from the AUTHORITATIVE JSON configs, never
hardcoded. Wave state is asserted from the monotonic ``gda logger tail``
records, not position polls (the #406 lesson); all injected input rides the
physics clock. Per RULES.md, mocks cannot replace this end-to-end proof.

Isolation: same throwaway-copy pattern as ``test_player_e2e`` (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX); headless.
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

# The S2-proven shooting lane: the legacy default spawn position, reachable by
# a straight Laser bolt from the resting Player at player_start.
_LANE = [640.0, 452.0]


def _make_project_copy(dst: Path, mutate_enemies=None) -> Path:
    """Copy the game, optionally rewrite its enemies config, build the config."""
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    if mutate_enemies is not None:
        enemies_path = dst / "data" / "json" / "enemies_config.json"
        config = json.loads(enemies_path.read_text(encoding="utf-8"))
        enemies_path.write_text(
            json.dumps(mutate_enemies(config), indent=2) + "\n", encoding="utf-8"
        )
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
        """Launch the engine session: the first LIVE op does (``logger tail``
        is a read and will not) — the S4 e2e idiom."""
        self.tree_root()

    def tree_root(self) -> dict:
        tree = self.run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        return json.loads(tree.stdout)["root"]

    def node_in_tree(self, name: str) -> dict | None:
        return _find_node(self.tree_root(), name)

    def position(self, node: str) -> list[float]:
        got = self.run("game", "get", node, "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == "position":
                return p["value"]
        raise AssertionError("position not returned")

    def tap(self, action: str) -> None:
        """One press+release of an InputMap action on the physics clock (#406)."""
        seq = self.run(
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

    def wait_player_landed(self, rest_y: float) -> None:
        assert self.poll(
            lambda: abs(self.position("/root/Main/Player")[1] - rest_y) <= 2.0
        ), "Player did not land"


def _rest_y(player_cfg: dict) -> float:
    return (
        player_cfg["platform_position"][1]
        - player_cfg["platform_size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )


def _wave_fields(records: list[dict]) -> list[dict]:
    return [r["fields"] for r in records]


@pytest.mark.e2e
@pytest.mark.parametrize("wave_count", [3, 5])
def test_reconfigured_wave_count_plays_through(
    tmp_path, daemon_runtime_dir, wave_count: int
):
    """A 3-/5-wave schedule (JSON-only reconfig) advances on clear to the end.

    The copy's waves are N single-minion waves on the shooting lane, each
    dormant (tiny aggro, zero move speed) and one-shot-killable (1 max_hp) —
    determinism by data: no enemy ever moves or attacks, every Laser tap
    kills exactly the one live target, and the schedule's whole life is
    readable from the monotonic wave records.
    """

    def reconfigure(config: dict) -> dict:
        kind = config["kinds"]["monster_minion_melee"]
        kind["max_hp"] = 1.0
        kind["move_speed"] = 0.0
        kind["aggro_range"] = 60.0
        config["waves"] = [
            {
                "spawns": [
                    {
                        "kind": "monster_minion_melee",
                        "name": f"W{n}Target",
                        "position": _LANE,
                    }
                ]
            }
            for n in range(1, wave_count + 1)
        ]
        return config

    project = _make_project_copy(tmp_path / "game", reconfigure)
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    iframe = combat["iframe_duration"]
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        # Boot: wave 1 of N is live, its target in the tree, later ones not.
        first = s.poll(lambda: s.records("wave_started"))
        assert first, "no gda_log 'wave_started' record"
        assert first[0]["fields"] == {"wave": 1, "total": wave_count, "spawns": 1}
        assert s.node_in_tree("W1Target") is not None
        assert s.node_in_tree("W2Target") is None
        s.wait_player_landed(_rest_y(player_cfg))

        # Drain the schedule: spaced shots (the S2 kill loop) clear wave after
        # wave; after each clear the NEXT wave's named target materializes.
        for n in range(1, wave_count + 1):
            for _ in range(6):
                if len(s.records("wave_cleared")) >= n:
                    break
                s.tap("fire")
                s.poll(lambda: len(s.records("wave_cleared")) >= n, timeout=3.0)
                time.sleep(iframe / 2.0)
            cleared = s.records("wave_cleared")
            assert len(cleared) >= n, f"wave {n} never cleared: {cleared}"
            if n < wave_count:
                assert s.poll(lambda: s.records("wave_started")[-1]["fields"]["wave"] == n + 1), (
                    f"wave {n + 1} never started"
                )
                assert s.poll(lambda: s.node_in_tree(f"W{n + 1}Target") is not None), (
                    f"wave {n + 1}'s target never spawned"
                )

        # The whole schedule walked 1..N in order, each wave once, and the
        # final clear reported the schedule done with the DATA's count.
        started_fields = _wave_fields(s.records("wave_started"))
        assert [f["wave"] for f in started_fields] == list(range(1, wave_count + 1))
        assert {f["total"] for f in started_fields} == {wave_count}
        cleared_fields = _wave_fields(s.records("wave_cleared"))
        assert [f["wave"] for f in cleared_fields] == list(range(1, wave_count + 1))
        done = s.records("all_waves_cleared")
        assert len(done) == 1, f"all_waves_cleared must fire exactly once: {done}"
        assert done[0]["fields"]["total"] == wave_count
        assert len(s.records("enemy_died")) == wave_count
    finally:
        s.run("daemon", "stop")


@pytest.mark.e2e
def test_default_schedule_advances_to_the_dormant_elite(tmp_path, daemon_runtime_dir):
    """The SHIPPED demo config: Wave 1 boots alone; clearing it wakes Wave 2.

    Kill choreography and every expectation derive from the authoritative
    JSON (the S6a reward-flow idioms): walk into the minion's Aggro Range,
    spaced Laser shots past the i-frame window, then the wave records and the
    runtime tree carry the advance. Wave 2's Elite must arrive DORMANT — its
    compact profile (gADR-0005) keeps the legacy kill positions outside its
    Aggro Range, which this gate proves live (no ranged attack, no motion).
    """
    project = _make_project_copy(tmp_path / "game")
    enemies = build_config.load_json(GAME_DIR / "data" / "json" / "enemies_config.json")
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    waves = enemies["waves"]
    wave_one = waves[0]["spawns"][0]
    minion = enemies["kinds"][wave_one["kind"]]
    elite_spawn = waves[1]["spawns"][0]
    elite = enemies["kinds"][elite_spawn["kind"]]
    player_stats = combat["player_stats"]
    laser_damage = max(
        combat["min_damage"],
        player_stats["attack"] * combat["attack_scale"]
        - minion["defense"] * combat["defense_scale"],
    )
    shots_to_kill = math.ceil(minion["max_hp"] / laser_damage)
    iframe = combat["iframe_duration"]
    rest_y = _rest_y(player_cfg)
    start_x = player_cfg["player_start"][0]
    # The reward-flow walk target: just inside the minion's Aggro Range, on
    # the physics clock (move_speed / 60 px per held tick).
    target_x = wave_one["position"][0] - minion["aggro_range"] + 40.0
    hold_ticks = round((target_x - start_x) / (player_cfg["move_speed"] / 60.0))
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        # Boot: the schedule opens on Wave 1 of the DATA's four — the legacy
        # minion alone; no later-wave spawn exists yet.
        first = s.poll(lambda: s.records("wave_started"))
        assert first, "no gda_log 'wave_started' record"
        assert first[0]["fields"] == {
            "wave": 1,
            "total": len(waves),
            "spawns": len(waves[0]["spawns"]),
        }
        assert s.node_in_tree(wave_one["name"]) is not None
        assert s.node_in_tree(elite_spawn["name"]) is None
        ready = s.poll(lambda: s.records("enemy_ready"))
        assert ready and ready[0]["fields"]["archetype"] == minion["archetype"]
        s.wait_player_landed(rest_y)

        # Clear Wave 1: walk into the Aggro Range, then spaced shots kill the
        # closing minion (contact hits on the way are the S6a-proven flow).
        walk = s.run(
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
                        "physics_frame": hold_ticks,
                    },
                ]
            ),
        )
        assert walk.returncode == 0, walk.stdout + walk.stderr
        for _ in range(shots_to_kill * 2):
            if s.records("enemy_died"):
                break
            time.sleep(iframe + 0.3)
            s.tap("fire")
            s.poll(lambda: bool(s.records("enemy_died")), timeout=3.0)
        assert s.poll(lambda: s.records("enemy_died")), "the Wave-1 minion never died"

        # The advance: Wave 1 cleared, Wave 2 started with ITS composition.
        assert s.poll(lambda: s.records("wave_cleared")), "no wave_cleared record"
        assert s.records("wave_cleared")[0]["fields"] == {"wave": 1}
        assert s.poll(lambda: len(s.records("wave_started")) >= 2), (
            "wave 2 never started"
        )
        second = s.records("wave_started")[1]["fields"]
        assert second == {
            "wave": 2,
            "total": len(waves),
            "spawns": len(waves[1]["spawns"]),
        }
        assert s.poll(lambda: s.node_in_tree(elite_spawn["name"]) is not None), (
            "Wave 2's Elite never entered the runtime tree"
        )
        elite_ready = s.records("enemy_ready")[-1]["fields"]
        assert elite_ready["archetype"] == elite["archetype"]
        assert elite_ready["tier"] == elite["tier"]
        assert elite_ready["x"] == pytest.approx(elite_spawn["position"][0])
        assert not s.records("all_waves_cleared"), (
            "the schedule must not be done after one of four waves"
        )

        # DORMANT by data (gADR-0005): the Player rests outside the Elite's
        # Aggro Range, so it neither attacks nor moves — no ranged
        # enemy_attack record appears, and its position holds across a beat.
        gap = math.dist(
            s.position("/root/Main/Player"),
            s.position(f"/root/Main/{elite_spawn['name']}"),
        )
        assert gap > elite["aggro_range"], (
            f"scenario broken: the Player ended inside the Elite's aggro ({gap})"
        )
        before = s.position(f"/root/Main/{elite_spawn['name']}")
        time.sleep(1.5)
        after = s.position(f"/root/Main/{elite_spawn['name']}")
        assert after == pytest.approx(before, abs=1.0), (
            f"the dormant Elite moved: {before} -> {after}"
        )
        ranged_attacks = [
            r
            for r in s.records("enemy_attack")
            if r["fields"]["archetype"] == elite["archetype"]
        ]
        assert not ranged_attacks, f"the dormant Elite attacked: {ranged_attacks}"
    finally:
        s.run("daemon", "stop")
