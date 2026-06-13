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


SET_RESULT = {
    "path": "/tmp/proj/hero.gd",
    "class_name": "Hero",
    "extends": "Node2D",
}


def test_script_set_search_replace_dispatches_search_and_replace(monkeypatch):
    # search-replace mode (issue #118): --search/--replace ride through as the
    # search/replace params; the other mode params pass as null. The result
    # re-parses the written source's class_name/extends, so set round-trips
    # through get.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(SET_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "/tmp/proj/hero.gd",
            "--search",
            "Node",
            "--replace",
            "Node2D",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/hero.gd"
    assert data["class_name"] == "Hero"
    assert data["extends"] == "Node2D"
    assert fake.calls == [
        (
            "script-set",
            {
                "path": "/tmp/proj/hero.gd",
                "search": "Node",
                "replace": "Node2D",
                "start_line": None,
                "end_line": None,
                "content": None,
            },
        )
    ]
    assert "engine diagnostic" in result.stderr


def test_script_set_line_range_dispatches_start_end_and_content(monkeypatch):
    # line-range mode: --start-line/--end-line + --content ride through; the
    # search-replace params pass as null.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "/tmp/proj/hero.gd",
            "--start-line",
            "2",
            "--end-line",
            "3",
            "--content",
            "extends Node2D",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "script-set",
            {
                "path": "/tmp/proj/hero.gd",
                "search": None,
                "replace": None,
                "start_line": 2,
                "end_line": 3,
                "content": "extends Node2D",
            },
        )
    ]


def test_script_set_full_overwrite_dispatches_content_only(monkeypatch):
    # full mode: --content with no --start-line overwrites the whole file; every
    # other mode param passes as null.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "/tmp/proj/hero.gd",
            "--content",
            "extends Node\n",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "script-set",
            {
                "path": "/tmp/proj/hero.gd",
                "search": None,
                "replace": None,
                "start_line": None,
                "end_line": None,
                "content": "extends Node\n",
            },
        )
    ]


def _assert_set_usage_error(fake, result):
    # A mode-validation error is a usage error (exit 2) that fires before any
    # dispatch — the engine is never reached.
    assert result.exit_code == 2
    assert fake.calls == []


def test_script_set_no_flags_is_a_usage_error(monkeypatch):
    # No edit mode at all is a usage error: set always needs exactly one mode.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["script", "set", "/tmp/proj/hero.gd", "--json"])

    _assert_set_usage_error(fake, result)


def test_script_set_search_without_replace_is_a_usage_error(monkeypatch):
    # --search requires --replace (and vice versa) — a half-specified
    # search-replace is a usage error, never a silent default.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "set", "/tmp/proj/hero.gd", "--search", "Node", "--json"]
    )

    _assert_set_usage_error(fake, result)


def test_script_set_replace_without_search_is_a_usage_error(monkeypatch):
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "set", "/tmp/proj/hero.gd", "--replace", "Node2D", "--json"]
    )

    _assert_set_usage_error(fake, result)


def test_script_set_search_replace_and_content_are_mutually_exclusive(monkeypatch):
    # Mixing search-replace with a line-range/full param (--content) is a usage
    # error: the modes are mutually exclusive.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "/tmp/proj/hero.gd",
            "--search",
            "Node",
            "--replace",
            "Node2D",
            "--content",
            "x",
            "--json",
        ],
    )

    _assert_set_usage_error(fake, result)


ATTACH_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "node": "Hero",
    "script": "/tmp/proj/hero.gd",
    "class_name": "Hero",
}


def test_script_attach_dispatches_scene_node_and_script(monkeypatch):
    # script attach (issue #118) binds a .gd to a node in a scene: the scene
    # path, the node path, and the script path ride through as the typed params;
    # the result echoes the attached script's class_name.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(ATTACH_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "attach",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--script",
            "/tmp/proj/hero.gd",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    assert data["node"] == "Hero"
    assert data["script"] == "/tmp/proj/hero.gd"
    assert data["class_name"] == "Hero"
    assert fake.calls == [
        (
            "script-attach",
            {
                "path": "/tmp/proj/main.tscn",
                "node": "Hero",
                "script": "/tmp/proj/hero.gd",
            },
        )
    ]
    assert "engine diagnostic" in result.stderr


def test_script_validate_valid_script_reports_valid_true_no_diagnostics(monkeypatch):
    # script validate (issue #118): a valid script is a successful op (exit 0)
    # reporting valid=true, no error_string, and no diagnostics.
    payload = {"path": "/tmp/proj/ok.gd", "valid": True, "error_string": None}
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(payload)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["script", "validate", "/tmp/proj/ok.gd", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert data["error_string"] is None
    assert data["diagnostics"] == []
    assert fake.calls == [("script-validate", {"path": "/tmp/proj/ok.gd"})]


def test_script_validate_invalid_script_is_success_with_parsed_diagnostics(monkeypatch):
    # Validating an INVALID script is a SUCCESSFUL op (exit 0): the sentinel says
    # valid=false, and the per-command classifier parses the line/message
    # diagnostics from stderr (the only place they live) into the result.
    payload = {
        "path": "/tmp/proj/broken.gd",
        "valid": False,
        "error_string": "Parse error.",
    }
    stderr = (
        'SCRIPT ERROR: Parse Error: Expected expression for variable initial '
        'value after "=".\n'
        "          at: GDScript::reload (gdscript://-9223371888644840980.gd:3)\n"
    )
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(payload)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr=stderr, exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/broken.gd", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert data["error_string"] == "Parse error."
    # The advisory diagnostics were parsed from stderr (line + message, no column).
    assert len(data["diagnostics"]) == 1
    assert data["diagnostics"][0]["line"] == 3
    assert data["diagnostics"][0]["column"] is None
    assert "Expected expression" in data["diagnostics"][0]["message"]
    assert fake.calls == [("script-validate", {"path": "/tmp/proj/broken.gd"})]


def test_script_set_start_line_without_content_is_a_usage_error(monkeypatch):
    # --start-line/--end-line require --content: a line range with no replacement
    # text is a usage error.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "set", "/tmp/proj/hero.gd", "--start-line", "2", "--json"]
    )

    _assert_set_usage_error(fake, result)


def test_script_set_end_line_without_start_line_is_a_usage_error(monkeypatch):
    # --end-line alone (with --content) is a usage error: end without a start has
    # no anchor.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "/tmp/proj/hero.gd",
            "--end-line",
            "3",
            "--content",
            "x",
            "--json",
        ],
    )

    _assert_set_usage_error(fake, result)
