"""Golden parity gate for the Balancing pipeline's rule reimplementation (gADR-0011).

gADR-0011 isolates the balancing pipeline from the game's GDScript by
reimplementing the combat/AI rules in Python (``tools/balancing/rules.py``) and
pinning them against the shipped seams with golden contract fixtures. Two tiers,
so drift on EITHER side goes red:

- **Fast tier** (``test_python_rules_match_golden``) — the Python rules reproduce
  every committed golden vector. A Python-side rule change breaks this without a
  Godot engine.
- **Engine tier** (``test_gdscript_seams_match_golden``, ``engine`` marker) —
  regenerates the fixtures FROM the GDScript seams via ``gda script run`` and
  asserts they still match the committed file. A GDScript-side rule change breaks
  this.

The parity tolerance is configurable via ``$BALANCING_PARITY_TOL`` (default a
tight ``1e-9`` — the seams are exact 64-bit-float arithmetic on these inputs).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pytest

from gda.binary import resolve_godot_binary

import build_config
from balancing import rules

GDA_CMD = [sys.executable, "-m", "gda"]
GAME_DIR = build_config.GAME_DIR
_FIXTURE = GAME_DIR / "tests" / "fixtures" / "balancing" / "seams.json"
_GENERATOR = "res://tests/gdscript/make_balancing_fixtures.gd"

PARITY_TOL = float(os.environ.get("BALANCING_PARITY_TOL", "1e-9"))


def _apply_rule(category: str, case: dict) -> float | bool:
    """Run the Python rule for one fixture ``category`` on its ``case`` inputs."""
    if category == "compute_damage":
        return rules.compute_damage(
            case["attacker_attack"],
            case["defender_defense"],
            case["attack_scale"],
            case["defense_scale"],
            case["min_damage"],
        )
    if category == "is_invulnerable":
        return rules.is_invulnerable(
            case["last_hit_time"], case["now"], case["iframe_duration"]
        )
    if category == "is_dead":
        return rules.is_dead(case["hp"])
    if category == "compute_move_dir":
        sp, pp = case["self_pos"], case["player_pos"]
        return rules.compute_move_dir(
            sp[0], sp[1], pp[0], pp[1],
            case["aggro_range"], case["keep_range_min"], case["keep_range_max"],
        )
    if category == "is_attack_ready":
        return rules.is_attack_ready(
            case["last_attack_time"], case["now"], case["cooldown"]
        )
    if category == "can_attack":
        sp, pp = case["self_pos"], case["player_pos"]
        return rules.can_attack(
            sp[0], sp[1], pp[0], pp[1],
            case["aggro_range"], case["attack_range"], case["attack_cooldown"],
            case["last_attack_time"], case["now"],
        )
    raise AssertionError(f"unknown fixture category {category!r}")


def _assert_match(got: float | bool, expected: float | bool, where: str) -> None:
    if isinstance(expected, bool) or isinstance(got, bool):
        assert bool(got) == bool(expected), f"{where}: {got!r} != {expected!r}"
    else:
        assert math.isclose(got, expected, rel_tol=0.0, abs_tol=PARITY_TOL), (
            f"{where}: {got!r} != {expected!r} (tol {PARITY_TOL})"
        )


def _script_run(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            *GDA_CMD, "script", "run", _GENERATOR,
            "--project", str(GAME_DIR),
            "--godot", str(resolve_godot_binary()),
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_python_rules_match_golden() -> None:
    """The Python reimplementation reproduces every committed golden vector."""
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert fixture, "the golden fixture is empty"
    for category, cases in fixture.items():
        assert cases, f"category {category!r} has no cases"
        for i, case in enumerate(cases):
            got = _apply_rule(category, case)
            _assert_match(got, case["expected"], f"{category}[{i}]")


@pytest.mark.engine
def test_gdscript_seams_match_golden(tmp_path) -> None:
    """Regenerating FROM the GDScript seams still matches the committed golden
    file — a GDScript-side rule change would break parity here."""
    env = {**os.environ, "BALANCING_FIXTURES_DIR": str(tmp_path)}
    proc = _script_run(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["exit_status"] == 0, doc
    assert "FIXTURES_DONE" in doc["stdout"], doc["stdout"]

    regenerated = json.loads((tmp_path / "seams.json").read_text(encoding="utf-8"))
    committed = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert set(regenerated) == set(committed), "fixture categories drifted"
    for category, cases in committed.items():
        fresh = regenerated[category]
        assert len(fresh) == len(cases), f"{category}: case count drifted"
        for i, (a, b) in enumerate(zip(fresh, cases)):
            _assert_match(a["expected"], b["expected"], f"{category}[{i}].expected")
