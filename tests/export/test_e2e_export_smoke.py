"""S1 (e2e): `gda export smoke` against a real exported build (ADR-0042, #979).

Every fact this command rests on is the ENGINE's, so the criteria that name
engine behaviour are proved here, against an artifact a real ``gda export run``
produced inside the test: that Godot's own ``--headless`` / ``--log-file`` /
``--quit-after`` reach an exported game, that values after Godot's ``--``
separator arrive in ``OS.get_cmdline_user_args()``, that a normal engine shutdown
prints the exit-time leak record a wall-clock termination never does, and that
the exit status a game chooses comes back as data.

**Bounded to macOS, deliberately.** ADR-0042 measured its facts on a macOS 4.6.3
release template and says the implementation must not claim more than its own
host probes establish, so the artifact half of this module skips off darwin
rather than manufacturing Linux evidence from an untested preset. The
resolution rules, the argv tail and the private-root lifecycle are host-neutral
and are proved engine-free in ``test_export_smoke_operation.py``.

The export needs the release templates for the running engine version; where the
host has none the module skips exactly as the existing export e2e does.
"""

import json
import os
import plistlib
import shutil
import sys
from pathlib import Path

import pytest

from tests.conftest import project_godot
from tests.support import Gda, templates_installed

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "ADR-0042's artifact evidence is macOS-only: the .app resolution and the "
        "release-template export this module runs are the host facts it measured, "
        "and no Linux or Windows behaviour is claimed until probed"
    ),
)

# The project name doubles as the `user://` directory name Godot derives, so it is
# unique to this module: the private-user-data test asserts that the host's REAL
# application-data directory never gains that directory, which a name shared with
# another fixture could not prove.
PROJECT_NAME = "gda-e2e-export-smoke"

# The fixture game, and the only file the artifact carries. One line of stdout per
# run echoes its user args (the `--arg` ordering criterion); one line of stderr
# does the same, because Godot's stdout is block-buffered off a terminal and a run
# gda ENDS at its timeout would lose it — the timeout criterion needs a stream the
# engine flushes, and the error stream is that one.
#
# Three switches, all read from the user args so one export serves every case:
# `exit=<n>` makes the game choose its own status, `leak` allocates an Object it
# never frees (so the engine reports a leak at exit, the second --strict trigger
# and GDA-DF-072's shape), and `write=<name>` writes a file under `user://` for the
# private-root criterion. Without `exit=` the game never ends by itself, which is
# what makes `--quit-after` and `--timeout` separable.
MAIN_GD = """\
extends Node


func _ready() -> void:
\tvar args := OS.get_cmdline_user_args()
\tprint("ARGS:", "|".join(args))
\tprinterr("SMOKE-ALIVE:", "|".join(args))
\tvar code := -1
\tfor a in args:
\t\tif a.begins_with("exit="):
\t\t\tcode = int(a.split("=")[1])
\t\tif a == "leak":
\t\t\tvar orphan := Object.new()
\t\t\torphan.set_meta("kept", 1)
\t\tif a.begins_with("write="):
\t\t\tvar f := FileAccess.open("user://" + a.split("=")[1], FileAccess.WRITE)
\t\t\tif f != null:
\t\t\t\tf.store_string("written")
\t\t\t\tf.close()
\tif code >= 0:
\t\tget_tree().quit(code)
"""

MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Node"]\n'
    'script = ExtResource("1")\n'
)

# A macOS release preset. `import_etc2_astc` is not decoration: without it the
# engine refuses a universal/arm64 macOS export outright ("cannot export ... when
# ETC2 ASTC texture format is disabled"), so the preset and the project setting
# are one fixture.
EXPORT_PRESETS_CFG = """\
[preset.0]

name="macOS"
platform="macOS"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/SmokeFixture.app"
encryption_include_filters=""
encryption_exclude_filters=""
seed=0
encrypt_pck=false
encrypt_directory=false
script_export_mode=2

[preset.0.options]

export/distribution_type=1
binary/architecture="universal"
application/icon=""
application/bundle_identifier="com.example.gdasmokefixture"
application/signature=""
application/copyright=""
codesign/codesign=0
notarization/notarization=0
"""


def _host_user_data_dir(project_name: str) -> Path:
    """Where Godot resolves ``user://`` for ``project_name`` on this REAL host."""
    return (
        Path(os.path.expanduser("~"))
        / "Library"
        / "Application Support"
        / "Godot"
        / "app_userdata"
        / project_name
    )


@pytest.fixture(scope="module")
def exported_app(tmp_path_factory):
    """One real ``export run`` artifact, shared by the whole module.

    A release export takes seconds and every test here needs the SAME artifact, so
    it is built once. It is a genuine `Export artifact`: produced by `gda export
    run` from a project written here, never checked in.
    """
    project = tmp_path_factory.mktemp("smoke-project")
    (project / "project.godot").write_text(
        project_godot(
            PROJECT_NAME,
            extra=(
                'run/main_scene="res://main.tscn"\n\n'
                "[rendering]\n\n"
                "textures/vram_compression/import_etc2_astc=true"
            ),
        ),
        encoding="utf-8",
    )
    (project / "main.gd").write_text(MAIN_GD, encoding="utf-8")
    (project / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (project / "export_presets.cfg").write_text(EXPORT_PRESETS_CFG, encoding="utf-8")

    gda = Gda(project)
    if not templates_installed(gda, preset="macOS"):
        pytest.skip(
            "export templates for the running engine version are not installed; "
            "the artifact this module smokes cannot be built (the same "
            "template-presence policy the export-run e2e observes)"
        )
    exported = gda.json("export", "run", "--preset", "macOS", timeout=300.0)
    artifact = Path(exported["output_path"])
    assert artifact.is_dir(), f"no .app bundle at {artifact}"
    yield artifact
    shutil.rmtree(project, ignore_errors=True)
    # The EXPORT — an editor run, not redirected — creates the host's user:// dir
    # for this project name. It is this module's own (the name is unique to it), so
    # it is removed rather than left behind on the developer's machine.
    shutil.rmtree(_host_user_data_dir(PROJECT_NAME), ignore_errors=True)


@pytest.fixture
def smoke():
    """The projectless ``gda`` invoker this command needs.

    No ``--project`` and no ``--godot``: the command declares neither, because the
    artifact is a caller-selected path and the engine it runs is the artifact's
    own.
    """
    return Gda(project=None, godot=None)


def _timeout_envelope(proc, ceiling: float) -> dict:
    """Assert ``proc`` is this channel's ``launch_timeout`` and return its error.

    Not :meth:`Gda.error`, which spells the ADR-0002 OPERATION contract: a timeout
    is the ENVIRONMENT-category `launch_timeout` at exit 124, shared with every
    other launch-backed channel and distinguished only by the label it names.
    """
    assert proc.returncode == 124, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "launch_timeout", error
    assert error["category"] == "environment"
    assert error["message"].startswith("Godot artifact smoke launched but did not")
    assert f"timeout of {ceiling}s" in error["message"]
    return error


# --- The real round trip -----------------------------------------------------


@pytest.mark.e2e
def test_a_real_export_run_artifact_runs_and_reports_both_paths(exported_app, smoke):
    # ADR-0042's first validation requirement: feed the `output_path` of a real
    # `export run` to `export smoke`. The bundle resolution is part of the claim —
    # the caller names the `.app`, gda names the executable it found inside it.
    result = smoke.json("export", "smoke", str(exported_app), "--arg", "exit=0")

    assert result["artifact"] == str(exported_app)
    with (exported_app / "Contents" / "Info.plist").open("rb") as handle:
        declared = plistlib.load(handle)["CFBundleExecutable"]
    assert result["executable"] == str(exported_app / "Contents" / "MacOS" / declared)
    assert result["exit_status"] == 0
    assert result["stdout_truncated"] is False
    assert result["stdout_file"] is None


@pytest.mark.e2e
def test_ordered_arg_values_reach_the_exported_game(exported_app, smoke):
    # After Godot's `--` separator, in order, read back with
    # OS.get_cmdline_user_args() — the engine fact the whole `--arg` option rests on.
    result = smoke.json(
        "export",
        "smoke",
        str(exported_app),
        "--arg",
        "alpha",
        "--arg",
        "beta",
        "--arg",
        "exit=0",
    )

    assert "ARGS:alpha|beta|exit=0" in result["stdout"]


@pytest.mark.e2e
def test_quit_after_ends_the_game_normally_and_surfaces_the_exit_time_leak(
    exported_app, smoke
):
    # The condition ADR-0042's follow-up probe found: the game does not end by
    # itself here, `--quit-after` makes the engine end its main loop normally, and
    # the normal shutdown is what prints the leak record. Exit status 0 — the engine
    # ended the loop, nothing failed — with the leak reported as a diagnostic.
    result = smoke.json(
        "export", "smoke", str(exported_app), "--quit-after", "30", "--arg", "leak"
    )

    assert result["exit_status"] == 0
    assert [d["kind"] for d in result["diagnostics"]] == ["shutdown_leak"]
    assert "leaked at exit" in result["stderr"]


@pytest.mark.e2e
@pytest.mark.parametrize("frames", ["0", None], ids=["zero", "omitted"])
def test_an_omitted_or_zero_quit_after_leaves_the_game_running(
    exported_app, smoke, frames
):
    # The negative half of the criterion: with no engine-owned exit the same game
    # runs until gda's own ceiling. That is what makes the test above evidence about
    # `--quit-after` rather than about the game.
    argv = ["export", "smoke", str(exported_app), "--timeout", "6", "--json"]
    if frames is not None:
        argv += ["--quit-after", frames]

    _timeout_envelope(smoke(*argv, timeout=60.0), 6.0)


@pytest.mark.e2e
def test_a_timeout_preserves_what_the_run_had_already_produced(exported_app, smoke):
    # A run gda ENDS keeps the partial capture (#655/#714) and claims nothing about
    # a normal cleanup: the assertion is on what the game FLUSHED, never on the
    # shutdown-only diagnostics this path does not reach.
    error = _timeout_envelope(
        smoke(
            "export",
            "smoke",
            str(exported_app),
            "--timeout",
            "6",
            "--arg",
            "waiting",
            "--json",
            timeout=60.0,
        ),
        6.0,
    )

    assert "SMOKE-ALIVE:waiting" in error["diagnostics"]
    assert error["evidence"]["timeout_seconds"] == 6.0
    assert error["evidence"]["termination_phase"] == "output_seen"


# --- Exit status: data by default, a verdict under --strict ------------------


@pytest.mark.e2e
def test_a_non_zero_exit_is_returned_as_data(exported_app, smoke):
    # gda does not interpret what the game meant by its status, so gda itself exits
    # 0 and the number is a field the agent reads.
    proc = smoke("export", "smoke", str(exported_app), "--arg", "exit=3", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["exit_status"] == 3


@pytest.mark.e2e
def test_strict_maps_a_non_zero_exit_to_smoke_failed(exported_app, smoke):
    error = smoke.error(
        "export",
        "smoke",
        str(exported_app),
        "--strict",
        "--arg",
        "exit=3",
        code="smoke_failed",
    )

    assert error["evidence"]["exit_status"] == 3
    assert error["evidence"]["script_errors"] == []
    assert "--- artifact stdout ---" in error["diagnostics"]
    assert "ARGS:exit=3" in error["diagnostics"]


@pytest.mark.e2e
def test_strict_maps_a_zero_exit_that_leaked_to_smoke_failed(exported_app, smoke):
    # The trigger a status-only gate cannot see, and the reason this command exists:
    # GDA-DF-072's build exited cleanly and still left resources alive.
    error = smoke.error(
        "export",
        "smoke",
        str(exported_app),
        "--quit-after",
        "30",
        "--arg",
        "leak",
        "--strict",
        code="smoke_failed",
    )

    assert error["evidence"]["exit_status"] == 0
    assert [e["kind"] for e in error["evidence"]["script_errors"]] == ["shutdown_leak"]


# --- Projectless -------------------------------------------------------------


@pytest.mark.e2e
def test_the_command_ignores_the_cwd_and_gda_project(exported_app, smoke, tmp_path):
    # Invoked from inside a directory that is NOT a project, with a $GDA_PROJECT
    # that names nothing — either of which is `project_not_found` for a domain
    # command. Neither is read here, and a relative artifact path means what the
    # shell would mean by it.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    relative = os.path.relpath(exported_app, elsewhere)

    result = smoke.json(
        "export",
        "smoke",
        relative,
        "--arg",
        "exit=0",
        cwd=elsewhere,
        extra_env={"GDA_PROJECT": str(tmp_path / "not-a-project")},
    )

    assert result["artifact"] == str(elsewhere / relative)
    assert result["exit_status"] == 0


@pytest.mark.e2e
def test_project_is_refused_as_an_unknown_option(exported_app, smoke, tmp_path):
    proc = smoke(
        "export", "smoke", str(exported_app), "--project", str(tmp_path), "--json"
    )

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["error"]["code"] == "unknown_option"


# --- The private user:// root ------------------------------------------------


@pytest.mark.e2e
def test_the_default_run_writes_a_private_user_dir_and_removes_it(
    exported_app, smoke, tmp_path
):
    # Two halves of one promise (ADR-0042): the exported game's `user://` write
    # lands somewhere gda owns — never the host's real application-data directory —
    # and the directory gda made for it is gone when the command returns. TMPDIR is
    # redirected for this one invocation so the private root's removal is observable
    # rather than inferred.
    private_tmp = tmp_path / "tmp"
    private_tmp.mkdir()
    # The host's directory for this project name may already EXIST: the export that
    # built the artifact is an editor run under no redirect, and the engine creates
    # `app_userdata/<config name>` whenever it resolves `user://` at all. What must
    # not appear in it is the file the smoked GAME writes — which is the claim.
    written_on_the_host = _host_user_data_dir(PROJECT_NAME) / "smoke.txt"
    assert not written_on_the_host.exists()

    result = smoke.json(
        "export",
        "smoke",
        str(exported_app),
        "--arg",
        "write=smoke.txt",
        "--arg",
        "exit=0",
        extra_env={"TMPDIR": str(private_tmp)},
    )

    assert result["exit_status"] == 0
    assert not written_on_the_host.exists(), (
        "the smoked game wrote the host's real user:// directory"
    )
    assert list(private_tmp.iterdir()) == [], (
        "the private user-data root outlived the command"
    )


@pytest.mark.e2e
def test_an_explicit_user_data_root_is_used_and_is_not_removed(
    exported_app, smoke, tmp_path
):
    # An override is CALLER-owned: the game's `user://` write lands under it, and
    # gda removes nothing. The global option precedes the subcommand.
    root = tmp_path / "kept"

    result = smoke.json(
        "--user-data-root",
        str(root),
        "export",
        "smoke",
        str(exported_app),
        "--arg",
        "write=smoke.txt",
        "--arg",
        "exit=0",
    )

    assert result["exit_status"] == 0
    assert root.is_dir(), "an explicit root is the caller's and must survive"
    written = list(root.rglob("smoke.txt"))
    assert written, f"the game's user:// write did not land under {root}"
    # The placement stays internal: the result names neither the root nor the log.
    assert not ({"user_data_root", "log_file", "engine_data_path"} & set(result))


# --- The two artifact refusals, against real paths ---------------------------


@pytest.mark.e2e
def test_an_absent_artifact_is_not_found(smoke, tmp_path):
    smoke.error(
        "export",
        "smoke",
        str(tmp_path / "never-exported.app"),
        code="export_artifact_not_found",
    )


@pytest.mark.e2e
def test_a_bundle_without_its_declared_executable_is_not_runnable(
    exported_app, smoke, tmp_path
):
    # A REAL bundle with the one file removed, so the refusal is measured against
    # the layout Godot actually writes rather than against a hand-built imitation.
    broken = tmp_path / "Broken.app"
    shutil.copytree(exported_app, broken, symlinks=True)
    with (broken / "Contents" / "Info.plist").open("rb") as handle:
        declared = plistlib.load(handle)["CFBundleExecutable"]
    (broken / "Contents" / "MacOS" / declared).unlink()

    error = smoke.error(
        "export", "smoke", str(broken), code="export_artifact_not_runnable"
    )

    assert "CFBundleExecutable" in error["message"]
