"""Integration seam (c) for S9 level integration + the End-state loop — THE gate.

The full demo arc live through the gda CLI against a running Engine session
(gADR-0010):

- **The full playthrough wins and retries**: a throwaway copy keeps the
  SHIPPED Wave schedule VERBATIM — every spawn of every wave at its shipped
  position (the mixed Wave-3 swarm included) and the Boss slot's Tank Boss
  with its presence-gated Warp block INTACT — and retunes only per-kind
  stats for determinism (1 max_hp, zero move speed, tiny aggro — the
  waves-e2e dormancy precedent; the Warp gate itself requires aggro,
  WarpSystem.should_warp, so the dormant Boss never blinks and the shipped
  data still rides the arc). Spaced Laser shots drain Wave 1 → the Boss;
  the monotonic records must walk ``wave_started``/``wave_cleared`` 1..4
  with each wave's SHIPPED spawn count, every shipped spawn must die, then
  ``all_waves_cleared`` → ``game_won`` → ``end_screen_shown``; the World
  freeze must disable the Player's processing WITHOUT severing the live
  channel (this test keeps reading state through it — the gADR-0010
  no-tree-pause argument, proven by construction); and the ``retry`` action
  must reload into a fresh run (second boot records, Wave 1 restarted,
  End screen hidden again). Retry mid-run must do nothing.
- **The lose path ends and retries the same way**: a one-hit-killer melee
  minion spawned point-blank fells the Player — ``player_died`` →
  ``game_lost`` → ``end_screen_shown`` → frozen world — and ``retry``
  boots the fresh run.

Every expectation derives from the AUTHORITATIVE JSON configs, never
hardcoded. End-state flow is asserted from the monotonic ``gda logger tail``
records, not position polls (the #406 lesson); all injected input rides the
physics clock. Per RULES.md, mocks cannot replace this end-to-end proof.

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

# Node.PROCESS_MODE_DISABLED — what the World freeze sets on gameplay children
# (gADR-0010); Node.PROCESS_MODE_INHERIT (0) is the fresh-scene default.
_PROCESS_MODE_DISABLED = 4
_PROCESS_MODE_INHERIT = 0


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

    def property_of(self, node: str, prop: str):
        got = self.run("game", "get", node, "--property", prop)
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == prop:
                return p["value"]
        raise AssertionError(f"{prop} not returned for {node}")

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


def _drain_schedule(s: _Session, iframe: float, spawn_counts: list[int]) -> None:
    """The waves-e2e kill loop: spaced Laser taps clear wave after wave.

    ``spawn_counts`` is each wave's SHIPPED spawn count: a bolt despawns on
    its first kill, so a wave takes at least one tap per spawn — the retry
    budget scales with the wave's composition.
    """
    for n, spawns in enumerate(spawn_counts, start=1):
        for _ in range(4 + 4 * spawns):
            if len(s.records("wave_cleared")) >= n:
                break
            s.tap("fire")
            s.poll(lambda: len(s.records("wave_cleared")) >= n, timeout=3.0)
            time.sleep(iframe / 2.0)
        cleared = s.records("wave_cleared")
        assert len(cleared) >= n, f"wave {n} never cleared: {cleared}"


@pytest.mark.e2e
def test_full_playthrough_wins_freezes_and_retries(tmp_path, daemon_runtime_dir):
    """Wave 1 → Boss-defeated → game_won → End screen → retry → fresh run.

    The copy keeps the SHIPPED Wave schedule VERBATIM — every spawn of every
    wave at its shipped position (the mixed melee+ranged Wave-3 swarm
    included) and the Boss with its presence-gated Warp block intact — and
    retunes ONLY per-kind stats: 1 max_hp (a one-shot kill; min_damage
    floors every bolt through any defense), zero move speed, and tiny aggro
    (the waves-e2e dormancy precedent). Dormancy also parks the Warp:
    WarpSystem.should_warp gates on the Aggro Range, so the Boss never
    blinks while its shipped Warp data rides the whole arc. Determinism by
    data: nothing moves or attacks, every shipped spawn dies to a spaced
    Laser tap from the resting Player, and the arc's whole life is readable
    from the monotonic records.
    """

    def reconfigure(config: dict) -> dict:
        for kind in config["kinds"].values():
            kind["max_hp"] = 1.0
            kind["move_speed"] = 0.0
            kind["aggro_range"] = 60.0
        return config

    project = _make_project_copy(tmp_path / "game", reconfigure)
    enemies = build_config.load_composed("data/json/enemies_config.json")
    combat = build_config.load_composed("data/json/combat_config.json")
    waves = enemies["waves"]
    wave_count = len(waves)
    spawn_counts = [len(wave["spawns"]) for wave in waves]
    boss_kind = waves[-1]["spawns"][0]["kind"]
    assert enemies["kinds"][boss_kind]["tier"] == "boss", (
        "scenario broken: the shipped schedule must end on the Boss slot"
    )
    assert "warp_cooldown" in enemies["kinds"][boss_kind], (
        "scenario broken: the shipped Boss must carry its Warp block — this "
        "gate proves the arc with the shipped data intact"
    )
    iframe = combat["iframe_duration"]
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        # Boot: the level and Wave 1 are up with its SHIPPED composition; the
        # End screen exists but hides.
        first = s.poll(lambda: s.records("wave_started"))
        assert first, "no gda_log 'wave_started' record"
        assert first[0]["fields"] == {
            "wave": 1,
            "total": wave_count,
            "spawns": spawn_counts[0],
        }
        level_ready = s.records("level_ready")
        assert level_ready, "no gda_log 'level_ready' record"
        assert s.property_of("/root/Main/EndScreen", "visible") is False

        # Retry mid-run must do nothing (can_retry gates on an End state).
        s.tap("retry")
        time.sleep(0.5)
        assert not s.records("game_retried"), "retry must be dead mid-run"
        assert not s.records("boot")[1:], "retry mid-run must not reload the scene"

        # Drain the arc: Wave 1 → the Boss, every SHIPPED spawn a one-shot
        # kill (one bolt per spawn — a bolt despawns on its first hit).
        _drain_schedule(s, iframe, spawn_counts)

        # The whole SHIPPED schedule walked 1..N in order, each wave with its
        # shipped composition, and every shipped spawn died.
        started_fields = [r["fields"] for r in s.records("wave_started")]
        assert [f["wave"] for f in started_fields] == list(range(1, wave_count + 1))
        assert [f["spawns"] for f in started_fields] == spawn_counts
        assert len(s.records("enemy_died")) == sum(spawn_counts)

        # The finale: the Boss's death ends the schedule AND the run — the
        # verdict + End screen records land, exactly once each.
        assert s.poll(lambda: s.records("all_waves_cleared")), "schedule never done"
        boss_ready = s.records("enemy_ready")[-1]["fields"]
        assert boss_ready["tier"] == "boss", "the final wave must be the Boss slot"
        won = s.poll(lambda: s.records("game_won"))
        assert won, "no gda_log 'game_won' record"
        assert len(won) == 1 and won[0]["fields"] == {"waves": wave_count}
        shown = s.poll(lambda: s.records("end_screen_shown"))
        assert shown, "no gda_log 'end_screen_shown' record"
        assert len(shown) == 1 and shown[0]["fields"] == {"result": "won"}
        assert not s.records("game_lost"), "a won run must not also lose"

        # The World freeze (gADR-0010): gameplay children disabled, the End
        # screen visible — and every one of these reads runs over the LIVE
        # channel a tree pause would have severed (the no-tree-pause proof).
        assert s.poll(
            lambda: (
                s.property_of("/root/Main/Player", "process_mode")
                == _PROCESS_MODE_DISABLED
            )
        ), "the World freeze never disabled the Player"
        assert s.property_of("/root/Main/EndScreen", "visible") is True

        # Retry: one tap reloads the scene — a FRESH run re-derived from
        # config (second boot/level_ready/player_ready, Wave 1 restarted,
        # End screen hidden, the Player processing again).
        s.tap("retry")
        retried = s.poll(lambda: s.records("game_retried"))
        assert retried, "no gda_log 'game_retried' record"
        assert retried[0]["fields"] == {"from_state": "won"}
        assert s.poll(lambda: len(s.records("boot")) == 2), "no fresh boot"
        assert s.poll(lambda: len(s.records("level_ready")) == 2)
        assert s.poll(lambda: len(s.records("player_ready")) == 2)
        assert s.poll(lambda: s.records("wave_started")[-1]["fields"]["wave"] == 1), (
            "the fresh run never restarted Wave 1"
        )
        assert s.poll(
            lambda: (
                s.property_of("/root/Main/Player", "process_mode")
                == _PROCESS_MODE_INHERIT
            )
        ), "the fresh run's Player must process again"
        assert s.property_of("/root/Main/EndScreen", "visible") is False
    finally:
        s.run("daemon", "stop")


@pytest.mark.e2e
def test_losing_run_freezes_and_retries(tmp_path, daemon_runtime_dir):
    """HP = 0 → game_lost → End screen → frozen world → retry → fresh run.

    The copy's single wave is one melee minion tuned into a stationary
    one-hit killer spawned point-blank under the falling Player (huge attack,
    quick cooldown, zero move speed): the first contact fells the Player, so
    the lose path needs no choreography at all.
    """

    def reconfigure(config: dict) -> dict:
        kind = config["kinds"]["monster_minion_melee"]
        kind["attack"] = 999.0
        kind["attack_cooldown"] = 0.5
        kind["move_speed"] = 0.0
        config["waves"] = [
            {
                "spawns": [
                    {
                        "kind": "monster_minion_melee",
                        "name": "Killer",
                        # Point-blank under the Player's spawn drop.
                        "position": [210.0, 452.0],
                    }
                ]
            }
        ]
        return config

    project = _make_project_copy(tmp_path / "game", reconfigure)
    s = _Session(project)

    try:
        started = s.run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        s.launch()

        # The Killer fells the Player: the S4 death latch, then the S9 lose
        # edge — player_died → game_lost (with the wave it happened on) →
        # end_screen_shown, exactly once each.
        assert s.poll(lambda: s.records("player_died")), "the Player never died"
        lost = s.poll(lambda: s.records("game_lost"))
        assert lost, "no gda_log 'game_lost' record"
        assert len(lost) == 1 and lost[0]["fields"] == {"wave": 1}
        shown = s.poll(lambda: s.records("end_screen_shown"))
        assert shown, "no gda_log 'end_screen_shown' record"
        assert len(shown) == 1 and shown[0]["fields"] == {"result": "lost"}
        assert not s.records("game_won"), "a lost run must not also win"

        # The World freeze holds the tableau: the dead Player AND its Killer
        # are disabled (no further enemy_attack lands), read over the live
        # channel (the gADR-0010 no-tree-pause proof again).
        assert s.poll(
            lambda: (
                s.property_of("/root/Main/Player", "process_mode")
                == _PROCESS_MODE_DISABLED
            )
        ), "the World freeze never disabled the Player"
        assert (
            s.property_of("/root/Main/Killer", "process_mode") == _PROCESS_MODE_DISABLED
        ), "the World freeze never disabled the Killer"
        attacks_frozen = len(s.records("enemy_attack"))
        time.sleep(1.5)
        assert len(s.records("enemy_attack")) == attacks_frozen, (
            "the frozen Killer kept attacking"
        )

        # Retry from the loss: the one-more-try loop (GDD) — a fresh run,
        # which this scenario's point-blank Killer promptly fells AGAIN: the
        # second game_lost proves the loop repeats (retry -> fresh run ->
        # fresh End state), so no EndScreen-hidden window is polled for.
        s.tap("retry")
        retried = s.poll(lambda: s.records("game_retried"))
        assert retried, "no gda_log 'game_retried' record"
        assert retried[0]["fields"] == {"from_state": "lost"}
        assert s.poll(lambda: len(s.records("player_ready")) == 2), "no fresh run"
        assert s.poll(
            lambda: [f["fields"]["wave"] for f in s.records("wave_started")] == [1, 1]
        ), "the fresh run never restarted Wave 1"
        assert s.poll(lambda: len(s.records("game_lost")) == 2), (
            "the fresh run never re-lost — the one-more-try loop broke"
        )
    finally:
        s.run("daemon", "stop")
