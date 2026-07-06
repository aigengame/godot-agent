"""Integration seam (c) for S7 Consumable use + Spacesuit Equipment — THE gate.

The full S7 loop through the gda CLI against a running Engine session
(gADR-0008), on a DETERMINISTIC single-wave project copy:

- boot: the Spacesuit is worn from spawn — ``spacesuit_equipped`` carries the
  config bonus and the composed total; the HUD column carries the S7 BUN/WINE
  lines at their zero supply;
- supply gating: with nothing held, ``eat_bun``/``drink_wine`` are REFUSED
  (``consumable_blocked``, nothing restored, readouts unchanged) — the use
  verbs consume the S6b item-count hook, never thin air;
- mitigation: the aggroed minion's contact damage lands MITIGATED — the
  ``player_hit`` amount is the S2 formula fed the Spacesuit-composed defender
  (base + ``spacesuit_defense``), asserted against the authoritative JSON;
- supply: killing the minion drops its RECONFIGURED table (Bun + Wine, both
  certain — the gADR-0006 chance-retune precedent), collection lands both in
  the hook and the BUN/WINE readouts tick up;
- use: ``eat_bun`` restores HP (capped add over the damage taken above,
  ``bun_eaten`` with before/after + remaining count, the HP readout agrees);
  a Gravity fire spends MP, ``drink_wine`` restores it (``wine_drunk``,
  capped at max) and RE-ARMS the Gravity Gun (the S3 economy loop, now
  supply-gated — one Wine covers at least one fire, a config sanity this
  test pins); the emptied supply refuses again.

Every expectation derives from the AUTHORITATIVE JSON configs (the copy's,
for the reconfigured drops/waves), never hardcoded. Per RULES.md, mocks
cannot replace this end-to-end proof.

Isolation: the throwaway-copy pattern (``daemon start`` mutates
``project.godot``); the copy is reconfigured for determinism by data (the
waves-e2e precedent): ONE wave (no wave-2 Elite to interfere with the
collection walk — the shipped Elite spawns inside aggro of the kill spot)
whose minion drop table is exactly one Bun + one Wine at chance 1.0.
Posix-only (AF_UNIX); fully headless. The windowed visual half (the BUN/WINE
lines actually RENDER) lives in the consolidated Visual-smoke seam
(gADR-0007), ``test_visual_smoke_e2e.py``.
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

_HUD_LABEL = "/root/Main/Hud/Stats/%sLabel"


def _make_project_copy(dst: Path) -> dict:
    """Copy the game, reconfigure it for S7 determinism, build its config.

    Returns the copy's enemies document (the authority the expectations
    derive from). Two data-only edits (the waves-e2e reconfiguration
    precedent): the schedule keeps its first wave for the kill and parks a
    dormant sentinel wave far east behind it (the shipped wave-2 Elite
    spawns within aggro of the kill spot and would interfere with the
    collection walk — and since S9, gADR-0010, clearing the WHOLE schedule
    wins the run and freezes the world, so a bare one-wave schedule would
    freeze the Player before the collection leg); and the minion Tier's
    drop table becomes exactly one Bun + one Wine, both certain (the
    gADR-0006 chance-retune precedent) — the Consumable supply this test
    consumes.
    """
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    enemies_path = dst / "data" / "json" / "enemies_config.json"
    enemies = json.loads(enemies_path.read_text(encoding="utf-8"))
    sentinel_kind = enemies["waves"][0]["spawns"][0]["kind"]
    enemies["waves"] = [
        enemies["waves"][0],
        {
            "spawns": [
                {
                    "kind": sentinel_kind,
                    "name": "EndSentinel",
                    # Far east on the rampart, outside every walk and aggro
                    # radius of this scenario — it exists only to keep the
                    # schedule un-cleared (the run stays `playing`).
                    "position": [1200.0, 452.0],
                }
            ]
        },
    ]
    minion_tier = enemies["kinds"][enemies["waves"][0]["spawns"][0]["kind"]]["tier"]
    enemies["tiers"][minion_tier]["drops"] = [
        {"item": "bun", "amount": 1, "chance": 1.0},
        {"item": "wine", "amount": 1, "chance": 1.0},
    ]
    enemies_path.write_text(json.dumps(enemies, indent=2) + "\n", encoding="utf-8")
    build_config.build_all(root=dst)
    return enemies


@pytest.mark.e2e
def test_daemon_serves_consumable_use_and_spacesuit(tmp_path, daemon_runtime_dir):
    project = tmp_path / "game"
    enemies = _make_project_copy(project)
    # Every expectation derives from the AUTHORITATIVE JSON (the copy's, for
    # the reconfigured waves/drops), never hardcoded.
    combat = build_config.load_composed("data/json/combat_config.json")
    gravity = build_config.load_composed("data/json/gravity_config.json")
    items = build_config.load_composed("data/json/items_config.json")
    player_cfg = build_config.load_composed("data/json/player_config.json")
    level_cfg = build_config.load_composed("data/json/level_config.json")
    rampart = next(p for p in level_cfg["platforms"] if p["name"] == "Rampart")
    default_spawn = enemies["waves"][0]["spawns"][0]
    kind = enemies["kinds"][default_spawn["kind"]]
    drops = enemies["tiers"][kind["tier"]]["drops"]
    player_stats = combat["player_stats"]
    max_hp = player_stats["max_hp"]
    max_mp = player_stats["max_mp"]
    mp_cost = gravity["mp_cost"]
    bun_restore = items["bun_hp_restore"]
    wine_restore = items["wine_mp_restore"]
    suit_bonus = items["spacesuit_defense"]
    # The symmetric damage formula, enemy->Player: the defender is the
    # SPACESUIT-COMPOSED stat block (base defense + suit bonus, gADR-0008).
    contact_damage = max(
        combat["min_damage"],
        kind["attack"] * combat["attack_scale"]
        - (player_stats["defense"] + suit_bonus) * combat["defense_scale"],
    )
    # The suit must actually mitigate on the shipped numbers, or the
    # mitigation assert below would pass vacuously through the min floor.
    unmitigated = max(
        combat["min_damage"],
        kind["attack"] * combat["attack_scale"]
        - player_stats["defense"] * combat["defense_scale"],
    )
    assert contact_damage < unmitigated, (
        "config sanity: the shipped spacesuit_defense must visibly mitigate "
        "the minion's contact damage"
    )
    laser_damage = max(
        combat["min_damage"],
        player_stats["attack"] * combat["attack_scale"]
        - kind["defense"] * combat["defense_scale"],
    )
    shots_to_kill = math.ceil(kind["max_hp"] / laser_damage)
    iframe = combat["iframe_duration"]
    rest_y = (
        rampart["position"][1]
        - rampart["size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
    start_x = player_cfg["player_start"][0]
    enemy_x = default_spawn["position"][0]
    # The S6a-proven walk target: inside the minion's Aggro Range with margin
    # on both sides; the minion closes the rest (gADR-0003 dynamics).
    target_x = enemy_x - kind["aggro_range"] + 40.0
    ticks_per_px = 1.0 / (player_cfg["move_speed"] / 60.0)
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

    def prop(path: str, name: str):
        got = run("game", "get", path, "--property", name)
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == name:
                return p["value"]
        raise AssertionError(f"{name} not returned for {path}")

    def label(key: str) -> str:
        return prop(_HUD_LABEL % key, "text")

    def tap(action: str) -> None:
        seq = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": action, "frame": 0},
                    {"type": "action", "action": action, "release": True, "frame": 4},
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    def walk_right(px: float) -> None:
        """Hold move_right for the physics ticks that cover ``px`` pixels."""
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
                        "physics_frame": max(round(px * ticks_per_px), 1),
                    },
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # The first live op launches the Engine session; the tree also proves
        # the S7 BUN/WINE lines are instanced in the HUD column.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        assert '"BunLabel"' in tree.stdout, tree.stdout
        assert '"WineLabel"' in tree.stdout, tree.stdout

        # --- Boot: the Spacesuit is worn from spawn (persistent Equipment) —
        # the module-entry record carries the config bonus and the composed
        # total (base defense + bonus, gADR-0008).
        equipped = poll(lambda: records("spacesuit_equipped"))
        assert equipped, "no gda_log 'spacesuit_equipped' record"
        assert len(equipped) == 1, f"the suit is worn exactly once: {equipped}"
        assert equipped[0]["fields"]["defense_bonus"] == pytest.approx(suit_bonus)
        assert equipped[0]["fields"]["defense_total"] == pytest.approx(
            player_stats["defense"] + suit_bonus
        )

        # The HUD boots with the S7 supply lines at zero.
        ready = poll(lambda: records("hud_ready"))
        assert ready, "no gda_log 'hud_ready' record"
        assert ready[0]["fields"]["bun"] == 0
        assert ready[0]["fields"]["wine"] == 0
        assert label("Bun") == "BUN 0"
        assert label("Wine") == "WINE 0"

        # Let the Player settle on the platform so the walk starts from rest.
        assert poll(
            lambda: abs(prop("/root/Main/Player", "position")[1] - rest_y) <= 2.0
        ), "Player did not land"

        # --- Supply gating: with nothing held, BOTH use verbs refuse — one
        # consumable_blocked each, nothing restored, nothing consumed.
        tap("eat_bun")
        blocked = poll(lambda: records("consumable_blocked"))
        assert blocked, "no gda_log 'consumable_blocked' record for the empty bun"
        assert blocked[-1]["fields"] == {"item": "bun", "count": 0}
        tap("drink_wine")
        assert poll(lambda: len(records("consumable_blocked")) >= 2), (
            "the empty wine must refuse too"
        )
        assert records("consumable_blocked")[-1]["fields"] == {
            "item": "wine",
            "count": 0,
        }
        assert not records("bun_eaten") and not records("wine_drunk"), (
            "a refused use must not restore anything"
        )
        assert label("Hp") == f"HP {round(max_hp)}/{round(max_hp)}"
        assert label("Mp") == f"MP {round(max_mp)}/{round(max_mp)}"

        # --- Mitigation: walk into the minion's Aggro Range (deterministic
        # physics-clock hold), let it close and land contact hits — the
        # player_hit amount is the UNTOUCHED formula fed the suit-composed
        # defender, mitigated by exactly the config bonus.
        walk_right(target_x - start_x)
        player_x = prop("/root/Main/Player", "position")[0]
        assert abs(player_x - target_x) <= 20.0, (
            f"physics-clock walk missed its target: x={player_x}, want ~{target_x}"
        )
        assert poll(lambda: records("player_hit"), timeout=30.0), (
            "the aggroed minion never landed a contact hit"
        )
        assert records("player_hit")[0]["fields"]["damage"] == pytest.approx(
            contact_damage
        ), "the Spacesuit must mitigate the contact damage via the formula"

        # --- The kill drops the reconfigured table: one Bun + one Wine, both
        # certain; walking across the row collects both into the hook and the
        # BUN/WINE readouts tick up.
        for _ in range(shots_to_kill * 2):
            if records("enemy_died"):
                break
            time.sleep(iframe + 0.3)
            tap("fire")
            poll(lambda: bool(records("enemy_died")), timeout=3.0)
        assert poll(lambda: records("enemy_died")), "the Enemy never died"
        spawned = poll(lambda: len(records("pickup_spawned")) == len(drops))
        assert spawned, (
            f"expected {len(drops)} pickup_spawned records, "
            f"got {records('pickup_spawned')}"
        )
        xs = [r["fields"]["x"] for r in records("pickup_spawned")]
        player_x = prop("/root/Main/Player", "position")[0]
        walk_right(max(xs) - player_x + 30.0)
        collected = poll(lambda: len(records("item_collected")) == len(drops))
        assert collected, (
            f"expected {len(drops)} item_collected records, "
            f"got {records('item_collected')}"
        )
        assert {r["fields"]["item"] for r in records("item_collected")} == {
            "bun",
            "wine",
        }
        assert poll(lambda: label("Bun") == "BUN 1"), (
            f"BUN readout never showed the supply: {label('Bun')}"
        )
        assert poll(lambda: label("Wine") == "WINE 1"), (
            f"WINE readout never showed the supply: {label('Wine')}"
        )

        # --- Bun use: the minion is dead (single-wave copy — the damage
        # trail is final), so the restore math is exact: hp_before is the
        # trail's value, hp_after the capped add. One Bun is consumed.
        hp_now = max_hp - contact_damage * len(records("player_hit"))
        assert hp_now < max_hp, "the mitigation beat must have cost some HP"
        tap("eat_bun")
        eaten = poll(lambda: records("bun_eaten"))
        assert eaten, "no gda_log 'bun_eaten' record"
        fields = eaten[0]["fields"]
        assert fields["hp_before"] == pytest.approx(hp_now)
        assert fields["hp_after"] == pytest.approx(min(hp_now + bun_restore, max_hp))
        assert fields["count"] == 0
        expected_hp = min(hp_now + bun_restore, max_hp)
        assert poll(
            lambda: label("Hp") == f"HP {math.ceil(expected_hp)}/{round(max_hp)}"
        ), f"HP readout disagrees with the restore: {label('Hp')}"
        assert poll(lambda: label("Bun") == "BUN 0"), (
            f"BUN readout must show the consumed supply: {label('Bun')}"
        )

        # --- Wine use: a Gravity fire spends MP first (the S3 economy), the
        # Wine restores it capped at max and RE-ARMS the gun — one Wine
        # covers at least one fire (config sanity pinned here since the S7
        # gating moved the re-arm proof out of the S3 e2e).
        assert wine_restore >= mp_cost, "items_config: wine_mp_restore < mp_cost"
        tap("switch_weapon")
        assert poll(lambda: records("weapon_switched")), "no weapon_switched record"
        tap("fire")
        assert poll(lambda: records("gravity_fired")), "no gravity_fired record"
        mp_now = max_mp - mp_cost
        assert poll(lambda: label("Mp") == f"MP {round(mp_now)}/{round(max_mp)}"), (
            "HUD should surface the MP spend"
        )
        tap("drink_wine")
        drunk = poll(lambda: records("wine_drunk"))
        assert drunk, "no gda_log 'wine_drunk' record"
        fields = drunk[0]["fields"]
        assert fields["mp_before"] == pytest.approx(mp_now)
        assert fields["mp_after"] == pytest.approx(min(mp_now + wine_restore, max_mp))
        assert fields["count"] == 0
        expected_mp = min(mp_now + wine_restore, max_mp)
        assert poll(
            lambda: label("Mp") == f"MP {math.ceil(expected_mp)}/{round(max_mp)}"
        ), f"MP readout disagrees with the restore: {label('Mp')}"
        assert poll(lambda: label("Wine") == "WINE 0"), (
            f"WINE readout must show the consumed supply: {label('Wine')}"
        )
        tap("fire")
        assert poll(lambda: len(records("gravity_fired")) >= 2), (
            "after Wine the Gravity Gun should fire again"
        )

        # --- Emptied supply refuses again: the loop is closed (collect ->
        # use -> empty), not a one-way faucet.
        blocked_before = len(records("consumable_blocked"))
        tap("drink_wine")
        assert poll(lambda: len(records("consumable_blocked")) == blocked_before + 1), (
            "the emptied wine supply must refuse"
        )
        assert records("consumable_blocked")[-1]["fields"] == {
            "item": "wine",
            "count": 0,
        }

        # --- The supply->use trace is ORDERED: collection precedes use,
        # use precedes the post-use refusal.
        proc = run("logger", "tail")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        trace = [
            r["message"]
            for r in json.loads(proc.stdout)["records"]
            if r["origin"] == "gda_log"
        ]
        assert trace.index("item_collected") < trace.index("bun_eaten"), trace
        assert trace.index("bun_eaten") < trace.index("wine_drunk"), trace
    finally:
        run("daemon", "stop")
