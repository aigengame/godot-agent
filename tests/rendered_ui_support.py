"""A fixed two-button UI for real CLI/MCP rendered input acceptance (#1123)."""

from pathlib import Path

from PIL import Image

from tests.screen_support import SCREEN_PROJECT_GODOT, assert_capture_receipt

# Authored viewport coordinates, independent of game rect and captured pixels.
BUTTON_A = (70, 40)
BUTTON_B = (70, 120)
OUTSIDE = (280, 160)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)

UI_GD = """extends Control
var a_pressed := 0
var b_pressed := 0
var a_down := 0
var a_up := 0
var b_down := 0
var b_up := 0
var polled_frames := 0
var mouse_at := Vector2(-1, -1)
var hover_a := false
var block_input := false
var snapshot: Dictionary:
    get:
        var owner := get_viewport().gui_get_focus_owner()
        return {
            "a_pressed": a_pressed, "b_pressed": b_pressed,
            "a_down": a_down, "a_up": a_up, "b_down": b_down, "b_up": b_up,
            "focus": str(owner.get_path()) if owner != null else null,
            "mouse_at": mouse_at, "hover_a": hover_a,
            "polled": Input.is_action_pressed("ui_accept"), "polled_frames": polled_frames,
            "a_rect": {"position": $A.position, "size": $A.size},
            "b_rect": {"position": $B.position, "size": $B.size},
        }
func _ready() -> void:
    Engine.max_fps = 30
    $A.pressed.connect(func():
        a_pressed += 1
        $AEffect.color = Color.GREEN if a_pressed % 2 == 1 else Color.RED)
    $B.pressed.connect(func():
        b_pressed += 1
        $BEffect.color = Color.GREEN if b_pressed % 2 == 1 else Color.RED)
    $A.button_down.connect(func(): a_down += 1)
    $A.button_up.connect(func(): a_up += 1)
    $B.button_down.connect(func(): b_down += 1)
    $B.button_up.connect(func(): b_up += 1)
    $A.mouse_entered.connect(func(): hover_a = true)
    $A.mouse_exited.connect(func(): hover_a = false)
    $A.grab_focus()
    var file := FileAccess.open("res://engine-pid.txt", FileAccess.WRITE)
    file.store_string(str(OS.get_process_id()))
    file.close()
func _process(_delta: float) -> void:
    var held := Input.is_action_pressed("ui_accept")
    if held:
        polled_frames += 1
    $StateEffect.color = Color.YELLOW if held else Color.RED
    $FocusEffect.color = Color.GREEN if $B.has_focus() else Color.RED
    $HoverEffect.color = Color.GREEN if hover_a else Color.RED
func _input(event: InputEvent) -> void:
    if block_input:
        OS.delay_msec(40000)
    if event is InputEventMouseMotion:
        mouse_at = event.position
"""

UI_TSCN = """[gd_scene load_steps=2 format=3]
[ext_resource type="Script" path="res://ui.gd" id="1"]
[node name="Main" type="Control"]
offset_right = 320.0
offset_bottom = 240.0
mouse_filter = 2
script = ExtResource("1")
[node name="A" type="Button" parent="."]
offset_left = 20.0
offset_top = 20.0
offset_right = 140.0
offset_bottom = 60.0
focus_neighbor_bottom = NodePath("../B")
text = "A"
[node name="B" type="Button" parent="."]
offset_left = 20.0
offset_top = 100.0
offset_right = 140.0
offset_bottom = 140.0
focus_neighbor_top = NodePath("../A")
text = "B"
[node name="AEffect" type="ColorRect" parent="."]
offset_left = 220.0
offset_top = 20.0
offset_right = 260.0
offset_bottom = 60.0
mouse_filter = 2
color = Color(1, 0, 0, 1)
[node name="BEffect" type="ColorRect" parent="."]
offset_left = 220.0
offset_top = 100.0
offset_right = 260.0
offset_bottom = 140.0
mouse_filter = 2
color = Color(1, 0, 0, 1)
[node name="FocusEffect" type="ColorRect" parent="."]
offset_left = 220.0
offset_top = 180.0
offset_right = 260.0
offset_bottom = 220.0
mouse_filter = 2
color = Color(1, 0, 0, 1)
[node name="StateEffect" type="ColorRect" parent="."]
offset_left = 20.0
offset_top = 180.0
offset_right = 60.0
offset_bottom = 220.0
mouse_filter = 2
color = Color(1, 0, 0, 1)
[node name="HoverEffect" type="ColorRect" parent="."]
offset_left = 100.0
offset_top = 180.0
offset_right = 140.0
offset_bottom = 220.0
mouse_filter = 2
color = Color(1, 0, 0, 1)
"""


def write_rendered_ui_project(project: Path) -> Path:
    (project / "project.godot").write_text(SCREEN_PROJECT_GODOT, encoding="utf-8")
    (project / "main.tscn").write_text(UI_TSCN, encoding="utf-8")
    (project / "ui.gd").write_text(UI_GD, encoding="utf-8")
    return project


def assert_ui_pixels(
    capture: dict, session: str, *, a=RED, b=RED, focus=RED, state=RED, hover=RED
) -> None:
    assert (capture["width"], capture["height"]) == (320, 240)
    assert_capture_receipt(capture, session)
    with Image.open(capture["path"]) as image:
        assert image.size == (320, 240)
        rgb = image.convert("RGB")
        for point, expected in (
            ((240, 40), a),
            ((240, 120), b),
            ((240, 200), focus),
            ((40, 200), state),
            ((120, 200), hover),
        ):
            assert rgb.getpixel(point) == expected, (
                point,
                rgb.getpixel(point),
                expected,
            )
