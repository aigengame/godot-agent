"""e2e: a headless launch survives a read-only application-data directory (#653).

The dogfooding failure (GDA-DF-001/014/042/030/028) is a filesystem-restricted
process where the *project* is writable but Godot's application-data directory is
not. Godot builds its file logger before any project code runs, and
``RotatedFileLogger::rotate_file()`` dereferences the ``FileAccess`` it could not
open — so EVERY command performing a headless launch died with signal 11 and was
reported as ``engine_crashed`` plus a C++ backtrace, rather than as the
environment problem it is.

These are real-engine tests because the claim is about the engine's own startup
order and crash behaviour: a fake runner would only prove that gda passes a flag.
The control arm deliberately spawns the raw engine, without gda's ``--log-file``,
to prove the restriction still breaks an unprotected launch — so the protected
arms cannot pass for the wrong reason (e.g. because the sandbox turned out to be
writable after all).

**These fixtures deliberately leave file logging at the engine default** instead of
using ``conftest.project_godot``, which disables it. Disabling it is exactly what
would hide the bug: with no ``RotatedFileLogger`` there is no crash to survive. It
is safe here because every gda launch now writes to its OWN private log target, so
the shared-``user://logs`` contention #180 worked around project-side cannot occur;
and the single raw-engine control run is confined to its own fake HOME.

Permissions are restored in fixture teardown, including on failure.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary
from gda.runner import engine_data_path
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# A project whose file logging is at the ENGINE DEFAULT (on for desktop), i.e. what
# a real user project looks like — see the module docstring.
DEFAULT_LOGGING_PROJECT = """\
config_version=5

[application]

config/name="gda-user-data-e2e"
"""

MARKER = "USER-DATA-E2E-OK"

HELLO_GD = f"""\
extends SceneTree

func _initialize() -> void:
\tprint("{MARKER}")
\tquit(0)
"""

# Writes to user:// and reports what it resolved, so the persistence arm can assert
# BOTH that the write landed and where.
PERSIST_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("USER_DIR=", OS.get_user_data_dir())
\tvar f = FileAccess.open("user://probe.txt", FileAccess.WRITE)
\tif f == null:
\t\tprint("WRITE_FAILED")
\t\tquit(1)
\tf.store_string("ok")
\tf.close()
\tprint("WRITE_OK")
\tquit(0)
"""


@pytest.fixture
def restricted_home(tmp_path):
    """A HOME whose Godot application-data directory cannot be written.

    Mirrors the dogfooding profile: the project is writable, the app-data root is
    not. The directory tree is pre-created and only the final component is locked,
    so this is a permission restriction and NOT a bare empty HOME (which perturbs
    the engine's first-run behaviour). The mode is always restored.
    """
    home = tmp_path / "home"
    data_path = engine_data_path({"HOME": str(home)}, platform=sys.platform)
    assert data_path is not None, f"no data path for platform {sys.platform}"
    data_path.mkdir(parents=True)
    data_path.chmod(0o555)
    try:
        yield home, data_path
    finally:
        data_path.chmod(0o755)


@pytest.fixture
def logging_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text(DEFAULT_LOGGING_PROJECT, encoding="utf-8")
    (project / "hello.gd").write_text(HELLO_GD, encoding="utf-8")
    (project / "persist.gd").write_text(PERSIST_GD, encoding="utf-8")
    return project


def _env(home: Path, **extra: str) -> dict:
    """gda's environment for a restricted run.

    ``$GDA_GODOT`` is set explicitly because the binary default is ``~``-relative:
    with HOME redirected it would otherwise resolve inside the fake home.
    """
    return {**os.environ, "HOME": str(home), "GDA_GODOT": str(GODOT), **extra}


def _run_gda(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([*GDA_CMD, *args], capture_output=True, text=True, env=env)


@pytest.mark.e2e
def test_control_unprotected_launch_really_does_die_on_the_restriction(
    restricted_home, logging_project
):
    # The control: the raw engine, without gda's --log-file, must NOT complete.
    # If this ever starts passing, the restriction is not being applied and the
    # protected arms below prove nothing.
    home, _ = restricted_home
    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--path",
            str(logging_project),
            "--script",
            "res://hello.gd",
        ],
        capture_output=True,
        text=True,
        env=_env(home),
    )

    assert MARKER not in proc.stdout, (
        "the engine completed under the restriction, so this profile does not "
        "reproduce the failure: " + proc.stdout + proc.stderr
    )


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["info", "script-validate"])
def test_commands_complete_under_a_read_only_app_data_dir(
    restricted_home, logging_project, command
):
    # AC: the default isolated log target lets a headless command complete where it
    # previously died in the engine's logger. `info` is projectless; `script
    # validate` runs against the project — both go through the same primitive.
    home, _ = restricted_home
    if command == "info":
        args = ["info"]
    else:
        args = [
            "script",
            "validate",
            str(logging_project / "hello.gd"),
            "--project",
            str(logging_project),
        ]

    run = _run_gda(*args, "--json", env=_env(home))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "handle_crash" not in run.stderr
    assert "RotatedFileLogger" not in run.stderr
    payload = json.loads(run.stdout)
    assert "error" not in payload


@pytest.mark.e2e
def test_script_run_completes_under_a_read_only_app_data_dir(
    restricted_home, logging_project
):
    home, _ = restricted_home

    run = _run_gda(
        "script",
        "run",
        "res://hello.gd",
        "--project",
        str(logging_project),
        "--json",
        env=_env(home),
    )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["exit_status"] == 0
    assert MARKER in data["stdout"]
    # The engine crash signature must be gone, not merely reclassified.
    assert "handle_crash" not in data["stderr"]
    assert "Program crashed with signal" not in data["stderr"]


@pytest.mark.e2e
def test_unwritable_log_target_is_a_typed_environment_error(
    restricted_home, logging_project
):
    # When gda's OWN target cannot be created either, the launch is refused with a
    # typed environment code before the engine starts — never a signal-11 backtrace.
    home, data_path = restricted_home

    run = _run_gda(
        "info",
        "--project",
        str(logging_project),
        "--json",
        env=_env(home, GDA_USER_DATA_ROOT=str(data_path / "denied")),
    )

    assert run.returncode == 127, run.stdout + run.stderr
    error = json.loads(run.stdout)["error"]
    assert error["code"] == "user_data_unwritable"
    assert error["category"] == "environment"
    # The diagnostics name the three paths an agent has to act on.
    diagnostics = error["diagnostics"]
    assert str(GODOT) in diagnostics
    assert str(data_path / "denied") in diagnostics
    assert str(data_path / "denied" / "logs" / "godot.log") in diagnostics
    assert "handle_crash" not in diagnostics


@pytest.mark.e2e
def test_user_data_root_makes_user_writable_again(restricted_home, logging_project):
    # The persistence half: user:// is redirectable per invocation, so a script that
    # persists works under the restricted profile too.
    home, _ = restricted_home
    root = logging_project.parent / "udr"

    run = _run_gda(
        "script",
        "run",
        "res://persist.gd",
        "--project",
        str(logging_project),
        "--json",
        env=_env(home, GDA_USER_DATA_ROOT=str(root)),
    )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["exit_status"] == 0, data["stdout"] + data["stderr"]
    assert "WRITE_OK" in data["stdout"]
    # It really resolved under the requested root, not the restricted default.
    assert str(root) in data["stdout"]
    assert (root / "logs" / "godot.log").exists()


@pytest.mark.e2e
def test_concurrent_invocations_do_not_share_a_log_target(logging_project):
    # AC: independent concurrent invocations must not contend over one
    # rotation-sensitive log file. Run unrestricted (the normal profile) so the only
    # thing under test is contention, and use a project with file logging ENABLED —
    # the shape that used to race in rotate_file().
    procs = [
        subprocess.Popen(
            [*GDA_CMD, "info", "--project", str(logging_project), "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "GDA_GODOT": str(GODOT)},
        )
        for _ in range(6)
    ]
    # communicate() before returncode: draining the pipes is what lets each child
    # exit, so waiting first can deadlock on a full pipe buffer.
    results = [(*p.communicate(), p.returncode) for p in procs]

    for out, err, code in results:
        assert code == 0, out + err
        assert "handle_crash" not in err
        assert "error" not in json.loads(out)
