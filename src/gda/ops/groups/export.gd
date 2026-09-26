extends "../op_base.gd"

# gda headless operations payload: the export command group (ADR-0043). The
# entry, operations.gd, creates one instance per run and dispatches the group's
# operations to it.

const VALUE := preload("../lib/value.gd")


# export-list: enumerate the project's export presets (issue #114). Reads the
# project's res://export_presets.cfg with ConfigFile — a cheap config parse, not
# an export run (issue #121 owns running an export) — and reports each preset's
# index/name/platform/runnable. Like scene-list / script-list this needs a
# project (project_not_found otherwise); a project that has never configured an
# export has no export_presets.cfg, which is the distinct export_presets_not_found
# failure rather than a misleading empty listing.
func _op_export_list(_params: Dictionary) -> void:
	_diag("running operation: export-list")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "export list requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var config := _load_export_presets()
	if config == null:
		return  # _load_export_presets already recorded the failure

	var presets: Array = []
	for entry in _export_preset_sections(config):
		presets.append(_export_preset_summary(config, entry["section"], entry["index"]))

	_succeed({"presets": presets})


# export-get: report one export preset's details plus export-template install
# status (issue #114). Addresses the preset by its display NAME (as export-list
# reports it); an unknown name is the export_preset_not_found failure. Beyond the
# preset's own fields it reports whether the export templates for the running
# engine version are installed — the readiness check an agent makes before a
# future export run (issue #121) — the version directory it checked, and the
# export-templates directory that version was looked for in. When the optional
# "host_data_path" param names a data directory other than this run's own, and that
# one DOES hold the version's templates, the reply names it too: --user-data-root
# moves the directory Godot reads the templates from, so a redirected run reports
# none installed on a host that has them (#840).
func _op_export_get(params: Dictionary) -> void:
	_diag("running operation: export-get")
	if not _has_project():
		_fail(OP_ERROR_PROJECT_NOT_FOUND, "export get requires a Godot project; none was resolved — pass --project, set $GDA_PROJECT, or run from a project directory")
		return

	var preset_name := VALUE._string_param(params, "preset")
	if preset_name.is_empty():
		_fail(OP_ERROR_INVALID_PARAMS, "missing required param: preset")
		return

	var config := _load_export_presets()
	if config == null:
		return  # _load_export_presets already recorded the failure

	for entry in _export_preset_sections(config):
		var section: String = entry["section"]
		if String(config.get_value(section, "name", "")) == preset_name:
			var summary := _export_preset_summary(config, section, entry["index"])
			summary["export_path"] = String(config.get_value(section, "export_path", ""))
			var version_dir := _export_templates_version_dir()
			var templates_root := _export_templates_root(OS.get_data_dir())
			summary["templates_version"] = version_dir
			summary["templates_root"] = templates_root
			var installed := _export_templates_installed(templates_root, version_dir)
			summary["templates_installed"] = installed
			summary["templates_root_host"] = _hidden_host_templates_root(
				VALUE._string_param(params, "host_data_path"), templates_root, version_dir, installed
			)
			_succeed(summary)
			return

	_fail(OP_ERROR_EXPORT_PRESET_NOT_FOUND, "no export preset named: " + preset_name)


# Load the project's export_presets.cfg as a ConfigFile, or record a failure and
# return null (the caller must stop). A project with no export_presets.cfg has
# never configured an export, so it is the distinct export_presets_not_found
# failure; a present-but-unparseable file is a save_failed-style read error.
func _load_export_presets() -> ConfigFile:
	var presets_path := "res://export_presets.cfg"
	if not FileAccess.file_exists(presets_path):
		_fail(OP_ERROR_EXPORT_PRESETS_NOT_FOUND, "project has no export_presets.cfg; no export presets are defined")
		return null
	var config := ConfigFile.new()
	var err := config.load(presets_path)
	if err != OK:
		_fail(OP_ERROR_SAVE_FAILED, "failed to read export_presets.cfg: " + error_string(err))
		return null
	return config


# The export-preset sections of an export_presets.cfg, in file order, each as
# {"section": "preset.N", "index": N}. A preset is stored as a "preset.N" section
# with a sibling "preset.N.options" section; only the bare "preset.N" is a preset,
# so the ".options" companions are filtered out. The index is the preset's N, the
# stable 0-based position the file assigns it.
func _export_preset_sections(config: ConfigFile) -> Array:
	var sections: Array = []
	for section in config.get_sections():
		if not section.begins_with("preset."):
			continue
		var rest := section.substr("preset.".length())
		if not rest.is_valid_int():
			continue  # skip "preset.N.options" and any non-numeric suffix
		sections.append({"section": section, "index": int(rest)})
	return sections


# Summarize one export preset for the listing: its index/name/platform plus
# whether it is marked runnable. Read straight from the ConfigFile, never running
# an export. Missing keys degrade to safe defaults so a hand-edited file still
# lists rather than crashing.
func _export_preset_summary(config: ConfigFile, section: String, index: int) -> Dictionary:
	return {
		"index": index,
		"name": String(config.get_value(section, "name", "")),
		"platform": String(config.get_value(section, "platform", "")),
		"runnable": bool(config.get_value(section, "runnable", false)),
	}


# The export-templates version directory name for the running engine, e.g.
# "4.6.stable" (4.6.0) or "4.6.3.stable" (4.6.3) — major.minor[.patch].status,
# matching how the editor names the per-version templates folder under
# <data_dir>/<godot-dir>/export_templates/. The patch component is OMITTED when it
# is 0 — exactly as Engine.get_version_info()'s version string does (engine.cpp) and
# as the official export-template archives are named — so a .0 release resolves to
# "<major>.<minor>.<status>", not "<major>.<minor>.0.<status>".
# Known limitation (#304): a NON-standard build appends a module/precision suffix to
# the real dir name (FULL_CONFIG — e.g. "4.6.stable.mono" for a C# build, "...double"
# for double precision), which Engine.get_version_info() exposes no field to
# reconstruct. gda targets STANDARD official builds, where that suffix is empty.
func _export_templates_version_dir() -> String:
	var v := Engine.get_version_info()
	var dir := "%d.%d" % [v.major, v.minor]
	if int(v.patch) != 0:
		dir += ".%d" % v.patch
	return "%s.%s" % [dir, v.status]


# The export-templates directory under one data directory: <data_dir>/<godot-dir>/
# export_templates. Headless --script runs have no EditorPaths singleton, so the
# path is composed from the data dir (the same root the editor uses) plus the
# "<godot-dir>/export_templates" layout, where <godot-dir> is the engine's
# per-platform user-dir name (see _godot_user_dir_name — lowercase "godot" on
# case-sensitive Linux, NOT the macOS/Windows "Godot"). Taking the data dir as an
# ARGUMENT is what keeps the layout rule in ONE place while two directories are
# compared (#840): the engine's own OS.get_data_dir(), which a --user-data-root
# redirect MOVES, and the host's, which gda passes in.
func _export_templates_root(data_dir: String) -> String:
	return data_dir.path_join(_godot_user_dir_name()).path_join("export_templates")


# Whether the export templates for the running engine version are installed:
# their per-version directory exists under the given export-templates root. This is
# the readiness signal an agent checks before a future export run (issue #121); it
# does not verify per-platform template files, only that the version's templates
# are present at all.
func _export_templates_installed(templates_root: String, version_dir: String) -> bool:
	return DirAccess.dir_exists_absolute(templates_root.path_join(version_dir))


# The HOST's export-templates directory, but only when it holds templates this run
# cannot see (#840). Godot reads the templates from OS.get_data_dir(), which
# --user-data-root relocates, so a redirected run reports none installed even on a
# host whose templates are correctly installed. gda passes the host data directory
# (it resolves it over its own, unredirected environment) so this reply can name the
# second directory — and it is named ONLY when something is really HIDDEN: null when
# no host directory was passed, when the checked root already holds this version
# (nothing is hidden, whatever the host holds — a redirected root a caller populated
# is a healthy run, PR #883 review round 3), when the redirect is not in play (the
# two roots are the same directory), and when the host has no templates for this
# version either, which is a plain missing-templates run with nothing to disclose.
func _hidden_host_templates_root(host_data_dir: String, templates_root: String, version_dir: String, installed: bool) -> Variant:
	if host_data_dir.is_empty() or installed:
		return null
	var host_root := _export_templates_root(host_data_dir)
	if host_root.simplify_path() == templates_root.simplify_path():
		return null
	if not _export_templates_installed(host_root, version_dir):
		return null
	return host_root


# The engine's per-platform user-data directory name. macOS and Windows capitalize it
# ("Godot"); every other platform — Linux and the BSDs — uses lowercase "godot", and
# their filesystems are case-sensitive, so the case is load-bearing. Mirrors the C++
# OS::get_godot_dir_name() (its default is lowercase; only macOS/Windows override it),
# which a headless --script run cannot call.
func _godot_user_dir_name() -> String:
	var os_name := OS.get_name()
	return "Godot" if os_name == "macOS" or os_name == "Windows" else "godot"
