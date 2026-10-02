"""`gda project scan` — what the command decides, engine-free (#1073).

The engine pass is exercised through the launch seam
(``gda.commands.project.launch``, `resource import`'s pattern) and the
class-list read through the runner seam: what this file pins is the command's
own policy — always one pass, rewrite detection on, error lines as data and
bounded, a failed pass or read as a failure. The real engine round trip (a
never-opened project's class types compile after a scan) is the e2e in
``test_e2e_project_scan``.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.project import ENGINE_ERROR_LINE_CAP
from gda.project_tree import ProjectTreeInventory
from gda.runner import LaunchFailure, RunResult
from tests.support import (
    ENGINE_BANNER,
    error_sentinel,
    inject_runner,
    minimal_project,
    sentinel,
)

runner_cli = CliRunner()

_CLASSES = [{"name": "AttackComponent", "path": "res://attack_component.gd"}]


def _run(project: Path, *args: str):
    return runner_cli.invoke(
        app, ["project", "scan", *args, "--project", str(project), "--json"]
    )


def _fake_pass(effects=lambda p: None, *, stderr="", exit_code=0, failure=None):
    calls = []

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        calls.append({"args": args, "cwd": cwd, "timeout": timeout})
        project = Path(args[args.index("--path") + 1])
        effects(project)
        return RunResult(
            stdout="", stderr=stderr, exit_code=exit_code, launch_failure=failure
        )

    return calls, fake_launch


def _classes_read(monkeypatch, classes=_CLASSES):
    return inject_runner(
        monkeypatch,
        RunResult(
            stdout=ENGINE_BANNER + sentinel({"classes": classes}),
            stderr="",
            exit_code=0,
        ),
    )


def test_a_scan_always_runs_the_import_pass_then_reads_the_classes(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path)

    def effects(p: Path) -> None:
        (p / ".godot").mkdir(exist_ok=True)
        (p / ".godot" / "global_script_class_cache.cfg").write_text("list=[]\n")
        (p / "attack_component.gd.uid").write_text("uid://x")

    calls, fake_launch = _fake_pass(effects)
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    asked: list[dict] = []
    real_capture = ProjectTreeInventory.capture

    def recording_capture(project_arg, **kwargs):
        asked.append(kwargs)
        return real_capture(project_arg, **kwargs)

    monkeypatch.setattr(ProjectTreeInventory, "capture", recording_capture)
    fake = _classes_read(monkeypatch)

    result = _run(project)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [call["args"] for call in calls] == [["--path", str(project), "--import"]]
    assert calls[0]["timeout"] == 300.0
    # The report is `export run`'s, rewrites included.
    assert asked == [{"detect_rewrites": True}]
    assert fake.calls == [("project-scan", {})]
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
    _, fake_launch = _fake_pass(stderr=stderr)
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    _classes_read(monkeypatch)

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
    _, fake_launch = _fake_pass(stderr="\n".join(lines) + "\n")
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    _classes_read(monkeypatch)

    data = json.loads(_run(project).stdout)

    assert data["engine_errors"] == lines[:ENGINE_ERROR_LINE_CAP]
    assert data["engine_errors_truncated"] is True


def test_exactly_the_cap_is_not_truncated(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    lines = [f"ERROR: failure {n}" for n in range(ENGINE_ERROR_LINE_CAP)]
    _, fake_launch = _fake_pass(stderr="\n".join(lines) + "\n")
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    _classes_read(monkeypatch)

    data = json.loads(_run(project).stdout)

    assert len(data["engine_errors"]) == ENGINE_ERROR_LINE_CAP
    assert data["engine_errors_truncated"] is False


def test_a_clean_pass_forwards_its_stderr_warnings_included(monkeypatch, tmp_path):
    # ADR-0002's child-stderr rule: a success forwards the child's stream.
    # `engine_errors` keeps only the error lines, so a warning the pass printed
    # (an `@tool` autoload's `push_warning`) reaches the caller only this way.
    project = minimal_project(tmp_path)
    stderr = (
        "WARNING: tool autoload said this\nERROR: Error importing 'res://bad.png'.\n"
    )
    _, fake_launch = _fake_pass(stderr=stderr)
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    _classes_read(monkeypatch)

    result = _run(project)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert stderr in result.stderr
    assert json.loads(result.stdout)["engine_errors"] == [
        "ERROR: Error importing 'res://bad.png'."
    ]


def test_a_pass_that_exits_non_zero_fails_and_reads_no_classes(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    _, fake_launch = _fake_pass(stderr="ERROR: boom\n", exit_code=1)
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    fake = _classes_read(monkeypatch)

    result = _run(project)

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "operation_failed"
    # A failure carries the pass's stream; under --json it is forwarded.
    assert "ERROR: boom" in result.stderr
    assert fake.calls == []


def test_a_timed_out_pass_is_the_launch_timeout_failure(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    _, fake_launch = _fake_pass(
        stderr="WARNING: before the ceiling\n",
        exit_code=-1,
        failure=LaunchFailure.TIMEOUT,
    )
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    fake = _classes_read(monkeypatch)

    result = _run(project, "--timeout", "5")

    assert json.loads(result.stdout)["error"]["code"] == "launch_timeout"
    assert "WARNING: before the ceiling" in result.stderr
    assert fake.calls == []


def test_a_failed_class_read_is_the_scans_failure(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    _, fake_launch = _fake_pass()
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=ENGINE_BANNER + error_sentinel("project_not_found", "none"),
            stderr="",
            exit_code=4,
        ),
    )

    result = _run(project)

    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_a_scan_without_a_project_is_refused_before_any_launch(monkeypatch, tmp_path):
    calls, fake_launch = _fake_pass()
    monkeypatch.setattr("gda.commands.project.launch", fake_launch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)

    result = runner_cli.invoke(app, ["project", "scan", "--json"])

    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"
    assert calls == []
