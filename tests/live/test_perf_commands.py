"""`gda perf` — runtime performance monitoring of the running game, LIVE (#223).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer→classify_live→JSON pipeline (mirroring ``test_game_commands``), and the
no-daemon attach-or-fail path runs the real ``DaemonRunner`` against an empty
runtime dir. The real-engine round trip (the time-windowed harness base + the
Performance snapshot) is the e2e in ``test_e2e_perf``.
"""

import json
import re

from typer.testing import CliRunner

from gda.cli import app
from gda.exit_codes import EXIT_LIVE
from gda.models import MAX_WINDOW_FRAMES
from gda.runner import RunResult
from tests.support import (
    PERF_MONITOR_PROPERTY_RESULT,
    PERF_MONITOR_SIGNAL_RESULT,
    PERF_MONITORS_RESULT,
    PERF_PACKED_VALUE_BYTES,
    PERF_SAMPLE_REPLY,
    assert_no_pydantic_dump,
    error_sentinel,
    inject_live_runner,
    perf_sample_reply,
    perf_sample_reply_all_monitors,
    plain_text,
    sentinel,
    minimal_project,
)


# --- perf monitors (single-frame snapshot) ------------------------------------


def test_perf_monitors_emits_a_snapshot_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_MONITORS_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(minimal_project(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["timestamp"] == 12345
    assert data["monitors"]["fps"]["value"] == 60.0
    assert data["monitors"]["node_count"]["type"] == "float"
    # Routed through the LIVE seam, dispatching the perf-monitors operation (no args).
    assert fake.calls == [("perf-monitors", {})]


def test_perf_monitors_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir,
    # so no daemon is found — the attach-or-fail typed error (ADR-0017).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(minimal_project(tmp_path)), "--json"]
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


def test_perf_monitors_schema_is_self_describing():
    result = CliRunner().invoke(app, ["perf", "monitors", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


def test_perf_monitors_without_a_project_reports_project_not_found(
    monkeypatch, tmp_path
):
    # No --project and a projectless cwd -> the project resolves to None, which is a
    # project-resolution error, NOT a daemon error (ADR-0021).
    monkeypatch.chdir(tmp_path)  # tmp_path holds no project.godot

    result = CliRunner().invoke(app, ["perf", "monitors", "--json"])

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_perf_monitors_on_non_unix_reports_live_unsupported_platform(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("gda.live_runner._is_unix", lambda: False)

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(minimal_project(tmp_path)), "--json"]
    )

    assert result.exit_code != 0, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "live_unsupported_platform"


# --- perf monitor (time-windowed property/signal timeline) --------------------


def test_perf_monitor_property_emits_a_timeline_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--frames",
            "3",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "property"
    assert data["property"] == "position"
    assert [s["frame"] for s in data["samples"]] == [0, 1, 2]
    assert data["emissions"] == []
    # The node, property, signal (absent) and frame count are threaded to the op.
    assert fake.calls == [
        (
            "perf-monitor",
            {
                "node": "/root/Main/Player",
                "property": "position",
                "signal": None,
                "frames": 3,
            },
        )
    ]


def test_perf_monitor_signal_records_emissions_through_the_live_channel(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_MONITOR_SIGNAL_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--signal",
            "hit",
            "--frames",
            "3",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "signal"
    assert data["signal"] == "hit"
    assert data["emissions"][0]["args"] == [42]
    assert data["samples"] == []
    assert fake.calls == [
        (
            "perf-monitor",
            {
                "node": "/root/Main/Player",
                "property": None,
                "signal": "hit",
                "frames": 3,
            },
        )
    ]


def test_perf_monitor_default_frame_count_is_threaded(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    # The default frames (60) is passed through when --frames is omitted.
    assert fake.calls[0][1]["frames"] == 60


def test_perf_monitor_missing_node_reports_live_perf_node_not_found(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_perf_node_not_found", "no node at runtime path"
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Ghost",
            "--property",
            "position",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "live_perf_node_not_found"
    assert error["category"] == "live"


def test_perf_monitor_unknown_property_reports_live_perf_property_not_found(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel(
                "live_perf_property_not_found", "no readable property"
            ),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "nope",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "live_perf_property_not_found"


def test_perf_monitor_unknown_signal_reports_live_perf_signal_not_found(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("live_perf_signal_not_found", "no signal"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--signal",
            "nope",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "live_perf_signal_not_found"


def test_perf_monitor_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


# --- argv selector / frames validation (#239) ---------------------------------
# Exactly one of --property/--signal is required and --frames is bounded. On the
# argv path these are usage errors (exit 2), the engine is never reached; the
# --params-json path surfaces them as the structured invalid_params error (see
# tests/cli/test_params_json.py). Both forms derive from the one PerfMonitorParams
# model (ADR-0015), so neither can bypass the rule.


def test_perf_monitor_argv_both_selectors_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--signal",
            "hit",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_perf_monitor_argv_no_selector_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_perf_monitor_argv_frames_over_range_is_a_usage_error(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(PERF_MONITOR_PROPERTY_RESULT), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "/root/Main/Player",
            "--property",
            "position",
            "--frames",
            "601",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert fake.calls == []


def test_perf_monitor_schema_reports_kind_live_and_is_self_describing():
    result = CliRunner().invoke(app, ["perf", "monitor", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "live"


# --- perf monitors --frames (the #662 window mode: statistics + budgets) -------


def _budget_file(tmp_path, name: str, content: str | bytes):
    """Write ONE budget case to its OWN file (#735 recheck 2).

    A single shared filename let every case alias the last content written, so
    the admission table silently stopped covering its branches; a unique name
    per case keeps each entry pointing at its own bytes.
    """
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _window(tmp_path, *args):
    return CliRunner().invoke(
        app,
        [
            "perf",
            "monitors",
            *args,
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )


def test_perf_monitors_window_computes_stats_from_the_raw_samples(
    monkeypatch, tmp_path
):
    # The window mode (#662): the harness returns raw rows only; the CLI
    # computes the aggregates. The reply values make each statistic exactly
    # checkable (nearest-rank percentiles); the result names its mode, echoes
    # the ceiling, and carries no snapshot fields.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    result = _window(
        tmp_path, "--frames", "5", "--monitor", "fps", "--monitor", "draw_calls"
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "window"
    assert data["frames"] == 5
    assert data["max_frames"] == MAX_WINDOW_FRAMES
    assert data["timestamp"] is None and data["monitors"] is None
    assert data["stats"]["fps"] == {
        "count": 5,
        "min": 55.0,
        "max": 62.0,
        "mean": 59.0,
        "p50": 60.0,
        "p95": 62.0,
    }
    assert data["stats"]["draw_calls"] == {
        "count": 5,
        "min": 90.0,
        "max": 120.0,
        "mean": 103.0,
        "p50": 100.0,
        "p95": 120.0,
    }
    assert len(data["samples"]) == 5
    assert data["samples"][0]["values"] == {"fps": 60.0, "draw_calls": 100.0}
    assert data["budget"] is None
    assert data["passed"] is None
    assert fake.calls == [
        ("perf-sample", {"frames": 5, "monitors": ["fps", "draw_calls"]})
    ]


def test_perf_monitors_window_default_selection_samples_all_monitors(
    monkeypatch, tmp_path
):
    # No --monitor sends an empty selection; the harness reads that as ALL, and
    # the recipe expects the reply to cover the whole mirrored table.
    from gda.commands.perf import PERF_MONITOR_NAMES

    fake = inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(perf_sample_reply_all_monitors(PERF_MONITOR_NAMES)),
            stderr="",
            exit_code=0,
        ),
    )

    result = _window(tmp_path, "--frames", "1")

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert set(data["stats"]) == set(PERF_MONITOR_NAMES)
    assert fake.calls == [("perf-sample", {"frames": 1, "monitors": []})]


def test_perf_monitors_window_budget_verdicts_pass_and_fail(monkeypatch, tmp_path):
    # fps p50 60 >= 60 passes; draw_calls p95 120 > 100 fails; overall FAIL —
    # and the verdict is DATA: the command still exits 0.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )
    budget = _budget_file(
        tmp_path,
        "verdicts.json",
        '{"fps": {"stat": "p50", "min": 60}, '
        '"draw_calls": {"stat": "p95", "max": 100}}',
    )

    result = _window(
        tmp_path,
        "--frames",
        "5",
        "--monitor",
        "fps",
        "--monitor",
        "draw_calls",
        "--budget",
        str(budget),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["budget"]["fps"] == {
        "stat": "p50",
        "value": 60.0,
        "min": 60.0,
        "max": None,
        "passed": True,
    }
    assert data["budget"]["draw_calls"] == {
        "stat": "p95",
        "value": 120.0,
        "min": None,
        "max": 100.0,
        "passed": False,
    }
    assert data["passed"] is False
    assert len(fake.calls) == 1


def test_perf_monitors_selection_and_budget_require_frames(monkeypatch, tmp_path):
    # Without --frames there is no window for them to act on; a silently inert
    # option is worse than a refusal that names the rule (the GDA-DF-037 lesson).
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    monitor_only = _window(tmp_path, "--monitor", "fps")
    budget_only = _window(
        tmp_path, "--budget", str(_budget_file(tmp_path, "modeless.json", "{}"))
    )
    params_json = CliRunner().invoke(
        app,
        [
            "perf",
            "monitors",
            "--params-json",
            '{"monitors": ["fps"]}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert monitor_only.exit_code == 2, monitor_only.stdout + monitor_only.stderr
    assert "frames" in plain_text(monitor_only.stderr)
    assert budget_only.exit_code == 2, budget_only.stdout + budget_only.stderr
    assert json.loads(params_json.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_perf_monitors_window_unknown_monitor_is_rejected_before_dispatch(
    monkeypatch, tmp_path
):
    # Monitor names are bounded model-side against the mirrored harness table
    # (ADR-0015): argv is a usage error, --params-json the structured
    # invalid_params, and neither costs a live round trip.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    argv = _window(tmp_path, "--frames", "5", "--monitor", "fpss")
    params_json = CliRunner().invoke(
        app,
        [
            "perf",
            "monitors",
            "--params-json",
            '{"frames": 5, "monitors": ["fpss"]}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert argv.exit_code == 2, argv.stdout + argv.stderr
    assert json.loads(params_json.stdout)["error"]["code"] == "invalid_params"
    assert fake.calls == []


def test_perf_monitors_window_budget_file_problems_are_invalid_params(
    monkeypatch, tmp_path
):
    # The budget is validated BEFORE dispatch, so a bad one never costs a live
    # window. Admission is strict (#735 review): unique keys at every depth,
    # finite numbers only, UTF-8 only — a duplicate key must not resolve
    # last-key-wins into a gate nobody wrote, an infinite bound is not a
    # representable rule, and a mis-encoded file is a structured error, not a
    # traceback.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    cases = [
        ("missing.json", None, "cannot read"),
        ("not-json.json", "not json", "not valid JSON"),
        (
            "unknown-monitor.json",
            '{"fpss": {"stat": "p50", "min": 60}}',
            "unknown performance monitor",
        ),
        ("no-bound.json", '{"fps": {"stat": "p50"}}', "'min' and/or 'max'"),
        ("bad-stat.json", '{"fps": {"stat": "count", "min": 1}}', "stat"),
        ("foreign-key.json", '{"fps": {"stat": "p50", "min": 60, "top": 1}}', "top"),
        # Duplicate keys: top-level and nested (#735 review) — json.loads'
        # silent last-key-wins must not erase a real gate.
        (
            "dup-top.json",
            '{"fps": {"stat": "p50", "min": 100}, "fps": {"stat": "p50", "min": 0}}',
            "duplicate key",
        ),
        (
            "dup-nested.json",
            '{"fps": {"stat": "p50", "min": 1, "min": 0}}',
            "duplicate key",
        ),
        # Non-finite bounds: JSON-extension constants and exponent overflow.
        ("neg-inf.json", '{"fps": {"stat": "p50", "min": -Infinity}}', "non-finite"),
        ("pos-inf.json", '{"fps": {"stat": "p50", "min": Infinity}}', "non-finite"),
        ("nan.json", '{"fps": {"stat": "p50", "min": NaN}}', "non-finite"),
        ("overflow.json", '{"fps": {"stat": "p50", "min": 1e999}}', "finite number"),
        # Strict JSON numbers (#735 recheck): a quoted "10" or a boolean must
        # not be coerced into a gate nobody wrote.
        ("string-bound.json", '{"fps": {"stat": "p50", "min": "10"}}', "number"),
        ("bool-bound.json", '{"fps": {"stat": "p50", "min": true}}', "number"),
        # An impossible interval (#735 recheck): min > max can only ever fail,
        # which would misreport a config mistake as a performance failure.
        (
            "impossible.json",
            '{"fps": {"stat": "p50", "min": 100, "max": 50}}',
            "impossible interval",
        ),
        # A pathologically nested document (#735 recheck): the decoder's
        # RecursionError must land in the same structured failure, not escape
        # as a raw traceback.
        ("deep.json", '{"fps": ' + "[" * 20000 + "]" * 20000 + "}", "nests too deeply"),
        # A mis-encoded file is a structured error, not a UnicodeDecodeError.
        ("not-utf8.json", b'{"fps": {"stat": "p50", "min": 6\xff}}', "not valid UTF-8"),
    ]
    for name, content, fragment in cases:
        budget = (
            str(tmp_path / name)
            if content is None
            else str(_budget_file(tmp_path, name, content))
        )
        result = _window(tmp_path, "--frames", "5", "--budget", budget)
        error = json.loads(result.stdout)["error"]
        assert error["code"] == "invalid_params", (name, result.stdout)
        # Each case must fail for ITS OWN reason — this is what the aliased
        # single-file table could not prove (#735 recheck 2).
        assert fragment in error["message"], (name, error["message"])
    assert fake.calls == []


def test_perf_monitors_window_budget_entry_refusal_leaks_no_pydantic_dump(
    monkeypatch, tmp_path
):
    # A broken budget ENTRY is refused by the `PerfBudget` model, and the
    # loader used to interpolate the raw `ValidationError` (#759): the message
    # an agent reads carried the model class name, a `[type=...,
    # input_value=..., input_type=...]` tag echoing the caller's own budget-file
    # content, embedded newlines, and a `pydantic.dev` URL. It now goes through
    # the SAME shared renderer the argv and --params-json channels use
    # (`gda.errors.validation_error_message`, #713/#754), so one
    # `invalid_params` code speaks one language on every surface.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )
    # A distinctive bound value: only pydantic's own dump echoes a rejected
    # input back, so finding it in the message proves the leak directly.
    secret = "NOT-A-NUMBER-4d9f21"
    cases = [
        # A built-in check (strict float) — the message is pydantic's own `msg`.
        (
            "leak-builtin.json",
            '{"fps": {"stat": "p50", "min": "%s"}}' % secret,
            "min: Input should be a valid number",
        ),
        # A field-scoped enum check — the field path survives the rendering.
        (
            "leak-enum.json",
            '{"fps": {"stat": "%s", "min": 60}}' % secret,
            "stat: Input should be",
        ),
        # A model-level validator's own ValueError — unprefixed, untagged.
        (
            "leak-validator.json",
            '{"fps": {"stat": "p50"}}',
            "a budget entry needs 'min' and/or 'max'.",
        ),
    ]
    for name, content, sentence in cases:
        budget = _budget_file(tmp_path, name, content)
        result = _window(tmp_path, "--frames", "5", "--budget", str(budget))

        error = json.loads(result.stdout)["error"]
        assert error["code"] == "invalid_params", (name, result.stdout)
        assert_no_pydantic_dump(error["message"])
        # The dump's other two tells: the model class name, and the newlines it
        # embeds to lay one error out over three lines.
        assert "PerfBudget" not in error["message"], (name, error["message"])
        assert "\n" not in error["message"], (name, error["message"])
        # The caller's own budget-file content is not echoed back...
        assert secret not in error["message"], (name, error["message"])
        # ...while the entry NAME — bounded by PERF_MONITOR_NAMES, and what the
        # caller must fix — and the check's own sentence both survive.
        assert error["message"].startswith("budget entry 'fps' is invalid: "), (
            name,
            error["message"],
        )
        assert sentence in error["message"], (name, error["message"])
    assert fake.calls == []


def test_perf_monitors_window_budget_outside_the_selection_is_invalid_params(
    monkeypatch, tmp_path
):
    # A budget for a monitor the window does not sample cannot produce a
    # verdict; refusing it names the fix instead of silently skipping the gate.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )
    budget = _budget_file(
        tmp_path, "outside.json", '{"draw_calls": {"stat": "p95", "max": 100}}'
    )

    result = _window(
        tmp_path, "--frames", "5", "--monitor", "fps", "--budget", str(budget)
    )

    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_params"
    assert "draw_calls" in error["message"]
    assert fake.calls == []


def test_perf_monitors_budget_path_expands_a_literal_tilde(monkeypatch, tmp_path):
    # The budget path rides NormalizedPath (ADR-0006/ADR-0015): a literal
    # `~/...` — as --params-json, MCP, or a shell-less argv passes it — expands
    # model-side on BOTH input channels instead of being opened verbatim.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "budget.json").write_text(
        '{"fps": {"stat": "p50", "min": 60}}', encoding="utf-8"
    )
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    argv = _window(
        tmp_path,
        "--frames",
        "5",
        "--monitor",
        "fps",
        "--monitor",
        "draw_calls",
        "--budget",
        "~/budget.json",
    )
    params_json = CliRunner().invoke(
        app,
        [
            "perf",
            "monitors",
            "--params-json",
            '{"frames": 5, "monitors": ["fps", "draw_calls"], '
            '"budget": "~/budget.json"}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    for result in (argv, params_json):
        assert result.exit_code == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["budget"]["fps"]["passed"] is True
    assert len(fake.calls) == 2


def test_perf_monitors_window_frames_over_ceiling_is_a_usage_error(
    monkeypatch, tmp_path
):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    result = _window(tmp_path, "--frames", str(MAX_WINDOW_FRAMES + 1))

    assert result.exit_code == 2, result.stdout + result.stderr
    assert "--frames" in plain_text(result.stderr)
    assert fake.calls == []


def test_perf_monitors_help_states_the_window_ceiling():
    result = CliRunner().invoke(app, ["perf", "monitors", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = re.sub(r"\s+", " ", plain_text(result.stdout))
    assert str(MAX_WINDOW_FRAMES) in flat
    assert "per-window ceiling" in flat


def test_perf_monitors_window_malformed_reply_is_a_contract_violation(
    monkeypatch, tmp_path
):
    # The wire reply's SELF-consistency is validated (the #732 lesson): a
    # drifted harness must classify as contract_violation, never produce
    # statistics over partial data.
    columns = PERF_SAMPLE_REPLY["values"]
    malformed = [
        {**PERF_SAMPLE_REPLY, "kind": "wrong"},
        {**PERF_SAMPLE_REPLY, "frames": 4},
        # A timestamp column that does not span the declared window.
        {**PERF_SAMPLE_REPLY, "timestamps": PERF_SAMPLE_REPLY["timestamps"][:4]},
        # A value column short of one frame (#846: the packed twin of the
        # partial-row arm this replaced).
        {
            **PERF_SAMPLE_REPLY,
            "values": {**columns, "fps": columns["fps"][:4]},
        },
        # Columns that are not the declared monitors.
        {**PERF_SAMPLE_REPLY, "values": {"fps": columns["fps"]}},
        # A duplicated monitor declaration (#735 review).
        {**PERF_SAMPLE_REPLY, "monitors": ["fps", "fps"]},
        # No disclosure of what the observer retained.
        {k: v for k, v in PERF_SAMPLE_REPLY.items() if k != "collector_bytes"},
    ]
    for payload in malformed:
        inject_live_runner(
            monkeypatch,
            RunResult(stdout=sentinel(payload), stderr="", exit_code=0),
        )
        result = _window(
            tmp_path, "--frames", "5", "--monitor", "fps", "--monitor", "draw_calls"
        )
        assert json.loads(result.stdout)["error"]["code"] == "contract_violation", (
            payload,
            result.stdout,
        )


def test_perf_monitors_window_reply_must_match_the_request(monkeypatch, tmp_path):
    # Correlation (#735 review): a SELF-consistent reply answering a DIFFERENT
    # request — another window length, another selection — is contract drift,
    # not a success to publish statistics from.
    # (arm the fake per invocation: same canned 5-frame fps+draw_calls reply)
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )
    wrong_frames = _window(tmp_path, "--frames", "3", "--monitor", "fps")
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )
    wrong_selection = _window(tmp_path, "--frames", "5", "--monitor", "fps")

    for result in (wrong_frames, wrong_selection):
        assert json.loads(result.stdout)["error"]["code"] == "contract_violation", (
            result.stdout
        )


def test_perf_monitors_window_with_no_daemon_reports_daemon_not_running(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = _window(tmp_path, "--frames", "5")

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


# --- perf monitors --frames: the packed window, --summary, collector_bytes (#846) ---


# ONE window in the shape the harness returned BEFORE #846: a Dictionary per
# frame, carrying its own frame index, its timestamp, and a name->value map. The
# values are chosen to be discriminating rather than captured from a session (see
# RECORDED_AGGREGATES). It is INPUT to nothing — the CLI does not decode this
# shape any more, and a reply in it is contract drift (ADR-0018's 2026-09-08
# current-harness note; the arm below pins that) — it is kept here as the
# auditable SOURCE of the aggregates pinned beside it.
RECORDED_DICTIONARY_WINDOW = {
    "kind": "sample",
    "frames": 20,
    "monitors": ["fps", "static_memory"],
    "samples": [
        {
            "frame": 0,
            "timestamp": 100,
            "values": {"fps": 59.5, "static_memory": 1048576.0},
        },
        {
            "frame": 1,
            "timestamp": 116,
            "values": {"fps": 61.25, "static_memory": 1051136.0},
        },
        {
            "frame": 2,
            "timestamp": 132,
            "values": {"fps": 58.0, "static_memory": 1053696.0},
        },
        {
            "frame": 3,
            "timestamp": 148,
            "values": {"fps": 60.75, "static_memory": 1054720.0},
        },
        {
            "frame": 4,
            "timestamp": 164,
            "values": {"fps": 57.5, "static_memory": 1057280.0},
        },
        {
            "frame": 5,
            "timestamp": 180,
            "values": {"fps": 62.0, "static_memory": 1059840.0},
        },
        {
            "frame": 6,
            "timestamp": 196,
            "values": {"fps": 60.0, "static_memory": 1060864.0},
        },
        {
            "frame": 7,
            "timestamp": 212,
            "values": {"fps": 59.0, "static_memory": 1063424.0},
        },
        {
            "frame": 8,
            "timestamp": 228,
            "values": {"fps": 63.5, "static_memory": 1065984.0},
        },
        {
            "frame": 9,
            "timestamp": 244,
            "values": {"fps": 58.25, "static_memory": 1067008.0},
        },
        {
            "frame": 10,
            "timestamp": 260,
            "values": {"fps": 61.0, "static_memory": 1069568.0},
        },
        {
            "frame": 11,
            "timestamp": 276,
            "values": {"fps": 60.5, "static_memory": 1072128.0},
        },
        {
            "frame": 12,
            "timestamp": 292,
            "values": {"fps": 56.75, "static_memory": 1073152.0},
        },
        {
            "frame": 13,
            "timestamp": 308,
            "values": {"fps": 64.0, "static_memory": 1075712.0},
        },
        {
            "frame": 14,
            "timestamp": 324,
            "values": {"fps": 59.75, "static_memory": 1078272.0},
        },
        {
            "frame": 15,
            "timestamp": 340,
            "values": {"fps": 62.5, "static_memory": 1079296.0},
        },
        {
            "frame": 16,
            "timestamp": 356,
            "values": {"fps": 57.0, "static_memory": 1081856.0},
        },
        {
            "frame": 17,
            "timestamp": 372,
            "values": {"fps": 61.75, "static_memory": 1084416.0},
        },
        {
            "frame": 18,
            "timestamp": 388,
            "values": {"fps": 60.25, "static_memory": 1085440.0},
        },
        {
            "frame": 19,
            "timestamp": 404,
            "values": {"fps": 58.5, "static_memory": 1088000.0},
        },
    ],
}

# What the CLI's aggregation produced over that window, recorded by running the
# PRE-#846 aggregation (`_stats_over` over the dictionary rows, at b7c485693)
# and pinned here as literals. Discriminating on purpose: the means are not
# sampled values (60.0875, 1068518.4), p50 is not the mean, and p95 is the
# second-largest rather than the max — so a projection that lost, reordered, or
# truncated a column could not reproduce them by accident.
RECORDED_AGGREGATES = {
    "fps": {
        "count": 20,
        "min": 56.75,
        "max": 64.0,
        "mean": 60.0875,
        "p50": 60.0,
        "p95": 63.5,
    },
    "static_memory": {
        "count": 20,
        "min": 1048576.0,
        "max": 1088000.0,
        "mean": 1068518.4,
        "p50": 1067008.0,
        "p95": 1085440.0,
    },
}


def _packed_recording() -> dict:
    """``RECORDED_DICTIONARY_WINDOW``'s values, in the PACKED wire shape (#846)."""
    rows = RECORDED_DICTIONARY_WINDOW["samples"]
    return perf_sample_reply(
        [row["timestamp"] for row in rows],
        {
            name: [row["values"][name] for row in rows]
            for name in RECORDED_DICTIONARY_WINDOW["monitors"]
        },
    )


def _recorded_window(monkeypatch, tmp_path, *args):
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(_packed_recording()), stderr="", exit_code=0),
    )
    return _window(
        tmp_path,
        "--frames",
        "20",
        "--monitor",
        "fps",
        "--monitor",
        "static_memory",
        *args,
    )


def test_the_packed_aggregation_equals_the_recorded_dictionary_aggregates(
    monkeypatch, tmp_path
):
    # #846 AC2. The window's storage changed shape; its STATISTICS must not.
    # Two live windows are never equal, so the equality is proven on a recording:
    # the aggregates above were produced by the pre-#846 aggregation over the
    # dictionary-shaped rows, and the CLI now reaches them from the packed
    # columns carrying the same values. The old shape is not fed to the CLI —
    # it is not a supported input (see the arm below).
    result = _recorded_window(monkeypatch, tmp_path)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["stats"] == RECORDED_AGGREGATES


def test_the_previous_dictionary_reply_shape_is_contract_drift(monkeypatch, tmp_path):
    # The CLI targets the harness bundled with it (ADR-0018's 2026-09-08
    # current-harness note): a mixed-version session is not a compatibility
    # target, so the reply shape #846 replaced is refused rather than decoded.
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(RECORDED_DICTIONARY_WINDOW), stderr="", exit_code=0),
    )

    result = _window(
        tmp_path, "--frames", "20", "--monitor", "fps", "--monitor", "static_memory"
    )

    assert json.loads(result.stdout)["error"]["code"] == "contract_violation", (
        result.stdout
    )


def test_the_rebuilt_rows_carry_the_recorded_window_frame_by_frame(
    monkeypatch, tmp_path
):
    # The packed columns are the storage; the per-frame rows are a projection of
    # them. Without --summary the projection is published, and it must be the
    # recorded window row for row — the frame index positional, the timestamp
    # from its own column, every selected monitor's value at that index.
    result = _recorded_window(monkeypatch, tmp_path)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["samples"] == RECORDED_DICTIONARY_WINDOW["samples"]


def test_a_window_reports_what_the_observer_retained(monkeypatch, tmp_path):
    # The observer discloses its own footprint (#846): 8 bytes per stored value,
    # over one column per sampled monitor plus one of timestamps. 20 frames x
    # (2 monitors + 1 timestamp column) x 8 = 480 bytes.
    result = _recorded_window(monkeypatch, tmp_path)

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["collector_bytes"] == 20 * 3 * PERF_PACKED_VALUE_BYTES == 480
    # It is the HARNESS's number, relayed — not one the CLI recomputes from the
    # request — so a harness reporting a different retention is believed.
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({**_packed_recording(), "collector_bytes": 4096}),
            stderr="",
            exit_code=0,
        ),
    )
    relayed = _window(
        tmp_path, "--frames", "20", "--monitor", "fps", "--monitor", "static_memory"
    )
    assert json.loads(relayed.stdout)["collector_bytes"] == 4096


def test_a_snapshot_reports_no_retention_at_all(monkeypatch, tmp_path):
    # A snapshot reads one frame and keeps nothing, so both window-only
    # disclosures are null rather than a zero nobody measured.
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_MONITORS_RESULT), stderr="", exit_code=0),
    )

    result = _window(tmp_path)

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "snapshot"
    assert data["collector_bytes"] is None
    assert data["samples_omitted"] is None


def test_summary_omits_the_rows_and_keeps_every_other_window_field(
    monkeypatch, tmp_path
):
    # #846 AC1. --summary changes ONE thing: the per-frame rows are left out.
    # The window is still sampled in full, so the statistics are the recorded
    # ones and the retained bytes are unchanged.
    with_rows = _recorded_window(monkeypatch, tmp_path)
    summarized = _recorded_window(monkeypatch, tmp_path, "--summary")

    assert summarized.exit_code == 0, summarized.stdout + summarized.stderr
    compact = json.loads(summarized.stdout)
    full = json.loads(with_rows.stdout)
    assert compact["samples"] is None
    assert compact["samples_omitted"] is True
    assert full["samples_omitted"] is False
    assert compact["stats"] == RECORDED_AGGREGATES
    assert compact["collector_bytes"] == full["collector_bytes"]
    assert {k: v for k, v in compact.items() if k != "samples"} == {
        **{k: v for k, v in full.items() if k != "samples"},
        "samples_omitted": True,
    }
    # And the point of the flag: the compact envelope does not grow with frames.
    assert len(summarized.stdout) < len(with_rows.stdout)


def test_summary_keeps_the_budget_verdicts(monkeypatch, tmp_path):
    # The budget gates the window's statistics, which --summary does not touch,
    # so the verdicts and the overall `passed` travel with the compact form too.
    budget = tmp_path / "summary-budget.json"
    budget.write_text(
        json.dumps(
            {
                "fps": {"stat": "p50", "min": 60.0},
                "static_memory": {"stat": "max", "max": 1000.0},
            }
        ),
        encoding="utf-8",
    )

    result = _recorded_window(
        monkeypatch, tmp_path, "--summary", "--budget", str(budget)
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["samples"] is None and data["samples_omitted"] is True
    assert data["budget"]["fps"]["passed"] is True
    assert data["budget"]["static_memory"]["passed"] is False
    assert data["passed"] is False


def test_summary_requires_frames(monkeypatch, tmp_path):
    # Like --monitor and --budget: a compaction with no window to compact is
    # refused BY NAME rather than silently ignored. The rule lives on the params
    # model, so the argv path refuses it as usage and --params-json reaches the
    # same verdict structurally.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    argv = _window(tmp_path, "--summary")
    params_json = CliRunner().invoke(
        app,
        [
            "perf",
            "monitors",
            "--params-json",
            '{"summary": true}',
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert argv.exit_code == 2, argv.stdout + argv.stderr
    assert "summary" in plain_text(argv.stderr)
    assert json.loads(params_json.stdout)["error"]["code"] == "invalid_params"
    assert "summary" in json.loads(params_json.stdout)["error"]["message"]
    assert fake.calls == []


def test_summary_sends_the_harness_the_same_request(monkeypatch, tmp_path):
    # --summary is a RESULT projection, not a sampling mode: the harness still
    # collects and returns the whole window, so the wire request is unchanged
    # and the compaction happens CLI-side.
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_SAMPLE_REPLY), stderr="", exit_code=0),
    )

    result = _window(
        tmp_path,
        "--frames",
        "5",
        "--monitor",
        "fps",
        "--monitor",
        "draw_calls",
        "--summary",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        ("perf-sample", {"frames": 5, "monitors": ["fps", "draw_calls"]})
    ]


def test_perf_monitors_help_states_the_observer_cost_and_summary():
    # The help must say that a long window allocates INSIDE the game and how to
    # read the disclosure against static_memory (#846's help requirement).
    result = CliRunner().invoke(app, ["perf", "monitors", "--help"])

    assert result.exit_code == 0, result.stdout + result.stderr
    flat = re.sub(r"\s+", " ", plain_text(result.stdout))
    assert "--summary" in flat
    assert "samples_omitted" in flat
    assert "collector_bytes" in flat
    assert "static_memory" in flat
    # And it must say what that number is NOT: a lower bound, read by order of
    # magnitude, so the help does not point a caller at a false game leak
    # (round 1 measured the observer's own rise at about 1.4x the figure).
    assert "LOWER bound" in flat
    assert "ORDER OF MAGNITUDE" in flat


def test_perf_monitors_schema_and_models_reach_the_same_verdict():
    # The #735 recheck's hard finding: the published contracts must not be
    # wider than the runtime ABI (ADR-0015 input / ADR-0004 output — gda-mcp
    # derives its wire schemas from these). One corpus runs through the EMITTED
    # schema and the MODEL; every instance must get the same verdict.
    import jsonschema
    import pydantic

    from gda.commands.perf import PerfMonitorsParams, PerfMonitorsResult

    doc = json.loads(CliRunner().invoke(app, ["perf", "monitors", "--schema"]).stdout)

    def schema_ok(schema, instance) -> bool:
        try:
            jsonschema.validate(instance=instance, schema=schema)
        except jsonschema.ValidationError:
            return False
        return True

    def model_ok(model, instance) -> bool:
        try:
            model.model_validate(instance)
        except pydantic.ValidationError:
            return False
        return True

    snapshot = {"kind": "snapshot", **PERF_MONITORS_RESULT}
    window = {
        "kind": "window",
        "frames": 1,
        "max_frames": 600,
        "stats": {
            "fps": {
                "count": 1,
                "min": 60.0,
                "max": 60.0,
                "mean": 60.0,
                "p50": 60.0,
                "p95": 60.0,
            }
        },
        "samples": [{"frame": 0, "timestamp": 100, "values": {"fps": 60.0}}],
        "samples_omitted": False,
        "collector_bytes": 16,
    }
    summarized = {**window, "samples": None, "samples_omitted": True}
    input_corpus = [
        {},  # the bare snapshot request
        {"frames": 5},
        {"frames": 5, "monitors": ["fps"]},
        # The recheck's counterexample: a selection with no window to act on.
        {"monitors": ["fps"]},
        {"budget": "budget.json"},
        {"frames": None, "monitors": ["fps"]},
        # Recheck 2 (#735): the bidirectional mismatches — an unknown monitor
        # the schema used to accept, and the lax coercions the schema refused.
        {"frames": 5, "monitors": ["fpss"]},
        {"frames": "5"},
        {"frames": True},
        # JSON Schema's `integer` admits a zero-fraction float; so must the ABI.
        {"frames": 5.0},
        # Recheck 3 (#735): the published range must be REAL JSON Schema
        # keywords (minimum/maximum) — raw ge/le keys are ignored by standard
        # validators, so these out-of-range values used to pass the schema.
        {"frames": 0},
        {"frames": -1},
        {"frames": 601},
        # #846: 'summary' compacts a WINDOW, so it needs one to compact — and a
        # default-valued summary with no window is still just a snapshot request.
        {"frames": 5, "summary": True},
        {"summary": True},
        {"summary": False},
        # The lax-coercion pair, the shape recheck 2 caught on `frames`: the
        # published contract says boolean, so the ABI must not admit these.
        {"frames": 5, "summary": "yes"},
        {"frames": 5, "summary": 1},
    ]
    output_corpus = [
        snapshot,
        window,
        {**window, "budget": None, "passed": None},
        # The recheck's counterexamples: a bare kind, and mixed-mode fields.
        {"kind": "snapshot"},
        {**snapshot, "stats": window["stats"]},
        {**window, "timestamp": 12345},
        # A window whose budget travels without its overall verdict.
        {**window, "budget": {}, "passed": None},
        # #846: both window forms, and the two ways to claim only one of them.
        summarized,
        {**window, "samples": None},
        {**summarized, "samples": window["samples"]},
        # A window that discloses neither what it kept nor what it retained.
        {k: v for k, v in window.items() if k != "samples_omitted"},
        {k: v for k, v in window.items() if k != "collector_bytes"},
        # A snapshot cannot borrow the window-only disclosures — either of
        # them: the schema pins both to null, and round 1 showed the pair was
        # only half covered here.
        {**snapshot, "collector_bytes": 16},
        {**snapshot, "samples_omitted": False},
        # A published `minimum: 0` that no instance exercises: a negative
        # retention figure is not a fact any window can report.
        {**window, "collector_bytes": -1},
    ]
    for instance in input_corpus:
        assert schema_ok(doc["input"], instance) == model_ok(
            PerfMonitorsParams, instance
        ), instance
    for instance in output_corpus:
        assert schema_ok(doc["output"], instance) == model_ok(
            PerfMonitorsResult, instance
        ), instance
    # And the direction that matters: the published schemas REJECT the
    # counterexamples (parity alone could hold with both sides too wide) —
    # and the runtime rejects what the schema rejects (recheck 2's lax pair).
    assert not schema_ok(doc["input"], {"monitors": ["fps"]})
    assert not schema_ok(doc["input"], {"frames": 5, "monitors": ["fpss"]})
    assert not model_ok(PerfMonitorsParams, {"frames": "5"})
    assert not model_ok(PerfMonitorsParams, {"frames": True})
    assert model_ok(PerfMonitorsParams, {"frames": 5.0})
    assert not schema_ok(doc["input"], {"frames": 0})
    assert not schema_ok(doc["input"], {"frames": 601})
    assert not schema_ok(doc["output"], {"kind": "snapshot"})
    assert not schema_ok(doc["output"], {**snapshot, "stats": window["stats"]})
    # #846: the window branch admits BOTH forms, and neither half-claim.
    assert schema_ok(doc["output"], summarized)
    assert not schema_ok(doc["output"], {**window, "samples": None})
    assert not schema_ok(doc["output"], {**summarized, "samples": window["samples"]})
    assert not schema_ok(doc["input"], {"summary": True})
    assert not model_ok(PerfMonitorsParams, {"frames": 5, "summary": "yes"})
    assert not model_ok(PerfMonitorsParams, {"frames": 5, "summary": 1})
    # #846, round 1: `collector_bytes`' published `minimum: 0` is derived from
    # the model's `ge=0`, so dropping the bound moves BOTH halves together and
    # parity alone stays silent. The published fact needs its own one-sided
    # assertion, the same reason recheck 3's range keywords have one.
    assert not schema_ok(doc["output"], {**window, "collector_bytes": -1})
    assert not model_ok(PerfMonitorsResult, {**window, "collector_bytes": -1})
