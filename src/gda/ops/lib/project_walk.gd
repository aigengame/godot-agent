extends RefCounted

# gda headless operations payload: the engine-side res:// walk (ADR-0032,
# ADR-0043 §2) and the graph-eligibility test it walks by. Static.


# The engine's own import/cache tree at the project root — the first of the three
# directories a res:// walk excludes. The VALUE only — the decision that uses it
# lives in exactly one place, _is_in_engine_cache, which _should_descend and
# _should_collect both ask.
#
# RESIDUAL (#804): the engine reads this location from ProjectSettings —
# `get_project_data_path()` is `res://` joined with `application/config/
# project_data_dir_name`, which a project may rename — while gda hardcodes the
# default. A project that renames its data directory therefore has gda walk the
# renamed cache and exclude a `res://.godot` that is ordinary content. Stated
# rather than chased: the rename is rare, and closing it means reading the setting
# in every walk-side predicate.
const ENGINE_CACHE_DIR := "res://.godot"

# The two MARKER files whose presence makes the engine's own scan skip a directory
# (EditorFileSystem::_should_skip_directory, editor/file_system/
# editor_file_system.cpp:3460-3480, line numbers from the 4.6.3-stable tag): a
# `project.godot` marks a NESTED project, whose files belong to a different res://
# root, and a `.gdignore` is the project's own explicit "do not scan this" marker.
# Values only — the decision that uses them is _should_descend's alone (#804).
#
# The same two literals are spelled a second time in Python, in
# `_engine_skips_directory_of` (src/gda/import_evidence.py), which predicts the
# same rule for an inventory that never spawns the engine. The two spellings are
# held together by `test_the_two_spellings_of_the_skip_markers_agree` (#808
# review), not by derivation.
const NESTED_PROJECT_MARKER := "project.godot"
const GDIGNORE_MARKER := ".gdignore"

# How far a res:// walk follows symlinks when it asks whether an entry is the
# engine cache (#760): the links followed in one chain, and the passes the
# component-by-component resolution takes to reach its fixed point. Both count
# SYMLINK TRAVERSALS — a pass that changes the path resolved at least one more
# link — which is the quantity the OS itself bounds, so a chain gda gives up on
# is one the kernel would refuse to open anyway and the bound cannot hide a path
# the walk could otherwise have reached. The value is the LOWER of the two
# ceilings gda targets: MAXSYMLINKS is 32 on macOS (MacOSX.sdk/usr/include/
# sys/param.h:197) and 40 on Linux (include/linux/namei.h), so a 33-to-40-link
# chain is resolvable on Linux and gda stops short of it — accepted, because
# such a chain is not a shape an honest project produces.
#
# The ancestor climb in _is_in_engine_cache is deliberately NOT bounded by this
# constant: it counts path COMPONENTS, a quantity no kernel limits, and running
# out of steps there returned false, which ADMITTED cache content — the opposite
# direction from the failure MAXSYMLINKS reasons about, and a leak at 32 levels
# below the cache (#795 review). It terminates on its own at the root instead.
const SYMLINK_PROBE_MAX_STEPS := 32


# Whether a res:// walk descends into this child DIRECTORY. The ONE owner of the
# descent decision: every walk over the project tree (scripts, scenes, graph
# resources, all files) asks this and nothing else, so the rule cannot drift
# between them and a new walk inherits it by calling this.
#
# THE ENGINE'S OWN SKIP RULE (#804). EditorFileSystem::_should_skip_directory
# (editor/file_system/editor_file_system.cpp:3460-3480, line numbers from the
# 4.6.3-stable tag) skips three kinds of directory, and this predicate now answers
# the same three:
#
#   - the project DATA path (the cache) — gda's ENGINE_CACHE_DIR clause below,
#     with the hardcoded-vs-configurable residual stated at that constant;
#   - a directory holding a `project.godot`: another project INSIDE this one. Its
#     files address a different res:// root, so enumerating them here gave them
#     the outer root — `script validate --all` compiled a nested script against it
#     and reported every one of its own `res://` preloads as missing, the exact
#     false cascade ADR-0006's gate refuses when the same file is NAMED. `--all`
#     and the named target now agree because the walk no longer reaches the file;
#   - a directory holding a `.gdignore`: the project's own explicit marker for
#     content the engine must not scan. gda honoured it nowhere, so a `.gdignore`d
#     tree was listed, validated, counted and indexed.
#
# Answering that function is NOT full parity with the engine's scan, and is not
# meant to be: _scan_new_dir discards every hidden entry and every dot-prefixed
# DIRECTORY before it consults _should_skip_directory (editor_file_system.cpp:
# 1157-1168, same tag). gda deliberately enumerates those (#54, #712), so a
# `res://.hidden/x.gd` is still listed here where the engine's scan never reaches
# it. What this predicate adopts is the marker rule, not the hidden-entry rule.
#
# Only a directory carrying one of those markers changes answer. The probes are
# lexical joins onto the child's res:// path, never the directory NAME, so a
# sub-directory merely CALLED `project.godot` (a directory, not a file) does not
# skip anything: FileAccess.file_exists answers false for a directory
# (FileAccessUnix::file_exists accepts S_IFREG/S_IFLNK only). Nor does the way the
# directory was REACHED: a marked directory symlinked into the tree is skipped
# too, because the probe resolves the link. Both edges are pinned e2e (#808
# review), which is what keeps them from being claims alone.
#
# COST (#804, recorded so review does not re-litigate it): two extra
# FileAccess.file_exists per child DIRECTORY — the same two probes the engine's
# own scan pays, on the same directories, and a file-level stat rather than a
# read. It is not paid per FILE, and a project's directory count is orders below
# its file count. Caching the answer was declined: a walk visits each directory
# once, so a cache would only add state to save nothing.
#
# The cache test is the full path, never the directory NAME, because a `.godot`
# deeper in the tree is not this project's engine cache. It is usually authored
# content (an addon vendoring a sample project, a fixture tree), and excluding it
# hid real scripts from `script list` and let `script validate --all` report a
# valid aggregate for a project holding an invalid script (#663 review). Sometimes
# it is a vendored sub-project's own cache instead, whose artefacts then counted in
# `project statistics` and `find-unused-resources` — a cost #712 accepted, since
# nothing in the PATH tells the two apart and a false-valid aggregate is worse.
#
# The marker clause above retires that cost wherever an ENGINE wrote the cache —
# the case #712 named — and #712's own reasoning is why: nothing in the path tells
# an engine cache from authored content, but the CONTENT does. Every engine that
# creates a project data directory writes a `.gdignore` into it — the editor
# (EditorPaths::create, editor/file_system/editor_paths.cpp:268-277) and gda's own
# import pass, whose `created` list names `res://.godot/.gdignore`. So a nested
# cache any engine produced now carries the marker and is skipped, while a
# `.godot` that is genuinely authored content — no engine ever wrote it, so no
# `.gdignore` inside — is still walked, which is the case #712's rule was FOR
# (#808 review).
#
# Three of the four walks once compared the NAME, so one project answered two
# ways: `script list` reported a script `project statistics` counted as zero
# (#712). One decision, one site — that is what keeps them in agreement.
#
# SYMLINK POLICY (#760). The walk FOLLOWS a link, as the engine does —
# DirAccessUnix::get_next stat()s a DT_LNK entry on purpose, so a linked directory
# reports current_is_dir() (drivers/unix/dir_access_unix.cpp:148-183), and
# ResourceLoader loads through an alias (both measured on 4.6.3) — but it
# identifies what it reached by FILESYSTEM IDENTITY, not by the spelling that
# reached it. Two rules follow, and only a link pays for them:
#
#   - the engine cache is excluded by identity, so no SYMLINK alias re-admits it
#     (_is_in_engine_cache — which also states why a hard link is outside the
#     rule);
#   - a linked directory already on this descent CHAIN is not re-entered, so a
#     cycle terminates by rule instead of running to the OS symlink limit —
#     `sub/loop -> sub` once emitted 33 spellings of one file, the deepest 174
#     characters long. The chain is per-BRANCH, so what the walk enumerates is
#     distinct res:// PATHS: a directory reachable through several link paths is
#     reported under each, and mutually linked directories multiply the spellings
#     quickly. The answer is decided and finite — that is the guarantee — not
#     "each real directory exactly once" (#795 review).
#
# A link to ordinary authored content — a vendored checkout reached through one —
# is neither the cache nor an ancestor, so it is followed and enumerated exactly
# as before. That is the point of deciding by identity rather than by refusing
# links: the two defects are about WHERE a link leads, not about links.
static func _should_descend(dir: DirAccess, child: String, chain: Array[String]) -> bool:
	if child == ENGINE_CACHE_DIR:
		return false
	# The engine's two marker clauses, in its own order. They are asked BEFORE the
	# link tests because a marker is about what the directory HOLDS, not about how
	# it was reached: a vendored checkout carrying its own `project.godot` is
	# skipped whether it sits in the tree or is symlinked into it, exactly as the
	# engine skips it (FileAccess::exists resolves the link too).
	if FileAccess.file_exists(child.path_join(NESTED_PROJECT_MARKER)):
		return false
	if FileAccess.file_exists(child.path_join(GDIGNORE_MARKER)):
		return false
	if not dir.is_link(child):
		# Not a link: its real parent is the directory being listed, which the
		# walk already cleared, and it cannot be an ancestor of itself. So the
		# tests above are the whole decision — an ordinary project pays one lstat
		# per entry plus the engine's own two marker probes, and nothing else.
		return true
	if _is_in_engine_cache(dir, child):
		return false
	for ancestor in chain:
		if dir.is_equivalent(child, ancestor):
			return false
	return true


# Whether a res:// walk COLLECTS this child FILE, once the collector's own
# acceptance test has said yes. The file-side half of the symlink policy above
# (#760): _should_descend gates DIRECTORY descent only, so a file link INTO the
# cache — `res://alias.gd -> res://.godot/root_cache.gd` — reaches the accept
# branch without ever passing it, and re-admits by itself the content the descent
# rule keeps out. The two halves ask the same question of the same owner.
#
# A link to ordinary content is collected, deliberately: it is a real res:// path
# the engine loads (measured on 4.6.3), so hiding it would hide authored content
# the game can address. That also means the same file can be listed under two
# paths when one is an alias of the other — both are true answers to "what can
# this project load", and neither is the fabricated path a cycle produced.
static func _should_collect(dir: DirAccess, child: String) -> bool:
	return not dir.is_link(child) or not _is_in_engine_cache(dir, child)


# Whether `path` IS the engine cache or lives inside it, however it is spelled —
# the ONE owner of the exclusion decision both walk-side predicates ask (#760).
#
# The identity test is the ENGINE's own: DirAccess.is_equivalent compares
# (st_dev, st_ino) on Unix and (VolumeSerialNumber, FileId) on Windows, both
# stat-resolved, and falls back to string equality when a path cannot be stat'd
# (DirAccess::is_equivalent, core/io/dir_access.cpp:630-632, overridden in
# DirAccessUnix::is_equivalent, drivers/unix/dir_access_unix.cpp:713-729, and
# DirAccessWindows::is_equivalent, drivers/windows/dir_access_windows.cpp:411-431;
# line numbers from the 4.6.3-stable tag). gda does not answer "are these the
# same directory" itself, and the fallback degrades to exactly the lexical rule
# this predicate replaced — a project with no `res://.godot` at all keeps
# answering as it did.
#
# The path is resolved by hand first because DirAccess cannot do it for us:
# DirAccessUnix::fix_path simplifies a path LEXICALLY before every syscall
# (drivers/unix/dir_access_unix.cpp:55-57), so a `..` appended to a link never
# reaches the kernel and cannot be used to walk up out of an alias (measured on
# 4.6.3: is_equivalent("res://nested/.godot/..", "res://") answers false through an
# alias of the root cache).
#
# ANCESTORS of the resolved path are probed, so a link INTO the cache —
# `res://nested/imported -> res://.godot/imported` — is excluded too, not only a
# link AT it. That climb is why _fully_resolved_path has to resolve EVERY
# component and not just the last one: with `link1 -> sub/deep` and
# `sub/deep/c -> ../../.godot`, reading the target against the spelling
# `res://link1` instead of against the real `res://sub/deep` made the ancestors
# of `res://link1/c` a directory the kernel never visits, and answered that the
# cache was not reached — the same wrong answer in both directions, admitting the
# root cache under one spelling and hiding a vendored checkout's own nested cache
# under another (#795 review). The climb carries no step bound of its own: it
# counts path COMPONENTS, which no kernel limits, and get_base_dir() shortens the
# path every step until the root is its own parent.
#
# What survives is a link gda cannot read — a target read_link refuses, or a
# chain longer than the OS resolves — which stops at the furthest path it did
# resolve, so an unresolvable alias is reported rather than hidden. Hard links
# are outside the rule by construction: the filesystem does not call them links,
# so is_link never reports one and this predicate is never asked. The guarantee
# is therefore about SYMLINK aliases.
static func _is_in_engine_cache(dir: DirAccess, path: String) -> bool:
	var probe := _fully_resolved_path(dir, path)
	while not dir.is_equivalent(probe, ENGINE_CACHE_DIR):
		var parent := probe.get_base_dir()
		if parent.is_empty() or parent == probe:
			return false
		probe = parent
	return true


# The path `path` really names, resolved the way the KERNEL resolves one: every
# component read against the components already resolved before it, not against
# the spelling that reached it (#795 review).
#
# One pass rebuilds the path component by component (_resolve_path_segments); a
# component whose target itself names a link is resolved by the NEXT pass, and
# the passes stop as soon as one changes nothing. A pass that does change the
# path resolved at least one more link, so SYMLINK_PROBE_MAX_STEPS bounds the
# passes for the same reason it bounds the hops inside one chain.
static func _fully_resolved_path(dir: DirAccess, path: String) -> String:
	var resolved := path
	for _pass in range(SYMLINK_PROBE_MAX_STEPS):
		var next_path := _resolve_path_segments(dir, resolved)
		if next_path == resolved:
			break
		resolved = next_path
	return resolved


# One left-to-right pass of the component resolution above: split `path` into its
# root and its components, then rebuild it, resolving each component against the
# prefix already rebuilt.
#
# The split climbs with get_base_dir()/get_file() rather than looking for a `/`,
# so it makes no assumption about the root it is given — `res://`, a Unix `/`, or
# a Windows drive all end the climb by being their own base directory, and a
# read_link target that leaves the project (an absolute path outside `res://`) is
# rebuilt on its own root.
#
# `..` pops the rebuilt prefix instead of being appended, which is the kernel's
# reading and is safe here for the reason the lexical shortcut is not: the prefix
# it pops is already resolved, so its parent is the real one. That is also what
# keeps the result canonical enough for the ancestor climb above.
static func _resolve_path_segments(dir: DirAccess, path: String) -> String:
	var segments: Array[String] = []
	var root := path
	while true:
		var base := root.get_base_dir()
		if base == root:
			break
		segments.push_front(root.get_file())
		root = base
	var resolved := root
	for segment in segments:
		if segment.is_empty() or segment == ".":
			continue
		if segment == "..":
			resolved = resolved.get_base_dir()
			continue
		resolved = _resolved_link_path(dir, resolved.path_join(segment))
	return resolved


# The path ONE component finally names, following a chain of links up to the OS's
# own ceiling (#760). A relative target is joined onto the directory holding the
# link — correct for the first hop, whose base the caller has already resolved,
# and repaired for any later one by the next pass of _fully_resolved_path. An
# absolute target is taken as it is.
#
# Returns the FURTHEST path it resolved: `path` itself when that is not a link,
# and otherwise the last target it read before the target became unreadable, the
# chain outran the bound, or a target named the path it came from. That last case
# is what a failed DirAccessWindows::read_link looks like — it returns the fixed
# input path, never the empty string, and otherwise returns an already-resolved
# absolute path from GetFinalPathNameByHandleW (drivers/windows/
# dir_access_windows.cpp:444-462) — so on Windows an unopenable reparse point
# stops after one probe instead of spinning out the bound, and the relative join
# below is dead code by that platform's contract rather than by accident.
static func _resolved_link_path(dir: DirAccess, path: String) -> String:
	var current := path
	for _step in range(SYMLINK_PROBE_MAX_STEPS):
		if not dir.is_link(current):
			return current
		var target := dir.read_link(current)
		if target.is_empty() or target == current:
			return current
		current = target if target.is_absolute_path() else current.get_base_dir().path_join(target)
	return current


# The ONE res:// traversal (#764). Open the directory, enumerate hidden entries,
# loop, ask _should_descend about each child DIRECTORY, and close the listing —
# the scaffolding that used to be copied into all four collectors below, where
# the copies were free to drift and one pair already had (see
# _collect_scene_paths). `accept` is the only thing a caller varies: it is asked
# about each FILE and decides whether the walk collects it, so the four
# collectors differ in exactly that predicate and in nothing else.
#
# The collectors share this TRAVERSAL, not a file universe. `accept` is what makes
# _collect_all_file_paths count the import sidecars and project.godot that
# _collect_resource_paths excludes: one traversal, one exclusion rule, different
# universes.
#
# Navigational entries ('.', '..') stay off, so the recursion cannot loop back on
# itself (issue #54 review). Hidden entries are enumerated, so a .hidden.tscn, or
# any file under a dot-prefixed directory, is collected as promised — the dot
# prefix is not the exclusion test, _should_descend is, and that decision stays
# its alone (#712).
#
# `accept` is asked about the full res:// child path, not the bare entry name: it
# is the shape the predicates the collectors reuse (_is_scene_path,
# _is_script_path, _is_graph_resource_path) are written against. The two agree on
# the extension anyway — String.get_extension() stops at the last '/', so a file
# with no extension under a dotted directory (res://a.b/README) answers "" either
# way — but only the full path can carry a test that looks at the directory too.
#
# `chain` is the descent chain: the directories above `dir_path`, which the walk
# carries so the symlink policy can tell a link that leads back UP the chain from
# one that leads to new content (#760). A caller never passes it — a walk starts
# at the root with an empty chain — and the recursion extends it by one, in a NEW
# array, so a branch cannot see a sibling branch's ancestors.
static func _collect_paths(dir_path: String, accept: Callable, out: Array[String], chain: Array[String] = []) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	var descended: Array[String] = chain.duplicate()
	descended.append(dir_path)
	dir.include_hidden = true
	dir.list_dir_begin()
	var entry := dir.get_next()
	while not entry.is_empty():
		var child := dir_path.path_join(entry)
		if dir.current_is_dir():
			if _should_descend(dir, child, descended):
				_collect_paths(child, accept, out, descended)
		elif accept.call(child) and _should_collect(dir, child):
			out.append(child)
		entry = dir.get_next()
	dir.list_dir_end()


# The unfiltered acceptance test: every file the traversal reaches (#764). A named
# predicate rather than an inline lambda, so the statistics walk reads as the same
# one-line shape as the other three collectors and its universe has a name.
static func _accept_any_file(_path: String) -> bool:
	return true


# Recursively collect every RESOURCE-bearing file under res:// — the files that
# can carry references (.tscn/.tres scenes & resources, .gd scripts) AND the leaf
# asset resources (everything else except import sidecars, the project file, and
# the .godot cache). This is the universe the reference graph, find-unused and the
# class_name index range over.
static func _collect_resource_paths(dir_path: String, out: Array[String]) -> void:
	_collect_paths(dir_path, _is_graph_resource_path, out)


# Recursively collect EVERY file under res:// for the statistics counts — unlike
# _collect_resource_paths this keeps import sidecars, project.godot and every
# asset, since statistics counts all files. The two walks therefore range over
# DIFFERENT universes under the same traversal and the same exclusion.
static func _collect_all_file_paths(dir_path: String, out: Array[String]) -> void:
	_collect_paths(dir_path, _accept_any_file, out)


# Whether a path names a file the reference graph / find-unused treat as a
# resource: a scene, a resource, a script, or a leaf asset — anything except the
# import sidecars and the project file the .godot cache and the engine own. Kept
# deliberately inclusive so an asset (an image, a font) referenced by a scene is
# itself a node in the graph and a candidate for find-unused. Distinct from the
# resource group's _is_resource_path (a strict .tres check): this is the project
# scan's graph-eligibility test, hence the separate name.
static func _is_graph_resource_path(path: String) -> bool:
	var ext := path.get_extension().to_lower()
	if ext == "import" or ext == "godot" or ext == "cfg" or ext == "uid":
		return false
	return not ext.is_empty()
