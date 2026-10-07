"""The `User-data placement` of one headless launch (#653, #850).

Split out of the launch primitive (:mod:`gda.core.engine.launch`) by ADR-0045 §2:
where a launch puts Godot's log and, under a ``--user-data-root``, its ``user://``
— the resolution, the placement, its preflight and the facts a result reports.
"""

import os
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The total ``~`` expansion (#988), shared with the project resolver so that a CLI
# path option and ``--project`` answer an unresolvable ``~user`` the same way.
from gda.core.project.paths import expand_user

# The environment variable naming a per-invocation user-data root, the env half of
# the `--user-data-root` option (issue #653). Same flag > env precedence shape as
# ``GDA_GODOT`` / ``GDA_PROJECT``.
USER_DATA_ROOT_ENV = "GDA_USER_DATA_ROOT"


@dataclass(frozen=True)
class UserDataReport:
    """Where one launch PUT Godot's user data — the disclosable facts (issue #850).

    The launch's :class:`UserDataPlacement` is prepared and DROPPED inside
    :func:`gda.core.engine.launch.launch`, so nothing outside it can see where the run's
    ``user://`` and log actually were. A channel that has to say so — ``gda script
    run``, whose callers keep diagnosing an unwritable ``user://`` as a game regression
    — needs the facts to ride the result out, the same reason
    :class:`~gda.core.engine.launch.TimeoutBound` does.

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


# The per-invocation user-data root the CLI resolved, or ``None`` for the engine
# default. Process-wide because it is process-wide CONFIG, not an operation parameter:
# it is set once from the root ``--user-data-root`` option (the same hand-over shape as
# ``gda.surface.options.set_ancestor_json``) and every later launch on any channel
# inherits it, so no channel has to plumb it through the runner seam.
#
# ``None`` means the option was ABSENT. An empty string means it was given empty,
# which is a different thing and must not collapse into absence — see
# :func:`resolve_user_data_root`.
_user_data_root_override: Optional[str] = None


def set_user_data_root(value: Optional[str]) -> None:
    """Record the root ``--user-data-root`` for every later `Headless launch`.

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

    ``None`` — the common case — means gda redirects nothing but the engine log, which
    it always owns (see :func:`user_data_placement`). Mirrors
    :func:`gda.core.engine.binary.resolve_godot_binary`'s precedence so the two
    environment knobs read the same way, including how each treats an empty value: an
    explicit but EMPTY flag raises, because an explicit value is a deliberate choice and
    an empty one is a mistake we surface rather than silently override — whereas an
    empty ENVIRONMENT variable reads as an unset one, since an unset and a blank
    variable are the same intent. Getting this wrong let an empty flag silently hand
    precedence to the environment.

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
    (see ``gda.core.engine.export_runner``, #344): ``absolute()`` rather than
    ``resolve()``, to keep the codebase's symlink-agnostic path handling.

    ``~`` is expanded through :func:`gda.core.project.paths.expand_user`, which owns the rule
    for a ``~user`` this host cannot resolve. Here the outcome is an ordinary
    relative directory under the invocation cwd — created where it can be, refused
    through this option's existing path where it cannot — instead of a
    ``RuntimeError`` traceback (#988).
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
    return expand_user(Path(raw)).absolute()


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

    ``root`` is the ``--user-data-root`` this placement was PREPARED from, carried
    here rather than left in the caller's local so the placement is self-describing:
    one object then answers every question about where the launch put its user data,
    and the :class:`UserDataReport` derives from it alone (#850 review).

    ``empty_engine_dir`` is set only for a launch that must load no project
    (#1035): an empty directory beside the log, which the launch passes to the
    engine as ``--path``. ``None`` for every other launch. It is not reported.
    """

    root: Optional[Path]
    log_file: Path
    data_path: Optional[Path]
    env: Optional[dict[str, str]]
    empty_engine_dir: Optional[Path] = None


@contextmanager
def user_data_placement(
    root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    *,
    empty_engine_dir: bool = False,
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

    ``empty_engine_dir`` also makes the empty engine working directory of a launch
    that must load no project (#1035). It is made after the log preflight, in the
    directory that holds the log (the private temporary directory, or
    ``<root>/logs``), so it uses no location that the log does not already use. If
    it cannot be made, the refusal is the same one, and it names the log target.
    It is removed on exit after every outcome, best effort.
    """
    if env is None:
        env = os.environ
    temp_root: Optional[str] = None
    engine_dir: Optional[Path] = None
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
                if empty_engine_dir:
                    engine_dir = Path(
                        tempfile.mkdtemp(prefix="gda-noproject-", dir=log_file.parent)
                    )
            except OSError as exc:
                raise UserDataUnwritable(
                    str(exc), data_path=data_path, log_file=log_file
                ) from exc
        except UserDataUnwritable:
            raise
        yield UserDataPlacement(
            root=root,
            log_file=log_file,
            data_path=data_path,
            env=child_env,
            empty_engine_dir=engine_dir,
        )
    finally:
        if engine_dir is not None:
            shutil.rmtree(engine_dir, ignore_errors=True)
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
