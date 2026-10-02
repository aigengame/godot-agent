"""The class-resolution remedy: one seam, two channels (#1073).

When a run the class index can explain fails, the dispatch tail adds the
`gda project scan` remedy to the op's own message and the unresolved class names
to `evidence.unresolved_classes`. The code stays the verdict. The remedy reaches
only the channels whose engine reads the index WITHOUT running the import pass —
the sentinel ops and `script run`. `export run`, `resource import` and
`project scan` run that pass, so after it a class-resolution error is a real
source error, and the remedy would be wrong advice.

Engine-free: every run is canned. The real-engine half is
`tests/project/test_e2e_class_resolution_remedy.py`.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import (
    ENGINE_BANNER,
    FakeExportRunner,
    error_sentinel,
    inject_runner,
    invoke_cli,
    minimal_project,
    sentinel,
)

NOT_FOUND = (
    'SCRIPT ERROR: Parse Error: Could not find type "AttackComponent" in the '
    "current scope.\n"
    "          at: GDScript::reload (res://holder.gd:2)\n"
)
BASE_NOT_FOUND = (
    'SCRIPT ERROR: Parse Error: Could not find base class "AttackComponent".\n'
    "          at: GDScript::reload (res://fire_attack.gd:1)\n"
)


def _node_set_failure(monkeypatch, project, stderr):
    result, _ = invoke_cli(
        monkeypatch,
        [
            "node",
            "set",
            "res://holder.tscn",
            "--node",
            ".",
            "--property",
            "c",
            "--value",
            "null",
            "--project",
            str(project),
            "--json",
        ],
        stdout=error_sentinel("unknown_property", "node . has no settable property: c"),
        stderr="gda: running operation: node-set\n" + stderr,
        exit_code=1,
    )
    assert result.exit_code == 4, result.stdout
    return json.loads(result.stdout)["error"]


def _write_index(project):
    (project / ".godot").mkdir()
    (project / ".godot" / "global_script_class_cache.cfg").write_text(
        "list=[]\n", encoding="utf-8"
    )


def test_a_sentinel_op_with_no_index_says_no_scan_has_run(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)

    error = _node_set_failure(monkeypatch, project, NOT_FOUND)

    assert error["code"] == "unknown_property"
    assert error["message"] == (
        "node . has no settable property: c; the engine could not resolve "
        "AttackComponent, and no scan has run on this project: run "
        "`gda project scan` and retry; if AttackComponent still fails after the "
        "scan, AttackComponent is not a class_name in this project"
    )
    assert error["evidence"] == {"unresolved_classes": ["AttackComponent"]}
    assert "hint" not in error


def test_with_the_index_present_the_remedy_is_conditional(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    _write_index(project)

    error = _node_set_failure(monkeypatch, project, NOT_FOUND)

    assert error["message"] == (
        "node . has no settable property: c; the engine could not resolve "
        "AttackComponent: if AttackComponent is a class_name in this project, "
        "run `gda project scan` and retry"
    )


def test_each_class_is_named_once_in_the_order_the_engine_reported_it(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path)
    stderr = (
        BASE_NOT_FOUND
        + 'SCRIPT ERROR: Parse Error: Could not parse global class "Mover" from '
        '"res://mover.gd".\n'
        + NOT_FOUND
        + 'SCRIPT ERROR: Parse Error: Could not resolve super class "Walker".\n'
    )

    error = _node_set_failure(monkeypatch, project, stderr)

    assert error["evidence"]["unresolved_classes"] == [
        "AttackComponent",
        "Mover",
        "Walker",
    ]
    assert "if one of them still fails after the scan" in error["message"]


def test_a_member_type_of_a_resolved_type_is_not_read_as_a_class(monkeypatch, tmp_path):
    # `A.B` where `A` resolved and `B` is not a member of it: no scan supplies a
    # member, so the engine's two member forms are not class-resolution errors.
    project = minimal_project(tmp_path)
    stderr = (
        'SCRIPT ERROR: Parse Error: Could not find type "Inner" under base '
        '"AttackComponent".\n'
        'SCRIPT ERROR: Parse Error: Could not find type "Inner" in '
        '"AttackComponent".\n'
    )

    error = _node_set_failure(monkeypatch, project, stderr)

    assert error["message"] == "node . has no settable property: c"
    assert "evidence" not in error


def test_a_failure_with_no_class_resolution_error_is_unchanged(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)

    error = _node_set_failure(monkeypatch, project, "")

    assert error["message"] == "node . has no settable property: c"
    assert "evidence" not in error


def test_a_success_is_not_touched(monkeypatch, tmp_path):
    # Out of scope by decision: a success that carries the same engine errors
    # (an invalid validate verdict, a non-strict `script run`) gets no remedy.
    project = minimal_project(tmp_path)

    result, _ = invoke_cli(
        monkeypatch,
        ["resource", "uid", "res://a.tres", "--project", str(project), "--json"],
        stdout=sentinel(
            {"queried": "path", "path": "res://a.tres", "uid": "uid://abc"}
        ),
        stderr=NOT_FOUND,
    )

    assert result.exit_code == 0, result.stdout
    assert "gda project scan" not in result.stdout


def test_export_run_never_gets_the_remedy(monkeypatch, tmp_path):
    # The excluded channel: `export run` runs the import pass itself, so after it
    # the index is fresh and a class-resolution error is a real source error.
    project = minimal_project(tmp_path)
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=ENGINE_BANNER
            + sentinel(
                {
                    "index": 0,
                    "name": "Linux/X11",
                    "platform": "Linux/X11",
                    "runnable": True,
                    "export_path": "build/game.x86_64",
                    "templates_installed": True,
                    "templates_version": "4.6.3.stable",
                    "templates_root": "/host/data/Godot/export_templates",
                    "templates_root_host": None,
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )
    export_runner = FakeExportRunner(
        RunResult(stdout="", stderr=NOT_FOUND, exit_code=1)
    )
    monkeypatch.setattr(
        "gda.dispatch.make_export_runner", lambda binary, project=None: export_runner
    )

    result = CliRunner().invoke(
        app,
        ["export", "run", "--preset", "Linux/X11", "--project", str(project), "--json"],
    )

    assert result.exit_code == 4, result.stdout
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "export_failed"
    assert 'Could not find type "AttackComponent"' in error["diagnostics"]
    assert "gda project scan" not in error["message"]
    assert "unresolved_classes" not in error.get("evidence", {})
