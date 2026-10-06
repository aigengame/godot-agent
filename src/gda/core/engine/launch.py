"""The Godot runner seam.

Given an operation name and JSON params, a runner spawns a one-shot
``godot --headless --script`` process and returns its raw
``{stdout, stderr, exit_code}``. The seam is a Protocol so that commands can be
exercised against a fake runner without touching a real engine (ADR-0001).
"""

import codecs
import enum
import os
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Optional, Protocol

# The codes the runner synthesizes when it never got a result from the engine.
# Defined once in gda.exit_codes (the full exit-code ABI); imported here because
# the runner is what produces them (issue #3).
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT
from gda.core.engine.user_data import (
    UserDataPlacement,
    UserDataReport,
    UserDataUnwritable,
    _user_data_unwritable_stderr,
    resolve_user_data_root,
    user_data_placement,
)

# A headless one-shot operation should be quick; this bounds a hung engine so
# the CLI fails loudly instead of blocking forever.
DEFAULT_TIMEOUT_SECONDS = 60.0

# How a timeout NAMES the launch it ended. Each channel passes its own
# (``"Godot export"``, ``"Godot import"``, …); the sentinel channel keeps the bare
# engine name it has always reported. It rides the result as part of
# :class:`TimeoutBound` and is rendered by the shared ``launch_timeout``
# classifier, so a caller still learns WHICH launch gave up (#185, #714).
DEFAULT_TIMEOUT_LABEL = "Godot"


class LaunchFailure(enum.Enum):
    """Why the runner never obtained a result from the engine (issue #15).

    Set *only* by the runner when it synthesizes a result without the engine
    returning one, so classification keys environment failures on this typed
    reason rather than on shell-convention exit codes that a real engine or
    wrapper can itself genuinely return.
    """

    NOT_FOUND = "not_found"  # the binary could not be launched
    TIMEOUT = "timeout"  # launched, but did not return before the runner timeout
    # The engine log target gda owns could not be created, so the launch was
    # REFUSED rather than attempted: Godot's file logger dereferences a null
    # ``FileAccess`` when it cannot open its log, dying with signal 11 before any
    # project code runs (issue #653).
    USER_DATA_UNWRITABLE = "user_data_unwritable"
    # gda ended the run EARLY, before the timeout, because the watching channel's
    # own :class:`LaunchWatch` asked it to (issue #655). Reachable only for a
    # caller that passes a POLICY ``watch``, which today is ``gda script run``
    # alone — and that channel classifies this value itself, because only it knows
    # what its watch condition means. ``classify_launch_or_crash`` therefore does
    # NOT map it: a shared classifier has no honest generic code for "the caller's
    # own declared condition fired". A future watching channel must classify it
    # too rather than fall through to that shared prefix.
    ABORTED = "aborted"


@dataclass(frozen=True)
class TimeoutBound:
    """The bound a synthesized ``TIMEOUT`` result was ended at (issue #714).

    Set by :func:`launch` and by nothing else, because the primitive is the only
    place that knows both halves — and it is the only thing that CROSSES the runner
    seam: ``GodotRunner.run`` hands a channel's classifier a
    :class:`RunResult` and nothing more, so a shared classifier cannot otherwise
    learn which launch gave up, or after how long. Carrying the pair here is what
    lets ONE ``launch_timeout`` branch report "Godot export … before the timeout of
    600.0s" without every ``classify_run`` call site plumbing it (#714).
    """

    #: How this launch is NAMED in the failure — see :data:`DEFAULT_TIMEOUT_LABEL`.
    label: str
    #: The ceiling, in seconds, that the launch reached.
    seconds: float


@dataclass
class RunResult:
    """The raw result of a one-shot headless Godot invocation."""

    stdout: str
    stderr: str
    exit_code: int
    # Set only when the runner synthesized this result (binary missing, timed
    # out, the placement was refused, or a watch ended the run) instead of the
    # engine returning one; ``None`` means the exit_code is the engine's own
    # (issue #15).
    launch_failure: "LaunchFailure | None" = None
    # The launch's wall clock, measured on every launch (issue #655; every channel
    # since #714). It is the datum that tells a merely-slow run from a hung one: a
    # timeout at 121s of a 120s ceiling is a suite that outgrew its budget, while
    # one that produced its last output at 2s is stuck. ``None`` only on a result
    # the primitive did not measure — a launch refused before the spawn, or a
    # hand-built result at a test seam.
    elapsed_seconds: float | None = None
    # The ceiling this run reached, set only on a synthesized ``TIMEOUT`` result
    # (issue #714) — see :class:`TimeoutBound`.
    timeout_bound: "TimeoutBound | None" = None
    # Where this launch put Godot's user data (issue #850) — see
    # :class:`~gda.core.engine.user_data.UserDataReport`. Set by :func:`launch` on
    # every result it returns from a prepared placement, whatever the outcome, so
    # that a channel CAN publish it wherever it decides to — not because every
    # outcome publishes it today. One
    # channel does: ``script run``, on its SUCCESS result (#850) and on three of its
    # failure envelopes — ``script_failed``, its own ``launch_timeout`` and
    # ``script_aborted`` — where the facts ride ADR-0004's `Failure evidence` (#862).
    # Those three codes and no others: this channel's remaining verdicts disclose
    # nothing, and neither does any other channel's result or envelope.
    # ``None`` on a launch REFUSED before a placement existed
    # (``USER_DATA_UNWRITABLE``, whose own diagnostics name what was attempted) and
    # on a hand-built result at a test seam.
    user_data: "UserDataReport | None" = None


class LaunchWatch(Protocol):
    """A channel's incremental POLICY over one launch (issue #655).

    Every launch streams — the child's stdout/stderr are read as they arrive, so
    whatever a run produced before gda ended it survives into the ``RunResult``,
    and the launch is timed (#714 moved the last three channels across; see
    :func:`launch`). A watch adds the one thing streaming alone cannot decide:
    **ending a run early**, before the timeout.

    The primitive owns the MECHANISM (spawn, read, decode, deadline, terminate)
    and the watch owns the POLICY (what the output means, and when a run is not
    worth waiting out). That split is why the policy is injected rather than
    written here: "a fatal script error appeared and the caller's declared
    completion marker did not" is ``script run``'s domain knowledge, not the
    channel-agnostic primitive's — and ADR-0031 rejected gda imposing any
    contract on a user-authored entry script, so only a caller can declare one.
    A channel with no such rule passes no watch and gets :class:`_CaptureOnly`.

    :meth:`observe` is polled on a fixed cadence for the whole run, **including
    polls where no output arrived** (both arguments empty), so a policy keyed on
    SILENCE can fire. ``elapsed`` is passed in rather than read from a clock
    inside the watch, which keeps an implementation a pure function of
    ``(text, elapsed)`` — deterministic on every platform, and testable without
    sleeping or spawning. The observed text and the clock are deliberately the
    watch's ONLY inputs: an earlier version also fed it the child's CPU time as
    evidence of idleness, and review falsified that in both directions (a run
    blocked in a wait consumes no CPU while alive, and a host where CPU time
    cannot be read loses the policy entirely), so no process-state probe belongs
    in this contract.
    """

    def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
        """Feed the text that arrived since the last poll; ``True`` ends the run.

        ``stdout``/``stderr`` are the NEWLY-decoded text only (each may be
        empty), never the accumulated capture, so an implementation is fed each
        byte exactly once and cannot become quadratic in the output size.
        ``elapsed`` is monotonic seconds since the spawn.
        """
        ...


class _CaptureOnly:
    """The watch of a channel that has no early-abort rule (issue #714).

    Streaming is the only capture strategy, so a channel no longer opts into it —
    it opts into a POLICY, and most channels have none. Observing without ever
    ending a run is the honest default: gda cannot tell from outside a process
    whether a quiet engine is stuck or working, and only a caller who declared what
    finishing looks like (``script run``'s ``--completion-marker``) can. So the
    ONLY bound for these channels is the caller's timeout, and what they get from
    the loop is the capture and the clock.
    """

    def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
        return False


# How often the launch loop polls its watch. It bounds the extra latency an early
# abort or a timeout can carry (a poll may wait through the moment the condition
# became true), so it is small — but not so small that a 120s run spends its time
# waking up: 0.05s is ~2400 polls over the default ``script run`` ceiling. It does
# NOT bound how quickly a finished run is noticed: the wait ends the instant the
# child exits (see :func:`_spawn_streamed`).
_POLL_INTERVAL_SECONDS = 0.05

# One read syscall's ceiling on the streaming path. The pipe is read with
# ``os.read`` on the raw descriptor, NOT ``BufferedReader.read``: the latter blocks
# until it has n bytes or EOF, which held a line-at-a-time engine's output back
# until the process died and defeated the streaming entirely (measured against
# Godot 4.6.3 while building this — the whole capture arrived at the kill).
_READ_CHUNK_BYTES = 65536

# How long a terminated child is given to exit on its own before it is killed.
# Godot handles SIGTERM as a quit request and exits cleanly, which FLUSHES its
# stdio — so asking first, rather than killing outright, recovers anything still
# sitting in the child's buffers. Streaming has already captured the rest, so this
# is a bonus rather than the mechanism (and Windows has no equivalent).
_TERMINATE_GRACE_SECONDS = 3.0

# How long the reader threads are given to finish after the child is gone. They
# end at EOF on their pipe, which the child's exit produces, so this only bounds a
# pathological case rather than being a normal wait.
_READER_JOIN_SECONDS = 5.0


class _StreamCapture:
    """One pipe, read on its own thread and decoded incrementally (issue #655).

    A thread per stream — rather than ``selectors`` — because the primitive must
    work on Windows, where a pipe is not selectable. The threads are also what
    keeps the child from deadlocking: an engine that writes more than the OS pipe
    buffer holds blocks until someone reads, and the polling loop cannot both wait
    on the deadline and drain two pipes.

    Decoding is INCREMENTAL (``codecs`` incremental decoder, ``errors="replace"``)
    for one reason: a chunk boundary can fall inside a multi-byte UTF-8 sequence,
    and decoding each chunk independently would turn a legitimate non-ASCII
    character into two replacement characters. Feeding one decoder across every
    chunk — and flushing it once at the end — yields exactly what decoding the
    whole buffer at once yields, so the text is identical to a whole-buffer decode
    of the same bytes.
    """

    def __init__(self, pipe: IO[bytes]) -> None:
        self._pipe = pipe
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._text: list[str] = []
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while True:
            try:
                chunk = os.read(self._pipe.fileno(), _READ_CHUNK_BYTES)
            except (ValueError, OSError):
                # The pipe was closed under us (an interpreter teardown race). The
                # thread's job is over; it must not raise into a daemon thread and
                # print a traceback over the CLI's own output.
                break
            if not chunk:
                break
            text = self._decoder.decode(chunk)
            if text:
                with self._lock:
                    self._pending.append(text)
                    self._text.append(text)

    def drain(self) -> str:
        """The text decoded since the previous drain, handed over exactly once."""
        with self._lock:
            new = "".join(self._pending)
            self._pending.clear()
        return new

    def finish(self) -> str:
        """Join the reader and return everything decoded, decoder flushed."""
        self._thread.join(_READER_JOIN_SECONDS)
        with self._lock:
            if not self._thread.is_alive():
                # Flush a trailing partial multi-byte sequence into its replacement
                # character, matching what a whole-buffer decode would produce. Only
                # safe once the pump can no longer touch the decoder.
                tail = self._decoder.decode(b"", final=True)
                if tail:
                    self._text.append(tail)
            return "".join(self._text)


def launch(
    binary: Path,
    args: list[str],
    *,
    cwd: Path | None,
    timeout: float,
    timeout_label: str = DEFAULT_TIMEOUT_LABEL,
    watch: Optional[LaunchWatch] = None,
    user_data_root: Path | None = None,
    ignore_cwd: bool = False,
) -> RunResult:
    """Spawn one ``godot --headless`` process and normalize its raw outcome.

    The single home of the headless-launch primitive: it builds
    ``[binary, --headless, *args]``, runs it with a timeout capturing raw
    *bytes*, and returns a normalized :class:`RunResult`. Every Phase-1 channel
    — the sentinel op-dispatch runner, the native-export runner, the
    ``resource import`` pass, ``script run`` and ``scene preflight`` — builds only
    its channel-specific argv tail (and the export-only ``cwd``) and delegates
    the spawn/timeout/``OSError``/decode handling here, so a launch-handling fix
    lands in one place rather than five copies (issue #185, ADR-0010).

    The mapping, identical for every channel:

    - the timeout reached → a synthesized ``EXIT_TIMEOUT`` result flagged
      ``LaunchFailure.TIMEOUT``: launched, but did not return before the
      timeout (a hung engine bounded so the CLI fails loudly, #15). Both streams
      hold **what the run had already produced**, verbatim, and no gda prose: the
      classifier composes the diagnostics from that capture, so mixing gda's own
      sentence into the child's stderr would corrupt the very evidence the
      streaming capture exists to preserve. What the run cannot say for itself —
      which launch this was, and the ceiling it reached — rides the result as
      :class:`TimeoutBound`, beside the measured ``elapsed_seconds`` (#714);
    - ``OSError`` → a synthesized ``EXIT_NOT_FOUND`` result flagged
      ``LaunchFailure.NOT_FOUND``: the configured binary could not be launched —
      ``FileNotFoundError`` (missing), ``PermissionError`` (a directory like
      ``Godot.app`` — a natural ``$GDA_GODOT`` mistake — or a non-executable
      file), and any other ``OSError`` from ``exec`` are the one environment
      failure of there being no engine to run (#33). The synthesized typed
      reason lets the classifier key environment on it, not on the overloaded
      exit code (#15). The OS message is kept as advisory stderr to disambiguate
      which mode occurred;
    - otherwise → the engine's own ``returncode`` with ``launch_failure=None``,
      and stdout/stderr decoded as UTF-8 with ``errors="replace"`` (see below).

    Every launch also carries gda's own ``--log-file`` (issue #653). The engine
    builds its file logger before any project code runs and dies with signal 11 if
    it cannot open the log, so gda owns that target: it is created (the preflight)
    and passed explicitly, which keeps a read-only application-data directory from
    being fatal and stops concurrent invocations sharing one rotated file. A target
    gda cannot create is refused HERE as ``LaunchFailure.USER_DATA_UNWRITABLE``
    rather than handed to the engine to crash on. ``--log-file`` precedes ``*args``
    because it is an engine option and the sentinel channel's tail ends in the
    ``--`` user-args separator.

    **One capture strategy (issue #714).** Every launch STREAMS: both pipes are
    read as they arrive and the run is timed. #655 introduced streaming beside a
    buffered ``subprocess.run`` capture that discarded the child's output at the
    timeout, keeping the sentinel and export channels on the buffered one so their
    published timeout envelopes stayed byte-identical while the mechanism was
    proven. #714 moved those channels — and the ``resource import`` pass, the third
    that shared the discard — across, which left the buffered strategy with no
    caller at all; a second capture path nothing selects is a trap for the next
    channel, not an option, so it is gone.

    ``watch`` is therefore POLICY, not strategy: a channel that can recognize a run
    not worth waiting out passes one and may end the launch early as
    ``LaunchFailure.ABORTED`` (``gda script run``, ADR-0031); a channel with no
    such rule passes nothing and gets :class:`_CaptureOnly`.

    ``user_data_root`` is the EXPLICIT placement input (ADR-0042). Omitted — every
    channel but one — the root is resolved process-wide exactly as before, from the
    ``--user-data-root`` flag and then ``$GDA_USER_DATA_ROOT``, so no existing
    caller changes. Given, it IS the root for this launch and the process-wide
    resolution is not consulted: ``gda export smoke`` runs a caller-selected
    exported game, so it hands the primitive a fresh private root of its own
    whenever the caller named none, and the game cannot write the real ``user://``.
    It is a root, not a placement: preparing one — creating and preflighting the
    log target and, under a root, the derived data path — stays here, so the two
    inputs cannot describe the placement differently. Lifetime stays with whoever
    supplied the root: this primitive removes only the private temporary log
    directory it makes for itself.

    ``ignore_cwd`` is for a run that must load no project (#1035), and only the
    sentinel runner sets it. The placement then also makes an empty directory
    beside the log, and the argv gets ``--path <that directory>`` before
    ``*args``, so the engine does not load a project from the invoker's working
    directory. The spawn's own ``cwd`` does not change, so a relative binary path
    still resolves against the invoker's directory. The directory is removed with
    the placement.
    """
    root: Path | None
    if user_data_root is None:
        try:
            root = resolve_user_data_root()
        except ValueError as exc:
            # An explicit but empty --user-data-root. There is no placement to
            # prepare, so it is the same unusable-placement outcome, reported before
            # any spawn (mirrors how an empty --godot becomes binary_not_found, #33)
            # — through the SHARED formatter, so the three-path diagnostic shape
            # holds with the unavailable fields rendered explicitly. Only the
            # process-wide resolution can produce it: an explicit root is a Path.
            refusal = UserDataUnwritable(
                str(exc),
                data_location="unresolved (--user-data-root is empty)",
                log_location="not attempted (no placement was prepared)",
            )
            return RunResult(
                stdout="",
                stderr=_user_data_unwritable_stderr(binary, None, refusal),
                exit_code=EXIT_NOT_FOUND,
                launch_failure=LaunchFailure.USER_DATA_UNWRITABLE,
            )
    else:
        root = user_data_root
    return _launch_under(
        binary,
        args,
        cwd=cwd,
        timeout=timeout,
        timeout_label=timeout_label,
        watch=watch,
        root=root,
        ignore_cwd=ignore_cwd,
    )


def _launch_under(
    binary: Path,
    args: list[str],
    *,
    cwd: Path | None,
    timeout: float,
    timeout_label: str,
    watch: Optional[LaunchWatch],
    root: Path | None,
    ignore_cwd: bool,
) -> RunResult:
    """Prepare ``root`` into a placement, spawn under it, and report it back.

    The half of :func:`launch` that runs once the root is settled, whichever of the
    two inputs settled it (ADR-0042): the process-wide resolution every existing
    channel uses, or the explicit one ``export smoke`` hands in. Separated only so
    that the two inputs share ONE preparation, spawn, refusal and report — a second
    copy is how the two would come to place a launch differently. ``ignore_cwd``
    asks the placement for the empty engine working directory (#1035).
    """
    try:
        with user_data_placement(root, empty_engine_dir=ignore_cwd) as placement:
            # Only the preparation above can raise UserDataUnwritable: the spawn
            # itself maps every OSError to the NOT_FOUND result below.
            result = _spawn_streamed(
                binary,
                args,
                cwd=cwd,
                timeout=timeout,
                timeout_label=timeout_label,
                placement=placement,
                watch=watch if watch is not None else _CaptureOnly(),
            )
            # Report the placement on the way out (#850). Done HERE rather than at
            # each of the spawn's exits because this is the one scope that knows
            # both halves — the root the launch resolved and the placement it
            # prepared from it — and because it applies to every outcome alike.
            return replace(
                result,
                user_data=UserDataReport(
                    root=placement.root,
                    data_path=placement.data_path,
                    # The log is a fact only under a root; otherwise it is the
                    # private temporary file this block is about to remove.
                    log_file=(
                        placement.log_file if placement.root is not None else None
                    ),
                ),
            )
    except UserDataUnwritable as exc:
        return RunResult(
            stdout="",
            stderr=_user_data_unwritable_stderr(binary, root, exc),
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.USER_DATA_UNWRITABLE,
        )


def _not_found_result(binary: Path, exc: OSError) -> RunResult:
    """The synthesized result of a binary that could not be launched at all.

    An ``OSError`` from ``exec`` is the one environment failure of there being no
    engine to run; it is reported before any capture exists, so it is the same
    result for every channel (#33).
    """
    return RunResult(
        stdout="",
        stderr=f"gda: Godot binary could not be launched: {binary} ({exc})\n",
        exit_code=EXIT_NOT_FOUND,
        launch_failure=LaunchFailure.NOT_FOUND,
    )


def _spawn_streamed(
    binary: Path,
    args: list[str],
    *,
    cwd: Path | None,
    timeout: float,
    timeout_label: str,
    placement: UserDataPlacement,
    watch: LaunchWatch,
) -> RunResult:
    """Run one prepared launch, reading both pipes as they arrive (#655, #714).

    Both pipes are drained on their own threads while this loop owns the deadline
    and the watch, so:

    - a timeout returns the output the child had ALREADY produced, verbatim,
      instead of discarding it. This is the whole point: a script error that
      aborted a run before its ``quit()`` had already been printed, and the
      buffered capture this replaced threw it away (GDA-DF-012);
    - the watch can end the run before the deadline, reported as
      ``LaunchFailure.ABORTED``;
    - the wall clock is measured either way, so a slow-but-live run is
      distinguishable from a stuck one (GDA-DF-032).

    A child still running at the end is asked to quit (SIGTERM) before it is
    killed, which lets Godot flush and exit cleanly. Its own exit code is then
    NOT the result's: gda ended this run, so the outcome is a synthesized
    launch failure, never the negative signal code — which would otherwise be
    classified as an ``engine_crashed`` the engine did not commit.
    """
    cmd = [str(binary), "--headless", "--log-file", str(placement.log_file)]
    if placement.empty_engine_dir is not None:
        # A run that must load no project (#1035): the engine's working directory
        # is the empty one the placement made, not the invoker's.
        cmd += ["--path", str(placement.empty_engine_dir)]
    cmd += args
    started = time.monotonic()
    try:
        # Capture raw bytes (no ``text=True``): Godot's ``JSON.stringify`` emits
        # UTF-8, but ``text=True`` would decode with the host locale, which
        # mojibakes or raises ``UnicodeDecodeError`` on a non-UTF-8 locale (e.g.
        # Windows cp1252/cp936) for a non-ASCII node name or echoed path. The decode
        # happens in ``_StreamCapture``, incrementally and explicitly as UTF-8, so
        # user content round-trips regardless of locale (issue #33).
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Pass the working directory as a string (not a Path): the export
            # channel resolves a relative output path against this CWD, and the
            # spawn shape stays byte-identical to the pre-#185 ``str(project)``.
            cwd=str(cwd) if cwd is not None else None,
            # ``None`` (the common case) inherits gda's own environment; a full
            # child environment is built only when ``--user-data-root`` overrides
            # the platform variable Godot resolves ``user://`` from (#653).
            env=placement.env,
        )
    except OSError as exc:
        return _not_found_result(binary, exc)

    # ``Popen`` with both pipes always gives non-None streams; the assertions name
    # that for the type checker rather than widening the capture's signature.
    assert proc.stdout is not None and proc.stderr is not None
    aborted = False
    elapsed = 0.0
    # Declared before the boundary below so the teardown can see whichever captures
    # exist. They are CONSTRUCTED inside it: each starts a reader thread, and a
    # construction that failed outside the boundary would leave the child running
    # with nothing to stop it — the same orphan the boundary exists to forbid, just
    # reached through setup instead of through the loop.
    out_capture: _StreamCapture | None = None
    err_capture: _StreamCapture | None = None
    try:
        out_capture = _StreamCapture(proc.stdout)
        err_capture = _StreamCapture(proc.stderr)
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            # Drain BEFORE the deadline check so the watch sees the last poll's
            # output even on the poll that gives up, and so a run that finished
            # just under the wire is not reported as a timeout.
            if watch.observe(
                stdout=out_capture.drain(),
                stderr=err_capture.drain(),
                elapsed=elapsed,
            ):
                # Re-polled AFTER the watch answered (#709 review): the child can
                # exit on its own while ``observe()`` deliberates, and calling
                # that exit ABORTED would synthesize a zero exit code over the
                # real one — discarding, for ``script run``, the status the
                # script's own ``quit()`` chose. Only a child that is still alive
                # here is gda's to end; a natural exit falls through to the
                # ordinary tail with its own code and its own clock.
                aborted = proc.poll() is None
                if not aborted:
                    elapsed = time.monotonic() - started
                break
            if elapsed >= timeout:
                break
            # WAIT on the child rather than sleeping through the interval: this loop
            # now runs on every gda invocation (#714), and a plain sleep would charge
            # each one up to a poll interval of latency after its engine had already
            # exited. ``wait`` returns the instant the child does, and otherwise
            # keeps exactly the cadence the watch is promised. It cannot deadlock on
            # a full pipe — the documented hazard for ``wait`` with ``PIPE`` — because
            # the reader threads are what drain those pipes, not this loop.
            try:
                proc.wait(timeout=_POLL_INTERVAL_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        else:
            # The loop ended because the child exited on its own, so the wall clock
            # is that exit — not the stale value from the last poll.
            elapsed = time.monotonic() - started
        # Whether GDA is what ended this run is decided BEFORE the teardown below
        # reaps it, and the clock is read before it too: the SIGTERM grace and the
        # reader join are gda's own shutdown, so charging them to the run would
        # report a 120s ceiling as 123s elapsed.
        ended_by_gda = aborted or proc.poll() is None
    finally:
        # The WHOLE teardown lives here, so it runs on every exit from the loop
        # above — including one by exception. A streaming launch must never outlive
        # its gda process, and the guarantee cannot be left on the happy path: the
        # runs this loop exists for are exactly the ones that do NOT stop on
        # their own, so an orphaned engine idles forever and repeated interruptions
        # accumulate engines contending over ``user://``. (``subprocess.run`` used to
        # give this free by killing its child when an exception left its ``with``
        # block; owning the process means owning that guarantee too.)
        #
        # ``BaseException`` matters, not just ``Exception``: a Ctrl-C out of the poll
        # wait is a ``KeyboardInterrupt``, and when gda runs in its own process
        # group the signal never reaches the engine at all. A ``finally`` covers
        # both, and covers whatever a caller's ``watch`` raised.
        #
        # The order is load-bearing. Reap first, so the pipes reach EOF and the
        # readers end on their own; join them next; only then close the pipes —
        # closing a descriptor a thread is blocked reading risks that read landing
        # on a recycled fd. The reap is conditional so the normal path, where the
        # child has already exited or been ended, pays nothing.
        #
        # Each step tolerates a PARTIALLY set-up capture, because setup itself can
        # fail: if the second constructor raised, the first is running and must
        # still be joined, and if the first raised there is nothing to join at all.
        # Whatever exists is drained; the pipes are always closable, since Popen
        # gave us both.
        if proc.poll() is None:
            _end_process(proc)
        stdout = out_capture.finish() if out_capture is not None else ""
        stderr = err_capture.finish() if err_capture is not None else ""
        proc.stdout.close()
        proc.stderr.close()

    if aborted:
        return RunResult(
            stdout=stdout,
            stderr=stderr,
            # Zero, and the value is never read: the watching channel classifies
            # ABORTED off ``launch_failure`` before anything consults ``exit_code``,
            # and the child's own code is the signal death gda itself caused. What it
            # must not be is NEGATIVE, which is how a genuine engine crash is
            # recognized. An error-shaped constant here would imply a mapping onto
            # ``script_aborted``'s exit 4 that does not exist — a Failure's process
            # exit comes from the code registry, never from this field.
            exit_code=0,
            launch_failure=LaunchFailure.ABORTED,
            elapsed_seconds=elapsed,
        )
    if ended_by_gda:
        return RunResult(
            # The CAPTURE, kept verbatim — no gda prose in either stream. The
            # classifying channel composes the timeout diagnostics from this, so
            # mixing gda's own sentence into the child's stderr would corrupt the
            # very evidence the streaming capture exists to preserve.
            stdout=stdout,
            stderr=stderr,
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=elapsed,
            # What the capture cannot say for itself, and the only way a shared
            # classifier can learn it: which launch this was, and the ceiling it
            # reached (#714).
            timeout_bound=TimeoutBound(timeout_label, timeout),
        )
    return RunResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode,
        elapsed_seconds=elapsed,
    )


def _end_process(proc: "subprocess.Popen[bytes]") -> None:
    """Ask the child to quit, then kill it if it will not (#655).

    Godot treats SIGTERM as a quit request and exits through its normal shutdown,
    which flushes its stdio — so asking recovers anything still buffered in the
    child. ``kill()`` is the fallback for a child that ignores the request (and is
    what ``terminate()`` already is on Windows).
    """
    proc.terminate()
    try:
        proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class LaunchFn(Protocol):
    """The headless-launch seam — the shape of :func:`launch` (#343, #664).

    Injected by a channel that calls the primitive directly, so its
    launch/classify bifurcation can be exercised with a canned
    :class:`RunResult` instead of a real engine — the launch-channel twin of the
    sentinel channel's ``RunnerFactory`` and the export channel's
    ``ExportRunnerFactory``. The default is always the real :func:`launch`: the
    deep module is reused, never re-implemented. ``gda script run`` (ADR-0031),
    ``gda scene preflight`` (#664) and ``gda export smoke`` (ADR-0042) all take
    one.
    """

    def __call__(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None,
        timeout: float,
        timeout_label: str = ...,
        watch: "LaunchWatch | None" = ...,
        user_data_root: Path | None = ...,
    ) -> RunResult: ...


class GodotRunner(Protocol):
    """Spawns a headless Godot operation and returns its raw output."""

    def run(self, operation: str, params: dict) -> RunResult: ...
