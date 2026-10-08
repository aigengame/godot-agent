"""E2E: ``gda project create`` against the real Godot engine (issue #1027).

AC1: a request creates the minimal project and reports ``path``, ``name``,
``created_dirs`` and ``project_file``. AC2: each refusal is its ``Error envelope``
on both input channels, modifies nothing that existed, and leaves nothing the
request created. AC3: a run from inside another project, with ``$GDA_PROJECT``
naming it, neither boots that project nor copies its settings (the #1035 launch).
AC5: a headless tracer from creation to a started main scene.
"""

import json
from pathlib import Path

import pytest

from gda.core.project.paths import ENGINE_VIRTUAL_PREFIXES
from gda.core.project.project_file import read_config_text
from tests.conftest import project_godot
from tests.support import Gda, unlistable, unwritable

gda = Gda()

# The keys every created project.godot holds, and nothing else: the name, plus
# what the engine writes on every save (#1027, "What to build").
DEFINED_KEYS = {
    "config_version",
    "application/config/name",
    "application/config/features",
}

# An autoload that leaves this mark on both streams when its project boots.
AUTOLOAD_MARK = "GDA-1027-OUTER-AUTOLOAD-RAN"
AUTOLOAD_GD = f"""extends Node


func _init() -> void:
\tprint("{AUTOLOAD_MARK}")
\tprinterr("{AUTOLOAD_MARK}")
"""

# The two input channels every refusal must answer alike (ADR-0015).
CHANNELS = ["argv", "params-json"]


def _create(destination: str, name: str, channel: str, **overrides):
    """Run ``gda project create`` through ``channel``; return the finished process."""
    if channel == "argv":
        return gda(
            "project", "create", destination, "--name", name, "--json", **overrides
        )
    params = json.dumps({"destination": destination, "name": name})
    return gda("project", "create", "--params-json", params, "--json", **overrides)


def _settings(project_file: Path) -> dict[str, str]:
    """The written keys of ``project_file``, by setting name, with their value text."""
    config = read_config_text(project_file.read_text(encoding="utf-8"))
    return {name: entry.value for name, entry in config.settings().items()}


def _engine_version_feature() -> str:
    info = gda.json("info")
    return f'"{info["major"]}.{info["minor"]}"'


def _snapshot(root: Path) -> dict[str, tuple]:
    """Every entry under ``root``: its kind, and a file's bytes and mtime."""
    entries: dict[str, tuple] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            entries[relative] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
        else:
            entries[relative] = ("dir",)
    return entries


def _assert_minimal_project(result: dict, destination: Path, name: str) -> None:
    project_file = destination / "project.godot"
    assert result["path"] == str(destination)
    assert result["name"] == name
    assert Path(result["project_file"]) == project_file
    settings = _settings(project_file)
    assert set(settings) == DEFINED_KEYS, settings
    assert settings["config_version"] == "5"
    assert settings["application/config/name"] == json.dumps(name)
    assert _engine_version_feature() in settings["application/config/features"]


# --- AC1 ------------------------------------------------------------------


@pytest.mark.e2e
def test_create_makes_the_destination_and_a_minimal_project(tmp_path):
    destination = tmp_path / "game"

    result = gda.json("project", "create", str(destination), "--name", "  My Game  ")

    # The name is stripped, then persisted and reported (Decisions: Name).
    _assert_minimal_project(result, destination, "My Game")
    assert result["created_dirs"] == [str(destination)]
    assert sorted(p.name for p in destination.iterdir()) == ["project.godot"]


@pytest.mark.e2e
def test_create_accepts_a_directory_that_holds_only_dot_entries(tmp_path):
    # A directory after `git init` is empty for this rule (Project Manager
    # precedent); it existed, so the request created no directory.
    destination = tmp_path / "repo"
    (destination / ".git").mkdir(parents=True)
    (destination / ".gitignore").write_text(".godot/\n", encoding="utf-8")
    before = _snapshot(destination)

    result = gda.json("project", "create", str(destination), "--name", "Repo")

    _assert_minimal_project(result, destination, "Repo")
    assert result["created_dirs"] == []
    after = _snapshot(destination)
    assert after.pop("project.godot")[0] == "file"
    assert after == before


@pytest.mark.e2e
def test_a_relative_destination_resolves_against_the_working_directory(tmp_path):
    result = gda.json("project", "create", "game", "--name", "Relative", cwd=tmp_path)

    _assert_minimal_project(result, tmp_path / "game", "Relative")


# --- AC2 ------------------------------------------------------------------


def _assert_refused(proc, code: str) -> None:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    envelope = json.loads(proc.stdout)
    assert set(envelope) == {"error"}, envelope
    assert envelope["error"]["code"] == code, envelope
    assert envelope["error"]["category"] == "operation"


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_destination_that_holds_a_project_is_already_exists(tmp_path, channel):
    # Checked before the emptiness rule: the other entry would also refuse it.
    destination = tmp_path / "game"
    destination.mkdir()
    (destination / "project.godot").write_text(
        project_godot(name="old"), encoding="utf-8"
    )
    (destination / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    before = _snapshot(tmp_path)

    _assert_refused(_create(str(destination), "New", channel), "already_exists")
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_nonempty_destination_is_destination_not_empty(tmp_path, channel):
    destination = tmp_path / "work"
    (destination / ".git").mkdir(parents=True)
    (destination / "notes.txt").write_text("keep\n", encoding="utf-8")
    before = _snapshot(tmp_path)

    _assert_refused(_create(str(destination), "New", channel), "destination_not_empty")
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_file_at_the_destination_is_invalid_path(tmp_path, channel):
    destination = tmp_path / "game"
    destination.write_text("not a directory\n", encoding="utf-8")
    before = _snapshot(tmp_path)

    _assert_refused(_create(str(destination), "New", channel), "invalid_path")
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_missing_parent_is_invalid_path_and_nothing_is_created(tmp_path, channel):
    before = _snapshot(tmp_path)

    proc = _create(str(tmp_path / "missing" / "game"), "New", channel)

    _assert_refused(proc, "invalid_path")
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
# The cases come from the Python constant, so this test also holds the op's own
# spelling of the schemes (PROJECT_CREATE_VIRTUAL_PREFIXES) to it.
@pytest.mark.parametrize(
    "destination", [prefix + "game" for prefix in ENGINE_VIRTUAL_PREFIXES]
)
def test_a_virtual_destination_is_invalid_path(tmp_path, channel, destination):
    before = _snapshot(tmp_path)

    proc = _create(destination, "New", channel, cwd=tmp_path)
    _assert_refused(proc, "invalid_path")
    # The code alone does not show the branch: an unlisted `uid://` falls through to
    # the missing-parent refusal, which is invalid_path too.
    assert "engine-virtual" in json.loads(proc.stdout)["error"]["message"]
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_an_empty_name_is_invalid_params_and_nothing_is_created(tmp_path, channel):
    before = _snapshot(tmp_path)

    _assert_refused(_create(str(tmp_path / "game"), " \t ", channel), "invalid_params")
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_name_that_does_not_read_back_is_save_failed_and_rolled_back(
    tmp_path, channel
):
    # The engine's parser drops a leading U+FEFF from a string value
    # (String::append_utf8 skips a BOM), so this name is written but reads back
    # without it. The request created the directory and the file; it removes both.
    before = _snapshot(tmp_path)

    proc = _create(str(tmp_path / "game"), "﻿Game", channel)

    _assert_refused(proc, "save_failed")
    assert "did not read back" in json.loads(proc.stdout)["error"]["message"]
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_name_that_does_not_read_back_leaves_an_existing_destination_as_it_was(
    tmp_path, channel
):
    # Rollback removes only what this request created: the file, not the
    # directory that existed before it.
    destination = tmp_path / "repo"
    (destination / ".git").mkdir(parents=True)
    before = _snapshot(tmp_path)

    _assert_refused(_create(str(destination), "﻿Game", channel), "save_failed")
    assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_directory_that_cannot_be_created_is_save_failed(tmp_path, channel):
    parent = tmp_path / "locked"
    parent.mkdir()
    with unwritable(parent) as restricted:
        if not restricted:
            pytest.skip("this host does not enforce the directory write restriction")
        before = _snapshot(tmp_path)

        _assert_refused(_create(str(parent / "game"), "New", channel), "save_failed")
        assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_file_that_cannot_be_written_is_save_failed(tmp_path, channel):
    destination = tmp_path / "locked"
    destination.mkdir()
    with unwritable(destination) as restricted:
        if not restricted:
            pytest.skip("this host does not enforce the directory write restriction")
        before = _snapshot(tmp_path)

        _assert_refused(_create(str(destination), "New", channel), "save_failed")
        assert _snapshot(tmp_path) == before


@pytest.mark.e2e
@pytest.mark.parametrize("channel", CHANNELS)
def test_a_destination_that_cannot_be_listed_is_invalid_path(tmp_path, channel):
    # The emptiness rule cannot be applied to a directory whose entries cannot be
    # read, so the request is refused before it writes into it.
    destination = tmp_path / "unlistable"
    destination.mkdir()
    (destination / "notes.txt").write_text("keep\n", encoding="utf-8")
    before = _snapshot(tmp_path)
    with unlistable(destination) as restricted:
        if not restricted:
            pytest.skip("this host does not enforce the directory list restriction")

        proc = _create(str(destination), "New", channel)

    _assert_refused(proc, "invalid_path")
    assert _snapshot(tmp_path) == before


# --- AC3 ------------------------------------------------------------------


def _outer_project(directory: Path) -> Path:
    """A project with a distinguishing setting and an autoload that marks the streams."""
    directory.mkdir()
    (directory / "project.godot").write_text(
        project_godot(
            name="outer",
            extra=(
                "[autoload]\n\n"
                'Marker="*res://marker.gd"\n\n'
                "[display]\n\n"
                "window/size/viewport_width=777\n"
            ),
        ),
        encoding="utf-8",
    )
    (directory / "marker.gd").write_text(AUTOLOAD_GD, encoding="utf-8")
    return directory


@pytest.mark.e2e
def test_create_inside_another_project_neither_boots_nor_copies_it(tmp_path):
    # The working directory is another project and $GDA_PROJECT names it. The
    # engine must load neither (#1035): the autoload mark is absent from both
    # streams and the engine log, the new file holds only the defined keys, and
    # no file of the outer project changes. The destination inside it is accepted.
    outer = _outer_project(tmp_path / "outer")
    root = tmp_path / "user-data"
    before = _snapshot(outer)

    proc = gda(
        "--user-data-root",
        str(root),
        "project",
        "create",
        "nested",
        "--name",
        "Nested",
        "--json",
        cwd=outer,
        extra_env={"GDA_PROJECT": str(outer)},
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    _assert_minimal_project(json.loads(proc.stdout), outer / "nested", "Nested")
    assert AUTOLOAD_MARK not in proc.stdout
    assert AUTOLOAD_MARK not in proc.stderr
    log = (root / "logs" / "godot.log").read_text(encoding="utf-8")
    assert "<<<GDA:RESULT>>>" in log, log
    assert AUTOLOAD_MARK not in log
    after = _snapshot(outer)
    assert {path for path in after if path.startswith("nested")} == {
        "nested",
        "nested/project.godot",
    }
    assert {
        path: entry for path, entry in after.items() if not path.startswith("nested")
    } == before

    # The control arm: the same working directory boots the outer project for a
    # command that inherits it, so the mark is observable when it runs.
    control = gda(
        "project", "info", "--json", cwd=outer, extra_env={"GDA_PROJECT": str(outer)}
    )
    assert control.returncode == 0, control.stdout + control.stderr
    assert AUTOLOAD_MARK in control.stderr


# --- AC5 ------------------------------------------------------------------


@pytest.mark.e2e
def test_a_created_project_boots_its_main_scene_headless(tmp_path):
    # Creation to a started main scene, through public commands only; every read
    # after a write is a later engine process.
    destination = tmp_path / "tracer"
    created = gda.json("project", "create", str(destination), "--name", "Tracer")
    project = Gda(
        created["path"], extra_env={"GDA_USER_DATA_ROOT": str(tmp_path / "ud")}
    )

    info = project.json("project", "info")
    assert info["name"] == "Tracer"
    assert info["main_scene"] == ""

    project.json("scene", "create", "res://main.tscn", "--root-type", "Node2D")
    project.json(
        "project", "set", "application/run/main_scene", "--value", "res://main.tscn"
    )
    preflighted = project.json("scene", "preflight", "res://main.tscn")
    assert preflighted["started"] is True, preflighted

    assert project.json("project", "info")["main_scene"] == "res://main.tscn"
