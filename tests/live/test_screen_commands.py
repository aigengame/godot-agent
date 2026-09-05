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

import pytest
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.commands.screen import (
    ScreenCaptureParams,
    ScreenFrame,
    ScreenFramesParams,
    ScreenFramesResult,
    ScreenFramesSummary,
)
from gda.models import MAX_WINDOW_FRAMES
from gda.runner import RunResult
from tests.support import (
    PNG_1X1_B64,
    error_sentinel,
    inject_live_runner,
    sentinel,
    screen_capture_reply,
    screen_frames_reply,
    usage_error_text,
    minimal_project,
)

# A 1x1 transparent PNG (valid, decodes to real bytes) so a written file starts
# with the PNG magic and has a real byte length. The base64 lives in
# tests.support, which the live-contract guard's capture probe reads too.
_PNG_B64 = PNG_1X1_B64
_PNG_1X1 = base64.b64decode(_PNG_B64)


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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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
            str(minimal_project(tmp_path)),
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


def _align_receipt(reply):
    # The harness stamps the receipt at the SAME tick it evaluates the predicate
    # (#660), so a coherent fake gated reply mirrors the report's observed value
    # and frame into the receipt — exactly what the CLI's receipt gate checks.
    report = reply["predicate"]
    reply["receipt"].update(
        observed=report.get("observed"), engine_frame=report.get("engine_frame", 0)
    )
    return reply


def test_await_predicate_rides_the_wire_with_the_default_ceiling(monkeypatch, tmp_path):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report()
    _align_receipt(reply)
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _await_argv(out, minimal_project(tmp_path)))

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
    _align_receipt(reply)
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    events = '[{"type": "key", "key": "Right", "frame": 1}]'

    result = CliRunner().invoke(
        app,
        _await_argv(
            out,
            minimal_project(tmp_path),
            "--await-frames",
            "30",
            "--await-events",
            events,
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
    _align_receipt(reply)
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(
            out,
            minimal_project(tmp_path),
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
    _align_receipt(reply)
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    argv = _await_argv(out, minimal_project(tmp_path))
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
        app, _await_argv(out, minimal_project(tmp_path), "--await-frames", "30")
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
    # The Rich-panel normalization itself is shared (tests/support.py,
    # `usage_error_text`, #713 review) rather than redefined here.
    return usage_error_text(result)


def _invalid_params_message(result):
    assert result.exit_code != 0
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "invalid_params"
    return data["error"]["message"]


def test_await_trio_is_all_or_none(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(out, minimal_project(tmp_path), "--await-node", "/root/Main/VFX"),
    )

    message = _usage_error_message(result)
    assert "'await_node', 'await_property', and 'await_value' together" in message


def test_await_value_null_is_refused_with_the_trio_message(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _capture_argv(
            out,
            minimal_project(tmp_path),
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
            minimal_project(tmp_path),
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
            minimal_project(tmp_path),
            "--await-events",
            '[{"type": "key", "key": "Right", "physics_frame": 1}]',
        ),
    )

    message = _usage_error_message(result)
    assert "process clock" in message
    assert "physics_frame" in message


def test_out_of_window_event_offset_is_accepted_and_rides_the_wire(
    monkeypatch, tmp_path
):
    # #743 second re-review: an event may sit beyond the PREDICATE ceiling and
    # still drain. That keeps schema/model parity without restoring the old
    # cross-field rule; the separate per-event maximum below keeps the TOTAL
    # serialized live window bounded.
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report()
    _align_receipt(reply)
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _await_argv(
            out,
            minimal_project(tmp_path),
            "--await-frames",
            "10",
            "--await-events",
            '[{"type": "key", "key": "Right", "frame": 10}]',
        ),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    op, params = fake.calls[0]
    assert params["await"]["frames"] == 10
    (event,) = params["events"]
    assert event["frame"] == 10


def test_await_event_offset_must_fit_the_shared_total_window(monkeypatch, tmp_path):
    # The predicate ceiling and the TOTAL drain ceiling are different: an event
    # may sit after await_frames, but no accepted event may extend the serialized
    # live operation beyond the repository-wide MAX_WINDOW_FRAMES bound (#223).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_capture_reply(_PNG_B64, width=8, height=8)),
            stderr="",
            exit_code=0,
        ),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app,
        _await_argv(
            out,
            minimal_project(tmp_path),
            "--await-frames",
            "10",
            "--await-events",
            json.dumps(
                [
                    {
                        "type": "key",
                        "key": "Right",
                        "released": True,
                        "frame": MAX_WINDOW_FRAMES,
                    }
                ]
            ),
        ),
    )

    message = _usage_error_message(result)
    assert str(MAX_WINDOW_FRAMES - 1) in message
    assert fake.calls == []


def test_await_frames_needs_the_predicate(monkeypatch, tmp_path):
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(
        app, _capture_argv(out, minimal_project(tmp_path), "--await-frames", "30")
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
            str(minimal_project(tmp_path)),
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
    event_frame = schema["$defs"]["KeySequenceEvent"]["properties"]["frame"]
    maximums = [
        branch["maximum"]
        for branch in event_frame.get("anyOf", [event_frame])
        if "maximum" in branch
    ]
    assert maximums == [MAX_WINDOW_FRAMES - 1]


# --- the receipt correlation gate (#743 review, Standards 2 / Spec 2) ----------


def _await_capture(monkeypatch, tmp_path, reply, *extra):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    result = CliRunner().invoke(
        app, _await_argv(out, minimal_project(tmp_path), *extra)
    )
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

    result = CliRunner().invoke(app, _capture_argv(out, minimal_project(tmp_path)))

    _assert_contract_violation(result, out, "declared no --await predicate")


# --- the capture receipt (#660) ------------------------------------------------
# Every capture result binds the image to its capture event: the daemon-minted
# session identity, the LAUNCHED scene (uid only when the project's file header
# provides one, ADR-0036), the engine frame, the gated capture's observed echo,
# and the SHA-256 of exactly the bytes the CLI wrote. The receipt is REQUIRED on
# the wire — a reply without one is a version-skewed harness — and its predicate
# echo must agree with the predicate report beside it, checked before any file
# is written.


def test_capture_receipt_surfaces_with_the_written_file_hash(monkeypatch, tmp_path):
    import hashlib

    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["receipt"].update(scene_uid="uid://c4qn8xbhw6kmv", engine_frame=412)
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _capture_argv(out, minimal_project(tmp_path)))

    assert result.exit_code == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)["receipt"]
    assert receipt == {
        "session_id": "a1b2c3d4e5f60718",
        "scene_path": "res://main.tscn",
        "scene_uid": "uid://c4qn8xbhw6kmv",
        "engine_frame": 412,
        "observed": None,
        # The hash of EXACTLY the decoded bytes written to --output.
        "sha256": hashlib.sha256(_PNG_1X1).hexdigest(),
    }
    assert out.read_bytes() == _PNG_1X1


def test_gated_capture_receipt_echoes_the_predicate_evidence(monkeypatch, tmp_path):
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["predicate"] = _predicate_report()
    _align_receipt(reply)
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _await_argv(out, minimal_project(tmp_path)))

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # The receipt's echo agrees with the predicate report beside it — the same
    # observed value at the same evaluation frame. What this proves is the
    # AGREEMENT; a gated capture's complete evidence is still the pair, receipt
    # + predicate report (which carries the node/property/expected).
    assert data["receipt"]["observed"] == data["predicate"]["observed"] == 3
    assert data["receipt"]["engine_frame"] == data["predicate"]["engine_frame"] == 240


def test_capture_reply_without_a_receipt_is_contract_violation(monkeypatch, tmp_path):
    # An old or drifted harness that predates the receipt cannot produce trusted
    # evidence: the reply-shape breach is refused before any file is written.
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    del reply["receipt"]
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _capture_argv(out, minimal_project(tmp_path)))

    data = json.loads(result.stdout)
    assert data["error"]["code"] == "contract_violation"
    assert not out.exists()


def test_receipt_missing_a_nullable_key_is_contract_violation(monkeypatch, tmp_path):
    # The nullable keys are required on the wire too (#746 review): the harness
    # always sends them, so a reply that omits one is shape drift, refused like
    # a missing receipt.
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    del reply["receipt"]["scene_uid"]
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _capture_argv(out, minimal_project(tmp_path)))

    assert json.loads(result.stdout)["error"]["code"] == "contract_violation"
    assert not out.exists()


def test_plain_capture_receipt_with_unsolicited_echo_is_contract_violation(
    monkeypatch, tmp_path
):
    # Mirrors the unsolicited-predicate refusal: a plain capture's receipt must
    # echo nothing — an observation nobody asked for is fabricated evidence.
    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    reply["receipt"]["observed"] = 3
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"

    result = CliRunner().invoke(app, _capture_argv(out, minimal_project(tmp_path)))

    data = json.loads(result.stdout)
    assert data["error"]["code"] == "contract_violation"
    assert "declared no --await predicate" in data["error"]["message"]
    assert not out.exists()


def test_gated_receipt_disagreeing_with_the_report_is_contract_violation(
    monkeypatch, tmp_path
):
    # The receipt and the predicate report both describe the ONE capture
    # boundary; a reply where they disagree describes two different events and
    # is evidence for neither. Both disagreement axes are refused.
    for patch, needle in (
        ({"observed": 2}, "does not match the predicate report"),
        ({"observed": 3, "engine_frame": 999}, "names engine frame 999"),
    ):
        reply = screen_capture_reply(_PNG_B64, width=8, height=8)
        reply["predicate"] = _predicate_report()
        _align_receipt(reply)
        reply["receipt"].update(patch)

        result, out = _await_capture(monkeypatch, tmp_path, reply)

        data = json.loads(result.stdout)
        assert data["error"]["code"] == "contract_violation", data
        assert needle in data["error"]["message"]
        assert not out.exists()


def test_capture_render_carries_the_receipt_line(monkeypatch, tmp_path):
    import hashlib

    reply = screen_capture_reply(_PNG_B64, width=8, height=8)
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out = tmp_path / "shot.png"
    argv = _capture_argv(out, minimal_project(tmp_path))
    argv.remove("--json")

    result = CliRunner().invoke(app, argv)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (
        "receipt session a1b2c3d4e5f60718 scene res://main.tscn frame 400 "
        f"sha256 {hashlib.sha256(_PNG_1X1).hexdigest()}"
    ) in result.stdout


def test_capture_schema_publishes_the_receipt_contract():
    # The output schema is the public contract (ADR-0004): the receipt is a
    # REQUIRED result field whose own shape (session/scene/frame/echo/sha256)
    # a consumer can validate against.
    schema = json.loads(
        CliRunner().invoke(app, ["screen", "capture", "--schema"]).stdout
    )
    output = schema["output"]
    assert "receipt" in output["properties"]
    assert "receipt" in output.get("required", [])
    receipt_def = output["$defs"]["CaptureReceipt"]
    assert {
        "session_id",
        "scene_path",
        "scene_uid",
        "engine_frame",
        "observed",
        "sha256",
    } <= set(receipt_def["properties"])
    # Required-but-nullable (#746 review): the nullable keys are ALWAYS carried,
    # so a standard consumer sees every field required — null is a value, not an
    # omitted key.
    assert set(receipt_def["required"]) == {
        "session_id",
        "scene_path",
        "scene_uid",
        "engine_frame",
        "observed",
        "sha256",
    }


# --- schema/model parity (#743 review, Standards 1; ADR-0015) ------------------


def test_await_schema_and_model_agree_on_the_cross_field_rules():
    # A standard Draft 2020-12 validator and the pydantic model must give the
    # SAME verdict on the public capture contract: cross-field await rules,
    # imported event scalar/vocabulary constraints, and both predicate and total
    # window boundaries.
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
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [
                    {
                        "type": "key",
                        "key": "Right",
                        "modifiers": ["hyper"],
                    }
                ],
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
        # #743 re-reviews: the REVERSE divergences — the schema says
        # `integer`/`number`/`boolean`, so the model must not quietly coerce
        # strings (strict clock ints, then the whole union's scalars).
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
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [{"type": "key", "key": "Right", "released": "false"}],
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [{"type": "mouse_click", "x": "10", "y": 20.0}],
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [
                    {"type": "mouse_click", "x": 10.0, "y": 20.0, "double": "false"}
                ],
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [
                    {"type": "action", "action": "jump", "strength": "0.5"}
                ],
            },
            False,
        ),
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [
                    {"type": "action", "action": "jump", "release": "false"}
                ],
            },
            False,
        ),
        # int-for-float stays accepted on BOTH sides (JSON Schema `number`
        # admits integers; pydantic strict float admits int input).
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_events": [{"type": "mouse_click", "x": 10, "y": 20}],
            },
            True,
        ),
        # The event may be beyond the predicate ceiling, but not beyond the
        # shared TOTAL live-window ceiling. This keeps the drain bounded while
        # preserving the both-accept offset-10 case below.
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_frames": 10,
                "await_events": [
                    {"type": "key", "key": "Right", "frame": MAX_WINDOW_FRAMES}
                ],
            },
            False,
        ),
        # The former model-only residual, now a BOTH-ACCEPT case: the
        # offset-inside-window rule was removed for exact parity — the drain
        # applies an out-of-window event anyway, it just cannot satisfy the
        # predicate (documented in the field description and the catalog).
        (
            {
                "output": "x.png",
                "await_node": "/root/N",
                "await_property": "p",
                "await_value": 3,
                "await_frames": 10,
                "await_events": [{"type": "key", "key": "Right", "frame": 10}],
            },
            True,
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


# --- the compact summary envelope (#665, GDA-DF-021) ---------------------------
# The dogfooding loss boundary followed the RESULT LINE's byte size, not the
# image payload (48 frames ≈ 11 KB fit the caller's output handling; 90 ≈ 20 KB
# did not), so the gda-side guarantee is a completion envelope that does not
# grow with the frame count: --summary writes every frame exactly as before and
# returns the aggregate instead of the per-frame list.


def test_frames_summary_returns_the_aggregate_and_still_writes_files(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64, _PNG_B64, _PNG_B64])),
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
            "--summary",
            "--output-dir",
            str(out_dir),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["count"] == 3
    # The per-frame list is replaced by the aggregate (exactly one projection).
    assert data["frames"] is None
    assert data["summary"] == {
        "output_dir": str(out_dir),
        "pattern": "frame_%04d.png",
        "width": 16,
        "height": 16,
        "total_bytes": 3 * len(_PNG_1X1),
    }
    # Every frame is still written — the compaction is the ENVELOPE, not the work.
    for index in range(3):
        assert (out_dir / f"frame_{index:04d}.png").read_bytes() == _PNG_1X1


def test_frames_default_form_is_unchanged_and_summary_null(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64])),
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
            "1",
            "--output-dir",
            str(out_dir),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert len(data["frames"]) == 1
    assert data["summary"] is None


def test_frames_summary_rides_params_json_identically(monkeypatch, tmp_path):
    # ADR-0015: the JSON path expresses the same summary switch the argv path does.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64, _PNG_B64])),
            stderr="",
            exit_code=0,
        ),
    )
    out_dir = tmp_path / "frames"
    payload = json.dumps({"frames": 2, "output_dir": str(out_dir), "summary": True})

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--params-json",
            payload,
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["frames"] is None and data["summary"]["total_bytes"] > 0


def test_frames_result_carries_exactly_one_projection():
    # The model refuses both-null and both-set: the result is either the
    # per-frame list or the aggregate, never neither and never both.
    import pydantic

    frame = ScreenFrame(path="/tmp/f.png", width=1, height=1, bytes=1, format="png")
    aggregate = ScreenFramesSummary(
        output_dir="/tmp", pattern="frame_%04d.png", width=1, height=1, total_bytes=1
    )
    for frames, summary in ((None, None), ([frame], aggregate)):
        try:
            ScreenFramesResult(count=1, frames=frames, summary=summary)
        except pydantic.ValidationError as error:
            assert "exactly one projection" in str(error)
        else:
            raise AssertionError("both-null / both-set must be refused")


def test_frames_result_count_list_identity_is_model_side_and_disclosed():
    # #748 third review (ARC-748-F006): the public result's concrete list must
    # agree with its captured-frame count. Draft 2020-12 cannot relate an integer
    # field to an array's length, so the standard schema accepts the counterexample
    # and the test pins that disclosed model-only identity explicitly.
    import jsonschema
    import pydantic

    frame = {"path": "/tmp/f.png", "width": 1, "height": 1, "bytes": 1, "format": "png"}
    document = {"count": 2, "frames": [frame], "summary": None}

    with pytest.raises(pydantic.ValidationError):
        ScreenFramesResult.model_validate(document)
    validator = jsonschema.Draft202012Validator(ScreenFramesResult.model_json_schema())
    assert validator.is_valid(document)

    # A requested window is never empty; unlike the cross-field identity, this
    # lower bound is schema-expressible and therefore rejected by both owners.
    empty = {"count": 0, "frames": [], "summary": None}
    with pytest.raises(pydantic.ValidationError):
        ScreenFramesResult.model_validate(empty)
    assert not validator.is_valid(empty)


def test_frames_reply_count_mismatch_is_contract_violation(monkeypatch, tmp_path):
    # #748 review (ARC-748-F002): the reply's count and frame list are ONE
    # claim; a drifted harness reply where they disagree is refused for BOTH
    # result forms before any file is written.
    reply = screen_frames_reply([_PNG_B64, _PNG_B64])
    reply["count"] = 3
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
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
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert json.loads(result.stdout)["error"]["code"] == "contract_violation"
    assert not out_dir.exists()


def test_frames_summary_reports_null_dims_for_a_nonuniform_sequence(
    monkeypatch, tmp_path
):
    # #748 review: a mid-window viewport resize is engine-legal, so the
    # aggregate makes the uniform-size claim only when it is TRUE — differing
    # frame sizes report null dims, never the first frame's size as a false
    # sequence invariant.
    reply = screen_frames_reply([_PNG_B64, _PNG_B64])
    reply["frames"][1]["width"] = 32  # the sequence is no longer uniform
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out_dir = tmp_path / "frames"

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--frames",
            "2",
            "--summary",
            "--output-dir",
            str(out_dir),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    aggregate = json.loads(result.stdout)["summary"]
    assert aggregate["width"] is None and aggregate["height"] is None
    assert aggregate["total_bytes"] == 2 * len(_PNG_1X1)


def test_frames_budget_mismatch_is_contract_violation(monkeypatch, tmp_path):
    # #748 re-review (ARC-748-F007): no partial-success semantics — a
    # self-consistent reply for a DIFFERENT frame budget (here zero frames for
    # a request of three) is contract drift, refused before any file effect.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({"count": 0, "frames": []}),
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
            "--summary",
            "--output-dir",
            str(out_dir),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    data = json.loads(result.stdout)
    assert data["error"]["code"] == "contract_violation"
    assert "0 frames for a request of 3" in data["error"]["message"]
    assert not out_dir.exists()


def test_summary_dims_are_a_pair_in_model_and_schema():
    # #748 re-review (ARC-748-F006): both dims or neither — model and standard
    # validator agree on the half-null counterexample.
    import jsonschema
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ScreenFramesSummary(
            output_dir="/tmp",
            pattern="frame_%04d.png",
            width=1,
            height=None,
            total_bytes=1,
        )
    validator = jsonschema.Draft202012Validator(ScreenFramesSummary.model_json_schema())
    assert not validator.is_valid(
        {
            "output_dir": "/tmp",
            "pattern": "frame_%04d.png",
            "width": 1,
            "height": None,
            "total_bytes": 1,
        }
    )
    assert validator.is_valid(
        {
            "output_dir": "/tmp",
            "pattern": "frame_%04d.png",
            "width": None,
            "height": None,
            "total_bytes": 1,
        }
    )
    assert validator.is_valid(
        {
            "output_dir": "/tmp",
            "pattern": "frame_%04d.png",
            "width": 2,
            "height": 3,
            "total_bytes": 1,
        }
    )


def test_nonuniform_summary_renders_the_varied_size_state(monkeypatch, tmp_path):
    # #748 re-review (Standards 3): the legal non-uniform aggregate renders an
    # explicit state, never "NonexNone".
    reply = screen_frames_reply([_PNG_B64, _PNG_B64])
    reply["frames"][1]["width"] = 32
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    out_dir = tmp_path / "frames"

    result = CliRunner().invoke(
        app,
        [
            "screen",
            "frames",
            "--frames",
            "2",
            "--summary",
            "--output-dir",
            str(out_dir),
            "--project",
            str(minimal_project(tmp_path)),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "varied sizes x2" in result.stdout
    assert "None" not in result.stdout


def test_frames_xor_is_published_and_parity_held():
    # #748 review (ARC-748-F001): the exactly-one rule the model enforces must
    # give the SAME verdict to a standard Draft 2020-12 validator.
    import jsonschema

    schema = ScreenFramesResult.model_json_schema()
    validator = jsonschema.Draft202012Validator(schema)
    frame = {"path": "/tmp/f.png", "width": 1, "height": 1, "bytes": 1, "format": "png"}
    aggregate = {
        "output_dir": "/tmp",
        "pattern": "frame_%04d.png",
        "width": 1,
        "height": 1,
        "total_bytes": 1,
    }

    def check(frames, summary) -> bool:
        return validator.is_valid({"count": 1, "frames": frames, "summary": summary})

    assert check([frame], None)
    assert check(None, aggregate)
    assert not check(None, None)
    assert not check([frame], aggregate)


def test_frames_schema_publishes_the_summary_contract():
    schema = json.loads(
        CliRunner().invoke(app, ["screen", "frames", "--schema"]).stdout
    )
    assert "summary" in schema["input"]["properties"]
    output = schema["output"]
    # Required-but-nullable (#746 review discipline): both projections are
    # ALWAYS present keys; null is a value, not an omitted key.
    assert {"frames", "summary"} <= set(output["required"])
    assert "ScreenFramesSummary" in output["$defs"]
    assert {"output_dir", "pattern", "width", "height", "total_bytes"} == set(
        output["$defs"]["ScreenFramesSummary"]["properties"]
    )


def test_frames_summary_render_is_one_aggregate_line(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(screen_frames_reply([_PNG_B64, _PNG_B64])),
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
            "2",
            "--summary",
            "--output-dir",
            str(out_dir),
            "--project",
            str(minimal_project(tmp_path)),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "captured 2 frames" in result.stdout
    assert f"-> {out_dir}/frame_%04d.png" in result.stdout
    assert "frame_0000.png\n" not in result.stdout  # no per-frame rows
