extends "../op_base.gd"

# gda headless operations payload: the shader command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")
const GDSCRIPT_SCAN := preload("../lib/gdscript_scan.gd")
const FILE_WRITE := preload("../lib/file_write.gd")
const TEXT_EDIT := preload("../lib/text_edit.gd")

# The instance concept modules this group's operations call, created with the
# group's frame and held for the group's life (ADR-0043 §4).
var _file_write: FILE_WRITE
var _text_edit: TEXT_EDIT


func _init(frame) -> void:
	super(frame)
	_file_write = FILE_WRITE.new(frame)
	_text_edit = TEXT_EDIT.new(frame)


# shader-create: author a new .gdshader as RAW TEXT (issue #115). A .gdshader is
# plain shader source — no engine compilation is needed to write it — so create
# is pure file authoring, exactly like script-create (issue #110): no-clobber
# (a target that exists is already_exists), and verbatim --content wins over the
# built-in shader_type template. The created file is verifiable end-to-end by
# shader-get (create → get returns the source).
func _op_shader_create(params: Dictionary) -> void:
	_diag("running operation: shader-create")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_shader_path(path):
		_fail(OP_ERROR_INVALID_PATH, "shader path must end in .gdshader: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "shader target already exists: " + path)
		return

	# Verbatim content wins; otherwise write a minimal template declaring the
	# requested shader_type (defaulting to canvas_item).
	var source: String
	var content: Variant = params.get("content", null)
	if content is String:
		source = content
	else:
		var shader_type := VALUE._string_param(params, "shader_type")
		if shader_type.is_empty():
			shader_type = "canvas_item"
		source = "shader_type " + shader_type + ";\n"

	var created_dirs: Variant = _file_write._ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	if not _write_text_file(path, source, "shader"):
		return  # _write_text_file already recorded the failure

	_succeed({
		"path": path,
		"shader_type": _shader_metadata(source),
		"created_dirs": created_dirs,
	})


# shader-get: read a shader's source back as RAW TEXT and report it with the
# shader_type the source declares — the read half of issue #115, which makes a
# shader-create verifiable end-to-end (create → get returns the source). Like
# script-get, it never load()s/compiles the shader, so reading it can never run
# project code (issue #30).
func _op_shader_get(params: Dictionary) -> void:
	_diag("running operation: shader-get")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_shader(path):
		return  # _require_existing_shader already recorded the failure

	var source: Variant = _read_text_file(path, "shader")
	if source == null:
		return  # _read_text_file already recorded the failure

	_succeed({
		"path": path,
		"source": source,
		"shader_type": _shader_metadata(source),
	})


# shader-set: edit an EXISTING .gdshader on disk as RAW TEXT (issue #115). It
# REUSES the script-set edit-mode interface (issue #118): the same three
# mutually-exclusive modes (search-replace / line-range / full), the same apply
# helpers, dispatched on the same explicit `mode` discriminator the CLI resolves
# (issue #133). It never compiles or loads the shader, so editing it cannot run
# project code (issue #30). set edits an existing shader; a missing target is
# path_not_found, never a silent create.
func _op_shader_set(params: Dictionary) -> void:
	_diag("running operation: shader-set")
	var path := VALUE._string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _require_existing_shader(path):
		return  # _require_existing_shader already recorded the failure

	var source: Variant = _read_text_file(path, "shader")
	if source == null:
		return  # _read_text_file already recorded the failure
	# Capture the staleness token right after the read (issue #226) — shader-set writes
	# raw text directly, not via the shared tail, so it wires capture/recheck itself.
	_file_write._capture_staleness_token(path)

	var mode := VALUE._string_param(params, "mode")
	var new_source: Variant
	match mode:
		"search_replace":
			new_source = _text_edit._apply_search_replace(source, params, "shader")
		"line_range":
			new_source = _text_edit._apply_line_range(source, params, "shader")
		"full":
			# full overwrite: content is guaranteed present by the CLI's mode check.
			new_source = VALUE._string_param(params, "content")
		_:
			# The CLI always supplies one of the three modes; a missing/unknown mode
			# means a malformed direct op invocation, not a reachable CLI path.
			_fail(OP_ERROR_INVALID_PARAMS, "unknown shader-set mode: " + mode)
			return
	if new_source == null:
		return  # the apply helper already recorded the failure

	# Recheck before the write (issue #226): refuse if a concurrent editor changed the
	# .gdshader in the read->write window.
	if not _file_write._check_unchanged():
		return
	if not _write_text_file(path, new_source, "shader"):
		return  # _write_text_file already recorded the failure

	# Re-parse the written source so set round-trips through shader get.
	_succeed({
		"path": path,
		"shader_type": _shader_metadata(new_source),
	})


# Whether a path names a shader file the shader group operates on: a .gdshader
# (Godot shader) file. Shader-file addressing is by extension, the same way
# script addressing keys on .gd and scene addressing on .tscn.
func _is_shader_path(path: String) -> bool:
	return path.get_extension().to_lower() == "gdshader"


# Clear the shader group's addressing boundary for an EXISTING shader: the path
# must be a .gdshader (invalid_path otherwise) and the file must exist on disk
# (path_not_found otherwise). Returns true to proceed, or false after recording
# the failure (the caller must stop). Mirrors _require_existing_script: shared by
# shader get and set so they refuse a non-.gdshader target and a missing file
# identically.
func _require_existing_shader(path: String) -> bool:
	if not _is_shader_path(path):
		_fail(OP_ERROR_INVALID_PATH, "shader path must end in .gdshader: " + path)
		return false
	if not FileAccess.file_exists(path):
		_fail(OP_ERROR_PATH_NOT_FOUND, "shader file does not exist: " + path)
		return false
	return true


# Extract a .gdshader's declared shader_type from its raw source by lightweight
# line-by-line parsing — never compiling the shader (issue #30). Null when absent.
# A .gdshader leads with `shader_type <type>;`, after optional blank/comment
# lines; scan that header, capture the first shader_type, and stop at the first
# real statement so a shader_type-shaped token deeper in the body is never
# mistaken for the declaration.
func _shader_metadata(source: String) -> Variant:
	for raw_line in source.split("\n"):
		var line := raw_line.strip_edges()
		if line.is_empty() or line.begins_with("//"):
			continue
		if line.begins_with("shader_type "):
			# Drop the trailing ';' and any inline comment, keep the first token.
			var rest := line.substr("shader_type ".length())
			var semicolon := rest.find(";")
			if semicolon != -1:
				rest = rest.substr(0, semicolon)
			return GDSCRIPT_SCAN._first_token(rest)
		# The first real line past the header: no shader_type can legally appear
		# after it, so stop scanning.
		break
	return null


# Read a text asset's source back as RAW TEXT, disambiguating an empty file from
# an unreadable one — the same trick as _read_script_source. Shared by the shader
# get/set ops; `noun` names the asset in the failure message.
func _read_text_file(path: String, noun: String) -> Variant:
	var source := FileAccess.get_file_as_string(path)
	if source.is_empty():
		var open_err := FileAccess.get_open_error()
		if open_err != OK:
			_fail(OP_ERROR_PATH_NOT_FOUND, noun + " file could not be read: " + path
					+ ": " + error_string(open_err))
			return null
	return source


# Write `source` to a text asset file as RAW TEXT, reporting both failure modes
# as save_failed — the generic twin of _write_script_file (which names "script"
# in its diagnostic). Returns true on a clean write, or false after recording the
# failure (the caller must stop). `noun` names the asset in the diagnostic.
func _write_text_file(path: String, source: String, noun: String) -> bool:
	var write_err := _file_write._atomic_write_text(path, source)
	if write_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _file_write._save_failure_message(noun, path, write_err))
		return false
	return true
