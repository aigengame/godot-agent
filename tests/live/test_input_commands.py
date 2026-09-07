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

import pytest

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE, EXIT_PARSE
from gda.models import MAX_WINDOW_FRAMES
from gda.runner import RunResult
from tests.support import (
    INPUT_ACTION_RESULT,
    INPUT_KEY_RESULT,
    INPUT_MOUSE_CLICK_RESULT,
    INPUT_MOUSE_MOVE_RESULT,
    INPUT_SEQUENCE_RESULT,
    INPUT_TAP_ACTION_RESULT,
    INPUT_TAP_KEY_RESULT,
    error_sentinel,
    inject_live_runner,
    sentinel,
    minimal_project,
)


# --- input key (single-frame) -------------------------------------------------


def test_input_key_injects_a_key_event_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "key",
            "Right",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
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
            str(minimal_project(tmp_path)),
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
        app,
        ["input", "key", "Nope", "--project", str(minimal_project(tmp_path)), "--json"],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_invalid_key"
    assert error["category"] == "live"


def test_input_key_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "input",
            "key",
            "Right",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
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


# --- input mouse-click (the activation gesture) / mouse-move (single-frame) ----


def test_input_mouse_click_injects_the_whole_gesture_through_the_live_channel(
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
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "mouse_click"
    assert data["position"] == [100.0, 200.0]
    # The result carries the COMPLETE gesture's evidence (#652): the three
    # phases at their window frames, and the focus state around the gesture.
    assert data["phases"] == [
        {"frame": 0, "phase": "move", "injection_route": "viewport_event"},
        {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
    ]
    assert data["focus_before"] is None
    assert data["focus_after"] == "/root/Main/Btn"
    # The position, button, and double flag are threaded to the operation params.
    assert fake.calls == [
        (
            "input-mouse-click",
            {"x": 100.0, "y": 200.0, "button": "right", "double": True},
        )
    ]


def _flat_help(result) -> str:
    """The rendered help as plain flowing text, so phrase assertions survive
    the terminal renderer's wrapping (the assertions are about content):
    ANSI codes and panel borders out, line breaks collapsed to spaces."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    text = re.sub(r"[│╭╮╰╯─]", " ", text)
    return re.sub(r"\s+", " ", text)


def test_input_mouse_help_documents_tracked_position_limitation():
    click = CliRunner().invoke(app, ["input", "mouse-click", "--help"])
    move = CliRunner().invoke(app, ["input", "mouse-move", "--help"])

    assert click.exit_code == 0, click.stdout + click.stderr
    assert move.exit_code == 0, move.stdout + move.stderr
    for result in (click, move):
        flat = _flat_help(result)
        assert "position" in flat
        assert "get_mouse_position()" in flat
        assert "get_global_mouse_position()" in flat
        assert "stale in daemon sessions" in flat


def test_input_mouse_click_help_states_the_activation_frame_semantics():
    # The #652 acceptance: the help states the minimum frame semantics Godot
    # needs for a UI activation — the whole gesture, activating on the release.
    result = CliRunner().invoke(app, ["input", "mouse-click", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "the initial move, the press, and the release" in flat
    assert "one per process frame" in flat
    assert "activates on the release" in flat


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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
        [
            "input",
            "action",
            "jump",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
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
            str(minimal_project(tmp_path)),
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
        app,
        [
            "input",
            "action",
            "nope",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
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
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_input_action_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "action", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["kind"] == "live"


# --- input tap (the press-hold-release activation gesture, #652) ---------------


def test_input_tap_key_dispatches_the_press_hold_release_window(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "tap"
    assert data["key"] == "Right"
    assert data["action"] is None
    # The gesture evidence (#652): press at frame 0, release at frame
    # hold_frames, and the focus state around the tap.
    assert data["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
    ]
    assert data["focus_before"] == "/root/Main/A"
    assert data["focus_after"] == "/root/Main/B"
    # The safe defaults: hold 2 process frames, settle 2 more (a 5-frame window).
    assert fake.calls == [
        (
            "input-tap",
            {
                "key": "Right",
                "action": None,
                "modifiers": [],
                "strength": None,
                "hold_frames": 2,
                "settle_frames": 2,
            },
        )
    ]


def test_input_tap_action_threads_strength_and_frame_counts(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--action",
            "jump",
            "--strength",
            "0.5",
            "--hold-frames",
            "6",
            "--settle-frames",
            "0",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "tap"
    assert data["action"] == "jump"
    assert data["key"] is None
    assert fake.calls == [
        (
            "input-tap",
            {
                "key": None,
                "action": "jump",
                "modifiers": [],
                "strength": 0.5,
                "hold_frames": 6,
                "settle_frames": 0,
            },
        )
    ]


def test_input_tap_requires_exactly_one_target(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    neither = CliRunner().invoke(
        app,
        ["input", "tap", "--project", str(minimal_project(tmp_path)), "--json"],
    )
    both = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--action",
            "jump",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert neither.exit_code == 2, neither.stdout + neither.stderr
    assert both.exit_code == 2, both.stdout + both.stderr
    assert "exactly one of 'key' or 'action'" in neither.stderr + both.stderr
    assert fake.calls == []


def test_input_tap_rejects_the_other_targets_fields(monkeypatch, tmp_path):
    # The GDA-DF-037 lesson carried over: a foreign field is refused with the
    # rule named, never silently inert.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    modifiers_on_action = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--action",
            "jump",
            "--modifiers",
            "shift",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )
    strength_on_key = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--strength",
            "0.5",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert modifiers_on_action.exit_code == 2
    assert "rides a key tap only" in modifiers_on_action.stderr
    assert strength_on_key.exit_code == 2
    assert "rides an action tap only" in strength_on_key.stderr
    assert fake.calls == []


def test_input_tap_window_is_bounded_to_the_shared_ceiling(monkeypatch, tmp_path):
    # hold + settle + 1 must fit the same per-window ceiling a sequence obeys:
    # an over-range tap is refused model-side, never a live stall (ADR-0015).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--hold-frames",
            str(MAX_WINDOW_FRAMES),
            "--settle-frames",
            "0",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert str(MAX_WINDOW_FRAMES) in result.stderr
    assert fake.calls == []


def test_input_tap_hold_frames_zero_is_a_usage_error(monkeypatch, tmp_path):
    # hold_frames >= 1 is the GDA-DF-034 floor: a same-frame press+release
    # reports success without advancing the focused UI, so the model refuses it.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--hold-frames",
            "0",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
    assert "--hold-frames" in stripped, stripped
    assert fake.calls == []


def test_input_tap_help_states_the_activation_frame_semantics():
    # The #652 acceptance: the help states the minimum frame semantics Godot
    # needs for a UI activation — press and release on separate process frames.
    result = CliRunner().invoke(app, ["input", "tap", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "SEPARATE process frames" in flat
    assert "presses at window frame 0" in flat
    assert "--hold-frames" in flat
    assert "--settle-frames" in flat


def test_input_tap_schema_reports_kind_live():
    result = CliRunner().invoke(app, ["input", "tap", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["kind"] == "live"


def test_input_tap_omitted_action_strength_is_normalized_model_side(
    monkeypatch, tmp_path
):
    # The params model owns the derived default (ADR-0015): an action tap with
    # no --strength sends an explicit 1.0 on BOTH invocation paths, so the
    # harness fallback stays defensive only and the wire never carries the
    # "null means 1.0" split the schema cannot express.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_ACTION_RESULT), stderr="", exit_code=0),
    )

    argv = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--action",
            "jump",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )
    params_json = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--params-json",
            '{"action": "jump"}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert argv.exit_code == 0, argv.stdout + argv.stderr
    assert params_json.exit_code == 0, params_json.stdout + params_json.stderr
    assert [call[1]["strength"] for call in fake.calls] == [1.0, 1.0]
    # A key tap has no strength: it stays null on the wire, never 1.0.
    fake.calls.clear()
    fake.result = RunResult(
        stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0
    )
    key = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )
    assert key.exit_code == 0, key.stdout + key.stderr
    assert fake.calls[0][1]["strength"] is None


# Malformed harness replies for the two activation gestures (#652). The output
# models VALIDATE the gesture evidence, so a reply outside the contract — a
# stale or drifted harness — is the structured contract_violation, never a
# silently-successful CLI/MCP result.
_MALFORMED_TAP_REPLIES = [
    # A kind outside the contract.
    {**INPUT_TAP_KEY_RESULT, "kind": "wrong"},
    # Both target families present at once.
    {**INPUT_TAP_KEY_RESULT, "action": "jump", "strength": 1.0},
    # Frame arithmetic that disagrees with hold + settle + 1.
    {**INPUT_TAP_KEY_RESULT, "frames": 1},
    # A phase outside the gesture vocabulary, at a negative frame.
    {**INPUT_TAP_KEY_RESULT, "phases": [{"frame": -7, "phase": "noop"}]},
    # Field bounds mirroring the request contract (#732 recheck): an empty
    # action name, an out-of-range strength, an empty key name, an echoed
    # KEY_NONE, and a modifier outside the vocabulary are all contract drift.
    {**INPUT_TAP_ACTION_RESULT, "action": ""},
    {**INPUT_TAP_ACTION_RESULT, "strength": 2.0},
    {**INPUT_TAP_KEY_RESULT, "key": ""},
    {**INPUT_TAP_KEY_RESULT, "keycode": 0},
    {**INPUT_TAP_KEY_RESULT, "modifiers": ["control"]},
]

_MALFORMED_CLICK_REPLIES = [
    # A kind outside the contract.
    {**INPUT_MOUSE_CLICK_RESULT, "kind": "mouse_move"},
    # A button outside the enum.
    {**INPUT_MOUSE_CLICK_RESULT, "button": "bogus"},
    # A position that is not an [x, y] pair (#732 recheck): an empty one used
    # to classify as success and then crash the human renderer's unpack.
    {**INPUT_MOUSE_CLICK_RESULT, "position": []},
    # The right phases in the wrong order.
    {
        **INPUT_MOUSE_CLICK_RESULT,
        "phases": [
            {"frame": 0, "phase": "press"},
            {"frame": 1, "phase": "move"},
            {"frame": 2, "phase": "release"},
        ],
    },
    # The release phase missing entirely.
    {
        **INPUT_MOUSE_CLICK_RESULT,
        "phases": INPUT_MOUSE_CLICK_RESULT["phases"][:2],
    },
]


def test_malformed_tap_reply_is_a_contract_violation(monkeypatch, tmp_path):
    for payload in _MALFORMED_TAP_REPLIES:
        inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(payload), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(
            app,
            [
                "input",
                "tap",
                "--key",
                "Right",
                "--project",
                str(minimal_project(tmp_path)),
                "--json",
            ],
        )
        assert result.exit_code == EXIT_PARSE, (payload, result.stdout)
        assert json.loads(result.stdout)["error"]["code"] == "contract_violation", (
            payload
        )


def test_malformed_click_reply_is_a_contract_violation(monkeypatch, tmp_path):
    for payload in _MALFORMED_CLICK_REPLIES:
        inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(payload), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(
            app,
            [
                "input",
                "mouse-click",
                "1",
                "2",
                "--project",
                str(minimal_project(tmp_path)),
                "--json",
            ],
        )
        assert result.exit_code == EXIT_PARSE, (payload, result.stdout)
        assert json.loads(result.stdout)["error"]["code"] == "contract_violation", (
            payload
        )


def test_malformed_mouse_move_reply_is_a_contract_violation(monkeypatch, tmp_path):
    malformed = [
        # A kind outside the contract.
        {**INPUT_MOUSE_MOVE_RESULT, "kind": "mouse_click"},
        # A position that is not an [x, y] pair (#732 recheck).
        {**INPUT_MOUSE_MOVE_RESULT, "position": [1.0]},
    ]
    for payload in malformed:
        inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(payload), stderr="", exit_code=0),
        )
        result = CliRunner().invoke(
            app,
            [
                "input",
                "mouse-move",
                "1",
                "2",
                "--project",
                str(minimal_project(tmp_path)),
                "--json",
            ],
        )
        assert result.exit_code == EXIT_PARSE, (payload, result.stdout)
        assert json.loads(result.stdout)["error"]["code"] == "contract_violation", (
            payload
        )


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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
        RunResult(
            stdout=sentinel(
                {
                    **INPUT_SEQUENCE_RESULT,
                    "events": 1,
                    "frames": MAX_WINDOW_FRAMES,
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
            "--events",
            json.dumps(
                [{"type": "key", "key": "Right", "frame": MAX_WINDOW_FRAMES - 1}]
            ),
            "--project",
            str(minimal_project(tmp_path)),
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
    # Flattened, so a phrase the renderer wraps is still one phrase (the same
    # reason the mouse-op help tests read `_flat_help`).
    flat = _flat_help(result)
    assert "mouse_click" in flat
    assert "mouse_move" in flat
    assert "mouse event" in flat
    assert "position" in flat
    assert "get_mouse_position()" in flat
    assert "get_global_mouse_position()" in flat
    assert "stale in" in flat
    assert "daemon sessions" in flat


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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
        RunResult(
            stdout=sentinel(
                {
                    **INPUT_SEQUENCE_RESULT,
                    "events": 1,
                    "frames": MAX_WINDOW_FRAMES,
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
                        {"type": "key", "key": "Right", "frame": MAX_WINDOW_FRAMES - 1}
                    ]
                }
            ),
            "--project",
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
    # too (its own test below), while the one-clock rule stays model-side. The
    # modifier vocabulary and per-event window ceiling are ordinary field
    # constraints, so clients must see them here too.
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
    assert not check({"type": "key", "key": "A", "modifiers": ["hyper"]})
    assert not check({"type": "key", "key": "A", "frame": MAX_WINDOW_FRAMES})


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
            str(minimal_project(tmp_path)),
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
        RunResult(
            stdout=sentinel({**INPUT_SEQUENCE_RESULT, "events": 2, "frames": 1}),
            stderr="",
            exit_code=0,
        ),
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
            str(minimal_project(tmp_path)),
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


# Each sequence variant, the single-frame op whose shape it mirrors, and the
# PINNED list of mirrored fields. The variants deliberately REDECLARE those
# fields (their descriptions differ — a variant explains itself inside a union),
# so nothing shared is extracted; this pairing is what keeps the redeclaration
# honest. The field lists are pinned rather than intersected: an intersection
# shrinks when a mirrored field is removed or renamed on one side, which is
# exactly the drift the guard exists to catch (PR #719 recheck).
_MIRRORED_MODELS = [
    ("key", "KeySequenceEvent", "InputKeyParams", ("key", "modifiers", "released")),
    (
        "mouse_click",
        "MouseClickSequenceEvent",
        "InputMouseClickParams",
        ("x", "y", "button", "double"),
    ),
    ("mouse_move", "MouseMoveSequenceEvent", "InputMouseMoveParams", ("x", "y")),
    (
        "action",
        "ActionSequenceEvent",
        "InputActionParams",
        ("action", "release", "strength", "as_event"),
    ),
]

# The one deliberate annotation divergence: the sequence variant accepts an
# explicit `button: null` (normalized to left) so a replayed dump of the old
# flat shape stays valid, while the single-frame op never took null. The
# exemption is pinned here so it cannot widen silently; the test still requires
# the variant's annotation to be exactly `Optional[<the op's annotation>]`.
_MIRRORED_NULLABLE_EXEMPTIONS = {("MouseClickSequenceEvent", "button")}


def test_a_sequence_variant_keeps_its_single_frame_ops_constraints():
    # A sequence event and its single-frame op are the same request at a clock
    # offset, so a bound that holds for one must hold for the other: tightening
    # `input action --strength` while a sequence action kept 0..∞ would accept
    # through one door what the other refuses. Compares the CONSTRAINTS
    # (annotation, bounds, defaults) of the PINNED mirrored fields, not their
    # prose — and requires each pinned field to exist on both sides, so removing
    # or renaming one is itself the drift.
    import gda.commands.input as input_module

    drift: list[str] = []
    for kind, variant_name, params_name, fields in _MIRRORED_MODELS:
        variant = getattr(input_module, variant_name)
        params = getattr(input_module, params_name)
        for field in fields:
            here = variant.model_fields.get(field)
            there = params.model_fields.get(field)
            if here is None or there is None:
                drift.append(
                    f"{variant_name}.{field} / {params_name}.{field}: pinned "
                    f"mirrored field missing on "
                    f"{'both sides' if here is there else (variant_name if here is None else params_name)}"
                )
                continue
            expected = there.annotation
            if (variant_name, field) in _MIRRORED_NULLABLE_EXEMPTIONS:
                # The exemption only means something while the op side is NOT
                # nullable: once it becomes nullable too, `| None` collapses
                # (Optional[Optional[T]] is Optional[T]) and the plain
                # comparison would keep passing forever — so a resolved
                # divergence must take its exemption entry with it.
                if repr(there.annotation | None) == repr(there.annotation):
                    drift.append(
                        f"stale exemption ({variant_name!r}, {field!r}): "
                        f"{params_name}.{field} is itself nullable now — the "
                        f"divergence is gone, delete the exemption"
                    )
                expected = there.annotation | None
            if repr(here.annotation) != repr(expected):
                drift.append(
                    f"{variant_name}.{field} annotation {here.annotation!r} != "
                    f"{params_name}.{field} annotation {there.annotation!r}"
                )
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
            if repr(here.default_factory) != repr(there.default_factory):
                drift.append(
                    f"{variant_name}.{field} default_factory "
                    f"{here.default_factory!r} != {params_name}.{field} "
                    f"default_factory {there.default_factory!r}"
                )

    assert not drift, "sequence variants drifted from their single-frame ops:\n" + (
        "\n".join(drift)
    )
    # Every exemption must name a pinned mirrored field, so an entry whose field
    # went away fails loudly instead of exempting nothing. (The other stale form
    # — the divergence got resolved — is caught above, where an exemption whose
    # op side is itself nullable is reported as drift.)
    pinned = {
        (variant_name, field)
        for _, variant_name, _, fields in _MIRRORED_MODELS
        for field in fields
    }
    assert _MIRRORED_NULLABLE_EXEMPTIONS <= pinned, (
        _MIRRORED_NULLABLE_EXEMPTIONS - pinned
    )


# --- the injection route every input result names (#838) ----------------------
# gda injects an action as a STATE change (Input.action_press/action_release) and
# a key or mouse event as an EVENT pushed through the root viewport. The two are
# not interchangeable — a state change reaches no `_input` / `_gui_input` /
# `_unhandled_input` handler — and a success result that named neither read as
# GUI-path validation twice in dogfooding (GDA-DF-048, GDA-DF-075). Every result
# now names the route it used; the CLI derives it from the event kind, so the
# harness reply below is the UNCHANGED one it already sends.


def _input_json(monkeypatch, tmp_path, payload, *argv):
    """Run one `gda input` command over a faked live seam; return its result JSON."""
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )
    result = CliRunner().invoke(
        app,
        ["input", *argv, "--project", str(minimal_project(tmp_path)), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_input_key_result_names_the_viewport_event_route(monkeypatch, tmp_path):
    data = _input_json(monkeypatch, tmp_path, INPUT_KEY_RESULT, "key", "Right")

    assert data["injection_route"] == "viewport_event"


def test_input_mouse_move_result_names_the_viewport_event_route(monkeypatch, tmp_path):
    data = _input_json(
        monkeypatch, tmp_path, INPUT_MOUSE_MOVE_RESULT, "mouse-move", "50", "60"
    )

    assert data["injection_route"] == "viewport_event"


def test_input_action_result_names_the_action_state_route(monkeypatch, tmp_path):
    data = _input_json(monkeypatch, tmp_path, INPUT_ACTION_RESULT, "action", "jump")

    assert data["injection_route"] == "action_state"


def test_input_mouse_click_phases_each_name_the_viewport_event_route(
    monkeypatch, tmp_path
):
    data = _input_json(
        monkeypatch, tmp_path, INPUT_MOUSE_CLICK_RESULT, "mouse-click", "100", "200"
    )

    assert [phase["injection_route"] for phase in data["phases"]] == [
        "viewport_event",
        "viewport_event",
        "viewport_event",
    ]


def test_input_tap_key_phases_name_the_viewport_event_route(monkeypatch, tmp_path):
    data = _input_json(
        monkeypatch, tmp_path, INPUT_TAP_KEY_RESULT, "tap", "--key", "Right"
    )

    assert [phase["injection_route"] for phase in data["phases"]] == [
        "viewport_event",
        "viewport_event",
    ]


def test_input_tap_action_phases_name_the_action_state_route(monkeypatch, tmp_path):
    # The tap is the one command whose route depends on the target it was given,
    # which is why the field rides the PHASE and not the result's head.
    data = _input_json(
        monkeypatch, tmp_path, INPUT_TAP_ACTION_RESULT, "tap", "--action", "jump"
    )

    assert [phase["injection_route"] for phase in data["phases"]] == [
        "action_state",
        "action_state",
    ]


def test_input_sequence_reports_one_phase_per_event_naming_its_route(
    monkeypatch, tmp_path
):
    # A sequence can MIX the routes, so each injected phase names its own. The
    # phases are derived from the request: the harness reply counts the events,
    # it does not enumerate them.
    events = [
        {"type": "action", "action": "jump", "frame": 0},
        {"type": "key", "key": "Right", "frame": 1},
        {"type": "mouse_click", "x": 10, "y": 20, "frame": 2},
    ]
    data = _input_json(
        monkeypatch,
        tmp_path,
        {**INPUT_SEQUENCE_RESULT, "events": 3, "frames": 3},
        "sequence",
        "--events",
        json.dumps(events),
    )

    assert data["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "action_state"},
        {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
    ]


def test_input_sequence_phases_report_releases_and_the_physics_clock(
    monkeypatch, tmp_path
):
    # A release event reports a release phase, and the phase offsets are the
    # offsets on the clock the result reports — physics here, not process.
    events = [
        {"type": "action", "action": "jump", "physics_frame": 0},
        {"type": "action", "action": "jump", "release": True, "physics_frame": 30},
        {"type": "mouse_move", "x": 1, "y": 2, "physics_frame": 30},
    ]
    data = _input_json(
        monkeypatch,
        tmp_path,
        {**INPUT_SEQUENCE_RESULT, "clock": "physics", "events": 3, "frames": 31},
        "sequence",
        "--events",
        json.dumps(events),
    )

    assert data["clock"] == "physics"
    assert data["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "action_state"},
        {"frame": 30, "phase": "release", "injection_route": "action_state"},
        {"frame": 30, "phase": "move", "injection_route": "viewport_event"},
    ]


def test_every_event_kind_declares_its_route_and_only_action_takes_the_state_one():
    # The route table must be COMPLETE over the union's own membership, and the
    # derivation must have no fallback: with one, a sixth kind that changes state
    # would silently inherit `viewport_event` — the common answer — and this test
    # would still pass. So the key set is pinned against `InputEventType`, and the
    # absence of a declared route is an error rather than a default.
    import gda.commands.input as input_module

    kinds = {kind.value for kind in input_module.InputEventType}
    assert set(input_module.INJECTION_ROUTES) == kinds, (
        input_module.INJECTION_ROUTES,
        kinds,
    )
    assert input_module.INJECTION_ROUTES["action"] == "action_state"
    assert {
        route
        for kind, route in input_module.INJECTION_ROUTES.items()
        if kind != "action"
    } == {"viewport_event"}
    assert all(
        input_module.injection_route(kind) == input_module.INJECTION_ROUTES[kind]
        for kind in kinds
    )
    with pytest.raises(ValueError, match="no injection route is declared"):
        input_module.injection_route("joypad_button")


def test_the_event_mode_is_offered_by_the_state_route_kind_alone(monkeypatch):
    # #854 adds a SECOND input to the one derivation, and no sixth event kind: the
    # opt-in flips the kind whose declared route is `action_state` to the event
    # route, and asking for it on a kind that already pushes an event is a gda bug,
    # not a silently ignored flag. Derived from the table above rather than from a
    # second membership list naming "action".
    import gda.commands.input as input_module

    state_kinds = {
        kind
        for kind, route in input_module.INJECTION_ROUTES.items()
        if route == "action_state"
    }
    assert state_kinds == {"action"}
    for kind in state_kinds:
        assert input_module.injection_route(kind, as_event=True) == "viewport_event"
    for kind in set(input_module.INJECTION_ROUTES) - state_kinds:
        with pytest.raises(ValueError, match="already takes the viewport_event route"):
            input_module.injection_route(kind, as_event=True)
    # The default is untouched: the opt-in is what changes the door (#854).
    assert input_module.injection_route("action") == "action_state"


def test_input_sequence_phases_are_reported_in_application_order(monkeypatch, tmp_path):
    # The harness applies a sequence by advancing the clock one index at a time and,
    # at each index, walking the events in REQUEST order — so the reported phases
    # are sorted by frame with request order kept inside a frame, and a request
    # written out of frame order still reads like the gesture ops' phase lists.
    events = [
        {"type": "key", "key": "Right", "frame": 5},
        {"type": "action", "action": "jump", "frame": 0},
        {"type": "mouse_move", "x": 1, "y": 2, "frame": 0},
    ]
    data = _input_json(
        monkeypatch,
        tmp_path,
        {**INPUT_SEQUENCE_RESULT, "events": 3, "frames": 6},
        "sequence",
        "--events",
        json.dumps(events),
    )

    assert data["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "action_state"},
        {"frame": 0, "phase": "move", "injection_route": "viewport_event"},
        {"frame": 5, "phase": "press", "injection_route": "viewport_event"},
    ]


def test_input_sequence_refuses_a_reply_that_applied_a_different_event_count(
    monkeypatch, tmp_path
):
    # The phases are derived from the REQUEST, so a reply that says it applied a
    # different sequence must not be published beside them: the result would state
    # two sequences at once. A self-consistent reply for a DIFFERENT request is a
    # contract_violation, the rule `perf monitors` already applies to its window.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({**INPUT_SEQUENCE_RESULT, "events": 1, "frames": 1}),
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
            json.dumps(
                [
                    {"type": "action", "action": "jump", "frame": 0},
                    {"type": "key", "key": "Right", "frame": 1},
                    {"type": "key", "key": "Left", "frame": 2},
                ]
            ),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_PARSE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "contract_violation"
    assert error["message"] == "the harness applied 1 events for a 3-event request."


def test_input_sequence_publishes_phases_when_the_reply_agrees(monkeypatch, tmp_path):
    # The other half of the correlation: an agreeing reply still publishes the
    # derived phases, so the guard refuses drift rather than the feature.
    data = _input_json(
        monkeypatch,
        tmp_path,
        {**INPUT_SEQUENCE_RESULT, "events": 2, "frames": 2},
        "sequence",
        "--events",
        json.dumps(
            [
                {"type": "action", "action": "jump", "frame": 0},
                {"type": "key", "key": "Right", "frame": 1},
            ]
        ),
    )

    assert data["events"] == 2
    assert [phase["injection_route"] for phase in data["phases"]] == [
        "action_state",
        "viewport_event",
    ]


def test_input_action_help_states_the_route_and_what_it_never_reaches():
    # The #838 acceptance, and the retraction of the claim that the game
    # "observes the action exactly as a real binding would fire".
    result = CliRunner().invoke(app, ["input", "action", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "real binding would fire" not in flat
    assert "action_state" in flat
    assert "polled action state" in flat
    assert "_input" in flat
    assert "_gui_input" in flat
    assert "_unhandled_input" in flat
    assert "Input.is_action_" in flat


def test_input_tap_help_states_the_route_of_each_target():
    result = CliRunner().invoke(app, ["input", "tap", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "action_state" in flat
    assert "viewport_event" in flat
    assert "_gui_input" in flat
    assert "Input.is_action_" in flat


def test_input_sequence_help_states_the_route_of_each_event_kind():
    result = CliRunner().invoke(app, ["input", "sequence", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "action_state" in flat
    assert "viewport_event" in flat
    assert "_unhandled_input" in flat


def test_input_action_schema_publishes_the_route_it_takes():
    result = CliRunner().invoke(app, ["input", "action", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "action_state" in schema["input"]["description"]
    assert "_gui_input" in schema["input"]["description"]
    route = schema["output"]["properties"]["injection_route"]
    assert route["enum"] == ["action_state", "viewport_event"]
    assert route["default"] == "action_state"


def test_input_tap_schema_publishes_the_route_on_every_phase():
    result = CliRunner().invoke(app, ["input", "tap", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "action_state" in schema["input"]["description"]
    assert "_gui_input" in schema["input"]["description"]
    phase = schema["output"]["$defs"]["InputEventPhase"]
    assert phase["properties"]["injection_route"]["enum"] == [
        "action_state",
        "viewport_event",
    ]
    assert "injection_route" in phase["required"]


def test_input_sequence_schema_publishes_the_route_per_event_kind():
    result = CliRunner().invoke(app, ["input", "sequence", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "action_state" in schema["input"]["description"]
    assert "_unhandled_input" in schema["input"]["description"]
    assert "action_state" in _variants()["action"]["description"]
    assert "viewport_event" in _variants()["key"]["description"]
    phases = schema["output"]["properties"]["phases"]
    assert "route" in phases["description"]


def test_the_bundled_skill_states_which_route_each_input_command_takes():
    # ADR-0024 ships the skill in-package, so the guidance an agent reads is
    # version-locked to this CLI: the route distinction must be in it, not only
    # in --help.
    from gda.commands.meta import read_skill_text

    skill = read_skill_text()

    assert "action_state" in skill
    assert "viewport_event" in skill
    assert "_gui_input" in skill
    assert "Input.is_action_" in skill


# --- the opt-in event mode for actions (#854) ---------------------------------
#
# An action injection changes the POLLED state and reaches no handler, and until
# #838 nothing said so; #854 adds the other door as an EXPLICIT opt-in rather than
# changing what an existing call means (GDA-DF-075 asked for exactly that). With
# `--as-event` gda builds an InputEventAction and pushes it through the root
# viewport — the same door a key event takes — so `_input`, `_gui_input` and
# `_unhandled_input` handlers matching the action receive it while
# `Input.is_action_pressed` stays untouched. Delivery is `Viewport.push_input`,
# never `Input.parse_input_event`, which would update the polled state too and
# collapse the two routes into one.

# The conformance matrix the issue documents, in the whitespace-flattened form
# every surface must carry it in (help, --schema and the bundled skill).
_MATRIX_ROWS = (
    "input action : yes | no | no",
    "input action --as-event : no | yes | yes",
    "input key <mapped key> : no | yes | yes",
)


def _flat(text: str) -> str:
    """Collapse whitespace, so a phrase assertion survives wrapping and indentation."""
    return re.sub(r"\s+", " ", text)


def test_input_action_as_event_relays_the_mode_and_names_the_event_route(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({**INPUT_ACTION_RESULT, "as_event": True}),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "action",
            "jump",
            "--as-event",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["injection_route"] == "viewport_event"
    assert fake.calls == [
        (
            "input-action",
            {"action": "jump", "release": False, "strength": 1.0, "as_event": True},
        )
    ]


def test_input_action_without_the_flag_keeps_the_state_route(monkeypatch, tmp_path):
    # The default is the decision, not an oversight: an existing call means what it
    # meant before, down to the relayed request.
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
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["injection_route"] == "action_state"
    assert fake.calls == [
        (
            "input-action",
            {"action": "jump", "release": False, "strength": 1.0, "as_event": False},
        )
    ]


def test_input_action_as_event_release_still_names_the_event_route(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    **INPUT_ACTION_RESULT,
                    "pressed": False,
                    "strength": 0.0,
                    "as_event": True,
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
            "action",
            "jump",
            "--release",
            "--as-event",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["pressed"] is False
    assert data["injection_route"] == "viewport_event"
    assert fake.calls == [
        (
            "input-action",
            {"action": "jump", "release": True, "strength": 1.0, "as_event": True},
        )
    ]


def test_input_action_params_json_as_event_dispatches_like_argv(monkeypatch, tmp_path):
    # ADR-0015 parity: --params-json accepts exactly what the published schema
    # accepts, and reaches the same live seam with the same request.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({**INPUT_ACTION_RESULT, "as_event": True}),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "action",
            "--params-json",
            '{"action": "jump", "as_event": true}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["injection_route"] == "viewport_event"
    assert fake.calls == [
        (
            "input-action",
            {"action": "jump", "release": False, "strength": 1.0, "as_event": True},
        )
    ]


def test_input_tap_action_as_event_phases_name_the_event_route(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({**INPUT_TAP_ACTION_RESULT, "as_event": True}),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--action",
            "jump",
            "--as-event",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [
        phase["injection_route"] for phase in json.loads(result.stdout)["phases"]
    ] == ["viewport_event", "viewport_event"]
    assert fake.calls == [
        (
            "input-tap",
            {
                "key": None,
                "action": "jump",
                "modifiers": [],
                "strength": 1.0,
                "hold_frames": 2,
                "settle_frames": 2,
                "as_event": True,
            },
        )
    ]


def test_input_tap_action_without_the_flag_keeps_the_state_route(monkeypatch, tmp_path):
    data = _input_json(
        monkeypatch,
        tmp_path,
        INPUT_TAP_ACTION_RESULT,
        "tap",
        "--action",
        "jump",
    )

    assert [phase["injection_route"] for phase in data["phases"]] == [
        "action_state",
        "action_state",
    ]


def test_input_tap_key_refuses_the_event_mode_argv(monkeypatch, tmp_path):
    # A key tap already pushes an event; `--as-event` on it is a request that means
    # nothing, and a silently inert flag is the GDA-DF-037 failure the tap's
    # per-family rules exist to prevent.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--key",
            "Right",
            "--as-event",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert "rides an action tap only" in result.stdout + result.stderr
    assert fake.calls == []


def test_input_tap_params_json_key_with_the_event_mode_is_invalid_params(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(INPUT_TAP_KEY_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "input",
            "tap",
            "--params-json",
            '{"key": "Right", "as_event": true}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_params"
    assert "rides an action tap only" in error["message"]
    assert fake.calls == []


def test_input_sequence_action_event_mode_names_the_event_route_per_phase(
    monkeypatch, tmp_path
):
    # The AC's sequence half: `as_event` rides an `action` event, one sequence may
    # mix all three, and every phase reports the route it took.
    events = [
        {"type": "action", "action": "jump", "frame": 0},
        {"type": "action", "action": "jump", "as_event": True, "frame": 1},
        {"type": "key", "key": "Right", "frame": 2},
    ]
    data = _input_json(
        monkeypatch,
        tmp_path,
        {**INPUT_SEQUENCE_RESULT, "events": 3, "frames": 3},
        "sequence",
        "--events",
        json.dumps(events),
    )

    assert data["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "action_state"},
        {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "press", "injection_route": "viewport_event"},
    ]


def test_input_sequence_action_event_mode_relays_the_flag(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({**INPUT_SEQUENCE_RESULT, "events": 1, "frames": 1}),
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
            json.dumps(
                [
                    {
                        "type": "action",
                        "action": "jump",
                        "as_event": True,
                        "release": True,
                    }
                ]
            ),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        (
            "input-sequence",
            {
                "events": [
                    {
                        "frame": 0,
                        "physics_frame": None,
                        "type": "action",
                        "action": "jump",
                        "release": True,
                        "strength": 1.0,
                        "as_event": True,
                    }
                ]
            },
        )
    ]


def test_the_event_mode_is_not_valid_on_a_key_sequence_event(monkeypatch, tmp_path):
    # The union's own refusal, derived from the variants: the flag exists on the
    # action kind alone, and the message names where it IS accepted.
    message = _reject(
        monkeypatch, tmp_path, {"type": "key", "key": "Right", "as_event": True}
    )

    assert "'as_event' is not valid on a 'key' sequence event" in message
    assert "'as_event' is accepted on: action" in message


def test_input_action_help_carries_the_conformance_matrix():
    result = CliRunner().invoke(app, ["input", "action", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "--as-event" in flat
    assert "InputEventAction" in flat
    for row in _MATRIX_ROWS:
        assert row in flat, (row, flat)


def test_input_tap_help_states_the_event_mode_rides_an_action_tap():
    result = CliRunner().invoke(app, ["input", "tap", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "--as-event" in flat
    assert "InputEventAction" in flat
    assert "viewport_event" in flat


def test_input_sequence_help_states_the_action_event_mode():
    result = CliRunner().invoke(app, ["input", "sequence", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = _flat_help(result)
    assert "as_event" in flat


def test_input_action_schema_publishes_the_event_mode_and_the_matrix():
    result = CliRunner().invoke(app, ["input", "action", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    mode = schema["input"]["properties"]["as_event"]
    assert mode["type"] == "boolean"
    assert mode["default"] is False
    assert "InputEventAction" in mode["description"]
    flat = _flat(schema["input"]["description"])
    for row in _MATRIX_ROWS:
        assert row in flat, (row, flat)


def test_input_tap_schema_publishes_the_event_mode_flag():
    result = CliRunner().invoke(app, ["input", "tap", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    mode = schema["input"]["properties"]["as_event"]
    assert mode["type"] == "boolean"
    assert mode["default"] is False
    assert "action tap" in mode["description"]
    assert "as_event" in _flat(schema["input"]["description"])


def test_input_sequence_schema_publishes_the_event_mode_on_the_action_variant_only():
    variants = _variants()

    assert "as_event" in variants["action"]["properties"]
    for kind in ("key", "mouse_click", "mouse_button", "mouse_move"):
        assert "as_event" not in variants[kind]["properties"], kind
    assert "as_event" not in variants["action"]["required"]
    assert (
        "InputEventAction"
        in variants["action"]["properties"]["as_event"]["description"]
    )


def test_the_conformance_matrix_is_carried_by_help_schema_and_the_skill():
    # The matrix is stated on three surfaces because each answers a different
    # reader (a human at the terminal, a schema client, an agent reading the
    # bundled skill). It is the same claim, so nothing may carry a stale copy:
    # every surface must name all three injections and all three observers.
    from gda.commands.meta import read_skill_text

    help_result = CliRunner().invoke(app, ["input", "action", "--help"])
    schema_result = CliRunner().invoke(app, ["input", "action", "--schema"])
    assert help_result.exit_code == 0, help_result.stdout
    assert schema_result.exit_code == 0, schema_result.stdout

    surfaces = {
        "help": _flat_help(help_result),
        "schema": _flat(json.loads(schema_result.stdout)["input"]["description"]),
        "skill": _flat(read_skill_text()),
    }
    for name, text in surfaces.items():
        for injection in ("input action --as-event", "input key"):
            assert injection in text, (name, injection)
        for observer in ("Input.is_action_pressed", "_unhandled_input", "_gui_input"):
            assert observer in text, (name, observer)
