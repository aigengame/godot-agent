"""S (e2e): `gda perf` live commands through the real gda-daemon loop (#223).

The Step-6 proof for perf: a real `gda daemon start` (real detached daemon, real
harness install, live-version gate) -> a real engine session it launches on
demand -> `gda perf monitors` returns the RUNNING game's live performance
snapshot, and `gda perf monitor --property ... --frames N` returns an N-sample
per-frame timeline collected by the harness's time-windowed multi-frame base.
Run e2e SERIALLY; not a fresh empty HOME (Godot first-run). The
`daemon_runtime_dir` fixture keeps the daemon's UDS path within `sun_path`.
"""

import json
import os

import pytest

from gda.commands.perf import PERF_MONITOR_NAMES

from tests.support import Gda, PERF_PACKED_VALUE_BYTES

from tests.conftest import LIVE_MAIN_TSCN, LIVE_PROJECT_GODOT

# A main scene with a Player Node2D so the launched session has a runtime
# SceneTree to monitor; Player.position is a Vector2 storage property the property
# timeline samples each frame. File logging stays disabled via project_godot (#180).
# A Player that DECLARES a custom signal and emits it once per _process frame with
# a single int argument (a monotonically increasing tick). The signal e2e watches
# this signal over a window and asserts the recorded emissions — exercising the
# real get_signal_list / connect / record / disconnect path in the harness (#239).
SIGNAL_PLAYER_GD = (
    "extends Node2D\n"
    "signal ticked(n)\n"
    "var _n := 0\n"
    "func _process(_delta: float) -> void:\n"
    "\t_n += 1\n"
    "\tticked.emit(_n)\n"
)
SIGNAL_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_a_live_perf_snapshot(tmp_path, daemon_runtime_dir):
    # `perf monitors`: a real daemon -> engine session -> the running game's live
    # Performance counters, snapshotted in one frame (frame-coherent, ADR-0020).
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        snap = run("perf", "monitors")
        assert snap.returncode == 0, snap.stdout + snap.stderr
        doc = json.loads(snap.stdout)
        # A real snapshot: a timestamp and the named monitors, with live values.
        assert isinstance(doc["timestamp"], int)
        monitors = doc["monitors"]
        assert "fps" in monitors and "static_memory" in monitors
        assert "node_count" in monitors and "draw_calls" in monitors
        # node_count is the running tree's live node total (at least Main + Player).
        assert monitors["node_count"]["value"] >= 2
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_a_property_timeline_over_a_window(tmp_path, daemon_runtime_dir):
    # `perf monitor --property --frames N`: the time-windowed multi-frame base
    # (#223) collects one sample per frame across the engine session and returns
    # the whole N-sample timeline in a single blocking call (ADR-0017 one-shot RPC).
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        timeline = run(
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--frames",
            "5",
        )
        assert timeline.returncode == 0, timeline.stdout + timeline.stderr
        doc = json.loads(timeline.stdout)
        assert doc["node"] == "/root/Main/Player"
        assert doc["kind"] == "property"
        assert doc["property"] == "position"
        # An N-sample timeline, one per frame, frame-indexed 0..N-1 (ADR-0020).
        assert doc["frames"] == 5
        assert len(doc["samples"]) == 5
        assert [s["frame"] for s in doc["samples"]] == [0, 1, 2, 3, 4]
        # Each sample carries the Vector2 position projection [x, y].
        assert all(len(s["value"]) == 2 for s in doc["samples"])
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_a_signal_timeline_over_a_window(tmp_path, daemon_runtime_dir):
    # `perf monitor --signal --frames N`: the time-windowed base connects a recorder
    # to a REAL script-declared signal, records each emission over the window, then
    # disconnects on finalize. The Player emits `ticked(n)` once per _process frame,
    # so a window of N frames records emissions carrying the int tick arg — the real
    # get_signal_list / connect / record / disconnect path (#239).
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SIGNAL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(SIGNAL_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        timeline = run(
            "perf",
            "monitor",
            "/root/Main/Player",
            "--signal",
            "ticked",
            "--frames",
            "5",
        )
        assert timeline.returncode == 0, timeline.stdout + timeline.stderr
        doc = json.loads(timeline.stdout)
        assert doc["node"] == "/root/Main/Player"
        assert doc["kind"] == "signal"
        assert doc["signal"] == "ticked"
        # The window collected its requested frame count (frames reports the ACTUAL
        # window length, consistent with the property monitor).
        assert doc["frames"] == 5
        # A property timeline is empty for a signal watch (the harness reports one).
        assert doc["samples"] == []
        # The Player emits once per _process frame, so the window records emissions —
        # at least one, each carrying the single int tick arg the signal declares.
        emissions = doc["emissions"]
        assert len(emissions) >= 1, doc
        for emission in emissions:
            assert len(emission["args"]) == 1
            assert isinstance(emission["args"][0], int)
            assert "frame" in emission and "timestamp" in emission
        # The recorded tick args are strictly increasing (the Player increments _n
        # each frame before emitting), proving real emission args were captured.
        ticks = [e["args"][0] for e in emissions]
        assert ticks == sorted(ticks) and len(set(ticks)) == len(ticks), ticks
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_perf_monitor_missing_node_reports_live_perf_node_not_found(
    tmp_path, daemon_runtime_dir
):
    # A path that resolves to no running node is the typed harness op-error,
    # relayed through the daemon (exit-0 sentinel) and mapped by classify_live.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        from gda.exit_codes import EXIT_LIVE

        missing = run(
            "perf",
            "monitor",
            "/root/Main/Ghost",
            "--property",
            "position",
            "--frames",
            "2",
        )
        assert missing.returncode == EXIT_LIVE, missing.stdout + missing.stderr
        assert json.loads(missing.stdout)["error"]["code"] == "live_perf_node_not_found"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_perf_monitors_without_a_daemon_reports_daemon_not_running(tmp_path):
    # The attach-or-fail path through the real DaemonRunner + discovery, no daemon.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    from gda.exit_codes import EXIT_LIVE

    proc = Gda(tmp_path, godot=None)(
        "perf",
        "monitors",
        "--json",
        extra_env={"XDG_RUNTIME_DIR": str(tmp_path / "run")},
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]


@pytest.mark.e2e
def test_perf_monitors_window_collects_bounded_stats_and_verdicts(
    tmp_path, daemon_runtime_dir
):
    # The #662 DoD: a real daemon -> engine session -> `perf monitors --frames`
    # samples the selected ENGINE monitors over a bounded window; the CLI
    # reports the aggregates, the raw samples, the echoed ceiling, and — with a
    # budget — the per-monitor verdicts. The budget pairs one rule that must
    # pass on any live session (node_count of this tiny scene stays far under
    # 1e6) with one that must fail (fps min 1e6), so `passed` is
    # deterministically false while the command still exits 0 (the verdict is
    # data). The plain snapshot is asserted afterwards on the SAME surface.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")
    budget = tmp_path / "budget.json"
    budget.write_text(
        '{"node_count": {"stat": "max", "max": 1000000},'
        ' "fps": {"stat": "min", "min": 1000000}}',
        encoding="utf-8",
    )

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        sampled = run(
            "perf",
            "monitors",
            "--frames",
            "30",
            "--monitor",
            "fps",
            "--monitor",
            "node_count",
            "--budget",
            str(budget),
        )
        assert sampled.returncode == 0, sampled.stdout + sampled.stderr
        data = json.loads(sampled.stdout)

        # The window mode, its echoed ceiling, and the raw samples.
        assert data["kind"] == "window"
        assert data["frames"] == 30
        assert data["max_frames"] == 600
        assert len(data["samples"]) == 30
        assert all(
            set(row["values"]) == {"fps", "node_count"} for row in data["samples"]
        )
        frames = [row["frame"] for row in data["samples"]]
        assert frames == list(range(30))

        # The aggregates cover exactly the selected monitors, over all 30 rows.
        assert set(data["stats"]) == {"fps", "node_count"}
        for stats in data["stats"].values():
            assert stats["count"] == 30
            assert stats["min"] <= stats["p50"] <= stats["p95"] <= stats["max"]

        # The budget verdicts: the generous rule passes, the absurd one fails,
        # so the overall verdict is false — as DATA, with exit code 0.
        assert data["budget"]["node_count"]["passed"] is True
        assert data["budget"]["fps"]["passed"] is False
        assert data["passed"] is False

        # The snapshot mode remains available on the same surface (#662 AC).
        snapshot = run("perf", "monitors")
        assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
        snap = json.loads(snapshot.stdout)
        assert snap["kind"] == "snapshot"
        assert "fps" in snap["monitors"]
    finally:
        run("daemon", "stop")


# The ceiling `perf monitors --frames 600 --summary --json` must stay under
# (#846). Measured on a real session over ALL 16 monitors (Godot 4.6.3, macOS,
# 2026-09-12): the compact result is the statistics block plus the mode fields,
# so its size follows the MONITOR count and not the frame count — 1,667 bytes at
# 600 frames, against 259,569 for the same window with its rows. The bound is
# ~4.9x the measured size, headroom for a widened monitor table but far below
# anything that grows with `--frames`: a result that started carrying per-frame
# data again fails here.
SUMMARY_RESULT_BYTE_BOUND = 8192


@pytest.mark.e2e
def test_a_600_frame_summary_window_stays_compact_and_reports_its_own_cost(
    tmp_path, daemon_runtime_dir
):
    # #846's live regression: a real daemon -> engine session -> a 600-frame
    # window over EVERY monitor, the size that made the dogfooding client
    # truncate the result. `--summary` returns the same statistics without the
    # rows, the result stays under a pinned byte bound, and `collector_bytes`
    # reports what the observer itself retained inside the game — the number a
    # `static_memory` rise has to be read against.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        summary = run("perf", "monitors", "--frames", "600", "--summary")
        assert summary.returncode == 0, summary.stdout + summary.stderr
        data = json.loads(summary.stdout)

        # The compact window: every aggregate, no rows, and it says so.
        assert data["kind"] == "window"
        assert data["frames"] == 600
        assert data["samples"] is None
        assert data["samples_omitted"] is True
        assert set(data["stats"]) == set(PERF_MONITOR_NAMES)
        assert all(stats["count"] == 600 for stats in data["stats"].values())
        assert data["budget"] is None and data["passed"] is None

        # The observer's own footprint, as the real harness computed it: one
        # packed column per monitor plus one of timestamps, 8 bytes per value.
        assert data["collector_bytes"] == (
            600 * (len(PERF_MONITOR_NAMES) + 1) * PERF_PACKED_VALUE_BYTES
        )

        # The bound the PR states: the result no longer grows with --frames.
        size = len(summary.stdout.encode("utf-8"))
        assert size <= SUMMARY_RESULT_BYTE_BOUND, size

        # The default is unchanged, and is what the bound exists to contrast
        # with: the same window WITH its rows is far larger and carries them.
        full = run("perf", "monitors", "--frames", "600")
        assert full.returncode == 0, full.stdout + full.stderr
        rows = json.loads(full.stdout)
        assert rows["samples_omitted"] is False
        assert len(rows["samples"]) == 600
        assert [row["frame"] for row in rows["samples"]] == list(range(600))
        assert set(rows["samples"][0]["values"]) == set(PERF_MONITOR_NAMES)
        # The timestamp column is the engine's clock, not a constant: only a
        # real session can show that, because every unit fake is CLI-side.
        assert rows["samples"][-1]["timestamp"] > rows["samples"][0]["timestamp"]
        assert rows["collector_bytes"] == data["collector_bytes"]
        assert len(full.stdout.encode("utf-8")) > SUMMARY_RESULT_BYTE_BOUND

        # The shared window base is untouched: the sibling op that runs on it
        # still collects its own per-frame timeline over the same session.
        timeline = run(
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--frames",
            "5",
        )
        assert timeline.returncode == 0, timeline.stdout + timeline.stderr
        assert len(json.loads(timeline.stdout)["samples"]) == 5
    finally:
        run("daemon", "stop")
