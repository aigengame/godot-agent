"""The Godot runner seam.

Given an operation name and JSON params, a runner spawns a one-shot
``godot --headless --script`` process and returns its raw
``{stdout, stderr, exit_code}``. The seam is a Protocol so that commands can be
exercised against a fake runner without touching a real engine (ADR-0001).
"""

import codecs
import enum
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Optional, Protocol

# The codes the runner synthesizes when it never got a result from the engine.
# Defined once in gda.exit_codes (the full exit-code ABI); imported here because
# the runner is what produces them (issue #3).
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_TIMEOUT

# The bundled GDScript operations payload, dispatched by operation name.
OPERATIONS_GD = Path(__file__).parent / "ops" / "operations.gd"

# A headless one-shot operation should be quick; this bounds a hung engine so
# the CLI fails loudly instead of blocking forever.
DEFAULT_TIMEOUT_SECONDS = 60.0

# How a timeout NAMES the launch it ended. Each channel passes its own
# (``"Godot export"``, ``"Godot import"``, …); the sentinel channel keeps the bare
# engine name it has always reported. It rides the result as part of
# :class:`TimeoutBound` and is rendered by the shared ``launch_timeout``
# classifier, so a caller still learns WHICH launch gave up (#185, #714).
DEFAULT_TIMEOUT_LABEL = "Godot"

# The environment variable naming a per-invocation user-data root, the env half of
# the `--user-data-root` option (issue #653). Same flag > env precedence shape as
# ``GDA_GODOT`` / ``GDA_PROJECT``.
USER_DATA_ROOT_ENV = "GDA_USER_DATA_ROOT"


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


@dataclass(frozen=True)
class UserDataReport:
    """Where one launch PUT Godot's user data — the disclosable facts (issue #850).

    The launch's :class:`UserDataPlacement` is prepared and DROPPED inside
    :func:`launch`, so nothing outside it can see where the run's ``user://`` and
    log actually were. A channel that has to say so — ``gda script run``, whose
    callers keep diagnosing an unwritable ``user://`` as a game regression — needs
    the facts to ride the result out, the same reason :class:`TimeoutBound` does.

    This is the placement MINUS its ``env``: the child environment is gda's own
    process environment merged with one override, and no result has any business
    carrying it. What is left is three paths, and each is reported only when it is
    a fact:

    - ``root`` is ``None`` when no ``--user-data-root`` (or ``$GDA_USER_DATA_ROOT``)
      was given, which is the common case — gda then redirects nothing but the log;
    - ``data_path`` is what :func:`engine_data_path` resolved for the child, so it
      is the platform-DERIVED path under a ``root`` (``<root>/Library/Application
      Support`` on macOS), never the bare root. ``None`` when the platform's own
      variable is unset — the honest answer, not a fabricated path;
    - ``log_file`` is set ONLY under a ``root``. Without one the log is a private
      temporary file this launch removes on the way out, so naming it would hand a
      caller a path that no longer exists. The rule lives here, in the primitive
      that owns the lifetime, rather than in each channel that publishes it.
    """

    root: Optional[Path]
    data_path: Optional[Path]
    log_file: Optional[Path]


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
    # :class:`UserDataReport`. Set by :func:`launch` on every result it returns
    # from a prepared placement, whatever the outcome: a timed-out run's ``user://``
    # root is exactly the fact a diagnosing caller wants. ``None`` on a launch
    # REFUSED before a placement existed (``USER_DATA_UNWRITABLE``, whose own
    # diagnostics name what was attempted) and on a hand-built result at a test seam.
    user_data: "UserDataReport | None" = None


# The per-invocation user-data root the CLI resolved, or ``None`` for the engine
# default. Process-wide because it is process-wide CONFIG, not an operation
# parameter: it is set once from the root ``--user-data-root`` option (the same
# hand-over shape as ``gda.headless.set_ancestor_json``) and every later launch on any
# channel inherits it, so no channel has to plumb it through the runner seam.
#
# ``None`` means the option was ABSENT. An empty string means it was given empty,
# which is a different thing and must not collapse into absence — see
# :func:`resolve_user_data_root`.
_user_data_root_override: Optional[str] = None


def set_user_data_root(value: Optional[str]) -> None:
    """Record the root ``--user-data-root`` for every later :func:`launch`.

    The write half of the option's contract, owned here beside the resolver that
    reads it, so knowledge runs downward: the CLI composition root CALLS this to
    hand the flag over instead of this module reaching up into it.

    The value is stored VERBATIM, including an empty string: collapsing ``""`` to
    ``None`` here would silently demote an explicit (if mistaken) flag to "absent"
    and let ``$GDA_USER_DATA_ROOT`` win, inverting the documented flag > env
    precedence.
    """
    global _user_data_root_override
    _user_data_root_override = value


def resolve_user_data_root(
    explicit: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Resolve the per-invocation user-data root: flag > env > engine default.

    ``None`` — the common case — means gda redirects nothing but the engine log,
    which it always owns (see :func:`user_data_placement`). Mirrors
    :func:`gda.binary.resolve_godot_binary`'s precedence so the two environment
    knobs read the same way, including how each treats an empty value: an explicit
    but EMPTY flag raises, because an explicit value is a deliberate choice and an
    empty one is a mistake we surface rather than silently override — whereas an
    empty ENVIRONMENT variable falls through to the default, since an unset and a
    blank variable are the same intent. Getting this wrong let an empty flag
    silently hand precedence to the environment.

    The root is ABSOLUTIZED, and it must be: gda and the engine do not share a
    working directory, so a relative root would name two different places. gda
    creates the log target relative to its OWN cwd, while the engine resolves the
    relative ``--log-file`` against ``--path`` (and the export channel spawns with
    ``cwd = <project>`` outright). The preflight would then pass for a file the
    engine never opens, and the engine would die in ``rotate_file()`` on the file
    it actually tried — reintroducing the very crash this machinery removes, plus
    leaking an ``app_userdata`` tree into the project. A relative
    ``XDG_DATA_HOME`` is ignored by the Linux engine outright
    (``OS_LinuxBSD::get_data_path``), which would silently not redirect ``user://``
    at all. Same bug class, and the same fix, as the export channel's ``--path``
    (see ``gda.export_runner``, #344): ``absolute()`` rather than ``resolve()``, to
    keep the codebase's symlink-agnostic path handling.
    """
    if env is None:
        env = os.environ
    given = explicit if explicit is not None else _user_data_root_override
    if given is not None:
        if not given:
            raise ValueError("explicit --user-data-root is empty")
        raw = given
    else:
        raw = env.get(USER_DATA_ROOT_ENV)
        if not raw:
            return None
    return Path(raw).expanduser().absolute()


def engine_data_path(
    env: Optional[Mapping[str, str]] = None, platform: Optional[str] = None
) -> Optional[Path]:
    """The directory Godot resolves ``user://`` under, per the engine's own rules.

    Mirrors the platform ``OS::get_data_path()`` implementations so a failure can
    NAME the directory an agent has to make writable (issue #653) — verified
    against the engine source:

    - macOS: ``$HOME/Library/Application Support`` (``OS_MacOS::get_config_path``,
      which ``get_data_path`` returns verbatim);
    - Windows: ``%APPDATA%`` (``OS_Windows::get_data_path``);
    - Linux/BSD: ``$XDG_DATA_HOME`` when it is an ABSOLUTE path, else
      ``$HOME/.local/share`` (``OS_LinuxBSD::get_data_path``).

    The engine then appends ``app_userdata/<project name>``; gda deliberately stops
    at the root, which is the part that is unwritable in a restricted profile and
    the part gda can name without parsing ``project.godot``. ``None`` when the
    platform's variable is unset, so the caller reports "unknown" rather than a
    fabricated path.
    """
    if env is None:
        env = os.environ
    if platform is None:
        platform = sys.platform
    if platform == "win32":
        appdata = env.get("APPDATA")
        return Path(appdata) if appdata else None
    home = env.get("HOME")
    if platform == "darwin":
        return Path(home) / "Library" / "Application Support" if home else None
    xdg = env.get("XDG_DATA_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg)
    return Path(home) / ".local" / "share" if home else None


def data_path_env(root: Path, platform: Optional[str] = None) -> dict[str, str]:
    """The child-environment overrides that move Godot's data path under ``root``.

    Godot has NO ``--user-data-dir`` flag (verified against the engine source: the
    spelling appears nowhere in ``main/`` or ``core/``), so the only per-invocation
    lever on ``user://`` is the platform variable :func:`engine_data_path` reads.
    Each platform therefore keeps its own layout UNDER ``root`` rather than
    resolving to ``root`` itself — the contract is "user data lands under this
    directory", and the resolved path is reported, never guessed at by the caller.
    """
    if platform is None:
        platform = sys.platform
    if platform == "win32":
        return {"APPDATA": str(root)}
    if platform == "darwin":
        # macOS resolves the data path from $HOME alone, so HOME is the only lever.
        return {"HOME": str(root)}
    return {"XDG_DATA_HOME": str(root)}


class UserDataUnwritable(OSError):
    """gda could not make one launch's user-data placement usable (issue #653).

    Carries the paths it actually RESOLVED and ATTEMPTED, so the refusal
    diagnostics can name them instead of re-deriving or paraphrasing them. Either
    may be ``None`` when the failure happened before that path was known — a
    temporary directory that could not be created has no log path yet, so the
    attempted *location* is reported instead.
    """

    def __init__(
        self,
        cause: str,
        *,
        data_path: Optional[Path] = None,
        data_location: Optional[str] = None,
        log_file: Optional[Path] = None,
        log_location: Optional[str] = None,
    ) -> None:
        super().__init__(cause)
        self.cause = cause
        self.data_path = data_path
        self.data_location = data_location
        self.log_file = log_file
        self.log_location = log_location


@dataclass(frozen=True)
class UserDataPlacement:
    """Where ONE headless launch puts Godot's user data.

    ``log_file`` is always gda-owned: the engine's default ``user://logs/godot.log``
    is a per-project path shared by every concurrent invocation AND rotated
    (``max_log_files`` 5), so two parallel runs contend over the same
    rotation-sensitive file. ``--log-file`` both moves it per invocation and
    disables rotation outright (``max_files = 1``, verified in ``Main::setup``).

    ``env`` is the FULL child environment when a root redirects ``user://``, else
    ``None`` to inherit gda's own.
    """

    log_file: Path
    data_path: Optional[Path]
    env: Optional[dict[str, str]]


@contextmanager
def user_data_placement(
    root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Iterator[UserDataPlacement]:
    """Prepare — and preflight — one launch's user-data placement (issue #653).

    Godot builds its file logger BEFORE it runs any project code, and
    ``RotatedFileLogger`` dereferences the ``FileAccess`` it failed to open, so a
    log target it cannot write kills the process with signal 11 in
    ``rotate_file()`` — reported as a noisy ``engine_crashed`` backtrace rather
    than the environment problem it is. gda therefore takes the log target over
    and CREATES it here, before spawning: the creation IS the preflight, and it
    fails as a typed :class:`UserDataUnwritable` instead of as a crash.

    Without a ``root`` the log goes to a private temporary directory, removed on
    exit — an isolated, writable target that keeps a read-only application-data
    directory from being fatal at all, and gives concurrent invocations separate
    files. Nothing else is preflighted in this mode, deliberately: the engine's own
    ``user://`` location is none of gda's business when gda is not redirecting it,
    and most commands never touch it.

    With a ``root``, gda IS redirecting ``user://``, and so it owns that promise
    too: the log lands at ``<root>/logs/godot.log``, the child's platform data
    variable is overridden, and **the platform-derived data path is created and
    probed as well**. Creating ``root`` alone is not enough — the engine appends a
    platform layout to it (``<root>/Library/Application Support`` on macOS), and
    that derived path can be unusable while ``root`` is perfectly writable, e.g.
    blocked by a regular file. gda would then have preflighted only the log,
    reported success, and left the script with an unopenable ``user://``.
    """
    if env is None:
        env = os.environ
    temp_root: Optional[str] = None
    try:
        try:
            if root is None:
                # A fully locked-down temporary directory makes this itself fail;
                # it is inside the guard so that too is a typed refusal, not a
                # traceback escaping the primitive. There is no log path to name
                # yet, so the attempted LOCATION is carried instead.
                try:
                    temp_root = tempfile.mkdtemp(prefix="gda-log-")
                except OSError as exc:
                    raise UserDataUnwritable(
                        str(exc),
                        data_path=engine_data_path(env),
                        log_location=(
                            f"a private directory under {tempfile.gettempdir()}"
                        ),
                    ) from exc
                log_file = Path(temp_root) / "godot.log"
                child_env = None
                data_path = engine_data_path(env)
            else:
                child_env = {**env, **data_path_env(root)}
                log_file = root / "logs" / "godot.log"
                data_path = engine_data_path(child_env)
            try:
                if root is not None and data_path is not None:
                    _probe_data_path(data_path)
                log_file.parent.mkdir(parents=True, exist_ok=True)
                # Truncate-or-create: the probe that proves the engine's own
                # ``FileAccess::open(..., WRITE)`` will succeed, and the same
                # per-launch truncation the daemon does for a Session log (ADR-0022).
                log_file.write_bytes(b"")
            except OSError as exc:
                raise UserDataUnwritable(
                    str(exc), data_path=data_path, log_file=log_file
                ) from exc
        except UserDataUnwritable:
            raise
        yield UserDataPlacement(log_file=log_file, data_path=data_path, env=child_env)
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def _probe_data_path(data_path: Path) -> None:
    """Create ``data_path`` and prove a subdirectory can be made inside it.

    The ``user://`` half of the preflight, and it takes the same shape as the log
    half — create the thing, do not merely inspect it — because that is what the
    engine will do: ``OS::ensure_user_data_dir`` calls ``make_dir_recursive`` on
    ``<data_path>/app_userdata/<project name>``. So the probe creates and removes a
    throwaway directory rather than checking a permission bit, which would miss an
    immutable flag, a full filesystem, or a read-only mount. Raises ``OSError`` for
    the caller to map.
    """
    data_path.mkdir(parents=True, exist_ok=True)
    probe = tempfile.mkdtemp(prefix=".gda-probe-", dir=data_path)
    os.rmdir(probe)


def _user_data_unwritable_stderr(
    binary: Path, root: Optional[Path], failure: UserDataUnwritable
) -> str:
    """The diagnostics prose for a refused launch (issue #653).

    Names the three paths an agent needs to act on — the resolved binary, the
    directory Godot resolves ``user://`` under, and the log target gda tried to
    create — plus whether gda is redirecting ``user://`` at all. The paths come
    from the failure itself, which RESOLVED them: paraphrasing them here ("under
    <root>", "a private temporary directory") named neither the platform-derived
    data path the engine would use nor the file actually attempted, so a reader
    could not act on either. Prose only: this text becomes
    ``GdaError.diagnostics``, whose ADR-0004 shape is unchanged.
    """
    if failure.data_path is None and failure.data_location is not None:
        # The placement was never prepared (an unresolvable root), so there is no
        # resolved path to name — render the unavailable fields explicitly rather
        # than dropping the three-path shape this diagnostic guarantees.
        where_suffix = ""
        remedy = (
            "pass a non-empty --user-data-root directory (an explicit empty "
            "value is refused rather than silently ignored, mirroring --godot)"
        )
    elif root is None:
        where_suffix = " (engine default; gda is not redirecting user://)"
        remedy = (
            "gda redirects only the engine log by default, not user://; "
            f"pass --user-data-root <writable dir> (or set {USER_DATA_ROOT_ENV}) "
            "to place both the log and user:// under a writable directory"
        )
    else:
        where_suffix = " (--user-data-root)"
        remedy = (
            f"gda redirects user:// under {root} for this invocation, so that "
            "directory and the platform path derived from it must both be writable"
        )
    where = (
        f"{failure.data_path}{where_suffix}"
        if failure.data_path
        else (failure.data_location or "unknown")
    )
    log_target = (
        str(failure.log_file)
        if failure.log_file is not None
        else (failure.log_location or "unknown")
    )
    return (
        "gda: Godot user data is not usable; the launch was refused before the "
        "engine started\n"
        f"gda:   binary:    {binary}\n"
        f"gda:   user data: {where}\n"
        f"gda:   log file:  {log_target}\n"
        f"gda:   cause:     {failure.cause}\n"
        f"gda: {remedy}.\n"
    )


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
    """
    try:
        root = resolve_user_data_root()
    except ValueError as exc:
        # An explicit but empty --user-data-root. There is no placement to prepare,
        # so it is the same unusable-placement outcome, reported before any spawn
        # (mirrors how an empty --godot becomes binary_not_found, #33) — through
        # the SHARED formatter, so the three-path diagnostic shape holds with the
        # unavailable fields rendered explicitly.
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
    try:
        with user_data_placement(root) as placement:
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
                    root=root,
                    data_path=placement.data_path,
                    log_file=placement.log_file if root is not None else None,
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
    cmd = [str(binary), "--headless", "--log-file", str(placement.log_file), *args]
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
    deep module is reused, never re-implemented. ``gda script run`` (ADR-0031)
    and ``gda scene preflight`` (#664) both take one.
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
    ) -> RunResult: ...


def sentinel_args(
    operation: str,
    params: dict,
    *,
    project: Path | None,
    script: Path = OPERATIONS_GD,
) -> list[str]:
    """The argv tail that dispatches one sentinel operation (ADR-0001, ADR-0002).

    How a sentinel op is SPELLED on the command line, owned once: the payload
    script, the ``--`` separator, the operation name and its JSON params — plus
    ``--path`` when the op runs against a project, so ``res://`` resolves there
    (issue #32). Everything after ``--`` reaches the payload verbatim through
    ``OS.get_cmdline_user_args()``, which decouples it from however Godot orders
    its own engine arguments.

    Two channels build this tail (#664): :class:`SubprocessGodotRunner`, the
    default sentinel runner, and ``scene preflight``, which dispatches the same
    kind of op but calls :func:`launch` itself — it bifurcates on the launch's own
    outcome (a timeout is its VERDICT, not an error) rather than handing the result
    to a classifier through the runner seam. Extracting the spelling keeps that
    second channel from re-deriving it, and keeps a change to it (a new separator,
    another engine flag) landing in one place.
    """
    args: list[str] = []
    if project is not None:
        args += ["--path", str(project)]
    return [*args, "--script", str(script), "--", operation, json.dumps(params)]


class GodotRunner(Protocol):
    """Spawns a headless Godot operation and returns its raw output."""

    def run(self, operation: str, params: dict) -> RunResult: ...


@dataclass
class SubprocessGodotRunner:
    """A GodotRunner that spawns a one-shot ``godot --headless --script`` process.

    It dispatches the operation to the bundled ``operations.gd`` payload and
    returns the process's raw stdout/stderr/exit code unparsed — extracting the
    result from the noise is the parser's job (ADR-0002). When ``project`` is
    set it is passed as ``--path`` so the engine runs against that project and
    ``res://`` resolves there (issue #32); otherwise the engine runs projectless.
    """

    binary: Path
    project: Path | None = None
    script: Path = OPERATIONS_GD
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def run(self, operation: str, params: dict) -> RunResult:
        # Build only this channel's argv tail (:func:`sentinel_args`, shared with the
        # one other channel that dispatches a sentinel op) and delegate the spawn /
        # timeout / OSError / UTF-8-decode handling to the shared launch primitive
        # (#185).
        #
        # A sentinel op runs projectless or against --path; it never needs a working
        # directory, so cwd is always the default.
        return launch(
            self.binary,
            sentinel_args(operation, params, project=self.project, script=self.script),
            cwd=None,
            timeout=self.timeout,
        )
