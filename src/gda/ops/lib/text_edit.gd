extends "../op_base.gd"

# gda headless operations payload: search-and-replace and line-range edits for
# script set and shader set (ADR-0043 §2). An instance module.

const VALUE := preload("value.gd")


# search-replace edit: replace every literal occurrence of `search` with
# `replace`. An empty or absent search string can never be located, and a search
# string the source does not contain is a no_search_match failure (so an agent
# learns the edit landed nowhere rather than silently writing the file back
# unchanged). Returns null after recording the failure.
func _apply_search_replace(source: String, params: Dictionary, noun: String) -> Variant:
	var search := VALUE._string_param(params, "search")
	var replace := VALUE._string_param(params, "replace")
	if search.is_empty() or not source.contains(search):
		_fail(OP_ERROR_NO_SEARCH_MATCH, "search string not found in " + noun + ": " + search.c_escape())
		return null
	return source.replace(search, replace)


# line-range edit: replace the 1-based, inclusive line span [start_line,
# end_line] with `content`. Lines are the parts of the source split on its
# newline, so a trailing newline yields a final empty part ("a\nb\n" →
# ["a","b",""], N=3); the valid range is 1..N. end_line defaults to start_line
# (a single-line edit). A range outside the bounds, or end before start, is
# invalid_line_range. Returns null after recording the failure.
#
# The file's own newline (CRLF when the source uses it, else LF) is used to both
# split and rejoin, and the replacement `content` is normalized onto it, so
# editing a CRLF script preserves CRLF instead of corrupting the edited span to
# mixed endings. A mixed-ending file is pathological and resolves to CRLF.
func _apply_line_range(source: String, params: Dictionary, noun: String) -> Variant:
	var newline := "\r\n" if source.contains("\r\n") else "\n"
	var lines := source.split(newline)
	var line_count := lines.size()
	var start_line := int(params.get("start_line", 0))
	var end_line: int = int(params.get("end_line", start_line)) if params.get("end_line", null) != null else start_line
	if start_line < 1 or start_line > line_count or end_line < start_line or end_line > line_count:
		_fail(OP_ERROR_INVALID_LINE_RANGE, "line range " + str(start_line) + ".." + str(end_line)
				+ " is outside the " + noun + "'s bounds (1.." + str(line_count) + ") or ends before it starts")
		return null
	var content := VALUE._string_param(params, "content")
	var before := lines.slice(0, start_line - 1)
	var after := lines.slice(end_line)
	# Normalize the replacement's own newlines onto the file's so the whole edited
	# file keeps one consistent ending.
	var replacement := content.replace("\r\n", "\n").split("\n")
	var rebuilt: Array = []
	rebuilt.append_array(before)
	rebuilt.append_array(replacement)
	rebuilt.append_array(after)
	return newline.join(PackedStringArray(rebuilt))
