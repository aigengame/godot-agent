extends "../op_base.gd"

# gda headless operations payload: the write side of a project file (ADR-0043
# §2) — parent directories, the atomic text and resource saves, the staleness
# token (#226), and the save-failure message. An instance module: it reports
# failure through the op base. The token is per-process, in static vars, so a
# capture and a check through two instances see one token (ADR-0043 §4).

const SCENE_TEXT := preload("scene_text.gd")


# --- optimistic staleness guard for headless read-modify-write ops (issue #226) ---
#
# A file-mutating op reads a target (.tscn/.gd/.tres/.gdshader), transforms it, then
# writes it back. If a concurrent external editor (ADR-0018) changes that file on disk
# inside the in-process read->write window, a blind write would CLOBBER the external
# edit. The guard captures a cheap change token (mtime + size) right after the read and
# re-checks it right before the write; a difference is reported as
# file_changed_externally and the write is refused, leaving the external edit intact.
#
# The token is mtime+size, not mtime alone: FileAccess.get_modified_time is
# whole-SECONDS granularity, so a same-second external edit would be invisible to mtime;
# the file size (which an edit almost always changes) catches that case. A single member
# set is safe — operations.gd is a one-shot process running exactly one op — mirroring
# the _captured_external_scripts pattern above. An op that captured no token (a create)
# leaves _staleness_path empty, and _check_unchanged is then a no-op (returns true).
static var _staleness_mtime: int = -1
static var _staleness_size: int = -1
static var _staleness_path: String = ""


# Capture the change token for `path` right after an op reads it. Uses the SAME path
# string the op passed to ResourceLoader.load / FileAccess (no globalize_path), so the
# recheck reads exactly the same file. Size is read via an explicit READ open + length;
# -1 marks an unreadable file (the recheck will still fire if it later becomes readable
# with a different token, which is the conservative outcome).
func _capture_staleness_token(path: String) -> void:
	_staleness_path = path
	_staleness_mtime = int(FileAccess.get_modified_time(path))
	_staleness_size = _file_size(path)


func _file_size(path: String) -> int:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return -1
	var size := file.get_length()
	file.close()
	return int(size)


# Re-check the captured token right before an op writes. Returns true when the file is
# unchanged (or when no token was captured, e.g. a create); returns false AFTER
# recording file_changed_externally when mtime or size differs. The single emission
# point for the guard — every wired op funnels its recheck through here.
func _check_unchanged() -> bool:
	# Production-inert test seam (issue #226): the in-process read->write window is
	# sub-second, so a normal test cannot race a real external edit into it. When this
	# env var is set, perturb the target's SIZE just before the comparison to simulate
	# an external edit landing in the window. Gated by has_environment, so it is dead
	# code in production — runner.py spawns Godot with no env= and never sets this var.
	if OS.has_environment("GDA_TEST_PERTURB_BEFORE_SAVE"):
		_test_perturb_target(_staleness_path)
	if _staleness_path.is_empty():
		return true  # no token captured (e.g. a create) — nothing to compare
	var current_mtime := int(FileAccess.get_modified_time(_staleness_path))
	var current_size := _file_size(_staleness_path)
	if current_mtime != _staleness_mtime or current_size != _staleness_size:
		_fail(OP_ERROR_FILE_CHANGED_EXTERNALLY,
				"target file changed on disk since gda read it (a concurrent editor may have"
				+ " edited it); refusing to overwrite: " + _staleness_path)
		return false
	return true


# Test-only: simulate an external edit landing in the read->write window by appending a
# byte to the target, guaranteeing a SIZE change so the guard fires regardless of mtime
# second-granularity. Reached only through the GDA_TEST_PERTURB_BEFORE_SAVE branch in
# _check_unchanged, so it never runs in production.
func _test_perturb_target(path: String) -> void:
	if path.is_empty():
		return
	var file := FileAccess.open(path, FileAccess.READ_WRITE)
	if file == null:
		return
	file.seek_end()
	file.store_8(10)  # a newline byte — any byte changes the size
	file.close()


func _ensure_parent_dirs(path: String) -> Variant:
	var parent := path.get_base_dir()
	if parent.is_empty() or DirAccess.dir_exists_absolute(parent):
		return []

	var missing: Array[String] = []
	var current := parent
	while not current.is_empty() and not DirAccess.dir_exists_absolute(current):
		missing.push_front(current)
		var next := current.get_base_dir()
		if next == current:
			break
		current = next

	var err := DirAccess.make_dir_recursive_absolute(parent)
	if err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to create parent directory " + parent + ": " + error_string(err))
		return null
	return missing


# Build a save-failure diagnostic for a `noun` (scene / script) written to
# `path`: the error, the parent directory, and a write-probe that names why the
# directory is unwritable when that is the cause. Shared by every save path so
# the diagnostic (and the probe) stays identical across groups.
func _save_failure_message(noun: String, path: String, save_err: Error) -> String:
	var parent := path.get_base_dir()
	var message := "failed to save " + noun + " to " + path
	if not parent.is_empty():
		message += " in parent directory " + parent
	message += ": " + error_string(save_err)

	var probe_dir := "."
	if not parent.is_empty():
		probe_dir = parent
	var probe_name := ".gda-write-check.tmp"
	var probe_path := probe_dir.path_join(probe_name)
	var probe := FileAccess.open(probe_path, FileAccess.WRITE)
	if probe == null:
		message += "; write probe " + probe_path + " failed: " + error_string(FileAccess.get_open_error())
	else:
		probe.close()
		var dir := DirAccess.open(probe_dir)
		if dir != null:
			dir.remove(probe_name)
	return message


# --- atomic write primitives (issue #226) -----------------------------------
#
# Godot's text savers (ResourceSaver for .tscn/.tres, FileAccess for .gd/.gdshader)
# open the destination directly and truncate-in-place, so a failed save TEARS the
# original. The engine has an atomic mode (FileAccess::set_backup_save(true)) but it
# is not bound to GDScript, so we replicate it: write to a SAME-DIRECTORY sibling
# temp, then DirAccess.rename_absolute(tmp, path) — a same-filesystem POSIX rename,
# which IS bound and IS atomic. On any failure the target is left byte-untouched and
# the temp is removed, so a concurrent reader (or our own staleness guard) never sees
# a half-written file. Returns an Error code (OK on success); the caller keeps its
# existing save_failed ladder and only translates a non-OK return.


# A sibling temp path in the target's own directory (so rename is same-filesystem
# and therefore atomic). The PID disambiguates parallel one-shot headless processes
# writing the same target, so their temps never collide. Pure string ops, so it
# works for res:// paths as well as absolute/user:// paths.
#
# The target's ORIGINAL extension is PRESERVED as the temp's trailing extension
# (".gda-<pid>-<file>.tmp.<ext>") because ResourceSaver.save picks its saver by the
# destination's recognized extension — a ".tmp" tail would be "File unrecognized"
# and fail every .tscn/.tres save. FileAccess writes (.gd/.gdshader) don't care, so
# preserving the extension is harmless there and correct for the resource path.
func _atomic_temp_path(path: String) -> String:
	var ext := path.get_extension()
	var suffix := ".tmp" if ext.is_empty() else ".tmp." + ext
	return path.get_base_dir().path_join(".gda-" + str(OS.get_process_id()) + "-" + path.get_file() + suffix)


# Remove a file if it exists, swallowing the outcome — used to clean up a temp on a
# failed atomic write, where the write error is what we want to report, not a
# secondary cleanup error.
func _remove_quiet(path: String) -> void:
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)


# Save `res` to `path` atomically: ResourceSaver.save to a sibling temp, then rename
# the temp over the target. Returns OK on success, or the first non-OK Error (with
# the temp removed and the target untouched).
func _atomic_save_resource(res: Resource, path: String) -> int:
	var should_restore_ext_ids := (
			path.get_extension().to_lower() == "tscn" and FileAccess.file_exists(path)
	)
	var original_text := FileAccess.get_file_as_string(path) if should_restore_ext_ids else ""
	var tmp := _atomic_temp_path(path)
	var save_err := ResourceSaver.save(res, tmp)
	if save_err != OK:
		_remove_quiet(tmp)
		return save_err
	if should_restore_ext_ids:
		var saved_text := FileAccess.get_file_as_string(tmp)
		var stable_text := SCENE_TEXT._restore_existing_ext_resource_ids(path, original_text, saved_text)
		if stable_text != saved_text:
			var rewrite_err := _atomic_write_text(tmp, stable_text)
			if rewrite_err != OK:
				_remove_quiet(tmp)
				return rewrite_err
	var rename_err := DirAccess.rename_absolute(tmp, path)
	if rename_err != OK:
		_remove_quiet(tmp)
		return rename_err
	return OK


# Write `content` to `path` atomically as RAW TEXT: store into a sibling temp,
# capture the write error BEFORE close() invalidates the handle (a disk-full/I/O
# error surfaces at get_error(), not at open), then rename the temp over the target.
# Returns OK on success, or the first non-OK Error (with the temp removed and the
# target untouched).
func _atomic_write_text(path: String, content: String) -> int:
	var tmp := _atomic_temp_path(path)
	var file := FileAccess.open(tmp, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(content)
	var write_err := file.get_error()
	file.close()
	if write_err != OK:
		_remove_quiet(tmp)
		return write_err
	var rename_err := DirAccess.rename_absolute(tmp, path)
	if rename_err != OK:
		_remove_quiet(tmp)
		return rename_err
	return OK
