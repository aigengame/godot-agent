"""One game-side observer for CLI/MCP input-route acceptance (#1120)."""

from tests.live.test_e2e_input import MATRIX_PROJECT_GODOT


INPUT_OBSERVER_GD = """\
extends Control

var polled_frames: int = 0
var pressed_edges: int = 0
var released_edges: int = 0
var input_hits: int = 0
var gui_hits: int = 0
var unhandled_hits: int = 0
var input_releases: int = 0
var gui_releases: int = 0
var unhandled_releases: int = 0
var mouse_edges: Array[String] = []
var mouse_position := Vector2.ZERO
var block_input: bool = false
var paused: bool:
\tget:
\t\treturn get_tree().paused
\tset(value):
\t\tget_tree().paused = value
var snapshot: Dictionary:
\tget:
\t\treturn {
\t\t\t"state": Input.is_action_pressed("move_right"),
\t\t\t"polled": polled_frames, "pressed": pressed_edges, "released": released_edges,
\t\t\t"input": input_hits, "gui": gui_hits, "unhandled": unhandled_hits,
\t\t\t"input_release": input_releases, "gui_release": gui_releases,
\t\t\t"unhandled_release": unhandled_releases,
\t\t\t"mouse": mouse_edges, "at": mouse_position,
\t\t\t"paused": paused, "ticker": $Ticker.ticks, "block_input": block_input,
\t\t}

func _ready() -> void:
\tprocess_mode = Node.PROCESS_MODE_ALWAYS
\tfocus_mode = Control.FOCUS_ALL
\tgrab_focus()
\tvar file := FileAccess.open("res://engine-pid.txt", FileAccess.WRITE)
\tfile.store_string(str(OS.get_process_id()))
\tfile.close()

func _process(_delta: float) -> void:
\tif Input.is_action_pressed("move_right"):
\t\tpolled_frames += 1
\tif Input.is_action_just_pressed("move_right"):
\t\tpressed_edges += 1
\tif Input.is_action_just_released("move_right"):
\t\treleased_edges += 1

func _input(event: InputEvent) -> void:
\tif block_input:
\t\tOS.delay_msec(40000)
\tif event is InputEventMouseMotion:
\t\tmouse_edges.append("move")
\t\tmouse_position = event.position
\telif event is InputEventMouseButton:
\t\tmouse_edges.append("press" if event.pressed else "release")
\t\tmouse_position = event.position
\tif event.is_action_pressed("move_right"):
\t\tinput_hits += 1
\telif event.is_action_released("move_right"):
\t\tinput_releases += 1

func _gui_input(event: InputEvent) -> void:
\tif event.is_action_pressed("move_right"):
\t\tgui_hits += 1
\telif event.is_action_released("move_right"):
\t\tgui_releases += 1

func _unhandled_input(event: InputEvent) -> void:
\tif event.is_action_pressed("move_right"):
\t\tunhandled_hits += 1
\telif event.is_action_released("move_right"):
\t\tunhandled_releases += 1
"""

INPUT_OBSERVER_TSCN = """\
[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://observer.gd" id="1"]
[ext_resource type="Script" path="res://ticker.gd" id="2"]

[node name="Main" type="Control"]
offset_right = 120.0
offset_bottom = 80.0
script = ExtResource("1")

[node name="Ticker" type="Node" parent="."]
process_mode = 1
script = ExtResource("2")
"""


def write_input_observer_project(project):
    (project / "project.godot").write_text(MATRIX_PROJECT_GODOT, encoding="utf-8")
    (project / "main.tscn").write_text(INPUT_OBSERVER_TSCN, encoding="utf-8")
    (project / "observer.gd").write_text(INPUT_OBSERVER_GD, encoding="utf-8")
    (project / "ticker.gd").write_text(
        "extends Node\nvar ticks: int = 0\nfunc _process(_delta: float) -> void:\n\tticks += 1\n",
        encoding="utf-8",
    )
    return project
