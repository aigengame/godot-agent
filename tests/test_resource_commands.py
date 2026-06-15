"""S3: gda resource create / resource get success paths against a fake runner (issue #112).

The resource command group acts on .tres resource files on disk (load/save
plumbing), staying headless. These tests drive the same proven pipeline as the
scene/node/script groups — Typer → binary resolution → runner → sentinel parse
→ typed model → JSON — with canned engine output, no real Godot.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import FakeRunner, inject_runner, sentinel

CREATE_RESULT = {
    "path": "/tmp/proj/palette.tres",
    "type": "Gradient",
    "created_dirs": [],
}

GET_RESULT = {
    "path": "/tmp/proj/palette.tres",
    "type": "Gradient",
    "properties": [
        {"name": "resource_name", "type": "String", "value": ""},
        {"name": "interpolation_mode", "type": "int", "value": 0},
    ],
}


def test_resource_create_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(CREATE_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "create",
            "/tmp/proj/palette.tres",
            "--type",
            "Gradient",
            "--json",
        ],
    )

    assert result.exit_code == 0
    # stdout carries ONLY the result payload — a single valid JSON object.
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/palette.tres"
    # The created resource's type, echoed so an agent verifies the effect
    # (path + type) without a second call.
    assert data["type"] == "Gradient"
    # The operation was dispatched by name with the command's typed params.
    assert fake.calls == [
        ("resource-create", {"path": "/tmp/proj/palette.tres", "type": "Gradient"})
    ]
    assert "engine diagnostic" in result.stderr


def test_resource_create_human_output_reports_path_and_type(monkeypatch):
    inject_runner(monkeypatch, RunResult(stdout=sentinel(CREATE_RESULT), stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["resource", "create", "/tmp/proj/palette.tres", "--type", "Gradient"]
    )

    assert result.exit_code == 0
    # The human path names what was created and where (mirrors scene create).
    assert "created /tmp/proj/palette.tres" in result.stdout
    assert "Gradient" in result.stdout


def test_resource_get_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(GET_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["resource", "get", "/tmp/proj/palette.tres", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/palette.tres"
    assert data["type"] == "Gradient"
    # The typed property projection (same shape as node get): name/type/value.
    by_name = {p["name"]: p for p in data["properties"]}
    assert by_name["interpolation_mode"]["type"] == "int"
    assert by_name["interpolation_mode"]["value"] == 0
    assert fake.calls == [("resource-get", {"path": "/tmp/proj/palette.tres"})]


def test_resource_get_human_output_lists_typed_properties(monkeypatch):
    inject_runner(monkeypatch, RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["resource", "get", "/tmp/proj/palette.tres"])

    assert result.exit_code == 0
    # The header names the resource and its type; each property is a typed line.
    assert "/tmp/proj/palette.tres (Gradient)" in result.stdout
    assert "interpolation_mode (int) = 0" in result.stdout


def test_resource_create_expands_user_home_in_filesystem_path(monkeypatch):
    # A filesystem path gets ~ expanded at the CLI layer (issue #32); res://
    # virtual paths pass through untouched. Exercise the expansion seam.
    fake = FakeRunner(RunResult(stdout=sentinel(CREATE_RESULT), stderr="", exit_code=0))
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app, ["resource", "create", "~/palette.tres", "--type", "Gradient", "--json"]
    )

    assert result.exit_code == 0
    sent_path = fake.calls[0][1]["path"]
    assert "~" not in sent_path
    assert sent_path.endswith("/palette.tres")


def test_resource_get_res_path_passes_through_untouched(monkeypatch):
    fake = FakeRunner(RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0))
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app, ["resource", "get", "res://palette.tres", "--json"]
    )

    assert result.exit_code == 0
    assert fake.calls == [("resource-get", {"path": "res://palette.tres"})]
