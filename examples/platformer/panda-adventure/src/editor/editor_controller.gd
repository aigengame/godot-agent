extends Node2D

## The Panda Adventure Editor — the in-game tool-mode director (gADR-0012).
##
## A SEPARATE entry scene (scenes/editor.tscn) of the same Godot project — the
## game's default entry (main.tscn) is untouched. It loads Level 1's JSON
## authorities for editing (EditorLevelModel), lets a human directly manipulate
## the spatial content — platform segments (move + resize), the Arena interval
## (drag its bounds), the backdrop, and the Wave/Spawn roster positions (drag the
## markers) — SAVES by writing ONLY the JSON authority, re-derives the Resources
## through the ONE Python builder (EditorBuilder -> scripts/build_config.py, never
## a GDScript re-derivation), and switches instantly between edit and play by
## instancing the game's own level flow (main.tscn) against the freshly derived
## Resources (WYSIWYG through the game's own rendering — gADR-0012).
##
## Keys: Tab = toggle edit<->play, S = save + re-derive, Esc = deselect.
## Direct manipulation: left-drag a segment body to move it, its yellow corner
## handle to resize (snapped to the tile grid so the Scale-spec semantic gate
## stays satisfied), an Arena line to move that bound, a spawn marker to reposition
## that spawn. Numeric forms and the debug palette are a later slice (#441).
##
## preload() over the global class_name registry: this project ships no
## editor-generated global_script_class_cache, so a bare type name would not
## resolve in a headless/plain runtime (the LevelController convention).

const EditorLevelModelScript := preload("res://src/editor/editor_level_model.gd")
const EditorBuilderScript := preload("res://src/editor/editor_builder.gd")
const GameLogScript := preload("res://src/util/game_log.gd")
const MainScene := preload("res://scenes/main.tscn")

const GENERATED_DIR := "res://data/generated"
const TILE := 16.0

# Hit-test / handle sizes, in WORLD units (the view is drawn in world space, so a
# handle reads a bit smaller on screen under the zoomed-out editor camera).
const SPAWN_RADIUS := 22.0
const HANDLE_HALF := 12.0
const HANDLE_RADIUS := 20.0
const ARENA_GRAB := 18.0
const ARENA_BAND_TOP := -80.0
const ARENA_BAND_BOTTOM := 640.0

# Hit kinds — what the cursor grabbed / what is selected.
const HIT_NONE := 0
const HIT_SEGMENT := 1
const HIT_SEGMENT_RESIZE := 2
const HIT_ARENA_MIN := 3
const HIT_ARENA_MAX := 4
const HIT_SPAWN := 5

# Per-wave marker palette (cycled) — a spawn's color tells which Wave it is in.
const WAVE_COLORS: Array[Color] = [
	Color(1.0, 0.6, 0.2),
	Color(0.3, 0.8, 1.0),
	Color(0.7, 0.5, 1.0),
	Color(1.0, 0.4, 0.6),
	Color(0.5, 1.0, 0.6),
]

# --- Live-inspectable state (readable via `gda game get --node . --property …`) ---
# The editor mode and a one-line summary; a live op can assert an edit took hold.
var is_playing := false
var status_line := ""
var last_action := "ready"

var _model: EditorLevelModelScript
# Selection (persists across drags) and the in-progress grab. Each is a
# {kind:int, a:int, b:int} record — a = segment or wave index, b = spawn index.
var _sel := {"kind": HIT_NONE, "a": -1, "b": -1}
var _active := {"kind": HIT_NONE, "a": -1, "b": -1}
var _dragging := false
var _drag_offset := Vector2.ZERO
var _play_instance: Node = null

@onready var _editor_camera: Camera2D = $EditorCamera
@onready var _play_host: Node = $PlayHost
@onready var _overlay_status: Label = $Overlay/Status
@onready var _overlay_help: Label = $Overlay/Help


func _ready() -> void:
	if OS.has_feature("template"):
		# Defense in depth (gADR-0012): the editor entry is EXCLUDED from player
		# builds by export_presets.cfg's exclude_filter, so this script is normally
		# absent from an export pack entirely. Should it ever be reached in a
		# template (exported) build, refuse — the editor is a dev-machine tool,
		# never a shipped mode.
		push_error("EditorController: the editor is not available in exported builds.")
		return
	_model = EditorLevelModelScript.new()
	if not _model.load_authorities():
		last_action = "load_failed"
		_set_status()
		push_error("EditorController: could not load Level 1 JSON authorities.")
		return
	RenderingServer.set_default_clear_color(_model.get_background_color())
	_set_status()
	queue_redraw()
	GameLogScript.emit("info", "editor_ready", {
		"platforms": _model.platform_count(),
		"waves": _model.wave_count(),
		"arena_min_x": _model.get_arena_min_x(),
		"arena_max_x": _model.get_arena_max_x(),
	})


# --- Input ---------------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_TAB:
				_toggle_play()
				get_viewport().set_input_as_handled()
				return
			KEY_S:
				if not is_playing:
					_save_and_derive()
					get_viewport().set_input_as_handled()
				return
			KEY_ESCAPE:
				if not is_playing:
					_sel = _none()
					queue_redraw()
					_set_status()
				return
	if is_playing or _model == null:
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			_begin_drag(get_global_mouse_position())
		else:
			_end_drag()
	elif event is InputEventMouseMotion and _dragging:
		_update_drag(get_global_mouse_position())


func _begin_drag(world: Vector2) -> void:
	var hit := _hit_test(world)
	if hit["kind"] == HIT_NONE:
		_sel = _none()
		queue_redraw()
		_set_status()
		return
	_sel = hit
	_active = hit
	_dragging = true
	match hit["kind"]:
		HIT_SPAWN:
			_drag_offset = _model.get_spawn_position(hit["a"], hit["b"]) - world
		HIT_SEGMENT:
			_drag_offset = _model.get_platform_center(hit["a"]) - world
		_:
			_drag_offset = Vector2.ZERO
	queue_redraw()
	_set_status()


func _update_drag(world: Vector2) -> void:
	match _active["kind"]:
		HIT_SPAWN:
			_model.set_spawn_position(_active["a"], _active["b"], _snap_int(world + _drag_offset))
		HIT_SEGMENT:
			_model.set_platform_center(_active["a"], _snap_int(world + _drag_offset))
		HIT_SEGMENT_RESIZE:
			var center := _model.get_platform_center(_active["a"])
			var size := _snap_tile((world - center).abs() * 2.0)
			size = Vector2(maxf(size.x, TILE), maxf(size.y, TILE))
			_model.set_platform_size(_active["a"], size)
		HIT_ARENA_MIN:
			_model.set_arena_min_x(minf(roundf(world.x), _model.get_arena_max_x() - TILE))
		HIT_ARENA_MAX:
			_model.set_arena_max_x(maxf(roundf(world.x), _model.get_arena_min_x() + TILE))
	last_action = "edit:" + _kind_name(_active["kind"])
	queue_redraw()
	_set_status()


func _end_drag() -> void:
	_dragging = false
	_active = _none()


func _hit_test(world: Vector2) -> Dictionary:
	# 1. The resize handle of the currently selected segment (so a corner grab
	#    beats re-selecting the body under it).
	if _sel["kind"] == HIT_SEGMENT or _sel["kind"] == HIT_SEGMENT_RESIZE:
		var idx: int = _sel["a"]
		var corner := _model.get_platform_center(idx) + _model.get_platform_size(idx) / 2.0
		if world.distance_to(corner) <= HANDLE_RADIUS:
			return {"kind": HIT_SEGMENT_RESIZE, "a": idx, "b": 0}
	# 2. Spawn markers (they sit ON platforms — grab them first).
	for w in range(_model.wave_count()):
		for s in range(_model.spawn_count(w)):
			if world.distance_to(_model.get_spawn_position(w, s)) <= SPAWN_RADIUS:
				return {"kind": HIT_SPAWN, "a": w, "b": s}
	# 3. Arena bound lines.
	if world.y >= ARENA_BAND_TOP and world.y <= ARENA_BAND_BOTTOM:
		if absf(world.x - _model.get_arena_min_x()) <= ARENA_GRAB:
			return {"kind": HIT_ARENA_MIN, "a": 0, "b": 0}
		if absf(world.x - _model.get_arena_max_x()) <= ARENA_GRAB:
			return {"kind": HIT_ARENA_MAX, "a": 0, "b": 0}
	# 4. Segment bodies, topmost (last drawn) first.
	for i in range(_model.platform_count() - 1, -1, -1):
		if _segment_rect(i).has_point(world):
			return {"kind": HIT_SEGMENT, "a": i, "b": 0}
	return _none()


# --- Save + derive + edit<->play ----------------------------------------------

func _save_and_derive() -> void:
	if not _model.save():
		last_action = "save_failed"
		_set_status()
		return
	GameLogScript.emit("info", "editor_saved", {
		"platforms": _model.platform_count(),
		"waves": _model.wave_count(),
	})
	var result: Dictionary = EditorBuilderScript.run()
	if result["ok"]:
		last_action = "derived"
		GameLogScript.emit("info", "editor_derived", {
			"exit_code": result["exit_code"],
			"python": result["python"],
		})
	else:
		last_action = "derive_failed"
		GameLogScript.emit("error", "editor_derive_failed", {
			"exit_code": result["exit_code"],
			"python": result["python"],
		})
		push_error(
			("EditorController: build_config.py failed (exit %d via %s). A Python " +
			"toolchain must be on PATH (gADR-0012). Output: %s")
			% [result["exit_code"], result["python"], result["output"]]
		)
	_set_status()


func _toggle_play() -> void:
	if is_playing:
		_exit_play()
	else:
		_enter_play()


func _enter_play() -> void:
	# Play the EDITED level: persist + re-derive any pending edits so main.tscn's
	# LevelController loads the fresh Resources, then refresh the process resource
	# cache (load() is cached, so a second edit->play would otherwise re-instance
	# against a STALE .tres).
	if _model.dirty:
		_save_and_derive()
	_refresh_generated_cache()
	_play_instance = MainScene.instantiate()
	_play_host.add_child(_play_instance)
	is_playing = true
	_overlay_help.visible = false
	queue_redraw()
	_set_status()
	GameLogScript.emit("info", "editor_play_entered", {})


func _exit_play() -> void:
	if _play_instance != null:
		_play_instance.queue_free()
		_play_instance = null
	is_playing = false
	_overlay_help.visible = true
	# The play instance freed its Player Camera2D; restore the editor framing and
	# the backdrop the game's LevelController overwrote.
	_editor_camera.make_current()
	RenderingServer.set_default_clear_color(_model.get_background_color())
	queue_redraw()
	_set_status()
	GameLogScript.emit("info", "editor_play_exited", {})


func _refresh_generated_cache() -> void:
	var dir := DirAccess.open(GENERATED_DIR)
	if dir == null:
		return
	dir.list_dir_begin()
	var entry := dir.get_next()
	while entry != "":
		if not dir.current_is_dir() and entry.ends_with(".tres"):
			ResourceLoader.load(
				"%s/%s" % [GENERATED_DIR, entry], "", ResourceLoader.CACHE_MODE_REPLACE
			)
		entry = dir.get_next()
	dir.list_dir_end()


# --- Rendering (the editable blockout; WYSIWYG comes from play) ----------------

func _draw() -> void:
	if is_playing or _model == null:
		return
	var font := ThemeDB.fallback_font
	_draw_arena(font)
	_draw_segments(font)
	_draw_spawns(font)


func _draw_arena(font: Font) -> void:
	_draw_arena_line(font, _model.get_arena_min_x(), _sel["kind"] == HIT_ARENA_MIN, "arena_min")
	_draw_arena_line(font, _model.get_arena_max_x(), _sel["kind"] == HIT_ARENA_MAX, "arena_max")


func _draw_arena_line(font: Font, x: float, selected: bool, label: String) -> void:
	var color := Color.YELLOW if selected else Color(0.9, 0.9, 0.4, 0.7)
	draw_line(Vector2(x, ARENA_BAND_TOP), Vector2(x, ARENA_BAND_BOTTOM), color, 2.0)
	draw_string(font, Vector2(x + 4, ARENA_BAND_TOP + 24), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 20, color)


func _draw_segments(font: Font) -> void:
	var fill := _model.get_platform_color()
	for i in range(_model.platform_count()):
		var rect := _segment_rect(i)
		draw_rect(rect, fill, true)
		var selected: bool = (_sel["kind"] == HIT_SEGMENT or _sel["kind"] == HIT_SEGMENT_RESIZE) and _sel["a"] == i
		draw_rect(rect, Color.WHITE if selected else Color(1, 1, 1, 0.35), false, 2.0)
		draw_string(font, rect.position + Vector2(4, 22), _model.get_platform_name(i), HORIZONTAL_ALIGNMENT_LEFT, -1, 20, Color(1, 1, 1, 0.85))
		if selected:
			var corner := rect.position + rect.size
			draw_rect(Rect2(corner - Vector2(HANDLE_HALF, HANDLE_HALF), Vector2(HANDLE_HALF * 2.0, HANDLE_HALF * 2.0)), Color.YELLOW)


func _draw_spawns(font: Font) -> void:
	for w in range(_model.wave_count()):
		var color := WAVE_COLORS[w % WAVE_COLORS.size()]
		for s in range(_model.spawn_count(w)):
			var p := _model.get_spawn_position(w, s)
			var selected: bool = _sel["kind"] == HIT_SPAWN and _sel["a"] == w and _sel["b"] == s
			draw_circle(p, SPAWN_RADIUS, color)
			draw_arc(p, SPAWN_RADIUS, 0.0, TAU, 24, Color.WHITE if selected else Color(0, 0, 0, 0.6), 2.0)
			draw_string(font, p + Vector2(SPAWN_RADIUS + 2.0, 6.0), "W%d:%s" % [w + 1, _model.get_spawn_label(w, s)], HORIZONTAL_ALIGNMENT_LEFT, -1, 18, color)


func _segment_rect(index: int) -> Rect2:
	var size := _model.get_platform_size(index)
	return Rect2(_model.get_platform_center(index) - size / 2.0, size)


# --- Status + helpers ----------------------------------------------------------

func _set_status() -> void:
	var mode := "PLAY" if is_playing else "EDIT"
	var mark := "*" if _model != null and _model.dirty else ""
	status_line = "[%s]%s  sel:%s  last:%s" % [mode, mark, _selection_text(), last_action]
	if _overlay_status != null:
		_overlay_status.text = status_line


func _selection_text() -> String:
	match _sel["kind"]:
		HIT_SEGMENT, HIT_SEGMENT_RESIZE:
			return "seg:" + _model.get_platform_name(_sel["a"])
		HIT_SPAWN:
			return "spawn:W%d:%s" % [_sel["a"] + 1, _model.get_spawn_label(_sel["a"], _sel["b"])]
		HIT_ARENA_MIN:
			return "arena_min"
		HIT_ARENA_MAX:
			return "arena_max"
		_:
			return "none"


func _kind_name(kind: int) -> String:
	match kind:
		HIT_SEGMENT: return "segment"
		HIT_SEGMENT_RESIZE: return "resize"
		HIT_ARENA_MIN: return "arena_min"
		HIT_ARENA_MAX: return "arena_max"
		HIT_SPAWN: return "spawn"
		_: return "none"


func _snap_int(v: Vector2) -> Vector2:
	return Vector2(roundf(v.x), roundf(v.y))


func _snap_tile(v: Vector2) -> Vector2:
	return Vector2(roundf(v.x / TILE) * TILE, roundf(v.y / TILE) * TILE)


func _none() -> Dictionary:
	return {"kind": HIT_NONE, "a": -1, "b": -1}
