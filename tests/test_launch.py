"""The headless-launch primitive maps subprocess failures to a RunResult (#185).

``launch`` is the single home of the spawn / timeout / ``OSError`` / UTF-8-decode
handling that every Phase-1 channel (the sentinel op runner, the native-export
runner, the ``resource import`` pass, ``script run`` and ``scene preflight``)
delegates to. A hung or missing engine must not surface as a raw Python traceback;
it is turned into a synthesized non-zero-exit :class:`RunResult` with a typed
``launch_failure`` — the launch-handling contract that used to be written (and
tested) twice, now exercised once here. The channel-specific argv tail /
export-only cwd stay tested in each runner's own suite.

Since #714 there is ONE capture strategy: every launch streams. These tests drive
REAL child processes — a small stand-in script in place of the engine — rather
than a fake ``Popen``, because what the capture is about is what real pipes and a
real process lifetime do. (``tests.support.RecordingSpawn`` exists for the suites
whose subject is the SPAWN SHAPE rather than the capture.)
"""

import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gda import runner
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT
from gda.runner import LaunchFailure, TimeoutBound, launch


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


# The stand-in engines every test below drives. A REAL child process, not a fake
# ``Popen``: what the capture is about is what real pipes and a real process
# lifetime do, so faking the spawn would only assert the fake. Both ignore the
# ``--headless --log-file <path>`` head that ``launch`` injects, exactly as they
# ignore every other argv tail.


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


def _fast_fake_engine(
    tmp_path: Path, stdout_line: str, stderr_line: str, marker: Path | None = None
) -> Path:
    """A ``/bin/sh`` stand-in, kept for WALL-CLOCK SPEED, not correctness (#728).

    Diverges from ``_fake_engine`` on purpose: that one pays a fresh Python
    interpreter's startup before it writes a byte, which every test that races a
    REAL deadline against the child's first output would then be racing too —
    flaky on a loaded machine, at a ceiling short enough to keep the suite fast.
    A cheap shell writes in milliseconds, so those tests get a wide margin without
    a long ceiling. (``test_streaming_timeout_preserves_the_output_the_child_already_wrote``
    additionally controls the runner's clock, and keeps this stand-in because it
    still waits in real time for the child to write before letting the fake
    deadline cross.)

    ``printf '%s\\n'``, not ``echo``: XSI ``echo`` interprets backslash
    escapes in its operand on this platform's ``/bin/sh``, so a payload
    containing ``\\n`` or similar would print something other than what was
    passed in. ``printf`` with a literal ``'%s\\n'`` format leaves the
    (``shlex.quote``-escaped, so shell-syntax-safe) argument untouched.

    ``marker``, when given, is a file the stand-in creates AFTER both lines are
    written — the observation channel a test without a watch needs to hold the
    runner's clock until the output is guaranteed to be in the pipe (#824, see
    ``_clock_held_until_written``).

    It always ``sleep``s afterward, past any timeout this suite uses, via
    ``exec`` — not a trailing background job. Without ``exec`` SIGTERM only
    ends the shell; the orphaned ``sleep`` keeps the captured pipe open and
    the reader-thread join in ``launch``'s teardown runs to its own timeout
    on every single launch (#728).
    """
    script = tmp_path / "fast-fake-engine"
    out = shlex.quote(stdout_line)
    err = shlex.quote(stderr_line)
    touch = f": > {shlex.quote(str(marker))}\n" if marker is not None else ""
    script.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {out}\nprintf '%s\\n' {err} 1>&2\n{touch}exec sleep 30\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _clock_held_until_written(
    monkeypatch, marker: Path, *, settle_polls: int = 5, then: float = 1.5
) -> None:
    """Make the runner's poll loop see NO time pass until ``marker`` exists (#824).

    The #728 technique for a launch that has no watch to observe the capture
    through: the stand-in touches ``marker`` after its two ``printf``s, and the
    clock the runner reads reports 0.0 until the marker exists AND it has been
    read ``settle_polls`` more times — one read per poll for a watchless launch
    (a watch's abort deliberation adds a second read), so this is proof that
    the run kept polling past its output rather than ending on it — then jumps
    to ``then``, past the ceiling its callers use, so the deadline "elapses"
    only once the output is guaranteed to be in the pipe. Racing a REAL 1.0s
    ceiling against the child's first write failed under xdist contention (10
    of 12 runs with the timing modules concentrated on four workers). A
    real-time safety ceiling turns a loop that never ends into a loud
    assertion, not a hung suite. The loop's real cadence is untouched: it
    comes from ``proc.wait(timeout=...)`` on the subprocess module's own
    clock, which this binding does not reach; ``sleep`` is kept real only so
    the stand-in module stays faithful.
    """
    real_monotonic = time.monotonic
    real_deadline = real_monotonic() + 15.0
    polls_after_written = 0

    def fake_monotonic() -> float:
        nonlocal polls_after_written
        if real_monotonic() > real_deadline:
            raise AssertionError(
                "safety ceiling: launch did not finish within 15s "
                f"(marker exists: {marker.exists()})"
            )
        if not marker.exists():
            return 0.0
        polls_after_written += 1
        return then if polls_after_written > settle_polls else 0.0

    monkeypatch.setattr(
        runner,
        "time",
        SimpleNamespace(monotonic=fake_monotonic, sleep=time.sleep),
    )


def test_timeout_synthesizes_a_result_that_keeps_what_the_run_produced(
    monkeypatch, tmp_path
):
    # The bound gda puts on a hung engine, and the evidence it comes back with. The
    # run below writes to both streams and then never returns; `launch` ends it at
    # the ceiling and reports what it had already read — the whole of #714, which
    # replaced a capture that discarded exactly this. The ceiling elapses on the
    # held clock only after the child has written (#824): the real 1.0s used to
    # race the child's first line under load.
    marker = tmp_path / "written"
    engine = _fast_fake_engine(tmp_path, "BOOTED", "wedged", marker=marker)
    _clock_held_until_written(monkeypatch, marker)

    result = launch(engine, ["--version"], cwd=None, timeout=1.0)

    assert result.exit_code == EXIT_TIMEOUT
    assert result.launch_failure is LaunchFailure.TIMEOUT
    assert result.stdout == "BOOTED\n"
    assert result.stderr == "wedged\n"
    # No gda prose in either stream: the classifier composes the sentence from the
    # bound below, so mixing one in would corrupt the evidence.
    assert "timed out" not in result.stderr
    # The caller's own ceiling is what ended it, and the clock the loop read says
    # so (the real wall clock is pinned by test_streaming_measures_the_elapsed_wall_clock).
    assert result.elapsed_seconds is not None
    assert 1.0 <= result.elapsed_seconds < 3.0
    # Default label: the sentinel channel's launch is just "Godot".
    assert result.timeout_bound == TimeoutBound("Godot", 1.0)


def test_the_timeout_bound_carries_the_channels_own_label(tmp_path):
    # The export channel passes a distinct label, and the import pass another. The
    # label rides the result rather than a synthesized stderr (#714), because the
    # shared classifier is the only place that renders it and the runner seam hands
    # that classifier a RunResult and nothing else.
    engine = _fast_fake_engine(tmp_path, "packing", "")

    result = launch(
        engine,
        ["--export-release", "Web", "out"],
        cwd=None,
        timeout=1.0,
        timeout_label="Godot export",
    )

    assert result.launch_failure is LaunchFailure.TIMEOUT
    assert result.timeout_bound == TimeoutBound("Godot export", 1.0)


def test_builds_headless_argv_from_binary_and_tail(tmp_path):
    # The stand-in echoes the argv it was handed, so the assertion is on the argv
    # the OS really received rather than on a recorded call.
    engine = _fake_engine(tmp_path, "print('\\x00'.join(sys.argv[1:]))\n")

    result = launch(engine, ["--path", "/p", "--version"], cwd=None, timeout=30.0)

    argv = result.stdout.rstrip("\n").split("\x00")
    # The primitive always prepends `[--headless, --log-file <gda path>]` to the
    # caller's tail: gda owns the engine log target on every launch (#653).
    assert argv[:2] == ["--headless", "--log-file"]
    assert argv[3:] == ["--path", "/p", "--version"]


def test_engine_output_is_decoded_as_utf8_regardless_of_host_locale(tmp_path):
    # Godot's JSON.stringify emits raw UTF-8, but decoding with the host locale
    # would mojibake or raise UnicodeDecodeError on a non-UTF-8 locale for a
    # non-ASCII node name or echoed path. The primitive captures BYTES and decodes
    # UTF-8 explicitly, so user content round-trips (#33). The stand-in writes
    # through the raw buffers so the bytes on the wire are the ones under test.
    engine = _fake_engine(
        tmp_path,
        "sys.stdout.buffer.write("
        '\'<<<GDA:RESULT>>>{"name":"\\u65e5\\u672c\\u8a9e"}<<<GDA:END>>>\''
        ".encode('utf-8'))\n"
        "sys.stderr.buffer.write("
        "'\\u8b66\\u544a: \\u30ce\\u30fc\\u30c9\\u540d\\n'.encode('utf-8'))\n",
    )

    result = launch(engine, ["--version"], cwd=None, timeout=30.0)

    assert "日本語" in result.stdout
    assert "警告: ノード名" in result.stderr


def test_cwd_is_passed_through_to_the_child(tmp_path):
    # The export channel relies on cwd to resolve a relative output path, so the
    # primitive must forward it — and the child must really start there.
    workdir = tmp_path / "work"
    workdir.mkdir()
    engine = _fake_engine(tmp_path, "import os\nprint(os.getcwd())\n")

    result = launch(engine, ["--version"], cwd=workdir, timeout=30.0)

    assert Path(result.stdout.strip()).resolve() == workdir.resolve()


def test_cwd_none_leaves_the_child_in_gdas_own_directory(tmp_path):
    # Projectless launches pass no working directory, so the child simply inherits
    # gda's — never a directory the primitive invented.
    engine = _fake_engine(tmp_path, "import os\nprint(os.getcwd())\n")

    result = launch(engine, ["--version"], cwd=None, timeout=30.0)

    assert Path(result.stdout.strip()).resolve() == Path.cwd().resolve()


# --- What a POLICY ``watch`` adds on top of the capture every launch gets (#655):
# it can end a run BEFORE the timeout, and it is fed the output as it arrives. The
# capture and the clock themselves are asserted above, on the no-watch launches
# every other channel makes.
#
# The stand-in engine ignores the ``--headless --log-file <path>`` head that
# ``launch`` injects, exactly as it ignores every other argv tail.


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


def test_streaming_timeout_preserves_the_output_the_child_already_wrote(
    monkeypatch, tmp_path
):
    # THE #655 DEFECT: a buffered capture discards everything on a timeout, so a
    # script error Godot had ALREADY printed was lost (GDA-DF-012). With a watch the
    # capture survives, on BOTH streams, and no gda prose is mixed into either — the
    # watching channel composes its own diagnostics from this.
    #
    # THE #728 FIX: proving that needs the child to have ALREADY written before the
    # deadline. An earlier version of this test raced a real 3.0s deadline against
    # the real child's startup, narrowed only by a cheap shell engine (see
    # ``_fast_fake_engine``) — a residual race, later removed outright by
    # controlling the CLOCK the runner's poll loop reads instead of the runner's
    # behaviour: ``gda.runner`` does a plain ``import time``, so replacing that
    # module binding with a runner-local proxy redirects its ``monotonic`` lookup
    # without mutating the process-global stdlib module. The proxy delegates
    # ``sleep`` to the real function, so only the poll loop's idea of "how much
    # time has passed" is fake.
    #
    # The fake reports elapsed 0.0 until the watch's accumulated capture actually
    # contains both lines the assertions below check, then jumps past any timeout
    # in one step — so the loop keeps making REAL polls, on a REAL process, in REAL
    # wall-clock time, until the REAL output arrives, and only then does the
    # deadline "elapse". A real-clock safety ceiling (independent of the fake)
    # fails the test loudly, with whatever was captured so far, if that output
    # never arrives at all — a hang becomes an assertion, not a stuck suite.
    #
    # ``timeout`` below is consequently INERT: the loop only ever observes elapsed
    # 0.0 or the fake's post-observation jump, so any positive value under that
    # jump behaves identically. It is kept small (1.0) to say so — the 1.5s/3.0s
    # cold-start margin math it used to carry (measured outliers of 312ms/1110ms
    # against a real deadline) no longer applies now that nothing races it, and is
    # deleted rather than kept as unused history.
    engine = _fast_fake_engine(tmp_path, "SUITE START", "boom")
    watch = _RecordingWatch()

    # Captured BEFORE replacing the runner's module binding. The stdlib module
    # itself stays untouched, and the fake uses the saved function for its
    # independent real-time safety ceiling.
    real_monotonic = time.monotonic
    real_deadline = real_monotonic() + 15.0  # generous real-time safety ceiling

    def fake_monotonic() -> float:
        now = real_monotonic()
        if now > real_deadline:
            raise AssertionError(
                "safety ceiling: the child's output never arrived "
                f"(stdout={watch.stdout!r} stderr={watch.stderr!r})"
            )
        both_lines_seen = "SUITE START" in watch.stdout and "boom" in watch.stderr
        return 100.0 if both_lines_seen else 0.0

    monkeypatch.setattr(
        runner,
        "time",
        SimpleNamespace(monotonic=fake_monotonic, sleep=time.sleep),
    )
    assert runner.time is not time
    assert time.monotonic is real_monotonic

    result = launch(engine, [], cwd=None, timeout=1.0, watch=watch, timeout_label="X")

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


def test_a_watchless_launch_streams_and_never_ends_a_run_early(monkeypatch, tmp_path):
    # The pairing that makes ``watch`` POLICY rather than strategy (#714): a launch
    # WITHOUT one still captures and still times itself, and the only thing it gives
    # up is the early abort. Both halves are asserted against the same engine, so a
    # regression that made the no-watch path buffered again — or one that let it end
    # a run on its own — fails here. The clock is held until the child has written
    # (#824), so neither half races the child's first line.
    marker = tmp_path / "written"
    engine = _fast_fake_engine(
        tmp_path, "written and kept", "and this too", marker=marker
    )
    _clock_held_until_written(monkeypatch, marker)

    result = launch(engine, [], cwd=None, timeout=1.0, timeout_label="Godot export")

    assert result.launch_failure is LaunchFailure.TIMEOUT
    assert result.stdout == "written and kept\n"
    assert result.stderr == "and this too\n"
    assert result.timeout_bound == TimeoutBound("Godot export", 1.0)
    # It waited out the ceiling rather than ending early on the output it saw: the
    # held clock reaches 1.0 only after the loop polled past the written output,
    # so a run that ended on that output would report an elapsed of 0.0.
    assert result.elapsed_seconds is not None
    assert result.elapsed_seconds >= 1.0


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
