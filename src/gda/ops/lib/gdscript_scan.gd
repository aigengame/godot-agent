extends RefCounted

# gda headless operations payload: the GDScript source scan (ADR-0043 §2) —
# tokens, string and comment skipping, class_name metadata, executable preload
# paths, and the .gd path test. Static.

const SCENE_TEXT := preload("scene_text.gd")


static func _is_identifier_char(ch: String) -> bool:
	return ch == "_" or (ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z") or (ch >= "0" and ch <= "9")


# Whether a path names a script file the script group operates on: a .gd
# (GDScript) file. Script-file addressing is by extension, the same way scene
# addressing keys on .tscn. C# (.cs) is out of scope for now — it needs the .NET
# build of Godot (ADR-0003 targets the standard build) and a dedicated decision.
static func _is_script_path(path: String) -> bool:
	return path.get_extension().to_lower() == "gd"


# Extract a GDScript's declared class_name and extends from its raw source by
# lightweight line-by-line parsing — never compiling the script (issue #30).
# Both are null when absent. Only .gd scripts reach here (the entry points reject
# any other extension as invalid_path), so this keys off GDScript syntax alone.
static func _script_metadata(source: String) -> Dictionary:
	var class_name_value: Variant = null
	var extends_value: Variant = null
	# class_name and extends, when present, lead a GDScript file: they sit in the
	# header, after the optional annotation lines (@tool, @icon(...), …) and
	# before the first real statement. Scan only that header — skip blanks,
	# comments and annotations, capture the first of each declaration, and STOP at
	# the first line that is neither. Stopping is what keeps a class_name/extends-
	# shaped line deeper in the body (e.g. inside a multiline string) from ever
	# being mistaken for the declaration.
	for raw_line in source.split("\n"):
		var line := raw_line.strip_edges()
		if line.is_empty() or line.begins_with("#") or line.begins_with("@"):
			continue
		if line.begins_with("class_name "):
			if class_name_value == null:
				class_name_value = _first_token(line.substr("class_name ".length()))
			continue
		if line.begins_with("extends "):
			if extends_value == null:
				extends_value = _first_token(line.substr("extends ".length()))
			continue
		# The first real statement past the header: no further class_name/extends
		# declaration can legally appear, so stop scanning.
		break
	return {"class_name": class_name_value, "extends": extends_value}


# The first token of a declaration's remainder — the class_name or base-class
# identifier. A bare identifier drops a trailing inline comment and stops at the
# first whitespace: "Hero # the hero" → "Hero", "Node2D" → "Node2D". The quoted
# base-class-by-path form (extends "res://Base.gd") is kept whole up to its
# closing quote — including any '#' inside the path, which is part of the string,
# not an inline comment.
static func _first_token(rest: String) -> Variant:
	var trimmed := rest.strip_edges()
	if trimmed.is_empty():
		return null
	if trimmed.begins_with("\"") or trimmed.begins_with("'"):
		var quote := trimmed[0]
		var close := trimmed.find(quote, 1)
		# An unterminated quote is reported as-is rather than silently truncated.
		return trimmed.substr(0, close + 1) if close != -1 else trimmed
	var comment := trimmed.find("#")
	if comment != -1:
		trimmed = trimmed.substr(0, comment).strip_edges()
	var token := trimmed.split(" ", false)[0]
	return token if not token.is_empty() else null


static func _script_executable_preload_paths(script_path: String) -> Array[String]:
	var out: Array[String] = []
	var source := FileAccess.get_file_as_string(script_path)
	if source.is_empty() and FileAccess.get_open_error() != OK:
		return out
	var base_dir := script_path.get_base_dir()
	var index := 0
	while index < source.length():
		var token_index := _find_code_token(source, "preload", index)
		if token_index == -1:
			break
		var after_token := token_index + "preload".length()
		var open_paren := _skip_gdscript_space_and_comments(source, after_token)
		if open_paren >= source.length() or source[open_paren] != "(":
			index = after_token
			continue
		var arg_start := _skip_gdscript_space_and_comments(source, open_paren + 1)
		var literal := _quoted_string_literal_at(source, arg_start)
		if not bool(literal.get("ok", false)):
			index = open_paren + 1
			continue
		out.append(SCENE_TEXT._resolve_ref_path(String(literal["value"]), base_dir))
		index = int(literal["end"])
	return out


static func _find_code_token(source: String, token: String, from: int) -> int:
	var index := from
	while index < source.length():
		var ch := source[index]
		if ch == "#":
			index = _skip_gdscript_line_comment(source, index)
			continue
		if ch == "\"" or ch == "'":
			index = _skip_quoted_string_literal(source, index)
			continue
		if source.substr(index, token.length()) == token:
			var before_ok := (
					index == 0
					or (not _is_identifier_char(source[index - 1]) and source[index - 1] != ".")
			)
			var after_index := index + token.length()
			var after_ok := (
					after_index >= source.length()
					or not _is_identifier_char(source[after_index])
			)
			if before_ok and after_ok:
				return index
		index += 1
	return -1


static func _skip_gdscript_space_and_comments(source: String, from: int) -> int:
	var index := from
	while index < source.length():
		var ch := source[index]
		if ch == " " or ch == "\t" or ch == "\r" or ch == "\n":
			index += 1
			continue
		if ch == "#":
			index = _skip_gdscript_line_comment(source, index)
			continue
		break
	return index


static func _skip_gdscript_line_comment(source: String, from: int) -> int:
	var index := from
	while index < source.length() and source[index] != "\n":
		index += 1
	return index


static func _skip_quoted_string_literal(source: String, from: int) -> int:
	var literal := _quoted_string_literal_at(source, from)
	return int(literal["end"])


static func _quoted_string_literal_at(source: String, from: int) -> Dictionary:
	if from >= source.length():
		return {"ok": false, "value": "", "end": source.length()}
	var quote := source[from]
	if quote != "\"" and quote != "'":
		return {"ok": false, "value": "", "end": from}
	var triple := quote + quote + quote
	if source.substr(from, 3) == triple:
		var content_start := from + 3
		var triple_end := source.find(triple, content_start)
		if triple_end == -1:
			return {"ok": false, "value": "", "end": source.length()}
		return {
			"ok": true,
			"value": source.substr(content_start, triple_end - content_start),
			"end": triple_end + 3,
		}
	var out := ""
	var index := from + 1
	while index < source.length():
		var ch := source[index]
		if ch == "\\":
			if index + 1 >= source.length():
				return {"ok": false, "value": "", "end": source.length()}
			out += source[index + 1]
			index += 2
			continue
		if ch == quote:
			return {"ok": true, "value": out, "end": index + 1}
		out += ch
		index += 1
	return {"ok": false, "value": "", "end": source.length()}
