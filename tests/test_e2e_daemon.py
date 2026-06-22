"""S1 (e2e): the full gda-daemon live loop through the console script (#7, #225).

The Step-6 proof: a real ``gda daemon start`` (real detached daemon, real harness
install, live-version gate) → a real engine session it launches on demand →
``gda game tree`` returns the RUNNING game's runtime scene tree, observed live via
the harness over Unix domain sockets → ``gda daemon stop`` tears it down. Run e2e
serially; not a fresh empty HOME (Godot first-run). The ``daemon_runtime_dir``
fixture keeps the daemon's UDS path within the OS ``sun_path`` limit.

#225 adds the harness-lifecycle e2e: start re-syncs the harness after a version
bump (the installed copy declares an older version), and the paired
``gda daemon uninstall`` (install→uninstall idempotent; refused while running).
"""

import json
import os
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from gda.harness.install import (
    HARNESS_FILE,
    HARNESS_RES_DIR,
    HARNESS_VERSION,
    installed_harness_version,
)

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A main scene so the launched session has a runtime SceneTree to read; a Player
# Node2D child carries a Vector2 storage property (position) for the game get/set
# round trip (#220). File logging stays disabled via project_godot (issue #180).
MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
)
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_a_real_runtime_tree(tmp_path, daemon_runtime_dir):
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    # XDG_RUNTIME_DIR is set short by the daemon_runtime_dir fixture; the spawned
    # daemon inherits it through the subprocess environment.
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        assert json.loads(started.stdout)["installed_harness"] is True

        # The daemon launches the engine session on demand and relays the live op;
        # the result is the running game's runtime scene tree.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        assert root["name"] == "Main"
        assert root["type"] == "Node2D"

        assert json.loads(run("daemon", "status").stdout)["running"] is True
        assert json.loads(run("daemon", "stop").stdout)["stopped"] is True
        assert json.loads(run("daemon", "status").stdout)["running"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_game_get_set_round_trip(tmp_path, daemon_runtime_dir):
    # The #220 DoD: a real daemon → engine session → `game set` mutates a runtime
    # property, applied at a frame boundary, and `game get` observes the change —
    # State consistency (ADR-0020) end-to-end through the real harness over UDS.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # set: mutate the Player's runtime position (a Vector2), coerced harness-side
        # from the CLI string "10,20" exactly as headless `node set` coerces it.
        was_set = run(
            "game", "set", "/root/Main/Player", "--property", "position", "--value", "10,20"
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        set_doc = json.loads(was_set.stdout)
        assert set_doc["path"] == "/root/Main/Player"
        assert set_doc["property"] == "position"
        assert set_doc["type"] == "Vector2"
        assert set_doc["value"] == [10.0, 20.0]

        # get: the SAME session observes the preceding write (single writer,
        # frame-coherent — ADR-0020). The session is held across the two ops.
        got = run("game", "get", "/root/Main/Player", "--property", "position")
        assert got.returncode == 0, got.stdout + got.stderr
        get_doc = json.loads(got.stdout)
        assert get_doc["path"] == "/root/Main/Player"
        position = next(p for p in get_doc["properties"] if p["name"] == "position")
        assert position["type"] == "Vector2"
        assert position["value"] == [10.0, 20.0]
    finally:
        run("daemon", "stop")


def _gda(tmp_path, env):
    """A `gda <args> --project <tmp> --godot <GODOT> --json` subprocess helper."""
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    return run


@pytest.mark.e2e
def test_daemon_start_re_syncs_harness_after_a_version_bump(tmp_path, daemon_runtime_dir):
    # #225 D1: the daemon self-syncs the installed harness to the running gda's
    # version. A real start installs at HARNESS_VERSION; we then SIMULATE a
    # previously-installed OLDER copy by rewriting its leading version header to a
    # stale value, stop the daemon, and start again. The second start must detect
    # the mismatch and re-materialize (harness_synced True), syncing the on-disk
    # version back to HARNESS_VERSION.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})
    harness = tmp_path / HARNESS_RES_DIR / HARNESS_FILE

    try:
        first = run("daemon", "start")
        assert first.returncode == 0, first.stdout + first.stderr
        first_doc = json.loads(first.stdout)
        assert first_doc["harness_synced"] is True  # a first install IS a sync
        assert first_doc["harness_version"] == HARNESS_VERSION
        assert installed_harness_version(tmp_path) == HARNESS_VERSION

        # Stop, then corrupt the installed header to a stale older version so the
        # next start sees a version mismatch.
        assert run("daemon", "stop").returncode == 0
        lines = harness.read_text(encoding="utf-8").splitlines()
        lines[0] = "# gda-harness-version: stale-old"
        harness.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert installed_harness_version(tmp_path) == "stale-old"

        resynced = run("daemon", "start")
        assert resynced.returncode == 0, resynced.stdout + resynced.stderr
        resynced_doc = json.loads(resynced.stdout)
        assert resynced_doc["harness_synced"] is True  # version mismatch -> resync
        assert resynced_doc["harness_version"] == HARNESS_VERSION
        assert installed_harness_version(tmp_path) == HARNESS_VERSION  # synced back
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_install_then_uninstall_is_paired_and_idempotent(
    tmp_path, daemon_runtime_dir
):
    # #225 D2: a real start installs the harness; with the daemon stopped,
    # `daemon uninstall` removes BOTH the [autoload] entry and the files (paired),
    # and a second uninstall is an idempotent no-op success.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})
    harness = tmp_path / HARNESS_RES_DIR / HARNESS_FILE

    try:
        assert run("daemon", "start").returncode == 0
        assert harness.exists()
        assert run("daemon", "stop").returncode == 0

        first = run("daemon", "uninstall")
        assert first.returncode == 0, first.stdout + first.stderr
        assert json.loads(first.stdout)["removed"] is True
        assert not harness.exists()  # files gone
        text = (tmp_path / "project.godot").read_text(encoding="utf-8")
        assert "GdaHarness" not in text  # autoload entry stripped

        # Idempotent: a second uninstall removes nothing (no-op success).
        again = run("daemon", "uninstall")
        assert again.returncode == 0, again.stdout + again.stderr
        assert json.loads(again.stdout)["removed"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_uninstall_is_refused_while_running(tmp_path, daemon_runtime_dir):
    # #225 D2: uninstall is refused while a daemon is running — it would yank the
    # harness autoload out from under the live engine session. The CLI surfaces the
    # daemon_running error at the LIVE exit (6), and the install is untouched.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})
    harness = tmp_path / HARNESS_RES_DIR / HARNESS_FILE

    try:
        assert run("daemon", "start").returncode == 0
        assert harness.exists()

        refused = run("daemon", "uninstall")
        assert refused.returncode == 6, refused.stdout + refused.stderr
        assert json.loads(refused.stdout)["error"]["code"] == "daemon_running"
        assert harness.exists()  # refusal left the install intact
    finally:
        run("daemon", "stop")
