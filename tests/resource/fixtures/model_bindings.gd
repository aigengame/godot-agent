extends SceneTree

# Authored PackedScene preserves deliberately broken bindings that glTF exporters
# are allowed to discard. Two Body names make short-name matching insufficient.
func _initialize() -> void:
	var root := Node3D.new()
	root.name = "Model"
	var rig := Skeleton3D.new()
	rig.name = "Rig"
	root.add_child(rig)
	rig.owner = root
	rig.add_bone("RootBone")
	rig.add_bone("Arm_L")
	rig.set_bone_parent(1, 0)
	rig.set_bone_rest(1, Transform3D(Basis.IDENTITY, Vector3(0, 2, 0)))
	var body := MeshInstance3D.new()
	body.name = "Body"
	body.mesh = BoxMesh.new()
	body.skeleton = NodePath("../Rig")
	var skin := Skin.new()
	skin.add_named_bind("Arm_L", Transform3D.IDENTITY)
	skin.add_bind(0, Transform3D.IDENTITY)
	skin.add_named_bind("MissingBone", Transform3D.IDENTITY)
	body.skin = skin
	root.add_child(body)
	body.owner = root
	var studio := Node3D.new()
	studio.name = "Studio"
	root.add_child(studio)
	studio.owner = root
	var duplicate := Node3D.new()
	duplicate.name = "Body"
	studio.add_child(duplicate)
	duplicate.owner = root
	var player := AnimationPlayer.new()
	player.name = "AnimationPlayer"
	root.add_child(player)
	player.owner = root
	var animation := Animation.new()
	animation.length = 1.25
	for target in ["Body", "Studio/Body", "Rig:Arm_L", "Rig:MissingBone", "Missing/Body"]:
		var track := animation.add_track(Animation.TYPE_POSITION_3D)
		animation.track_set_path(track, NodePath(target))
		animation.track_insert_key(track, 0.0, Vector3.ZERO)
	for target in ["Body:position", "Body:mesh:size", "Body:missing"]:
		var track := animation.add_track(Animation.TYPE_VALUE)
		animation.track_set_path(track, NodePath(target))
		animation.track_insert_key(track, 0.0, Vector3.ONE)
	var library := AnimationLibrary.new()
	library.add_animation("Walk", animation)
	player.add_animation_library("", library)
	var packed := PackedScene.new()
	assert(packed.pack(root) == OK)
	assert(ResourceSaver.save(packed, "res://bindings.tscn") == OK)
	# A separate valid, weighted glTF proves the real imported skin path. Broken
	# authored bindings above remain unchanged in their saved PackedScene.
	var mesh := ArrayMesh.new()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3.ZERO, Vector3.RIGHT, Vector3.UP])
	arrays[Mesh.ARRAY_BONES] = PackedInt32Array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
	arrays[Mesh.ARRAY_WEIGHTS] = PackedFloat32Array([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	body.mesh = mesh
	skin.set_bind_name(2, "Arm_L")
	for index in range(animation.get_track_count() - 1, 4, -1):
		animation.remove_track(index)
	animation.remove_track(4)
	animation.remove_track(3)
	for track in animation.get_track_count():
		animation.track_insert_key(track, 1.25, Vector3(0, 1, 0))
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	assert(document.append_from_scene(root, state) == OK)
	assert(document.write_to_filesystem(state, "res://skinned.glb") == OK)
	root.free()
	quit()
