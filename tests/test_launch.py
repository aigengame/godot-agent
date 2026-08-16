"""The headless-launch primitive maps subprocess failures to a RunResult (#185).

``launch`` is the single home of the spawn / timeout / ``OSError`` / UTF-8-decode
handling that both Phase-1 channels (the sentinel op runner and the native-export
runner) delegate to. A hung or missing engine must not surface as a raw Python
traceback; it is turned into a synthesized non-zero-exit :class:`RunResult` with a
typed ``launch_failure`` and a diagnostic on stderr — the launch-handling contract
that used to be written (and tested) twice, now exercised once here. The
channel-specific argv tail / export-only cwd stay tested in each runner's own
suite.
"""

import subprocess
from pathlib import Path

from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT
from gda.runner import LaunchFailure, launch


def test_missing_binary_maps_to_not_found_not_traceback():
    result = launch(Path("/nonexistent/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert result.exit_code == EXIT_NOT_FOUND
    assert "/nonexistent/Godot" in result.stderr
    assert result.stdout == ""
    # The primitive flags this as a synthesized launch failure so the classifier
    # keys environment on the typed reason, not the overloaded exit code (#15).
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_directory_binary_maps_to_not_found_not_traceback(tmp_path):
    # A directory passed as --godot (e.g. the bundle "Godot.app", a natural
    # $GDA_GODOT mistake) cannot be exec'd; the OS raises a PermissionError /
    # IsADirectoryError that must not escape as a raw traceback (#33).
    result = launch(tmp_path, ["--version"], cwd=None, timeout=60.0)

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(tmp_path) in result.stderr
    assert result.stdout == ""
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_non_executable_file_binary_maps_to_not_found_not_traceback(tmp_path):
    # A plain, non-executable file passed as --godot cannot be exec'd; the OS
    # raises a PermissionError that the primitive must catch and synthesize as a
    # launch failure rather than leak as a traceback (#33).
    not_exec = tmp_path / "notgodot.txt"
    not_exec.write_text("i am not an engine")

    result = launch(not_exec, ["--version"], cwd=None, timeout=60.0)

    assert result.exit_code == EXIT_NOT_FOUND
    assert str(not_exec) in result.stderr
    assert result.stdout == ""
    assert result.launch_failure is LaunchFailure.NOT_FOUND


def test_timeout_maps_to_synthesized_timeout_result(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = launch(Path("/any/Godot"), ["--version"], cwd=None, timeout=0.01)

    assert result.exit_code == EXIT_TIMEOUT
    # Default label is "Godot": the sentinel channel keeps its exact pre-#185
    # timeout diagnostic wording.
    assert result.stderr == "gda: Godot timed out after 0.01s\n"
    assert result.launch_failure is LaunchFailure.TIMEOUT


def test_timeout_label_customizes_the_diagnostic(monkeypatch):
    # The export channel passes a distinct label so its timeout diagnostic stays
    # byte-compatible with the pre-#185 "Godot export timed out" wording — the
    # stderr the classifier carries into the public GdaError.diagnostics (#185).
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = launch(
        Path("/any/Godot"),
        ["--export-release", "Web", "out"],
        cwd=None,
        timeout=600.0,
        timeout_label="Godot export",
    )

    assert result.exit_code == EXIT_TIMEOUT
    assert result.stderr == "gda: Godot export timed out after 600.0s\n"
    assert result.launch_failure is LaunchFailure.TIMEOUT


def test_timeout_is_passed_through_to_subprocess(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")

        class _Proc:
            # The primitive captures bytes (no text=True) and decodes UTF-8
            # itself, so the double mirrors that real subprocess contract (#33).
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = launch(Path("/any/Godot"), ["--version"], cwd=None, timeout=42.0)

    assert captured["timeout"] == 42.0
    # An engine that actually returned has no synthesized launch failure, so its
    # exit code is classified as the engine's own result (#15).
    assert result.launch_failure is None


def test_builds_headless_argv_from_binary_and_tail(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Proc:
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    launch(Path("/x/Godot"), ["--path", "/p", "--version"], cwd=None, timeout=60.0)

    # The primitive always prepends `[binary, --headless, --log-file <gda path>]`
    # to the caller's tail: gda owns the engine log target on every launch (#653).
    assert captured["cmd"][:3] == ["/x/Godot", "--headless", "--log-file"]
    assert captured["cmd"][4:] == ["--path", "/p", "--version"]


def test_engine_output_is_decoded_as_utf8_regardless_of_host_locale(monkeypatch):
    # Godot's JSON.stringify emits raw UTF-8, but subprocess(text=True) would
    # decode with the host locale. On a non-UTF-8 locale a non-ASCII node name
    # mojibakes or raises UnicodeDecodeError. The primitive must capture bytes and
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

    result = launch(Path("/any/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert "日本語" in result.stdout
    assert "警告: ノード名" in result.stderr


def test_cwd_is_passed_through_to_subprocess_as_a_string(monkeypatch, tmp_path):
    # The export channel relies on cwd to resolve a relative output path; the
    # primitive must forward it (as a string, the historical spawn shape).
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cwd"] = kwargs.get("cwd")

        class _Proc:
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    launch(Path("/x/Godot"), ["--version"], cwd=tmp_path, timeout=60.0)

    assert captured["cwd"] == str(tmp_path)


def test_cwd_none_passes_no_working_directory(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cwd"] = kwargs.get("cwd")

        class _Proc:
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert captured["cwd"] is None
