"""`gda input` — runtime input simulation into the running game, LIVE (#221).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer→classify_live→JSON pipeline (mirroring ``test_game_commands`` /
``test_perf_commands``), and the no-daemon attach-or-fail path runs the real
``DaemonRunner`` against an empty runtime dir. Model-side validation (the modifier
set, button enum, strength range, sequence-event shape) is asserted on BOTH the
argv path (usage error, exit 2) and the ``--params-json`` path (structured
``invalid_params``). The real-engine round trip (push_input into a live session,
observed via ``game get``) is the e2e in ``test_e2e_input``.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    INPUT_ACTION_RESULT,
    INPUT_KEY_RESULT,
    INPUT_MOUSE_CLICK_RESULT,
    INPUT_MOUSE_MOVE_RESULT,
    INPUT_SEQUENCE_RESULT,
    error_sentinel,
    inject_live_runner,
    sentinel,
)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


# --- input key (single-frame) -------------------------------------------------


def test_input_key_injects_a_key_event_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["input", "key", "Right", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "key"
    assert data["key"] == "Right"
    assert data["pressed"] is True
    # Routed through the LIVE seam, dispatching input-key with the key arg and the
    # defaults (no modifiers, a press).
    assert fake.calls == [
        ("input-key", {"key": "Right", "modifiers": [], "released": False})
    ]


def test_input_key_threads_modifiers_and_released(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_KEY_RESULT), stderr="", exit_code=0),
    )

    CliRunner().invoke(
        app,
        [
            "input", "key", "A",
            "--modifiers", "shift", "--modifiers", "ctrl", "--released",
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert fake.calls == [
        ("input-key", {"key": "A", "modifiers": ["shift", "ctrl"], "released": True})
    ]


def test_input_key_unresolvable_name_reports_live_invalid_key(monkeypatch, tmp_path):
    # The harness reports its op-error as an exit-0 sentinel envelope; classify_live
    # maps the LIVE-category code, so the exit is EXIT_LIVE (the routing keeps it off
    # the contract_violation fallthrough).
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_invalid_key", "could not resolve key name"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["input", "key", "Nope", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_invalid_key"
    assert error["category"] == "live"


def test_input_key_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["input", "key", "Right", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"


def test_input_key_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "key", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


# --- input mouse click / move (single-frame) ----------------------------------


def test_input_mouse_click_injects_a_click_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_MOUSE_CLICK_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "mouse", "click", "100", "200",
            "--button", "right", "--double",
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "mouse_click"
    assert data["position"] == [100.0, 200.0]
    # The position, button, and double flag are threaded to the operation params.
    assert fake.calls == [
        (
            "input-mouse-click",
            {"x": 100.0, "y": 200.0, "button": "right", "double": True},
        )
    ]


def test_input_mouse_move_injects_a_motion_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_MOUSE_MOVE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "mouse", "move", "50", "60",
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "mouse_move"
    assert data["position"] == [50.0, 60.0]
    assert fake.calls == [("input-mouse-move", {"x": 50.0, "y": 60.0})]


def test_input_mouse_click_default_button_is_left(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_MOUSE_CLICK_RESULT), stderr="", exit_code=0),
    )

    CliRunner().invoke(
        app,
        ["input", "mouse", "click", "1", "2", "--project", str(_project(tmp_path)), "--json"],
    )

    assert fake.calls[0][1]["button"] == "left"
    assert fake.calls[0][1]["double"] is False


def test_input_mouse_click_unknown_button_argv_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_MOUSE_CLICK_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "mouse", "click", "1", "2", "--button", "scroll",
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_mouse_click_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "mouse", "click", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["kind"] == "live"


# --- input action (single-frame) ----------------------------------------------


def test_input_action_presses_an_action_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["input", "action", "jump", "--project", str(_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["action"] == "jump"
    assert data["pressed"] is True
    assert fake.calls == [
        ("input-action", {"action": "jump", "release": False, "strength": 1.0})
    ]


def test_input_action_release_and_strength_are_threaded(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    CliRunner().invoke(
        app,
        [
            "input", "action", "move_right", "--strength", "0.5",
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert fake.calls == [
        ("input-action", {"action": "move_right", "release": False, "strength": 0.5})
    ]


def test_input_action_unknown_action_reports_live_unknown_action(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_unknown_action", "no such action"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app, ["input", "action", "nope", "--project", str(_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_unknown_action"
    assert error["category"] == "live"


def test_input_action_strength_over_range_argv_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "action", "jump", "--strength", "2.0",
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_action_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "action", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["kind"] == "live"


# --- input sequence (multi-frame, time-windowed base) -------------------------


def test_input_sequence_injects_events_across_frames_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )
    events = [
        {"type": "key", "key": "Right", "frame": 0},
        {"type": "action", "action": "jump", "frame": 2},
        {"type": "mouse_click", "x": 1.0, "y": 2.0, "frame": 4},
    ]

    result = CliRunner().invoke(
        app,
        [
            "input", "sequence", "--events", json.dumps(events),
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "sequence"
    assert data["events"] == 3
    assert data["frames"] == 5
    # The whole events list is threaded to the operation; the model has normalized
    # each event (defaults filled, enums to their wire values).
    assert fake.calls[0][0] == "input-sequence"
    sent_events = fake.calls[0][1]["events"]
    assert [e["type"] for e in sent_events] == ["key", "action", "mouse_click"]
    assert [e["frame"] for e in sent_events] == [0, 2, 4]


def test_input_sequence_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "input", "sequence",
            "--events", json.dumps([{"type": "key", "key": "Right"}]),
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


def test_input_sequence_invalid_event_spec_reports_the_typed_error(monkeypatch, tmp_path):
    # A request that reached the harness without passing the model (a direct daemon
    # caller) with an unrecognized event type aborts the window with the typed code,
    # relayed exit-0 and mapped by classify_live.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_invalid_event_spec", "unsupported event type"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "sequence",
            "--events", json.dumps([{"type": "key", "key": "Right"}]),
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_invalid_event_spec"
    assert error["category"] == "live"


def test_input_sequence_non_json_events_argv_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["input", "sequence", "--events", "not json", "--project", str(_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_empty_events_argv_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["input", "sequence", "--events", "[]", "--project", str(_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_malformed_event_argv_is_a_usage_error(monkeypatch, tmp_path):
    # A 'key' event missing its 'key' field is malformed; the model rejects it, so
    # the argv path is a usage error (exit 2) and the engine is never reached.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "sequence",
            "--events", json.dumps([{"type": "key", "frame": 0}]),
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "sequence", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["kind"] == "live"


# --- model validation via --params-json (ADR-0015) ----------------------------
# The model is the input source of truth for BOTH paths; an out-of-contract
# --params-json object surfaces as the structured invalid_params error (exit 0,
# the error envelope), not a silent acceptance or a traceback.


def test_input_key_params_json_bad_modifier_is_invalid_params(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "key",
            "--params-json", '{"key": "A", "modifiers": ["control"]}',
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_action_params_json_strength_over_range_is_invalid_params(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "action",
            "--params-json", '{"action": "jump", "strength": 2.0}',
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_empty_events_is_invalid_params(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "sequence",
            "--params-json", '{"events": []}',
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_malformed_event_is_invalid_params(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "sequence",
            "--params-json", '{"events": [{"type": "mouse_click", "x": 1.0}]}',
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_key_params_json_dispatches_like_argv(monkeypatch, tmp_path):
    # A valid --params-json object dispatches through the SAME live seam the argv
    # path uses, so the two input paths are indistinguishable downstream (ADR-0015).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input", "key",
            "--params-json", '{"key": "Right", "modifiers": ["shift"]}',
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        ("input-key", {"key": "Right", "modifiers": ["shift"], "released": False})
    ]
