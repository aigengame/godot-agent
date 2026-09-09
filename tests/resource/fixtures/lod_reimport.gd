extends SceneTree

# Two small, maintained GLB sources for native importer verification. The sphere
# has enough geometry for Godot's importer to generate LODs. The triangle is the
# enabled-but-zero control: generate_lods can be retained without producing one.
func _initialize() -> void:
	_export_mesh("lod_model.glb", _sphere())
	_export_mesh("zero_lod_model.glb", _triangle())
	quit()


func _sphere() -> Mesh:
	var sphere := SphereMesh.new()
	sphere.radial_segments = 32
	sphere.rings = 16
	return sphere


func _triangle() -> Mesh:
	var mesh := ArrayMesh.new()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
		Vector3.ZERO, Vector3.RIGHT, Vector3.UP])
	arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2])
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh


func _export_mesh(path: String, mesh: Mesh) -> void:
	var root := Node3D.new()
	root.name = "Fixture"
	var instance := MeshInstance3D.new()
	instance.name = "Geometry"
	instance.mesh = mesh
	root.add_child(instance)
	instance.owner = root
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	assert(document.append_from_scene(root, state) == OK)
	assert(document.write_to_filesystem(state, "res://" + path) == OK)
	root.free()
