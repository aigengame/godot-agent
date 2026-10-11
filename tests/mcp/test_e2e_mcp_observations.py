"""Real stdio MCP observations, including paused windows and post-exit logs."""

import json

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import stdio_client

from tests.mcp_support import call_tool_success, stdio_params, tool_text
from tests.observation_support import write_observation_project
from tests.support import DEFAULT_TIMEOUT, Gda


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_mcp_observations_serve_paused_windows_and_keep_post_exit_logs(
    tmp_path, daemon_runtime_dir, mode
):
    project = write_observation_project(tmp_path)
    params = stdio_params(project)

    async def drive():
        async with Client(stdio_client(params), mode=mode) as client:

            async def call(name, arguments):
                return await call_tool_success(client, name, arguments)

            async def refused(name, arguments, code):
                result = await client.call_tool(name, arguments)
                assert result.is_error is True
                assert result.structured_content is None
                error = json.loads(tool_text(result))["error"]
                assert (error["category"], error["code"]) == ("live", code)

            await call("daemon_start", {})
            for name in ("diag_errors", "logger_tail"):
                await refused(name, {}, "engine_session_not_running")
            assert (await call("daemon_status", {}))["session_id"] is None
            assert not (project / "launch-count.txt").exists()
            await call("daemon_wait_ready", {})
            before = await call("daemon_status", {})
            await call(
                "game_set",
                {"node": "/root/Main", "property": "paused", "value": "true"},
            )
            ticks = (
                await call("game_get", {"node": "/root/Main", "property": "ticks"})
            )["properties"][0]["value"]
            snapshot = await call("perf_monitors", {})
            assert snapshot["monitors"]["node_count"]["value"] >= 2
            window = await call(
                "perf_monitors",
                {"frames": 5, "monitors": ["node_count"], "summary": True},
            )
            assert window["frames"] == 5 and window["samples"] is None
            assert window["stats"]["node_count"]["count"] == 5
            timeline = await call(
                "perf_monitor", {"node": "/root/Main", "property": "ticks", "frames": 5}
            )
            assert [s["frame"] for s in timeline["samples"]] == [0, 1, 2, 3, 4]
            assert [s["value"] for s in timeline["samples"]] == [ticks] * 5
            signals = await call(
                "perf_monitor", {"node": "/root/Main", "signal": "ticked", "frames": 3}
            )
            assert signals["frames"] == 3 and signals["emissions"] == []
            errors = (await call("diag_errors", {"limit": 1}))["errors"]
            assert len(errors) == 1 and errors[0]["level"] == "script_error"
            assert "observer_failure" in errors[0]["message"]
            assert [f["function"] for f in errors[0]["callstack"]] == ["fail", "_ready"]
            records = (await call("logger_tail", {}))["records"]
            ready = next(r for r in records if r["message"] == "observer ready")
            assert (ready["level"], ready["origin"]) == ("warning", "gda_log")
            assert ready["fields"] == {
                "launch": 1,
                "precise": 3.141592653589793,
                "tiny": 1e-300,
            }
            filtered = (await call("logger_tail", {"level": "error", "limit": 1}))[
                "records"
            ]
            assert len(filtered) == 1 and filtered[0]["level"] == "error"
            assert filtered[0]["source"]["file"] == "res://main.gd"
            raw = (await call("logger_tail", {"raw": True}))["records"]
            assert all(r["level"] == "info" and r["fields"] == {} for r in raw)
            assert any(r["message"].startswith("<<<GDA:LOG>>>") for r in raw)
            await refused(
                "perf_monitor",
                {"node": "/root/Ghost", "property": "ticks", "frames": 2},
                "live_perf_node_not_found",
            )
            assert (await call("daemon_status", {}))["session_id"] == before[
                "session_id"
            ]

            # Quit during a multi-frame window: logs remain passive after disconnect.
            await call(
                "game_set",
                {"node": "/root/Main", "property": "end_on_sample", "value": "true"},
            )
            await refused(
                "perf_monitor",
                {"node": "/root/Main", "property": "sample", "frames": 3},
                "engine_disconnected",
            )
            persisted = (await call("logger_tail", {}))["records"]
            assert (
                next(r for r in persisted if r["message"] == "observer ready") == ready
            )
            assert (await call("diag_errors", {}))["errors"] == errors
            assert (await call("daemon_status", {}))["session_id"] == before[
                "session_id"
            ]
            assert (project / "launch-count.txt").read_text(encoding="utf-8") == "1"
            assert (await call("daemon_wait_ready", {}))["launched"] is True
            after = await call("daemon_status", {})
            assert after["pid"] == before["pid"]
            assert after["session_id"] != before["session_id"]
            current = (await call("logger_tail", {}))["records"]
            assert (
                next(r for r in current if r["message"] == "observer ready")["fields"][
                    "launch"
                ]
                == 2
            )
            assert (project / "launch-count.txt").read_text(encoding="utf-8") == "2"
            assert (await call("daemon_stop", {}))["stopped"] is True

    async def bounded_drive():
        with anyio.fail_after(DEFAULT_TIMEOUT):
            await drive()

    try:
        anyio.run(bounded_drive)
    finally:
        Gda(project)("daemon", "stop")
