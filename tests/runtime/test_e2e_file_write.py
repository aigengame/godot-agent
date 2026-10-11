"""Real payload token sharing and run isolation (#1139, ADR-0043 §4)."""

import json
import shutil
import subprocess

import pytest

from tests.support import GODOT, PAYLOAD_DIR


@pytest.mark.e2e
def test_file_write_shares_a_token_within_a_run_and_isolates_a_fresh_run(
    godot_project,
):
    # Public commands start a fresh process. The existing payload harness seam
    # can exercise two runtime instances deterministically without depending on
    # an intermittent native crash or on the token's storage fields.
    shutil.copytree(PAYLOAD_DIR, godot_project / "ops")
    (godot_project / "target.gd").write_text("extends Node\n", encoding="utf-8")
    external_edit = "extends Node\n# external edit\n"
    harness = """\
extends SceneTree

func _initialize() -> void:
	var entry: GDScript = load("res://ops/operations.gd")
	var file_write: GDScript = load("res://ops/lib/file_write.gd")
	var first_run: Object = entry.new()
	var fresh_run: Object = entry.new()
	var capture: RefCounted = file_write.new(first_run)
	var check: RefCounted = file_write.new(first_run)
	var fresh_check: RefCounted = file_write.new(fresh_run)
	capture.call("_capture_staleness_token", "res://target.gd")
	var file := FileAccess.open("res://target.gd", FileAccess.WRITE)
	file.store_string("extends Node\\n# external edit\\n")
	file.close()
	var rejects_edit: bool = not check.call("_check_unchanged")
	var fresh_has_no_token: bool = fresh_check.call("_check_unchanged")
	capture = null
	check = null
	fresh_check = null
	first_run.free()
	fresh_run.free()
	print("<<<TOKEN-HARNESS>>>", JSON.stringify({
		"rejects_edit": rejects_edit, "fresh_has_no_token": fresh_has_no_token
	}))
	quit(0)
"""
    (godot_project / "token_harness.gd").write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--path",
            str(godot_project),
            "--script",
            "res://token_harness.gd",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    marker = "<<<TOKEN-HARNESS>>>"
    assert marker in proc.stdout, proc.stdout + proc.stderr
    result = json.loads(proc.stdout.split(marker, 1)[1].splitlines()[0])
    assert result == {"rejects_edit": True, "fresh_has_no_token": True}
    assert (godot_project / "target.gd").read_text(encoding="utf-8") == external_edit
