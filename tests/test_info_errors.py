"""S3: gda info failure modes map to structured JSON errors + distinct exit codes.

Each failure mode is exercised by injecting a fake Godot runner (or crafted raw
stdout for the parse case). The contract under test (issue #3):

- stdout carries a single ``{"error": {...}}`` JSON object — the stable error shape.
- the process exits non-zero with a code that distinguishes the failure category.
- engine/script diagnostics are surfaced on stderr (ADR-0002).
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import LaunchFailure, RunResult
from tests.support import inject_runner as _inject
from tests.support import raw_sentinel, sentinel


def test_binary_not_found_maps_to_environment_error(monkeypatch):
    # The runner synthesizes exit 127 + a not-found diagnostic on stderr when
    # the binary is missing (#2 convention; ADR-0002 surfaces stderr).
    _inject(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda: Godot binary not found: /x/Godot\n",
            exit_code=127,
            launch_failure=LaunchFailure.NOT_FOUND,
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 127
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "environment"
    assert err["code"] == "binary_not_found"
    # Engine/script diagnostics are surfaced on stderr for inspection.
    assert "not found" in result.stderr


def test_launch_timeout_maps_to_environment_error_distinct_from_not_found(monkeypatch):
    # A launched-but-hung engine is bounded by the runner's timeout: exit 124
    # with a timeout diagnostic (#2). It is still an environment failure but
    # must be distinguishable from binary-not-found.
    _inject(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda: Godot timed out after 60.0s\n",
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 124
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "environment"
    # Distinguishable from the binary-not-found case via a distinct code.
    assert err["code"] == "launch_timeout"
    assert "timed out" in result.stderr


def test_operation_failure_maps_to_operation_error_distinct_from_environment(monkeypatch):
    # The engine launched and ran but the GDScript operation reported an error
    # and quit non-zero (no synthetic 124/127, no result sentinel). This is an
    # operation failure, distinct from the environment-error case.
    _inject(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda: unknown operation: bogus\n",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "operation_failed"
    assert "unknown operation" in result.stderr


def test_engine_signal_crash_maps_to_operation_error_distinct_from_clean_exit(monkeypatch):
    # subprocess reports a signal death as a NEGATIVE return code. The engine
    # ran but was killed (e.g. SIGSEGV) — surfaced as an engine_crashed code,
    # distinct from a clean non-zero operation exit, never a raw negative code.
    _inject(
        monkeypatch,
        RunResult(stdout="", stderr="", exit_code=-11),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "engine_crashed"
    # The signal number is surfaced for diagnosis.
    assert "11" in err["message"]


def test_missing_sentinel_maps_to_parse_error_distinct_from_operation(monkeypatch):
    # The engine exited 0 but stdout carries no result sentinel — a violation
    # of the structured-output contract (ADR-0002), distinct from an operation
    # error (which exits non-zero).
    _inject(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.stable\nno sentinel here\n",
            stderr="engine noise\n",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 5
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "parse"
    assert err["code"] == "contract_violation"


def test_wrong_shape_sentinel_payload_maps_to_parse_error(monkeypatch):
    # Sentinels present, payload is valid JSON, but it does not match the
    # EngineVersion shape (e.g. the GDScript emitted a partial/renamed payload,
    # or a non-object). This is still a contract violation — it must surface as
    # a structured parse error, NOT an unhandled pydantic ValidationError that
    # escapes as a traceback with exit 1.
    _inject(
        monkeypatch,
        RunResult(
            stdout=sentinel({"major": 4, "minor": 4}),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    # A clean exit (SystemExit via typer.Exit), NOT an escaped ValidationError.
    assert isinstance(result.exception, SystemExit)
    assert result.exit_code == 5
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "parse"
    assert err["code"] == "contract_violation"


def _version_payload(major: int, minor: int) -> str:
    return sentinel(
        {
            "major": major,
            "minor": minor,
            "patch": 0,
            "hex": (major << 16) | (minor << 8),
            "status": "stable",
            "build": "official",
            "hash": "0" * 40,
            "string": f"{major}.{minor}.0-stable (official)",
            "timestamp": 0,
        }
    )


def test_version_below_minimum_maps_to_version_error_distinct_from_environment(monkeypatch):
    # The engine launched and reported its version successfully, but it is below
    # the minimum supported version of 4.4 (ADR-0003). This is a version error,
    # distinct from the environment-error case.
    _inject(
        monkeypatch,
        RunResult(stdout=_version_payload(4, 3), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 3
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "version"
    assert err["code"] == "unsupported_version"
    # The detected version is surfaced in the message for diagnosis.
    assert "4.3" in err["message"]


def test_version_at_minimum_succeeds(monkeypatch):
    # 4.4 is exactly the floor — it must NOT be reported as unsupported.
    _inject(
        monkeypatch,
        RunResult(stdout=_version_payload(4, 4), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert (data["major"], data["minor"]) == (4, 4)


def test_malformed_sentinel_json_maps_to_parse_error(monkeypatch):
    # Sentinels are present but the payload between them is not valid JSON —
    # also a contract violation, surfaced as a parse error rather than an
    # opaque JSONDecodeError traceback.
    _inject(
        monkeypatch,
        RunResult(
            stdout=raw_sentinel("{not valid json}"),
            stderr="",
            exit_code=0,
        ),
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 5
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "parse"
    assert err["code"] == "contract_violation"
