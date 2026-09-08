extends SceneTree

# Generate a deterministic GLB with duplicate short names, a named material,
# skeleton bindings, and an animation target. The fixture is built by Godot so
# the check command is exercised against the real 3D import path.
func _initialize() -> void:
	var root := Node3D.new()
	root.name = "Model"

	var character := Node3D.new()
	character.name = "Character"
	root.add_child(character)
	character.owner = root

	var rig := Skeleton3D.new()
	rig.name = "Rig"
	character.add_child(rig)
	rig.owner = root
	rig.add_bone("RootBone")
	rig.add_bone("HandBone")
	rig.set_bone_parent(1, 0)
	rig.set_bone_rest(1, Transform3D(Basis.IDENTITY, Vector3(0, 1, 0)))

	var mesh := ArrayMesh.new()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
		Vector3(-1, -2, -0.5), Vector3(1, -2, -0.5), Vector3(-1, 2, 0.5),
		Vector3(1, 2, 0.5),
	])
	arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2, 1, 3, 2])
	arrays[Mesh.ARRAY_BONES] = PackedInt32Array([
		1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0,
	])
	arrays[Mesh.ARRAY_WEIGHTS] = PackedFloat32Array([
		1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0,
	])
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var material := StandardMaterial3D.new()
	material.resource_name = "LimbMaterial"
	mesh.surface_set_material(0, material)

	var limb := MeshInstance3D.new()
	limb.name = "Arm_L"
	limb.mesh = mesh
	limb.skeleton = NodePath("../Rig")
	var skin := Skin.new()
	skin.add_named_bind("HandBone", Transform3D.IDENTITY)
	limb.skin = skin
	character.add_child(limb)
	limb.owner = root

	var props := Node3D.new()
	props.name = "Props"
	root.add_child(props)
	props.owner = root
	var duplicate := MeshInstance3D.new()
	duplicate.name = "Arm_L"
	duplicate.mesh = mesh
	duplicate.position = Vector3(4, 0, 0)
	props.add_child(duplicate)
	duplicate.owner = root

	var player := AnimationPlayer.new()
	player.name = "AnimationPlayer"
	root.add_child(player)
	player.owner = root
	var animation := Animation.new()
	animation.length = 1.0
	var track := animation.add_track(Animation.TYPE_POSITION_3D)
	animation.track_set_path(track, NodePath("Character/Rig:HandBone"))
	animation.track_insert_key(track, 0.0, Vector3.ZERO)
	animation.track_insert_key(track, 1.0, Vector3(0, 1, 0))
	var library := AnimationLibrary.new()
	library.add_animation("Wave", animation)
	player.add_animation_library("", library)
	# PackedScene preserves the duplicate short names. The GLB importer makes
	# names globally unique, so this companion resource tests exact full paths.
	var packed := PackedScene.new()
	assert(packed.pack(root) == OK)
	assert(ResourceSaver.save(packed, "res://duplicate_names.tscn") == OK)

	var document := GLTFDocument.new()
	var state := GLTFState.new()
	assert(document.append_from_scene(root, state) == OK)
	assert(document.write_to_filesystem(state, "res://model.glb") == OK)
	root.free()
	quit()
