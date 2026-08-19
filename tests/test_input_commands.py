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
import re

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.models import MAX_WINDOW_FRAMES
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
            "input",
            "key",
            "A",
            "--modifiers",
            "shift",
            "--modifiers",
            "ctrl",
            "--released",
            "--project",
            str(_project(tmp_path)),
            "--json",
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


# --- input mouse-click / mouse-move (single-frame) ----------------------------


def test_input_mouse_click_injects_a_click_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_MOUSE_CLICK_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "mouse-click",
            "100",
            "200",
            "--button",
            "right",
            "--double",
            "--project",
            str(_project(tmp_path)),
            "--json",
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


def test_input_mouse_help_documents_tracked_position_limitation():
    click = CliRunner().invoke(app, ["input", "mouse-click", "--help"])
    move = CliRunner().invoke(app, ["input", "mouse-move", "--help"])

    assert click.exit_code == 0, click.stdout + click.stderr
    assert move.exit_code == 0, move.stdout + move.stderr
    for result in (click, move):
        assert "mouse event" in result.stdout
        assert "position" in result.stdout
        assert "get_mouse_position()" in result.stdout
        assert "get_global_mouse_position()" in result.stdout
        assert "stale in daemon sessions" in result.stdout


def test_input_mouse_move_injects_a_motion_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_MOUSE_MOVE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "mouse-move",
            "50",
            "60",
            "--project",
            str(_project(tmp_path)),
            "--json",
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
        [
            "input",
            "mouse-click",
            "1",
            "2",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
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
            "input",
            "mouse-click",
            "1",
            "2",
            "--button",
            "scroll",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_mouse_click_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "mouse-click", "--schema"])

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
            "input",
            "action",
            "move_right",
            "--strength",
            "0.5",
            "--project",
            str(_project(tmp_path)),
            "--json",
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
            "input",
            "action",
            "jump",
            "--strength",
            "2.0",
            "--project",
            str(_project(tmp_path)),
            "--json",
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
            "input",
            "sequence",
            "--events",
            json.dumps(events),
            "--project",
            str(_project(tmp_path)),
            "--json",
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


def test_input_sequence_physics_frame_offsets_dispatch_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    **INPUT_SEQUENCE_RESULT,
                    "clock": "physics",
                    "events": 2,
                    "frames": 13,
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )
    events = [
        {"type": "action", "action": "move_right", "physics_frame": 0},
        {
            "type": "action",
            "action": "move_right",
            "release": True,
            "physics_frame": 12,
        },
    ]

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps(events),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["clock"] == "physics"
    assert data["events"] == 2
    assert data["frames"] == 13
    assert fake.calls[0][0] == "input-sequence"
    sent_events = fake.calls[0][1]["events"]
    assert [e["physics_frame"] for e in sent_events] == [0, 12]
    assert [e["frame"] for e in sent_events] == [None, None]


def test_input_sequence_accepts_mouse_button_press_move_release(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    **INPUT_SEQUENCE_RESULT,
                    "events": 4,
                    "frames": 4,
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )
    events = [
        {"type": "mouse_button", "x": 10.0, "y": 10.0, "pressed": True, "frame": 0},
        {"type": "mouse_move", "x": 40.0, "y": 20.0, "frame": 1},
        {"type": "mouse_move", "x": 70.0, "y": 50.0, "frame": 2},
        {"type": "mouse_button", "x": 70.0, "y": 50.0, "release": True, "frame": 3},
    ]

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps(events),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    sent_events = fake.calls[0][1]["events"]
    assert [e["type"] for e in sent_events] == [
        "mouse_button",
        "mouse_move",
        "mouse_move",
        "mouse_button",
    ]
    assert sent_events[0]["button"] == "left"
    assert sent_events[0]["pressed"] is True
    assert sent_events[0]["release"] is False
    assert sent_events[3]["button"] == "left"
    assert sent_events[3]["pressed"] is False
    assert sent_events[3]["release"] is True


def test_input_sequence_with_no_daemon_reports_daemon_not_running(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps([{"type": "key", "key": "Right"}]),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


def test_input_sequence_invalid_event_spec_reports_the_typed_error(
    monkeypatch, tmp_path
):
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
            "input",
            "sequence",
            "--events",
            json.dumps([{"type": "key", "key": "Right"}]),
            "--project",
            str(_project(tmp_path)),
            "--json",
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
        [
            "input",
            "sequence",
            "--events",
            "not json",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
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
        [
            "input",
            "sequence",
            "--events",
            "[]",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
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
            "input",
            "sequence",
            "--events",
            json.dumps([{"type": "key", "frame": 0}]),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_over_window_frame_argv_is_a_usage_error(monkeypatch, tmp_path):
    # A sequence whose window (max frame + 1) exceeds MAX_WINDOW_FRAMES would
    # monopolise the serialised live session (the time-windowed base has no
    # harness-side timeout). The model bounds it, so the argv path is a usage error
    # (exit 2) and the engine is never reached.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps([{"type": "key", "key": "Right", "frame": 999999}]),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_over_window_physics_frame_argv_is_a_usage_error(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {
                        "type": "action",
                        "action": "move_right",
                        "physics_frame": 999999,
                    }
                ]
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_mixed_process_and_physics_clocks_argv_is_a_usage_error(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "key", "key": "Right", "frame": 0},
                    {
                        "type": "action",
                        "action": "move_right",
                        "physics_frame": 1,
                    },
                ]
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_sequence_at_the_window_boundary_argv_is_accepted(monkeypatch, tmp_path):
    # The largest accepted relative frame is MAX_WINDOW_FRAMES - 1 (window ==
    # MAX_WINDOW_FRAMES). It passes the model and reaches the live seam unchanged.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps(
                [{"type": "key", "key": "Right", "frame": MAX_WINDOW_FRAMES - 1}]
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls[0][0] == "input-sequence"
    assert fake.calls[0][1]["events"][0]["frame"] == MAX_WINDOW_FRAMES - 1


def test_input_sequence_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "sequence", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert schema["kind"] == "live"
    events_description = schema["input"]["properties"]["events"]["description"]
    assert "process-clock `frame`" in events_description
    assert "physics-clock `physics_frame`" in events_description
    # The kinds are enumerated by the union's discriminator mapping (#669), and
    # each variant carries the clock descriptions the whole union shares.
    variants = _variants()
    assert "mouse_button" in variants
    key_props = variants["key"]["properties"]
    assert "harness/process-frame" in key_props["frame"]["description"]
    assert "physics-frame" in key_props["physics_frame"]["description"]
    assert (
        "one of `pressed` or `release`"
        in variants["mouse_button"]["properties"]["pressed"]["description"]
    )


def test_input_sequence_help_names_process_and_physics_clocks():
    result = CliRunner().invoke(app, ["input", "sequence", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "harness/process-frame" in result.stdout
    assert "physics_frame" in result.stdout
    assert "mouse_button" in result.stdout


def test_input_sequence_help_documents_mouse_tracked_position_limitation():
    result = CliRunner().invoke(app, ["input", "sequence", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "mouse_click" in result.stdout
    assert "mouse_move" in result.stdout
    assert "mouse event" in result.stdout
    assert "position" in result.stdout
    assert "get_mouse_position()" in result.stdout
    assert "get_global_mouse_position()" in result.stdout
    assert "stale in" in result.stdout
    assert "daemon sessions" in result.stdout


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
            "input",
            "key",
            "--params-json",
            '{"key": "A", "modifiers": ["control"]}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_action_params_json_strength_over_range_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "action",
            "--params-json",
            '{"action": "jump", "strength": 2.0}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_empty_events_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            '{"events": []}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_malformed_event_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            '{"events": [{"type": "mouse_click", "x": 1.0}]}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_mouse_button_without_phase_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            '{"events": [{"type": "mouse_button", "x": 1.0, "y": 2.0}]}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_mouse_button_conflicting_phase_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            (
                '{"events": [{"type": "mouse_button", "x": 1.0, "y": 2.0, '
                '"pressed": true, "release": true}]}'
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_mouse_button_pressed_false_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            (
                '{"events": [{"type": "mouse_button", "x": 1.0, "y": 2.0, '
                '"pressed": false}]}'
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_pressed_on_mouse_move_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            '{"events": [{"type": "mouse_move", "x": 1.0, "y": 2.0, "pressed": true}]}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_over_window_frame_is_invalid_params(
    monkeypatch, tmp_path
):
    # The same window bound as the argv path, surfaced as the structured
    # invalid_params on --params-json (ADR-0015): a frame whose window exceeds
    # MAX_WINDOW_FRAMES never reaches the engine.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            json.dumps({"events": [{"type": "key", "key": "Right", "frame": 999999}]}),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_mixed_clock_fields_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            json.dumps(
                {
                    "events": [
                        {
                            "type": "action",
                            "action": "move_right",
                            "frame": 0,
                            "physics_frame": 0,
                        }
                    ]
                }
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_input_sequence_params_json_at_the_window_boundary_dispatches(
    monkeypatch, tmp_path
):
    # The boundary frame (window == MAX_WINDOW_FRAMES) passes the model and
    # dispatches through the same live seam the argv path uses.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            json.dumps(
                {
                    "events": [
                        {"type": "key", "key": "Right", "frame": MAX_WINDOW_FRAMES - 1}
                    ]
                }
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls[0][0] == "input-sequence"


def test_input_sequence_params_json_physics_frame_dispatches(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    **INPUT_SEQUENCE_RESULT,
                    "clock": "physics",
                    "events": 2,
                    "frames": 31,
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            json.dumps(
                {
                    "events": [
                        {
                            "type": "action",
                            "action": "move_right",
                            "physics_frame": 0,
                        },
                        {
                            "type": "action",
                            "action": "move_right",
                            "release": True,
                            "physics_frame": 30,
                        },
                    ]
                }
            ),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["clock"] == "physics"
    assert fake.calls[0][0] == "input-sequence"
    assert [e["physics_frame"] for e in fake.calls[0][1]["events"]] == [0, 30]


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
            "input",
            "key",
            "--params-json",
            '{"key": "Right", "modifiers": ["shift"]}',
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        ("input-key", {"key": "Right", "modifiers": ["shift"], "released": False})
    ]


# --- the sequence event is a discriminated union (#669) ------------------------
#
# GDA-DF-037 / GDA-DF-032: one flat event shape carried every kind's fields, so
# the per-kind rules lived only in prose — `pressed` is valid on `mouse_button`
# alone, an action presses by default and releases with `release`, and a key
# releases with `released`. Schema-driven automation could not tell the kinds
# apart without a failed invocation, and a foreign field was silently accepted
# and ignored (a `release` on a key event PRESSED the key).


def _sequence_events_schema() -> dict:
    result = CliRunner().invoke(app, ["input", "sequence", "--schema"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)["input"]


def _variants() -> dict[str, dict]:
    """Each event kind's variant schema, resolved through the discriminator."""
    schema = _sequence_events_schema()
    mapping = schema["properties"]["events"]["items"]["discriminator"]["mapping"]
    return {
        kind: schema["$defs"][ref.rsplit("/", 1)[-1]] for kind, ref in mapping.items()
    }


def test_sequence_events_are_published_as_a_discriminated_union():
    # The kinds are machine-discoverable: one `oneOf` branch per kind, selected
    # by the `type` discriminator — not a single shape plus prose.
    items = _sequence_events_schema()["properties"]["events"]["items"]

    assert items["discriminator"]["propertyName"] == "type"
    assert set(items["discriminator"]["mapping"]) == {
        "key",
        "mouse_click",
        "mouse_button",
        "mouse_move",
        "action",
    }
    assert len(items["oneOf"]) == 5


def test_each_event_kind_publishes_its_required_and_forbidden_fields():
    # A schema client can decide each kind's valid fields without a trial
    # invocation: what it MUST carry, and that nothing else is accepted.
    variants = _variants()

    assert set(variants["key"]["required"]) == {"type", "key"}
    assert set(variants["action"]["required"]) == {"type", "action"}
    assert set(variants["mouse_click"]["required"]) == {"type", "x", "y"}
    assert set(variants["mouse_move"]["required"]) == {"type", "x", "y"}
    assert set(variants["mouse_button"]["required"]) == {"type", "x", "y"}

    for kind, variant in variants.items():
        assert variant["additionalProperties"] is False, kind

    # `pressed` belongs to `mouse_button` alone; an action releases with
    # `release`, a key with `released`.
    assert "pressed" in variants["mouse_button"]["properties"]
    assert "pressed" not in variants["action"]["properties"]
    assert "pressed" not in variants["key"]["properties"]
    assert "pressed" not in variants["mouse_move"]["properties"]
    assert "release" in variants["action"]["properties"]
    assert "released" in variants["key"]["properties"]
    assert "released" not in variants["action"]["properties"]
    # Both clocks stay shared by every kind.
    for kind, variant in variants.items():
        assert {"frame", "physics_frame"} <= set(variant["properties"]), kind


def test_a_schema_client_can_validate_events_without_invoking_gda():
    # The acceptance property for the per-kind FIELD SETS, checked the way a
    # client would: validate candidate events against the EMITTED schema and get
    # the same verdict gda gives for what each kind requires and forbids. The
    # cross-field rules are a narrower claim — the mouse-button phase is published
    # too (its own test below), while the one-clock rule, the modifier vocabulary
    # and the window ceiling stay enforced model-side only.
    import jsonschema

    schema = _sequence_events_schema()

    def check(event: dict) -> bool:
        try:
            jsonschema.validate(instance={"events": [event]}, schema=schema)
        except jsonschema.ValidationError:
            return False
        return True

    assert check({"type": "action", "action": "jump"})
    assert check({"type": "action", "action": "jump", "release": True, "frame": 10})
    assert check({"type": "mouse_button", "x": 1.0, "y": 2.0, "pressed": True})
    # …and the mistakes the flat shape used to swallow are rejected.
    assert not check({"type": "action", "action": "jump", "pressed": True})
    assert not check({"type": "key", "key": "A", "release": True})
    assert not check({"type": "mouse_move", "x": 1.0, "y": 2.0, "pressed": True})
    assert not check({"type": "key"})


def _reject(monkeypatch, tmp_path, event: dict) -> str:
    """Run one malformed event through --params-json; return the error message."""
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )
    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            json.dumps({"events": [event]}),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "invalid_params", payload
    assert fake.calls == []
    return payload["error"]["message"]


def test_a_wrong_kind_field_rejection_names_the_accepted_field(monkeypatch, tmp_path):
    # The rejection already fired; it did not say what to write instead.
    message = _reject(
        monkeypatch, tmp_path, {"type": "action", "action": "j", "pressed": True}
    )

    assert "'pressed'" in message
    assert "'release'" in message
    assert "action" in message


def test_a_wrong_kind_field_rejection_names_the_key_events_own_phase_field(
    monkeypatch, tmp_path
):
    # The reverse mistake: an action's `release` on a key event, which used to be
    # accepted and silently PRESS the key.
    message = _reject(
        monkeypatch, tmp_path, {"type": "key", "key": "A", "release": True}
    )

    assert "'release'" in message
    assert "'released'" in message


def test_a_phaseless_kind_rejection_points_at_the_kind_that_has_a_phase(
    monkeypatch, tmp_path
):
    # `mouse_click` / `mouse_move` have no press/release phase at all; the
    # rejection names the kind that does rather than a field they lack.
    message = _reject(
        monkeypatch,
        tmp_path,
        {"type": "mouse_move", "x": 1.0, "y": 2.0, "pressed": True},
    )

    assert "'pressed'" in message
    assert "mouse_button" in message


def test_an_unknown_field_rejection_lists_the_kinds_accepted_fields(
    monkeypatch, tmp_path
):
    message = _reject(monkeypatch, tmp_path, {"type": "key", "key": "A", "keycode": 65})

    assert "'keycode'" in message
    assert "'key'" in message


# The SGR colour sequences the help renderer emits when it believes it is writing
# to a terminal. It believes that on GitHub Actions but not in a local run, so a
# test that reads the rendered help must strip them or it passes locally and fails
# only in CI.
_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")


def test_input_sequence_help_carries_a_copyable_action_example():
    # The help showed only a mouse example, so an action sequence had to be
    # inferred (GDA-DF-032). It now shows the press / release pair too.
    result = CliRunner().invoke(app, ["input", "sequence", "--help"])

    assert result.exit_code == 0, result.stdout
    # The help renderer wraps the example across the option column and frames it
    # with box borders (and colours it); normalizing all three back out is what a
    # reader copying the example does. Nothing is ELLIPSIZED away — the whole
    # example survives, which the one-line spelling it replaced did not.
    plain = _ANSI_SGR.sub("", result.stdout).replace("│", " ")
    rendered = " ".join(plain.split())
    assert '{"type": "action", "action": "jump", "frame": 0}' in rendered
    assert (
        '{"type": "action", "action": "jump", "release": true, "frame": 10}' in rendered
    )
    # …beside the mouse example it joins, likewise intact.
    assert '{"type": "mouse_button", "x": 10, "y": 10, "pressed": true}' in rendered


def test_an_unknown_event_type_lists_the_kinds_a_caller_can_type(monkeypatch, tmp_path):
    # The union refuses an unknown `type` by listing the expected tags. They must
    # read as the WIRE values a caller writes — a bare enum would put
    # "<InputEventType.KEY: 'key'>" into a public message, naming a Python symbol
    # that is not typeable in a request.
    message = _reject(monkeypatch, tmp_path, {"type": "nope", "key": "A"})

    assert "'key', 'mouse_click', 'mouse_button', 'mouse_move', 'action'" in message
    assert "InputEventType" not in message


# The mouse-button phase corpus, spanning every combination the two fields can be
# written in. The point is not any single verdict but that ONE corpus gets the
# SAME verdict from the published schema and from the model.
_PHASE_CORPUS = [
    {"pressed": True},
    {"release": True},
    {"pressed": True, "release": False},
    {"pressed": None, "release": True},
    {},
    {"pressed": False},
    {"pressed": False, "release": True},
    {"pressed": True, "release": True},
    {"release": False},
    {"pressed": None},
]


def test_the_mouse_button_phase_rule_is_checkable_and_matches_the_model():
    # #669: `mouse_button` is the kind an agent reaches for to build a drag, and
    # its "exactly one of `pressed: true` / `release: true`" rule used to live only
    # in prose — so a schema-driven client learned it from a failed invocation
    # (GDA-DF-037). It is now published as schema, and this pins the published rule
    # to the enforcing validator so the two cannot drift apart.
    import jsonschema

    from gda.commands.input import InputSequenceParams

    schema = _sequence_events_schema()
    for phase in _PHASE_CORPUS:
        event = {"type": "mouse_button", "x": 1.0, "y": 2.0, **phase}
        try:
            jsonschema.validate(instance={"events": [event]}, schema=schema)
            by_schema = True
        except jsonschema.ValidationError:
            by_schema = False
        try:
            InputSequenceParams.model_validate({"events": [event]})
            by_model = True
        except ValueError:
            by_model = False
        assert by_schema == by_model, (phase, by_schema, by_model)
    # …and the corpus really does span both verdicts, so agreement is not vacuous.
    accepted = [p for p in _PHASE_CORPUS if p in ({"pressed": True}, {"release": True})]
    assert accepted


def test_an_explicit_null_button_still_means_the_left_button(monkeypatch, tmp_path):
    # The flat shape these variants replace defaulted `button` to null and let the
    # harness read that as left, so a producer that dumped an event and replayed it
    # sent an explicit null. It stays accepted, and normalizes to a named button.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_SEQUENCE_RESULT), stderr="", exit_code=0),
    )
    events = [
        {"type": "mouse_click", "x": 1.0, "y": 2.0, "button": None},
        {"type": "mouse_button", "x": 1.0, "y": 2.0, "button": None, "pressed": True},
    ]

    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--events",
            json.dumps(events),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [e["button"] for e in fake.calls[0][1]["events"]] == ["left", "left"]


def test_every_phase_synonym_is_a_field_some_event_kind_declares():
    # The rejection names a kind's OWN press/release spelling by intersecting the
    # phase synonyms with the variant's fields. That list is the one thing about
    # the union written down separately, so hold it to what the variants declare:
    # renaming `released` without updating it would silently drop the message back
    # to the generic branch, with no test noticing.
    from gda.commands.input import _PHASE_FIELDS, _SEQUENCE_EVENT_MODELS, _event_kind

    declared = {f for model in _SEQUENCE_EVENT_MODELS for f in model.model_fields}
    assert set(_PHASE_FIELDS) <= declared, set(_PHASE_FIELDS) - declared
    # …and every kind that carries a phase is reachable through it: the three
    # phase-bearing kinds each intersect the list, the two phaseless ones do not.
    with_phase = {
        _event_kind(m)
        for m in _SEQUENCE_EVENT_MODELS
        if set(_PHASE_FIELDS) & set(m.model_fields)
    }
    assert with_phase == {"key", "action", "mouse_button"}


def test_the_union_members_are_read_off_the_union_itself():
    # `_SEQUENCE_EVENT_MODELS` feeds every "is accepted on:" hint. Deriving it from
    # the union rather than re-listing it is what keeps a sixth variant from
    # joining the contract while vanishing from the messages, so pin that the two
    # cannot disagree.
    from gda.commands.input import _SEQUENCE_EVENT_MODELS, _event_kind

    mapping = _sequence_events_schema()["properties"]["events"]["items"][
        "discriminator"
    ]["mapping"]
    assert {_event_kind(m) for m in _SEQUENCE_EVENT_MODELS} == set(mapping)


# Each sequence variant and the single-frame op whose shape it mirrors. The
# variants deliberately REDECLARE those fields (their descriptions differ — a
# variant explains itself inside a union), so nothing shared is extracted; this
# pairing is what keeps the redeclaration honest.
_MIRRORED_MODELS = [
    ("key", "KeySequenceEvent", "InputKeyParams"),
    ("mouse_click", "MouseClickSequenceEvent", "InputMouseClickParams"),
    ("mouse_move", "MouseMoveSequenceEvent", "InputMouseMoveParams"),
    ("action", "ActionSequenceEvent", "InputActionParams"),
]


def test_a_sequence_variant_keeps_its_single_frame_ops_constraints():
    # A sequence event and its single-frame op are the same request at a clock
    # offset, so a bound that holds for one must hold for the other: tightening
    # `input action --strength` while a sequence action kept 0..∞ would accept
    # through one door what the other refuses. Compares the CONSTRAINTS (bounds
    # and defaults) of the fields both declare, not their prose.
    import gda.commands.input as input_module

    drift: list[str] = []
    compared = 0
    for kind, variant_name, params_name in _MIRRORED_MODELS:
        variant = getattr(input_module, variant_name)
        params = getattr(input_module, params_name)
        shared = set(variant.model_fields) & set(params.model_fields)
        assert shared, (kind, "no shared fields — the pairing is stale")
        for field in sorted(shared):
            here, there = variant.model_fields[field], params.model_fields[field]
            if repr(here.metadata) != repr(there.metadata):
                drift.append(
                    f"{variant_name}.{field} bounds {here.metadata} != "
                    f"{params_name}.{field} bounds {there.metadata}"
                )
            if repr(here.default) != repr(there.default):
                drift.append(
                    f"{variant_name}.{field} default {here.default!r} != "
                    f"{params_name}.{field} default {there.default!r}"
                )
            compared += 1

    assert not drift, "sequence variants drifted from their single-frame ops:\n" + (
        "\n".join(drift)
    )
    # The comparison really covered the interesting fields, not just `type`.
    assert compared >= 10, compared
