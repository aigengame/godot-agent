"""Integration seam (c) for S4 enemy taxonomy + Archetype AI — THE gate.

The live Archetype behaviors through the gda CLI against a running Engine
session, one scenario per archetype:

- **Melee closes distance and damages the Player**: a roster override spawns
  the melee kind hot (aggro across the whole platform); it walks from its spawn
  to point-blank range (``gda game get`` positions strictly closing), then
  ``gda logger tail`` returns ``enemy_attack {archetype: melee}`` and
  ``player_hit`` records whose damage matches the AUTHORITATIVE JSON through
  the SAME symmetric formula (roles swapped — gADR-0001's S4 payoff).
- **Ranged keeps distance and damages from afar**: the ranged kind holds its
  Steering Band (never approaching inside it), its bolts cross the level into
  the Player (``enemy_attack {archetype: ranged}`` + ``player_hit`` at
  standoff distance), and when the Player pushes inside the band the enemy
  BACKS OFF until the distance is restored.

Both scenarios tune via DATA: the throwaway project copy's
``enemies_config.json`` is rewritten (kind params + a single-wave schedule,
gADR-0005) before the config build — the shipped default schedule stays
conservative so the S1/S2 flows are untouched. Since S5 retuned the shipped
Elite to its compact Wave-2 profile, the ranged scenario sets its hot
long-range numbers here explicitly (the same move the melee scenario always
made). Per RULES.md, mocks cannot replace this end-to-end proof.

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


def _make_project_copy(dst: Path, mutate_enemies) -> Path:
    """Copy the game, rewrite its enemies config via ``mutate_enemies``, build.

    ``mutate_enemies(config: dict) -> dict`` edits kind params / the Spawn
    Roster — the data-driven tuning knob (kind NAMES stay fixed: the SPECS
    table keys per-kind outputs by name). The mutated JSON still passes the
    schema because build_all validates it.
    """
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    enemies_path = dst / "data" / "json" / "enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    enemies_path.write_text(
        json.dumps(mutate_enemies(config), indent=2) + "\n", encoding="utf-8"
    )
    build_config.build_all(root=dst)
    return dst


def _expected_player_damage(kind: dict, combat: dict, player_stats: dict) -> float:
    """The data-driven formula with the roles swapped: enemy kind -> Player.

    The Player defends with the SPACESUIT-composed block since S7
    (gADR-0008): base defense + the items config's suit bonus.
    """
    items = build_config.load_json(GAME_DIR / "data" / "json" / "items_config.json")
    return max(
        combat["min_damage"],
        kind["attack"] * combat["attack_scale"]
        - (player_stats["defense"] + items["spacesuit_defense"])
        * combat["defense_scale"],
    )


class _Session:
    """A tiny per-scenario harness over the gda CLI (the S1/S2 e2e idioms)."""

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

    def position(self, node: str) -> list[float]:
        got = self.run("game", "get", node, "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == "position":
                return p["value"]
        raise AssertionError("position not returned")

    def distance(self) -> float:
        player = self.position("/root/Main/Player")
        enemy = self.position("/root/Main/Enemy")
        return math.dist(player, enemy)

    def wait_player_landed(self, rest_y: float) -> None:
        assert self.poll(
            lambda: abs(self.position("/root/Main/Player")[1] - rest_y) <= 2.0
        ), "Player did not land"

    def launch(self) -> None:
        """Launch the engine session (the first live op does; `logger tail` is
        a read and will not) and require the roster-spawned Enemy in the tree."""
        tree = self.run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr

        def find(node: dict) -> bool:
            return node.get("name") == "Enemy" or any(
                find(c) for c in node.get("children", [])
            )

        assert find(json.loads(tree.stdout)["root"]), tree.stdout


def _rest_y(player_cfg: dict, rampart: dict) -> float:
    return (
        rampart["position"][1]
        - rampart["size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )


def _rampart() -> dict:
    """The main fight platform from the authoritative level config."""
    level_cfg = build_config.load_json(GAME_DIR / "data" / "json" / "level_config.json")
    return next(p for p in level_cfg["platforms"] if p["name"] == "Rampart")


@pytest.mark.e2e
def test_melee_enemy_closes_distance_and_damages_player(tmp_path, daemon_runtime_dir):
    """The Melee archetype live: aggro -> walk to point-blank -> contact damage."""

    def hot_melee(config: dict) -> dict:
        kind = config["kinds"]["monster_minion_melee"]
        # Aggro across the whole platform so the approach starts immediately,
        # but walk SLOWLY: session launch + the first CLI polls take seconds,
        # and the closing-distance observation below needs the approach still
        # in progress when the first gap sample lands. Data, not code.
        kind["aggro_range"] = 600.0
        kind["move_speed"] = 80.0
        kind["attack_cooldown"] = 1.0
        config["waves"] = [
            {
                "spawns": [
                    {
                        "kind": "monster_minion_melee",
                        "name": "Enemy",
                        "position": [640.0, 452.0],
                    }
                ]
            }
        ]
        return config

    project = _make_project_copy(tmp_path / "game", hot_melee)
    # Every expectation derives from the copy's AUTHORITATIVE JSON.
    enemies = json.loads(
        (project / "data" / "json" / "enemies_config.json").read_text(encoding="utf-8")
    )
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    rampart = _rampart()
    kind = enemies["kinds"]["monster_minion_melee"]
    damage = _expected_player_damage(kind, combat, combat["player_stats"])
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        # The spawned enemy boots as its data-driven kind.
        ready = s.poll(lambda: s.records("enemy_ready"))
        assert ready, "no gda_log 'enemy_ready' record"
        assert ready[0]["fields"]["archetype"] == "melee"
        assert ready[0]["fields"]["max_hp"] == pytest.approx(kind["max_hp"])
        s.wait_player_landed(_rest_y(player_cfg, rampart))

        # Melee damage is CONTACT damage (gADR-0003): attack_range is pinned
        # inside the Steering Band by the data-seam invariant, so the band's
        # upper edge IS the point-blank boundary this scenario asserts against.
        band = kind["keep_range_max"]
        assert kind["attack_range"] <= band, "melee contact invariant violated"
        # Reachability, from the actual body sizes (both bodies rest centered
        # on the platform top and never collide with each other — the enemy
        # masks terrain only): the only gap the walk cannot close is the
        # VERTICAL offset between the two rest centers, so the band must
        # exceed it or point-blank would be unreachable. Tune data if this
        # trips; never loosen the assertions below.
        dy = abs(
            _rest_y(player_cfg, rampart)
            - (
                rampart["position"][1]
                - rampart["size"][1] / 2.0
                - kind["size"][1] / 2.0
            )
        )
        assert dy < band, f"band {band} unreachable: vertical offset {dy}"
        # The steering decision runs before the move each physics tick, so the
        # enemy can overshoot the band edge by at most one tick of travel —
        # the justified epsilon (the project keeps Godot's default 60 ticks/s).
        step = kind["move_speed"] / 60.0

        # CLOSES DISTANCE: the gap shrinks strictly from the spawn gap down to
        # point-blank (the band edge, +/- one physics step).
        d0 = s.distance()
        assert d0 > band + step, f"scenario broken: spawned at {d0}"
        assert s.poll(lambda: s.distance() < d0 - 50.0), (
            "melee enemy never started closing distance"
        )
        assert s.poll(lambda: s.distance() <= band + step), (
            "melee enemy never reached point-blank range"
        )

        # DAMAGES THE PLAYER at point-blank ONLY: enemy_attack {melee} records
        # and player_hit whose damage is the symmetric formula, roles swapped;
        # hp_left strictly decreases from max_hp. The Player never moves, so
        # the standing gap while hits land must stay within the band edge
        # (+ the same one-tick epsilon) — hits from outside it would regress
        # the contact semantics.
        assert s.poll(lambda: s.records("enemy_attack")), "no enemy_attack record"
        attack = s.records("enemy_attack")[0]
        assert attack["fields"]["archetype"] == "melee"
        assert attack["fields"]["faction"] == kind["faction"]
        assert s.poll(lambda: len(s.records("player_hit")) >= 2), (
            "repeated melee attacks should land repeated player hits"
        )
        assert s.distance() <= band + step, (
            f"hits landed while outside the point-blank band: {s.distance()}"
        )
        hits = s.records("player_hit")
        for hit in hits:
            assert hit["fields"]["damage"] == pytest.approx(damage)
        hp_trace = [h["fields"]["hp_left"] for h in hits]
        assert hp_trace[0] == pytest.approx(combat["player_stats"]["max_hp"] - damage)
        assert all(a > b for a, b in zip(hp_trace, hp_trace[1:])), hp_trace
    finally:
        s.run("daemon", "stop")


@pytest.mark.e2e
def test_ranged_enemy_keeps_distance_and_damages_from_afar(
    tmp_path, daemon_runtime_dir
):
    """The Ranged archetype live: hold the Steering Band, bolt the Player, back off."""

    def ranged_roster(config: dict) -> dict:
        kind = config["kinds"]["robot_elite_ranged"]
        # The HOT long-range scenario profile, explicit since S5 retuned the
        # shipped default to the compact Wave-2 encounter (gADR-0005): aggro
        # across the whole platform, bolts at standoff range, a wide band.
        kind["aggro_range"] = 700.0
        kind["attack_range"] = 520.0
        kind["keep_range_min"] = 220.0
        kind["keep_range_max"] = 380.0
        # Rest the elite on the platform top (bodies are center-origin).
        rampart = _rampart()
        platform_top = rampart["position"][1] - rampart["size"][1] / 2.0
        config["waves"] = [
            {
                "spawns": [
                    {
                        "kind": "robot_elite_ranged",
                        "name": "Enemy",
                        "position": [640.0, platform_top - kind["size"][1] / 2.0],
                    }
                ]
            }
        ]
        return config

    project = _make_project_copy(tmp_path / "game", ranged_roster)
    enemies = json.loads(
        (project / "data" / "json" / "enemies_config.json").read_text(encoding="utf-8")
    )
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    kind = enemies["kinds"]["robot_elite_ranged"]
    damage = _expected_player_damage(kind, combat, combat["player_stats"])
    band_min = kind["keep_range_min"]
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        ready = s.poll(lambda: s.records("enemy_ready"))
        assert ready, "no gda_log 'enemy_ready' record"
        assert ready[0]["fields"]["archetype"] == "ranged"
        s.wait_player_landed(_rest_y(player_cfg, _rampart()))

        # DAMAGES FROM AFAR: bolts land while the enemy stays at standoff
        # distance — every hit arrives with the gap still outside the band's
        # lower edge (small slack for the frames between samples).
        assert s.poll(lambda: s.records("enemy_attack")), "no enemy_attack record"
        assert s.records("enemy_attack")[0]["fields"]["archetype"] == "ranged"
        assert s.poll(lambda: s.records("player_hit")), (
            "no bolt ever reached the Player"
        )
        standoff = s.distance()
        assert standoff >= band_min - 40.0, (
            f"ranged enemy should hold its band, got distance {standoff}"
        )
        hit = s.records("player_hit")[0]
        assert hit["fields"]["damage"] == pytest.approx(damage)

        # KEEPS DISTANCE: push the Player inside the band; the enemy backs off
        # until the standoff is restored (never pinned at point-blank). The
        # press is long (observed ~2px per sequence frame live): the Player
        # must cross the band's lower edge decisively; the enemy retreats
        # concurrently, so the gap never actually collapses.
        enemy_x0 = s.position("/root/Main/Enemy")[0]
        events = [
            {"type": "action", "action": "move_right", "frame": 0},
            {"type": "action", "action": "move_right", "release": True, "frame": 150},
        ]
        seq = s.run("input", "sequence", "--events", json.dumps(events))
        assert seq.returncode == 0, seq.stdout + seq.stderr
        assert s.poll(lambda: s.position("/root/Main/Enemy")[0] > enemy_x0 + 30.0), (
            "crowded ranged enemy never backed off"
        )
        assert s.poll(lambda: s.distance() >= band_min - 40.0), (
            f"ranged enemy never restored its standoff: {s.distance()}"
        )
    finally:
        s.run("daemon", "stop")
