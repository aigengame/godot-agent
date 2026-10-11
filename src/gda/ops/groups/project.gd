extends "../op_base.gd"

# gda headless operations payload: the project command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")
const PROJECT_WALK := preload("../lib/project_walk.gd")
const SCENE_TEXT := preload("../lib/scene_text.gd")
const GDSCRIPT_SCAN := preload("../lib/gdscript_scan.gd")
const CLASS_INDEX := preload("../lib/class_index.gd")
const REFERENCE_GRAPH := preload("../lib/reference_graph.gd")


# The project-info settings (issue #111), read with a default so a project that
# never wrote them still reports a sensible value rather than failing: a new
# Godot 4 project has no explicit main_scene and inherits viewport defaults.
const PROJECT_NAME_SETTING := "application/config/name"
const PROJECT_MAIN_SCENE_SETTING := "application/run/main_scene"
const PROJECT_VIEWPORT_WIDTH_SETTING := "display/window/size/viewport_width"
const PROJECT_VIEWPORT_HEIGHT_SETTING := "display/window/size/viewport_height"

# project-create (issue #1027): the one file the op writes, and the engine-virtual
# schemes it refuses as a destination (the CLI passes them through unchanged, so
# the refusal is an operation error on both input channels).
#
# The schemes are spelled a second time in Python, as ENGINE_VIRTUAL_PREFIXES
# (src/gda/core/project/paths.py), which decides what the CLI passes through. The two
# spellings are held together by a test, not by derivation:
# `test_a_virtual_destination_is_invalid_path` (tests/project/test_e2e_project_create.py)
# takes its cases from the Python constant.
const PROJECT_CREATE_FILE := "project.godot"
const PROJECT_CREATE_VIRTUAL_PREFIXES := ["res://", "user://", "uid://"]

# Autoload singletons live under the "autoload/<name>" section of project.godot
# (issue #119). The value is the res:// path optionally prefixed with "*" to mean
# "enabled as a singleton" — the normal, accessible form gda writes.
const AUTOLOAD_SETTING_PREFIX := "autoload/"
const AUTOLOAD_ENABLED_PREFIX := "*"

# InputMap actions live under the "input/<name>" section of project.godot
# (issue #380). The value is a Dictionary of {deadzone, events} where the events
# are real InputEventKey Objects, persisted via ProjectSettings.save() so the
# serialization is exactly the engine's own var_to_str form.
const INPUT_SETTING_PREFIX := "input/"
# InputEvent.device is a 32-bit field: a larger int wraps on assignment (issue
# #842 review), so the op refuses it as the CLI does rather than storing a
# different device than the caller named.
const INPUT_EVENT_DEVICE_MAX := 2147483647


# project-info: report core project metadata — name, main scene, viewport size,
# and the engine version — as typed JSON (issue #111, the project-group tracer's
# read half). Reads ProjectSettings, which the engine populates from project.godot
# at startup; the engine version comes from Engine.get_version_info(), the same
# source gda info reports. The viewport/main-scene settings are read WITH A DEFAULT
# so a new project that never wrote them still reports a value (a fresh Godot 4
# project has no explicit main_scene and inherits the built-in viewport size)
# rather than failing.
#
# project-info needs a project: ProjectSettings without a resolved project would
# report only the engine's bare defaults, not the agent's project, so a projectless
# run is refused with project_not_found rather than returning a misleading result.
# Like every --project op it runs the project's autoloads at engine startup (#61,
# ADR-0009) — reading settings is a state-read at the operation level (it never
# instantiates a scene), but the startup autoload execution surface still applies.
func _op_project_info(_params: Dictionary) -> void:
	_diag("running operation: project-info")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project info requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	_succeed({
		"name": String(ProjectSettings.get_setting(PROJECT_NAME_SETTING, "")),
		"main_scene": String(ProjectSettings.get_setting(PROJECT_MAIN_SCENE_SETTING, "")),
		"viewport_width": int(ProjectSettings.get_setting(PROJECT_VIEWPORT_WIDTH_SETTING, 0)),
		"viewport_height": int(ProjectSettings.get_setting(PROJECT_VIEWPORT_HEIGHT_SETTING, 0)),
		"engine_version": Engine.get_version_info(),
	})


# project-create: create a minimal Godot project at a destination directory (issue
# #1027). The destination is an operation input, not the project this process runs
# against. The CLI starts this engine in an empty directory of its own (#1035), so
# ProjectSettings holds only engine defaults, and save_custom() — which merges the
# current settings into the file it writes — writes the name and what the engine
# writes on every save (config_version and the version feature). The CLI has made
# the destination absolute, because this engine's working directory is that empty
# directory.
#
# The destination is a new directory in an existing parent, or an existing
# directory that holds no entries other than dot-prefixed ones (Project Manager
# precedent: a directory after `git init` is accepted). The op creates only the
# destination itself, never a parent. When the request fails after it created
# something, it removes only what it created, and names on stderr (the envelope's
# diagnostics) each path it could not remove.
#
# The success condition is a read-back: ConfigFile, the engine's own parser, must
# return the name from the written file in this process. A name that the parser
# does not return unchanged (for example one that starts with U+FEFF, which the
# parser drops) is save_failed, and the file is removed.
func _op_project_create(params: Dictionary) -> void:
	_diag("running operation: project-create")
	var destination := VALUE._string_param(params, "destination")
	var name := VALUE._string_param(params, "name").strip_edges()
	if destination.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: destination")
		return
	for prefix in PROJECT_CREATE_VIRTUAL_PREFIXES:
		if destination.begins_with(prefix):
			_fail(OP_ERROR_INVALID_PATH, "project create requires a filesystem destination; "
					+ destination + " is an engine-virtual path")
			return
	if not destination.is_absolute_path():
		_fail(OP_ERROR_INVALID_PATH, "project create requires an absolute destination: " + destination)
		return
	if name.is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "project create requires a nonempty name; the name is"
				+ " empty after leading and trailing spaces and control characters are removed")
		return

	var project_file := destination.path_join(PROJECT_CREATE_FILE)
	var created_dirs: Array = []
	if DirAccess.dir_exists_absolute(destination):
		# project.godot is checked before the emptiness rule, and also where the
		# directory cannot be listed (a stat needs no read permission).
		var entries: Variant = _destination_entries(destination)
		if FileAccess.file_exists(project_file) \
				or (entries != null and (entries as PackedStringArray).has(PROJECT_CREATE_FILE)):
			_fail(OP_ERROR_ALREADY_EXISTS, "the destination already holds a project: " + project_file)
			return
		if entries == null:
			_fail(OP_ERROR_INVALID_PATH, "cannot list the destination directory: " + destination)
			return
		for entry in entries:
			if not String(entry).begins_with("."):
				_fail(OP_ERROR_DESTINATION_NOT_EMPTY, "the destination directory is not empty"
						+ " (it holds " + String(entry) + "): " + destination)
				return
	elif FileAccess.file_exists(destination):
		_fail(OP_ERROR_INVALID_PATH, "the destination is a file, not a directory: " + destination)
		return
	elif not DirAccess.dir_exists_absolute(destination.get_base_dir()):
		_fail(OP_ERROR_INVALID_PATH, "the destination's parent directory does not exist: "
				+ destination.get_base_dir() + " — project create does not create parent directories")
		return
	else:
		var mkdir_err := DirAccess.make_dir_absolute(destination)
		# Windows mkdir also maps access denial to ERR_ALREADY_EXISTS (#1134).
		# Require a real file collision there; keep Unix refusal semantics.
		if mkdir_err == ERR_ALREADY_EXISTS and (OS.get_name() != "Windows"
				or FileAccess.file_exists(destination)):
			_fail(OP_ERROR_INVALID_PATH, "an entry that is not a directory exists at the destination: "
					+ destination)
			return
		if mkdir_err != OK:
			_fail(OP_ERROR_SAVE_FAILED, "could not create the destination directory "
					+ destination + ": " + error_string(mkdir_err))
			return
		created_dirs.append(destination)

	ProjectSettings.set_setting(PROJECT_NAME_SETTING, name)
	var save_err := ProjectSettings.save_custom(project_file)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "could not write " + project_file + ": " + error_string(save_err)
				+ _remove_created(project_file, created_dirs))
		return

	var config := ConfigFile.new()
	var load_err := config.load(project_file)
	var stored: Variant = null
	if load_err == OK:
		stored = config.get_value("application", "config/name", null)
	if not (stored is String and stored == name):
		_fail(OP_ERROR_SAVE_FAILED, "the project name did not read back unchanged from "
				+ project_file + " (read back: " + var_to_str(stored) + ")"
				+ _remove_created(project_file, created_dirs))
		return

	_succeed({
		"path": destination,
		"name": name,
		"created_dirs": created_dirs,
		"project_file": project_file,
	})


# Every entry of `destination` except "." and "..", hidden ones included, or null
# when the directory cannot be listed. DirAccess hides dot-prefixed entries by
# default, and on macOS also the entries with the UF_HIDDEN flag, so the op asks
# for all of them and applies the dot-prefix rule itself. This is the one listing
# outside the shared res:// walk; the #764 guard in tests/project/test_project_walk.py
# exempts it by name and counts it once.
func _destination_entries(destination: String) -> Variant:
	var dir := DirAccess.open(destination)
	if dir == null:
		return null
	dir.include_hidden = true
	dir.include_navigational = false
	if dir.list_dir_begin() != OK:
		return null
	var entries := PackedStringArray()
	var entry := dir.get_next()
	while not entry.is_empty():
		entries.append(entry)
		entry = dir.get_next()
	dir.list_dir_end()
	return entries


# Remove what a failed project-create request created: the project file, when it
# exists now (the op refuses a destination that already holds one, so this request
# wrote it), then each directory the request created. Each path that cannot be
# removed is a leftover, named on stderr (the envelope's diagnostics). Returns the
# text the failure message ends with.
func _remove_created(project_file: String, created_dirs: Array) -> String:
	var leftovers := PackedStringArray()
	if FileAccess.file_exists(project_file) and DirAccess.remove_absolute(project_file) != OK:
		leftovers.append(project_file)
	for index in range(created_dirs.size() - 1, -1, -1):
		var directory := String(created_dirs[index])
		if DirAccess.dir_exists_absolute(directory) and DirAccess.remove_absolute(directory) != OK:
			leftovers.append(directory)
	if leftovers.is_empty():
		return ""
	for leftover in leftovers:
		_diag("leftover: " + leftover)
	return "; could not remove " + str(leftovers.size()) + " path(s) this request created, listed in diagnostics"


# project-get: read one project setting by its full "section/key" name and report
# it as typed JSON (issue #111). The reported `type` is the setting's declared
# Godot type name and `value` its JSON projection — the same {type, value}
# projection node get reports for a node property, so project get / set round-trip
# through the same shape as node get / set. A setting that does not exist is a
# clean unknown_setting error (not a null value), so a typo'd key is distinguished
# from a setting genuinely holding null.
#
# Like project-info it needs a project (project_not_found otherwise) and runs the
# project's autoloads at startup (#61, ADR-0009); reading a setting never
# instantiates a scene, so it is a state-read at the operation level.
func _op_project_get(params: Dictionary) -> void:
	_diag("running operation: project-get")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project get requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var setting := VALUE._string_param(params, "setting")
	if setting.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: setting")
		return
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "project setting not found: " + setting)
		return

	var value: Variant = ProjectSettings.get_setting(setting)
	_succeed({
		"setting": setting,
		"type": VALUE._type_name(typeof(value)),
		"value": VALUE._jsonify(value),
	})


# project-list: enumerate the project's ProjectSettings keys so an agent can
# DISCOVER which settings exist (issue #312) — the list half of the list → get →
# set workflow, since get/set both require you to already know the section/key.
# Each entry reuses the same {setting, type, value} projection project get reports
# (so a listed entry round-trips through project get), plus an is_default flag:
# false when the key is CUSTOMIZED (written in project.godot), true when it is at
# the engine's built-in default.
#
# Scope: by default only customized settings are listed (keeping the default
# output small and agent-useful); include_defaults widens it to the engine's
# built-in defaults too, and a non-empty section restricts to keys whose name
# begins with that section/ prefix — the two compose. Internal engine-bookkeeping
# settings (PROPERTY_USAGE_INTERNAL — features/tags/translation remaps/…) and the
# non-setting properties get_property_list() also returns (the ProjectSettings
# category, the `script` property) are filtered out, so only real ProjectSettings
# keys appear; the has_setting check is what distinguishes a real setting.
#
# Like every --project op it needs a project (project_not_found otherwise) and
# runs the project's autoloads at startup (#61, ADR-0009); enumerating settings
# never instantiates a scene, so it is a state-read at the operation level.
func _op_project_list(params: Dictionary) -> void:
	_diag("running operation: project-list")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project list requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var include_defaults := bool(params.get("include_defaults", false))
	var section := VALUE._string_param(params, "section")
	var customized := _customized_settings()

	var names: Array[String] = []
	for prop in ProjectSettings.get_property_list():
		var key := String(prop.get("name", ""))
		# Only entries ProjectSettings tracks as real settings answer has_setting —
		# this drops the category header and the `script` property.
		if not ProjectSettings.has_setting(key):
			continue
		# Internal engine bookkeeping is not an agent-facing setting key.
		if int(prop.get("usage", 0)) & PROPERTY_USAGE_INTERNAL:
			continue
		var is_default := not customized.has(key)
		if is_default and not include_defaults:
			continue
		if not section.is_empty() and not key.begins_with(section):
			continue
		names.append(key)

	# Sort by name so the listing is stable regardless of registration order.
	names.sort()
	var settings: Array = []
	for key in names:
		var value: Variant = ProjectSettings.get_setting(key)
		settings.append({
			"setting": key,
			"type": VALUE._type_name(typeof(value)),
			"value": VALUE._jsonify(value),
			"is_default": not customized.has(key),
		})

	_succeed({"settings": settings})


# The set of project setting names CUSTOMIZED in res://project.godot — the keys
# actually written there, as opposed to the engine's built-in defaults. Read by
# parsing project.godot with ConfigFile: each [section] key becomes the full
# "section/key" setting name (a sectionless key like config_version maps to its
# bare name, harmlessly — it is not a real setting). project list reports
# is_default=false for these keys and true for the rest.
#
# The file is the right source even though the initial value IS reachable
# (ProjectSettings.property_get_revert, which _op_project_set uses): "written in
# project.godot" and "differs from the engine default" are different facts, and
# this listing is about the first. A key the caller declared AT the default is
# customized — it is in the file — while property_get_revert would call it a
# default and hide it from a bare `project list`.
func _customized_settings() -> Dictionary:
	var customized := {}
	var cfg := ConfigFile.new()
	if cfg.load("res://project.godot") != OK:
		return customized
	for section in cfg.get_sections():
		for key in cfg.get_section_keys(section):
			var name := key if section.is_empty() else section + "/" + key
			customized[name] = true
	return customized


# project-set: write one project setting, coercing the CLI string value to the
# setting's DECLARED Godot type, then persist project.godot (issue #111, the write
# half — verifiable via project get). The declared type is read off the setting's
# CURRENT value (typeof), exactly as node set reads it off the node's property
# list, and the value is coerced with the SAME shared _coerce_value rules (#55):
# an uncoercible value is a clean uncoercible_value error, leaving project.godot
# untouched. set only writes a setting that already exists — an unknown key is
# unknown_setting, not a silent create — so the type to coerce to is always known.
#
# Persistence: ProjectSettings.set_setting mutates the in-memory settings, and
# ProjectSettings.save() writes them back to res://project.godot. A failed save is
# save_failed. Like every --project op it runs the project's autoloads at
# startup (#61, ADR-0009); the set itself never instantiates a scene.
#
# The save RESERIALIZES the whole file, which is the CLI's business to bound and
# report (#843) — with one part only the engine can do: a value equal to the
# setting's default would be dropped by the writer, so this op keeps the line by
# moving that default aside, and names the setting in restored_settings.
func _op_project_set(params: Dictionary) -> void:
	_diag("running operation: project-set")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project set requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var setting := VALUE._string_param(params, "setting")
	if setting.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: setting")
		return
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "project setting not found: " + setting
				+ " — project set edits an existing setting; it never creates one")
		return

	var current_value: Variant = ProjectSettings.get_setting(setting)
	var declared_type := typeof(current_value)
	var raw_value := VALUE._string_param(params, "value")
	var coerced: Variant = VALUE._coerce_value(raw_value, declared_type, current_value)
	if coerced == null:
		_fail(OP_ERROR_UNCOERCIBLE_VALUE, "cannot coerce value " + raw_value.c_escape()
				+ " to " + VALUE._type_name(declared_type) + " for project setting " + setting
				+ VALUE._float_fidelity_note(raw_value, declared_type))
		return

	# The engine's writer DROPS every setting whose value equals its INITIAL value
	# (ProjectSettings::save_custom: `if (v->variant == v->initial) continue;`), so
	# setting one TO its default would persist nothing at all — the file would come
	# back without the line the caller just asked for. property_get_revert reads the
	# very value that comparison uses, so when they match, move the initial aside and
	# let the ENGINE write the line in its own serialization; gda never hand-builds a
	# Godot literal for it (the ADR-0033 rule). Reported as restored_settings, which
	# the CLI merges with the declarations it restored from the pre-write file (#843).
	var restored: Array = []
	if ProjectSettings.property_get_revert(setting) == coerced:
		ProjectSettings.set_initial_value(setting, null)
		restored.append(setting)
	ProjectSettings.set_setting(setting, coerced)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after setting "
				+ setting + ": " + error_string(save_err))
		return

	# Read the value back off ProjectSettings before reporting — it now holds the
	# coerced value in its canonical form, the same projection project get reports,
	# so a set round-trips through a get.
	var stored_value: Variant = VALUE._jsonify(ProjectSettings.get_setting(setting))
	_succeed({
		"setting": setting,
		"type": VALUE._type_name(declared_type),
		"value": stored_value,
		"restored_settings": restored,
	})


# project-add-autoload: register an autoload singleton (name -> script/scene path)
# under the autoload/<name> section of project.godot, then persist (issue #119).
# The value is stored in the ENABLED-singleton form — the res:// path with a
# leading "*" — which is the normal, globally-accessible autoload gda writes, the
# same value a `project get autoload/<name>` reads back so an add round-trips
# through a get.
#
# Failure modes use existing registered codes: an empty name or path is
# invalid_path; a name already registered is already_exists (add never silently
# overwrites — use remove + add to replace); a target file that does not exist is
# path_not_found; a failed save is save_failed. Like every --project op it runs
# the project's autoloads at startup (#61, ADR-0009); the registration itself
# never instantiates the autoload.
func _op_project_add_autoload(params: Dictionary) -> void:
	_diag("running operation: project-add-autoload")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project add-autoload requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var autoload_name := VALUE._string_param(params, "name")
	if autoload_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return

	var setting := AUTOLOAD_SETTING_PREFIX + autoload_name
	if ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_ALREADY_EXISTS, "autoload already registered: " + autoload_name
				+ " — add-autoload never overwrites; remove it first to replace it")
		return
	if not (FileAccess.file_exists(path) or ResourceLoader.exists(path)):
		_fail(OP_ERROR_PATH_NOT_FOUND, "autoload target does not exist: " + path)
		return

	var stored_path := AUTOLOAD_ENABLED_PREFIX + path
	ProjectSettings.set_setting(setting, stored_path)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after registering autoload "
				+ autoload_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": autoload_name,
		"path": stored_path,
	})


# project-remove-autoload: unregister an autoload singleton by name (clearing the
# autoload/<name> section), then persist project.godot (issue #119). An autoload
# that is not registered is a clean unknown_setting error — the same code
# `project get` of a missing setting reports, since an autoload IS a project
# setting — not a silent no-op, so a typo'd name is distinguished from a genuine
# removal. A failed save is save_failed.
func _op_project_remove_autoload(params: Dictionary) -> void:
	_diag("running operation: project-remove-autoload")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project remove-autoload requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var autoload_name := VALUE._string_param(params, "name")
	if autoload_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return

	var setting := AUTOLOAD_SETTING_PREFIX + autoload_name
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "autoload not registered: " + autoload_name)
		return

	# Clearing the setting (assigning null) removes it from ProjectSettings, so it
	# is dropped from project.godot on save rather than persisted as an empty key.
	ProjectSettings.set_setting(setting, null)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after removing autoload "
				+ autoload_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": autoload_name,
	})


# Resolve one --key token to a Godot keycode (issue #380). A base-10 integer
# spelling is taken as a raw keycode and must be positive; anything else is
# looked up as a Godot key NAME via OS.find_keycode_from_string (e.g. "J",
# "Space", "Escape"). Returns KEY_NONE (0) when the token is unresolvable —
# unambiguous as a failure signal because no valid keycode is 0 or negative —
# which the caller reports as the registered invalid_key error naming the token.
func _resolve_input_keycode(token: String) -> int:
	var trimmed := token.strip_edges()
	if trimmed.is_valid_int():
		var keycode := trimmed.to_int()
		return keycode if keycode > 0 else KEY_NONE
	return OS.find_keycode_from_string(trimmed)


# The JoyButton / JoyAxis names --joy-button and --joy-axis accept (issue #842),
# each mapped to the ENGINE's own global constant. Godot ships no name resolver
# for the joypad enums — there is no counterpart of OS.find_keycode_from_string —
# so gda has to carry the table; mapping every name to the engine constant keeps
# each VALUE the engine's (the GDScript compiler resolves it) and leaves gda
# owning only the SPELLING. The enums' INVALID / SDL_MAX / MAX entries are
# deliberately absent: they are enum bookkeeping, not bindable inputs.
# tests/project/test_input_action_joy_names.py diffs both tables against the enum
# the engine itself dumps, so an engine that gains a button fails a test here
# instead of silently going unbindable.
const JOY_BUTTON_BY_NAME := {
	"A": JOY_BUTTON_A,
	"B": JOY_BUTTON_B,
	"X": JOY_BUTTON_X,
	"Y": JOY_BUTTON_Y,
	"Back": JOY_BUTTON_BACK,
	"Guide": JOY_BUTTON_GUIDE,
	"Start": JOY_BUTTON_START,
	"LeftStick": JOY_BUTTON_LEFT_STICK,
	"RightStick": JOY_BUTTON_RIGHT_STICK,
	"LeftShoulder": JOY_BUTTON_LEFT_SHOULDER,
	"RightShoulder": JOY_BUTTON_RIGHT_SHOULDER,
	"DPadUp": JOY_BUTTON_DPAD_UP,
	"DPadDown": JOY_BUTTON_DPAD_DOWN,
	"DPadLeft": JOY_BUTTON_DPAD_LEFT,
	"DPadRight": JOY_BUTTON_DPAD_RIGHT,
	"Misc1": JOY_BUTTON_MISC1,
	"Paddle1": JOY_BUTTON_PADDLE1,
	"Paddle2": JOY_BUTTON_PADDLE2,
	"Paddle3": JOY_BUTTON_PADDLE3,
	"Paddle4": JOY_BUTTON_PADDLE4,
	"Touchpad": JOY_BUTTON_TOUCHPAD,
}

const JOY_AXIS_BY_NAME := {
	"LeftX": JOY_AXIS_LEFT_X,
	"LeftY": JOY_AXIS_LEFT_Y,
	"RightX": JOY_AXIS_RIGHT_X,
	"RightY": JOY_AXIS_RIGHT_Y,
	"TriggerLeft": JOY_AXIS_TRIGGER_LEFT,
	"TriggerRight": JOY_AXIS_TRIGGER_RIGHT,
}


# Fold a joypad binding name to its comparison form: case- and separator-
# insensitive, so DPadLeft, dpad_left and DPAD_LEFT all name the same button —
# a caller may spell it gda's way or the engine documentation's way.
# Separator-insensitivity is total on purpose: separators are DELETED, not
# normalized, so a leading or trailing one folds away too ("A-" is A). That
# widens the spellings accepted and never makes two buttons collide — the
# oracle test asserts the folded names stay unique — and the alternative would
# be a separator grammar for a token no caller writes deliberately.
func _fold_joy_name(token: String) -> String:
	return token.strip_edges().replace("_", "").replace("-", "").replace(" ", "").to_upper()


# Look one folded token up in a joypad name table, or return -1 (the INVALID
# member both enums share) when nothing matches.
func _lookup_joy_name(table: Dictionary, token: String) -> int:
	var folded := _fold_joy_name(token)
	for name in table:
		if _fold_joy_name(name) == folded:
			return table[name]
	return -1


# The accepted-name list a refusal message names, read off the table itself so
# the message cannot drift from what the resolver accepts.
func _joy_name_list(table: Dictionary) -> String:
	return ", ".join(PackedStringArray(table.keys()))


# Resolve one --joy-button token to a JoyButton index (issue #842). A base-10
# integer is taken as a raw index and must sit inside the engine's own JoyButton
# range (0..JOY_BUTTON_MAX - 1 — a device may report more buttons than the SDL
# names cover); anything else is a name looked up case- and separator-
# insensitively. Returns JOY_BUTTON_INVALID when the token names nothing.
func _resolve_joy_button(token: String) -> int:
	var trimmed := token.strip_edges()
	if trimmed.is_valid_int():
		var index := trimmed.to_int()
		return index if index >= 0 and index < JOY_BUTTON_MAX else JOY_BUTTON_INVALID
	return _lookup_joy_name(JOY_BUTTON_BY_NAME, trimmed)


# Resolve one --joy-axis token to a JoyAxis index (issue #842), same rules as
# _resolve_joy_button over the JoyAxis range. Returns JOY_AXIS_INVALID when the
# token names nothing.
func _resolve_joy_axis(token: String) -> int:
	var trimmed := token.strip_edges()
	if trimmed.is_valid_int():
		var index := trimmed.to_int()
		return index if index >= 0 and index < JOY_AXIS_MAX else JOY_AXIS_INVALID
	return _lookup_joy_name(JOY_AXIS_BY_NAME, trimmed)


# Split one --joy-axis token into its axis part and its axis_value (issue #842).
# The token is `<axis>[:<sign>]`: an axis names a whole stick DIMENSION, so the
# sign is what turns it into one bindable direction (`LeftX:-` is "stick left").
# An omitted sign is the positive direction — the only sensible reading for a
# trigger, which never goes negative. Returns an empty Dictionary when the token
# is not a resolvable direction; the caller reports it with the accepted set.
func _parse_joy_axis_token(token: String) -> Dictionary:
	var parts := token.strip_edges().split(":")
	if parts.size() > 2:
		return {}
	var axis := _resolve_joy_axis(parts[0])
	if axis == JOY_AXIS_INVALID:
		return {}
	var axis_value := 1.0
	if parts.size() == 2:
		match parts[1]:
			"+":
				axis_value = 1.0
			"-":
				axis_value = -1.0
			_:
				return {}
	return {"axis": axis, "axis_value": axis_value}


# project-add-input-action: register an InputMap action under input/<name> with
# keyboard and/or joypad bindings, then persist project.godot (issues #380, #842).
#
# The stored value is the InputMap Dictionary shape — {deadzone, events} with
# real InputEvent Objects, deadzone first (Godot's own key order) — set via
# ProjectSettings.set_setting and serialized by ProjectSettings.save() (the
# engine's own var_to_str form). gda never hand-builds the Object(InputEventKey,
# …) string, so the persisted entry is byte-equivalent to a hand-authored one.
# That holds for every event kind: the joypad kinds are real
# InputEventJoypadButton / InputEventJoypadMotion objects, serialized the same way.
#
# The events are appended in kind order — keys, then joypad buttons, then joypad
# axis directions — so one call's persisted order is deterministic.
#
# Failure modes use registered codes: an empty name is invalid_path (the
# missing-required-param convention the autoload ops set); malformed params,
# and a call naming no binding at all, are invalid_params; an action name already
# present is already_exists (add never silently clobbers — remove first to
# replace). NOTE: the engine registers the built-in ui_* actions
# (input/ui_accept, …) as ProjectSettings defaults, so has_setting answers true
# for them and adding e.g. ui_accept reports already_exists by design. An
# unresolvable BINDING token — a key, a joypad button or a joypad axis direction —
# is invalid_key naming the accepted set (nothing saved); a failed save is
# save_failed.
func _op_project_add_input_action(params: Dictionary) -> void:
	_diag("running operation: project-add-input-action")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project add-input-action requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var action_name := VALUE._string_param(params, "name")
	if action_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return
	# Defensive params reads: the params arrive as arbitrary JSON, so a wrong
	# shape surfaces as a structured failure rather than a runtime error.
	var raw_keys: Variant = params.get("keys", [])
	if not (raw_keys is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "keys must be an array of key names or keycodes")
		return
	var raw_joy_buttons: Variant = params.get("joy_buttons", [])
	if not (raw_joy_buttons is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "joy_buttons must be an array of JoyButton names or indices")
		return
	var raw_joy_axes: Variant = params.get("joy_axes", [])
	if not (raw_joy_axes is Array):
		_fail(OP_ERROR_INVALID_PARAMS, "joy_axes must be an array of <axis>[:<sign>] tokens")
		return
	# An action with no event matches nothing, so the op refuses it rather than
	# registering a dead entry. On the argv path the same rule is a model-side
	# usage error before dispatch (ADR-0015); this is the params-json edge.
	if (raw_keys as Array).is_empty() and (raw_joy_buttons as Array).is_empty() \
			and (raw_joy_axes as Array).is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "at least one binding is required: keys, joy_buttons or joy_axes")
		return
	var raw_deadzone: Variant = params.get("deadzone", 0.5)
	if not (raw_deadzone is float or raw_deadzone is int):
		_fail(OP_ERROR_INVALID_PARAMS, "deadzone must be a number in 0..1")
		return
	var deadzone := float(raw_deadzone)
	var physical := bool(params.get("physical", false))
	var raw_device: Variant = params.get("device", -1)
	if (not (raw_device is int or raw_device is float) or int(raw_device) < -1
			or int(raw_device) > INPUT_EVENT_DEVICE_MAX):
		_fail(OP_ERROR_INVALID_PARAMS, "device must be an integer in -1.." + str(INPUT_EVENT_DEVICE_MAX)
				+ " (-1 matches every joypad; the engine stores the device as a 32-bit integer)")
		return
	var device := int(raw_device)

	var setting := INPUT_SETTING_PREFIX + action_name
	if ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_ALREADY_EXISTS, "input action already registered: " + action_name
				+ " — add-input-action never overwrites; remove it first to replace it")
		return

	# Resolve every binding token before touching ProjectSettings, so a bad token
	# fails the whole add cleanly with nothing saved. `events` stays an UNTYPED
	# Array: a typed Array[InputEventKey] would serialize with an
	# `Array[InputEventKey](...)` annotation, not the plain `[Object(...)]` form
	# the editor writes — untyped keeps the persisted entry byte-equivalent, and
	# it is also what lets the three event kinds share one array.
	var events := []
	var reported_events := []
	for raw_token in (raw_keys as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "keys must be an array of key names or keycodes")
			return
		var token: String = raw_token
		var keycode := _resolve_input_keycode(token)
		if keycode == KEY_NONE:
			_fail(OP_ERROR_INVALID_KEY, "cannot resolve key to a Godot keycode: " + token)
			return
		var event := InputEventKey.new()
		# Match from ANY device, the editor's convention (InputMap::ALL_DEVICES,
		# -1): InputMap matching filters on device, and a real keyboard event
		# carries DEVICE_ID_KEYBOARD (16), so the InputEventKey.new() default of
		# device 0 would never match a physical key press. --device names a
		# JOYPAD and so is never applied to a key event.
		event.device = -1
		# --physical binds the keyboard POSITION (physical_keycode) instead of
		# the layout symbol (keycode) — set only the requested one, exactly as
		# the editor's "Physical" toggle does, never both.
		if physical:
			event.physical_keycode = keycode as Key
		else:
			event.keycode = keycode as Key
		events.append(event)
		reported_events.append({
			"kind": "key",
			"key": token,
			"keycode": keycode,
			"physical": physical,
		})
	for raw_token in (raw_joy_buttons as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "joy_buttons must be an array of JoyButton names or indices")
			return
		var token: String = raw_token
		var button_index := _resolve_joy_button(token)
		if button_index == JOY_BUTTON_INVALID:
			_fail(OP_ERROR_INVALID_KEY, "cannot resolve joypad button: " + token
					+ " — accepted names (case- and separator-insensitive): "
					+ _joy_name_list(JOY_BUTTON_BY_NAME)
					+ "; or an index 0.." + str(JOY_BUTTON_MAX - 1))
			return
		var event := InputEventJoypadButton.new()
		# InputEvent::device defaults to 0 in the engine, which matches only the
		# FIRST joypad; --device defaults to -1 (InputMap::ALL_DEVICES) and is set
		# explicitly here for the same reason the key path sets it.
		event.device = device
		event.button_index = button_index as JoyButton
		events.append(event)
		reported_events.append({
			"kind": "joy_button",
			"button": token,
			"button_index": button_index,
			"device": device,
		})
	for raw_token in (raw_joy_axes as Array):
		if not (raw_token is String):
			_fail(OP_ERROR_INVALID_PARAMS, "joy_axes must be an array of <axis>[:<sign>] tokens")
			return
		var token: String = raw_token
		var parsed := _parse_joy_axis_token(token)
		if parsed.is_empty():
			_fail(OP_ERROR_INVALID_KEY, "cannot resolve joypad axis direction: " + token
					+ " — expected <axis>[:<sign>] with sign + or - (default +) and an axis"
					+ " named (case- and separator-insensitive): "
					+ _joy_name_list(JOY_AXIS_BY_NAME)
					+ "; or an index 0.." + str(JOY_AXIS_MAX - 1))
			return
		var axis: int = parsed["axis"]
		var axis_value: float = parsed["axis_value"]
		var event := InputEventJoypadMotion.new()
		event.device = device
		event.axis = axis as JoyAxis
		event.axis_value = axis_value
		events.append(event)
		reported_events.append({
			"kind": "joy_axis",
			"axis": token,
			"axis_index": axis,
			"axis_value": axis_value,
			"device": device,
		})

	# deadzone first — the key order Godot itself writes for an input action.
	ProjectSettings.set_setting(setting, {"deadzone": deadzone, "events": events})
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after registering input action "
				+ action_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": action_name,
		"deadzone": deadzone,
		"events": reported_events,
	})


# project-remove-input-action: unregister an InputMap action by name (clearing
# the input/<name> setting), then persist project.godot (issue #380). An action
# that is not registered is a clean unknown_setting error — the same code
# `project get` of a missing setting reports, since an input action IS a project
# setting — not a silent no-op. A failed save is save_failed.
func _op_project_remove_input_action(params: Dictionary) -> void:
	_diag("running operation: project-remove-input-action")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project remove-input-action requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var action_name := VALUE._string_param(params, "name")
	if action_name.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: name")
		return

	var setting := INPUT_SETTING_PREFIX + action_name
	if not ProjectSettings.has_setting(setting):
		_fail(OP_ERROR_UNKNOWN_SETTING, "input action not registered: " + action_name)
		return

	# Clearing the setting (assigning null) removes it from ProjectSettings, so it
	# is dropped from project.godot on save rather than persisted as an empty key.
	ProjectSettings.set_setting(setting, null)
	var save_err := ProjectSettings.save()
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to save project settings after removing input action "
				+ action_name + ": " + error_string(save_err))
		return

	_succeed({
		"name": action_name,
	})


# --- project static-analysis reads (issue #116) -----------------------------
#
# Four read-only, project-wide reads, backed by TWO static scans over different
# file universes. find-references, dependencies and find-unused-resources share
# the extension-filtered scan (_collect_resource_paths); statistics counts with
# the unfiltered one (_collect_all_file_paths), which also sees the .import
# sidecars and project.godot the other excludes — so its file total does not
# reconcile with the others' candidate set. The two scans share one traversal
# (_collect_paths) and one directory-exclusion rule (_should_descend), which is
# what keeps them from disagreeing about the TREE while ranging over different
# files within it.
#
# Both scans read files as TEXT — parsing each .tscn/.tres for its
# [ext_resource path="..."] entries and each .gd for its preload/load/extends
# references — and never instantiate a scene or load/compile a script (the read
# trust boundary of issue #30). Reads still run under --project, so the engine
# constructs the project's autoloads at startup before _initialize (the residual
# project-code execution of issue #61); the scans themselves add none.
#
# The THREE reference-graph reads share one graph so they stay consistent
# (acceptance criterion): find-references reports the incoming references of one
# target; dependencies reports the outgoing references of every scene/resource;
# find-unused-resources reports the resources with no incoming reference (and not
# an entry point). A resource is "unused" exactly when find-references for it
# would return empty — the same graph, one truth. statistics is not on that graph:
# it only counts what its own scan reaches.
#
# ONE graph needs ONE identity per file, and that identity is the path the ENGINE
# resolves a declaration to — not the string the declaration spells. Two spellings
# reach the same file:
#
# - an ALIAS of an absolute address (res://leaf.tscn and res://sub/../leaf.tscn),
#   folded by _canonical_resource_path, the engine's own simplify_path;
# - a RELATIVE address, which the engine resolves against the DECLARING file's
#   own directory — `path="../shared/leaf.tscn"` in res://scenes/main.tscn loads
#   res://shared/leaf.tscn (measured on 4.6.3), and `preload("../shared/x.gd")`
#   in res://scripts/user.gd loads res://shared/x.gd (measured likewise).
#
# So every path that enters the graph is folded by the ONE owner that knows its
# base directory — _resolve_ref_path, for an [ext_resource] line and for a
# preload/load/extends argument alike. Only two entrants have no
# declaring file to anchor to and are absolute by construction — project.godot's
# main scene and autoloads, and the caller's find-references query — and those go
# straight to _canonical_resource_path.
#
# Keying on the raw spelling broke all three reads at once (#774): dependencies
# named a node no file on disk answers to, find-references for the resolved path
# missed the declaration, and find-unused-resources therefore advised DELETING a
# scene the project instances — wrong advice with a destructive follow-up. The
# other side of every comparison is canonical by construction: the walk builds each
# path by joining directory entries, never by echoing a declaration.


# project-find-references: find every project file that references the target — a
# resource res:// path, or a script class_name (issue #116). Walks the project's
# res:// tree, parsing each file's references as text (no instantiation), and
# reports each referencing site (path + kind + matched context). A target nothing
# references is a SUCCESSFUL empty result, not a failure.
func _op_project_find_references(params: Dictionary) -> void:
	_diag("running operation: project-find-references")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project find-references requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var target := VALUE._string_param(params, "target")
	if target.is_empty():
		_fail(OP_ERROR_INVALID_TARGET, "missing required param: target")
		return

	# Resolve the target to the set of strings a reference can name it by. A
	# res:// path names a resource directly; a class_name names both the class
	# token (used in .gd as `extends Name` / type annotations) AND the script
	# path it resolves to (used as an ext_resource/preload). A bare token that is
	# neither a res:// path nor a class_name the unified resolver resolves to a .gd
	# (ADR-0032) is rejected: a filesystem path (or a typo) could never appear in a
	# res://-addressed reference, so scanning for it would only ever return a
	# misleading empty result.
	var target_paths := {}  # res:// paths a reference may name the target by
	var target_class := ""  # class_name token a .gd reference may name it by
	if target.begins_with("res://"):
		# The query is canonicalized like every harvested path (#774), so a caller
		# that spells the target res://sub/../leaf.tscn asks about the same node
		# the graph keys res://leaf.tscn under. The echoed "target" keeps the
		# caller's own spelling — it also carries a class_name, which is no path.
		target_paths[SCENE_TEXT._canonical_resource_path(target)] = true
	else:
		# Resolve the class_name through the SAME unified resolver node add /
		# resource create use (ADR-0032), so find-references and resource create
		# agree on whether a class resolves in an editor-never-opened project, and
		# a class_name declared in more than one .gd is the shared ambiguous error.
		var resolution := CLASS_INDEX._resolve_project_class_script(target)
		match resolution["status"]:
			"resolved":
				target_class = target
				target_paths[SCENE_TEXT._canonical_resource_path(String(resolution["path"]))] = true
			"ambiguous":
				_fail(OP_ERROR_AMBIGUOUS_CLASS_NAME, CLASS_INDEX._ambiguous_class_name_message(target, resolution["paths"]))
				return
			_:
				_fail(OP_ERROR_INVALID_TARGET, "find-references target is not a res:// path, and no .gd script declares class_name " + target + " (check for a misspelled name): " + target)
				return

	var paths: Array[String] = []
	PROJECT_WALK._collect_resource_paths("res://", paths)
	paths.sort()

	var references: Array = []
	for path in paths:
		REFERENCE_GRAPH._collect_references_from(path, target_paths, target_class, references)
	# Project-level references (autoloads, the main scene) live in
	# project.godot, not in a scanned file — add them from ProjectSettings.
	REFERENCE_GRAPH._collect_project_level_references(target_paths, references)

	_succeed({
		"target": target,
		"references": references,
	})


# project-dependencies: map every scene/resource in the project to the resources
# it references — its outgoing [ext_resource] / preload references (issue #116).
# A scene/resource with no external references is reported with an empty
# depends_on, not dropped.
func _op_project_dependencies(_params: Dictionary) -> void:
	_diag("running operation: project-dependencies")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project dependencies requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	PROJECT_WALK._collect_resource_paths("res://", paths)
	paths.sort()

	var dependencies: Array = []
	for path in paths:
		# Only resources that can declare ext_resource dependencies (.tscn/.tres)
		# and scripts (.gd, via preload/load) are reported as dependency sources;
		# a leaf asset (an image) has no outgoing references to map.
		if not REFERENCE_GRAPH._has_outgoing_references(path):
			continue
		var depends_on := REFERENCE_GRAPH._outgoing_references_of(path)
		dependencies.append({
			"path": path,
			"depends_on": depends_on,
		})

	_succeed({"dependencies": dependencies})


# project-find-unused-resources: resources nothing references (issue #116). Built
# on the SAME reference graph as find-references/dependencies (acceptance
# criterion): a resource is unused exactly when no other file references it AND it
# is not a project entry point (the main scene, or an autoload's script/scene).
# Scripts (.gd) are excluded from the "unused resource" report — an unreferenced
# script is dead CODE, a different concern from an unused resource asset, and a
# project's scripts are routinely referenced only dynamically; reporting them
# would be noise. .tscn scenes and .tres/asset resources are the resources this
# reports.
func _op_project_find_unused_resources(_params: Dictionary) -> void:
	_diag("running operation: project-find-unused-resources")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project find-unused-resources requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	PROJECT_WALK._collect_resource_paths("res://", paths)
	paths.sort()

	# Build the set of every res:// path that ANY file references — the union of
	# all outgoing references across the project, the exact graph find-references
	# reads one target at a time. A path absent from this set has zero incoming
	# references (find-references would return empty for it), the consistency the
	# issue requires.
	var referenced := {}
	for path in paths:
		for dep in REFERENCE_GRAPH._outgoing_references_of(path):
			referenced[dep["path"]] = true
	# Project-level entry points are "referenced" too, so they are never reported
	# unused: the main scene and the autoloads are entered directly, not via a
	# file reference.
	for entry in REFERENCE_GRAPH._project_entry_points():
		referenced[entry] = true

	var unused: Array = []
	for path in paths:
		# A script is dead CODE, not an unused resource asset (see the op note).
		if GDSCRIPT_SCAN._is_script_path(path):
			continue
		if not referenced.has(path):
			unused.append(path)

	_succeed({"unused": unused})


# project-statistics: file/line counts, autoloads, plugins (issue #116). Counts
# every file under res:// (skipping the engine's .godot cache) by extension; sums
# line counts for text files (binary assets count as files but contribute no
# lines). Autoloads and plugins are read from ProjectSettings — never executed.
func _op_project_statistics(_params: Dictionary) -> void:
	_diag("running operation: project-statistics")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project statistics requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var paths: Array[String] = []
	PROJECT_WALK._collect_all_file_paths("res://", paths)
	paths.sort()

	var total_files := 0
	var total_lines := 0
	var by_ext := {}  # extension -> {"files": int, "lines": int}
	var scene_count := 0
	var script_count := 0
	var resource_count := 0
	for path in paths:
		total_files += 1
		var ext := path.get_extension().to_lower()
		if not by_ext.has(ext):
			by_ext[ext] = {"files": 0, "lines": 0}
		by_ext[ext]["files"] += 1
		var lines := REFERENCE_GRAPH._count_lines(path)
		by_ext[ext]["lines"] += lines
		total_lines += lines
		match ext:
			"tscn":
				scene_count += 1
			"gd":
				script_count += 1
			"png", "jpg", "jpeg", "webp", "svg", "ogg", "wav", "mp3", "ttf", "otf", "import", "godot", "cfg":
				# import sidecars, the project file, and binary/asset files are not
				# "resource" files in the .tres sense; they still count as files.
				pass
			_:
				resource_count += 1

	var extensions: Array = []
	var ext_keys := by_ext.keys()
	ext_keys.sort()
	for ext in ext_keys:
		extensions.append({
			"extension": ext,
			"files": by_ext[ext]["files"],
			"lines": by_ext[ext]["lines"],
		})

	_succeed({
		"total_files": total_files,
		"total_lines": total_lines,
		"by_extension": extensions,
		"autoloads": REFERENCE_GRAPH._project_autoloads(),
		"plugins": REFERENCE_GRAPH._project_plugins(),
		"scene_count": scene_count,
		"script_count": script_count,
		"resource_count": resource_count,
	})


# project-scan: the class list as the engine holds it (issue #1073). `gda project
# scan` runs the engine import pass first — the editor filesystem scan, the only
# writer of the class index — and then this op, in a fresh engine that read the
# index the pass wrote at startup. It reports ProjectSettings.get_global_class_list()
# as the engine read it: gda never parses the index file. It loads no script.
func _op_project_scan(_params: Dictionary) -> void:
	_diag("running operation: project-scan")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "project scan requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return
	var classes: Array = []
	for entry in ProjectSettings.get_global_class_list():
		classes.append({"name": String(entry.get("class", "")), "path": String(entry.get("path", ""))})
	classes.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return String(a["name"]) < String(b["name"]))
	_succeed({"classes": classes})
