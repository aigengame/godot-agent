"""A game state subject shared by real CLI and MCP acceptance paths (#1119)."""

from tests.conftest import LIVE_PROJECT_GODOT, PAUSED_PROPERTY_GD


GAME_STATE_GD = (
    """\
extends Node2D

const GDA_CALLABLE := ["state", "echo_float"]

var count: int = 3
var ticks: int = 0
var payload: Dictionary = {"items": [1, 1.25], "at": Vector2(5, 7)}
"""
    + PAUSED_PROPERTY_GD
    + """
func _process(_delta: float) -> void:
\tticks += 1

func state() -> Dictionary:
\treturn {"count": count, "ticks": ticks, "paused": paused, "payload": payload}

func echo_float(value: float) -> float:
\treturn value

func secret() -> String:
\treturn "not declared"
"""
)

GAME_STATE_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")

[node name="Panel" type="Control" parent="."]
offset_left = 20.0
offset_top = 30.0
offset_right = 120.0
offset_bottom = 80.0
custom_minimum_size = Vector2(40, 25)
"""


def write_game_state_project(project):
    (project / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (project / "main.tscn").write_text(GAME_STATE_TSCN, encoding="utf-8")
    (project / "main.gd").write_text(GAME_STATE_GD, encoding="utf-8")
    return project
