"""A fixed rendered scene shared by the real CLI and MCP capture checks."""

import hashlib
from pathlib import Path

from PIL import Image

from tests.conftest import project_godot


SCREEN_PROJECT_GODOT = project_godot(
    extra="""run/main_scene="res://main.tscn"
[display]
window/size/viewport_width=320
window/size/viewport_height=240
[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
environment/defaults/default_clear_color=Color(0, 0, 0, 1)"""
)


def write_screen_project(project: Path) -> Path:
    (project / "project.godot").write_text(SCREEN_PROJECT_GODOT, encoding="utf-8")
    (project / "main.tscn").write_text(
        """[gd_scene format=3]
[node name="Main" type="Node2D"]
[node name="Rect" type="ColorRect" parent="."]
offset_right = 200.0
offset_bottom = 150.0
color = Color(0.2, 0.6, 0.9, 1)
""",
        encoding="utf-8",
    )
    return project


def assert_screen_pixels(frame: dict) -> None:
    path = Path(frame["path"])
    assert (frame["width"], frame["height"], frame["format"]) == (320, 240, "png")
    assert frame["bytes"] == path.stat().st_size > 0
    with Image.open(path) as image:
        assert image.size == (320, 240)
        rgb = image.convert("RGB")
        color = rgb.getpixel((50, 50))
        assert isinstance(color, tuple)
        # Known authored rectangle and clear color, independent of the capture.
        assert all(
            abs(actual - expected) <= 2
            for actual, expected in zip(color, (51, 153, 230))
        )
        assert rgb.getpixel((250, 200)) == (0, 0, 0)


def assert_capture_receipt(capture: dict, session: str) -> None:
    receipt = capture["receipt"]
    assert receipt["session_id"] == session
    assert receipt["scene_path"] == "res://main.tscn"
    assert receipt["scene_uid"] is None and receipt["observed"] is None
    assert receipt["engine_frame"] >= receipt["render_frame"] >= 0
    assert (
        receipt["sha256"]
        == hashlib.sha256(Path(capture["path"]).read_bytes()).hexdigest()
    )
