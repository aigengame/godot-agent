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
from dataclasses import dataclass
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
    # caller that passes a ``watch``, which today is ``gda script run`` alone —
    # and that channel classifies this value itself, because only it knows what
    # its watch condition means. ``classify_launch_or_crash`` therefore does NOT
    # map it: a shared classifier has no honest generic code for "the caller's
    # own declared condition fired". A future watching channel must classify it
    # too rather than fall through to that shared prefix.
    ABORTED = "aborted"


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
    # The launch's wall clock, measured only on the STREAMING capture path (issue
    # #655) — ``None`` under the buffered capture, which does not time itself. It is the
    # datum that tells a merely-slow run from a hung one: a timeout at 121s of a
    # 120s ceiling is a suite that outgrew its budget, while one that produced its
    # last output at 2s is stuck.
    elapsed_seconds: float | None = None


# The per-invocation user-data root the CLI resolved, or ``None`` for the engine
# default. Process-wide because it is process-wide CONFIG, not an operation
# parameter: it is set once from the root ``--user-data-root`` option (the same
# hand-over shape as ``gda.headless.set_root_json``) and every later launch on any
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
    """A channel's incremental view of one streaming launch (issue #655).

    Passing a watch to :func:`launch` switches the primitive from BUFFERED capture
    (``subprocess.run``, which discards everything the child wrote when the
    timeout expires) to STREAMING capture, which changes three things about the
    launch and nothing else:

    - the child's stdout/stderr are read as they arrive, so **whatever the run
      produced before gda ended it survives** into the ``RunResult`` — the
      dogfooding defect this seam exists for (GDA-DF-012/GDA-DF-032: a 120s
      timeout whose diagnostics held only the timeout message);
    - the launch is timed, so ``RunResult.elapsed_seconds`` is populated;
    - the watch can **end the run early**, before the timeout.

    The primitive owns the MECHANISM (spawn, read, decode, deadline, terminate)
    and the watch owns the POLICY (what the output means, and when a run is not
    worth waiting out). That split is why the policy is injected rather than
    written here: "a fatal script error appeared and the caller's declared
    completion marker did not" is ``script run``'s domain knowledge, not the
    channel-agnostic primitive's — and ADR-0031 rejected gda imposing any
    contract on a user-authored entry script, so only a caller can declare one.

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


# How often the streaming path polls the child and its watch. It bounds the extra
# latency an early abort or a timeout can carry (a poll may sleep through the
# moment the condition became true), so it is small — but not so small that a
# 120s run spends its time waking up: 0.05s is ~2400 polls over the default
# ``script run`` ceiling.
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
    whole buffer at once yields, so the streaming path's text is identical to the
    buffered strategy's for the same bytes.
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
    timeout_label: str = "Godot",
    watch: Optional[LaunchWatch] = None,
) -> RunResult:
    """Spawn one ``godot --headless`` process and normalize its raw outcome.

    The single home of the headless-launch primitive: it builds
    ``[binary, --headless, *args]``, runs it with a timeout capturing raw
    *bytes*, and returns a normalized :class:`RunResult`. Both Phase-1 channels
    — the sentinel op-dispatch runner and the native-export runner — build only
    their channel-specific argv tail (and the export-only ``cwd``) and delegate
    the spawn/timeout/``OSError``/decode handling here, so a launch-handling fix
    lands in one place rather than two copies (issue #185, ADR-0010).

    The mapping, identical for both channels:

    - ``subprocess.TimeoutExpired`` → a synthesized ``EXIT_TIMEOUT`` result
      flagged ``LaunchFailure.TIMEOUT``: launched, but did not return before the
      timeout (a hung engine bounded so the CLI fails loudly, #15). The diagnostic
      names ``timeout_label`` (default ``"Godot"``; the export channel passes
      ``"Godot export"``) — this stderr is carried into ``GdaError.diagnostics``
      and serialized in ``--json``, so the per-channel wording is part of the
      public error envelope and stays byte-compatible across the refactor (#185);
    - ``OSError`` → a synthesized ``EXIT_NOT_FOUND`` result flagged
      ``LaunchFailure.NOT_FOUND``: the configured binary could not be launched —
      ``FileNotFoundError`` (missing), ``PermissionError`` (a directory like
      ``Godot.app`` — a natural ``$GDA_GODOT`` mistake — or a non-executable
      file), and any other ``OSError`` from ``exec`` are the one environment
      failure of there being no engine to run (#33). The synthesized typed
      reason lets the classifier key environment on it, not on the overloaded
      exit code (#15). ``OSError`` does not subsume ``TimeoutExpired`` (a
      ``SubprocessError``), so the timeout path above is preserved. The OS
      message is kept as advisory stderr to disambiguate which mode occurred;
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

    **Two capture strategies, one mapping (issue #655).** ``watch`` selects how the
    child's output is captured, and nothing else:

    - ``None`` (the default, and what the sentinel and export channels pass) —
      BUFFERED capture via ``subprocess.run``. A timeout DISCARDS whatever the
      child wrote and synthesizes the ``gda: <label> timed out after <n>s``
      diagnostic in its place, exactly as before.
    - a :class:`LaunchWatch` (``gda script run``) — STREAMING capture. A timeout
      PRESERVES the captured stdout/stderr verbatim and carries no gda prose in
      either stream, because the watching channel composes its own diagnostics
      from the capture; ``elapsed_seconds`` is populated; and the watch may end
      the run early as ``LaunchFailure.ABORTED``.

    Keeping the buffered strategy is deliberate rather than transitional debt: the
    other two channels' timeout results are a published part of their error
    envelopes, and this change had to leave them byte-identical. Moving them onto
    the preserving path is the named follow-up the issue records, and it is a
    one-line switch here — not a second mechanism to write. What is NOT duplicated
    is the failure mapping: both strategies return through the same
    :func:`_timeout_result` / :func:`_not_found_result`, so the timeout and
    launch-failure taxonomy still has exactly one home.
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
            if watch is None:
                return _spawn(
                    binary,
                    args,
                    cwd=cwd,
                    timeout=timeout,
                    timeout_label=timeout_label,
                    placement=placement,
                )
            return _spawn_streamed(
                binary,
                args,
                cwd=cwd,
                timeout=timeout,
                placement=placement,
                watch=watch,
            )
    except UserDataUnwritable as exc:
        return RunResult(
            stdout="",
            stderr=_user_data_unwritable_stderr(binary, root, exc),
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.USER_DATA_UNWRITABLE,
        )


def _spawn(
    binary: Path,
    args: list[str],
    *,
    cwd: Path | None,
    timeout: float,
    timeout_label: str,
    placement: UserDataPlacement,
) -> RunResult:
    """Run one prepared launch with BUFFERED capture — see :func:`launch`.

    Reads both streams in one ``subprocess.run`` call, which is why a timeout here
    has nothing left to report: the call discards what it buffered when it raises.
    """
    cmd = [str(binary), "--headless", "--log-file", str(placement.log_file), *args]
    try:
        # Capture raw bytes (no ``text=True``): Godot's ``JSON.stringify`` emits
        # UTF-8, but ``text=True`` would decode with the host locale, which
        # mojibakes or raises ``UnicodeDecodeError`` on a non-UTF-8 locale (e.g.
        # Windows cp1252/cp936) for a non-ASCII node name or echoed path. We
        # decode UTF-8 explicitly below so user content round-trips regardless of
        # locale (issue #33).
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            # Pass the working directory as a string (not a Path): the export
            # channel resolves a relative output path against this CWD, and the
            # spawn shape stays byte-identical to the pre-#185 ``str(project)``.
            cwd=str(cwd) if cwd is not None else None,
            # ``None`` (the common case) inherits gda's own environment; a full
            # child environment is built only when ``--user-data-root`` overrides
            # the platform variable Godot resolves ``user://`` from (#653).
            env=placement.env,
        )
    except subprocess.TimeoutExpired:
        return _timeout_result(timeout, timeout_label)
    except OSError as exc:
        return _not_found_result(binary, exc)
    return RunResult(
        # Decode the engine's bytes as UTF-8 with a replacement policy: a
        # well-behaved operation emits valid UTF-8, so ``replace`` only ever
        # fires on genuinely malformed bytes — and the runner never crashes on
        # engine output. A malformed result then surfaces as a structured
        # ``contract_violation`` downstream rather than an escaping
        # ``UnicodeDecodeError`` traceback (ADR-0002).
        stdout=proc.stdout.decode("utf-8", errors="replace"),
        stderr=proc.stderr.decode("utf-8", errors="replace"),
        exit_code=proc.returncode,
    )


def _timeout_result(timeout: float, timeout_label: str) -> RunResult:
    """The synthesized result of a run that outlived the BUFFERED capture's timeout.

    The output is gone — ``subprocess.run`` discards it when the timeout expires —
    so the diagnostic stands in for it. That wording is carried into
    ``GdaError.diagnostics`` and serialized in ``--json``, which makes it part of
    the public error envelope of the sentinel and export channels; it is kept
    byte-for-byte, and shared here, so no channel can drift from it (#185, #655).
    """
    return RunResult(
        stdout="",
        stderr=f"gda: {timeout_label} timed out after {timeout}s\n",
        exit_code=EXIT_TIMEOUT,
        launch_failure=LaunchFailure.TIMEOUT,
    )


def _not_found_result(binary: Path, exc: OSError) -> RunResult:
    """The synthesized result of a binary that could not be launched at all.

    Shared by both capture strategies: an ``OSError`` from ``exec`` is the one
    environment failure of there being no engine to run, whichever way gda was
    going to read its output (#33, #655).
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
    placement: UserDataPlacement,
    watch: LaunchWatch,
) -> RunResult:
    """Run one prepared launch with STREAMING capture — see :func:`launch` (#655).

    The same argv, cwd and child environment as :func:`_spawn`; only the reading
    differs. Both pipes are drained on their own threads while this loop owns the
    deadline and the watch, so:

    - a timeout returns the output the child had ALREADY produced, verbatim,
      instead of discarding it. This is the whole point: a script error that
      aborted a run before its ``quit()`` had already been printed, and a
      buffered capture threw it away (GDA-DF-012);
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
        # Bytes, not ``text=True``, for the same locale reason as ``_spawn`` (#33);
        # the decode happens in ``_StreamCapture``, incrementally.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
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
                aborted = True
                break
            if elapsed >= timeout:
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
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
        # runs this strategy exists for are exactly the ones that do NOT stop on
        # their own, so an orphaned engine idles forever and repeated interruptions
        # accumulate engines contending over ``user://``. The buffered strategy gets
        # this free (``subprocess.run`` kills its child when an exception leaves its
        # ``with`` block), so this path owes the same.
        #
        # ``BaseException`` matters, not just ``Exception``: a Ctrl-C out of the poll
        # sleep is a ``KeyboardInterrupt``, and when gda runs in its own process
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
            # watching channel composes the timeout diagnostics from this, so
            # mixing gda's own sentence into the child's stderr would corrupt the
            # very evidence the streaming path exists to preserve.
            stdout=stdout,
            stderr=stderr,
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=elapsed,
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
    kind of op but needs :func:`launch`'s STREAMING capture — so it calls the
    primitive itself rather than going through the runner seam. Extracting the
    spelling keeps that second channel from re-deriving it, and keeps a change to
    it (a new separator, another engine flag) landing in one place.
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
