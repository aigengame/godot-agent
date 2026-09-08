"""Owned isolated-project files for the model preview workflow."""

import json
from pathlib import Path
import struct

import pytest

from gda_assets.adapters.preview_files import PreviewFiles
from gda_assets.application.ports import PortFailure
from gda_assets.domain.preview import PreviewCamera, PreviewSettings


def _glb(path: Path, *, external_uri: str | None = None) -> None:
    document: dict[str, object] = {"asset": {"version": "2.0"}}
    if external_uri is not None:
        document["images"] = [{"uri": external_uri}]
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    size = 12 + 8 + len(payload)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, size)
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def _cameras() -> tuple[PreviewCamera, ...]:
    return (
        PreviewCamera("front", (0, 0, 5), (0, 0, 0), 3, 0.1, 10),
        PreviewCamera("side", (5, 0, 0), (0, 0, 0), 3, 0.1, 10),
        PreviewCamera("three_quarter", (5, 2, 5), (0, 0, 0), 4, 0.1, 15),
    )


def test_prepare_creates_separate_owned_project_and_preserves_inputs(tmp_path):
    source = tmp_path / "source.glb"
    budget = tmp_path / "budget.json"
    output = tmp_path / "result"
    _glb(source)
    budget.write_text('{"render/total_draw_calls_in_frame":{"stat":"max","max":8}}')
    original = source.read_bytes()

    project, digest = PreviewFiles().prepare(source, output, budget)
    try:
        assert output.is_dir()
        assert project.parent != output and not project.is_relative_to(output)
        assert (project / "model.glb").read_bytes() == original
        assert (project / "budget.json").read_bytes() == budget.read_bytes()
        assert (project / "preview.tscn").is_file()
        assert (project / "preview.gd").is_file()
        assert len(digest) == 64
        assert source.read_bytes() == original
    finally:
        PreviewFiles().remove_project(project)

    assert output.is_dir()
    assert not project.exists()


def test_prepare_refuses_external_glb_references_and_existing_output(tmp_path):
    source = tmp_path / "source.glb"
    _glb(source, external_uri="texture.png")
    output = tmp_path / "result"

    with pytest.raises(PortFailure, match="self-contained"):
        PreviewFiles().prepare(source, output, None)
    assert not output.exists()

    _glb(source)
    output.mkdir()
    marker = output / "keep"
    marker.write_text("owned by caller")
    with pytest.raises(PortFailure, match="already exists"):
        PreviewFiles().prepare(source, output, None)
    assert marker.read_text() == "owned by caller"


def test_prepare_refuses_png_before_creating_preview_files(tmp_path):
    from PIL import Image

    source = tmp_path / "image.png"
    Image.new("RGBA", (2, 2)).save(source)
    output = tmp_path / "result"

    with pytest.raises(PortFailure, match="GLB"):
        project, _ = PreviewFiles().prepare(source, output, None)
        PreviewFiles().remove_project(project)
    assert not output.exists()


def test_prepare_failure_cleans_only_new_empty_output_and_temporary_project(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.glb"
    _glb(source)
    output = tmp_path / "result"

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr("gda_assets.adapters.preview_files.shutil.copyfile", fail_copy)
    with pytest.raises(PortFailure, match="prepare"):
        PreviewFiles().prepare(source, output, None)

    assert not output.exists()


def test_configure_writes_bounded_views_and_actual_viewport_settings(tmp_path):
    source = tmp_path / "source.glb"
    output = tmp_path / "result"
    _glb(source)
    files = PreviewFiles()
    project, _ = files.prepare(source, output, None)
    try:
        settings = PreviewSettings(width=800, height=600, padding=1.25)
        files.configure(project, settings, _cameras())

        configuration = json.loads((project / "preview.json").read_text())
        assert configuration["settings"] == {
            "width": 800,
            "height": 600,
            "padding": 1.25,
        }
        assert [view["name"] for view in configuration["views"]] == [
            "front",
            "side",
            "three_quarter",
        ]
        project_settings = (project / "project.godot").read_text()
        assert 'run/main_scene="res://preview.tscn"' in project_settings
        assert "window/size/viewport_width=800" in project_settings
        assert 'renderer/rendering_method="gl_compatibility"' in project_settings
    finally:
        files.remove_project(project)


def test_remove_project_refuses_a_directory_it_does_not_own(tmp_path):
    project = tmp_path / "caller-project"
    project.mkdir()
    keep = project / "keep"
    keep.write_text("caller data")

    with pytest.raises(PortFailure, match="unowned"):
        PreviewFiles().remove_project(project)

    assert keep.read_text() == "caller data"


def test_fixture_declares_imported_child_and_rendered_view_state():
    fixture = Path(__file__).parents[1] / "src/gda_assets/adapters/preview_fixture"
    scene = (fixture / "preview.tscn").read_text()
    script = (fixture / "preview.gd").read_text()

    assert 'path="res://model.glb"' in scene
    assert 'name="Model" parent="." instance=' in scene
    assert "@export var view_index" in script
    assert "@export var applied_view" in script
    assert "@export var view_state: Dictionary" in script
    assert "await get_tree().process_frame" in script
    applied = script.index("\tapplied_view = index")
    assert script.rfind("\t_publish_view_state", 0, applied) != -1
    assert '"pose": "static_imported"' in script
    assert '"overlays": []' in script
