"""S3: gda resource create / get / uid success paths against a fake runner (issues #112, #113).

The resource command group acts on .tres resource files on disk (load/save
plumbing), staying headless; `gda resource uid` additionally resolves a Godot
resource UID to/from its resource path in BOTH directions against the engine's
read-only UID cache. These tests drive the same proven pipeline as the
scene/node/script groups — Typer → binary resolution → runner → sentinel parse
→ typed model → JSON — with canned engine output, no real Godot. For `uid`, the
single `target` argument selects the direction by its form (a `uid://` value vs
a `res://`/filesystem path); both directions converge on one
`{queried, uid, path}` result.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import (
    RESOURCE_CREATE_RESULT as CREATE_RESULT,
    RESOURCE_DELETE_RESULT as DELETE_RESULT,
    RESOURCE_GET_RESULT as GET_RESULT,
    RESOURCE_SET_RESULT as SET_RESULT,
    PATH,
    PATH_TO_UID_RESULT,
    UID,
    UID_TO_PATH_RESULT,
    FakeRunner,
    inject_runner,
    sentinel,
)


# --- resource set (issue #120) -------------------------------------------


def test_resource_set_dispatches_path_property_value_and_round_trips(monkeypatch):
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(SET_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "set",
            "/tmp/proj/palette.tres",
            "--property",
            "interpolation_mode",
            "--value",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    # The result reports the coerced value in the JSON projection get reports, so
    # a set round-trips through a get (the declared int type, not the string).
    assert data["path"] == "/tmp/proj/palette.tres"
    assert data["property"] == "interpolation_mode"
    assert data["type"] == "int"
    assert data["value"] == 1
    # The CLI value rides through as a string; the operation owns the coercion.
    assert fake.calls == [
        (
            "resource-set",
            {
                "path": "/tmp/proj/palette.tres",
                "property": "interpolation_mode",
                "value": "1",
            },
        )
    ]
    assert "engine diagnostic" in result.stderr


def test_resource_set_human_output_is_set_path_property_type_value(monkeypatch):
    inject_runner(monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "set",
            "/tmp/proj/palette.tres",
            "--property",
            "interpolation_mode",
            "--value",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == "set /tmp/proj/palette.tres.interpolation_mode (int) = 1"
    )


def test_resource_set_requires_value(monkeypatch):
    # --value is required: a set with no value is a usage error (exit 2), not a
    # silent no-op or an empty write.
    fake = FakeRunner(RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0))
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app, ["resource", "set", "/tmp/proj/palette.tres", "--property", "x"]
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_resource_set_expands_user_home_in_filesystem_path(monkeypatch):
    fake = FakeRunner(RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0))
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app,
        [
            "resource",
            "set",
            "~/palette.tres",
            "--property",
            "interpolation_mode",
            "--value",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    sent_path = fake.calls[0][1]["path"]
    assert "~" not in sent_path
    assert sent_path.endswith("/palette.tres")


# --- resource delete (issue #120) ----------------------------------------


def test_resource_delete_dispatches_path_and_reports_removed(monkeypatch):
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(DELETE_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["resource", "delete", "/tmp/proj/palette.tres", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    # The result names the content removed (path + type), not just the path.
    assert data["path"] == "/tmp/proj/palette.tres"
    assert data["type"] == "Gradient"
    assert fake.calls == [("resource-delete", {"path": "/tmp/proj/palette.tres"})]
    assert "engine diagnostic" in result.stderr


def test_resource_delete_human_output_names_path_and_type(monkeypatch):
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(DELETE_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["resource", "delete", "/tmp/proj/palette.tres"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "deleted /tmp/proj/palette.tres (Gradient)"


def test_resource_delete_res_path_passes_through_untouched(monkeypatch):
    fake = FakeRunner(RunResult(stdout=sentinel(DELETE_RESULT), stderr="", exit_code=0))
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app, ["resource", "delete", "res://palette.tres", "--json"]
    )

    assert result.exit_code == 0
    assert fake.calls == [("resource-delete", {"path": "res://palette.tres"})]


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


def test_resource_uid_resolves_uid_to_path_json_and_exit_zero(monkeypatch, tmp_path):
    # Given a uid://, the command reports the res:// path it resolves to. Engine
    # banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(UID_TO_PATH_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["resource", "uid", UID, "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["queried"] == "uid"
    assert data["uid"] == UID
    assert data["path"] == PATH
    # The target rides through verbatim as the typed `target` param; a uid://
    # value passes through the CLI path normalization untouched (issue #32).
    assert fake.calls == [("resource-uid", {"target": UID})]
    assert "engine diagnostic" in result.stderr


def test_resource_uid_resolves_path_to_uid_json_and_exit_zero(monkeypatch, tmp_path):
    # Given a res:// path, the command reports its assigned uid://. The result is
    # the same shape; only `queried` distinguishes which side was the target.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(PATH_TO_UID_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["resource", "uid", PATH, "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["queried"] == "path"
    assert data["uid"] == UID
    assert data["path"] == PATH
    # A res:// path also passes through normalization untouched (issue #32).
    assert fake.calls == [("resource-uid", {"target": PATH})]


def test_resource_uid_passes_resolved_project_to_the_runner(monkeypatch, tmp_path):
    # Resolution queries the project's UID cache, so --project must reach the
    # runner (which hands it to the engine as --path, issue #32).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    seen: dict = {}

    def record(binary, project):
        seen["project"] = project
        return FakeRunner(
            RunResult(stdout=sentinel(UID_TO_PATH_RESULT), stderr="", exit_code=0)
        )

    monkeypatch.setattr("gda.cli._make_runner", record)

    result = CliRunner().invoke(
        app, ["resource", "uid", UID, "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert seen["project"] == tmp_path


def test_resource_uid_expands_tilde_for_a_filesystem_target(monkeypatch, tmp_path):
    # A filesystem path target gets ~ expanded at the CLI layer so a literal ~
    # works without a shell (issue #32); a uid:// / res:// target is untouched.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(PATH_TO_UID_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["resource", "uid", "~/data.tres", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    # The dispatched target is the ~-expanded absolute path, not the literal "~".
    (operation, params), = fake.calls
    assert operation == "resource-uid"
    assert not params["target"].startswith("~")
    assert params["target"].endswith("/data.tres")


# --- human-readable output (no --json): the render_text path (issue #113) ---


def test_resource_uid_human_output_renders_uid_arrow_path(monkeypatch, tmp_path):
    # Without --json, a resolved mapping renders as `<uid> -> <path>`, the same
    # for both directions since the result shape is identical.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(UID_TO_PATH_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["resource", "uid", UID, "--project", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == f"{UID} -> {PATH}"
