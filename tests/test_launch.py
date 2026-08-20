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
import sys
from pathlib import Path

import pytest

from gda import runner
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


# --- The STREAMING capture path (#655). Selected by passing a ``watch``; without one
# the BUFFERED behaviour asserted above is unchanged, which the
# ``test_the_buffered_path_still_*`` guard below pins for the sentinel and export
# channels that rely on it.
#
# These drive a REAL child process — a small shebang script standing in for the
# engine — rather than a fake ``Popen``. The whole point of the streaming path is
# what real pipes and a real process lifetime do (a buffered capture threw away the
# output that a real Godot had already written), so faking the spawn would only
# assert the fake. The stand-in ignores the ``--headless --log-file <path>`` head
# that ``launch`` injects, exactly as it ignores every other argv tail.


def _fake_engine(tmp_path: Path, body: str) -> Path:
    """An executable stand-in for the Godot binary that runs ``body``.

    ``sys.executable`` cannot be used directly: ``launch`` builds
    ``[binary, --headless, --log-file <path>, *args]`` and Python rejects
    ``--headless``. A shebang script takes the same argv and ignores it.
    """
    script = tmp_path / "fake-engine"
    script.write_text(
        f"#!{sys.executable}\nimport sys, time\n{body}\n", encoding="utf-8"
    )
    script.chmod(0o755)
    return script


class _RecordingWatch:
    """A ``LaunchWatch`` that records what it was fed and can ask for an abort.

    ``abort_when`` is called with the accumulated stderr, so a test states its
    trigger as a plain predicate instead of reimplementing the real watch's rule
    (which is tested against the real parser in the script-run suite).
    """

    def __init__(self, abort_when=None) -> None:
        self.abort_when = abort_when
        self.stdout = ""
        self.stderr = ""
        self.polls = 0
        self.max_elapsed = 0.0

    def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
        self.polls += 1
        self.stdout += stdout
        self.stderr += stderr
        self.max_elapsed = max(self.max_elapsed, elapsed)
        return bool(self.abort_when and self.abort_when(self.stderr))


def test_streaming_timeout_preserves_the_output_the_child_already_wrote(tmp_path):
    # THE #655 DEFECT: a buffered capture discards everything on a timeout, so a
    # script error Godot had ALREADY printed was lost (GDA-DF-012). With a watch the
    # capture survives, on BOTH streams, and no gda prose is mixed into either — the
    # watching channel composes its own diagnostics from this.
    engine = _fake_engine(
        tmp_path,
        "print('SUITE START', flush=True)\n"
        "print('boom', file=sys.stderr, flush=True)\n"
        "time.sleep(30)\n",
    )

    result = launch(
        engine, [], cwd=None, timeout=1.5, watch=_RecordingWatch(), timeout_label="X"
    )

    assert result.launch_failure is LaunchFailure.TIMEOUT
    assert result.exit_code == EXIT_TIMEOUT
    assert result.stdout == "SUITE START\n"
    assert result.stderr == "boom\n"
    assert "timed out" not in result.stderr


def test_streaming_measures_the_elapsed_wall_clock(tmp_path):
    # The other half of GDA-DF-032: a healthy suite that outgrew its ceiling was
    # indistinguishable from a hang because nothing reported how long it ran. The
    # clock stops when gda decides to end the run, NOT after the SIGTERM grace and
    # the reader join — those are gda's own shutdown, and charging them to the run
    # would report a 1.0s ceiling as several seconds.
    engine = _fake_engine(tmp_path, "time.sleep(30)")

    result = launch(engine, [], cwd=None, timeout=1.0, watch=_RecordingWatch())

    assert result.elapsed_seconds is not None
    assert 1.0 <= result.elapsed_seconds < 2.0


def test_streaming_lets_the_watch_end_the_run_before_the_timeout(tmp_path):
    # The early-abort mechanism: the watch sees the error as it arrives and asks for
    # the run to end, so the failure is reported in a fraction of the ceiling rather
    # than at it. The captured output still comes back — the abort exists to RETURN
    # the evidence, not merely to stop waiting.
    engine = _fake_engine(
        tmp_path,
        "print('working', flush=True)\n"
        "print('SCRIPT ERROR: boom', file=sys.stderr, flush=True)\n"
        "time.sleep(60)\n",
    )
    watch = _RecordingWatch(abort_when=lambda stderr: "SCRIPT ERROR" in stderr)

    result = launch(engine, [], cwd=None, timeout=60.0, watch=watch)

    assert result.launch_failure is LaunchFailure.ABORTED
    # A NON-NEGATIVE exit code, deliberately: gda caused the signal death, and a
    # negative exit_code is how a genuine engine crash is recognized.
    assert result.exit_code >= 0
    assert result.stdout == "working\n"
    assert "SCRIPT ERROR: boom" in result.stderr
    assert result.elapsed_seconds is not None and result.elapsed_seconds < 10.0


def test_a_natural_exit_during_the_watchs_deliberation_keeps_its_exit_status(
    tmp_path, monkeypatch
):
    # THE #709 REVIEW'S RACE: the watch asks to end the run, but the child already
    # exited on its own while ``observe()`` deliberated. Reporting that as ABORTED
    # synthesized exit_code 0 over the real status — for ``script run``, discarding
    # the status the script's own ``quit()`` chose. A run gda did not end must come
    # back as the natural exit it was.
    # A file handshake makes the interleaving exact: the child stays alive until
    # the watch has SEEN the trigger (so the poll loop is still live and observe
    # is the one deciding), then exits with its own status while the watch is
    # still deliberating. Without it the child's exit wins the poll race and the
    # loop ends naturally before observe ever sees the line.
    release = tmp_path / "release"
    engine = _fake_engine(
        tmp_path,
        "import os\n"
        "print('SCRIPT ERROR: boom', file=sys.stderr, flush=True)\n"
        f"while not os.path.exists({str(release)!r}):\n"
        "    time.sleep(0.01)\n"
        "sys.exit(7)\n",
    )
    spawned = _capture_popen(monkeypatch)

    class _DeliberatingWatch:
        stderr_seen = ""

        def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
            self.stderr_seen += stderr
            if "SCRIPT ERROR" not in self.stderr_seen:
                return False
            # Let the child go, and only answer once it is PROVEN gone — the
            # exit lands inside this very deliberation, deterministically.
            release.write_text("go", encoding="utf-8")
            spawned[0].wait(timeout=10)
            return True

    result = launch(engine, [], cwd=None, timeout=30.0, watch=_DeliberatingWatch())

    assert result.launch_failure is None
    assert result.exit_code == 7
    assert "SCRIPT ERROR: boom" in result.stderr


def test_streaming_passes_a_completed_run_through_with_its_own_exit_code(tmp_path):
    # A child that finishes inside the ceiling is NOT a launch failure: the engine's
    # own exit code is the result, launch_failure stays None, and the clock is still
    # measured. The streaming path must not turn a completed run into a synthesized one.
    engine = _fake_engine(
        tmp_path,
        "print('done', flush=True)\nprint('warn', file=sys.stderr, flush=True)\n"
        "sys.exit(3)\n",
    )

    result = launch(engine, [], cwd=None, timeout=30.0, watch=_RecordingWatch())

    assert result.launch_failure is None
    assert result.exit_code == 3
    assert result.stdout == "done\n"
    assert result.stderr == "warn\n"
    assert result.elapsed_seconds is not None


def test_streaming_feeds_the_watch_each_byte_exactly_once(tmp_path):
    # The seam's contract: ``observe`` receives the NEWLY-arrived text, never the
    # accumulated capture, so an implementation cannot become quadratic in the output
    # size. Reassembling the increments must therefore reproduce the capture — as a
    # PREFIX of it, not all of it: the watch is polled only while the run is alive,
    # so whatever the child writes in its final moments arrives after the loop has
    # ended. That is harmless by construction (there is no longer a run to abort) and
    # it is why the final capture, not the watch's view, is what the result carries.
    engine = _fake_engine(
        tmp_path,
        "for i in range(20):\n"
        "    print(f'line {i}', flush=True)\n"
        "    time.sleep(0.05)\n",
    )
    watch = _RecordingWatch()

    result = launch(engine, [], cwd=None, timeout=30.0, watch=watch)

    assert result.stdout.count("line ") == 20
    assert result.stdout.startswith(watch.stdout)
    # Genuinely incremental, not one dump at the end: several lines reached the watch
    # while the child was still running.
    assert watch.stdout.count("line ") >= 2
    # And the watch is polled repeatedly, including on polls with no new output —
    # that is what lets a silence-based policy fire at all.
    assert watch.polls >= 2


def test_streaming_decodes_utf8_split_across_a_read_boundary(tmp_path):
    # The incremental decode is not a detail: a chunk boundary can fall inside a
    # multi-byte sequence, and decoding each chunk independently would turn one
    # character into two replacement characters. Writing the two halves of a 3-byte
    # character with a pause between them forces that boundary.
    engine = _fake_engine(
        tmp_path,
        "sys.stdout.buffer.write('你'.encode()[:1])\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(0.3)\n"
        "sys.stdout.buffer.write('你'.encode()[1:])\n"
        "sys.stdout.buffer.flush()\n",
    )

    result = launch(engine, [], cwd=None, timeout=30.0, watch=_RecordingWatch())

    assert result.stdout == "你"


def test_streaming_captures_more_than_one_pipe_buffer_without_deadlocking(tmp_path):
    # Why the reads happen on threads rather than in the polling loop: a child that
    # writes more than the OS pipe buffer holds (64 KiB on Linux) blocks until
    # someone drains it, and a loop that only watches the deadline never would. The
    # run below would hang forever on a single-threaded capture.
    engine = _fake_engine(
        tmp_path,
        "sys.stdout.write('o' * 300_000)\n"
        "sys.stderr.write('e' * 300_000)\n"
        "sys.stdout.flush()\nsys.stderr.flush()\n",
    )

    result = launch(engine, [], cwd=None, timeout=30.0, watch=_RecordingWatch())

    assert result.exit_code == 0
    assert len(result.stdout) == 300_000
    assert len(result.stderr) == 300_000


def test_streaming_maps_a_missing_binary_to_the_same_not_found_result():
    # The two capture strategies share ONE failure mapping: an unlaunchable binary is
    # the identical synthesized result whichever way gda meant to read the output.
    buffered = launch(Path("/nonexistent/Godot"), [], cwd=None, timeout=1.0)
    streamed = launch(
        Path("/nonexistent/Godot"), [], cwd=None, timeout=1.0, watch=_RecordingWatch()
    )

    assert streamed.launch_failure is buffered.launch_failure is LaunchFailure.NOT_FOUND
    assert streamed.exit_code == buffered.exit_code == EXIT_NOT_FOUND
    assert streamed.stderr == buffered.stderr


def test_the_buffered_path_still_discards_output_and_keeps_its_diagnostic(tmp_path):
    # The byte-identity guard for the sentinel and export channels (#655): they pass
    # NO watch, so their timeout result must stay exactly what it was — the output
    # discarded and the ``gda: <label> timed out after <n>s`` diagnostic standing in
    # for it, which is published prose in their error envelopes. Moving them onto the
    # preserving path is named follow-up work, not this change.
    engine = _fake_engine(
        tmp_path, "print('written but discarded', flush=True)\ntime.sleep(30)\n"
    )

    result = launch(engine, [], cwd=None, timeout=1.0, timeout_label="Godot export")

    assert result.launch_failure is LaunchFailure.TIMEOUT
    assert result.stdout == ""
    assert result.stderr == "gda: Godot export timed out after 1.0s\n"
    # And it does not time itself — the clock is the streaming path's addition.
    assert result.elapsed_seconds is None


def _capture_popen(monkeypatch) -> list:
    """Record every child the streaming path spawns, so a test can prove it was reaped.

    ``launch`` deliberately does not expose the process — a ``Raw run`` is the whole
    outcome — so the assertion needs the ``Popen`` itself. Wrapping the real spawn is
    honest about what is being asserted: the CHILD's fate, not a stand-in's.
    """
    spawned: list = []
    real = subprocess.Popen

    def recording(*args, **kwargs):
        proc = real(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", recording)
    return spawned


@pytest.mark.parametrize("interruption", [RuntimeError, KeyboardInterrupt])
def test_streaming_reaps_the_child_when_the_poll_loop_is_interrupted(
    tmp_path, monkeypatch, interruption
):
    # A streaming launch must never OUTLIVE its gda process. The buffered strategy
    # gets this free — ``subprocess.run`` kills the child when an exception leaves its
    # ``with`` block — so the streaming path owes the same guarantee, and it is not
    # cosmetic: the runs this path exists for are precisely the ones that do not stop
    # on their own, so an orphan idles forever and repeated interruptions accumulate
    # engines contending over ``user://``.
    #
    # Both interruption classes are covered on purpose. ``RuntimeError`` stands for
    # anything a caller's watch raises; ``KeyboardInterrupt`` is a BaseException, so it
    # would slip past an ``except Exception`` and is the case a Ctrl-C actually takes
    # when gda sits in its own process group and the signal never reaches the engine.
    engine = _fake_engine(tmp_path, "print('alive', flush=True)\ntime.sleep(120)\n")
    spawned = _capture_popen(monkeypatch)

    class _RaisingWatch:
        def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
            raise interruption("interrupted mid-run")

    with pytest.raises(interruption):
        launch(engine, [], cwd=None, timeout=120.0, watch=_RaisingWatch())

    assert len(spawned) == 1
    proc = spawned[0]
    reaped = proc.poll() is not None
    if not reaped:
        # Do not leak the very orphan this test exists to forbid.
        proc.kill()
        proc.wait()
    assert reaped, "the engine outlived the interrupted launch"


@pytest.mark.parametrize("fail_on", [1, 2])
def test_streaming_reaps_the_child_when_capture_setup_fails(
    tmp_path, monkeypatch, fail_on
):
    # The no-outliving guarantee has to cover SETUP, not just the loop. Each capture
    # starts a reader thread, so constructing them is fallible; done outside the
    # lifecycle boundary, a failure there left the child running with nothing left to
    # stop it — the same orphan, reached through setup instead of through the loop.
    #
    # Both positions are covered because they fail differently: the FIRST leaves
    # nothing to join, while the SECOND leaves a live reader thread on stdout that the
    # teardown must still drain before closing the pipes.
    engine = _fake_engine(tmp_path, "print('alive', flush=True)\ntime.sleep(120)\n")
    spawned = _capture_popen(monkeypatch)
    real_capture = runner._StreamCapture
    built = {"n": 0}

    def exploding(pipe):
        built["n"] += 1
        if built["n"] == fail_on:
            raise RuntimeError(f"capture setup failed on #{fail_on}")
        return real_capture(pipe)

    monkeypatch.setattr(runner, "_StreamCapture", exploding)

    with pytest.raises(RuntimeError, match="capture setup failed"):
        launch(engine, [], cwd=None, timeout=120.0, watch=_RecordingWatch())

    assert len(spawned) == 1
    proc = spawned[0]
    reaped = proc.poll() is not None
    if not reaped:
        proc.kill()
        proc.wait()
    assert reaped, f"the engine outlived a capture-setup failure on #{fail_on}"
