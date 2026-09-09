"""Native effective-material precedence and bounded albedo content controls."""

import os

import pytest

from tests.conftest import project_godot
from tests.support import Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
]

SCRIPT = """extends Node3D
func _ready():
    var red := _texture(Color.RED)
    var blue := _texture(Color.BLUE)
    _model(self, "Plain", null)
    _model(self, "Red", red)
    _model(self, "Blue", blue)
    _model(self, "Rgb", _texture(Color.RED, Image.FORMAT_RGB8))
    _model(self, "Mipped", _texture(Color.RED, Image.FORMAT_RGBA8, true))
    var overridden := _model(self, "SurfaceOverride", red)
    overridden.set_surface_override_material(0, _material(blue))
    var global := _model(self, "GlobalOverride", blue)
    global.set_surface_override_material(0, _material(blue))
    global.material_override = _material(red)
    var normal := _model(self, "NormalResource", null)
    (normal.mesh.surface_get_material(0) as StandardMaterial3D).normal_texture = red
    _model(self, "Empty", ImageTexture.new())
    _model(self, "Procedural", GradientTexture2D.new())
    var viewport := SubViewport.new()
    viewport.size = Vector2i(2, 2)
    add_child(viewport)
    _model(self, "RenderTarget", viewport.get_texture())
    _model(self, "FloatFormat", _texture(Color.RED, Image.FORMAT_RGBAF))
    var script := GDScript.new()
    script.source_code = "extends ImageTexture\\n"
    assert(script.reload() == OK)
    var scripted := _texture(Color.RED)
    scripted.set_script(script)
    _model(self, "Scripted", scripted)
    var oversized := _texture(Color.RED)
    oversized.set_size_override(Vector2i(4097, 4097))
    _model(self, "PixelLimit", oversized)
    # One texture reused across surfaces must still consume per-read budgets.
    var shared := _texture(Color.RED, Image.FORMAT_RGBA8, true, 1024)
    var budget := Node3D.new()
    budget.name = "Repeated"
    add_child(budget)
    for i in range(17):
        _model(budget, "Part" + str(i), shared)

func _texture(color: Color, format := Image.FORMAT_RGBA8, mipmaps := false, size := 2) -> ImageTexture:
    var image := Image.create(size, size, false, format)
    image.fill(color)
    if mipmaps:
        image.generate_mipmaps()
    return ImageTexture.create_from_image(image)

func _material(texture: Texture2D) -> StandardMaterial3D:
    var material := StandardMaterial3D.new()
    material.albedo_texture = texture
    return material

func _model(parent: Node, model_name: String, texture: Texture2D) -> MeshInstance3D:
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3.ZERO, Vector3.RIGHT, Vector3.UP])
    arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2])
    var mesh := ArrayMesh.new()
    mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
    mesh.surface_set_material(0, _material(texture))
    var instance := MeshInstance3D.new()
    instance.name = model_name
    instance.mesh = mesh
    parent.add_child(instance)
    return instance
"""


def test_albedo_precedence_formats_and_repeated_read_budgets(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    (tmp_path / "project.godot").write_text(
        project_godot(
            name="gda-albedo-boundary-e2e",
            extra=(
                'run/main_scene="res://main.tscn"\n\n'
                '[rendering]\n\nrenderer/rendering_method="gl_compatibility"'
            ),
        )
    )
    (tmp_path / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n"
        '[ext_resource type="Script" path="res://main.gd" id="1"]\n'
        '[node name="Main" type="Node3D"]\nscript = ExtResource("1")\n'
    )
    (tmp_path / "main.gd").write_text(SCRIPT)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(tmp_path, json_output=True, timeout=120)

    def inspect(name):
        return run.json(
            "game", "inspect-model-content", "--node", f"/root/Main/{name}"
        )["content"]

    try:
        assert run("daemon", "start").returncode == 0
        run.json("daemon", "wait-ready")
        complete = {
            name: inspect(name)
            for name in (
                "Plain",
                "Red",
                "Blue",
                "Rgb",
                "Mipped",
                "SurfaceOverride",
                "GlobalOverride",
            )
        }
        for content in complete.values():
            assert content["complete"] is True, content
            assert len(content["digest"]) == 64
        assert complete["Red"]["digest"] != complete["Blue"]["digest"]
        assert complete["SurfaceOverride"]["digest"] == complete["Blue"]["digest"]
        assert complete["GlobalOverride"]["digest"] == complete["Red"]["digest"]
        assert complete["Rgb"]["digest"] != complete["Red"]["digest"]
        assert complete["Mipped"]["digest"] != complete["Red"]["digest"]
        for name in (
            "NormalResource",
            "Empty",
            "Procedural",
            "RenderTarget",
            "FloatFormat",
            "Scripted",
        ):
            unsupported = inspect(name)
            assert unsupported["complete"] is False
            assert unsupported["digest"] is None
            assert unsupported["unsupported"], (name, unsupported)
        pixel = inspect("PixelLimit")
        assert pixel["complete"] is False and pixel["digest"] is None
        assert any("albedo pixel limit" in reason for reason in pixel["omitted"])
        repeated = inspect("Repeated")
        assert repeated["complete"] is False and repeated["digest"] is None
        assert any("albedo pixel limit" in reason for reason in repeated["omitted"])
        assert any("albedo byte limit" in reason for reason in repeated["omitted"])
    finally:
        stopped = run("daemon", "stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
