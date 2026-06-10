"""SubprocessGodotRunner maps subprocess failures to a structured RunResult.

A hung or missing engine must not surface as a raw Python traceback; it is
turned into a non-zero-exit RunResult with a diagnostic on stderr, which the
CLI already handles via its exit-code path.
"""

import subprocess
from pathlib import Path

from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT
from gda.runner import LaunchFailure, SubprocessGodotRunner


def test_missing_binary_maps_to_nonzero_result_not_traceback():
    runner = SubprocessGodotRunner(Path("/nonexistent/Godot"))

    result = runner.run("info", {})

    assert result.exit_code == EXIT_NOT_FOUND
    assert "/nonexistent/Godot" in result.stderr
    assert result.stdout == ""
    # The runner flags this as a synthesized launch failure so the classifier
    # keys environment on the typed reason, not the overloaded exit code (#15).
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_timeout_maps_to_nonzero_result(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessGodotRunner(Path("/any/Godot"), timeout=0.01)

    result = runner.run("info", {})

    assert result.exit_code == EXIT_TIMEOUT
    assert "timed out" in result.stderr.lower()
    assert result.launch_failure is LaunchFailure.TIMEOUT


def test_timeout_is_passed_through_to_subprocess(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")

        class _Proc:
            stdout = "<<<GDA:RESULT>>>{}<<<GDA:END>>>"
            stderr = ""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessGodotRunner(Path("/any/Godot"), timeout=42.0)

    result = runner.run("info", {})

    assert captured["timeout"] == 42.0
    # An engine that actually returned has no synthesized launch failure, so its
    # exit code is classified as the engine's own result (#15).
    assert result.launch_failure is None
