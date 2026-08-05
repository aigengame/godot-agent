"""Tests for predict mode: cross-validation, the report, and the no-write CLI (#440).

Predict mode integrates the long-term SD growth/economy trajectory, checks it
against the difficulty/growth design targets, and — the core of gADR-0011's
trust story — cross-validates the macro model against the Monte-Carlo micro
engine on their overlapping domain, within a DOCUMENTED tolerance. Like validate
(gADR-0011) it writes NOTHING back to config; that guarantee is asserted by
hashing the whole authority around a run and by refusing an ``--out`` in the
authority tree. Fast tier, no engine (pure Python — both engines are).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import build_config
from balancing import config, prediction
from balancing.cli import EXIT_REFUSED, main as cli_main
from balancing.model import build_player_model
from panda_balancing import adapter

GAME_DIR = build_config.GAME_DIR
CONFIG_DIR = GAME_DIR / "content" / "data" / "json"
GENERATED_DIR = GAME_DIR / "content" / "data" / "generated"
DATA_DIR = GAME_DIR / "content" / "data"
TARGETS = GAME_DIR / "tools" / "panda_balancing" / "targets.json"


def _cli(*args: str) -> list[str]:
    """A CLI argv against the committed per-game targets file."""
    return [args[0], "--targets", str(TARGETS), *args[1:]]


def _tree_hash(*dirs: Path) -> str:
    h = hashlib.sha256()
    for root in dirs:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                h.update(str(path.relative_to(GAME_DIR)).encode())
                h.update(path.read_bytes())
    return h.hexdigest()


def _prediction():
    cfg = config.load_pipeline_config(TARGETS)
    sd = config.load_sd_config(TARGETS)
    inputs = adapter.load_inputs(CONFIG_DIR)
    player = build_player_model(inputs.game, cfg.player_model_params)
    return (
        prediction.run_prediction(inputs.game, inputs.economy, player, cfg.sim, sd),
        sd,
    )


# --- Cross-validation vs MC (AC3) -------------------------------------------- #


def test_sd_cross_validates_against_mc_within_tolerance() -> None:
    """On every overlapping Wave the SD prediction agrees with the MC median it
    must not contradict — clearing outcome AND the applicable TTK/TTD metric
    within the documented tolerance. The macro model does not contradict the
    micro simulation where their domains meet."""
    result, sd = _prediction()
    assert result.cross_checks, "no overlapping waves were cross-validated"
    for c in result.cross_checks:
        assert c.clearing_agreement, f"wave {c.wave}: SD/MC disagree on clearing"
        assert c.within_tolerance, (
            f"wave {c.wave}: SD {c.metric} {c.sd_value} vs MC {c.mc_value} "
            f"(rel error {c.rel_error}) exceeds tolerance {sd.cross_validation_tolerance}"
        )
    assert result.cross_validation_ok


def test_documented_cross_validation_tolerance_is_present() -> None:
    """gADR-0011 requires a DOCUMENTED cross-validation tolerance: it lives in the
    targets file (both the machine value and the prose rationale)."""
    doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    sd = doc["sd_model"]
    assert sd["cross_validation"]["tolerance"] == 0.30
    notes = sd["notes"]
    assert "cross_validation_tolerance" in notes
    assert "cross_validation_scenarios" in notes  # the overlapping scenarios
    assert "stocks" in notes and "flows" in notes  # the stock/flow variable list


def test_boss_is_the_meaningful_ttd_overlap() -> None:
    """The overlap is a mix of metrics: the cleared Waves cross-validate on TTK,
    the lethal Boss Wave on TTD (where MC and SD both have the Player die)."""
    result, _ = _prediction()
    by_wave = {c.wave: c for c in result.cross_checks}
    boss = max(by_wave)
    assert by_wave[boss].metric == "ttd"
    assert by_wave[boss].mc_death_rate >= 0.5
    # An earlier wave is a TTK overlap (both clear).
    assert any(c.metric == "ttk" for w, c in by_wave.items() if w < boss)


# --- The report + design targets (AC2) --------------------------------------- #


def test_report_shape_and_design_targets() -> None:
    """The report carries one trajectory entry per Wave with the growth/economy
    stocks, and the committed config MEETS its design targets (a green baseline
    for the predict gate)."""
    result, _ = _prediction()
    game = adapter.load_game_data(CONFIG_DIR)
    assert len(result.waves) == len(game.waves)
    assert result.design_targets_ok
    assert result.cleared_schedule  # the designed kit clears the schedule
    doc = prediction.report_to_dict(result)
    assert [w["wave"] for w in doc["waves"]] == [w.index for w in game.waves]
    assert "level_end" in doc["waves"][0] and "difficulty" in doc["waves"][0]
    assert doc["ok"] is True


def test_monotonic_ramp_target_gates_the_verdict() -> None:
    """A configured difficulty target the actual ramp FAILS drives the verdict
    red — with ``expect_monotonic_ramp=True`` but the committed ramp dipping at
    the swarm Wave, ``design_targets_ok`` and ``ok`` are False (finding 4: the
    ramp target must gate the verdict, not merely be reported)."""
    cfg = config.load_pipeline_config(TARGETS)
    sd = config.load_sd_config(TARGETS)
    sd = replace(sd, targets=replace(sd.targets, expect_monotonic_ramp=True))
    inputs = adapter.load_inputs(CONFIG_DIR)
    player = build_player_model(inputs.game, cfg.player_model_params)
    result = prediction.run_prediction(inputs.game, inputs.economy, player, cfg.sim, sd)
    assert result.monotonic_ramp_actual is False  # the swarm Wave dips
    assert result.monotonic_ramp_ok is False  # expected True, actual False
    assert not result.design_targets_ok
    assert not result.ok


def test_format_text_renders() -> None:
    """The human rendering produces the three sections without error."""
    result, _ = _prediction()
    text = prediction.format_text(result)
    assert "Balancing predict" in text
    assert "CROSS-VALIDATION vs MC" in text
    assert "RESULT:" in text


# --- No-write guarantee + CLI (gADR-0011) ------------------------------------ #


def test_predict_writes_nothing() -> None:
    """A predict run leaves the JSON authority AND the derived Resources
    byte-identical — predict never writes config."""
    before = _tree_hash(CONFIG_DIR, GENERATED_DIR)
    _prediction()
    assert _tree_hash(CONFIG_DIR, GENERATED_DIR) == before


def test_cli_predict_default_verdict_is_green() -> None:
    """The default ``predict`` (committed targets) exits 0."""
    assert cli_main(_cli("predict", "--json")) == 0


def test_cli_predict_json_writes_nothing(tmp_path) -> None:
    """``predict --json --out <tmp>`` emits a parseable report to a non-config
    path and writes nothing to the authority."""
    before = _tree_hash(CONFIG_DIR, GENERATED_DIR)
    out = tmp_path / "prediction.json"
    code = cli_main(_cli("predict", "--json", "--runs", "16", "--out", str(out)))
    assert code in (0, 1)  # a verdict, not a crash
    assert _tree_hash(CONFIG_DIR, GENERATED_DIR) == before
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "cross_validation" in doc and "waves" in doc
    assert len(doc["waves"]) == 4


@pytest.mark.parametrize(
    "forbidden",
    [
        DATA_DIR / "json" / "prediction.json",
        DATA_DIR / "json" / "combat_config.json",
        DATA_DIR / "generated" / "prediction.json",
        DATA_DIR / "prediction.json",
    ],
    ids=["authority-new", "authority-clobber", "generated", "data-root"],
)
def test_cli_predict_out_into_authority_is_refused(capsys, forbidden: Path) -> None:
    """An ``--out`` inside the config authority tree is REFUSED before anything
    runs: structured error, ``EXIT_REFUSED``, authority byte-identical."""
    before = _tree_hash(DATA_DIR)
    existed_before = forbidden.exists()
    code = cli_main(_cli("predict", "--json", "--runs", "1", "--out", str(forbidden)))
    assert code == EXIT_REFUSED
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "out_path_in_authority"
    assert forbidden.exists() == existed_before
    assert _tree_hash(DATA_DIR) == before


def test_cli_predict_out_relative_traversal_is_refused(capsys, monkeypatch) -> None:
    """The guard resolves first, so a ``../`` spelling of an authority path is
    refused too."""
    monkeypatch.chdir(GAME_DIR / "tools")
    before = _tree_hash(DATA_DIR)
    code = cli_main(
        _cli("predict", "--json", "--runs", "1", "--out", "../content/data/json/sneaky.json")
    )
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "out_path_in_authority"
    assert _tree_hash(DATA_DIR) == before


def test_cli_predict_null_sd_model_is_structured_refusal(capsys, tmp_path) -> None:
    """A ``sd_model: null`` targets document refuses as ``targets_invalid``
    when predict reads its block — never a TypeError traceback (PR #493
    re-review; config_dir/adapter point at the real ones so the parse is the
    first failure)."""
    doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    doc["sd_model"] = None
    doc["config_dir"] = str(CONFIG_DIR)
    doc["adapter"] = str(GAME_DIR / "tools" / "panda_balancing" / "adapter.py")
    doc["no_write_roots"] = []
    bad = tmp_path / "targets.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    code = cli_main(["predict", "--targets", str(bad), "--json"])
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "targets_invalid"


def test_cli_predict_out_outside_authority_works(tmp_path) -> None:
    """A normal ``--out`` (tmp dir) is unaffected by the guard."""
    out = tmp_path / "prediction.json"
    code = cli_main(_cli("predict", "--json", "--runs", "1", "--out", str(out)))
    assert code in (0, 1)
    assert "cross_validation" in json.loads(out.read_text(encoding="utf-8"))


# The game-agnostic guarantee (AC6) is pinned package-wide — imports AND
# vocabulary — in ``test_balancing_isolation.py`` (gADR-0018).
