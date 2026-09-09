"""`gda resource import` — the scoped import surface, engine-free (#668).

What the COMMAND decides, driven through the CLI: whether the pass runs, the
before/after accounting, the settlement vocabulary, the request refusals, and
the render. The cache-verdict logic is pure Python (sidecar + dest-file checks),
so the dry-run and all-cached paths run with NO fake at all against a real temp
project tree. The engine pass is exercised through the launch seam
(``gda.commands.resource.launch``, the scene/script channels' pattern): a fake
launch simulates the pass's file effects, so the re-verdict, the before/after
accounting, and the classification are covered without an engine. The real
engine round trip (GDA-DF-010's preload failure healed by the import) is the
e2e in ``test_e2e_resource_import``.

The verdicts themselves belong to ``gda.import_evidence`` since #741 and are
tested against it directly in ``test_import_evidence``; what stays here is one
dry-run smoke per evidence state, so the wire ABI keeps its own cover.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import LaunchFailure, RunResult, TimeoutBound
from tests.resource.import_artifacts import (
    cached_asset,
    icon_project,
    receipt_path,
    sidecar,
)
from tests.support import minimal_project

runner_cli = CliRunner()


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
    project = icon_project(tmp_path)
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
            # The #853 keys ride on EVERY asset, empty where there is nothing to
            # explain — the shape `sidecar` already set for this result.
            "reason": None,
            "detail": None,
            "engine_output": [],
            "engine_output_truncated": False,
        }
    ]
    assert data["predicted_source_adjacent"] == ["res://icon.png.import"]
    assert data["created"] == []
    assert data["summary"]["missing"] == 1
    assert data["cache_root"] == "res://.godot"
    # The AC: a dry run writes nothing at all.
    assert _tree(project) == before


def test_dry_run_cached_when_sidecar_dest_files_exist(tmp_path):
    project = icon_project(tmp_path)
    dest = ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex"
    cached_asset(project, "icon.png", dest)

    result = _run(project, "res://icon.png", "--dry-run")

    data = json.loads(result.stdout)
    assert data["assets"][0]["status"] == "cached"
    assert data["assets"][0]["sidecar"] == "res://icon.png.import"
    assert data["assets"][0]["dest_files"] == [f"res://{dest}"]
    assert data["engine_pass"] is False
    assert data["predicted_source_adjacent"] == []


def test_dry_run_stale_when_a_dest_file_is_absent(tmp_path):
    project = icon_project(tmp_path)
    sidecar(
        project,
        "icon.png",
        ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
    )

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "stale"
    # It HAS a sidecar, so no sidecar-creation prediction for it.
    assert data["predicted_source_adjacent"] == []
    assert data["engine_pass"] is True


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
    project = icon_project(tmp_path)

    def effects(p: Path) -> None:
        cached_asset(
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
    project = icon_project(tmp_path)
    cached_asset(
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
    project = icon_project(tmp_path)
    (project / "script.gd").write_text("extends Node\n", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://script.gd").stdout)

    assert data["assets"][0]["status"] == "not_importable"
    assert data["summary"]["not_importable"] == 1


def test_pass_that_leaves_dest_missing_is_failed(monkeypatch, tmp_path):
    project = icon_project(tmp_path)

    def effects(p: Path) -> None:
        sidecar(p, "icon.png", ".godot/imported/never-written.ctex")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["assets"][0]["status"] == "failed"
    assert data["summary"]["failed"] == 1


def test_launch_failures_classify_through_the_shared_prefix(monkeypatch, tmp_path):
    project = icon_project(tmp_path)

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
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    sidecar(project, "icon.png", None, valid=False)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["assets"][0]["status"] == "failed"
    assert data["summary"]["failed"] == 1
    # The engine skips a previously failed import, so gda spends NO pass on it.
    assert calls == []


def test_malformed_receipt_is_invalid_and_spends_no_pass(monkeypatch, tmp_path):
    # #738 re-review 5 [P1]: the engine parses the receipt with VariantParser
    # and treats a parse error as the same deliberate skip as valid=false —
    # "skip and let user attempt manual reimport to avoid reimport loop",
    # never a re-import. gda must not spend a pass the engine would not run,
    # and must not settle the asset failed AFTER spending one.
    project = icon_project(tmp_path)
    dest = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"
    cached_asset(project, "icon.png", dest)
    receipt_path(project, "icon.png").write_text("source_md5=[\n", encoding="utf-8")

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


def test_human_dry_run_renders_the_project_wide_prediction(tmp_path):
    # #738 review [P2]: the default (non-JSON) dry run must carry the revised
    # contract's project-wide decidable inventory, not only the JSON form.
    project = icon_project(tmp_path)
    (project / "other.png").write_bytes(b"\x89PNG other")
    sidecar(project, "other.png", ".godot/imported/other.png-" + "a" * 32 + ".ctex")

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


def test_relative_project_with_symlinked_asset_is_structured(tmp_path, monkeypatch):
    # #738 re-review 2 [P1]: a RELATIVE --project plus a symlinked-in asset
    # used to compare a relative candidate against an absolute project and
    # escape as a bare ValueError traceback. Both sides now share one
    # coordinate system; the verdict is structured either way.
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)
    nested = minimal_project(project / "vendor")
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
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)

    for spelling in ("res://", "res://foo/..", ".", "foo/.."):
        data = json.loads(_run(project, spelling, "--dry-run").stdout)
        assert data["error"]["code"] == "invalid_params", spelling
        assert "asset res:// does not exist" in data["error"]["message"], spelling


def test_symlinked_in_asset_is_accepted_like_the_engine_walks_it(tmp_path):
    # The shared ADR-0006 gate's established symlink treatment (#738 review):
    # a file linked INTO the project tree is addressable through the project's
    # res:// namespace — the engine walks the link — so it is accepted, for
    # both input forms, exactly as `script run` accepts it.
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)
    (project / "other.png").write_bytes(b"\x89PNG other")
    sidecar(
        project,
        "other.png",
        ".godot/imported/other.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
    )
    (project / "bad.png").write_bytes(b"\x89PNG bad")
    sidecar(project, "bad.png", None, valid=False)

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["path"] == "res://icon.png"
    assert data["pass_will_also_import"] == ["res://other.png"]


# --- request validation --------------------------------------------------------


def test_asset_outside_the_project_is_the_shared_containment_refusal(tmp_path):
    # #763: one condition, one code. This used to be a generic `invalid_params`
    # while `script validate` reported `project_not_found` and `script run`
    # `invalid_path` for the very same "this target is not in the resolved
    # project" — three answers an agent could not branch on once.
    project = icon_project(tmp_path)
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
    project = icon_project(tmp_path)

    data = json.loads(_run(project, "res://nope.png").stdout)

    assert data["error"]["code"] == "invalid_params"
    assert "does not exist" in data["error"]["message"]


def test_relative_filesystem_path_is_project_relative(tmp_path):
    project = icon_project(tmp_path)

    data = json.loads(_run(project, "icon.png", "--dry-run").stdout)

    assert data["assets"][0]["path"] == "res://icon.png"


def test_no_assets_is_a_usage_error(tmp_path):
    project = icon_project(tmp_path)

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


# --- why an asset is invalid or failed (#853) ----------------------------------


def test_an_invalid_reason_survives_the_settlement_unchanged(monkeypatch, tmp_path):
    # The AC's first pair, both halves of one fixture: `--dry-run` reports the
    # evidence state WITH the check that decided it, and a real run — which
    # spends no pass on an invalid request — settles to `failed` still naming
    # that same check. PIPE-DF-191 got the settlement with nothing on it.
    #
    # The fixture is the reason spelling that also carries a DETAIL (PR #937
    # review round 1): a sidecar that decodes but whose `dest_files=` list does
    # not parse, so the offending line has to survive the settlement beside the
    # reason. With undecodable bytes there was no detail to lose.
    project = icon_project(tmp_path)
    (project / "icon.png.import").write_text(
        '[remap]\n\nimporter="texture"\nuid="uid://test"\n\n[deps]\n\n'
        'source_file="res://icon.png"\ndest_files=[oops]\n',
        encoding="utf-8",
    )

    dry = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)["assets"][0]
    assert dry["status"] == "invalid"
    assert dry["reason"] == "sidecar_unparsable"
    assert dry["detail"] == "dest_files=[oops]"
    assert dry["sidecar"] == "res://icon.png.import"

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    real = json.loads(_run(project, "res://icon.png").stdout)["assets"][0]

    assert calls == []
    assert real["status"] == "failed"
    assert real["reason"] == "sidecar_unparsable"
    assert real["detail"] == "dest_files=[oops]"
    # No pass ran, so there is no engine output to attribute to it.
    assert real["engine_output"] == []
    assert real["engine_output_truncated"] is False


def test_a_skipped_invalid_asset_takes_no_lines_from_a_siblings_pass(
    monkeypatch, tmp_path
):
    # PR #937 review round 1 [P2]: the pass runs for the MISSING sibling, and
    # the engine deliberately skips the invalid one — so a stderr line naming
    # the skipped asset belongs to the run, not to it. Attaching the pass's
    # output to every settled `failed` contradicted the field's own
    # description, and no test noticed.
    project = icon_project(tmp_path)
    (project / "bad.png").write_bytes(b"\x89PNG bad")
    sidecar(project, "bad.png", None, valid=False)
    stderr = (
        "ERROR: Error importing 'res://bad.png'.\n"
        "ERROR: Error importing 'res://icon.png'.\n"
    )

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, "icon.png", ".godot/imported/never-written.ctex")
        return RunResult(stdout="", stderr=stderr, exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png", "res://bad.png").stdout)
    by_path = {a["path"]: a for a in data["assets"]}

    # The skipped one keeps its pre-pass check and takes none of the output.
    assert by_path["res://bad.png"]["status"] == "failed"
    assert by_path["res://bad.png"]["reason"] == "sidecar_marked_invalid"
    assert by_path["res://bad.png"]["engine_output"] == []
    assert by_path["res://bad.png"]["engine_output_truncated"] is False
    # The asset the pass DID run over still gets its own line.
    assert by_path["res://icon.png"]["reason"] == "dest_missing_after_pass"
    assert by_path["res://icon.png"]["engine_output"] == [
        "ERROR: Error importing 'res://icon.png'."
    ]


def test_a_pass_that_leaves_the_asset_uncached_reports_the_settlement_reason(
    monkeypatch, tmp_path
):
    # The other half of the enum, and the one only the COMMAND can decide: no
    # pre-pass check refused this asset — the pass ran and the destination is
    # still not there. The engine's own lines for the asset ride with it.
    project = icon_project(tmp_path)
    stderr = (
        "ERROR: Error loading image: 'res://icon.png'.\n"
        "   at: load_image (core/io/image_loader.cpp:100)\n"
        "ERROR: Error importing 'res://icon.png'.\n"
        "ERROR: Error importing 'res://other.png'.\n"
    )

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, "icon.png", ".godot/imported/never-written.ctex")
        return RunResult(stdout="", stderr=stderr, exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, "res://icon.png").stdout)["assets"][0]

    assert asset["status"] == "failed"
    assert asset["reason"] == "dest_missing_after_pass"
    assert asset["detail"] is None
    # Only the lines that NAME this asset: the neighbour's error and the
    # engine's `at:` continuation lines are not this asset's evidence.
    assert asset["engine_output"] == [
        "ERROR: Error loading image: 'res://icon.png'.",
        "ERROR: Error importing 'res://icon.png'.",
    ]
    assert asset["engine_output_truncated"] is False


def test_engine_output_is_bounded_to_twenty_lines(monkeypatch, tmp_path):
    # #665's bounded-stream rule, without a spill file: a pass that floods the
    # log must not turn one asset's verdict into an unbounded payload, and the
    # caller is TOLD the cut happened.
    project = icon_project(tmp_path)
    lines = [f"ERROR: {i} 'res://icon.png' failed." for i in range(25)]

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, "icon.png", ".godot/imported/never-written.ctex")
        return RunResult(stdout="", stderr="\n".join(lines) + "\n", exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, "res://icon.png").stdout)["assets"][0]

    assert asset["engine_output"] == lines[:20]
    assert asset["engine_output_truncated"] is True


def test_exactly_twenty_matching_lines_are_not_reported_truncated(
    monkeypatch, tmp_path
):
    # The boundary: the flag says lines were DROPPED, not that the cap was met.
    project = icon_project(tmp_path)
    lines = [f"ERROR: {i} 'res://icon.png' failed." for i in range(20)]

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, "icon.png", ".godot/imported/never-written.ctex")
        return RunResult(stdout="", stderr="\n".join(lines) + "\n", exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, "res://icon.png").stdout)["assets"][0]

    assert asset["engine_output"] == lines
    assert asset["engine_output_truncated"] is False


def test_a_settled_asset_the_pass_repaired_carries_no_reason(monkeypatch, tmp_path):
    # The reason explains a verdict, so a verdict that needs no explanation
    # must not carry a stale one — an `imported` asset re-read after the pass
    # answers `cached`, and the settlement must not copy the pass's noise onto
    # it either.
    project = icon_project(tmp_path)

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        cached_asset(project, "icon.png", ".godot/imported/icon.png-" + "a" * 32)
        return RunResult(
            stdout="", stderr="ERROR: noise about 'res://icon.png'.\n", exit_code=0
        )

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, "res://icon.png").stdout)["assets"][0]

    assert asset["status"] == "imported"
    assert asset["reason"] is None
    assert asset["detail"] is None
    assert asset["engine_output"] == []


def test_a_not_importable_asset_carries_no_reason(monkeypatch, tmp_path):
    # The engine deciding a type needs no import is not a failure at all.
    project = icon_project(tmp_path)
    (project / "script.gd").write_text("extends Node\n", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, "res://script.gd").stdout)["assets"][0]

    assert asset["status"] == "not_importable"
    assert asset["reason"] is None


def test_the_wire_enum_covers_every_reason_the_adapter_can_decide():
    # The two enums are one contract split across the commands -> core seam: a
    # reason the adapter learns to decide but the wire model cannot spell would
    # fail validation at the worst moment, on the failure path. The wire adds
    # exactly one value of its own, the settlement's.
    from typing import get_args

    from gda.commands.resource import AssetReason
    from gda.import_evidence import EvidenceReason

    assert set(get_args(EvidenceReason)) < set(get_args(AssetReason))
    assert set(get_args(AssetReason)) - set(get_args(EvidenceReason)) == {
        "dest_missing_after_pass"
    }


def test_a_dry_run_never_reports_engine_output():
    # The mode invariant, in the model that already validates the mode's field
    # set (#732): a dry run runs no pass, so no asset can carry the pass's lines.
    import pydantic

    from gda.commands.resource import ResourceImportResult

    payload = {
        "dry_run": True,
        "cache_root": "res://.godot",
        "engine_pass": False,
        "assets": [
            {
                "path": "res://icon.png",
                "status": "invalid",
                "reason": "sidecar_marked_invalid",
                "engine_output": ["ERROR: something about 'res://icon.png'."],
            }
        ],
        "summary": {
            "requested": 1,
            "cached": 0,
            "missing": 0,
            "stale": 0,
            "invalid": 1,
            "imported": 0,
            "not_importable": 0,
            "failed": 0,
            "created_cache_owned": 0,
            "created_source_adjacent": 0,
        },
    }
    with pytest.raises(pydantic.ValidationError):
        ResourceImportResult.model_validate(payload)


def test_the_human_render_shows_the_reason_on_the_assets_line(monkeypatch, tmp_path):
    # AC: the reason is not a JSON-only key. The default rendering names it
    # beside the verdict, with the offending line or path when there is one.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", ".godot/imported/icon.png-" + "a" * 32 + ".ctex")
    receipt_path(project, "icon.png").write_text("source_md5=[\n", encoding="utf-8")

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
    line = next(line for line in result.stdout.splitlines() if "res://icon.png" in line)
    assert "invalid" in line
    assert "receipt_unsupported" in line
    assert ".md5" in line
