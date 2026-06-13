"""S3: gda script create / script get success paths against a fake runner (issue #110).

The script command group acts on .gd/.cs script files on disk (write text /
read text back), staying headless. These tests drive the same proven pipeline
as the scene and node groups — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import inject_runner, sentinel

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
    inject_runner(monkeypatch, RunResult(stdout=sentinel(CREATE_RESULT), stderr="", exit_code=0))

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


def test_script_create_cs_without_content_is_a_usage_error(monkeypatch):
    # The built-in template is GDScript; writing it into a .cs file is
    # meaningless, so a .cs target without --content is a usage error (exit 2)
    # rather than a GDScript template silently landing in a C# file.
    inject_runner(monkeypatch, RunResult(stdout=sentinel(CREATE_RESULT), stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["script", "create", "/tmp/proj/Player.cs", "--json"])

    assert result.exit_code == 2


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
