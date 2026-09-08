"""Executed by a separate Blender process; never imported by gda discovery."""

import json
import math
from pathlib import Path
import sys

import bpy  # pyright: ignore[reportMissingImports]
from mathutils import Vector  # pyright: ignore[reportMissingImports]


def bounds(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        if evaluated.type == "MESH":
            points.extend(
                evaluated.matrix_world @ Vector(corner)
                for corner in evaluated.bound_box
            )
    if not points or any(
        not math.isfinite(value) for point in points for value in point
    ):
        raise ValueError("Selected subtree has no finite evaluated mesh bounds")
    lower = [min(point[i] for point in points) for i in range(3)]
    upper = [max(point[i] for point in points) for i in range(3)]
    return {"position": lower, "size": [upper[i] - lower[i] for i in range(3)]}


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    result = {
        "stage": "inspect",
        "blender_version": bpy.app.version_string,
        "scene": request["scene"],
        "root": request["root"],
        "completed": [],
    }
    try:
        scenes = [item for item in bpy.data.scenes if item.name == request["scene"]]
        if len(scenes) != 1:
            raise ValueError("Selected Blender scene is absent or ambiguous")
        scene = scenes[0]
        bpy.context.window.scene = scene
        roots = [item for item in scene.objects if item.name == request["root"]]
        if len(roots) != 1:
            raise ValueError(
                "Selected root is absent or ambiguous in the selected scene"
            )
        root = roots[0]
        objects = [root, *root.children_recursive]
        if len(objects) > 1024 or any(obj.name not in scene.objects for obj in objects):
            raise ValueError(
                "Selected subtree exceeds 1024 objects or crosses scene membership"
            )
        for obj in scene.objects:
            obj.select_set(False)
        for obj in objects:
            if obj.name not in bpy.context.view_layer.objects:
                raise ValueError(
                    "Selected subtree contains an object excluded from the view layer"
                )
            obj.hide_set(False)
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_select = False
            obj.select_set(True)
        bpy.context.view_layer.objects.active = root
        bpy.context.view_layer.update()
        result["objects"] = [{"name": obj.name, "type": obj.type} for obj in objects]
        result["measurement"] = {
            "basis": "evaluated_mesh_world_aabb",
            "coordinates": "Blender Z-up world",
            "frame": scene.frame_current,
            "unit_scale": scene.unit_settings.scale_length,
            "view_layer": bpy.context.view_layer.name,
        }
        result["before"] = bounds(objects)
        result["completed"].append("inspect")
        result["stage"] = "prepare"
        if request["uniform_scale"] != 1 and root.animation_data is not None:
            raise ValueError(
                "Export scaling of an animated or driven root is unsupported"
            )
        root.scale *= request["uniform_scale"]
        bpy.context.view_layer.update()
        result["after"] = bounds(objects)
        if any(
            not math.isclose(
                after, before * request["uniform_scale"], rel_tol=1e-5, abs_tol=1e-6
            )
            for before, after in zip(result["before"]["size"], result["after"]["size"])
        ):
            raise ValueError(
                "Selected evaluated bounds did not follow the requested uniform scale"
            )
        result["uniform_scale"] = request["uniform_scale"]
        result["completed"].append("prepare")
        result["stage"] = "export"
        options = {
            "filepath": request["output"],
            "export_format": "GLB",
            "use_selection": True,
            "use_active_scene": True,
            "use_visible": False,
            "use_renderable": False,
            "export_yup": True,
            "export_cameras": False,
            "export_lights": False,
            "export_animations": request["export"]["animations"],
            "export_materials": request["export"]["materials"],
            "export_apply": request["export"]["apply_modifiers"],
        }
        available = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
        missing = set(options) - set(available)
        if missing:
            raise ValueError(
                "Exporter lacks required options: " + ", ".join(sorted(missing))
            )
        if bpy.ops.export_scene.gltf(**options) != {"FINISHED"}:
            raise ValueError("glTF exporter did not finish")
        result["export_options"] = {
            key: value for key, value in options.items() if key != "filepath"
        }
        result["completed"].append("export")
    except Exception as exc:
        result["failure"] = str(exc)[:4096]
    Path(request["result"]).write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
