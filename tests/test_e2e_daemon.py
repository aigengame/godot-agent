"""S1 (e2e): the full gda-daemon live loop through the gda CLI (#7, #225).

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
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from gda.harness.install import (
    HARNESS_FILE,
    HARNESS_RES_DIR,
    HARNESS_VERSION,
    installed_harness_version,
)

from tests.support import GDA_CMD

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

RECT_MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Control"]\n\n'
    '[node name="HUD" type="VBoxContainer" parent="."]\n'
    "offset_left = 24.0\n"
    "offset_top = 24.0\n"
    "offset_right = 184.0\n"
    "offset_bottom = 72.0\n\n"
    '[node name="Stats" type="Label" parent="HUD"]\n'
    "custom_minimum_size = Vector2(160, 48)\n"
    'text = "HP"\n'
)
CONTROL_POSITION_MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Control"]\n\n'
    '[node name="Panel" type="Control" parent="."]\n'
    "offset_left = 5.0\n"
    "offset_top = 7.0\n"
    "offset_right = 105.0\n"
    "offset_bottom = 57.0\n"
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_a_real_runtime_tree(tmp_path, daemon_runtime_dir):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    # XDG_RUNTIME_DIR is set short by the daemon_runtime_dir fixture; the spawned
    # daemon inherits it through the subprocess environment.
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(tmp_path),
                "--godot",
                str(GODOT),
                "--json",
            ],
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
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(tmp_path),
                "--godot",
                str(GODOT),
                "--json",
            ],
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
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "position",
            "--value",
            "10,20",
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        set_doc = json.loads(was_set.stdout)
        assert set_doc["path"] == "/root/Main/Player"
        assert set_doc["property"] == "position"
        assert set_doc["type"] == "Vector2"
        assert set_doc["value"] == [10.0, 20.0]
        assert set_doc["verified"] is True

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


@pytest.mark.e2e
def test_daemon_game_rect_reads_free_positioned_control_rect(
    tmp_path, daemon_runtime_dir
):
    # #419: `game rect` reads rendered viewport-space geometry, not storage
    # properties, so a free-positioned Control reports get_global_rect().
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(RECT_MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        rect = run("game", "rect", "/root/Main/HUD")
        assert rect.returncode == 0, rect.stdout + rect.stderr
        doc = json.loads(rect.stdout)
        assert doc["path"] == "/root/Main/HUD"
        assert doc["name"] == "HUD"
        assert doc["type"] == "VBoxContainer"
        assert doc["position"] == [24.0, 24.0]
        assert doc["size"] == [160.0, 48.0]
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_control_position_updates_offsets_preserving_size(
    tmp_path, daemon_runtime_dir
):
    # #464: live `game set` mirrors headless `node set` for Control.position by
    # applying an actionable offset write while preserving the current size.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CONTROL_POSITION_MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        was_set = run(
            "game",
            "set",
            "/root/Main/Panel",
            "--property",
            "position",
            "--value",
            "20,30",
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        set_doc = json.loads(was_set.stdout)
        assert set_doc["path"] == "/root/Main/Panel"
        assert (set_doc["property"], set_doc["type"]) == ("position", "Vector2")
        assert set_doc["value"] == [20.0, 30.0]

        props = {}
        for name in ("offset_left", "offset_top", "offset_right", "offset_bottom"):
            got = run("game", "get", "/root/Main/Panel", "--property", name)
            assert got.returncode == 0, got.stdout + got.stderr
            props[name] = json.loads(got.stdout)["properties"][0]["value"]
        assert props == {
            "offset_left": 20.0,
            "offset_top": 30.0,
            "offset_right": 120.0,
            "offset_bottom": 80.0,
        }
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_container_managed_control_position_names_offset_alternatives(
    tmp_path, daemon_runtime_dir
):
    # A Container owns direct-child layout; `game set position` reports an
    # actionable live error instead of claiming a write the next layout pass owns.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(RECT_MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        was_set = run(
            "game",
            "set",
            "/root/Main/HUD/Stats",
            "--property",
            "position",
            "--value",
            "20,30",
        )
        assert was_set.returncode == 6, was_set.stdout + was_set.stderr
        error = json.loads(was_set.stdout)["error"]
        assert error["category"] == "live"
        assert error["code"] == "live_unknown_property"
        for name in ("offset_left", "offset_top", "offset_right", "offset_bottom"):
            assert name in error["message"]
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_rect_reads_container_managed_child_rect(
    tmp_path, daemon_runtime_dir
):
    # #419: container-managed Controls have layout output even when a storage
    # property read is the wrong surface. `game rect` returns the rendered rect.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(RECT_MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        position = run(
            "game",
            "get",
            "/root/Main/HUD/Stats",
            "--property",
            "position",
        )
        assert position.returncode == 6, position.stdout + position.stderr
        assert json.loads(position.stdout)["error"]["code"] == "live_unknown_property"

        rect = run("game", "rect", "/root/Main/HUD/Stats")
        assert rect.returncode == 0, rect.stdout + rect.stderr
        doc = json.loads(rect.stdout)
        assert doc["path"] == "/root/Main/HUD/Stats"
        assert doc["name"] == "Stats"
        assert doc["type"] == "Label"
        assert doc["position"] == [24.0, 24.0]
        assert doc["size"] == [160.0, 48.0]
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_rect_rejects_non_control_node(tmp_path, daemon_runtime_dir):
    # #419: the command is intentionally Control-specific; a live node that
    # exists but is not a Control gets a typed LIVE error.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        rect = run("game", "rect", "/root/Main/Player")
        assert rect.returncode == 6, rect.stdout + rect.stderr
        error = json.loads(rect.stdout)["error"]
        assert error["code"] == "live_not_control"
        assert error["category"] == "live"
    finally:
        run("daemon", "stop")


# A Player script for the live half of the value projection (ADR-0035, #381):
# an exported Dictionary (compound -> structured) and an exported Node
# reference assigned at _ready (a NON-whitelisted runtime Object -> the str()
# fallback, the live-side risk boundary).
PROJECTION_PLAYER_GD = (
    "extends Node2D\n"
    '@export var stats: Dictionary = {"hp": 5, "label": "panda"}\n'
    "@export var buddy: Node\n"
    "func _ready() -> void:\n"
    "\tbuddy = get_parent()\n"
)
PROJECTION_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

SCRIPT_VARIABLE_PLAYER_GD = (
    'extends Node2D\nvar _items := {"wine": 1}\nvar _tags := ["starter"]\n'
)
READONLY_SCRIPT_VARIABLE_PLAYER_GD = (
    "extends Node2D\nvar readonly: int:\n\tget:\n\t\treturn 1\n"
)
EDGE_TRIGGER_SCRIPT_VARIABLE_PLAYER_GD = (
    "extends Node2D\n"
    "var spawn_count: int = 0\n"
    "var spawn: bool:\n"
    "\tget:\n"
    "\t\treturn false\n"
    "\tset(value):\n"
    "\t\tif value:\n"
    "\t\t\tspawn_count += 1\n"
)
SCRIPT_VARIABLE_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
def test_daemon_game_get_projects_compound_values_with_live_fallback(
    tmp_path, daemon_runtime_dir
):
    # The live half of ADR-0035, through the byte-identical mirrored harness
    # projection: `game get` of an exported Dictionary arrives as a structured
    # JSON object, while a Node-valued property — a non-whitelisted runtime
    # Object — stays the str() fallback (the whitelist keeps the shared
    # projection safe against projecting a whole live scene tree).
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(PROJECTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(PROJECTION_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        got = run("game", "get", "/root/Main/Player")
        assert got.returncode == 0, got.stdout + got.stderr
        props = {p["name"]: p for p in json.loads(got.stdout)["properties"]}

        stats = props["stats"]
        assert stats["type"] == "Dictionary"
        assert stats["value"] == {"hp": 5, "label": "panda"}

        # The live Node reference is NOT projected — no structure, no descent
        # into the runtime tree — just the existing string form.
        buddy = props["buddy"]
        assert isinstance(buddy["value"], str)
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_get_reads_explicit_plain_script_dictionary_variable(
    tmp_path, daemon_runtime_dir
):
    # #422: a plain non-exported script variable is addressable when explicitly
    # named, but it remains outside the unfiltered storage-property listing.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        got = run("game", "get", "/root/Main/Player", "--property", "_items")
        assert got.returncode == 0, got.stdout + got.stderr
        doc = json.loads(got.stdout)
        assert doc["path"] == "/root/Main/Player"
        assert doc["properties"] == [
            {"name": "_items", "type": "Dictionary", "value": {"wine": 1}}
        ]

        unfiltered = run("game", "get", "/root/Main/Player")
        assert unfiltered.returncode == 0, unfiltered.stdout + unfiltered.stderr
        prop_names = {p["name"] for p in json.loads(unfiltered.stdout)["properties"]}
        assert "_items" not in prop_names
        assert "_tags" not in prop_names
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_mutates_explicit_plain_script_dictionary_variable(
    tmp_path, daemon_runtime_dir
):
    # #422: script-variable writes are live-session state seeding only. A later
    # read in the same session observes the mutation; nothing is persisted.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        was_set = run(
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "_items",
            "--value",
            '{"wine":2}',
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        assert json.loads(was_set.stdout) == {
            "path": "/root/Main/Player",
            "property": "_items",
            "type": "Dictionary",
            "value": {"wine": 2},
            "verified": True,
        }

        got = run("game", "get", "/root/Main/Player", "--property", "_items")
        assert got.returncode == 0, got.stdout + got.stderr
        assert json.loads(got.stdout)["properties"] == [
            {"name": "_items", "type": "Dictionary", "value": {"wine": 2}}
        ]

        tags_set = run(
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "_tags",
            "--value",
            '["rare","consumable"]',
        )
        assert tags_set.returncode == 0, tags_set.stdout + tags_set.stderr
        assert json.loads(tags_set.stdout) == {
            "path": "/root/Main/Player",
            "property": "_tags",
            "type": "Array",
            "value": ["rare", "consumable"],
            "verified": True,
        }
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_preserves_json_container_integer_and_float_types(
    tmp_path, daemon_runtime_dir
):
    # #427 live-side parity: the mirrored harness coercion must preserve JSON
    # integer vs float values in the same session state that game get observes.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        was_set = run(
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "_items",
            "--value",
            '{"a":2,"b":2.0,"items":[1,1.5]}',
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        set_value = json.loads(was_set.stdout)["value"]
        assert type(set_value["a"]) is int
        assert type(set_value["b"]) is float
        assert type(set_value["items"][0]) is int
        assert type(set_value["items"][1]) is float

        got = run("game", "get", "/root/Main/Player", "--property", "_items")
        assert got.returncode == 0, got.stdout + got.stderr
        got_value = json.loads(got.stdout)["properties"][0]["value"]
        assert type(got_value["a"]) is int
        assert type(got_value["b"]) is float
        assert type(got_value["items"][0]) is int
        assert type(got_value["items"][1]) is float
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_get_unknown_explicit_script_variable_reports_unknown_property(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        got = run("game", "get", "/root/Main/Player", "--property", "_typo")
        assert got.returncode == 6, got.stdout + got.stderr
        error = json.loads(got.stdout)["error"]
        assert error["code"] == "live_unknown_property"
        assert error["message"] == (
            "node /root/Main/Player has no runtime, storage, or script property: _typo"
        )
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_uncoercible_script_variable_reports_target_type(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        was_set = run(
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "_items",
            "--value",
            "not-json",
        )
        assert was_set.returncode == 6, was_set.stdout + was_set.stderr
        error = json.loads(was_set.stdout)["error"]
        assert error["code"] == "live_uncoercible_value"
        assert error["message"] == (
            "cannot coerce value not-json to Dictionary for script variable _items "
            "on node /root/Main/Player"
        )
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_readonly_script_variable_reports_unverified_observed_value(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(
        READONLY_SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8"
    )
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        got = run("game", "get", "/root/Main/Player", "--property", "readonly")
        assert got.returncode == 0, got.stdout + got.stderr
        assert json.loads(got.stdout)["properties"] == [
            {"name": "readonly", "type": "int", "value": 1}
        ]

        was_set = run(
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "readonly",
            "--value",
            "2",
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        assert json.loads(was_set.stdout) == {
            "path": "/root/Main/Player",
            "property": "readonly",
            "type": "int",
            "value": 1,
            "verified": False,
        }
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_game_set_edge_trigger_reports_unverified_then_side_effect_is_readable(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPT_VARIABLE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(
        EDGE_TRIGGER_SCRIPT_VARIABLE_PLAYER_GD, encoding="utf-8"
    )
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        was_set = run(
            "game",
            "set",
            "/root/Main/Player",
            "--property",
            "spawn",
            "--value",
            "true",
        )
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        assert json.loads(was_set.stdout) == {
            "path": "/root/Main/Player",
            "property": "spawn",
            "type": "bool",
            "value": False,
            "verified": False,
        }

        got = run("game", "get", "/root/Main/Player", "--property", "spawn_count")
        assert got.returncode == 0, got.stdout + got.stderr
        assert json.loads(got.stdout)["properties"] == [
            {"name": "spawn_count", "type": "int", "value": 1}
        ]
    finally:
        run("daemon", "stop")


def _gda(tmp_path, env, timeout=90):
    """A `gda <args> --project <tmp> --godot <GODOT> --json` subprocess helper.

    ``timeout`` defaults to 90s (the value every existing call site relied on
    implicitly); a windowed session is heavier to launch, so callers that start
    one pass a larger value (e.g. ``timeout=120``, matching the windowed e2e
    tests elsewhere) instead of hand-rolling a near-duplicate of this helper.
    """

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(tmp_path),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    return run


@pytest.mark.e2e
def test_daemon_start_re_syncs_harness_after_a_version_bump(
    tmp_path, daemon_runtime_dir
):
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
        assert (
            first_doc["harness_synced"] is False
        )  # a first install is NOT a sync (#247)
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


@pytest.mark.e2e
def test_daemon_status_surfaces_the_windowed_display_mode(tmp_path, daemon_runtime_dir):
    # #251: `daemon status` reports the running daemon's launch-time display mode,
    # read over STATUS_OP through the `gda` CLI, so an agent can tell whether a
    # live session can serve a `screen` capture before issuing one. No daemon ->
    # `windowed` null (clean, hang-free fallback); a default start -> false; a
    # `--windowed` start -> true. The daemon records the mode at start; no engine
    # session is launched here (lazy launch, ADR-0017), so this needs no display.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    # No daemon running yet: running False, windowed null.
    before = json.loads(run("daemon", "status").stdout)
    assert before["running"] is False
    assert before["windowed"] is None

    try:
        # The default start is headless -> status reports windowed False.
        assert run("daemon", "start").returncode == 0
        headless = json.loads(run("daemon", "status").stdout)
        assert headless["running"] is True
        assert headless["windowed"] is False
        assert run("daemon", "stop").returncode == 0

        # A `--windowed` start -> status reports windowed True. `daemon start
        # --windowed` now refuses PRE-LAUNCH with live_windowed_unavailable on a host
        # with no usable DisplayServer (#345), so gate this half on the shared display
        # helper — the headless portions above already ran.
        from gda.display import windowed_unavailable_reason

        reason = windowed_unavailable_reason()
        if reason is not None:
            pytest.skip(reason)
        assert run("daemon", "start", "--windowed").returncode == 0
        windowed = json.loads(run("daemon", "status").stdout)
        assert windowed["running"] is True
        assert windowed["windowed"] is True
    finally:
        run("daemon", "stop")


# A SECOND scene the session can boot via `--scene`, distinct from main.tscn so the
# runtime tree's root name proves WHICH scene ran. Its root is "B" (not "Main").
B_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="B" type="Node2D"]\n\n'
    '[node name="Marker" type="Node2D" parent="."]\n'
)


@pytest.mark.e2e
def test_daemon_start_scene_runs_the_chosen_scene_not_main(
    tmp_path, daemon_runtime_dir
):
    # #278 (ADR-0017 amendment): `daemon start --scene res://B.tscn` boots the chosen
    # scene B — `game tree` reports B's root (not Main's), proving the engine received
    # `--scene` (before `--path`) — and `project.godot`'s `main_scene` is UNCHANGED
    # (no mutation, F6-equivalent). With scenes A (main) + B present.
    project_text = PROJECT_GODOT
    (tmp_path / "project.godot").write_text(project_text, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "B.tscn").write_text(B_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start", "--scene", "res://B.tscn")
        assert started.returncode == 0, started.stdout + started.stderr

        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr
        root = json.loads(tree.stdout)["root"]
        # The chosen scene B ran — NOT the project's main_scene (Main).
        assert root["name"] == "B"
        assert any(c["name"] == "Marker" for c in root.get("children", []))

        # main_scene is untouched on disk (running a scene is not setting it).
        assert 'run/main_scene="res://main.tscn"' in (
            tmp_path / "project.godot"
        ).read_text(encoding="utf-8")
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_start_nonexistent_scene_is_typed_live_scene_not_found(
    tmp_path, daemon_runtime_dir
):
    # #278: a non-existent `--scene` selector surfaces a TYPED `live_scene_not_found`
    # (LIVE exit 6) on the first live op — NEVER a silent fall back to main_scene.
    # Detected at launch by the harness (the loaded scene != the requested selector),
    # surfaced when the lazy launch is triggered by `game tree`.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start", "--scene", "res://does_not_exist.tscn")
        assert started.returncode == 0, started.stdout + started.stderr

        tree = run("game", "tree")
        assert tree.returncode == 6, tree.stdout + tree.stderr
        assert json.loads(tree.stdout)["error"]["code"] == "live_scene_not_found"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_start_nonexistent_uid_is_typed_not_silent_main_scene(
    tmp_path, daemon_runtime_dir
):
    # #278 review finding 2: Godot given a BAD `uid://` selector silently falls back
    # to main_scene. Launch-time harness verification catches this — the loaded scene
    # (main) != the requested uid — and surfaces a typed `live_scene_not_found`, NOT a
    # silent success on main_scene.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        started = run("daemon", "start", "--scene", "uid://doesnotexist000")
        assert started.returncode == 0, started.stdout + started.stderr

        tree = run("game", "tree")
        assert tree.returncode == 6, tree.stdout + tree.stderr
        assert json.loads(tree.stdout)["error"]["code"] == "live_scene_not_found"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_start_scene_against_a_running_daemon_is_a_typed_refusal(
    tmp_path, daemon_runtime_dir
):
    # #278 review finding 3: `--scene` only takes effect at daemon START. Against a
    # daemon that is already running it is a typed `daemon_already_running` refusal,
    # NOT a silent no-op that quietly ignores the chosen scene.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "B.tscn").write_text(B_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        assert run("daemon", "start").returncode == 0

        refused = run("daemon", "start", "--scene", "res://B.tscn")
        assert refused.returncode == 6, refused.stdout + refused.stderr
        assert json.loads(refused.stdout)["error"]["code"] == "daemon_already_running"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_scene_verified_once_at_launch_survives_deleting_the_file(
    tmp_path, daemon_runtime_dir
):
    # #278 review finding 1: scene is verified ONCE at launch, never per-request. A
    # live session bound to scene B keeps serving B after B.tscn is deleted on disk —
    # the running game does not reload disk edits (ADR-0017/0020 session-bound state),
    # so a later `game tree` STILL reports B, not `live_scene_not_found`.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    b_scene = tmp_path / "B.tscn"
    b_scene.write_text(B_TSCN, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    try:
        assert run("daemon", "start", "--scene", "res://B.tscn").returncode == 0

        first = run("game", "tree")
        assert first.returncode == 0, first.stdout + first.stderr
        assert json.loads(first.stdout)["root"]["name"] == "B"

        # Delete the scene file out from under the LIVE session.
        b_scene.unlink()

        # The session is bound to B and verified once at launch — it STILL serves B
        # (no per-request disk re-validation).
        again = run("game", "tree")
        assert again.returncode == 0, again.stdout + again.stderr
        assert json.loads(again.stdout)["root"]["name"] == "B"
    finally:
        run("daemon", "stop")


# #656 (GDA-DF-013): a real pause menu sets SceneTree.paused; a "Resumer" node
# forwards SceneTree.paused through a script-variable property so a live `game
# set`/`game get` can drive and observe it (no Node exposes `paused` directly), and
# reacts to an injected resume key ONLY because it opts into PROCESS_MODE_ALWAYS —
# the same pattern a real pause-menu script needs to keep handling input while
# paused. A sibling "Ticker" node keeps the DEFAULT process mode, so its tick count
# is the control that proves the pause (and later the resume) is real, not just a
# flag read back.
PAUSE_PLAYER_GD = (
    "extends Node2D\n"
    "@export var is_resumer: bool = false\n"
    "@export var ticks: int = 0\n"
    "func _ready() -> void:\n"
    "\tif is_resumer:\n"
    "\t\tprocess_mode = Node.PROCESS_MODE_ALWAYS\n"
    "func _process(_delta: float) -> void:\n"
    "\tticks += 1\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif not is_resumer:\n"
    "\t\treturn\n"
    "\tif event is InputEventKey and event.pressed and event.keycode == KEY_R:\n"
    "\t\tget_tree().paused = false\n"
    "var tree_paused: bool:\n"
    "\tget:\n"
    "\t\treturn get_tree().paused\n"
    "\tset(value):\n"
    "\t\tget_tree().paused = value\n"
)
PAUSE_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Resumer" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
    "is_resumer = true\n\n"
    '[node name="Ticker" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n\n'
    '[node name="Rect" type="ColorRect" parent="."]\n'
    "offset_right = 64.0\n"
    "offset_bottom = 64.0\n"
    "color = Color(0.8, 0.2, 0.2, 1)\n"
)


@pytest.mark.e2e
def test_daemon_serves_live_ops_while_scenetree_paused(tmp_path, daemon_runtime_dir):
    # The #656 DoD's headless core: opening a real pause menu sets SceneTree.paused,
    # and the harness must keep serving `game get` / `input sequence` through it —
    # and an injected "resume" input must be able to unpause the session, proving
    # this is not the dead-end the dogfooding note (GDA-DF-013) reported (input
    # injection is itself a harness op, so if the harness stopped ticking on pause
    # there would be no way back in). A default (headless) session, so this runs
    # everywhere a daemon e2e runs — including CI's display-less godot-e2e job; the
    # `screen capture` leg needs a real DisplayServer and lives in the windowed-gated
    # test below instead.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(PAUSE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(PAUSE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ})

    def ticker_ticks() -> int:
        got = run("game", "get", "/root/Main/Ticker", "--property", "ticks")
        assert got.returncode == 0, got.stdout + got.stderr
        return json.loads(got.stdout)["properties"][0]["value"]

    def tree_is_paused() -> bool:
        got = run("game", "get", "/root/Main/Resumer", "--property", "tree_paused")
        assert got.returncode == 0, got.stdout + got.stderr
        return json.loads(got.stdout)["properties"][0]["value"]

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr
        assert tree_is_paused() is False

        # Pause the game the way a real pause menu does: a live `game set` flips
        # SceneTree.paused through the Resumer's forwarding property.
        paused_set = run(
            "game",
            "set",
            "/root/Main/Resumer",
            "--property",
            "tree_paused",
            "--value",
            "true",
        )
        assert paused_set.returncode == 0, paused_set.stdout + paused_set.stderr
        assert json.loads(paused_set.stdout)["verified"] is True
        assert tree_is_paused() is True

        # Control: the DEFAULT-process-mode Ticker genuinely stops advancing while
        # paused — proving the pause took effect, not just that the flag reads back.
        stalled_before = ticker_ticks()
        stalled_after = ticker_ticks()
        assert stalled_after == stalled_before

        # The harness-served ops the #656 acceptance criteria name must still serve
        # while paused: a live read and an input injection.
        read_while_paused = run("game", "get", "/root/Main/Resumer")
        assert read_while_paused.returncode == 0, (
            read_while_paused.stdout + read_while_paused.stderr
        )

        # Resume input: inject KEY_R via `input sequence`. It reaches ONLY the
        # Resumer (PROCESS_MODE_ALWAYS) — mirroring a real pause menu's resume
        # handler — which flips SceneTree.paused back off.
        events = json.dumps([{"type": "key", "key": "R", "frame": 0}])
        resumed = run("input", "sequence", "--events", events)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert json.loads(resumed.stdout)["kind"] == "sequence"

        # The session is genuinely responsive again: the paused flag cleared, and
        # the default-process-mode Ticker resumes advancing.
        assert tree_is_paused() is False
        resumed_before = ticker_ticks()
        resumed_after = ticker_ticks()
        assert resumed_after > resumed_before
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_screen_capture_while_scenetree_paused(
    tmp_path, daemon_runtime_dir
):
    # The #656 DoD's windowed leg, split from the headless core above because
    # `screen capture` needs a real DisplayServer (`daemon start --windowed`) —
    # gated like the other windowed e2e tests, so it runs on a developer's local
    # GUI macOS session (or under xvfb on Linux) but skips on CI's display-less
    # godot-e2e job, unlike the headless core test.
    #
    # This restores the issue's INTEGRATED paused-session sequence on the one path
    # that can exercise every op it names in a single session: capture alone could
    # pass even with a capture-specific regression elsewhere in the harness, so
    # after the paused capture this continues in the SAME session with a live read,
    # a resume `input sequence` injection, and a responsiveness proof — the same
    # read/resume/responsiveness shape the headless test proves without a display,
    # here proven end-to-end alongside the capture that needs one.
    from gda.display import windowed_unavailable_reason

    reason = windowed_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(PAUSE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(PAUSE_PLAYER_GD, encoding="utf-8")
    run = _gda(tmp_path, {**os.environ}, timeout=120)

    def ticker_ticks() -> int:
        got = run("game", "get", "/root/Main/Ticker", "--property", "ticks")
        assert got.returncode == 0, got.stdout + got.stderr
        return json.loads(got.stdout)["properties"][0]["value"]

    def tree_is_paused() -> bool:
        got = run("game", "get", "/root/Main/Resumer", "--property", "tree_paused")
        assert got.returncode == 0, got.stdout + got.stderr
        return json.loads(got.stdout)["properties"][0]["value"]

    try:
        started = run("daemon", "start", "--windowed")
        assert started.returncode == 0, started.stdout + started.stderr

        # Pause the game the way a real pause menu does: a live `game set` flips
        # SceneTree.paused through the Resumer's forwarding property.
        paused_set = run(
            "game",
            "set",
            "/root/Main/Resumer",
            "--property",
            "tree_paused",
            "--value",
            "true",
        )
        assert paused_set.returncode == 0, paused_set.stdout + paused_set.stderr
        assert json.loads(paused_set.stdout)["verified"] is True
        assert tree_is_paused() is True

        capture_path = tmp_path / "paused.png"
        captured = run("screen", "capture", "--output", str(capture_path))
        assert captured.returncode == 0, captured.stdout + captured.stderr
        assert capture_path.exists()
        assert capture_path.stat().st_size > 0

        # The SAME paused session still serves a live read right after the
        # capture — the capture's time-windowed harness state did not wedge it.
        read_while_paused = run("game", "get", "/root/Main/Resumer")
        assert read_while_paused.returncode == 0, (
            read_while_paused.stdout + read_while_paused.stderr
        )

        # Resume input: inject KEY_R via `input sequence`. It reaches ONLY the
        # Resumer (PROCESS_MODE_ALWAYS) — mirroring a real pause menu's resume
        # handler — which flips SceneTree.paused back off.
        events = json.dumps([{"type": "key", "key": "R", "frame": 0}])
        resumed = run("input", "sequence", "--events", events)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert json.loads(resumed.stdout)["kind"] == "sequence"

        # The session is genuinely responsive again: the paused flag cleared, and
        # the default-process-mode Ticker resumes advancing.
        assert tree_is_paused() is False
        resumed_before = ticker_ticks()
        resumed_after = ticker_ticks()
        assert resumed_after > resumed_before
    finally:
        run("daemon", "stop")
