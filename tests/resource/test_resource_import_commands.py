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
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.project_tree import ProjectTreeInventory
from gda.runner import LaunchFailure, RunResult, TimeoutBound
from tests.resource.import_artifacts import (
    cached_asset,
    icon_project,
    receipt_path,
    sidecar,
)
from tests.support import minimal_project, unlistable

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
    # What this command ASKS the `Project tree inventory` for is the one
    # consumer-specific gate #985 allows, and nothing else pins it: with
    # `detect_rewrites=True` the result is identical — `modified` is computed and
    # discarded — and only the cost moves, by 3.7x on an 11k-file tree (PR #989
    # review round 1). So record the kwargs.
    asked: list[dict] = []
    real_capture = ProjectTreeInventory.capture

    def recording_capture(project_arg, **kwargs):
        asked.append(kwargs)
        return real_capture(project_arg, **kwargs)

    monkeypatch.setattr(ProjectTreeInventory, "capture", recording_capture)

    result = _run(project, "res://icon.png")

    # No artifact (the pass writes none) and no rewrite detection (`created` is
    # the whole question, so the capture hashes nothing).
    assert asked == [{"detect_rewrites": False}], asked

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


def test_a_file_created_under_a_directory_link_is_reported(monkeypatch, tmp_path):
    # The one behaviour change of #985. This command used to walk the tree with
    # `Path.rglob("*")`, which does NOT descend a directory symlink on Python
    # 3.13, so a sidecar the pass wrote into a linked-in shared library was
    # invisible: the same pass reported it to `export run` (whose walk follows the
    # link, PR #981 round 3) and not here. The `Project tree inventory` now
    # answers both, so the file is reported under the spelling the walk reached it
    # by — the res:// path the engine names it by too.
    project = icon_project(tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "sprite.png").write_bytes(b"\x89PNG other bytes")
    (project / "assets").symlink_to(shared, target_is_directory=True)

    def effects(p: Path) -> None:
        cached_asset(
            p,
            "icon.png",
            ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
        )
        (shared / "sprite.png.import").write_text("[remap]\n", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    created = {f["path"]: f["classification"] for f in data["created"]}
    assert created["res://assets/sprite.png.import"] == "source_adjacent"
    assert (shared / "sprite.png.import").is_file()
    assert data["summary"]["created_source_adjacent"] == 2


def _locked_icon_project(tmp_path: Path) -> "tuple[Path, Path]":
    """An importable project holding one unreadable directory and a link to it."""
    project = icon_project(tmp_path)
    locked = project / "locked"
    locked.mkdir()
    (locked / "secret.tres").write_text("old", encoding="utf-8")
    (project / "alias").symlink_to(locked, target_is_directory=True)
    return project, locked


def _icon_effects(p: Path) -> None:
    """What the pass writes for res://icon.png."""
    cached_asset(
        p, "icon.png", ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex"
    )


def test_an_unreadable_subtree_is_counted_once_beside_the_created_list(
    monkeypatch, tmp_path
):
    # #990: `created` promised an exhaustive list and the result carried no way to
    # check it — the walk's own count was computed and discarded. It is published
    # now, and it counts the INODE: the locked directory that `alias` reaches a
    # second time is one entry, not two (the count read 2 before this issue). The
    # created files the walk COULD see are still listed.
    project, locked = _locked_icon_project(tmp_path)
    calls, fake_launch = _fake_pass(project, _icon_effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    if not unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        result = _run(project, "res://icon.png")
    finally:
        locked.chmod(0o755)

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["skipped"] == 1
    assert data["assets"][0]["status"] == "imported"
    assert "res://icon.png.import" in {f["path"] for f in data["created"]}
    # Nothing under either spelling of the unreadable directory is claimed.
    assert not [
        f
        for f in data["created"]
        if f["path"].startswith(("res://locked/", "res://alias/"))
    ]


def test_a_complete_inventory_publishes_a_zero_count(monkeypatch, tmp_path):
    # The common case, and the one that makes the field worth reading: a tree the
    # walk saw whole reports 0, so a caller branches on the number rather than on
    # the absence of a key.
    project = icon_project(tmp_path)
    calls, fake_launch = _fake_pass(project, _icon_effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["skipped"] == 0


def test_the_render_names_the_unreadable_count_beside_the_created_line(
    monkeypatch, tmp_path
):
    # The count is not a JSON-only key: a record that could not read part of the
    # tree must not print as a complete one, which is `export run`'s rule for the
    # same fact. A complete record prints no such phrase at all.
    project, locked = _locked_icon_project(tmp_path)
    calls, fake_launch = _fake_pass(project, _icon_effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    if not unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        partial = runner_cli.invoke(
            app, ["resource", "import", "res://icon.png", "--project", str(project)]
        )
    finally:
        locked.chmod(0o755)

    assert partial.exit_code == 0, partial.stdout + partial.stderr
    created_line = next(
        line for line in partial.stdout.splitlines() if line.startswith("  created:")
    )
    assert created_line.endswith(", 1 unreadable"), created_line

    whole = icon_project(tmp_path / "whole")
    calls, fake_launch = _fake_pass(whole, _icon_effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    clean = runner_cli.invoke(
        app, ["resource", "import", "res://icon.png", "--project", str(whole)]
    )

    assert clean.exit_code == 0, clean.stdout + clean.stderr
    assert "unreadable" not in clean.stdout


def test_a_symlink_cycle_under_the_project_terminates(monkeypatch, tmp_path):
    # The rule that makes following a link safe: a directory is walked once by
    # filesystem identity, so `sub/loop -> ..` is not re-entered and the
    # accounting ends by rule rather than at the OS path limit. Run on a thread
    # with a deadline, so a regression reads RED instead of wedging the suite.
    project = icon_project(tmp_path)
    (project / "sub").mkdir()
    (project / "sub" / "loop").symlink_to("..", target_is_directory=True)

    def effects(p: Path) -> None:
        cached_asset(
            p,
            "icon.png",
            ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
        )
        (p / "sub" / "asset.tres.import").write_text("[remap]\n", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    outcome: list = []
    worker = threading.Thread(
        target=lambda: outcome.append(_run(project, "res://icon.png")), daemon=True
    )

    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "the accounting did not terminate on a cycle"

    data = json.loads(outcome[0].stdout)
    assert "res://sub/asset.tres.import" in {f["path"] for f in data["created"]}


def test_a_top_level_git_directory_is_still_excluded(monkeypatch, tmp_path):
    # The exclusion the old walker made on its own is now the inventory's rule 5,
    # and it did not change: the engine writes nothing to `.git`, and a checkout's
    # object database would swamp a list about the project's own files.
    project = icon_project(tmp_path)
    (project / ".git").mkdir()
    (project / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    def effects(p: Path) -> None:
        cached_asset(
            p,
            "icon.png",
            ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
        )
        objects = p / ".git" / "objects" / "ab"
        objects.mkdir(parents=True)
        (objects / "cdef").write_text("object", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert not [f for f in data["created"] if f["path"].startswith("res://.git/")]


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
    # `skipped` joins that field set on the same terms as `created` (#990): a dry
    # run walks no tree, so it can report nothing the walk could not see.
    with pytest.raises(pydantic.ValidationError):
        ResourceImportResult.model_validate({**base, "skipped": 1})


def test_a_real_run_may_report_entries_the_walk_could_not_see():
    # The other half of that rule, and the reason the field exists: a real run
    # carries whatever count the inventory settled, so a caller can tell a partial
    # `created` list from a complete one (#990).
    from gda.commands.resource import ResourceImportResult

    real = {
        "dry_run": False,
        "cache_root": "res://.godot",
        "engine_pass": True,
        "assets": [],
        "skipped": 2,
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

    assert ResourceImportResult.model_validate(real).skipped == 2
    # And the field is additive: a payload without it reports a whole tree.
    without = {k: v for k, v in real.items() if k != "skipped"}
    assert ResourceImportResult.model_validate(without).skipped == 0


def test_the_render_prints_the_created_line_for_the_count_alone():
    # The other half of the render rule, on the state that isolates it: a pass
    # can create nothing and still leave part of the tree unread, so the
    # disclosure must print without a created file to hang it on. A gate on
    # `created` alone silences it with the whole suite green (PR #994 review).
    from gda.commands.resource import ResourceImportResult, render_resource_import

    outcome = ResourceImportResult.model_validate(
        {
            "dry_run": False,
            "cache_root": "res://.godot",
            "engine_pass": True,
            "assets": [],
            "skipped": 1,
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
    )

    assert outcome.created == []
    assert render_resource_import(outcome).splitlines()[-1] == (
        "  created: 0 cache-owned, 0 source-adjacent, 1 unreadable"
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


def test_each_asset_takes_only_the_passs_lines_that_name_it(monkeypatch, tmp_path):
    # PR #937 review round 2: `engine_output` follows the PASS, never the
    # reason. Round 1 gated it on a settlement-decided reason, assuming the
    # engine says nothing about an asset it skips — false on 4.6.3, where an
    # unparsable sidecar draws two `ResourceFormatImporter::load` errors naming
    # it before the skip. The stderr below is that real shape (reproduced
    # against the engine), and the rule is the literal one: each asset takes
    # the lines that NAME it, and only those.
    project = icon_project(tmp_path)
    (project / "bad.png").write_bytes(b"\x89PNG bad")
    (project / "bad.png.import").write_text(
        '[remap]\n\nimporter="texture"\nuid="uid://test"\n\n[deps]\n\n'
        'source_file="res://bad.png"\ndest_files=[oops]\n',
        encoding="utf-8",
    )
    bad_lines = [
        "ERROR: ResourceFormatImporter::load - 'res://bad.png.import:8' error "
        "'Unexpected identifier 'oops''.",
        "ERROR: ResourceFormatImporter::load - 'res://bad.png.import:8' error "
        "'Unexpected identifier 'oops''.",
    ]
    stderr = (
        f"{bad_lines[0]}\n"
        "   at: _test_for_reimport (editor/file_system/editor_file_system.cpp:620)\n"
        f"{bad_lines[1]}\n"
        "   at: _get_import_dest_paths (editor/file_system/editor_file_system.cpp:772)\n"
        "ERROR: Error importing 'res://fresh.png'.\n"
        "   at: _reimport_file (editor/file_system/editor_file_system.cpp:3065)\n"
    )

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, "fresh.png", ".godot/imported/never-written.ctex")
        return RunResult(stdout="", stderr=stderr, exit_code=0)

    (project / "fresh.png").write_bytes(b"\x89PNG fresh")
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://bad.png", "res://fresh.png").stdout)
    by_path = {a["path"]: a for a in data["assets"]}

    # The asset the engine SKIPPED still keeps its pre-pass reason AND the
    # engine's two lines about it. The `at:` continuations name a source file,
    # not the asset, so they stay out.
    assert by_path["res://bad.png"]["status"] == "failed"
    assert by_path["res://bad.png"]["reason"] == "sidecar_unparsable"
    assert by_path["res://bad.png"]["engine_output"] == bad_lines
    assert by_path["res://bad.png"]["engine_output_truncated"] is False
    # The sibling that spent the pass takes its own line, and only its own.
    assert by_path["res://fresh.png"]["reason"] == "dest_missing_after_pass"
    assert by_path["res://fresh.png"]["engine_output"] == [
        "ERROR: Error importing 'res://fresh.png'."
    ]

    # And with no pass to attribute anything to, both are empty: `bad.png`
    # alone is invalid, so nothing runs.
    calls, no_pass = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", no_pass)
    alone = json.loads(_run(project, "res://bad.png").stdout)["assets"][0]
    assert calls == []
    assert alone["status"] == "failed"
    assert alone["reason"] == "sidecar_unparsable"
    assert alone["engine_output"] == []


def test_the_remedy_footnote_follows_the_artifact_reason_into_a_real_run(
    monkeypatch, tmp_path
):
    # PR #937 review round 2 [P3]: the "delete the .import sidecar" hint was
    # keyed on the `invalid` STATE, which a real run settles away — so the run
    # that most needs the remedy printed none. It follows the artifact reason
    # now, and `dest_missing_after_pass` still gets no sidecar advice.
    project = icon_project(tmp_path)
    sidecar(project, "icon.png", None, valid=False)

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)
    settled = runner_cli.invoke(
        app, ["resource", "import", "res://icon.png", "--project", str(project)]
    )

    assert settled.exit_code == 0, settled.stdout + settled.stderr
    assert "failed" in settled.stdout
    assert "delete the asset's .import sidecar" in settled.stdout

    # A pass-decided failure is not a sidecar-syntax problem; no such advice.
    project2 = icon_project(tmp_path / "second")

    def effects(p):
        sidecar(p, "icon.png", ".godot/imported/never-written.ctex")

    _, leaves_dest = _fake_pass(project2, effects)
    monkeypatch.setattr("gda.commands.resource.launch", leaves_dest)
    passed = runner_cli.invoke(
        app, ["resource", "import", "res://icon.png", "--project", str(project2)]
    )

    assert "dest_missing_after_pass" in passed.stdout
    assert "delete the asset's .import sidecar" not in passed.stdout


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


def test_engine_output_names_the_asset_as_a_whole_token(monkeypatch, tmp_path):
    # Fourth review of PR #937: where a path ENDS is decided by how the engine
    # printed it, not by the character after the asset's name — the third
    # review's lookahead stopped at punctuation a legal neighbouring path can
    # carry inside it (and the fourth review's tokenizer cut a quoted path at
    # EITHER quote character, missing a path that carries one — see the next
    # test). Every line in `ours` is an engine form measured on the
    # 4.6 sources (message literal and quoting), with the asset's path where
    # that source puts it; every neighbour is a legal path that EXTENDS ours.
    project = icon_project(tmp_path)
    ours = [
        # editor/file_system/editor_file_system.cpp — 'Error importing '%s'.'
        "ERROR: Error importing 'res://icon.png'.",
        # core/io/image_loader.cpp — "Error loading image: '%s'."
        "ERROR: Error loading image: 'res://icon.png'.",
        # core/io/resource_format_binary.cpp — "Cannot open file '%s'."
        "ERROR: Cannot open file 'res://icon.png'.",
        # editor sidecar record — 'ResourceFormatImporter::load - '%s.import:%d' …'
        "ERROR: ResourceFormatImporter::load - 'res://icon.png.import:8' error 'x'.",
        # core/io/resource_importer.cpp — bare path, ".import:%d error:"
        "ERROR: ResourceFormatImporter::load - res://icon.png.import:8 error: x.",
        "ERROR: Cannot open import file 'res://icon.png.import'.",
        # core/io/resource_loader.cpp — bare path, sentence-final period
        "ERROR: Failed loading resource: res://icon.png. The file doesn't seem to exist.",
        "ERROR: Failed loading resource: res://icon.png.",
        # bare path followed by " (expected type: …)"
        "ERROR: Resource file not found: res://icon.png (expected type: Texture2D)",
        # double-quoted, the UID warnings
        'WARNING: Missing .uid file for path "res://icon.png". The file was re-created from cache.',
    ]
    neighbours = [
        # prefix neighbours (third review) …
        "ERROR: Error importing 'res://icon.png2'.",
        "ERROR: Error importing 'res://icon.png.backup'.",
        "ERROR: ResourceFormatImporter::load - 'res://icon.png2.import:3' error 'y'.",
        "ERROR: Failed loading resource: res://icon.png2.",
        # … and the neighbours whose paths carry the very separators the old
        # lookahead stopped at (fourth review): a sidecar-looking suffix, a
        # space, a bracket, a second extension.
        "ERROR: Error importing 'res://icon.png.import-backup'.",
        "ERROR: Error importing 'res://icon.png copy'.",
        "ERROR: Error importing 'res://icon.png]backup'.",
        "ERROR: Resource file not found: res://icon.png.png (expected type: Texture2D)",
        'WARNING: Missing .uid file for path "res://icon.png copy". The file was re-created from cache.',
    ]
    # A neighbour flood beyond the cap: none of it is the asset's, so none of it
    # can spend the asset's cap or mark it truncated.
    flood = [f"ERROR: Error importing 'res://icon.png copy {i}'." for i in range(25)]

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, "icon.png", ".godot/imported/never-written.ctex")
        stderr = "\n".join(neighbours + flood + ours) + "\n"
        return RunResult(stdout="", stderr=stderr, exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, "res://icon.png").stdout)["assets"][0]

    assert asset["engine_output"] == ours
    assert asset["engine_output_truncated"] is False


@pytest.mark.parametrize(
    "name",
    ['icon"hero.png', "it's.png", "it's\"both.png"],
    ids=["other-quote", "same-quote", "both-quotes"],
)
def test_engine_output_names_an_asset_whose_path_carries_a_quote(
    monkeypatch, tmp_path, name
):
    # Fifth review of PR #937: `res://icon"hero.png` is a legal asset path and the
    # real engine prints `Error importing 'res://icon"hero.png'.` for it; the
    # tokenizer's `[^'"]*` cut the token at the inner quote and reported no
    # evidence. gda knows the path it is looking for, so it finds THAT spelling
    # and checks the engine's delimiters around it — the quote that opens the
    # path closes it, whatever the path holds in between. The neighbour that
    # extends this path stays out, as before.
    project = icon_project(tmp_path)
    (project / name).write_bytes((project / "icon.png").read_bytes())
    res_path = f"res://{name}"
    ours = [
        f"ERROR: Error importing '{res_path}'.",
        f"ERROR: Error loading image: '{res_path}'.",
        f"ERROR: ResourceFormatImporter::load - '{res_path}.import:8' error 'x'.",
        f"ERROR: Failed loading resource: {res_path}.",
    ]
    neighbours = [
        f"ERROR: Error importing '{res_path}2'.",
        f"ERROR: Error importing '{res_path} copy'.",
        "ERROR: Error importing 'res://icon.png'.",
    ]

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        sidecar(project, name, ".godot/imported/never-written.ctex")
        stderr = "\n".join(neighbours + ours) + "\n"
        return RunResult(stdout="", stderr=stderr, exit_code=0)

    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    asset = json.loads(_run(project, res_path).stdout)["assets"][0]

    assert asset["engine_output"] == ours
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


# --- an empty --godot, where the command resolves a binary (#1012) -------------


def test_an_empty_godot_is_binary_not_found_before_the_pass(monkeypatch, tmp_path):
    # The asset has no import cache, so the pass must run and the binary is
    # resolved. An empty `--godot ""` cannot be: it is the shared binary_not_found
    # envelope (exit 127), not a ValueError traceback, and nothing is launched.
    project = icon_project(tmp_path)
    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    result = _run(project, "res://icon.png", "--godot", "")

    assert result.exit_code == 127, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "error": {
            "category": "environment",
            "code": "binary_not_found",
            "message": (
                "Godot binary could not be resolved: "
                "explicit Godot binary path is empty"
            ),
            "diagnostics": "",
        }
    }
    assert calls == []


def test_a_dry_run_with_an_empty_godot_still_succeeds(tmp_path):
    # A dry run resolves no binary, so an empty `--godot ""` does not refuse it:
    # the command resolves where it always did, not earlier.
    project = icon_project(tmp_path)

    result = _run(project, "res://icon.png", "--dry-run", "--godot", "")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["engine_pass"] is True


def test_an_all_cached_run_with_an_empty_godot_still_succeeds(monkeypatch, tmp_path):
    # All cached: no pass, so no binary is resolved and an empty `--godot ""`
    # does not refuse the run either.
    project = icon_project(tmp_path)
    cached_asset(
        project,
        "icon.png",
        ".godot/imported/icon.png-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.ctex",
    )
    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    result = _run(project, "res://icon.png", "--godot", "")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["engine_pass"] is False
    assert calls == []
