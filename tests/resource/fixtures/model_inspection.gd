extends SceneTree

# Independent fixture geometry: one triangle shared by three mesh instances.
# The selected Body subtree has two instances; Studio is deliberately unrelated.
func _initialize() -> void:
	var root := Node3D.new()
	root.name = "Model"
	var mesh := ArrayMesh.new()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
		Vector3(-1, -1, 0), Vector3(1, -1, 0), Vector3(-1, 1, 0)])
	arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2])
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var material := StandardMaterial3D.new()
	material.resource_name = "Base"
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	image.fill(Color.RED)
	material.albedo_texture = ImageTexture.create_from_image(image)
	mesh.surface_set_material(0, material)
	var asset := Node3D.new()
	asset.name = "Asset"
	root.add_child(asset)
	asset.owner = root
	var body := MeshInstance3D.new()
	body.name = "Body"
	body.mesh = mesh
	body.position = Vector3(2, 0, 0)
	asset.add_child(body)
	body.owner = root
	var detail := MeshInstance3D.new()
	detail.name = "Detail"
	detail.mesh = mesh
	detail.position = Vector3(0, 3, 0)
	body.add_child(detail)
	detail.owner = root
	var studio := Node3D.new()
	studio.name = "Studio"
	root.add_child(studio)
	studio.owner = root
	var other := MeshInstance3D.new()
	other.name = "Body"
	other.mesh = mesh
	other.position = Vector3(100, 0, 0)
	studio.add_child(other)
	other.owner = root
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	assert(document.append_from_scene(root, state) == OK)
	assert(document.write_to_filesystem(state, "res://model.glb") == OK)
	root.free()
	quit()
