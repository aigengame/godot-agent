"""S3: gda script create / script get success paths against a fake runner (issue #110).

The script command group acts on .gd script files on disk (write text /
read text back), staying headless. These tests drive the same proven pipeline
as the scene and node groups — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.script import ScriptSetMode
from gda.project import owning_project
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


# The absolute directory the engine-free `script validate` tests below address
# scripts in. It never exists on disk — the runner is faked — but since #697 the
# recipe asks whether some `project.godot` ABOVE a target claims it, walking to the
# filesystem root when no project resolved. "Nothing above /tmp/proj is a Godot
# project" is therefore an assumption about the MACHINE that a dozen unrelated
# verdicts now rest on, and /tmp is exactly where a scratch project gets left. The
# assumption is asserted once, by name, so a stray marker fails HERE with its cause
# stated instead of turning a dozen tests into `target_outside_project` refusals
# whose messages point everywhere else.
PROJECTLESS_DIR = Path("/tmp/proj")


def test_the_projectless_test_paths_really_have_no_owning_project():
    assert owning_project(str(PROJECTLESS_DIR / "ok.gd"), None) is None, (
        f"a project.godot exists at or above {PROJECTLESS_DIR}, so the projectless "
        "`script validate` tests in this module no longer address a projectless "
        "target — remove it, or move those tests under a pytest tmp_path"
    )


def test_script_validate_valid_script_reports_valid_true_no_diagnostics(monkeypatch):
    # script validate (issue #118): a valid script is a successful op (exit 0)
    # reporting valid=true, no error_string, and no diagnostics. A single path is a
    # batch of one (#663), so the verdict sits in the one `scripts` entry and the
    # top-level `valid` is that entry's own.
    stdout = "Godot Engine v4.6.3.stable.official\n" + _validate_sentinel(
        _ok("/tmp/proj/ok.gd")
    )
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/ok.gd", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert len(data["scripts"]) == 1
    assert data["scripts"][0]["path"] == "/tmp/proj/ok.gd"
    assert data["scripts"][0]["error_string"] is None
    assert data["scripts"][0]["diagnostics"] == []
    assert fake.calls == [
        ("script-validate", {"paths": ["/tmp/proj/ok.gd"], "all_scripts": False})
    ]


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
    # #697: the sibling code, not `project_not_found` — a project WAS resolved, it
    # just does not own this file, and the remedy is a DIFFERENT project rather
    # than supplying one. Reusing the projectless code said neither.
    assert error["code"] == "target_outside_project"
    assert error["category"] == "operation"
    # Both locations are named: where the file is, and which project was resolved.
    assert str(outsider.resolve()) in error["message"]
    assert str(proj.resolve()) in error["message"]
    # ...and both ride as TYPED evidence (#687), because they are exactly the pair
    # a caller needs to do for itself the derivation ADR-0006 refuses to do for it:
    # walk up from the target to its own project.godot and re-issue with it.
    assert error["evidence"] == {
        "target_location": str(outsider.resolve()),
        "project_root": str(proj.resolve()),
    }
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
            json.dumps({"paths": [str(outsider)]}),
            "--project",
            str(proj),
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "target_outside_project"
    assert fake.calls == []


@pytest.mark.parametrize(
    "spelling",
    [
        "res://../outside.gd",
        # Godot folds `\\` to `/` across a res:// address before it collapses
        # anything (`String::simplify_path`, ustring.cpp:4192), so these name the
        # SAME file to the engine — a real 4.6.3 run loads it and reports back
        # `res://../outside.gd`. They bypassed the check the slash spelling is
        # refused by until the shared canonicalizer learned the fold (PR #766
        # round-2 review).
        "res://..\\outside.gd",
        "res://a\\..\\..\\outside.gd",
    ],
)
def test_script_validate_refuses_a_res_dotdot_escape_the_same_as_the_absolute_spelling(
    monkeypatch, tmp_path, spelling
):
    # #762: `path_outside_project` used to short-circuit EVERY res:// spelling as
    # inside, so the SAME file, addressed as `res://../outside.gd`, bypassed the
    # refusal the absolute spelling above already gets. Pinning both spellings in
    # one test — not two separate ones — is deliberate: it is exactly the
    # invariant that broke (same file, same command, opposite verdicts), so a
    # future change that fixes one spelling without the other fails HERE.
    proj = _project(tmp_path, "game")
    outsider = tmp_path / "outside.gd"  # one directory above the project root

    fake_abs = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )
    result_abs = CliRunner().invoke(
        app,
        ["script", "validate", str(outsider), "--project", str(proj), "--json"],
    )

    fake_res = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )
    result_res = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            spelling,
            "--project",
            str(proj),
            "--json",
        ],
    )

    error_abs = json.loads(result_abs.stdout)["error"]
    error_res = json.loads(result_res.stdout)["error"]
    assert result_abs.exit_code == result_res.exit_code == 4
    assert error_abs["code"] == error_res["code"] == "target_outside_project"
    assert error_abs["category"] == error_res["category"] == "operation"
    # Both spellings name the SAME underlying location in their message.
    assert str(outsider.resolve()) in error_abs["message"]
    assert str(outsider.resolve()) in error_res["message"]
    # Neither spelling reached the engine.
    assert fake_abs.calls == []
    assert fake_res.calls == []


def test_script_validate_reports_the_resolved_project_root(monkeypatch, tmp_path):
    # The result names the root its res:// dependencies resolved against, so a
    # reader can tell a real compile error from a wrong-project one without
    # re-deriving gda's resolution.
    proj = _project(tmp_path, "game")
    script = proj / "deck.gd"
    inject_runner(
        monkeypatch,
        RunResult(stdout=_validate_sentinel(_ok(str(script))), stderr="", exit_code=0),
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
    fake = inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("/tmp/proj/ok.gd")), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/ok.gd", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["project_root"] is None
    # The engine still ran: projectless is not a refusal.
    assert fake.calls == [
        ("script-validate", {"paths": ["/tmp/proj/ok.gd"], "all_scripts": False})
    ]


def test_script_validate_does_not_refuse_a_res_path(monkeypatch, tmp_path):
    # A WELL-FORMED res:// path addresses the resolved project by construction
    # (ADR-0006), so containment makes no filesystem claim about it and it is not
    # refused. That is no longer true of every res:// spelling (#762): one that
    # lexically escapes the namespace, e.g. `res://../outside.gd`, is refused —
    # see test_script_validate_refuses_a_res_dotdot_escape_the_same_as_the_absolute_spelling.
    proj = _project(tmp_path, "game")
    fake = inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("res://deck.gd")), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        ["script", "validate", "res://deck.gd", "--project", str(proj), "--json"],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        ("script-validate", {"paths": ["res://deck.gd"], "all_scripts": False})
    ]


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
    assert json.loads(result.stdout)["error"]["code"] == "target_outside_project"
    assert fake.calls == []


def test_script_validate_refuses_a_target_a_nested_project_owns(monkeypatch, tmp_path):
    # GDA-DF-035 reading 2, end to end: `outer` and `outer/inner` are both
    # projects, `inner/main.gd` preloads `res://local_dep.gd` meaning INNER's root.
    # Validated with --project outer the engine reported a cascade of false missing
    # -file errors for a file that is perfectly valid in its own project, and only
    # `project_root` hinted why. ADR-0006's 2026-08-31 amendment (#697) refuses
    # instead and names the owner to pass.
    outer = _project(tmp_path, "outer")
    inner = _project(tmp_path, "outer/inner")
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            str(inner / "main.gd"),
            "--project",
            str(outer),
            "--json",
        ],
    )

    assert result.exit_code == 4
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "target_outside_project"
    assert str(inner) in error["message"]
    # The owner is typed, because it is the one thing the caller has to retype.
    assert error["evidence"] == {
        "target_location": str((inner / "main.gd").resolve()),
        "project_root": str(outer.resolve()),
        "owning_project": str(inner.resolve()),
    }
    # Refused BEFORE the engine: the false cascade is never produced at all.
    assert fake.calls == []


def test_script_validate_names_a_res_target_s_real_location(monkeypatch, tmp_path):
    # The coordinate has to name a real place: it is what a caller walks up from to
    # find the owner for itself. Handing the `res://` string to a filesystem
    # anchoring made `Path("res://inner/main.gd")` the RELATIVE `res:/inner/main.gd`
    # and reported `<project>/res:/inner/main.gd`, a directory that does not exist —
    # in the human message and in the typed evidence alike.
    outer = _project(tmp_path, "outer")
    inner = _project(tmp_path, "outer/inner")
    inject_runner(monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "res://inner/main.gd",
            "--project",
            str(outer),
            "--json",
        ],
    )

    error = json.loads(result.stdout)["error"]
    assert error["code"] == "target_outside_project"
    assert error["evidence"]["target_location"] == str((inner / "main.gd").resolve())
    assert "res:" not in error["evidence"]["target_location"]


def test_script_validate_refuses_a_projectless_target_that_has_an_owner(
    monkeypatch, tmp_path
):
    # GDA-DF-035 reading 1 — the EXACT dogfooded invocation: a project nested in a
    # plain workspace, validated from the ancestor. Nothing resolves, so the
    # containment check had no root to be outside of and the file went to a
    # projectless engine, where its res:// references resolved against nothing and
    # produced the same cascade with `project_root: null` as the only clue.
    workspace = tmp_path / "workspace"
    game = _project(workspace, "game")
    monkeypatch.chdir(workspace)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["script", "validate", "game/main.gd", "--json"])

    assert result.exit_code == 4
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "target_outside_project"
    # No root resolved, so that coordinate is OMITTED rather than invented — and
    # the owner, the actionable one, is there.
    assert error["evidence"] == {
        "target_location": str((game / "main.gd").resolve()),
        "owning_project": str(game.resolve()),
    }
    assert fake.calls == []


def test_script_validate_still_validates_a_standalone_script_projectless(
    monkeypatch, tmp_path
):
    # The mode ADR-0006 keeps, and the boundary of the refusal above: a loose .gd
    # that no project.godot claims is still validated projectless by filesystem
    # path. The ownership probe must not turn the documented fallback into a
    # refusal for the files it exists to serve.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scratch.gd").write_text("extends Node\n", encoding="utf-8")
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=_validate_sentinel(_ok("scratch.gd")), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["script", "validate", "scratch.gd", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["project_root"] is None
    assert fake.calls, "a standalone script still reaches the engine"


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
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=_validate_sentinel(_ok("deck.gd")), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "deck.gd", "--project", "game", "--json"]
    )

    assert result.exit_code == 0, result.stdout
    # The op receives the path unchanged — the engine does the anchoring — and the
    # reported root is absolute, not the bare relative "game" the caller typed.
    assert fake.calls == [
        ("script-validate", {"paths": ["deck.gd"], "all_scripts": False})
    ]
    assert json.loads(result.stdout)["project_root"] == str(proj)


def test_script_validate_relative_target_parity_on_the_params_json_path(
    monkeypatch, tmp_path
):
    # ADR-0015 parity for the same shape: --params-json must anchor identically.
    proj = _ancestor_cwd_project(monkeypatch, tmp_path)
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=_validate_sentinel(_ok("deck.gd")), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "--params-json",
            json.dumps({"paths": ["deck.gd"]}),
            "--project",
            "game",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert fake.calls == [
        ("script-validate", {"paths": ["deck.gd"], "all_scripts": False})
    ]
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
    assert json.loads(result.stdout)["error"]["code"] == "target_outside_project"
    assert fake.calls == []


def test_script_validate_invalid_script_is_success_with_parsed_diagnostics(monkeypatch):
    # Validating an INVALID script is a SUCCESSFUL op (exit 0): the sentinel says
    # valid=false, and the per-command classifier parses the line/message
    # diagnostics from stderr (the only place they live) into the result.
    stderr = (
        "gda: validating: /tmp/proj/broken.gd\n"
        "SCRIPT ERROR: Parse Error: Expected expression for variable initial "
        'value after "=".\n'
        "          at: GDScript::reload (/tmp/proj/broken.gd:3)\n"
    )
    stdout = "Godot Engine v4.6.3.stable.official\n" + _validate_sentinel(
        _broken("/tmp/proj/broken.gd", "Parse error.")
    )
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr=stderr, exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/broken.gd", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is False
    entry = data["scripts"][0]
    assert entry["error_string"] == "Parse error."
    # The advisory diagnostics were parsed from stderr (line + message, no column).
    assert len(entry["diagnostics"]) == 1
    assert entry["diagnostics"][0]["line"] == 3
    assert entry["diagnostics"][0]["column"] is None
    assert "Expected expression" in entry["diagnostics"][0]["message"]
    assert fake.calls == [
        ("script-validate", {"paths": ["/tmp/proj/broken.gd"], "all_scripts": False})
    ]


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
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("/tmp/proj/ok.gd")), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(app, ["script", "validate", "/tmp/proj/ok.gd"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "valid /tmp/proj/ok.gd"


def test_script_validate_human_output_invalid_lists_diagnostics(monkeypatch):
    # An invalid result renders 'invalid <path>', the error_string, and each
    # advisory diagnostic as 'line N: message' (parsed from stderr).
    stderr = (
        "gda: validating: /tmp/proj/broken.gd\n"
        "SCRIPT ERROR: Parse Error: the message.\n"
        "          at: GDScript::reload (/tmp/proj/broken.gd:3)\n"
    )
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_broken("/tmp/proj/broken.gd", "Parse error.")),
            stderr=stderr,
            exit_code=0,
        ),
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
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_broken(str(script), "Parse error.")),
            stderr="",
            exit_code=0,
        ),
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
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_broken("/tmp/proj/broken.gd", "Parse error.")),
            stderr="",
            exit_code=0,
        ),
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


# --- script validate: batch and project mode (#663) ---------------------------
#
# One invocation validates N scripts in ONE engine launch, reporting per-file
# diagnostics plus one aggregate verdict. A single path is just a batch of one, so
# there is no second code path to keep in step.


def _validate_sentinel(*entries: dict, valid: bool | None = None) -> str:
    """The batch sentinel operations.gd emits: the aggregate plus per-script rows."""
    aggregate = all(entry["valid"] for entry in entries) if valid is None else valid
    return sentinel({"valid": aggregate, "scripts": list(entries)})


def _ok(path: str) -> dict:
    return {"path": path, "valid": True, "error_string": None}


def _broken(path: str, error: str = "Parse error") -> dict:
    return {"path": path, "valid": False, "error_string": error}


def test_script_validate_batch_reaches_the_engine_once_with_every_path(monkeypatch):
    # The #663 core: repeated PATH arguments become ONE op call carrying the whole
    # batch, so six related scripts cost one engine launch instead of six.
    fake = inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(
                _ok("/tmp/proj/a.gd"), _ok("/tmp/proj/b.gd"), _ok("/tmp/proj/c.gd")
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "/tmp/proj/a.gd",
            "/tmp/proj/b.gd",
            "/tmp/proj/c.gd",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "script-validate",
            {
                "paths": ["/tmp/proj/a.gd", "/tmp/proj/b.gd", "/tmp/proj/c.gd"],
                "all_scripts": False,
            },
        )
    ]
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert [entry["path"] for entry in data["scripts"]] == [
        "/tmp/proj/a.gd",
        "/tmp/proj/b.gd",
        "/tmp/proj/c.gd",
    ]


def test_script_validate_batch_aggregate_is_false_when_any_script_is_invalid(
    monkeypatch,
):
    # The aggregate verdict: false when ANY file is invalid, and the command still
    # exits 0 — an invalid script is a successful validation, the existing contract.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("/tmp/proj/a.gd"), _broken("/tmp/proj/b.gd")),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/a.gd", "/tmp/proj/b.gd", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert [entry["valid"] for entry in data["scripts"]] == [True, False]


def test_script_validate_batch_attributes_diagnostics_to_their_own_script(monkeypatch):
    # Per-FILE diagnostics: the engine marks each script's stderr window with its
    # own `gda: validating:` line, so the advisory line/message pairs land on the
    # script that produced them rather than on the batch as a whole.
    stderr = (
        "gda: running operation: script-validate\n"
        "gda: validating: /tmp/proj/a.gd\n"
        "gda: validating: /tmp/proj/b.gd\n"
        "SCRIPT ERROR: Parse Error: bad b\n"
        "   at: GDScript::reload (/tmp/proj/b.gd:3)\n"
        "gda: validating: /tmp/proj/c.gd\n"
        "SCRIPT ERROR: Parse Error: bad c\n"
        "   at: GDScript::reload (/tmp/proj/c.gd:7)\n"
    )
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(
                _ok("/tmp/proj/a.gd"),
                _broken("/tmp/proj/b.gd"),
                _broken("/tmp/proj/c.gd"),
            ),
            stderr=stderr,
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "/tmp/proj/a.gd",
            "/tmp/proj/b.gd",
            "/tmp/proj/c.gd",
            "--json",
        ],
    )

    assert result.exit_code == 0
    scripts = json.loads(result.stdout)["scripts"]
    assert scripts[0]["diagnostics"] == []
    assert scripts[1]["diagnostics"] == [
        {"line": 3, "column": None, "message": "Parse Error: bad b"}
    ]
    assert scripts[2]["diagnostics"] == [
        {"line": 7, "column": None, "message": "Parse Error: bad c"}
    ]


def test_script_validate_keeps_a_duplicate_path_as_its_own_entry(monkeypatch):
    # gda never silently drops an input: a path given twice is validated twice and
    # reported twice, so entry i always corresponds to argument i.
    fake = inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("/tmp/proj/a.gd"), _ok("/tmp/proj/a.gd")),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/a.gd", "/tmp/proj/a.gd", "--json"]
    )

    assert result.exit_code == 0
    assert fake.calls[0][1]["paths"] == ["/tmp/proj/a.gd", "/tmp/proj/a.gd"]
    assert len(json.loads(result.stdout)["scripts"]) == 2


def test_script_validate_refuses_a_batch_whose_second_path_is_outside_the_project(
    monkeypatch, tmp_path
):
    # ADR-0006's one resolved project applies to EVERY path in the batch: a batch
    # that spans projects is refused before the engine runs, reusing #658's refusal
    # rather than compiling the outsider against the wrong root.
    proj = _project(tmp_path, "game")
    inside = proj / "deck.gd"
    outsider = tmp_path / "elsewhere" / "card.gd"
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            str(inside),
            str(outsider),
            "--project",
            str(proj),
            "--json",
        ],
    )

    assert result.exit_code == 4
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "target_outside_project"
    assert str(outsider.resolve()) in error["message"]
    assert fake.calls == []


def test_script_validate_all_asks_the_engine_for_every_project_script(monkeypatch):
    # Project mode: `--all` carries no paths — the engine enumerates the project's
    # res:// tree itself and reports the same result shape.
    fake = inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("res://a.gd"), _ok("res://b.gd")),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(app, ["script", "validate", "--all", "--json"])

    assert result.exit_code == 0
    assert fake.calls == [("script-validate", {"paths": [], "all_scripts": True})]
    assert len(json.loads(result.stdout)["scripts"]) == 2


def test_script_validate_all_with_paths_is_a_usage_error(monkeypatch):
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "--all", "/tmp/proj/a.gd", "--json"]
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_script_validate_without_paths_or_all_is_a_usage_error(monkeypatch):
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["script", "validate", "--json"])

    assert result.exit_code == 2
    assert fake.calls == []


def test_script_validate_params_json_refuses_an_empty_batch(monkeypatch):
    # ADR-0015 parity: the rule lives on the model, so the JSON route reports it as
    # the structured invalid_params rather than as a usage error.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "--params-json",
            json.dumps({"paths": []}),
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_script_validate_params_json_refuses_paths_together_with_all(monkeypatch):
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel({}), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "validate",
            "--params-json",
            json.dumps({"paths": ["/tmp/proj/a.gd"], "all_scripts": True}),
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_script_validate_batch_human_output_leads_with_the_aggregate(monkeypatch):
    stderr = (
        "gda: validating: /tmp/proj/a.gd\n"
        "gda: validating: /tmp/proj/b.gd\n"
        "SCRIPT ERROR: Parse Error: bad b\n"
        "   at: GDScript::reload (/tmp/proj/b.gd:3)\n"
    )
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_ok("/tmp/proj/a.gd"), _broken("/tmp/proj/b.gd")),
            stderr=stderr,
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/a.gd", "/tmp/proj/b.gd"]
    )

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "invalid (1 of 2 scripts)",
        "  project: (none resolved: projectless)",
        "  valid /tmp/proj/a.gd",
        "  invalid /tmp/proj/b.gd",
        "    Parse error",
        "    line 3: Parse Error: bad b",
    ]


# The two `operations.gd` consts the per-file marker is composed from. Matched the
# way every other cross-language mirror in this repo is (cf. `HARNESS_LOG_MARKER`
# in tests/test_error_registry.py): extract the const's VALUE, so the pin survives
# any change to how or where the line is written and fails only when the CONTRACT
# moves.
_OPERATIONS_DIAG_PREFIX = re.compile(r'^const DIAG_PREFIX := "(.*)"$', re.MULTILINE)
_OPERATIONS_VALIDATE_MARKER = re.compile(
    r'^const VALIDATE_MARKER := "(.*)"$', re.MULTILINE
)


def _operations_const(pattern: re.Pattern[str], name: str) -> str:
    operations = (
        Path(__file__).resolve().parents[1] / "src" / "gda" / "ops" / "operations.gd"
    )
    match = pattern.search(operations.read_text(encoding="utf-8"))
    assert match is not None, f"{name} const missing from operations.gd"
    return match.group(1)


def test_validate_marker_mirrors_the_operations_gd_consts():
    # The cross-language half of the per-file attribution: the engine WRITES the
    # marker and Python READS it, so a drift in either spelling silently empties
    # every batch's diagnostics. The engine composes the line from two consts and
    # Python holds the composed prefix; this pins the composition.
    from gda.commands.script import VALIDATE_MARKER_PREFIX

    prefix = _operations_const(_OPERATIONS_DIAG_PREFIX, "DIAG_PREFIX")
    marker = _operations_const(_OPERATIONS_VALIDATE_MARKER, "VALIDATE_MARKER")

    assert prefix + marker == VALIDATE_MARKER_PREFIX


def test_validate_marker_is_recognised_by_the_parser_it_feeds():
    # The behavioural half of the same contract: the composed line the engine emits
    # is one the segment parser actually splits on. The equality above pins the
    # spelling; this pins that the spelling is the one the regex accepts, so a
    # future change to the pattern (an anchor, an escape) cannot pass the mirror
    # check while failing on real output.
    from gda.commands.script import parse_validate_segments

    prefix = _operations_const(_OPERATIONS_DIAG_PREFIX, "DIAG_PREFIX")
    marker = _operations_const(_OPERATIONS_VALIDATE_MARKER, "VALIDATE_MARKER")

    segments = parse_validate_segments(f"{prefix}{marker}res://a.gd\n")

    assert [path for path, _ in segments] == ["res://a.gd"]


def test_script_validate_attribution_is_dropped_when_the_stream_desynchronizes(
    monkeypatch,
):
    # The count guard, and it is a DEFENSIVE invariant rather than a fix for a
    # reachable defect: the op writes exactly one marker per verdict, so a stream
    # carrying a different number of them is not the stream this result came from.
    # Checking it makes such a stream degrade WHOLESALE — no advisory diagnostics
    # at all — instead of attaching the leading segments that happen to line up and
    # silently dropping the rest, which is a half-answer no reader can tell from a
    # complete one. The per-path guard stays: it is the one that catches a
    # substitution which keeps the count. The engine's `valid` is untouched either
    # way, so nothing about the verdict itself depends on this.
    stderr = (
        "gda: validating: /tmp/proj/a.gd\n"
        "SCRIPT ERROR: Parse Error: bad a\n"
        "   at: GDScript::reload (/tmp/proj/a.gd:3)\n"
        "gda: validating: /tmp/proj/b.gd\n"
        "SCRIPT ERROR: Parse Error: bad b\n"
        "   at: GDScript::reload (/tmp/proj/b.gd:4)\n"
        "gda: validating: /tmp/proj/unexpected.gd\n"
    )
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(
                _broken("/tmp/proj/a.gd"), _broken("/tmp/proj/b.gd")
            ),
            stderr=stderr,
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/a.gd", "/tmp/proj/b.gd", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert [entry["valid"] for entry in data["scripts"]] == [False, False]
    assert [entry["diagnostics"] for entry in data["scripts"]] == [[], []]


def test_script_validate_attributes_diagnostics_over_a_crlf_stream(monkeypatch):
    # Windows regression guard: the engine's C runtime writes stderr in TEXT mode,
    # so every `\n` reaches gda as `\r\n` — and the runner decodes raw bytes with
    # no newline translation, by design (a locale-aware decode mojibakes non-ASCII
    # paths). A marker pattern that let the `\r` into the captured path made the
    # attribution guard fail against every verdict, so EVERY validate on Windows —
    # batch and single-path alike — silently reported empty `diagnostics`. The
    # engine's own message must come through clean too: a trailing `\r` inside it
    # is not part of what the engine said.
    stderr = (
        "gda: running operation: script-validate\r\n"
        "gda: validating: /tmp/proj/broken.gd\r\n"
        "SCRIPT ERROR: Parse Error: bad token\r\n"
        "   at: GDScript::reload (/tmp/proj/broken.gd:3)\r\n"
    )
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=_validate_sentinel(_broken("/tmp/proj/broken.gd")),
            stderr=stderr,
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["script", "validate", "/tmp/proj/broken.gd", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["scripts"][0]["diagnostics"] == [
        {"line": 3, "column": None, "message": "Parse Error: bad token"}
    ]
