extends SceneTree

# Save a supported import option through Godot's ConfigFile API while leaving
# one default absent. The test observes that line after the next real import;
# the endpoint reads do not attribute a writer or establish equivalence.
func _initialize() -> void:
	var path := "res://models/model.glb.import"
	var config := ConfigFile.new()
	assert(config.load(path) == OK)
	config.set_value("params", "meshes/generate_lods", false)
	config.erase_section_key("params", "nodes/root_script")
	assert(config.save(path) == OK)
	quit()
