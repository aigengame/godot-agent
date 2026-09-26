extends "../op_base.gd"

# gda headless operations payload: the theme command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operation to it.


# theme-create: produce a loadable .tres Theme resource (issue #115). Unlike the
# shader trio (plain file authoring), a Theme is an ENGINE-BACKED resource: it is
# constructed as a Theme and written through ResourceSaver so the .tres is a
# genuine, loadable resource (the same ResourceSaver path scene-create uses for a
# PackedScene), not hand-written text — the file-level vs engine-backed split the
# script group draws between create/get/set and attach/validate. No-clobber: a
# target that exists is already_exists.
func _op_theme_create(params: Dictionary) -> void:
	_diag("running operation: theme-create")
	var path := _string_param(params, "path")
	if path.is_empty():
		_fail(OP_ERROR_INVALID_PATH, "missing required param: path")
		return
	if not _is_theme_path(path):
		_fail(OP_ERROR_INVALID_PATH, "theme path must end in .tres: " + path)
		return
	if FileAccess.file_exists(path) or DirAccess.dir_exists_absolute(path):
		_fail(OP_ERROR_ALREADY_EXISTS, "theme target already exists: " + path)
		return

	var theme := Theme.new()
	var created_dirs: Variant = _ensure_parent_dirs(path)
	if created_dirs == null:
		return  # _ensure_parent_dirs already recorded the failure
	var save_err := _atomic_save_resource(theme, path)
	if save_err != OK:
		_fail(OP_ERROR_SAVE_FAILED, _save_failure_message("theme", path, save_err))
		return

	_succeed({
		"path": path,
		"type": "Theme",
		"created_dirs": created_dirs,
	})


# Whether a path names a theme resource file: a .tres. theme-create writes a
# Theme resource, addressed by extension like the rest of the asset-file groups.
func _is_theme_path(path: String) -> bool:
	return path.get_extension().to_lower() == "tres"
