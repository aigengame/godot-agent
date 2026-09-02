"""`gda resource import` — the scoped import surface, engine-free (#668).

The cache-verdict logic is pure Python (sidecar + dest-file checks), so the
dry-run and all-cached paths run with NO fake at all against a real temp
project tree. The engine pass is exercised through the launch seam
(``gda.commands.resource.launch``, the scene/script channels' pattern): a fake
launch simulates the pass's file effects, so the re-verdict, the before/after
accounting, and the classification are covered without an engine. The real
engine round trip (GDA-DF-010's preload failure healed by the import) is the
e2e in ``test_e2e_resource_import``.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import LaunchFailure, RunResult, TimeoutBound

runner_cli = CliRunner()


def _project(tmp_path: Path) -> Path:
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG fake bytes")
    return tmp_path


def _sidecar(
    project: Path,
    asset: str,
    dest_rel: str | None,
    valid: bool = True,
    importer: str = "texture",
    uid: bool = True,
    source_file: str | None = None,
) -> None:
    """A sidecar shaped like the engine writes it (uid + source_file included:
    the reimport-test adapter reads both, #738 review)."""
    lines = [f'[remap]\n\nimporter="{importer}"\n']
    if not valid:
        lines.append("valid=false\n")
    if uid:
        lines.append('uid="uid://test"\n')
    lines.append("\n[deps]\n\n")
    source = source_file if source_file is not None else f"res://{asset}"
    lines.append(f'source_file="{source}"\n')
    if dest_rel is not None:
        lines.append(f'dest_files=["res://{dest_rel}"]\n')
    (project / f"{asset}.import").write_text("".join(lines), encoding="utf-8")


def _receipt_path(project: Path, asset: str) -> Path:
    """The engine's per-asset receipt, at the PATH-derived import base:
    .godot/imported/<filename>-<md5 of the res:// path>.md5 — how
    ResourceFormatImporter::get_import_base_path derives it."""
    import hashlib

    digest = hashlib.md5(f"res://{asset}".encode()).hexdigest()
    return project / ".godot" / "imported" / f"{Path(asset).name}-{digest}.md5"


def _md5_companion(project: Path, dest_rel: str, source_rel: str) -> None:
    """The engine's freshness receipt for ``source_rel``, recording source_md5."""
    import hashlib

    digest = hashlib.md5((project / source_rel).read_bytes()).hexdigest()
    receipt = _receipt_path(project, source_rel)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(f'source_md5="{digest}"\n', encoding="utf-8")


def _cached_asset(project: Path, asset: str, dest_rel: str) -> None:
    """A fully intact cache: sidecar + dest + the engine's md5 receipt."""
    (project / dest_rel).parent.mkdir(parents=True, exist_ok=True)
    (project / dest_rel).write_bytes(b"ctex")
    _sidecar(project, asset, dest_rel)
    _md5_companion(project, dest_rel, asset)


def _run(project: Path, *args: str):
    return runner_cli.invoke(
        app,
        ["resource", "import", *args, "--project", str(project), "--json"],
    )


def _tree(project: Path) -> set[str]:
    return {
        p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()
    }


# --- dry run and the pure-Python verdicts (no engine, no fake) -----------------


def test_dry_run_reports_missing_and_predictions_and_writes_nothing(tmp_path):
    project = _project(tmp_path)
    before = _tree(project)

    result = _run(project, "res://icon.png", "--dry-run")

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["dry_run"] is True
    assert data["engine_pass"] is True  # a real run WOULD run the pass
    assert data["assets"] == [
        {
            "path": "res://icon.png",
            "status": "missing",
            "sidecar": None,
            "dest_files": [],
        }
    ]
    assert data["predicted_source_adjacent"] == ["res://icon.png.import"]
    assert data["created"] == []
    assert data["summary"]["missing"] == 1
    assert data["cache_root"] == "res://.godot"
    # The AC: a dry run writes nothing at all.
    assert _tree(project) == before


def test_dry_run_cached_when_sidecar_dest_files_exist(tmp_path):
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex"
    _cached_asset(project, "icon.png", dest)

    result = _run(project, "res://icon.png", "--dry-run")

    data = json.loads(result.stdout)
    assert data["assets"][0]["status"] == "cached"
    assert data["assets"][0]["sidecar"] == "res://icon.png.import"
    assert data["assets"][0]["dest_files"] == [f"res://{dest}"]
    assert data["engine_pass"] is False
    assert data["predicted_source_adjacent"] == []


def test_dry_run_stale_when_a_dest_file_is_absent(tmp_path):
    project = _project(tmp_path)
    _sidecar(
        project,
        "icon.png",
        ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    # It HAS a sidecar, so no sidecar-creation prediction for it.
    assert data["predicted_source_adjacent"] == []
    assert data["engine_pass"] is True


def test_dry_run_keep_importer_sidecar_counts_as_cached(tmp_path):
    project = _project(tmp_path)
    _sidecar(project, "icon.png", None, importer="keep")

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "cached"
    assert data["engine_pass"] is False


# --- the engine pass, through the launch seam ---------------------------------


def _fake_pass(project: Path, effects):
    """A fake launch that simulates the engine pass's file effects."""
    calls = []

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        calls.append((binary, args, cwd, timeout))
        effects(project)
        return RunResult(stdout="", stderr="", exit_code=0)

    return calls, fake_launch


def test_missing_asset_runs_the_pass_and_reports_created_classified(
    monkeypatch, tmp_path
):
    project = _project(tmp_path)

    def effects(p: Path) -> None:
        _cached_asset(
            p,
            "icon.png",
            ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
        )
        (p / "tool.gd.uid").write_text("uid://x", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    result = _run(project, "res://icon.png")

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["dry_run"] is False
    assert data["engine_pass"] is True
    assert data["assets"][0]["status"] == "imported"
    created = {f["path"]: f["classification"] for f in data["created"]}
    assert (
        created["res://.godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex"]
        == "cache_owned"
    )
    assert created["res://icon.png.import"] == "source_adjacent"
    assert created["res://tool.gd.uid"] == "source_adjacent"
    assert data["summary"]["imported"] == 1
    assert data["summary"]["created_cache_owned"] == 2  # the .ctex and its .md5
    assert data["summary"]["created_source_adjacent"] == 2
    # The pass argv: the engine's project-wide --import, nothing else.
    (binary, args, cwd, timeout) = calls[0]
    assert args == ["--path", str(project), "--import"]
    assert timeout == 300.0


def test_all_cached_runs_no_pass(monkeypatch, tmp_path):
    project = _project(tmp_path)
    _cached_asset(
        project,
        "icon.png",
        ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
    )

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["engine_pass"] is False
    assert data["assets"][0]["status"] == "cached"
    assert data["created"] == []
    assert calls == []  # the AC's spirit: no needless pass, ever


def test_pass_that_settles_no_sidecar_is_not_importable(monkeypatch, tmp_path):
    project = _project(tmp_path)
    (project / "script.gd").write_text("extends Node\n", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://script.gd").stdout)

    assert data["assets"][0]["status"] == "not_importable"
    assert data["summary"]["not_importable"] == 1


def test_pass_that_leaves_dest_missing_is_failed(monkeypatch, tmp_path):
    project = _project(tmp_path)

    def effects(p: Path) -> None:
        _sidecar(p, "icon.png", ".godot/imported/never-written.ctex")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["assets"][0]["status"] == "failed"
    assert data["summary"]["failed"] == 1


def test_launch_failures_classify_through_the_shared_prefix(monkeypatch, tmp_path):
    project = _project(tmp_path)

    def timed_out(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        return RunResult(
            stdout="[  30% ] importing res://icon.png\n",
            stderr="took too long",
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=timeout + 0.2,
            timeout_bound=TimeoutBound(timeout_label, timeout),
        )

    monkeypatch.setattr("gda.commands.resource.launch", timed_out)
    timed = json.loads(_run(project, "res://icon.png").stdout)
    assert timed["error"]["code"] == "launch_timeout"
    # The THIRD buffered channel, on the shared branch with the other two (#714):
    # its label, its ceiling and its own captured output, none of it forked here.
    assert timed["error"]["message"].startswith("Godot import launched but did not")
    assert "importing res://icon.png" in timed["error"]["diagnostics"]
    assert "took too long" in timed["error"]["diagnostics"]


def test_the_import_pass_declares_its_own_timeout_label(monkeypatch, tmp_path):
    # The label is this channel's one contribution to the shared timeout envelope,
    # and it is what tells an agent WHICH launch gave up when three of them report
    # the same code. Pinned at the call site, because nothing else would notice it
    # silently reverting to the sentinel channel's bare "Godot".
    project = _project(tmp_path)
    seen: dict[str, object] = {}

    def recording(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        seen["label"] = timeout_label
        seen["timeout"] = timeout
        return RunResult(stdout="", stderr="", exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", recording)
    _run(project, "res://icon.png", "--timeout", "7")

    assert seen == {"label": "Godot import", "timeout": 7.0}

    def engine_failed(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        return RunResult(stdout="", stderr="importer exploded", exit_code=1)

    monkeypatch.setattr("gda.commands.resource.launch", engine_failed)
    failed = json.loads(_run(project, "res://icon.png").stdout)
    assert failed["error"]["code"] == "operation_failed"
    assert "importer exploded" in failed["error"]["diagnostics"]


def test_engine_invalid_sidecar_is_never_a_hit_and_settles_failed(
    monkeypatch, tmp_path
):
    # #738 review [P1]: the ENGINE marked the import failed (valid=false); gda
    # must not call that cached — nor rewrite it to "imported" after a pass
    # that leaves it invalid.
    project = _project(tmp_path)

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    _sidecar(project, "icon.png", None, valid=False)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["assets"][0]["status"] == "failed"
    assert data["summary"]["failed"] == 1
    # The engine skips a previously failed import, so gda spends NO pass on it.
    assert calls == []


def test_stale_source_is_stale_not_cached(tmp_path):
    # #738 review [P1]: freshness rides the engine's own md5 receipt — a source
    # that hashes differently from the recorded source_md5 would be re-imported
    # by the engine, so gda agrees: missing, and a pass would run.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex"
    _cached_asset(project, "icon.png", dest)
    (project / "icon.png").write_bytes(b"\x89PNG different bytes")

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    assert data["engine_pass"] is True


def test_receipt_uses_the_last_source_md5_assignment(tmp_path):
    # #738 re-review 6 [P1]: VariantParser consumes every assignment, so a
    # later source_md5 replaces an earlier value. Taking the first value spends
    # a pass the engine would skip.
    import hashlib

    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    _receipt_path(project, "icon.png").write_text(
        f'source_md5="{"0" * 32}"\nsource_md5="{source_digest}"\n',
        encoding="utf-8",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "cached"
    assert data["engine_pass"] is False


def test_receipt_last_source_md5_mismatch_is_stale(tmp_path):
    import hashlib

    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    _receipt_path(project, "icon.png").write_text(
        f'source_md5="{source_digest}"\nsource_md5="{"0" * 32}"\n',
        encoding="utf-8",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    assert data["engine_pass"] is True


def test_receipt_uses_the_last_dest_md5_assignment(tmp_path):
    import hashlib

    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    dest_digest = hashlib.md5((project / dest).read_bytes()).hexdigest()
    _receipt_path(project, "icon.png").write_text(
        f'source_md5="{source_digest}"\n'
        f'dest_md5="{"0" * 32}"\n'
        f'dest_md5="{dest_digest}"\n',
        encoding="utf-8",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "cached"
    assert data["engine_pass"] is False


def test_receipt_accepts_spacing_comments_and_escaped_string_values(tmp_path):
    # VariantParser accepts spacing, semicolon comments, and quoted-string
    # escapes even though the engine's own writer emits a canonical subset.
    import hashlib

    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    _receipt_path(project, "icon.png").write_text(
        "; retained hand-written comment\n"
        'note = "escaped \\"quote\\"" ; ignored assignment\n'
        f'source_md5 = "{source_digest}" ; current source\n',
        encoding="utf-8",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "cached"
    assert data["engine_pass"] is False


def test_receipt_lone_surrogate_escape_is_invalid_not_stale(tmp_path):
    # #738 review follow-up: json.loads accepts a LONE UTF-16 surrogate
    # escape, but VariantParser rejects it ("unpaired lead surrogate") — the
    # engine's deliberate parse-error skip. Classifying it stale would spend
    # a pass the engine would not run.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    _receipt_path(project, "icon.png").write_text(
        'source_md5="\\ud800"\n', encoding="utf-8"
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "invalid"
    assert data["engine_pass"] is False


def test_receipt_paired_surrogate_escape_still_parses(tmp_path):
    # The boundary pin: a PAIRED surrogate escape decodes to one real code
    # point on both sides (json.loads and VariantParser agree), so it stays
    # inside the subset — with a matching source_md5 the asset is cached.
    import hashlib

    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    _receipt_path(project, "icon.png").write_text(
        'note="\\ud83d\\ude00"\n' + f'source_md5="{source_digest}"\n',
        encoding="utf-8",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "cached"
    assert data["engine_pass"] is False


def test_malformed_receipt_is_invalid_and_spends_no_pass(monkeypatch, tmp_path):
    # #738 re-review 5 [P1]: the engine parses the receipt with VariantParser
    # and treats a parse error as the same deliberate skip as valid=false —
    # "skip and let user attempt manual reimport to avoid reimport loop",
    # never a re-import. gda must not spend a pass the engine would not run,
    # and must not settle the asset failed AFTER spending one.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    _receipt_path(project, "icon.png").write_text("source_md5=[\n", encoding="utf-8")

    dry = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)
    assert dry["assets"][0]["status"] == "invalid"
    assert dry["engine_pass"] is False
    assert dry["summary"]["invalid"] == 1

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    real = json.loads(_run(project, "res://icon.png").stdout)
    assert real["assets"][0]["status"] == "failed"
    assert real["engine_pass"] is False
    assert calls == []


def test_malformed_receipt_neighbor_is_excluded_from_the_gap_scan(tmp_path):
    # ...and the same skip state must not be predicted as pass work when
    # ANOTHER asset triggers the pass.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    _receipt_path(project, "icon.png").write_text("source_md5=[\n", encoding="utf-8")
    (project / "fresh.png").write_bytes(b"\x89PNG fresh")

    data = json.loads(_run(project, "res://fresh.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "missing"
    assert data["pass_will_also_import"] == []


def test_receipt_lacking_source_md5_is_stale_not_invalid(tmp_path):
    # The boundary NEXT to the parse error: a receipt that PARSES but lacks
    # source_md5 is the engine's "Lacks md5, so just reimport" — a pass
    # state, not the deliberate skip.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    _receipt_path(project, "icon.png").write_text(
        'dest_md5="' + "a" * 32 + '"\n', encoding="utf-8"
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    assert data["engine_pass"] is True


def test_missing_md5_receipt_is_stale_not_cached(tmp_path):
    # #738 review [P1]: without the receipt the engine cannot prove freshness
    # and re-imports; gda must not claim a hit the engine would not.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex"
    _cached_asset(project, "icon.png", dest)
    _receipt_path(project, "icon.png").unlink()

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"


def test_copied_sidecar_naming_another_source_is_stale(tmp_path):
    # #738 review [P1], the alias reproduction: copying icon.png + its sidecar
    # to alias2.png leaves source_file="res://icon.png" inside the copy — the
    # engine re-imports that; a destination-exists heuristic called it cached.
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    (project / "alias2.png").write_bytes((project / "icon.png").read_bytes())
    (project / "alias2.png.import").write_text(
        (project / "icon.png.import").read_text(encoding="utf-8"), encoding="utf-8"
    )

    data = json.loads(_run(project, "res://alias2.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    assert data["engine_pass"] is True


def test_dest_md5_mismatch_is_stale(tmp_path):
    # The engine's receipt also digests the DESTINATION bytes (one MD5 over
    # every dest, in order); a tampered cache file must not stay a hit.
    import hashlib

    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    _cached_asset(project, "icon.png", dest)
    receipt = _receipt_path(project, "icon.png")
    dest_digest = hashlib.md5(b"OTHER BYTES").hexdigest()
    receipt.write_text(
        receipt.read_text(encoding="utf-8") + f'dest_md5="{dest_digest}"\n',
        encoding="utf-8",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"


def test_human_dry_run_renders_the_project_wide_prediction(tmp_path):
    # #738 review [P2]: the default (non-JSON) dry run must carry the revised
    # contract's project-wide decidable inventory, not only the JSON form.
    project = _project(tmp_path)
    (project / "other.png").write_bytes(b"\x89PNG other")
    _sidecar(project, "other.png", ".godot/imported/other.png-" + "a" * 32 + ".ctex")

    result = runner_cli.invoke(
        app,
        [
            "resource",
            "import",
            "res://icon.png",
            "--dry-run",
            "--project",
            str(project),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "will also re-import" in result.stdout
    assert "res://other.png" in result.stdout


def test_no_destination_sidecar_with_matching_receipt_is_cached(tmp_path):
    # #738 re-review 4 [P1]: a sidecar declaring no destinations, whose
    # path-derived receipt exists and matches, is CURRENT to the engine
    # (there is nothing to check and the receipts pass) — the pass leaves it
    # untouched, so gda must not spend a pass on it or settle it failed.
    project = _project(tmp_path)
    _sidecar(project, "icon.png", None)  # importer=texture, uid, source_file
    _md5_companion(project, "", "icon.png")

    dry = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)
    assert dry["assets"][0]["status"] == "cached"
    assert dry["engine_pass"] is False

    real = json.loads(_run(project, "res://icon.png").stdout)
    assert real["assets"][0]["status"] == "cached"
    assert real["engine_pass"] is False


def test_no_destination_sidecar_is_excluded_from_the_gap_scan(tmp_path):
    # ...and the same state must not be falsely listed as something the pass
    # will re-import when ANOTHER asset triggers it.
    project = _project(tmp_path)
    _sidecar(project, "icon.png", None)
    _md5_companion(project, "", "icon.png")
    (project / "fresh.png").write_bytes(b"\x89PNG fresh")

    data = json.loads(_run(project, "res://fresh.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "missing"
    assert data["pass_will_also_import"] == []


def test_minimal_sidecar_is_stale_not_cached(tmp_path):
    # #738 re-review 2 [P1]: a parseable sidecar with only a uid line proved
    # nothing, yet fell through to cached and suppressed the pass the engine
    # would run. A CACHED verdict needs positive evidence.
    project = _project(tmp_path)
    (project / "icon.png.import").write_text('uid="uid://test"\n', encoding="utf-8")

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    assert data["engine_pass"] is True


def test_sidecar_without_an_importer_line_is_stale(tmp_path):
    # The engine's importer-existence check re-imports a sidecar whose
    # importer cannot be resolved; a missing declaration proves nothing.
    project = _project(tmp_path)
    (project / "icon.png.import").write_text(
        'uid="uid://test"\nsource_file="res://icon.png"\n', encoding="utf-8"
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"


def test_relative_project_with_symlinked_asset_is_structured(tmp_path, monkeypatch):
    # #738 re-review 2 [P1]: a RELATIVE --project plus a symlinked-in asset
    # used to compare a relative candidate against an absolute project and
    # escape as a bare ValueError traceback. Both sides now share one
    # coordinate system; the verdict is structured either way.
    project = _project(tmp_path)
    outside = tmp_path.parent / "linked-668.png"
    outside.write_bytes(b"\x89PNG linked")
    (project / "link.png").symlink_to(outside)
    monkeypatch.chdir(tmp_path.parent)

    result = runner_cli.invoke(
        app,
        [
            "resource",
            "import",
            "link.png",
            "--dry-run",
            "--project",
            project.name,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["assets"][0]["path"] == "res://link.png"
    assert data["assets"][0]["status"] == "missing"


def test_non_res_engine_virtual_schemes_are_refused(tmp_path):
    # #738 re-review 2 [P2]: user:// and uid:// are engine-virtual but not the
    # project's res:// namespace — refused by name, never misread as literal
    # filesystem paths (which used to happen when such a file existed).
    project = _project(tmp_path)
    (project / "user:").mkdir()
    (project / "user:" / "x.png").write_bytes(b"x")

    for scheme_path in ("user://x.png", "uid://abcdef"):
        data = json.loads(_run(project, scheme_path, "--dry-run").stdout)
        assert data["error"]["code"] == "invalid_params", scheme_path
        assert "not a project asset" in data["error"]["message"], scheme_path


@pytest.mark.parametrize(
    "spelling",
    [
        "res://../outside-668.png",
        # The separator spelling, and the Windows gap this gate carried until #763:
        # it split with `PurePosixPath`, so `..\\x` was ONE segment holding no `..`
        # at all and the `..`-in-parts check never fired. On POSIX the later
        # `is_file()` check happened to stop it; on native Windows `\\` IS a
        # separator and the join reaches the parent directory. The shared
        # canonicalizer folds `\\` to `/` the way `String::simplify_path` does
        # (ustring.cpp:4192), so the escape is now refused by the rule rather than
        # by a platform accident — identically on every platform.
        "res://..\\outside-668.png",
        "res://a\\..\\..\\outside-668.png",
    ],
)
def test_res_scheme_cannot_escape_the_project(tmp_path, spelling):
    # #738 review [P2]: res://../ must go through the same canonical
    # containment gate as filesystem input — which since #763 is literally the
    # ADR-0006 authority, not a second rule that agreed with it by coincidence.
    project = _project(tmp_path)
    (tmp_path.parent / "outside-668.png").write_bytes(b"x")

    data = json.loads(_run(project, spelling, "--dry-run").stdout)

    assert data["error"]["code"] == "target_outside_project"
    assert "outside the resolved Godot project" in data["error"]["message"]


def test_an_asset_a_nested_project_owns_is_refused_before_the_pass(tmp_path):
    # #697 re-review: the engine's own scan SKIPS a directory holding a nested
    # `project.godot` (`EditorFileSystem::_should_skip_directory`,
    # editor/file_system/editor_file_system.cpp:3482 — "Skip if another project
    # inside this"), so an asset in one cannot be imported into the outer project
    # at all. gda used to accept the request, spend an engine pass, and return
    # `not_importable`, while `--dry-run` predicted a sidecar that would never
    # appear. It now refuses up front and names the project that CAN import it.
    project = _project(tmp_path)
    nested = project / "vendor"
    nested.mkdir()
    (nested / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (nested / "pic.png").write_bytes(b"\x89PNG")

    data = json.loads(_run(project, "res://vendor/pic.png", "--dry-run").stdout)

    assert data["error"]["code"] == "target_outside_project"
    assert data["error"]["evidence"]["owning_project"] == str(nested.resolve())
    # The same file named by its filesystem spelling gets the same answer.
    other = json.loads(_run(project, str(nested / "pic.png"), "--dry-run").stdout)
    assert other["error"]["code"] == "target_outside_project"


def test_a_res_path_that_collapses_back_inside_is_accepted(tmp_path):
    # The divergence #763 exists to reconcile, decided in the authority's favour:
    # `res://foo/../pic.png` collapses net-INSIDE and names an address the engine
    # resolves happily, so it is accepted here exactly as `script validate` and
    # `script run` accept it. This gate used to refuse ANY literal `..`, so one
    # input had two verdicts depending on which command read it.
    project = _project(tmp_path)
    (project / "pic.png").write_bytes(b"\x89PNG")

    data = json.loads(_run(project, "res://foo/../pic.png", "--dry-run").stdout)

    assert "error" not in data, data
    assert data["assets"][0]["path"] == "res://pic.png"


def test_a_res_path_with_a_leading_slash_is_accepted_as_the_engine_reads_it(tmp_path):
    # The same reconciliation, second spelling: `res:///pic.png` was refused here
    # (`PurePosixPath("/pic.png").is_absolute()`) with a message about a `..` the
    # path does not contain, while both script commands accepted it. Godot's
    # `split("/", false)` drops the empty segment, so the engine reads it as
    # `res://pic.png` — and so does gda now, in one place.
    project = _project(tmp_path)
    (project / "pic.png").write_bytes(b"\x89PNG")

    data = json.loads(_run(project, "res:///pic.png", "--dry-run").stdout)

    assert "error" not in data, data
    assert data["assets"][0]["path"] == "res://pic.png"


def test_both_spellings_of_the_project_root_normalize_to_the_bare_scheme(tmp_path):
    # The root-collapse parity gap PR #766 documented and #763 closes: the engine
    # joins an empty segment vector back to the bare `res://`, while `normpath`
    # yields `.`. This gate handed the bogus `res://.` on to the existence check,
    # which then named it in the refusal. The root is still refused — it is a
    # directory, not an asset — but by its one real address, and identically from
    # the res:// and the filesystem spelling.
    project = _project(tmp_path)

    for spelling in ("res://", "res://foo/..", ".", "foo/.."):
        data = json.loads(_run(project, spelling, "--dry-run").stdout)
        assert data["error"]["code"] == "invalid_params", spelling
        assert "asset res:// does not exist" in data["error"]["message"], spelling


def test_symlinked_in_asset_is_accepted_like_the_engine_walks_it(tmp_path):
    # The shared ADR-0006 gate's established symlink treatment (#738 review):
    # a file linked INTO the project tree is addressable through the project's
    # res:// namespace — the engine walks the link — so it is accepted, for
    # both input forms, exactly as `script run` accepts it.
    project = _project(tmp_path)
    outside = tmp_path.parent / "target-668.png"
    outside.write_bytes(b"\x89PNG linked")
    (project / "link.png").symlink_to(outside)

    data = json.loads(_run(project, "link.png", "--dry-run").stdout)

    assert data["assets"][0]["path"] == "res://link.png"
    assert data["assets"][0]["status"] == "missing"


def test_dry_run_lists_what_the_pass_will_also_reimport(tmp_path):
    # #738 review: the project-wide pass WILL re-import other stale assets —
    # and will NOT retry an invalid one (the engine skips those), so the
    # prediction separates the two evidence states.
    project = _project(tmp_path)
    (project / "other.png").write_bytes(b"\x89PNG other")
    _sidecar(
        project,
        "other.png",
        ".godot/imported/other.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
    )
    (project / "bad.png").write_bytes(b"\x89PNG bad")
    _sidecar(project, "bad.png", None, valid=False)

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["path"] == "res://icon.png"
    assert data["pass_will_also_import"] == ["res://other.png"]


def test_the_gap_scan_skips_every_directory_the_engines_scan_never_reaches(tmp_path):
    # #804: the prediction must not promise work the engine's pass never does.
    # `EditorFileSystem::_should_skip_directory` skips a directory holding a
    # `project.godot` or a `.gdignore`, so a stale sidecar under one is never
    # re-imported — the gap scan reads the project's files directly and used to
    # report both. A stale asset in an ordinary directory is still a gap, so this
    # narrows the scan rather than emptying it.
    #
    # The DOT-prefixed directory is the third case, and the one the marker clauses
    # alone still got wrong (#808 review): `_scan_new_dir` drops such a directory
    # BEFORE it consults the skip rule, so `res://.hidden/pic.png` is unreachable
    # too. Measured against a real pass, which re-imported the ordinary asset and
    # left the hidden one's sidecar and cache artefacts untouched.
    project = _project(tmp_path)
    for directory, marker in (("nested", "project.godot"), ("ignored", ".gdignore")):
        (project / directory).mkdir()
        (project / directory / marker).write_text("", encoding="utf-8")
        (project / directory / "pic.png").write_bytes(b"\x89PNG skipped")
        _sidecar(project, f"{directory}/pic.png", None)
    for hidden in (".hidden", "sub/.hidden"):
        (project / hidden).mkdir(parents=True)
        (project / hidden / "pic.png").write_bytes(b"\x89PNG hidden")
        _sidecar(project, f"{hidden}/pic.png", None)
    (project / "ordinary").mkdir()
    (project / "ordinary" / "pic.png").write_bytes(b"\x89PNG reached")
    _sidecar(project, "ordinary/pic.png", None)

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["pass_will_also_import"] == ["res://ordinary/pic.png"], data


# --- request validation --------------------------------------------------------


def test_asset_outside_the_project_is_the_shared_containment_refusal(tmp_path):
    # #763: one condition, one code. This used to be a generic `invalid_params`
    # while `script validate` reported `project_not_found` and `script run`
    # `invalid_path` for the very same "this target is not in the resolved
    # project" — three answers an agent could not branch on once.
    project = _project(tmp_path)
    outside = tmp_path.parent / "elsewhere.png"

    data = json.loads(_run(project, str(outside)).stdout)

    assert data["error"]["code"] == "target_outside_project"
    assert "outside the resolved Godot project" in data["error"]["message"]
    # The pair rides typed, as it does for `script validate` (#687).
    assert data["error"]["evidence"] == {
        "target_location": str(outside.resolve()),
        "project_root": str(project.resolve()),
    }


def test_absent_asset_is_invalid_params(tmp_path):
    project = _project(tmp_path)

    data = json.loads(_run(project, "res://nope.png").stdout)

    assert data["error"]["code"] == "invalid_params"
    assert "does not exist" in data["error"]["message"]


def test_relative_filesystem_path_is_project_relative(tmp_path):
    project = _project(tmp_path)

    data = json.loads(_run(project, "icon.png", "--dry-run").stdout)

    assert data["assets"][0]["path"] == "res://icon.png"


def test_no_assets_is_a_usage_error(tmp_path):
    project = _project(tmp_path)

    result = _run(project)

    assert result.exit_code == 2, result.stdout + result.stderr
    from tests.support import plain_text

    assert "ASSETS" in plain_text(result.stderr)


def test_schema_is_self_describing():
    result = runner_cli.invoke(app, ["resource", "import", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    # The published channel is the native import pass, not the operations.gd
    # sentinel pipeline this command never uses (#738 review).
    assert schema["kind"] == "import"


def test_result_model_validates_its_mode_fields():
    # The #732 lesson, applied at birth: a payload mixing the modes fails.
    import pydantic

    from gda.commands.resource import ResourceImportResult

    base = {
        "dry_run": True,
        "cache_root": "res://.godot",
        "engine_pass": False,
        "assets": [],
        "summary": {
            "requested": 0,
            "cached": 0,
            "missing": 0,
            "stale": 0,
            "invalid": 0,
            "imported": 0,
            "not_importable": 0,
            "failed": 0,
            "created_cache_owned": 0,
            "created_source_adjacent": 0,
        },
    }
    ResourceImportResult.model_validate(base)  # a coherent dry run passes
    with pytest.raises(pydantic.ValidationError):
        ResourceImportResult.model_validate(
            {
                **base,
                "created": [{"path": "res://x", "classification": "cache_owned"}],
            }
        )
    with pytest.raises(pydantic.ValidationError):
        ResourceImportResult.model_validate(
            {**base, "summary": {**base["summary"], "requested": 5}}
        )
