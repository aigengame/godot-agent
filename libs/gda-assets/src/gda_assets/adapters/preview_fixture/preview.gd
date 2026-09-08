extends Node3D

const BACKGROUND := Color(0.08, 0.1, 0.14, 1.0)
const AMBIENT_ENERGY := 0.65
const LIGHT_ENERGY := 1.4
const LIGHT_ROTATION := Vector3(-45.0, -35.0, 0.0)

@export var view_index := 0:
	set(value):
		view_index = value
		applied_view = -1
		call_deferred("_apply_after_frame", value)
@export var applied_view := -1
@export var view_state: Dictionary = {}

var _camera: Camera3D
var _environment: Environment
var _light: DirectionalLight3D
var _views: Array
var _target_distance := 0.0


func _enter_tree() -> void:
	# The declared imported child already exists here, before it enters the tree.
	# Disable its processing and animation players before scene entry establishes
	# the static imported pose used by this fixture.
	_freeze_imported($Model)


func _ready() -> void:
	var parsed: Variant = JSON.parse_string(
		FileAccess.get_file_as_string("res://preview.json")
	)
	if not parsed is Dictionary or not parsed.has("views"):
		push_error("Preview configuration is missing or invalid")
		return
	_views = parsed["views"]
	if _views.size() != 3:
		push_error("Preview configuration must contain three views")
		return
	_environment = Environment.new()
	_environment.background_mode = Environment.BG_COLOR
	_environment.background_color = BACKGROUND
	_environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	_environment.ambient_light_color = Color.WHITE
	_environment.ambient_light_energy = AMBIENT_ENERGY
	var world_environment := WorldEnvironment.new()
	world_environment.environment = _environment
	add_child(world_environment)
	_light = DirectionalLight3D.new()
	_light.rotation_degrees = LIGHT_ROTATION
	_light.light_energy = LIGHT_ENERGY
	add_child(_light)
	_camera = Camera3D.new()
	_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	_camera.keep_aspect = Camera3D.KEEP_HEIGHT
	_camera.current = true
	add_child(_camera)
	_apply_view(0)


func _freeze_imported(node: Node) -> void:
	node.process_mode = Node.PROCESS_MODE_DISABLED
	if node is AnimationPlayer:
		node.active = false
		node.stop(false)
	for child in node.get_children():
		_freeze_imported(child)


func _apply_after_frame(index: int) -> void:
	await get_tree().process_frame
	_apply_view(index)


func _apply_view(index: int) -> void:
	if index < 0 or index >= _views.size():
		return
	var item: Dictionary = _views[index]
	var position := _vector3(item["position"])
	var target := _vector3(item["target"])
	var up := _vector3(item["up"])
	_camera.position = position
	_camera.size = float(item["size"])
	_camera.near = float(item["near"])
	_camera.far = float(item["far"])
	_camera.look_at(target, up)
	_target_distance = _camera.global_position.distance_to(target)
	await get_tree().process_frame
	_publish_view_state(index, String(item["name"]))
	applied_view = index


func _publish_view_state(index: int, name: String) -> void:
	# Camera3D stores an orientation, not a target. Reproject the actual -Z
	# direction at the configured target distance so a failed look_at cannot be
	# hidden by echoing the requested target. Basis Y is the canonicalized up.
	var actual_target := (
		_camera.global_position - _camera.global_basis.z * _target_distance
	)
	view_state = {
		"index": index,
		"camera": {
			"name": name,
			"position": _array3(_camera.global_position),
			"target": _array3(actual_target),
			"size": _camera.size,
			"near": _camera.near,
			"far": _camera.far,
			"up": _array3(_camera.global_basis.y),
		},
		"viewport": [get_viewport().size.x, get_viewport().size.y],
		"renderer": RenderingServer.get_current_rendering_method(),
		"engine": String(Engine.get_version_info()["string"]),
		"platform": OS.get_name(),
		"pose": "static_imported",
		"background": [
			_environment.background_color.r,
			_environment.background_color.g,
			_environment.background_color.b,
			_environment.background_color.a,
		],
		"ambient_energy": _environment.ambient_light_energy,
		"light_energy": _light.light_energy,
		"light_rotation": _array3(_light.rotation_degrees),
		"overlays": [],
	}


func _vector3(value: Array) -> Vector3:
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


func _array3(value: Vector3) -> Array:
	return [value.x, value.y, value.z]
