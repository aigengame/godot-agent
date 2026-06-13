"""S3: gda script create / script get success paths against a fake runner (issue #110).

The script command group acts on .gd script files on disk (write text /
read text back), staying headless. These tests drive the same proven pipeline
as the scene and node groups — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import FakeRunner, inject_runner, sentinel

CREATE_RESULT = {
    "path": "/tmp/proj/hero.gd",
    "class_name": "Hero",
    "extends": "Node2D",
    "created_dirs": [],
}


def test_script_create_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(CREATE_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["script", "create", "/tmp/proj/hero.gd", "--extends", "Node2D", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/hero.gd"
    # The created script's declared metadata, echoed so an agent verifies the
    # effect without a second call.
    assert data["class_name"] == "Hero"
    assert data["extends"] == "Node2D"
    # The operation was dispatched by name with the command's typed params. With
    # --extends and no --content, content is null.
    assert fake.calls == [
        (
            "script-create",
            {
                "path": "/tmp/proj/hero.gd",
                "content": None,
                "extends_type": "Node2D",
            },
        )
    ]
    assert "engine diagnostic" in result.stderr


def test_script_create_default_template_passes_null_content_and_extends(monkeypatch):
    # The bare template: no --content, no --extends. Both pass through as null,
    # so the operation writes its default minimal template.
    stdout = sentinel({**CREATE_RESULT, "extends": "Node"})
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["script", "create", "/tmp/proj/hero.gd", "--json"])

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "script-create",
            {"path": "/tmp/proj/hero.gd", "content": None, "extends_type": None},
        )
    ]


def test_script_create_content_passes_verbatim_source(monkeypatch):
    # --content supplies verbatim source; it rides through as the content param.
    stdout = sentinel(
        {"path": "/tmp/proj/util.gd", "class_name": None, "extends": None, "created_dirs": []}
    )
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "create",
            "/tmp/proj/util.gd",
            "--content",
            "extends RefCounted\n",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "script-create",
            {
                "path": "/tmp/proj/util.gd",
                "content": "extends RefCounted\n",
                "extends_type": None,
            },
        )
    ]


def test_script_create_content_and_extends_are_mutually_exclusive(monkeypatch):
    # Verbatim content is not templated, so a base class has nowhere to go;
    # supplying both is a usage error (exit 2), never a silent precedence rule.
    fake = inject_runner(monkeypatch, RunResult(stdout=sentinel(CREATE_RESULT), stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "create",
            "/tmp/proj/hero.gd",
            "--content",
            "extends Node\n",
            "--extends",
            "Node2D",
            "--json",
        ],
    )

    assert result.exit_code == 2
    # The usage error fires before any dispatch — the engine is never reached.
    assert fake.calls == []


GET_RESULT = {
    "path": "/tmp/proj/hero.gd",
    "source": "class_name Hero\nextends Node2D\n",
    "class_name": "Hero",
    "extends": "Node2D",
}


def test_script_get_json_emits_source_and_metadata_and_exit_zero(monkeypatch):
    # script get is the verifier (issue #110): it reads a script's source back
    # as raw text with its class_name/extends, so a create round-trips.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(GET_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["script", "get", "/tmp/proj/hero.gd", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/hero.gd"
    assert data["source"] == "class_name Hero\nextends Node2D\n"
    assert data["class_name"] == "Hero"
    assert data["extends"] == "Node2D"
    assert fake.calls == [("script-get", {"path": "/tmp/proj/hero.gd"})]


LIST_RESULT = {
    "scripts": [
        {"path": "res://hero.gd", "class_name": "Hero", "extends": "Node2D"},
        {"path": "res://util.gd", "class_name": None, "extends": "RefCounted"},
        {"path": "res://empty.gd", "class_name": None, "extends": None},
    ]
}


def test_script_list_json_enumerates_project_scripts_and_exit_zero(monkeypatch, tmp_path):
    # script list enumerates the resolved project's .gd files (issue #117): each
    # entry carries its res:// path plus the class_name/extends parsed cheaply
    # from the script's raw source.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(LIST_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["script", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [s["path"] for s in data["scripts"]] == [
        "res://hero.gd",
        "res://util.gd",
        "res://empty.gd",
    ]
    assert data["scripts"][0]["class_name"] == "Hero"
    assert data["scripts"][1]["extends"] == "RefCounted"
    assert data["scripts"][2]["class_name"] is None
    # script list takes no operation params: the project is process context.
    assert fake.calls == [("script-list", {})]


def test_script_list_passes_resolved_project_to_the_runner(monkeypatch, tmp_path):
    # script list enumerates res:// in the resolved project, so --project must
    # reach the runner (which hands it to the engine as --path, issue #32).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    seen: dict = {}

    def record(binary, project):
        seen["project"] = project
        return FakeRunner(
            RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
        )

    monkeypatch.setattr("gda.cli._make_runner", record)

    result = CliRunner().invoke(
        app, ["script", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert seen["project"] == tmp_path
