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

**A PROJECT is required to reproduce the crash — ``gda info`` cannot.** The issue
lists ``info`` among the commands that died, but that does not reproduce on Godot
4.6.3 and there is no arm for it here. ``info`` is projectless, and ``Main::setup``
builds the file logger only when ``!project_manager && !editor && …``; a projectless
run takes the project-manager branch, so no ``RotatedFileLogger`` is ever
constructed and there is nothing to crash. Verified directly: the projectless
sentinel op under the restriction emits its result with zero ``handle_crash`` lines,
with and without the fix. ``info`` is still covered here for the *refusal* path,
which does apply to it: gda creates a log target for every launch, projectless
included.

Permissions are restored in fixture teardown, including on failure.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gda.runner import data_path_env, engine_data_path
from tests.support import GDA_CMD, GODOT, Gda

# A project whose file logging is at the ENGINE DEFAULT (on for desktop), i.e. what
# a real user project looks like — see the module docstring.
DEFAULT_LOGGING_PROJECT = """\
config_version=5

[application]

config/name="gda-user-data-e2e"
"""

MARKER = "USER-DATA-E2E-OK"

# A pack-mode preset: `--mode pack` produces project data only, so the export-channel
# arm below needs no installed export templates and runs on any machine.
EXPORT_PRESETS_CFG = """\
[preset.0]

name="Linux/X11"
platform="Linux/X11"
runnable=true
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/game.x86_64"

[preset.0.options]

binary_format/embed_pck=false
"""

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
def writable_home(tmp_path):
    """A WRITABLE fake HOME, so a run's resolved ``user://`` can be inspected.

    The normal-profile twin of :func:`restricted_home`: it isolates the assertion
    from the developer's real application-data directory without restricting
    anything, so a test can assert what the engine did and did not create there.
    """
    home = tmp_path / "writable-home"
    data_path = engine_data_path({"HOME": str(home)}, platform=sys.platform)
    assert data_path is not None, f"no data path for platform {sys.platform}"
    data_path.mkdir(parents=True)
    return home, data_path


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
        timeout=120,
    )

    assert MARKER not in proc.stdout, (
        "the engine completed under the restriction, so this profile does not "
        "reproduce the failure: " + proc.stdout + proc.stderr
    )


@pytest.mark.e2e
def test_script_validate_completes_under_a_read_only_app_data_dir(
    restricted_home, logging_project
):
    # AC: the default isolated log target lets a project-backed headless command
    # complete where it previously died in the engine's logger. Project-backed is
    # the load-bearing word — see the module docstring on why `info` cannot be an
    # arm here. Red-proof: the control arm above pins that this same project and
    # restriction really do kill an unprotected launch.
    home, _ = restricted_home

    run = Gda(godot=None, env=_env(home))(
        "script",
        "validate",
        str(logging_project / "hello.gd"),
        "--project",
        str(logging_project),
        "--json",
    )

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

    run = Gda(godot=None, env=_env(home))(
        "script",
        "run",
        "res://hello.gd",
        "--project",
        str(logging_project),
        "--json",
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

    run = Gda(godot=None, env=_env(home, GDA_USER_DATA_ROOT=str(data_path / "denied")))(
        "info",
        "--json",
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
def test_a_root_whose_derived_data_path_is_blocked_is_refused(
    tmp_path, logging_project
):
    # Creating the root and the log target is not enough to keep the `user://`
    # promise: the engine appends a platform layout to the root, and that DERIVED
    # path can be unusable while the root and its `logs/` are perfectly writable.
    #
    # Before the derived-path probe this was the worst possible outcome — a
    # SUCCESSFUL result. gda preflighted only the log, the engine printed "Could not
    # create directory" to stderr and still exited 0, and the script ran with an
    # unopenable `user://` while `script run` reported exit_status 0. So this arm
    # asserts BOTH the typed refusal and that the project never executed.
    root = tmp_path / "udr"
    derived = engine_data_path(data_path_env(root), platform=sys.platform)
    assert derived is not None
    if derived == root:
        pytest.skip(
            "flat user-data shape (XDG): the derived path IS the root, so it "
            "cannot be blocked while the root stays writable — the nested-shape "
            "refusal is exercised ungated by the unit tier"
        )
    # Block the derived path with a regular FILE at its first component under root.
    blocker = derived
    while blocker.parent != root and blocker.parent != blocker:
        blocker = blocker.parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory", encoding="utf-8")

    run = Gda(godot=None, env={**os.environ, "GDA_GODOT": str(GODOT)})(
        "--user-data-root",
        str(root),
        "script",
        "run",
        "res://persist.gd",
        "--project",
        str(logging_project),
        "--json",
    )

    assert run.returncode == 127, run.stdout + run.stderr
    error = json.loads(run.stdout)["error"]
    assert error["code"] == "user_data_unwritable"
    assert error["category"] == "environment"
    # The diagnostics name the DERIVED path — the one to fix — not just the root.
    assert str(derived) in error["diagnostics"]
    # The project never ran: no engine banner, no script output, no false success.
    assert "USER_DIR=" not in run.stdout
    assert "WRITE_FAILED" not in run.stdout
    assert "exit_status" not in run.stdout


@pytest.mark.e2e
def test_user_data_root_makes_user_writable_again(restricted_home, logging_project):
    # The persistence half: user:// is redirectable per invocation, so a script that
    # persists works under the restricted profile too.
    #
    # Driven through the FLAG rather than the env twin (review finding F2), so the
    # real-engine tier exercises the CLI hand-over too, not only the env path that
    # bypasses it.
    home, _ = restricted_home
    root = logging_project.parent / "udr"

    run = Gda(godot=None, env=_env(home))(
        "--user-data-root",
        str(root),
        "script",
        "run",
        "res://persist.gd",
        "--project",
        str(logging_project),
        "--json",
    )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["exit_status"] == 0, data["stdout"] + data["stderr"]
    assert "WRITE_OK" in data["stdout"]
    # It really resolved under the requested root, not the restricted default.
    assert str(root) in data["stdout"]
    assert (root / "logs" / "godot.log").exists()


@pytest.mark.e2e
def test_concurrent_invocations_never_touch_the_shared_rotated_log(
    writable_home, logging_project
):
    # AC: independent concurrent invocations must not contend over one
    # rotation-sensitive log file. The assertion that carries the weight is the
    # NEGATIVE one: the engine's shared `user://logs/` for this project is never
    # created at all, so there is no shared target left to rotate or race on. Six
    # successes alone would prove nothing — they pass just as well while every run
    # writes the same file.
    #
    # A writable fake HOME (not the restricted one) so the run is the NORMAL
    # profile and the resolved user:// dir can be inspected deterministically
    # without touching the developer's real one. File logging is at the engine
    # default here — the exact shape that used to race in rotate_file().
    home, data_path = writable_home

    procs = [
        subprocess.Popen(
            [
                *GDA_CMD,
                "script",
                "validate",
                str(logging_project / "hello.gd"),
                "--project",
                str(logging_project),
                "--json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_env(home),
        )
        for _ in range(6)
    ]
    # communicate() before returncode: draining the pipes is what lets each child
    # exit, so waiting first can deadlock on a full pipe buffer.
    results = [(*p.communicate(timeout=120), p.returncode) for p in procs]

    for out, err, code in results:
        assert code == 0, out + err
        assert "handle_crash" not in err
        assert "error" not in json.loads(out)

    # The engine DID resolve user:// (it creates app_userdata eagerly), but no
    # rotated log directory may appear anywhere beneath the data path. Globbed
    # rather than spelled out, because the layout below the data path differs per
    # platform (`Godot/app_userdata/…` vs `godot/app_userdata/…`).
    shared_logs = list(data_path.rglob("logs"))
    assert not shared_logs, (
        f"a shared user://logs was created, so concurrent runs still contend: "
        f"{shared_logs}"
    )


# --------------------------------------------------------------------------
# A relative --user-data-root (review finding F1)
# --------------------------------------------------------------------------


@pytest.mark.e2e
def test_relative_root_on_the_sentinel_channel_lands_under_gda_cwd(
    tmp_path, logging_project
):
    # gda and the engine do not share a working directory: gda would create the log
    # relative to its own cwd while the engine resolved the relative --log-file
    # against --path. The preflight then passed for a file the engine never opened
    # and the engine died in rotate_file() on the one it did — the very crash this
    # change removes, reintroduced by a relative path.
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    run = Gda(godot=None, env={**os.environ, "GDA_GODOT": str(GODOT)}, cwd=workdir)(
        "--user-data-root",
        "./rel",
        "script",
        "validate",
        str(logging_project / "hello.gd"),
        "--project",
        str(logging_project),
        "--json",
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert "handle_crash" not in run.stderr
    assert json.loads(run.stdout)["valid"] is True
    # Resolved against gda's cwd, exactly once...
    assert (workdir / "rel" / "logs" / "godot.log").exists()
    # ...and NOT leaked into the project the engine was pointed at.
    assert not (logging_project / "rel").exists()


@pytest.mark.e2e
def test_relative_root_on_the_export_channel_lands_under_gda_cwd(
    tmp_path, logging_project
):
    # The export channel is the sharper case: it spawns with cwd = <project>, so a
    # relative --log-file resolves there for certain. `--mode pack` needs no export
    # templates, so this runs on any machine.
    (logging_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    workdir = tmp_path / "workdir-export"
    workdir.mkdir()
    artifact = logging_project / "dist" / "packed.pck"

    run = Gda(godot=None, env={**os.environ, "GDA_GODOT": str(GODOT)}, cwd=workdir)(
        "--user-data-root",
        "./rel",
        "export",
        "run",
        "--preset",
        "Linux/X11",
        "--mode",
        "pack",
        "--output",
        str(artifact),
        "--project",
        str(logging_project),
        "--json",
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert "handle_crash" not in run.stderr
    assert artifact.exists()
    assert (workdir / "rel" / "logs" / "godot.log").exists()
    assert not (logging_project / "rel").exists()
