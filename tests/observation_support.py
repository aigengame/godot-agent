"""A real game subject shared by CLI/MCP observation acceptance (#1121)."""

from tests.conftest import LIVE_PROJECT_GODOT, SCRIPTED_MAIN_TSCN


OBSERVATION_MAIN_GD = """\
extends Node2D

signal ticked(n)
@export var ticks: int = 0
var stall: bool = false
var end_on_sample: bool = false
var paused: bool:
\tget:
\t\treturn get_tree().paused
\tset(value):
\t\tget_tree().paused = value
@export var sample: int:
\tget:
\t\tif stall:
\t\t\tOS.delay_msec(40000)
\t\tif end_on_sample:
\t\t\tget_tree().quit()
\t\treturn ticks

func _ready() -> void:
\tvar launches := 0
\tif FileAccess.file_exists("res://launch-count.txt"):
\t\tvar previous := FileAccess.open("res://launch-count.txt", FileAccess.READ)
\t\tlaunches = previous.get_as_text().to_int()
\t\tprevious.close()
\tvar count := FileAccess.open("res://launch-count.txt", FileAccess.WRITE)
\tcount.store_string(str(launches + 1))
\tcount.close()
\tvar pid := FileAccess.open("res://engine-pid.txt", FileAccess.WRITE)
\tpid.store_string(str(OS.get_process_id()))
\tpid.close()
\tGdaHarness.gda_log("warning", "observer ready", {
\t\t"launch": launches + 1, "precise": 3.141592653589793, "tiny": 1e-300,
\t})
\tprint("observer plain line")
\tfail()

func fail() -> void:
\tvar missing = null
\tmissing.observer_failure()

func _process(_delta: float) -> void:
\tticks += 1
\tticked.emit(ticks)
"""


def write_observation_project(project):
    (project / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (project / "main.tscn").write_text(SCRIPTED_MAIN_TSCN, encoding="utf-8")
    (project / "main.gd").write_text(OBSERVATION_MAIN_GD, encoding="utf-8")
    return project
