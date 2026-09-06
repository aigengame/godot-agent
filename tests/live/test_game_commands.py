"""`gda game` — the running game's runtime scene graph, served LIVE (#7, ADR-0019).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer→classify_live→JSON pipeline, and the no-daemon attach-or-fail path runs the
real ``DaemonRunner`` against an empty runtime dir. The real-engine round trip is
the e2e.
"""

import json

import jsonschema
import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    GAME_CALL_RESULT,
    GAME_GET_RESULT,
    GAME_RECT_RESULT,
    GAME_SET_RESULT,
    GAME_TREE_RESULT,
    GAME_TREE_TRUNCATED_RESULT,
    error_sentinel,
    inject_live_runner,
    panel_text,
    sentinel,
    usage_error_text,
    minimal_project,
)


def test_game_tree_emits_runtime_tree_json_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_TREE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(minimal_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["root"]["name"] == "Main"
    assert data["root"]["children"][0]["type"] == "CharacterBody2D"
    # AC3 (#849): an unbounded read gains only the two totals. No node carries
    # `children_omitted` — the key is ABSENT rather than zero, so the read a
    # caller did not bound does not grow by one key per node.
    assert data["truncated"] is False
    assert data["omitted_nodes"] == 0
    assert "children_omitted" not in data["root"]
    assert "children_omitted" not in data["root"]["children"][0]
    # Routed through the LIVE seam, dispatching the game-tree operation; both
    # bounding params ride unset, as `game get`'s optional filter does.
    assert fake.calls == [("game-tree", {"root": None, "max_depth": None})]


def test_game_tree_relays_the_bounding_options(monkeypatch, tmp_path):
    # #849: --root and --max-depth are threaded to the operation params; the
    # harness applies them (it owns the walk).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_TREE_TRUNCATED_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "tree",
            "--root",
            "/root/Main/HUD",
            "--max-depth",
            "1",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        ("game-tree", {"root": "/root/Main/HUD", "max_depth": 1}),
    ]


def test_game_tree_reports_the_omitted_counts_of_a_bounded_read(monkeypatch, tmp_path):
    # AC1 (#849): the partial read is never mistaken for a complete one — the
    # result totals the unserialized nodes and the node whose children were left
    # out says how many.
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_TREE_TRUNCATED_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "tree",
            "--root",
            "/root/Main/HUD",
            "--max-depth",
            "1",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["truncated"] is True
    assert data["omitted_nodes"] == 2
    children = data["root"]["children"]
    assert [child["name"] for child in children] == ["Panel", "Score", "Timer"]
    assert children[0]["children_omitted"] == 2
    # A node whose children were ALL serialized keeps the key absent.
    assert "children_omitted" not in children[1]
    assert "children_omitted" not in children[2]


def test_game_tree_renders_the_omission_for_a_human(monkeypatch, tmp_path):
    # Without --json the outline must not read as a complete tree: the total
    # rides one trailing line, so a truncated read is visible on both channels.
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_TREE_TRUNCATED_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "tree",
            "--max-depth",
            "1",
            "--project",
            str(minimal_project(tmp_path)),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "HUD (Control)" in result.stdout
    assert "truncated: 2 nodes omitted" in result.stdout


def test_game_tree_refuses_a_negative_max_depth(monkeypatch, tmp_path):
    # The bound is a depth, so a negative one is a usage error — before any
    # daemon is involved. Click's own `min=0` mirrors the model's `ge=0` and
    # decides first, so the message names the FLAG the caller typed; the model
    # still refuses the same value on the --params-json path (ADR-0015).
    result = CliRunner().invoke(
        app,
        [
            "game",
            "tree",
            "--max-depth",
            "-1",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert "--max-depth" in usage_error_text(result)


def test_game_tree_help_states_the_bounding_options():
    result = CliRunner().invoke(app, ["game", "tree", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    text = panel_text(result.stdout)
    assert "--root" in text and "--max-depth" in text
    # The unbounded default is the caller's choice, and help says so.
    assert "unbounded" in text


def test_game_tree_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run, against an empty runtime dir
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["game", "tree", "--project", str(minimal_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


def test_game_tree_schema_publishes_the_bounding_params_and_counts():
    # AC4 (#849): the two params and the two result totals are published, and
    # `children_omitted` rides the node shape as an OPTIONAL key — the presence
    # decision is part of the contract, not an implementation detail.
    result = CliRunner().invoke(app, ["game", "tree", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert {"root", "max_depth"} <= set(doc["input"]["properties"])
    assert {"truncated", "omitted_nodes"} <= set(doc["output"]["properties"])
    assert {"truncated", "omitted_nodes"} <= set(doc["output"]["required"])
    node = doc["output"]["$defs"]["GameNode"]
    assert "children_omitted" in node["properties"]
    assert "children_omitted" not in node.get("required", [])


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
        app, ["game", "tree", "--project", str(minimal_project(tmp_path)), "--json"]
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
    # digest is required-but-nullable (#736 review): the producer always emits
    # the key, so a payload missing it must fail the published shape — while
    # null stays a legal value (the opt-in absent, or readback unavailable).
    assert set(defs["TextureProjection"]["required"]) == {
        "type",
        "width",
        "height",
        "object_string",
        "digest",
    }
    digest_branch = defs["TextureProjection"]["properties"]["digest"]["anyOf"]
    assert {"type": "null"} in digest_branch


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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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


# --- game call: the declared read-only method surface (#673, ADR-0041) --------
# The live read `game get` cannot serve: a debug/state contract exposed as a
# METHOD. The attached-script chain declares what gda may call in its `GDA_CALLABLE`
# constant; gda calls nothing undeclared, and the three refusals are distinct.


def test_game_call_invokes_the_method_and_projects_its_return(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "/root/Main/QA",
            "--method",
            "qa_current_state_contract",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["path"] == "/root/Main/QA"
    assert data["method"] == "qa_current_state_contract"
    # The return rides the shared value projection: a Dictionary arrives
    # structured, not as a str() dump.
    assert data["value"] == {"phase": 3, "ready": True, "labels": ["a", "b"]}
    # No --args -> a null on the wire, the same full-model shape every other
    # dispatch_domain command in this group sends (cf. game get's property:
    # None). The harness treats any non-Array args as none, so the method is
    # called with no arguments.
    assert fake.calls == [
        (
            "game-call",
            {
                "node": "/root/Main/QA",
                "method": "qa_current_state_contract",
                "args": None,
            },
        )
    ]


def test_game_call_threads_json_args_as_values(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "/root/Main/QA",
            "--method",
            "with_args",
            "--args",
            '[2, "peak", {"deep": [1]}]',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    # JSON values reach the daemon model as values, never as the CLI string (no
    # property-coercion table here, ADR-0041). The Godot-side live parser later
    # materializes every JSON number as float; its type domain is pinned by e2e.
    assert fake.calls == [
        (
            "game-call",
            {
                "node": "/root/Main/QA",
                "method": "with_args",
                "args": [2, "peak", {"deep": [1]}],
            },
        )
    ]


def test_game_call_non_json_args_is_refused_before_the_wire(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "/root/Main/QA",
            "--method",
            "with_args",
            "--args",
            "not json",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_game_call_undeclared_method_reports_not_allowlisted(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_method_not_allowlisted",
                "the method undeclared_secret is not declared callable",
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "/root/Main/QA",
            "--method",
            "undeclared_secret",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE
    assert json.loads(result.stdout)["error"]["code"] == "live_method_not_allowlisted"


def test_game_call_distinguishes_missing_from_undeclared_and_bad_args(
    monkeypatch, tmp_path
):
    # The three refusals are distinct registered codes, each with its own
    # remediation (ADR-0041): fix the name, declare it, fix the arguments.
    for code, message in (
        ("live_unknown_method", "has no method named nope"),
        ("live_method_not_allowlisted", "is not declared callable"),
        ("live_invalid_call_args", "needs at least 1 argument(s)"),
    ):
        inject_live_runner(
            monkeypatch,
            RunResult(stdout=error_sentinel(code, message), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(
            app,
            [
                "game",
                "call",
                "/root/Main/QA",
                "--method",
                "whatever",
                "--project",
                str(minimal_project(tmp_path)),
                "--json",
            ],
        )
        assert result.exit_code == EXIT_LIVE
        error = json.loads(result.stdout)["error"]
        assert error["code"] == code, error
        assert error["category"] == "live"


def test_game_call_human_render_names_the_method_and_value(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "/root/Main/QA",
            "--method",
            "qa_current_state_contract",
            "--project",
            str(minimal_project(tmp_path)),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "call /root/Main/QA.qa_current_state_contract() ->" in result.stdout


def test_game_call_schema_publishes_the_declaration_contract():
    from gda.commands.game import MAX_EXACT_JSON_INT

    doc = json.loads(CliRunner().invoke(app, ["game", "call", "--schema"]).stdout)
    assert doc["kind"] == "live"
    assert {"node", "method", "args"} <= set(doc["input"]["properties"])
    # `method` is required (there is no default method); `args` is optional.
    assert set(doc["input"]["required"]) == {"node", "method"}
    assert {"path", "name", "type", "method", "value"} <= set(
        doc["output"]["properties"]
    )
    # The declaration site is named in the published contract, so an agent
    # reading only the schema learns why a call can be refused.
    assert "GDA_CALLABLE" in json.dumps(doc["input"]["properties"]["method"])

    # Standard JSON Schema has one mathematical number model: it cannot tell a
    # float token such as `1e17` from the equal integer value. The public schema
    # must therefore keep the high-range finite-float domain open and disclose
    # that the params model applies the safe bound only to values decoded as ints.
    validator = jsonschema.Draft202012Validator(doc["input"])
    assert validator.is_valid(
        {"node": "/root/M", "method": "m", "args": [MAX_EXACT_JSON_INT]}
    )
    assert validator.is_valid(
        {"node": "/root/M", "method": "m", "args": [-MAX_EXACT_JSON_INT]}
    )
    from gda.commands.game import GameCallParams

    for argument in (1e17, 2.5e17, 1e300, {"deep": [-1e300]}):
        payload = {"node": "/root/M", "method": "m", "args": [argument]}
        assert validator.is_valid(payload), argument
        GameCallParams.model_validate(payload)

    oversized_integer = {
        "node": "/root/M",
        "method": "m",
        "args": [MAX_EXACT_JSON_INT + 2],
    }
    # This standard-schema over-acceptance is deliberate and disclosed: adding
    # an integer maximum also rejects equal high-range floats, which the wire
    # carries exactly. The params model remains the execution authority.
    assert validator.is_valid(oversized_integer)
    with pytest.raises(ValueError, match=str(MAX_EXACT_JSON_INT)):
        GameCallParams.model_validate(oversized_integer)

    # The schema consumes RFC JSON data, whose number grammar excludes these
    # values. Some in-memory validators still accept Python's non-finite float
    # extensions as `number`; the params model is the execution authority and
    # refuses the permissive decoder extensions before the live wire.
    for non_finite in (float("nan"), float("inf"), float("-inf")):
        payload = {"node": "/root/M", "method": "m", "args": [non_finite]}
        assert validator.is_valid(payload)
        with pytest.raises(ValueError, match="finite"):
            GameCallParams.model_validate(payload)

    args_description = doc["input"]["properties"]["args"]["description"]
    number_description = next(
        branch
        for branch in doc["input"]["$defs"]["LiveCallArgument"]["anyOf"]
        if branch.get("type") == "number"
    )["description"]
    assert "finite float values are not subject" in args_description.lower()
    assert "JSON Schema cannot distinguish" in args_description
    assert "in-memory validators" in args_description
    assert "small-magnitude" in args_description
    assert "1.2345678901234567e-300" in args_description
    assert "0.0" in args_description
    assert "REFUSED here" in args_description
    assert "in-memory JSON Schema validators" in number_description
    # The DECIDED contract, not a defect pointer (#752): the refusal on the
    # request side and the exactness guarantee on the result side.
    assert "reads as 0.0 is refused" in number_description
    # Exact APART FROM the disclosed residual: the same schema now publishes
    # the negative-zero caveat on the result value, so an absolute claim here
    # would contradict it (#770 review).
    assert (
        "Every float a live reply RETURNS is exact, apart from a NEGATIVE ZERO"
        in number_description
    )


def test_game_call_help_publishes_the_safe_integer_bound_without_duplicate_words():
    from gda.commands.game import MAX_EXACT_JSON_INT

    result = CliRunner().invoke(app, ["game", "call", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    # Help is rendered inside a Rich panel: colour codes and box rules land in
    # the middle of sentences, so normalize before asserting on prose (the shared
    # tests/support normalizer, not a private copy of it).
    rendered = panel_text(result.stdout)
    assert str(MAX_EXACT_JSON_INT) in rendered
    assert "finite floats are not subject to the integer" in rendered
    assert "integer values must stay within" in rendered
    assert "parser reads as 0.0 is refused too" in rendered
    assert "1.2345678901234567e-300" in rendered
    assert "ULP" in rendered  # the disclosed residual on values the wire DOES carry
    assert "an an argument" not in rendered


def test_game_call_refuses_non_finite_args_on_both_paths(monkeypatch, tmp_path):
    # #749 review: JSON has no NaN/Infinity literals, but Python's decoder
    # accepts them and an Any field keeps them — and the frame the daemon then
    # writes is unreadable to the harness, so the caller waits out the relay
    # bound, gets live_timeout, and the session is retired (state lost). The
    # params model is the one authority both paths share (ADR-0015), so both
    # are refused structurally, before the wire.
    project = str(minimal_project(tmp_path))
    for argv in (
        ["--method", "m", "--args", "[NaN]"],
        ["--method", "m", "--args", '[{"deep": [Infinity]}]'],
    ):
        fake = inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(
            app,
            ["game", "call", "/root/M", *argv, "--project", project, "--json"],
        )
        assert result.exit_code != 0, result.stdout
        # Nothing reached the live channel.
        assert fake.calls == [], argv

    # Pure --params-json: adding the positional node would stop at the
    # mutual-exclusion usage error instead of testing the shared model.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )
    params_refused = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "--params-json",
            '{"node": "/root/M", "method": "m", "args": [NaN]}',
            "--project",
            project,
            "--json",
        ],
    )
    assert params_refused.exit_code != 0, params_refused.stdout
    assert json.loads(params_refused.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_game_call_accepts_finite_nested_json_args(monkeypatch, tmp_path):
    # The guard bounds only what cannot cross the wire: ordinary nested JSON
    # (including floats) still rides through untouched.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "/root/M",
            "--method",
            "m",
            "--args",
            '[1, 2.5, {"a": [3.5, "x"]}]',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls[0][1]["args"] == [1, 2.5, {"a": [3.5, "x"]}]


def test_game_call_accepts_large_finite_float_args_on_both_paths(monkeypatch, tmp_path):
    """High-range floats already are binary64 and do not inherit the int bound."""
    project = str(minimal_project(tmp_path))
    expected = [1e17, 2.5e17, {"deep": [1e300]}]

    invocations = (
        [
            "game",
            "call",
            "/root/M",
            "--method",
            "m",
            "--args",
            '[1e17, 2.5e17, {"deep": [1e300]}]',
            "--project",
            project,
            "--json",
        ],
        [
            "game",
            "call",
            "--params-json",
            '{"node": "/root/M", "method": "m", '
            '"args": [1e17, 2.5e17, {"deep": [1e300]}]}',
            "--project",
            project,
            "--json",
        ],
    )
    for invocation in invocations:
        fake = inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(app, invocation)

        assert result.exit_code == 0, result.stdout + result.stderr
        assert fake.calls[0][1]["args"] == expected


def test_game_call_refuses_integers_beyond_the_exact_json_range(monkeypatch, tmp_path):
    # #749 re-review: the live wire reads JSON numbers as doubles, so an integer
    # past the exact-integer range arrives CHANGED and the call succeeds on a
    # value the caller never sent. Refused in the params model, so both paths and
    # nested positions are covered; the boundary value still rides through.
    from gda.commands.game import MAX_EXACT_JSON_INT

    project = str(minimal_project(tmp_path))
    for argv in (
        ["--method", "m", "--args", f"[{MAX_EXACT_JSON_INT + 2}]"],
        ["--method", "m", "--args", f"[-{MAX_EXACT_JSON_INT + 2}]"],
        ["--method", "m", "--args", f'[{{"deep": [{MAX_EXACT_JSON_INT + 2}]}}]'],
    ):
        fake = inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(
            app,
            ["game", "call", "/root/M", *argv, "--project", project, "--json"],
        )
        assert result.exit_code != 0, result.stdout
        assert fake.calls == [], argv

    # `--params-json` supplies every operation argument. Do not combine it with
    # the positional node: that only tests the mutual-exclusion `usage_error`
    # and never reaches this validator (#749 third review).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
    )
    params_refused = CliRunner().invoke(
        app,
        [
            "game",
            "call",
            "--params-json",
            f'{{"node": "/root/M", "method": "m", "args": [{MAX_EXACT_JSON_INT + 2}]}}',
            "--project",
            project,
            "--json",
        ],
    )
    assert params_refused.exit_code != 0, params_refused.stdout
    error = json.loads(params_refused.stdout)["error"]
    assert error["code"] == "invalid_params"
    assert str(MAX_EXACT_JSON_INT) in error["message"]
    assert fake.calls == []

    # Both boundaries are representable and go through unchanged on the normal
    # argv path.
    for boundary in (MAX_EXACT_JSON_INT, -MAX_EXACT_JSON_INT):
        fake = inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(GAME_CALL_RESULT), stderr="", exit_code=0),
        )
        ok = CliRunner().invoke(
            app,
            [
                "game",
                "call",
                "/root/M",
                "--method",
                "m",
                "--args",
                f"[{boundary}]",
                "--project",
                project,
                "--json",
            ],
        )
        assert ok.exit_code == 0, ok.stdout + ok.stderr
        assert fake.calls[0][1]["args"] == [boundary]
