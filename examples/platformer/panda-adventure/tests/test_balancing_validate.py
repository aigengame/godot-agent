"""Tests for validate mode: the report, the no-write guarantee, and the CLI (#437).

Validate mode reports per-wave TTK/TTD against design targets and — per
gADR-0011 (this slice is validate-only) — writes NOTHING back to config. That
guarantee is asserted two ways: hashing the whole JSON authority (and the
derived Resources) before and after a validate run, and refusing an ``--out``
path that resolves into the authority tree (exit ``EXIT_REFUSED``, distinct
from the tolerance verdict) BEFORE anything runs. Fast tier, no engine.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import build_config
from balancing import game_config, report
from balancing.cli import EXIT_REFUSED, main as cli_main

GAME_DIR = build_config.GAME_DIR
CONFIG_DIR = GAME_DIR / "data" / "json"
GENERATED_DIR = GAME_DIR / "data" / "generated"
DATA_DIR = GAME_DIR / "data"
TARGETS = GAME_DIR / "tools" / "balancing" / "panda_adventure.targets.json"


def _tree_hash(*dirs: Path) -> str:
    """A content hash over every file under ``dirs`` (path + bytes)."""
    h = hashlib.sha256()
    for root in dirs:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                h.update(str(path.relative_to(GAME_DIR)).encode())
                h.update(path.read_bytes())
    return h.hexdigest()


def _small_config() -> tuple:
    cfg = report.load_pipeline_config(TARGETS)
    game = game_config.load_game_data(CONFIG_DIR)
    player = game_config.build_player_model(game, cfg.player_model_params)
    fast = type(cfg.sim)(dt=cfg.sim.dt, max_time=cfg.sim.max_time, runs=8, seed=1)
    return game, player, fast, cfg.targets


def test_report_shape_per_wave() -> None:
    """The report has one entry per wave, each carrying measured TTK/TTD
    distributions and its targets."""
    game, player, sim, targets = _small_config()
    result = report.run_validation(game, player, sim, targets)
    assert len(result.waves) == len(game.waves)
    for w in result.waves:
        assert w.ttk.n == sim.runs and w.ttd.n == sim.runs
        assert w.target_ttk is not None and w.target_ttd is not None
        assert 0.0 <= w.clear_rate <= 1.0 and 0.0 <= w.death_rate <= 1.0
    # Serializes to a plain JSON-able dict.
    doc = report.report_to_dict(result)
    assert [x["wave"] for x in doc["waves"]] == [w.index for w in game.waves]
    assert "median" in doc["waves"][0]["ttk"]


def test_validate_writes_nothing() -> None:
    """A validate run leaves the JSON authority AND the derived Resources
    byte-identical — this slice never writes config (gADR-0011)."""
    before = _tree_hash(CONFIG_DIR, GENERATED_DIR)
    game, player, sim, targets = _small_config()
    report.run_validation(game, player, sim, targets)
    assert _tree_hash(CONFIG_DIR, GENERATED_DIR) == before


def test_committed_targets_are_within_tolerance() -> None:
    """The committed design targets pass at the committed seed/run count — the
    demo's initial tune meets intent (a green baseline for the validate gate)."""
    cfg = report.load_pipeline_config(TARGETS)
    game = game_config.load_game_data(CONFIG_DIR)
    player = game_config.build_player_model(game, cfg.player_model_params)
    result = report.run_validation(game, player, cfg.sim, cfg.targets)
    assert result.all_within_tolerance, report.format_text(result)


def test_cli_validate_json_writes_nothing(capsys, tmp_path) -> None:
    """``python -m balancing validate --json`` prints a parseable report and
    writes nothing to config; ``--out`` targets a non-config path only."""
    before = _tree_hash(CONFIG_DIR, GENERATED_DIR)
    out = tmp_path / "report.json"
    code = cli_main(["validate", "--json", "--runs", "8", "--out", str(out)])
    assert code in (0, 1)  # a verdict, not a crash
    assert _tree_hash(CONFIG_DIR, GENERATED_DIR) == before
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["runs"] == 8
    assert len(doc["waves"]) == 4
    assert out.parent != CONFIG_DIR  # the report never lands in the authority


def test_cli_validate_default_verdict_is_green() -> None:
    """The default ``validate`` (committed targets, seed, runs) exits 0."""
    assert cli_main(["validate", "--json"]) == 0


@pytest.mark.parametrize(
    "forbidden",
    [
        DATA_DIR / "json" / "probe_report.json",  # the reviewer's repro
        DATA_DIR / "json" / "combat_config.json",  # the clobber scenario
        DATA_DIR / "generated" / "probe_report.json",  # the derived tree
        DATA_DIR / "schema" / "probe_report.json",  # the whole data/ chain
        DATA_DIR / "probe_report.json",
    ],
    ids=["authority-new", "authority-clobber", "generated", "schema", "data-root"],
)
def test_cli_out_into_authority_is_refused(capsys, forbidden: Path) -> None:
    """An ``--out`` inside the config authority tree is REFUSED before the sim
    runs: structured error on stderr, ``EXIT_REFUSED`` (distinct from the 0/1
    tolerance verdict), no file created, authority tree byte-identical."""
    before = _tree_hash(DATA_DIR)
    existed_before = forbidden.exists()
    code = cli_main(["validate", "--json", "--runs", "1", "--out", str(forbidden)])
    assert code == EXIT_REFUSED
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "out_path_in_authority"
    assert forbidden.exists() == existed_before  # nothing new appeared
    assert _tree_hash(DATA_DIR) == before  # nothing changed either


def test_cli_out_relative_traversal_is_refused(capsys, monkeypatch) -> None:
    """The guard resolves the path first, so a relative ``../``-style spelling
    of an authority location is refused too."""
    monkeypatch.chdir(GAME_DIR / "tools")
    before = _tree_hash(DATA_DIR)
    code = cli_main(
        ["validate", "--json", "--runs", "1", "--out", "../data/json/sneaky.json"]
    )
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "out_path_in_authority"
    assert _tree_hash(DATA_DIR) == before


def test_cli_out_outside_authority_still_works(tmp_path) -> None:
    """A normal ``--out`` (tmp dir) is unaffected by the guard and produces the
    report file."""
    out = tmp_path / "report.json"
    code = cli_main(["validate", "--json", "--runs", "1", "--out", str(out)])
    assert code in (0, 1)  # the verdict, never the refusal
    assert json.loads(out.read_text(encoding="utf-8"))["runs"] == 1
