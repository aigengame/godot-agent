"""SubprocessGodotRunner maps subprocess failures to a structured RunResult.

A hung or missing engine must not surface as a raw Python traceback; it is
turned into a non-zero-exit RunResult with a diagnostic on stderr, which the
CLI already handles via its exit-code path.
"""

import subprocess
from pathlib import Path

from gda.runner import SubprocessGodotRunner


def test_missing_binary_maps_to_nonzero_result_not_traceback():
    runner = SubprocessGodotRunner(Path("/nonexistent/Godot"))

    result = runner.run("info", {})

    assert result.exit_code != 0
    assert "/nonexistent/Godot" in result.stderr
    assert result.stdout == ""


def test_timeout_maps_to_nonzero_result(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessGodotRunner(Path("/any/Godot"), timeout=0.01)

    result = runner.run("info", {})

    assert result.exit_code != 0
    assert "timed out" in result.stderr.lower()


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

    runner.run("info", {})

    assert captured["timeout"] == 42.0
