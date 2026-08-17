"""S3: gda script create / script get success paths against a fake runner (issue #110).

The script command group acts on .gd script files on disk (write text /
read text back), staying headless. These tests drive the same proven pipeline
as the scene and node groups — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.script import ScriptSetMode
from gda.runner import RunResult
from tests.support import (
    SCRIPT_CREATE_RESULT as CREATE_RESULT,
    SCRIPT_GET_RESULT as GET_RESULT,
    SCRIPT_LIST_RESULT as LIST_RESULT,
    SCRIPT_SET_RESULT as SET_RESULT,
    FakeRunner,
    inject_runner,
    sentinel,
)


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

    result = CliRunner().invoke(
        app, ["script", "create", "/tmp/proj/hero.gd", "--json"]
    )

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
        {
            "path": "/tmp/proj/util.gd",
            "class_name": None,
            "extends": None,
            "created_dirs": [],
        }
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
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(CREATE_RESULT), stderr="", exit_code=0)
    )

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


def test_script_list_json_enumerates_project_scripts_and_exit_zero(
    monkeypatch, tmp_path
):
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

    monkeypatch.setattr("gda.dispatch.make_runner", record)

    result = CliRunner().invoke(
        app, ["script", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert seen["project"] == tmp_path


def test_script_set_search_replace_dispatches_search_and_replace(monkeypatch):
    # search-replace mode (issue #118): --search/--replace ride through as the
    # search/replace params; the other mode params pass as null. The CLI resolves
    # the edit mode once and stamps the explicit `mode` discriminator the op
    # dispatches on (issue #133). The result re-parses the written source's
    # class_name/extends, so set round-trips through get.
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
                "mode": ScriptSetMode.SEARCH_REPLACE,
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
    # search-replace params pass as null. The CLI stamps the explicit `mode`
    # discriminator the op dispatches on (issue #133).
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
                "mode": ScriptSetMode.LINE_RANGE,
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
    # other mode param passes as null. The CLI stamps the explicit `mode`
    # discriminator the op dispatches on (issue #133).
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
                "mode": ScriptSetMode.FULL,
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
    "replaced_script": None,
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
    # attach overwrites-and-reports (issue #132): the displaced-script field rides
    # through to the result; null here means the node had no prior script.
    assert data["replaced_script"] is None
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


def test_script_attach_reports_the_displaced_script(monkeypatch):
    # attach is overwrite-and-report (issue #132): when the node already carried a
    # script, the result names the displaced script's resource_path verbatim, so an
    # agent can detect a clobber from the result rather than have it silently hidden.
    payload = {
        "scene_path": "/tmp/proj/main.tscn",
        "node": "Hero",
        "script": "/tmp/proj/new.gd",
        "class_name": None,
        "replaced_script": "res://old.gd",
    }
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(payload)
    inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "attach",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--script",
            "/tmp/proj/new.gd",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["replaced_script"] == "res://old.gd"


def test_script_validate_valid_script_reports_valid_true_no_diagnostics(monkeypatch):
    # script validate (issue #118): a valid script is a successful op (exit 0)
    # reporting valid=true, no error_string, and no diagnostics.
    payload = {"path": "/tmp/proj/ok.gd", "valid": True, "error_string": None}
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(payload)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/ok.gd", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert data["error_string"] is None
    assert data["diagnostics"] == []
    assert fake.calls == [("script-validate", {"path": "/tmp/proj/ok.gd"})]


def test_script_validate_help_mentions_valid_false_success_result():
    result = CliRunner().invoke(app, ["script", "validate", "--help"])

    assert result.exit_code == 0
    assert "invalid exits 0 with valid=false" in result.stdout


# --- project context: the refusal and the reported root (#658) ----------------


def _project(tmp_path, name: str):
    """A directory Godot counts as a project (it holds the marker)."""
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return proj


def test_script_validate_refuses_a_script_outside_the_resolved_project(
    monkeypatch, tmp_path
):
    # GDA-DF-035: compiling a script against a project that does not own it makes
    # every res:// dependency resolve against the wrong root, so the engine
    # reports a cascade of false missing-file and derived type errors. gda refuses
    # instead — BEFORE the engine runs, which is what `fake.calls == []` pins —
    # and names both sides so the reader sees which one is wrong.
    proj = _project(tmp_path, "game")
    outsider = tmp_path / "elsewhere" / "deck.gd"
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["script", "validate", str(outsider), "--project", str(proj), "--json"],
    )

    assert result.exit_code == 4
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "project_not_found"
    assert error["category"] == "operation"
    # Both locations are named: where the file is, and which project was resolved.
    assert str(outsider.resolve()) in error["message"]
    assert str(proj.resolve()) in error["message"]
    # Nothing was parsed: no engine call was made at all.
    assert fake.calls == []


def test_script_validate_refusal_is_identical_on_the_params_json_path(
    monkeypatch, tmp_path
):
    # ADR-0015 parity: --params-json builds the same model and must reach the same
    # refusal. The check lives on the command's recipe — the one hook both input
    # paths share — not in the argv body, which --params-json bypasses.
    proj = _project(tmp_path, "game")
    outsider = tmp_path / "elsewhere" / "deck.gd"
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "--params-json",
            json.dumps({"path": str(outsider)}),
            "--project",
            str(proj),
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"
    assert fake.calls == []


def test_script_validate_reports_the_resolved_project_root(monkeypatch, tmp_path):
    # The result names the root its res:// dependencies resolved against, so a
    # reader can tell a real compile error from a wrong-project one without
    # re-deriving gda's resolution.
    proj = _project(tmp_path, "game")
    script = proj / "deck.gd"
    payload = {"path": str(script), "valid": True, "error_string": None}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", str(script), "--project", str(proj), "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["project_root"] == str(proj)


def test_script_validate_reports_a_null_project_root_when_projectless(
    monkeypatch, tmp_path
):
    # Projectless (no --project, no $GDA_PROJECT, cwd is not a project) stays
    # supported: a standalone script is still validated by filesystem path, and
    # the null root tells the reader that res:// resolved against no project of
    # gda's choosing — so any res:// dependency error is not to be trusted.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    payload = {"path": "/tmp/proj/ok.gd", "valid": True, "error_string": None}
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/ok.gd", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["project_root"] is None
    # The engine still ran: projectless is not a refusal.
    assert fake.calls == [("script-validate", {"path": "/tmp/proj/ok.gd"})]


def test_script_validate_does_not_refuse_a_res_path(monkeypatch, tmp_path):
    # A res:// path addresses the resolved project by construction (ADR-0006), so
    # containment makes no filesystem claim about it — it is never refused.
    proj = _project(tmp_path, "game")
    payload = {"path": "res://deck.gd", "valid": True, "error_string": None}
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["script", "validate", "res://deck.gd", "--project", str(proj), "--json"],
    )

    assert result.exit_code == 0
    assert fake.calls == [("script-validate", {"path": "res://deck.gd"})]


def test_script_validate_does_not_refuse_a_colon_bearing_path_as_virtual(
    monkeypatch, tmp_path
):
    # A colon is legal in a POSIX filename, so a path merely CONTAINING "://" is
    # an ordinary filesystem path — and this one is outside the project, so it is
    # refused rather than waved through as engine-virtual (which skipped
    # containment entirely and let the engine open the outside file).
    proj = _project(tmp_path, "game")
    odd = tmp_path / "outside:" / "deck.gd"
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", str(odd), "--project", str(proj), "--json"]
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"
    assert fake.calls == []


def _ancestor_cwd_project(monkeypatch, tmp_path):
    """A project one level below the cwd, with a script in it (the #658 A shape)."""
    proj = _project(tmp_path, "game")
    monkeypatch.chdir(tmp_path)
    return proj


def test_script_validate_accepts_a_relative_target_from_an_ancestor_cwd(
    monkeypatch, tmp_path
):
    # An ordinary invocation that the containment check used to refuse: run from
    # the workspace ABOVE the project, naming both the project and the script
    # relatively. The engine anchors `deck.gd` at `--path game`, and the README
    # promises exactly that, so gda must not judge it against its own cwd.
    proj = _ancestor_cwd_project(monkeypatch, tmp_path)
    payload = {"path": "deck.gd", "valid": True, "error_string": None}
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "deck.gd", "--project", "game", "--json"]
    )

    assert result.exit_code == 0, result.stdout
    # The op receives the path unchanged — the engine does the anchoring — and the
    # reported root is absolute, not the bare relative "game" the caller typed.
    assert fake.calls == [("script-validate", {"path": "deck.gd"})]
    assert json.loads(result.stdout)["project_root"] == str(proj)


def test_script_validate_relative_target_parity_on_the_params_json_path(
    monkeypatch, tmp_path
):
    # ADR-0015 parity for the same shape: --params-json must anchor identically.
    proj = _ancestor_cwd_project(monkeypatch, tmp_path)
    payload = {"path": "deck.gd", "valid": True, "error_string": None}
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "--params-json",
            json.dumps({"path": "deck.gd"}),
            "--project",
            "game",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert fake.calls == [("script-validate", {"path": "deck.gd"})]
    assert json.loads(result.stdout)["project_root"] == str(proj)


def test_script_validate_still_refuses_a_relative_target_that_climbs_out(
    monkeypatch, tmp_path
):
    # Anchoring at the project is not a blanket accept: a relative path that
    # climbs out of the project with `..` is still outside, from either spelling.
    _ancestor_cwd_project(monkeypatch, tmp_path)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "../elsewhere/deck.gd",
            "--project",
            "game",
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"
    assert fake.calls == []


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
        "SCRIPT ERROR: Parse Error: Expected expression for variable initial "
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


# --- human-readable output (no --json): the render_text paths (issue #118) ---


def test_script_validate_human_output_valid(monkeypatch):
    # Without --json, a valid result renders a one-line 'valid <path>'.
    payload = {"path": "/tmp/proj/ok.gd", "valid": True, "error_string": None}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["script", "validate", "/tmp/proj/ok.gd"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "valid /tmp/proj/ok.gd"


def test_script_validate_human_output_invalid_lists_diagnostics(monkeypatch):
    # An invalid result renders 'invalid <path>', the error_string, and each
    # advisory diagnostic as 'line N: message' (parsed from stderr).
    payload = {
        "path": "/tmp/proj/broken.gd",
        "valid": False,
        "error_string": "Parse error.",
    }
    stderr = (
        "SCRIPT ERROR: Parse Error: the message.\n"
        "          at: GDScript::reload (gdscript://-1.gd:3)\n"
    )
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr=stderr, exit_code=0)
    )

    result = CliRunner().invoke(app, ["script", "validate", "/tmp/proj/broken.gd"])

    assert result.exit_code == 0
    assert "invalid /tmp/proj/broken.gd" in result.stdout
    assert "Parse error." in result.stdout
    assert "line 3: Parse Error: the message." in result.stdout


def test_script_validate_human_output_invalid_leads_with_the_project_root(
    monkeypatch, tmp_path
):
    # An invalid verdict prints the project it was compiled against BEFORE the
    # diagnostics (#658): when the root is wrong every line below it is an
    # artefact of that one mistake, so the cause must not sit under the cascade.
    proj = _project(tmp_path, "game")
    script = proj / "broken.gd"
    payload = {"path": str(script), "valid": False, "error_string": "Parse error."}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", str(script), "--project", str(proj)]
    )

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == f"invalid {script}"
    assert lines[1] == f"  project: {proj}"


def test_script_validate_human_output_names_projectless_explicitly(
    monkeypatch, tmp_path
):
    # With no project resolved the line says so rather than printing an empty
    # value — "(none resolved: projectless)" is the actionable reading of a
    # res:// dependency error.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    payload = {
        "path": "/tmp/proj/broken.gd",
        "valid": False,
        "error_string": "Parse error.",
    }
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["script", "validate", "/tmp/proj/broken.gd"])

    assert result.exit_code == 0
    assert "  project: (none resolved: projectless)" in result.stdout


def test_script_attach_human_output(monkeypatch):
    # Without --json, attach renders 'attached <script> to <node> in <scene>'.
    payload = {
        "scene_path": "/tmp/proj/main.tscn",
        "node": "Hero",
        "script": "/tmp/proj/hero.gd",
        "class_name": "Hero",
    }
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
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
        ],
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == "attached /tmp/proj/hero.gd to Hero in /tmp/proj/main.tscn"
    )


def test_script_set_human_output_renders_metadata(monkeypatch):
    # Without --json, set reuses the shared script-metadata renderer.
    payload = {"path": "/tmp/proj/hero.gd", "class_name": "Hero", "extends": "Node2D"}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "set", "/tmp/proj/hero.gd", "--content", "x"]
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == "set /tmp/proj/hero.gd (extends Node2D, class_name Hero)"
    )
