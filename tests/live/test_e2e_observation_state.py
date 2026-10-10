"""Observe paused game state and daemon-owned logs through the public CLI."""

import json
import sys
import time

import pytest

from gda.exit_codes import EXIT_LIVE
from tests.observation_support import write_observation_project
from tests.support import Gda, ObservedWindowsProcess


pytestmark = pytest.mark.e2e


def test_observations_serve_paused_windows_and_logs_without_launching_a_session(
    tmp_path, daemon_runtime_dir
):
    run = Gda(write_observation_project(tmp_path), json_output=True)
    try:
        run.json("daemon", "start")
        for group, command in (("diag", "errors"), ("logger", "tail")):
            refused = run(group, command)
            assert refused.returncode == EXIT_LIVE, refused.stdout + refused.stderr
            assert (
                json.loads(refused.stdout)["error"]["code"]
                == "engine_session_not_running"
            )
        assert run.json("daemon", "status")["session_id"] is None
        assert not (tmp_path / "launch-count.txt").exists()

        run.json("daemon", "wait-ready")
        session = run.json("daemon", "status")["session_id"]
        run.json("game", "set", "/root/Main", "--property", "paused", "--value", "true")
        ticks = run.json("game", "get", "/root/Main", "--property", "ticks")[
            "properties"
        ][0]["value"]
        timeline = run.json(
            "perf", "monitor", "/root/Main", "--property", "ticks", "--frames", "5"
        )
        assert timeline["frames"] == 5
        assert [s["frame"] for s in timeline["samples"]] == [0, 1, 2, 3, 4]
        assert [s["value"] for s in timeline["samples"]] == [ticks] * 5
        signals = run.json(
            "perf", "monitor", "/root/Main", "--signal", "ticked", "--frames", "3"
        )
        assert signals["frames"] == 3 and signals["emissions"] == []
        assert run.json("perf", "monitors")["monitors"]["node_count"]["value"] >= 2
        window = run.json(
            "perf", "monitors", "--frames", "5", "--monitor", "node_count", "--summary"
        )
        assert window["frames"] == 5 and window["samples"] is None
        assert window["stats"]["node_count"]["count"] == 5

        errors = run.json("diag", "errors", "--limit", "1")["errors"]
        assert len(errors) == 1
        assert errors[0]["level"] == "script_error"
        assert "observer_failure" in errors[0]["message"]
        assert [f["function"] for f in errors[0]["callstack"]] == ["fail", "_ready"]
        records = run.json("logger", "tail")["records"]
        rich = next(r for r in records if r["message"] == "observer ready")
        assert (rich["level"], rich["origin"]) == ("warning", "gda_log")
        assert rich["fields"] == {
            "launch": 1,
            "precise": 3.141592653589793,
            "tiny": 1e-300,
        }
        assert any(r["message"] == "observer plain line" for r in records)
        filtered = run.json("logger", "tail", "--level", "error", "--limit", "1")[
            "records"
        ]
        assert len(filtered) == 1 and filtered[0]["level"] == "error"
        assert "observer_failure" in filtered[0]["message"]
        assert filtered[0]["source"]["file"] == "res://main.gd"
        raw = run.json("logger", "tail", "--raw")["records"]
        assert all(r["level"] == "info" and r["fields"] == {} for r in raw)
        assert any(r["message"].startswith("<<<GDA:LOG>>>") for r in raw)
        assert run.json("daemon", "status")["session_id"] == session
        assert (tmp_path / "launch-count.txt").read_text(encoding="utf-8") == "1"

        run.json(
            "game", "set", "/root/Main", "--property", "paused", "--value", "false"
        )
        resumed = run.json(
            "perf", "monitor", "/root/Main", "--property", "ticks", "--frames", "3"
        )
        values = [s["value"] for s in resumed["samples"]]
        assert ticks < values[0] < values[1] < values[2]
    finally:
        run("daemon", "stop")


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows observation deadline and owned replacement"
)
@pytest.mark.parametrize("retirement", ["timeout", "disconnect"])
def test_observation_failure_keeps_logs_until_the_owned_session_is_replaced(
    tmp_path, daemon_runtime_dir, retirement
):
    run = Gda(write_observation_project(tmp_path), json_output=True)
    engine = None
    try:
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        before = run.json("daemon", "status")
        engine = ObservedWindowsProcess(
            int((tmp_path / "engine-pid.txt").read_text(encoding="utf-8"))
        )
        initial = run.json("logger", "tail")["records"]
        ready = next(r for r in initial if r["message"] == "observer ready")
        assert ready["fields"]["launch"] == 1
        property_name = "stall" if retirement == "timeout" else "end_on_sample"
        run.json(
            "game", "set", "/root/Main", "--property", property_name, "--value", "true"
        )
        started = time.monotonic()
        failed = run(
            "perf", "monitor", "/root/Main", "--property", "sample", "--frames", "3"
        )
        elapsed = time.monotonic() - started
        assert failed.returncode == EXIT_LIVE, failed.stdout + failed.stderr
        error = json.loads(failed.stdout)["error"]
        expected = "live_timeout" if retirement == "timeout" else "engine_disconnected"
        assert (error["category"], error["code"]) == ("live", expected)
        if retirement == "timeout":
            assert "within 30s" in error["message"]
            assert 29 <= elapsed < 45, elapsed
        else:
            assert elapsed < 30, elapsed
            engine.exited()

        # Passive reads must retain the failed session, including after actual exit.
        records = run.json("logger", "tail")["records"]
        assert next(r for r in records if r["message"] == "observer ready") == ready
        raw = run.json("logger", "tail", "--raw")["records"]
        assert any(r["message"] == "observer plain line" for r in raw)
        errors = run.json("diag", "errors")["errors"]
        assert any("observer_failure" in e["message"] for e in errors)
        assert run.json("daemon", "status")["session_id"] == before["session_id"]
        assert (tmp_path / "launch-count.txt").read_text(encoding="utf-8") == "1"

        assert run.json("daemon", "wait-ready")["launched"] is True
        engine.exited()
        after = run.json("daemon", "status")
        assert after["pid"] == before["pid"]
        assert after["session_id"] != before["session_id"]
        assert (tmp_path / "launch-count.txt").read_text(encoding="utf-8") == "2"
        for flag in ("stall", "end_on_sample"):
            assert (
                run.json("game", "get", "/root/Main", "--property", flag)["properties"][
                    0
                ]["value"]
                is False
            )
        fresh = run.json(
            "perf", "monitor", "/root/Main", "--property", "ticks", "--frames", "3"
        )
        values = [s["value"] for s in fresh["samples"]]
        assert values[0] < values[1] < values[2]
        current = run.json("logger", "tail")["records"]
        assert (
            next(r for r in current if r["message"] == "observer ready")["fields"][
                "launch"
            ]
            == 2
        )
        assert not any(r["fields"].get("launch") == 1 for r in current)
    finally:
        run("daemon", "stop")
        if engine is not None:
            engine.close()
