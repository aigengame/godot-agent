"""`gda project scan` — what the command decides, engine-free (#1073, #1255).

The scan is one `Editor context` launch, exercised through the shared step's launch
seam (``gda.core.steps.editor_context.launch``): what this file pins is the
command's own policy and the step's mechanics — one launch and no second engine,
rewrite detection on, error lines as data and bounded, the private editor root made
for the launch and removed after it, and the classifier's verdict as the scan's
failure. The real engine round trip (the classes equal the index on disk after a
rename, no plain autoload runs) is the e2e in ``test_e2e_project_scan``.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.project import ENGINE_ERROR_LINE_CAP
from gda.core.engine.launch import LaunchFailure, RunResult
from gda.core.engine.user_data import USER_DATA_ROOT_ENV
from gda.core.project.project_tree import ProjectTreeInventory
from gda.core.steps.editor_context import EDITOR_GD
from tests.support import (
    ENGINE_BANNER,
    error_sentinel,
    inject_runner,
    minimal_project,
    sentinel,
)

runner_cli = CliRunner()

_CLASSES = [{"name": "AttackComponent", "path": "res://attack_component.gd"}]

_SCAN_STDOUT = ENGINE_BANNER + sentinel({"classes": _CLASSES})


@pytest.fixture(autouse=True)
def _no_configured_root(monkeypatch):
    # The private root is the default under test; a host value would replace it.
    monkeypatch.delenv(USER_DATA_ROOT_ENV, raising=False)


def _run(project: Path, *args: str):
    return runner_cli.invoke(
        app, ["project", "scan", *args, "--project", str(project), "--json"]
    )


def _fake_editor(
    effects=lambda p: None,
    *,
    stdout=_SCAN_STDOUT,
    stderr="",
    exit_code=0,
    failure=None,
):
    calls = []

    def fake_launch(binary, args, **kwargs):
        root = kwargs["user_data_root"]
        calls.append(
            {
                "args": args,
                **kwargs,
                "root_existed": root is not None and root.is_dir(),
            }
        )
        effects(Path(args[args.index("--path") + 1]))
        return RunResult(
            stdout=stdout, stderr=stderr, exit_code=exit_code, launch_failure=failure
        )

    return calls, fake_launch


def _patch(monkeypatch, fake_launch):
    monkeypatch.setattr("gda.core.steps.editor_context.launch", fake_launch)
    # The sentinel runner is the second engine the scan no longer starts.
    return inject_runner(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))


def test_a_scan_is_one_editor_launch_that_reports_its_classes(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)

    def effects(p: Path) -> None:
        (p / ".godot").mkdir(exist_ok=True)
        (p / ".godot" / "global_script_class_cache.cfg").write_text("list=[]\n")
        (p / "attack_component.gd.uid").write_text("uid://x")

    calls, fake_launch = _fake_editor(effects)
    runner = _patch(monkeypatch, fake_launch)
    asked: list[dict] = []
    real_capture = ProjectTreeInventory.capture

    def recording_capture(project_arg, **kwargs):
        asked.append(kwargs)
        return real_capture(project_arg, **kwargs)

    monkeypatch.setattr(ProjectTreeInventory, "capture", recording_capture)

    result = _run(project)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [call["args"] for call in calls] == [
        [
            "-e",
            "--language",
            "en",
            "--path",
            str(project),
            "--script",
            str(EDITOR_GD),
            "--",
            "project-scan",
            "{}",
        ]
    ]
    assert calls[0]["timeout"] == 300.0
    assert calls[0]["timeout_label"] == "Godot editor"
    assert calls[0]["editor_dirs"] is True
    assert runner.calls == []
    # The report is `export run`'s, rewrites included.
    assert asked == [{"detect_rewrites": True}]
    data = json.loads(result.stdout)
    assert data["classes"] == _CLASSES
    created = {
        entry["path"]: entry["classification"]
        for entry in data["project_tree_mutations"]["created"]
    }
    assert created == {
        "res://.godot/global_script_class_cache.cfg": "cache_owned",
        "res://attack_component.gd.uid": "source_adjacent",
    }
    assert data["engine_errors"] == []
    assert data["engine_errors_truncated"] is False


@pytest.mark.parametrize(
    ("exit_code", "failure"),
    [(0, None), (1, None), (-1, LaunchFailure.TIMEOUT)],
    ids=["success", "failure", "timeout"],
)
def test_the_private_editor_root_exists_for_the_launch_and_is_removed_after_it(
    monkeypatch, tmp_path, exit_code, failure
):
    project = minimal_project(tmp_path)
    calls, fake_launch = _fake_editor(exit_code=exit_code, failure=failure)
    _patch(monkeypatch, fake_launch)

    _run(project)

    [call] = calls
    assert call["root_existed"] is True
    assert not call["user_data_root"].exists()


def test_a_configured_user_data_root_replaces_the_private_root_and_is_kept(
    monkeypatch, tmp_path
):
    # The launch places the editor's directories under the configured root itself
    # (`user_data_placement`); the step hands it no root of its own and removes
    # nothing.
    project = minimal_project(tmp_path)
    configured = tmp_path / "kept"
    monkeypatch.setenv(USER_DATA_ROOT_ENV, str(configured))
    calls, fake_launch = _fake_editor(lambda p: configured.mkdir())
    _patch(monkeypatch, fake_launch)

    result = _run(project)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls[0]["user_data_root"] is None
    assert calls[0]["editor_dirs"] is True
    assert configured.is_dir()


def test_a_private_root_that_cannot_be_made_is_refused_before_any_launch(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path)
    calls, fake_launch = _fake_editor()
    _patch(monkeypatch, fake_launch)

    def no_temp_dir(**kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("gda.core.steps.editor_context.tempfile.mkdtemp", no_temp_dir)

    result = _run(project)

    assert json.loads(result.stdout)["error"]["code"] == "user_data_unwritable"
    assert calls == []


def test_engine_error_lines_are_data_verbatim_without_warnings_or_at_lines(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path)
    stderr = (
        "WARNING: Not a PNG file\n"
        "     at: load_image (drivers/png/image_loader_png.cpp:58)\n"
        "ERROR: Error importing 'res://bad.png'.\n"
        "   at: _reimport_file (editor/file_system/editor_file_system.cpp:3240)\n"
        'SCRIPT ERROR: Parse Error: Expected closing ")".\n'
        "SHADER ERROR: Expected expression.\n"
        "an ERROR: that is not at the line start\n"
    )
    _, fake_launch = _fake_editor(stderr=stderr)
    _patch(monkeypatch, fake_launch)

    result = _run(project)

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["engine_errors"] == [
        "ERROR: Error importing 'res://bad.png'.",
        'SCRIPT ERROR: Parse Error: Expected closing ")".',
        "SHADER ERROR: Expected expression.",
    ]
    assert data["engine_errors_truncated"] is False


def test_engine_error_lines_are_capped_and_the_cut_is_flagged(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    lines = [f"ERROR: failure {n}" for n in range(ENGINE_ERROR_LINE_CAP + 1)]
    _, fake_launch = _fake_editor(stderr="\n".join(lines) + "\n")
    _patch(monkeypatch, fake_launch)

    data = json.loads(_run(project).stdout)

    assert data["engine_errors"] == lines[:ENGINE_ERROR_LINE_CAP]
    assert data["engine_errors_truncated"] is True


def test_exactly_the_cap_is_not_truncated(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    lines = [f"ERROR: failure {n}" for n in range(ENGINE_ERROR_LINE_CAP)]
    _, fake_launch = _fake_editor(stderr="\n".join(lines) + "\n")
    _patch(monkeypatch, fake_launch)

    data = json.loads(_run(project).stdout)

    assert len(data["engine_errors"]) == ENGINE_ERROR_LINE_CAP
    assert data["engine_errors_truncated"] is False


def test_a_clean_scan_forwards_its_stderr_warnings_included(monkeypatch, tmp_path):
    # ADR-0002's child-stderr rule: a success forwards the child's stream.
    # `engine_errors` keeps only the error lines, so a warning the editor printed
    # (an `@tool` autoload's `push_warning`) reaches the caller only this way.
    project = minimal_project(tmp_path)
    stderr = (
        "WARNING: tool autoload said this\nERROR: Error importing 'res://bad.png'.\n"
    )
    _, fake_launch = _fake_editor(stderr=stderr)
    _patch(monkeypatch, fake_launch)

    result = _run(project)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert stderr in result.stderr
    assert json.loads(result.stdout)["engine_errors"] == [
        "ERROR: Error importing 'res://bad.png'."
    ]


def test_a_non_zero_exit_with_no_reported_code_is_operation_failed(
    monkeypatch, tmp_path
):
    # The payload's single quit after a runtime error in the operation: the frame
    # aborts, the next one quits with the default non-zero code and no sentinel.
    project = minimal_project(tmp_path)
    _, fake_launch = _fake_editor(
        stdout=ENGINE_BANNER, stderr="SCRIPT ERROR: boom\n", exit_code=1
    )
    _patch(monkeypatch, fake_launch)

    result = _run(project)

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "operation_failed"
    # A failure carries the editor's stream; under --json it is forwarded.
    assert "SCRIPT ERROR: boom" in result.stderr


def test_a_code_the_payload_reports_is_the_scans_failure(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    _, fake_launch = _fake_editor(
        stdout=ENGINE_BANNER + error_sentinel("project_not_found", "none"),
        exit_code=1,
    )
    _patch(monkeypatch, fake_launch)

    result = _run(project)

    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_a_timed_out_scan_is_the_launch_timeout_failure(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    calls, fake_launch = _fake_editor(
        stdout="",
        stderr="WARNING: before the ceiling\n",
        exit_code=-1,
        failure=LaunchFailure.TIMEOUT,
    )
    _patch(monkeypatch, fake_launch)

    result = _run(project, "--timeout", "5")

    assert json.loads(result.stdout)["error"]["code"] == "launch_timeout"
    assert calls[0]["timeout"] == 5.0
    assert "WARNING: before the ceiling" in result.stderr


def test_a_scan_without_a_project_is_refused_before_any_launch(monkeypatch, tmp_path):
    calls, fake_launch = _fake_editor()
    _patch(monkeypatch, fake_launch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)

    result = runner_cli.invoke(app, ["project", "scan", "--json"])

    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"
    assert calls == []
