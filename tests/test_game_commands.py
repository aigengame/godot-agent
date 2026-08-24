"""`gda game` — the running game's runtime scene graph, served LIVE (#7, ADR-0019).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer→classify_live→JSON pipeline, and the no-daemon attach-or-fail path runs the
real ``DaemonRunner`` against an empty runtime dir. The real-engine round trip is
the e2e.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    GAME_GET_RESULT,
    GAME_RECT_RESULT,
    GAME_SET_RESULT,
    GAME_TREE_RESULT,
    error_sentinel,
    inject_live_runner,
    sentinel,
)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_game_tree_emits_runtime_tree_json_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_TREE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["root"]["name"] == "Main"
    assert data["root"]["children"][0]["type"] == "CharacterBody2D"
    # Routed through the LIVE seam, dispatching the game-tree operation (no args).
    assert fake.calls == [("game-tree", {})]


def test_game_tree_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run, against an empty runtime dir
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


def test_game_tree_schema_is_self_describing():
    result = CliRunner().invoke(app, ["game", "tree", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    # Self-describes its input and output contracts like any headless command.
    assert "input" in schema and "output" in schema


def test_game_tree_without_a_project_reports_project_not_found(monkeypatch, tmp_path):
    # No --project and a projectless cwd -> the project resolves to None, which is
    # a project-resolution error, NOT a daemon error (ADR-0021).
    monkeypatch.chdir(tmp_path)  # tmp_path holds no project.godot

    result = CliRunner().invoke(app, ["game", "tree", "--json"])

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_game_tree_on_non_unix_reports_live_unsupported_platform(monkeypatch, tmp_path):
    # The live stack is UNIX-only (UDS); a non-UNIX platform fails fast with the
    # typed error, before touching the daemon (ADR-0021).
    monkeypatch.setattr("gda.live_runner._is_unix", lambda: False)

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "live_unsupported_platform"


# --- game get (live runtime property read) -----------------------------------


def test_game_get_emits_runtime_properties_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_GET_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "get",
            "/root/Main/Player",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["path"] == "/root/Main/Player"
    assert data["type"] == "CharacterBody2D"
    assert {p["name"] for p in data["properties"]} == {"position", "visible"}
    # Routed through the LIVE seam, dispatching game-get with the node arg; the
    # optional property is absent (read the whole surface).
    assert fake.calls == [
        (
            "game-get",
            {"node": "/root/Main/Player", "property": None, "texture_digest": False},
        )
    ]


def test_game_get_passes_the_property_filter_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_GET_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "get",
            "/root/Main/Player",
            "--property",
            "position",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    # The filter is threaded to the operation params (the harness applies it).
    assert fake.calls == [
        (
            "game-get",
            {
                "node": "/root/Main/Player",
                "property": "position",
                "texture_digest": False,
            },
        )
    ]


def test_game_get_threads_the_texture_digest_opt_in(monkeypatch, tmp_path):
    # The #666 digest opt-in: --texture-digest rides the wire to the harness,
    # which threads it into the shared value projection; without the flag the
    # TextureProjection's digest field stays null (the GPU-to-CPU readback is
    # never paid silently).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_GET_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "get",
            "/root/Main/Player",
            "--property",
            "sprite_texture",
            "--texture-digest",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        (
            "game-get",
            {
                "node": "/root/Main/Player",
                "property": "sprite_texture",
                "texture_digest": True,
            },
        )
    ]


def test_game_get_schema_names_the_texture_projection(monkeypatch):
    # The TextureProjection shape is published beside the other named
    # projection kinds in the value field's $defs (ADR-0035 amendment #666),
    # so a schema client learns the shape without invoking gda.
    result = CliRunner().invoke(app, ["game", "get", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    defs = schema["output"]["$defs"]["NodeProperty"]["properties"]["value"]["$defs"]
    assert set(defs) >= {
        "ReferenceProjection",
        "TextureProjection",
        "InlineValueProjection",
    }
    texture = defs["TextureProjection"]["properties"]
    assert set(texture) == {"type", "width", "height", "object_string", "digest"}
    assert "resource_path" not in texture


def test_game_get_missing_node_reports_live_node_not_found(monkeypatch, tmp_path):
    # The harness reports its op-error as an exit-0 sentinel envelope (Finding B);
    # classify_live maps the LIVE-category code, so the exit is EXIT_LIVE — proving
    # the routing keeps it off the contract_violation fallthrough.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_node_not_found", "no node at runtime path"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "get",
            "/root/Main/Ghost",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_node_not_found"
    assert error["category"] == "live"


def test_game_get_unknown_property_reports_live_unknown_property(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_unknown_property", "no readable property"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "get",
            "/root/Main/Player",
            "--property",
            "nope",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_unknown_property"
    assert error["category"] == "live"


def test_game_get_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "game",
            "get",
            "/root/Main/Player",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


def test_game_get_schema_is_self_describing():
    result = CliRunner().invoke(app, ["game", "get", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


# --- game rect (live rendered Control rect read) -----------------------------


def test_game_rect_emits_rendered_control_rect_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_RECT_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "rect",
            "/root/Main/HUD/Stats",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data == GAME_RECT_RESULT
    assert fake.calls == [("game-rect", {"node": "/root/Main/HUD/Stats"})]


def test_game_rect_non_control_reports_live_not_control(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_not_control", "node is not a Control"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "rect",
            "/root/Main/Player",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_not_control"
    assert error["category"] == "live"


def test_game_rect_missing_node_reports_live_node_not_found(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_node_not_found", "no node at runtime path"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "rect",
            "/root/Main/Ghost",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_node_not_found"
    assert error["category"] == "live"


# --- game set (live runtime property write) ----------------------------------


def test_game_set_mutates_and_echoes_coerced_value_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_SET_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "position",
            "--value",
            "10,20",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["path"] == "/root/Main/Player"
    assert data["property"] == "position"
    # The harness echoes the coerced value in the node get projection.
    assert data["value"] == [10.0, 20.0]
    assert data["verified"] is True
    # The node arg, property and raw value are threaded to the operation params;
    # the harness coerces the string to the declared type.
    assert fake.calls == [
        (
            "game-set",
            {"node": "/root/Main/Player", "property": "position", "value": "10,20"},
        )
    ]


def test_game_set_missing_node_reports_live_node_not_found(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_node_not_found", "no node at runtime path"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "set",
            "/root/Main/Ghost",
            "--property",
            "position",
            "--value",
            "1,2",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_node_not_found"
    assert error["category"] == "live"


def test_game_set_unknown_property_reports_live_unknown_property(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_unknown_property", "no settable property"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "nope",
            "--value",
            "1",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_unknown_property"
    assert error["category"] == "live"


def test_game_set_uncoercible_value_reports_live_uncoercible_value(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_uncoercible_value", "cannot coerce value"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "position",
            "--value",
            "not-a-vector",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_uncoercible_value"
    assert error["category"] == "live"


def test_game_set_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "position",
            "--value",
            "1,2",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


def test_game_set_schema_is_self_describing():
    result = CliRunner().invoke(app, ["game", "set", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"
    value_description = schema["output"]["properties"]["value"]["description"]
    assert "observed read-back value" in value_description
    assert "coerced value" not in value_description
