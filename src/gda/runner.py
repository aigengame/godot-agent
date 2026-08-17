"""The Godot runner seam.

Given an operation name and JSON params, a runner spawns a one-shot
``godot --headless --script`` process and returns its raw
``{stdout, stderr, exit_code}``. The seam is a Protocol so that commands can be
exercised against a fake runner without touching a real engine (ADR-0001).
"""

import enum
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

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


@dataclass
class RunResult:
    """The raw result of a one-shot headless Godot invocation."""

    stdout: str
    stderr: str
    exit_code: int
    # Set only when the runner synthesized this result (binary missing, timed
    # out) instead of the engine returning one; ``None`` means the exit_code is
    # the engine's own (issue #15).
    launch_failure: "LaunchFailure | None" = None


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


def launch(
    binary: Path,
    args: list[str],
    *,
    cwd: Path | None,
    timeout: float,
    timeout_label: str = "Godot",
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
            return _spawn(
                binary,
                args,
                cwd=cwd,
                timeout=timeout,
                timeout_label=timeout_label,
                placement=placement,
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
    """Run one prepared launch and normalize its outcome — see :func:`launch`."""
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
        return RunResult(
            stdout="",
            stderr=f"gda: {timeout_label} timed out after {timeout}s\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        )
    except OSError as exc:
        return RunResult(
            stdout="",
            stderr=f"gda: Godot binary could not be launched: {binary} ({exc})\n",
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.NOT_FOUND,
        )
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
        # Build only this channel's argv tail and delegate the spawn / timeout /
        # OSError / UTF-8-decode handling to the shared launch primitive (#185).
        # Everything after `--` is delivered to the script verbatim via
        # OS.get_cmdline_user_args(), so the payload is decoupled from however
        # Godot orders its own engine arguments.
        args: list[str] = []
        if self.project is not None:
            args += ["--path", str(self.project)]
        args += [
            "--script",
            str(self.script),
            "--",
            operation,
            json.dumps(params),
        ]
        # A sentinel op runs projectless or against --path; it never needs a
        # working directory, so cwd is always the default.
        return launch(self.binary, args, cwd=None, timeout=self.timeout)
