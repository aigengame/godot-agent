"""`gda screen` — runtime viewport capture of the running game, LIVE (#222).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer -> screen recipe -> classify_live -> JSON pipeline (mirroring
``test_perf_commands``). The harness reply carries the PNG as base64 in the
ADR-0002 sentinel JSON; the CLI decodes it and WRITES a PNG file, so the default
return is a path + dims + bytes + format (a 1080p base64 inline is ~MBs of JSON;
an N-frame sequence would blow the agent's context). ``screen capture --inline``
additionally embeds the base64; ``screen frames`` is path-only.

The no-daemon attach-or-fail path runs the real ``DaemonRunner`` against an empty
runtime dir. The real-engine windowed round trip (the GPU framebuffer + the
headless guard) is the e2e in ``test_e2e_screen``.
"""

import base64
import json
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.commands.screen import ScreenCaptureParams, ScreenFramesParams
from gda.runner import RunResult
from tests.support import (
    error_sentinel,
    inject_live_runner,
    sentinel,
    screen_capture_reply,
    screen_frames_reply,
)

# A 1x1 transparent PNG (valid, decodes to real bytes) so a written file starts
# with the PNG magic and has a real byte length.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG_1X1).decode("ascii")


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


# --- input contract: output paths are params, not CLI-only (#222, PR #248) ----


def test_screen_capture_params_json_supplies_the_output_path(monkeypatch, tmp_path):
    # The output path is part of the params model now (ADR-0004/ADR-0015 single
    # source), so a JSON-only invocation can express it and the PNG is written.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_capture_reply(_PNG_B64, width=8, height=8)),
            stderr="",
            exit_code=0,
        ),
    )
    out = tmp_path / "shot.png"
    payload = json.dumps({"output": str(out)})

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--params-json",
            payload,
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["path"] == str(out)
    assert out.read_bytes().startswith(b"\x89PNG")  # the PNG was actually written


def test_screen_capture_params_json_without_output_is_invalid_params(tmp_path):
    # The worst finding: a JSON-only invocation that omits the now-required output is
    # a STRUCTURED invalid_params, never an AttributeError on a None path.
    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--params-json",
            "{}",
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_screen_frames_params_json_supplies_the_output_dir(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64, _PNG_B64])),
            stderr="",
            exit_code=0,
        ),
    )
    out_dir = tmp_path / "frames"
    payload = json.dumps({"frames": 2, "output_dir": str(out_dir)})

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--params-json",
            payload,
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["count"] == 2
    assert (out_dir / "frame_0000.png").exists()


def test_screen_schema_input_carries_the_output_contract():
    # ADR-0004: the public input schema must carry the output path so an agent /
    # gda-mcp can supply it (the params were empty/frames-only before — PR #248).
    cap = json.loads(CliRunner().invoke(app, ["screen", "capture", "--schema"]).stdout)
    assert {"output", "inline"} <= set(cap["input"]["properties"])
    frm = json.loads(CliRunner().invoke(app, ["screen", "frames", "--schema"]).stdout)
    assert "output_dir" in frm["input"]["properties"]


def test_screen_output_paths_are_tilde_normalized():
    # ADR-0006: filesystem paths are ~-expanded once at the model boundary (the same
    # NormalizedPath rule export run --output follows), not kept as a literal "~".
    assert not ScreenCaptureParams(output="~/shot.png").output.startswith("~")
    assert ScreenCaptureParams(output="~/shot.png").output.endswith("shot.png")
    frames = ScreenFramesParams(frames=2, output_dir="~/frames")
    assert not frames.output_dir.startswith("~")
    assert frames.output_dir.endswith("frames")


# --- screen capture (single frame) --------------------------------------------


def test_screen_capture_writes_a_png_and_returns_its_path(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_capture_reply(_PNG_B64, width=64, height=48)),
            stderr="",
            exit_code=0,
        ),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--output",
            str(out),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # The default return: a written PNG file path + dims + bytes + format.
    assert data["path"] == str(out)
    assert data["width"] == 64 and data["height"] == 48
    assert data["format"] == "png"
    assert data["bytes"] == len(_PNG_1X1)
    # No --inline -> no base64 in the JSON (keeps the agent's context small).
    assert data.get("inline") is None
    # The file is the decoded PNG on disk (the magic the e2e asserts).
    assert out.read_bytes() == _PNG_1X1
    # Routed through the LIVE seam, dispatching the screen-capture op (no params).
    assert fake.calls == [("screen-capture", {})]


def test_screen_capture_inline_embeds_the_base64(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_capture_reply(_PNG_B64, width=10, height=10)),
            stderr="",
            exit_code=0,
        ),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--inline",
            "--output",
            str(out),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # --inline embeds the base64 PNG ALONGSIDE the written file (both).
    assert data["inline"] == _PNG_B64
    assert data["path"] == str(out)
    assert out.read_bytes() == _PNG_1X1


def test_screen_capture_with_no_daemon_reports_daemon_not_running(
    monkeypatch, tmp_path
):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir,
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--output",
            str(tmp_path / "shot.png"),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


def test_screen_capture_on_headless_session_reports_live_display_unavailable(
    monkeypatch, tmp_path
):
    # The harness guards a headless DisplayServer and reports the typed error; the
    # CLI surfaces it (and writes NO file).
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_display_unavailable", "the engine session is headless"
            ),
            stderr="",
            exit_code=0,
        ),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--output",
            str(out),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "live_display_unavailable"
    assert not out.exists()  # a failed capture writes nothing


def test_screen_capture_schema_reports_kind_live_and_is_self_describing():
    result = CliRunner().invoke(app, ["screen", "capture", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


def test_screen_capture_without_a_project_reports_project_not_found(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)  # holds no project.godot

    result = CliRunner().invoke(
        app, ["screen", "capture", "--output", str(tmp_path / "s.png"), "--json"]
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


# --- screen frames (multi-frame, time-windowed) -------------------------------


def test_screen_frames_writes_each_png_and_returns_paths(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                screen_frames_reply([_PNG_B64, _PNG_B64, _PNG_B64], width=32, height=24)
            ),
            stderr="",
            exit_code=0,
        ),
    )
    out_dir = tmp_path / "frames"

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--frames",
            "3",
            "--output-dir",
            str(out_dir),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["count"] == 3
    assert len(data["frames"]) == 3
    for frame in data["frames"]:
        assert frame["width"] == 32 and frame["height"] == 24
        assert frame["format"] == "png"
        assert frame["bytes"] == len(_PNG_1X1)
        # Path-only: no base64 in a frame sequence (would blow the context).
        assert "inline" not in frame
        assert Path(frame["path"]).read_bytes() == _PNG_1X1
    # Distinct paths, one per frame.
    assert len({f["path"] for f in data["frames"]}) == 3
    # The requested frame count is threaded to the op.
    assert fake.calls == [("screen-frames", {"frames": 3})]


def test_screen_frames_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--frames",
            "3",
            "--output-dir",
            str(tmp_path / "frames"),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


def test_screen_frames_argv_frames_over_range_is_a_usage_error(monkeypatch, tmp_path):
    # --frames is bounded by the harness's per-window ceiling (MAX_WINDOW_FRAMES);
    # an over-range value is a usage error on argv (exit 2), engine never reached.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64])), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--frames",
            "601",
            "--output-dir",
            str(tmp_path / "frames"),
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_screen_frames_schema_reports_kind_live_and_is_self_describing():
    result = CliRunner().invoke(app, ["screen", "frames", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


# --- model validation via --params-json (ADR-0015) ----------------------------
# The frame bound is the ScreenFramesParams model's, so BOTH the argv path (usage
# error, exit 2) and --params-json (structured invalid_params, exit 0 sentinel)
# reject the same over-range request — the harness never has to clamp.


def test_screen_frames_params_json_over_range_frames_is_invalid_params(
    monkeypatch, tmp_path
):
    # The model validates the --params-json object before dispatch (ADR-0015), so an
    # over-range `frames` is the structured invalid_params, not a clamp. A valid
    # output_dir is included in the JSON so the over-range `frames` is the SOLE failing
    # constraint — output_dir is now a required params field carried IN --params-json,
    # not a CLI-only option mutually exclusive with it (PR #248 review).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64])), stderr="", exit_code=0
        ),
    )
    payload = json.dumps({"frames": 601, "output_dir": str(tmp_path / "frames")})

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--project",
            str(_project(tmp_path)),
            "--json",
            "--params-json",
            payload,
        ],
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


# --- the --await-* predicate capture (#661) ------------------------------------


def _capture_argv(out, project, *extra):
    return [
        "screen",
        "capture",
        "--output",
        str(out),
        "--project",
        str(project),
        "--json",
        *extra,
    ]


def _await_argv(out, project, *extra):
    return _capture_argv(
        out,
        project,
        "--await-node",
        "/root/Main/VFX",
        "--await-property",
        "frame",
        "--await-value",
        "3",
        *extra,
    )


def _predicate_report(**overrides):
    report = {
        "node": "/root/Main/VFX",
        "property": "frame",
        "expected": 3,
        "observed": 3,
        "engine_frame": 240,
        "frames_waited": 5,
    }
    report.update(overrides)
    return report


def test_await_predicate_rides_the_wire_with_the_default_ceiling(monkeypatch, tmp_path):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report()
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _await_argv(out, _project(tmp_path)))

    assert result.exit_code == 0, result.stdout + result.stderr
    # One op, the SAME screen-capture op — the predicate is params, not a new
    # surface — with the JSON-scalar value (3 the integer, not "3") and the
    # documented default ceiling.
    assert fake.calls == [
        (
            "screen-capture",
            {
                "await": {
                    "node": "/root/Main/VFX",
                    "property": "frame",
                    "value": 3,
                    "frames": 60,
                }
            },
        )
    ]


def test_await_events_ride_the_same_window_and_report_surfaces(monkeypatch, tmp_path):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = {
        "node": "/root/Main/VFX",
        "property": "frame",
        "expected": 3,
        "observed": 3,
        "engine_frame": 240,
        "frames_waited": 5,
    }
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    events = '[{"type": "key", "key": "Right", "frame": 1}]'

    result = CliRunner().invoke(
        app,
        _await_argv(
            out, _project(tmp_path), "--await-frames", "30", "--await-events", events
        ),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    op, params = fake.calls[0]
    assert op == "screen-capture"
    assert params["await"]["frames"] == 30
    # The atomic form: the input-sequence event shapes ride the SAME window.
    (event,) = params["events"]
    assert event["type"] == "key"
    assert event["key"] == "Right"
    assert event["frame"] == 1
    # The predicate report is surfaced verbatim on the result.
    data = json.loads(result.stdout)
    assert data["predicate"] == {
        "node": "/root/Main/VFX",
        "property": "frame",
        "expected": 3,
        "observed": 3,
        "engine_frame": 240,
        "frames_waited": 5,
    }


def test_await_bare_word_value_is_a_string_predicate(monkeypatch, tmp_path):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report(
        property="anim", expected="peak", observed="peak"
    )
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(
            out,
            _project(tmp_path),
            "--await-node",
            "/root/Main/VFX",
            "--await-property",
            "anim",
            "--await-value",
            "peak",
        ),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls[0][1]["await"]["value"] == "peak"


def test_await_render_carries_the_predicate_line(monkeypatch, tmp_path):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = {
        "node": "/root/Main/VFX",
        "property": "frame",
        "expected": 3,
        "observed": 3,
        "engine_frame": 240,
        "frames_waited": 5,
    }
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    argv = _await_argv(out, _project(tmp_path))
    argv.remove("--json")

    result = CliRunner().invoke(app, argv)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "predicate /root/Main/VFX.frame == 3 held after 5 frames" in result.stdout
    assert "engine frame 240" in result.stdout


def test_await_unmet_predicate_is_the_typed_live_error(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_predicate_unmet",
                "the predicate /root/Main/VFX.frame == 3 did not hold within "
                "30 frames (last observed: 2)",
            ),
            stderr="",
            exit_code=0,
        ),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app, _await_argv(out, _project(tmp_path), "--await-frames", "30")
    )

    assert result.exit_code == EXIT_LIVE
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "live_predicate_unmet"
    assert "last observed: 2" in data["error"]["message"]
    assert not out.exists()  # no capture reply, no file written


def _usage_error_message(result):
    # The argv path's contract (gda.dispatch.params_or_bad_parameter): a model
    # refusal is a Click usage error — exit 2, message on stderr — while the
    # --params-json path surfaces the SAME rule as structured invalid_params.
    # Click line-wraps and colors the message, so strip ANSI and collapse
    # whitespace before matching.
    import re

    assert result.exit_code == 2, result.stdout + result.stderr
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
    plain = re.sub(r"[\u2500-\u257f]", " ", plain)  # rich panel borders
    return re.sub(r"\s+", " ", plain)


def _invalid_params_message(result):
    assert result.exit_code != 0
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "invalid_params"
    return data["error"]["message"]


def test_await_trio_is_all_or_none(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(out, _project(tmp_path), "--await-node", "/root/Main/VFX"),
    )

    message = _usage_error_message(result)
    assert "'await_node', 'await_property', and 'await_value' together" in message


def test_await_value_null_is_refused_with_the_trio_message(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(
            out,
            _project(tmp_path),
            "--await-node",
            "/root/Main/VFX",
            "--await-property",
            "frame",
            "--await-value",
            "null",
        ),
    )

    message = _usage_error_message(result)
    assert "JSON null value is not supported" in message


def test_await_events_need_the_predicate(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(
            out,
            _project(tmp_path),
            "--await-events",
            '[{"type": "key", "key": "Right"}]',
        ),
    )

    message = _usage_error_message(result)
    assert "'await_events' needs the await predicate" in message


def test_await_events_refuse_the_physics_clock(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _await_argv(
            out,
            _project(tmp_path),
            "--await-events",
            '[{"type": "key", "key": "Right", "physics_frame": 1}]',
        ),
    )

    message = _usage_error_message(result)
    assert "process clock" in message
    assert "physics_frame" in message


def test_await_event_offsets_must_fit_the_window(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _await_argv(
            out,
            _project(tmp_path),
            "--await-frames",
            "10",
            "--await-events",
            '[{"type": "key", "key": "Right", "frame": 10}]',
        ),
    )

    message = _usage_error_message(result)
    assert "must be inside the predicate window" in message


def test_await_frames_needs_the_predicate(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app, _capture_argv(out, _project(tmp_path), "--await-frames", "30")
    )

    message = _usage_error_message(result)
    assert "'await_frames' needs the await predicate" in message


def test_await_params_json_path_rejects_identically(monkeypatch, tmp_path):
    # ADR-0015: the model is the single validation authority, so the
    # --params-json path refuses the same malformed predicate the argv path does.
    out = tmp_path / "shot.png"
    params = json.dumps(
        {
            "output": str(out),
            "await_node": "/root/Main/VFX",
            "await_property": "frame",
            "await_value": 3,
            "await_events": [{"type": "key", "key": "Right", "physics_frame": 1}],
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "capture",
            "--params-json",
            params,
            "--project",
            str(_project(tmp_path)),
            "--json",
        ],
    )

    message = _invalid_params_message(result)
    assert "process clock" in message


def test_await_schema_publishes_the_predicate_contract():
    schema = ScreenCaptureParams.model_json_schema()
    frames = schema["properties"]["await_frames"]
    bounds = {
        key: value
        for branch in frames.get("anyOf", [frames])
        for key, value in branch.items()
        if key in ("minimum", "maximum")
    }
    assert bounds == {"minimum": 1, "maximum": 600}
    # The events field embeds the SAME input-sequence union (single authority).
    events = schema["properties"]["await_events"]
    assert "$defs" in schema and any(
        "KeySequenceEvent" in str(events) or "KeySequenceEvent" in key
        for key in schema["$defs"]
    )


# --- the receipt correlation gate (#743 review, Standards 2 / Spec 2) ----------


def _await_capture(monkeypatch, tmp_path, reply, *extra):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    result = CliRunner().invoke(app, _await_argv(out, _project(tmp_path), *extra))
    return result, out


def _assert_contract_violation(result, out, fragment):
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "contract_violation", result.stdout
    assert fragment in data["error"]["message"]
    # Refused BEFORE the output file is written.
    assert not out.exists()


def test_gated_request_with_no_predicate_report_is_contract_violation(
    monkeypatch, tmp_path
):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)

    result, out = _await_capture(monkeypatch, tmp_path, reply)

    _assert_contract_violation(result, out, "no predicate report")


def test_predicate_report_naming_another_target_is_contract_violation(
    monkeypatch, tmp_path
):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report(node="/root/Wrong")

    result, out = _await_capture(monkeypatch, tmp_path, reply)

    _assert_contract_violation(result, out, "does not name the requested predicate")


def test_predicate_report_with_unsatisfied_observation_is_contract_violation(
    monkeypatch, tmp_path
):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report(observed=2)

    result, out = _await_capture(monkeypatch, tmp_path, reply)

    _assert_contract_violation(result, out, "does not satisfy the declared predicate")


def test_predicate_report_outside_the_declared_window_is_contract_violation(
    monkeypatch, tmp_path
):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report(frames_waited=999)

    result, out = _await_capture(monkeypatch, tmp_path, reply)

    _assert_contract_violation(result, out, "outside the declared window")


def test_negative_engine_frame_is_contract_violation(monkeypatch, tmp_path):
    # The wire model bounds the receipt's frames (ge=0), so classify_live
    # refuses a fabricated negative frame as the standard reply-shape breach.
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report(engine_frame=-1)

    result, out = _await_capture(monkeypatch, tmp_path, reply)

    data = json.loads(result.stdout)
    assert data["error"]["code"] == "contract_violation"
    assert not out.exists()


def test_plain_capture_with_unsolicited_predicate_is_contract_violation(
    monkeypatch, tmp_path
):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report()
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _capture_argv(out, _project(tmp_path)))

    _assert_contract_violation(result, out, "declared no --await predicate")


# --- schema/model parity (#743 review, Standards 1; ADR-0015) ------------------


def test_await_schema_and_model_agree_on_the_cross_field_rules():
    # A standard Draft 2020-12 validator and the pydantic model must give the
    # SAME verdict on the cross-field rules the model enforces. One disclosed
    # exception (stated in the schema helper's docstring): an event offset
    # outside the window is model-only — a value-dependent relation across two
    # fields Draft 2020-12 cannot state.
    import jsonschema
    import pydantic

    schema = ScreenCaptureParams.model_json_schema()
    validator = jsonschema.Draft202012Validator(schema)
    corpus = [
        ({"output": "x.png"}, True),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
            },
            True,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": "peak",
                "await_frames": 30,
                "await_events": [{"type": "key", "key": "Right", "frame": 1}],
            },
            True,
        ),
        ({"output": "x.png", "await_node": "/root/N"}, False),
        ({"output": "x.png", "await_property": "p"}, False),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": None,
            },
            False,
        ),
        ({"output": "x.png", "await_frames": 30}, False),
        (
            {
                "output": "x.png",
                "await_events": [{"type": "key", "key": "Right"}],
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [],
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [{"type": "key", "key": "Right", "physics_frame": 1}],
            },
            False,
        ),
        # #743 re-review: the REVERSE divergences — the schema says `integer`,
        # so the model must not quietly coerce strings (strict clock ints).
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_frames": "10",
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [{"type": "key", "key": "Right", "frame": "1"}],
            },
            False,
        ),
    ]
    for payload, accepted in corpus:
        schema_ok = validator.is_valid(payload)
        try:
            ScreenCaptureParams.model_validate(payload)
            model_ok = True
        except pydantic.ValidationError:
            model_ok = False
        assert schema_ok == model_ok == accepted, (payload, schema_ok, model_ok)

    # The disclosed model-only residual, pinned so it stays a KNOWN divergence:
    # an event offset outside the window passes the schema but not the model —
    # a cross-field numeric bound Draft 2020-12 cannot state. The disclosure is
    # PUBLIC: the await_events field description (published in the schema) and
    # the command catalog both name the rule and that it is validation-enforced.
    residual = {
        "output": "x.png",
        "await_node": "/root/N",
        "await_property": "p",
        "await_value": 3,
        "await_frames": 10,
        "await_events": [{"type": "key", "key": "Right", "frame": 10}],
    }
    assert validator.is_valid(residual)
    try:
        ScreenCaptureParams.model_validate(residual)
        assert False, "the model must refuse an offset outside the window"
    except pydantic.ValidationError:
        pass
