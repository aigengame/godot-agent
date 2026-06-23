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
from gda.models import ScreenCaptureParams, ScreenFramesParams
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
        ["screen", "capture", "--params-json", payload,
         "--project", str(_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["path"] == str(out)
    assert out.read_bytes().startswith(b"\x89PNG")  # the PNG was actually written


def test_screen_capture_params_json_without_output_is_invalid_params(tmp_path):
    # The worst finding: a JSON-only invocation that omits the now-required output is
    # a STRUCTURED invalid_params, never an AttributeError on a None path.
    result = CliRunner().invoke(
        app,
        ["screen", "capture", "--params-json", "{}",
         "--project", str(_project(tmp_path)), "--json"],
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
        ["screen", "frames", "--params-json", payload,
         "--project", str(_project(tmp_path)), "--json"],
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
            "screen", "capture",
            "--output", str(out),
            "--project", str(_project(tmp_path)), "--json",
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
            "screen", "capture", "--inline",
            "--output", str(out),
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # --inline embeds the base64 PNG ALONGSIDE the written file (both).
    assert data["inline"] == _PNG_B64
    assert data["path"] == str(out)
    assert out.read_bytes() == _PNG_1X1


def test_screen_capture_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir,
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "screen", "capture",
            "--output", str(tmp_path / "shot.png"),
            "--project", str(_project(tmp_path)), "--json",
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
            "screen", "capture",
            "--output", str(out),
            "--project", str(_project(tmp_path)), "--json",
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


def test_screen_capture_without_a_project_reports_project_not_found(monkeypatch, tmp_path):
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
            "screen", "frames", "--frames", "3",
            "--output-dir", str(out_dir),
            "--project", str(_project(tmp_path)), "--json",
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
            "screen", "frames", "--frames", "3",
            "--output-dir", str(tmp_path / "frames"),
            "--project", str(_project(tmp_path)), "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


def test_screen_frames_argv_frames_over_range_is_a_usage_error(monkeypatch, tmp_path):
    # --frames is bounded by the harness's per-window ceiling (MAX_WINDOW_FRAMES);
    # an over-range value is a usage error on argv (exit 2), engine never reached.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(screen_frames_reply([_PNG_B64])), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "screen", "frames", "--frames", "601",
            "--output-dir", str(tmp_path / "frames"),
            "--project", str(_project(tmp_path)), "--json",
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
        RunResult(stdout=sentinel(screen_frames_reply([_PNG_B64])), stderr="", exit_code=0),
    )
    payload = json.dumps({"frames": 601, "output_dir": str(tmp_path / "frames")})

    result = CliRunner().invoke(
        app,
        [
            "screen", "frames",
            "--project", str(_project(tmp_path)), "--json",
            "--params-json", payload,
        ],
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []
