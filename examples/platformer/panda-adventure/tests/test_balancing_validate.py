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
import subprocess
import sys
from pathlib import Path

import pytest

import build_config
from balancing import config, report
from balancing.cli import EXIT_REFUSED, main as cli_main
from balancing.model import build_player_model
from panda_balancing import adapter

GAME_DIR = build_config.GAME_DIR
CONFIG_DIR = GAME_DIR / "data" / "json"
GENERATED_DIR = GAME_DIR / "data" / "generated"
DATA_DIR = GAME_DIR / "data"
TARGETS = GAME_DIR / "tools" / "panda_balancing" / "targets.json"


def _cli(*args: str) -> list[str]:
    """A CLI argv against the committed per-game targets file."""
    return [args[0], "--targets", str(TARGETS), *args[1:]]


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
    cfg = config.load_pipeline_config(TARGETS)
    game = adapter.load_game_data(CONFIG_DIR)
    player = build_player_model(game, cfg.player_model_params)
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
    cfg = config.load_pipeline_config(TARGETS)
    game = adapter.load_game_data(CONFIG_DIR)
    player = build_player_model(game, cfg.player_model_params)
    result = report.run_validation(game, player, cfg.sim, cfg.targets)
    assert result.all_within_tolerance, report.format_text(result)


def test_cli_validate_json_writes_nothing(capsys, tmp_path) -> None:
    """``python -m balancing validate --json`` prints a parseable report and
    writes nothing to config; ``--out`` targets a non-config path only."""
    before = _tree_hash(CONFIG_DIR, GENERATED_DIR)
    out = tmp_path / "report.json"
    code = cli_main(_cli("validate", "--json", "--runs", "8", "--out", str(out)))
    assert code in (0, 1)  # a verdict, not a crash
    assert _tree_hash(CONFIG_DIR, GENERATED_DIR) == before
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["runs"] == 8
    assert len(doc["waves"]) == 4
    assert out.parent != CONFIG_DIR  # the report never lands in the authority


def test_cli_validate_default_verdict_is_green() -> None:
    """The default ``validate`` (committed targets, seed, runs) exits 0."""
    assert cli_main(_cli("validate", "--json")) == 0


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
    code = cli_main(_cli("validate", "--json", "--runs", "1", "--out", str(forbidden)))
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
        _cli("validate", "--json", "--runs", "1", "--out", "../data/json/sneaky.json")
    )
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "out_path_in_authority"
    assert _tree_hash(DATA_DIR) == before


def test_cli_out_outside_authority_still_works(tmp_path) -> None:
    """A normal ``--out`` (tmp dir) is unaffected by the guard and produces the
    report file."""
    out = tmp_path / "report.json"
    code = cli_main(_cli("validate", "--json", "--runs", "1", "--out", str(out)))
    assert code in (0, 1)  # the verdict, never the refusal
    assert json.loads(out.read_text(encoding="utf-8"))["runs"] == 1


@pytest.mark.parametrize(
    "artifact", ["targets.json", "adapter.py"], ids=["targets", "adapter"]
)
def test_cli_out_onto_own_input_artifact_is_refused(capsys, artifact: str) -> None:
    """An ``--out`` aimed at the run's own input artifacts (the targets file or
    the adapter) is REFUSED automatically — no declared root needed — and the
    artifact stays byte-identical (the self-clobber guard, PR #493 review)."""
    target = GAME_DIR / "tools" / "panda_balancing" / artifact
    before = target.read_bytes()
    code = cli_main(_cli("validate", "--json", "--runs", "1", "--out", str(target)))
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "out_path_in_authority"
    assert target.read_bytes() == before


def test_cli_non_object_targets_is_structured_refusal(capsys, tmp_path) -> None:
    """A syntactically valid targets document whose root is not a JSON object
    is a structured exit-2 refusal, never an AttributeError traceback."""
    bad = tmp_path / "targets.json"
    bad.write_text("[]", encoding="utf-8")
    code = cli_main(["validate", "--targets", str(bad), "--json"])
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "targets_invalid"


def test_cli_adapter_import_failure_is_structured_refusal(capsys, tmp_path) -> None:
    """An adapter that raises while importing is a structured exit-2 refusal
    (``adapter_invalid``), never a traceback."""
    doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    doc["config_dir"] = str(CONFIG_DIR)
    doc["adapter"] = "boom.py"
    doc["no_write_roots"] = []
    (tmp_path / "boom.py").write_text("raise RuntimeError('broken adapter')\n")
    bad = tmp_path / "targets.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    code = cli_main(["validate", "--targets", str(bad), "--json"])
    assert code == EXIT_REFUSED
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "adapter_invalid"
    assert "broken adapter" in err["detail"]


def test_documented_run_command_works() -> None:
    """The plug-in's documented invocation — ``python -m balancing validate
    --targets panda_balancing/targets.json`` from the ``tools/`` directory —
    actually runs (a verdict, not a usage error)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "balancing",
            "validate",
            "--targets",
            "panda_balancing/targets.json",
            "--json",
            "--runs",
            "1",
        ],
        cwd=GAME_DIR / "tools",
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    assert json.loads(proc.stdout)["runs"] == 1


@pytest.mark.parametrize(
    "field",
    [
        "player_model",
        "simulation",
        "waves",
        "config_dir",
        "adapter",
        "tolerance",
        "no_write_roots",
    ],
    ids=lambda f: f"{f}-null",
)
def test_cli_null_targets_field_is_structured_refusal(
    capsys, tmp_path, field: str
) -> None:
    """A targets document where ANY consumed field holds the wrong SHAPE (null
    where an object/array/string/number belongs) is a structured exit-2
    refusal at the schema boundary, never a TypeError traceback — including
    the path-valued fields resolved later (PR #493 re-review)."""
    doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    doc[field] = None
    bad = tmp_path / "targets.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    code = cli_main(["validate", "--targets", str(bad), "--json"])
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "targets_invalid"


def test_cli_nonpositive_runs_is_structured_refusal(capsys) -> None:
    """A non-positive simulation control (here ``--runs 0``, the CLI-override
    path) refuses as ``sim_invalid`` instead of crashing inside the sim."""
    code = cli_main(_cli("validate", "--json", "--runs", "0"))
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "sim_invalid"


def test_cli_adapter_returning_none_is_structured_refusal(capsys, tmp_path) -> None:
    """An adapter whose ``load_inputs`` returns something other than
    ``model.GameInputs`` (e.g. None) is a structured exit-2 refusal
    (``adapter_invalid``), never an AttributeError traceback (PR #493 recheck)."""
    doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    doc["config_dir"] = str(CONFIG_DIR)
    doc["adapter"] = "none_adapter.py"
    doc["no_write_roots"] = []
    (tmp_path / "none_adapter.py").write_text(
        "def load_inputs(config_dir):\n    return None\n"
    )
    bad = tmp_path / "targets.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    code = cli_main(["validate", "--targets", str(bad), "--json"])
    assert code == EXIT_REFUSED
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "adapter_invalid"
    assert "GameInputs" in err["detail"]


def test_cli_incomplete_player_model_is_structured_refusal(capsys, tmp_path) -> None:
    """A targets file missing a player-model assumption is a structured exit-2
    refusal (``targets_invalid``), never a KeyError traceback (gADR-0018)."""
    doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    del doc["player_model"]["accuracy"]
    bad = tmp_path / "targets.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    code = cli_main(["validate", "--targets", str(bad), "--json"])
    assert code == EXIT_REFUSED
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "targets_invalid"
    assert "accuracy" in err["detail"]


def test_cli_unloadable_config_dir_is_structured_refusal(capsys, tmp_path) -> None:
    """A config dir the adapter cannot load from (missing files) is a structured
    exit-2 refusal (``game_config_invalid``), never a traceback (gADR-0018)."""
    code = cli_main(
        _cli("validate", "--json", "--config-dir", str(tmp_path / "nowhere"))
    )
    assert code == EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["error"] == "game_config_invalid"
