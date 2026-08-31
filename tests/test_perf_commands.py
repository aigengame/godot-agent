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
    PERF_SAMPLE_REPLY,
    assert_no_pydantic_dump,
    error_sentinel,
    inject_live_runner,
    perf_sample_reply_all_monitors,
    plain_text,
    sentinel,
)


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


# --- perf monitors (single-frame snapshot) ------------------------------------


def test_perf_monitors_emits_a_snapshot_through_the_live_channel(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(PERF_MONITORS_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["perf", "monitors", "--project", str(_project(tmp_path)), "--json"]
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
        app, ["perf", "monitors", "--project", str(_project(tmp_path)), "--json"]
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
        app, ["perf", "monitors", "--project", str(_project(tmp_path)), "--json"]
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "daemon_not_running"


# --- argv selector / frames validation (#239) ---------------------------------
# Exactly one of --property/--signal is required and --frames is bounded. On the
# argv path these are usage errors (exit 2), the engine is never reached; the
# --params-json path surfaces them as the structured invalid_params error (see
# tests/test_params_json.py). Both forms derive from the one PerfMonitorParams
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
            str(_project(tmp_path)),
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
    # statistics over partial or disordered data.
    malformed = [
        {**PERF_SAMPLE_REPLY, "kind": "wrong"},
        {**PERF_SAMPLE_REPLY, "frames": 4},
        {
            **PERF_SAMPLE_REPLY,
            "samples": PERF_SAMPLE_REPLY["samples"][:4]
            + [{"frame": 4, "timestamp": 164, "values": {"fps": 60.0}}],
        },
        # The right rows in the wrong order (#735 review).
        {
            **PERF_SAMPLE_REPLY,
            "samples": [PERF_SAMPLE_REPLY["samples"][0]] * 5,
        },
        # A duplicated monitor declaration (#735 review).
        {**PERF_SAMPLE_REPLY, "monitors": ["fps", "fps"]},
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
    }
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
