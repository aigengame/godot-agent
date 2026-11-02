"""e2e: a launch with no project does not start Godot's Project Manager (#1266).

A command that inherits no project and gets no ``--project`` (``gda project create``,
``gda info``) runs the engine on a private project whose ``project.godot`` is empty
(#1035, #1266). For a ``--script`` run that finds no ``project.godot``, Godot starts
its Project Manager (``main/main.cpp``, 4.6.3), which reads the user's project list,
loads the icon of each listed project, and writes the editor settings.

The fixture points the platform data, config and cache locations at a temporary
profile whose project list names a project with a missing icon. A Project Manager
run under it prints the icon error and writes ``editor_settings-*.tres`` into the
profile. The control runs the raw engine in an empty directory under the same
profile, as gda launched it before #1266, and must find both. Without the control,
the gda arms could pass because the fixture does not reach the Project Manager on
this platform.

The child environment does not hold ``GDA_USER_DATA_ROOT``: that variable moves the
data directory away from the profile, and the gda arms then pass without the fix.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import GODOT, Gda

ICON_ERROR = "Error opening file"

# Quits after a few frames, so that the Project Manager loads the listed icon: it
# loads one icon per process frame (editor/project_manager/project_list.cpp).
QUIT_GD = """\
extends SceneTree

var _frames := 0


func _process(_delta: float) -> bool:
\t_frames += 1
\treturn _frames >= 10
"""


def _profile_env(root: Path) -> tuple[dict[str, str], Path]:
    """The variables that put Godot's data, config and cache under ``root``, and the
    Godot data directory they give (``OS::get_data_path`` and ``get_godot_dir_name``
    of each platform, 4.6.3)."""
    if sys.platform == "win32":
        return (
            {"APPDATA": str(root / "Roaming"), "LOCALAPPDATA": str(root / "Local")},
            root / "Roaming" / "Godot",
        )
    if sys.platform == "darwin":
        return {"HOME": str(root)}, root / "Library" / "Application Support" / "Godot"
    return (
        {
            "HOME": str(root),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
        },
        root / "data" / "godot",
    )


@pytest.fixture
def profile(tmp_path):
    """The child environment, the profile root, and the icon path the list names."""
    listed = tmp_path / "listed"
    listed.mkdir()
    (listed / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="listed"\n'
        'config/icon="res://missing/icon.svg"\n',
        encoding="utf-8",
    )
    root = tmp_path / "profile"
    overrides, data_dir = _profile_env(root)
    data_dir.mkdir(parents=True)
    (data_dir / "projects.cfg").write_text(
        f"[{listed.as_posix()}]\n\nfavorite=false\n", encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if k != "GDA_USER_DATA_ROOT"}
    return {**env, **overrides}, root, f"{listed.as_posix()}/missing/icon.svg"


def _editor_settings(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob("editor_settings-*.tres"))


@pytest.mark.e2e
def test_control_a_run_in_an_empty_directory_reads_the_profile(profile, tmp_path):
    env, root, icon = profile
    empty = tmp_path / "empty"
    empty.mkdir()
    script = tmp_path / "quit.gd"
    script.write_text(QUIT_GD, encoding="utf-8")

    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--log-file",
            str(tmp_path / "control.log"),
            "--path",
            str(empty),
            "--script",
            str(script),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    errors = [line for line in proc.stderr.splitlines() if ICON_ERROR in line]
    assert errors == [f"ERROR: {ICON_ERROR} '{icon}'."], proc.stderr
    settings = _editor_settings(root)
    assert len(settings) == 1, settings


@pytest.mark.e2e
@pytest.mark.parametrize(
    "argv",
    [("project", "create", "game", "--name", "Game"), ("info",)],
    ids=["project-create", "info"],
)
def test_a_projectless_command_does_not_start_the_project_manager(
    profile, tmp_path, argv
):
    env, root, _ = profile

    proc = Gda(env=env)(*argv, "--json", cwd=tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ICON_ERROR not in proc.stdout + proc.stderr
    assert _editor_settings(root) == []


@pytest.mark.e2e
def test_a_refused_project_create_carries_no_project_manager_line(profile, tmp_path):
    env, root, _ = profile
    destination = tmp_path / "game"
    destination.mkdir()
    (destination / "project.godot").write_text("", encoding="utf-8")

    err = Gda(env=env).error(
        "project", "create", str(destination), "--name", "Game", code="already_exists"
    )

    assert ICON_ERROR not in err.get("diagnostics", "")
    assert _editor_settings(root) == []
