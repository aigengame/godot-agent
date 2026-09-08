"""Bounded Blender reference blockout worker, executed in a separate process."""

import hashlib
import json
from pathlib import Path
import sys

import bpy  # pyright: ignore[reportMissingImports]


def _sample_color(image) -> list[float]:
    """Return an alpha-weighted color from at most 64 decoded image pixels."""
    width, height = image.size
    columns = min(8, width)
    rows = min(8, height)
    coordinates = [
        (
            0 if columns == 1 else round(x * (width - 1) / (columns - 1)),
            0 if rows == 1 else round(y * (height - 1) / (rows - 1)),
        )
        for y in range(rows)
        for x in range(columns)
    ]
    pixels = image.pixels
    values = []
    for x, y in coordinates:
        offset = (y * width + x) * 4
        values.append(tuple(float(pixels[offset + channel]) for channel in range(4)))
    alpha = sum(value[3] for value in values)
    if alpha > 0:
        rgb = [
            sum(value[channel] * value[3] for value in values) / alpha
            for channel in range(3)
        ]
    else:
        rgb = [
            sum(value[channel] for value in values) / len(values)
            for channel in range(3)
        ]
    return [*rgb, sum(value[3] for value in values) / len(values)]


def main() -> None:
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    reference = Path(request["reference"])
    output = Path(request["output"])
    result_path = Path(request["result"])
    result = {"stage": "read_reference", "completed": []}
    try:
        raw = reference.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        result["completed"].append("read_reference")
        result["stage"] = "decode_reference"
        image = bpy.data.images.load(str(reference), check_existing=False)
        color = _sample_color(image)
        width, height = (int(value) for value in image.size)
        if not image.has_data or width < 1 or height < 1:
            raise ValueError("Selected concept did not decode to a nonempty image")
        result["completed"].append("decode_reference")

        result["stage"] = "create_reference"
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        reference_object = bpy.data.objects.new("SelectedConceptReference", None)
        reference_object.empty_display_type = "IMAGE"
        reference_object.data = image
        bpy.context.scene.collection.objects.link(reference_object)
        result["completed"].append("create_reference")

        result["stage"] = "create_blockout"
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.mesh.primitive_cube_add()
        blockout = bpy.context.object
        blockout.name = "ReferenceBlockout"
        material = bpy.data.materials.new("ReferenceColor")
        material.diffuse_color = color
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is None or "Base Color" not in principled.inputs:
            raise ValueError("Blender lacks the required Principled Base Color input")
        principled.inputs["Base Color"].default_value = color
        blockout.data.materials.append(material)
        result["completed"].append("create_blockout")

        result["stage"] = "save"
        blend = output / "reference-blockout.blend"
        glb = output / "reference-blockout.glb"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        result["completed"].append("save_blend")
        result["stage"] = "export"
        if bpy.ops.export_scene.gltf(
            filepath=str(glb),
            export_format="GLB",
            use_selection=True,
            export_materials="EXPORT",
            export_animations=False,
            export_cameras=False,
            export_lights=False,
        ) != {"FINISHED"}:
            raise ValueError("Blender GLB export did not finish")
        result["completed"].append("export_glb")
        result.update(
            {
                "stage": "complete",
                "reference_sha256": digest,
                "reference_width": width,
                "reference_height": height,
                "reference_object": reference_object.name,
                "reference_loaded": reference_object.data == image,
                "material_color": color,
                "scene_objects": sorted(obj.name for obj in bpy.context.scene.objects),
                "blend": str(blend),
                "glb": str(glb),
                "blender_version": bpy.app.version_string,
            }
        )
    except Exception as exc:
        result["failure"] = str(exc)[:4096]
    result_path.write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
