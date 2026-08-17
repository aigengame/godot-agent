"""gda owns the engine log target of every headless launch (issue #653).

Godot builds its file logger before it runs any project code, and
``RotatedFileLogger::rotate_file()`` dereferences the ``FileAccess`` it failed to
open — so a log target the engine cannot write kills the process with signal 11,
which reached an agent as an ``engine_crashed`` backtrace rather than as the
environment problem it is. The engine has NO ``--user-data-dir`` flag (verified
against the engine source), so gda's levers are ``--log-file`` for the log and the
platform data variable for ``user://``.

These are the unit-tier guards on that contract; the real-engine proof — a genuinely
unwritable application-data directory — lives in ``test_e2e_user_data.py``.
"""

import subprocess
from pathlib import Path

import pytest

from typer.testing import CliRunner

from gda.cli import app
from gda.errors import Failure, classify_launch_or_crash
from gda.exit_codes import EXIT_NOT_FOUND
from gda.models import ErrorCategory
from gda.runner import (
    USER_DATA_ROOT_ENV,
    LaunchFailure,
    data_path_env,
    engine_data_path,
    launch,
    resolve_user_data_root,
    set_user_data_root,
    user_data_placement,
)
from tests.support import VERSION_INFO, sentinel


@pytest.fixture(autouse=True)
def _no_root_override():
    """Keep the process-wide root override off unless a test sets it."""
    set_user_data_root(None)
    yield
    set_user_data_root(None)


class _RecordingRun:
    """A ``subprocess.run`` double recording the call and returning a clean exit.

    ``payload`` is the raw stdout the fake engine writes; the CLI-seam tests pass a
    real ADR-0002 sentinel so the command SUCCEEDS, and the argv assertion is then
    made on a working invocation rather than on one that happened to fail late.
    """

    def __init__(self, payload: str = "") -> None:
        self.cmd: list[str] | None = None
        self.kwargs: dict | None = None
        self._payload = payload.encode()

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        payload = self._payload

        class _Proc:
            stdout = payload
            stderr = b""
            returncode = 0

        return _Proc()


def _log_file_arg(cmd: list[str]) -> Path:
    return Path(cmd[cmd.index("--log-file") + 1])


# --------------------------------------------------------------------------
# The default: an isolated, gda-owned log target
# --------------------------------------------------------------------------


def test_default_launch_redirects_the_log_to_a_gda_owned_file(monkeypatch):
    # The crash fix: the engine never resolves `user://logs/godot.log`, because gda
    # hands it a target it has already created.
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        log_file = _log_file_arg(cmd)
        # Created BEFORE the spawn — that creation is the preflight, and it is what
        # guarantees the engine's own FileAccess open cannot fail.
        seen["name"] = log_file.name
        seen["existed"] = log_file.exists()

        class _Proc:
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert seen == {"name": "godot.log", "existed": True}


def test_default_launch_does_not_touch_the_child_environment(monkeypatch):
    # Without a root, gda redirects the LOG only: `user://`, the export templates
    # and the editor settings all stay where the engine puts them by default.
    rec = _RecordingRun()
    monkeypatch.setattr(subprocess, "run", rec)

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert rec.kwargs is not None and rec.kwargs.get("env") is None


def test_default_log_target_is_removed_after_the_run(monkeypatch):
    seen: dict[str, Path] = {}

    def fake_run(cmd, **kwargs):
        seen["log"] = _log_file_arg(cmd)

        class _Proc:
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    # A private temporary directory, cleaned up so repeated invocations do not
    # accumulate stale logs.
    assert not seen["log"].exists()
    assert not seen["log"].parent.exists()


def test_concurrent_default_launches_get_distinct_log_targets(monkeypatch):
    # The non-contention guarantee: the engine default is ONE per-project
    # `user://logs/godot.log` that is also rotated (max_log_files 5), so parallel
    # invocations fight over the same rotation-sensitive file. Two gda launches
    # must never name the same target.
    targets: list[Path] = []

    def fake_run(cmd, **kwargs):
        targets.append(_log_file_arg(cmd))

        class _Proc:
            stdout = b""
            stderr = b""
            returncode = 0

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)
    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert targets[0] != targets[1]


# --------------------------------------------------------------------------
# The preflight refusal
# --------------------------------------------------------------------------


def test_unwritable_log_root_is_refused_before_the_spawn(monkeypatch, tmp_path):
    # The whole point: refuse with a typed reason instead of letting the engine
    # segfault in its logger. `subprocess.run` must never be reached.
    def _must_not_spawn(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("the engine must not be spawned")

    monkeypatch.setattr(subprocess, "run", _must_not_spawn)
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        set_user_data_root(str(locked / "root"))

        result = launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)
    finally:
        locked.chmod(0o755)

    assert result.launch_failure is LaunchFailure.USER_DATA_UNWRITABLE
    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stdout == ""


def test_refusal_diagnostics_name_binary_user_data_and_log_path(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    root = locked / "root"
    try:
        set_user_data_root(str(root))

        result = launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)
    finally:
        locked.chmod(0o755)

    # An agent must be able to act without reading gda's source: the three paths
    # it would have to fix are all named.
    assert "/x/Godot" in result.stderr
    assert str(root) in result.stderr
    assert str(root / "logs" / "godot.log") in result.stderr


def test_default_root_refusal_names_the_engine_resolved_user_data_dir(monkeypatch):
    # With no --user-data-root, the failure must still name where `user://` lives
    # — the engine's own resolved directory — and say gda is not redirecting it.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)

    def _explode(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("gda.runner.tempfile.mkdtemp", _explode)

    result = launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert result.launch_failure is LaunchFailure.USER_DATA_UNWRITABLE
    data_path = engine_data_path()
    assert data_path is not None and str(data_path) in result.stderr
    assert "--user-data-root" in result.stderr
    assert USER_DATA_ROOT_ENV in result.stderr


def test_refusal_classifies_as_the_environment_error_code():
    # The registry row: ENVIRONMENT category, the shared 127 environment exit.
    from gda.runner import RunResult

    raw = RunResult(
        stdout="",
        stderr="gda: Godot user data is not writable\n",
        exit_code=EXIT_NOT_FOUND,
        launch_failure=LaunchFailure.USER_DATA_UNWRITABLE,
    )

    outcome = classify_launch_or_crash(raw, Path("/x/Godot"))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "user_data_unwritable"
    assert outcome.error.category is ErrorCategory.ENVIRONMENT
    assert outcome.exit_code == EXIT_NOT_FOUND
    # It is NOT the engine_crashed backtrace this used to arrive as.
    assert outcome.error.diagnostics == raw.stderr


# --------------------------------------------------------------------------
# --user-data-root
# --------------------------------------------------------------------------


def test_root_redirects_both_the_log_and_the_platform_data_variable(
    monkeypatch, tmp_path
):
    rec = _RecordingRun()
    monkeypatch.setattr(subprocess, "run", rec)
    root = tmp_path / "udr"
    set_user_data_root(str(root))

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert rec.cmd is not None
    assert _log_file_arg(rec.cmd) == root / "logs" / "godot.log"
    # The child gets a FULL environment carrying the platform override, so
    # `user://` resolves under the same root as the log.
    assert rec.kwargs is not None
    env = rec.kwargs["env"]
    assert env is not None
    assert set(data_path_env(root).items()) <= set(env.items())
    # The root itself is created, so the engine can build app_userdata/<name> in it.
    assert root.is_dir()


def test_a_relative_root_is_absolutized_against_gda_cwd(monkeypatch, tmp_path):
    # gda and the engine do NOT share a working directory, so a relative root names
    # two different places: gda creates the log relative to its own cwd while the
    # engine resolves the relative --log-file against --path (and the export channel
    # spawns with cwd=<project>). The preflight would then pass for a file the engine
    # never opens, and the engine would die in rotate_file() on the one it did —
    # reintroducing the crash. Same bug class as the export channel's --path (#344).
    rec = _RecordingRun()
    monkeypatch.setattr(subprocess, "run", rec)
    monkeypatch.chdir(tmp_path)
    set_user_data_root("./rel")

    launch(Path("/x/Godot"), ["--path", "/some/project"], cwd=None, timeout=60.0)

    assert rec.cmd is not None
    log_file = _log_file_arg(rec.cmd)
    assert log_file.is_absolute()
    assert log_file == tmp_path / "rel" / "logs" / "godot.log"


def test_a_relative_root_absolutizes_the_platform_override_too(monkeypatch, tmp_path):
    # The env half must be absolutized as well, and for an extra reason: the Linux
    # engine IGNORES a relative XDG_DATA_HOME outright (OS_LinuxBSD::get_data_path),
    # so a relative root would silently not redirect `user://` at all while the docs
    # promise it does.
    rec = _RecordingRun()
    monkeypatch.setattr(subprocess, "run", rec)
    monkeypatch.chdir(tmp_path)
    set_user_data_root("./rel")

    launch(Path("/x/Godot"), ["--version"], cwd=None, timeout=60.0)

    assert rec.kwargs is not None
    env = rec.kwargs["env"]
    assert env is not None
    for value in data_path_env(tmp_path / "rel").values():
        assert Path(value).is_absolute()
    assert set(data_path_env(tmp_path / "rel").items()) <= set(env.items())


def test_root_precedence_is_flag_then_env_then_engine_default(monkeypatch):
    monkeypatch.setenv(USER_DATA_ROOT_ENV, "/from/env")
    assert resolve_user_data_root() == Path("/from/env")

    set_user_data_root("/from/flag")
    assert resolve_user_data_root() == Path("/from/flag")

    set_user_data_root(None)
    monkeypatch.delenv(USER_DATA_ROOT_ENV)
    assert resolve_user_data_root() is None


def test_root_expands_a_user_relative_path(monkeypatch):
    monkeypatch.setenv(USER_DATA_ROOT_ENV, "~/gda-user-data")
    resolved = resolve_user_data_root()
    assert resolved is not None and "~" not in str(resolved)


# --------------------------------------------------------------------------
# The engine's own resolution rules, mirrored for reporting and redirect
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        # OS_MacOS::get_config_path(), which get_data_path() returns verbatim.
        ("darwin", {"HOME": "/h"}, "/h/Library/Application Support"),
        # OS_Windows::get_data_path().
        ("win32", {"APPDATA": "/a"}, "/a"),
        # OS_LinuxBSD::get_data_path(): XDG_DATA_HOME when absolute, else
        # $HOME/.local/share.
        ("linux", {"HOME": "/h", "XDG_DATA_HOME": "/xdg"}, "/xdg"),
        ("linux", {"HOME": "/h", "XDG_DATA_HOME": "rel"}, "/h/.local/share"),
        ("linux", {"HOME": "/h"}, "/h/.local/share"),
    ],
)
def test_engine_data_path_mirrors_the_engine_per_platform(platform, env, expected):
    assert engine_data_path(env, platform=platform) == Path(expected)


def test_engine_data_path_is_unknown_when_the_variable_is_unset():
    # Report "unknown" rather than fabricate a path gda cannot know.
    assert engine_data_path({}, platform="darwin") is None
    assert engine_data_path({}, platform="win32") is None


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", {"HOME": "/r"}),
        ("win32", {"APPDATA": "/r"}),
        ("linux", {"XDG_DATA_HOME": "/r"}),
    ],
)
def test_data_path_env_targets_the_variable_that_platform_reads(platform, expected):
    # The redirect must set exactly the variable engine_data_path reads back, or
    # the reported path and the real one diverge.
    assert data_path_env(Path("/r"), platform=platform) == expected


def test_placement_reports_the_redirected_data_path(tmp_path):
    root = tmp_path / "udr"
    with user_data_placement(root, env={"HOME": "/h"}) as placement:
        assert placement.data_path is not None
        assert str(root) in str(placement.data_path)


# --------------------------------------------------------------------------
# The CLI seam: the OPTION, not just the environment variable
# --------------------------------------------------------------------------


def test_the_root_option_reaches_the_launch(monkeypatch, tmp_path):
    # The option travels CLI → root callback → set_user_data_root → the runner, a
    # hand-over seam with no other test on it: every other arm here drives the env
    # twin, which bypasses the CLI entirely. Without this, deleting the root
    # callback's `set_user_data_root(...)` line leaves the whole suite green and the
    # flag silently inert — a live risk, since a sibling change rewrites exactly
    # those lines in `gda.cli`.
    rec = _RecordingRun(sentinel(VERSION_INFO))
    monkeypatch.setattr(subprocess, "run", rec)
    monkeypatch.delenv(USER_DATA_ROOT_ENV, raising=False)
    root = tmp_path / "from-the-flag"

    result = CliRunner().invoke(app, ["--user-data-root", str(root), "info", "--json"])

    assert result.exit_code == 0, result.stdout
    assert rec.cmd is not None
    assert _log_file_arg(rec.cmd) == root / "logs" / "godot.log"
    assert rec.kwargs is not None and rec.kwargs["env"] is not None


def test_without_the_root_option_the_launch_keeps_the_engine_default(
    monkeypatch, tmp_path
):
    # The negative half: absent the flag (and the env twin), nothing is redirected
    # but the log — so this pair fails if the option is wired to always-on as well
    # as if it is wired to nothing.
    rec = _RecordingRun(sentinel(VERSION_INFO))
    monkeypatch.setattr(subprocess, "run", rec)
    monkeypatch.delenv(USER_DATA_ROOT_ENV, raising=False)

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == 0, result.stdout
    assert rec.kwargs is not None and rec.kwargs["env"] is None
