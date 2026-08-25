"""S1 (e2e): `gda game` live commands through the real `gda` CLI (`python -m gda`, #7).

This slice's real path is the attach-or-fail: a real ``gda game tree`` with no
running daemon must emit the typed ``daemon_not_running`` envelope and exit
``EXIT_LIVE`` — exercised through the out-of-process `gda` CLI and the real
``DaemonRunner`` + discovery (no fake at the seam). The connected path (a live
tree from a real engine session) lands with the daemon, a later slice. Per
RULES.md DoD the fake-runner command tests do not count toward this gate.
"""

import json
import os
import subprocess

import pytest

from gda.exit_codes import EXIT_LIVE

from tests.support import GDA_CMD


@pytest.mark.e2e
def test_game_tree_without_a_daemon_reports_daemon_not_running(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    # An empty runtime dir so discovery finds no daemon for this fresh project.
    env = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path / "run")}
    proc = subprocess.run(
        [*GDA_CMD, "game", "tree", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


# A Player that builds PATH-LESS ImageTextures at runtime (#666): two with
# different content and a third repeating the first's, so the digest opt-in can
# prove distinguishability AND stability. Deliberately path-less — the exact
# GDA-DF-011 shape the string fallback could not identify.
TEXTURE_PLAYER_GD = (
    "extends Node2D\n"
    "@export var tex_a: Texture2D\n"
    "@export var tex_b: Texture2D\n"
    "@export var tex_a2: Texture2D\n"
    "func _ready() -> void:\n"
    "\ttex_a = _make(Color.RED)\n"
    "\ttex_b = _make(Color.BLUE)\n"
    "\ttex_a2 = _make(Color.RED)\n"
    "func _make(c: Color) -> ImageTexture:\n"
    "\tvar img := Image.create(2, 3, false, Image.FORMAT_RGBA8)\n"
    "\timg.fill(c)\n"
    "\treturn ImageTexture.create_from_image(img)\n"
)
TEXTURE_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
def test_game_get_projects_a_path_less_texture_with_optional_digest(
    tmp_path, daemon_runtime_dir
):
    # The #666 DoD (GDA-DF-011): a live `game get` on a path-less ImageTexture
    # returns the TextureProjection — type + dimensions, the old str() form
    # under object_string, NO resource_path key — with digest null by default;
    # with --texture-digest, two same-class textures with different content
    # get different digests and same-content textures the same one.
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(TEXTURE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(TEXTURE_PLAYER_GD, encoding="utf-8")

    from gda.binary import resolve_godot_binary

    godot = resolve_godot_binary()
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(tmp_path),
                "--godot",
                str(godot),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    def texture_value(prop, *extra):
        got = run("game", "get", "/root/Main/Player", "--property", prop, *extra)
        assert got.returncode == 0, got.stdout + got.stderr
        return next(
            p for p in json.loads(got.stdout)["properties"] if p["name"] == prop
        )["value"]

    try:
        assert run("daemon", "start").returncode == 0

        # Without the opt-in: the projection names the texture, digest stays
        # null, and the readback is never paid.
        plain = texture_value("tex_a")
        assert plain["type"] == "ImageTexture"
        assert plain["width"] == 2
        assert plain["height"] == 3
        assert "ImageTexture" in plain["object_string"]
        assert plain["digest"] is None
        assert "resource_path" not in plain

        # With the opt-in: different content, different digest; same content,
        # the same digest — the identity GDA-DF-011 could not establish.
        tex_a = texture_value("tex_a", "--texture-digest")
        tex_b = texture_value("tex_b", "--texture-digest")
        tex_a2 = texture_value("tex_a2", "--texture-digest")
        assert tex_a["digest"].startswith("sha256:")
        assert tex_b["digest"].startswith("sha256:")
        assert tex_a["digest"] != tex_b["digest"]
        assert tex_a2["digest"] == tex_a["digest"]
    finally:
        run("daemon", "stop")
