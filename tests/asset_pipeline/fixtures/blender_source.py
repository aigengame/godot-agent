"""Run inside Blender to create an independent saved-source fixture."""

import sys

import bpy  # pyright: ignore[reportMissingImports]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "AssetScene"
root = bpy.data.objects.new("AssetRoot", None)
scene.collection.objects.link(root)
root.location = (5, 0, 0)

bpy.ops.mesh.primitive_cube_add(size=2)
body = bpy.context.object
body.name = "Body"
body.parent = root
body.location = (0, 0, 0)
body.scale = (1, 2, 3)

bpy.ops.mesh.primitive_cube_add(size=2)
detail = bpy.context.object
detail.name = "HiddenDetail"
detail.parent = root
detail.location = (3, 0, 0)
detail.hide_set(True)
detail.hide_render = True

bpy.ops.mesh.primitive_cube_add(size=100)
studio = bpy.context.object
studio.name = "UnrelatedStudio"
studio.location = (50, 50, 50)
if sys.argv[-1] == "animated":
    for frame in (1, 10):
        root.keyframe_insert(data_path="scale", frame=frame)
elif sys.argv[-1] == "empty":
    for obj in (body, detail):
        bpy.data.objects.remove(obj, do_unlink=True)
elif sys.argv[-1] == "ambiguous":
    from pathlib import Path

    library = str(Path(sys.argv[sys.argv.index("--") + 1]).with_name("linked.blend"))
    bpy.data.libraries.write(library, {root})
    with bpy.data.libraries.load(library, link=True) as (source_data, target_data):
        target_data.objects = ["AssetRoot"]
    scene.collection.objects.link(target_data.objects[0])
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
