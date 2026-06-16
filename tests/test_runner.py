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


def test_directory_binary_maps_to_not_found_not_traceback(tmp_path):
    # A directory passed as --godot (e.g. the bundle "Godot.app", a natural
    # $GDA_GODOT mistake) cannot be exec'd; the OS raises a PermissionError /
    # IsADirectoryError that must not escape as a raw traceback (#33).
    runner = SubprocessGodotRunner(tmp_path)

    result = runner.run("info", {})

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(tmp_path) in result.stderr
    assert result.stdout == ""
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_non_executable_file_binary_maps_to_not_found_not_traceback(tmp_path):
    # A plain, non-executable file passed as --godot cannot be exec'd; the OS
    # raises a PermissionError that the runner must catch and synthesize as a
    # launch failure rather than leak as a traceback (#33).
    not_exec = tmp_path / "notgodot.txt"
    not_exec.write_text("i am not an engine")
    runner = SubprocessGodotRunner(not_exec)

    result = runner.run("info", {})

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(not_exec) in result.stderr
    assert result.stdout == ""
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_engine_output_is_decoded_as_utf8_regardless_of_host_locale(monkeypatch):
    # Godot's JSON.stringify emits raw UTF-8, but subprocess(text=True) would
    # decode with the host locale. On a non-UTF-8 locale a non-ASCII node name
    # mojibakes or raises UnicodeDecodeError. The runner must capture bytes and
    # decode UTF-8 explicitly so user content round-trips (#33). We prove this by
    # returning raw UTF-8 *bytes* from subprocess (the bytes mode the fix uses).
    payload = '<<<GDA:RESULT>>>{"name":"日本語"}<<<GDA:END>>>'
    stdout_bytes = payload.encode("utf-8")
    stderr_bytes = "警告: ノード名\n".encode("utf-8")

    def fake_run(cmd, **kwargs):
        # The fix drops text=True and captures bytes; assert that contract here
        # so the test fails loudly if decoding silently reverts to locale text.
        assert kwargs.get("text") in (None, False)

        class _Proc:
            stdout = stdout_bytes
            stderr = stderr_bytes
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessGodotRunner(Path("/any/Godot"))

    result = runner.run("scene", {})

    assert "日本語" in result.stdout
    assert "警告: ノード名" in result.stderr


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
            # The runner captures bytes (no text=True) and decodes UTF-8 itself,
            # so the double mirrors that real subprocess contract (#33).
            stdout = b"<<<GDA:RESULT>>>{}<<<GDA:END>>>"
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessGodotRunner(Path("/any/Godot"), timeout=42.0)

    result = runner.run("info", {})

    assert captured["timeout"] == 42.0
    # An engine that actually returned has no synthesized launch failure, so its
    # exit code is classified as the engine's own result (#15).
    assert result.launch_failure is None
