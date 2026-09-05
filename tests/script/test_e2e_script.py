"""S1 (e2e): the script create → get round-trip against the real Godot engine.

The script-group tracer (issue #110): ``gda script create`` writes a .gd
script (from a template or verbatim --content), no-clobber; ``gda script get``
reads its source back with class_name/extends metadata — ``script get`` IS the
structured-level verification of ``script create``'s effect (create → get
returns the source).
"""

import json
import os
import shutil
import subprocess

import pytest

from gda.runner import OPERATIONS_GD
from tests.support import GODOT, Gda, assert_operation_error

from tests.conftest import project_godot

gda = Gda()


@pytest.mark.e2e
def test_script_create_default_template_then_get_round_trip(godot_project):
    # The bare template: create writes `extends Node`, get reads it back. The
    # source on disk IS what get reports — the round-trip proves the write.
    script_path = godot_project / "actor.gd"

    created = gda("script", "create", str(script_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(script_path)
    assert data["extends"] == "Node"
    assert data["class_name"] is None
    assert script_path.exists()

    got = gda("script", "get", str(script_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    # Round-trip: get returns exactly the source create wrote to disk.
    assert got_data["source"] == script_path.read_text(encoding="utf-8")
    assert got_data["source"] == "extends Node\n"
    assert got_data["extends"] == "Node"
    assert got_data["class_name"] is None


@pytest.mark.e2e
def test_script_create_with_extends_parameterizes_the_template(godot_project):
    # --extends parameterizes the template's base class (mirrors scene create
    # --root-type), and get reports it back from the parsed source.
    script_path = godot_project / "sprite.gd"

    created = gda("script", "create", str(script_path), "--extends", "Node2D", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["extends"] == "Node2D"

    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["extends"] == "Node2D"


@pytest.mark.e2e
def test_script_create_with_content_round_trips_verbatim_source_and_metadata(
    godot_project,
):
    # --content supplies verbatim source; get reports it byte-identical and
    # parses the class_name/extends the source declares — without ever compiling
    # the script (issue #30: reading a script must never run it).
    script_path = godot_project / "hero.gd"
    source = "class_name Hero\nextends Node2D\n\nvar speed := 100\n"

    created = gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] == "Hero"
    assert create_data["extends"] == "Node2D"

    got = gda("script", "get", str(script_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["source"] == source
    assert got_data["class_name"] == "Hero"
    assert got_data["extends"] == "Node2D"


@pytest.mark.e2e
def test_script_create_resolves_res_path_against_the_project(godot_project):
    # Script-file addressing via res:// resolves against --project, exactly like
    # scene create (issue #32): the script lands inside the project and reads
    # back through res://.
    gda = Gda(godot_project)

    created = gda("script", "create", "res://hero.gd", "--extends", "Node2D", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert (godot_project / "hero.gd").exists()

    got = gda("script", "get", "res://hero.gd", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["extends"] == "Node2D"


@pytest.mark.e2e
def test_script_create_creates_missing_parent_directories(godot_project):
    # Parent dirs are created before the write (mirrors scene create), reported
    # in created_dirs from outermost to innermost.
    script_path = godot_project / "actors" / "enemies" / "goblin.gd"

    created = gda("script", "create", str(script_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert script_path.exists()
    assert json.loads(created.stdout)["created_dirs"] == [
        str(godot_project / "actors"),
        str(godot_project / "actors" / "enemies"),
    ]


@pytest.mark.e2e
def test_script_create_existing_path_yields_already_exists_without_overwriting(
    godot_project,
):
    # No-clobber: a second create on the same path is refused with already_exists
    # and the original content is left untouched.
    script_path = godot_project / "hero.gd"
    gda("script", "create", str(script_path), "--extends", "Node2D", "--json")
    before = script_path.read_text(encoding="utf-8")

    err = gda.error(
        "script",
        "create",
        str(script_path),
        "--extends",
        "Sprite2D",
        "--json",
        code="already_exists",
    )
    assert str(script_path) in err["message"]
    assert script_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_create_wrong_extension_yields_invalid_path(godot_project):
    # A target that is not a .gd script is an invalid path param; nothing is
    # written.
    target = godot_project / "notes.txt"

    err = gda.error("script", "create", str(target), "--json", code="invalid_path")
    assert ".gd" in err["message"]
    assert str(target) in err["message"]
    assert not target.exists()


@pytest.mark.e2e
def test_script_create_cs_extension_is_refused(godot_project):
    # C# is out of scope for now (it needs the .NET build of Godot, ADR-0003
    # targets the standard build): a .cs target is refused as invalid_path, the
    # same as any non-.gd path, and nothing is written — never half-supported as
    # opaque text.
    target = godot_project / "Player.cs"

    err = gda.error("script", "create", str(target), "--json", code="invalid_path")
    assert ".gd" in err["message"]
    assert str(target) in err["message"]
    assert not target.exists()


@pytest.mark.e2e
def test_script_get_missing_file_yields_path_not_found(godot_project):
    missing = godot_project / "nope.gd"

    err = gda.error("script", "get", str(missing), "--json", code="path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_script_get_unreadable_file_is_path_not_found_not_empty_source(godot_project):
    # The empty-vs-unreadable disambiguation: get_file_as_string returns "" both
    # for an empty file AND on an open error, so an unreadable .gd must be reported
    # as path_not_found ("could not be read"), never mistaken for a (legal) empty
    # source. This pins the open-error half of the guard the empty-source
    # round-trip test (above) leaves uncovered.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("file read permissions do not bind as root")
    locked = godot_project / "locked.gd"
    locked.write_text("extends Node\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        got = gda("script", "get", str(locked), "--json")
    finally:
        locked.chmod(0o600)

    err = assert_operation_error(got, "path_not_found")
    assert str(locked) in err["message"]
    assert "could not be read" in err["message"]


@pytest.mark.e2e
def test_script_get_wrong_extension_yields_invalid_path(godot_project):
    notes = godot_project / "notes.txt"
    notes.write_text("not a script\n", encoding="utf-8")

    err = gda.error("script", "get", str(notes), "--json", code="invalid_path")
    assert ".gd" in err["message"]
    assert str(notes) in err["message"]


@pytest.mark.e2e
def test_script_create_then_get_preserves_a_path_containing_the_end_sentinel(
    godot_project,
):
    # issue #34 parallel: the result echoes the path verbatim and carries the
    # source as a JSON string, so a path or source containing the literal end
    # sentinel must round-trip, not truncate into a parse error.
    script_path = godot_project / "weird<<<GDA:END>>>name.gd"

    created = gda("script", "create", str(script_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["path"] == str(script_path)

    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["source"] == "extends Node\n"


@pytest.mark.e2e
def test_script_get_parses_metadata_past_a_leading_annotation_header(godot_project):
    # class_name/extends lead a GDScript file, but the optional annotation header
    # (@tool, @icon(...)) comes first. The lightweight parser must skip those
    # header lines and still report the real class_name/extends — not give up at
    # the first @-line.
    script_path = godot_project / "widget.gd"
    source = (
        "@tool\n"
        '@icon("res://icon.svg")\n'
        "class_name Widget\n"
        "extends Control\n"
        "\n"
        "func _ready() -> void:\n"
        "\tpass\n"
    )

    created = gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] == "Widget"
    assert create_data["extends"] == "Control"

    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["class_name"] == "Widget"
    assert got_data["extends"] == "Control"


@pytest.mark.e2e
def test_script_get_does_not_mistake_declaration_shaped_body_text_for_metadata(
    godot_project,
):
    # The parser scans only the header and stops at the first real statement, so
    # a `class_name`/`extends`-shaped line deeper in the body (here inside a
    # multiline string) is never mistaken for the declaration: the real extends
    # is reported, and class_name stays null.
    script_path = godot_project / "doc.gd"
    source = (
        'extends Node\n\nvar doc := """\nclass_name Injected\nextends Injected\n"""\n'
    )

    created = gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["extends"] == "Node"
    assert create_data["class_name"] is None

    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["source"] == source
    assert got_data["extends"] == "Node"
    assert got_data["class_name"] is None


@pytest.mark.e2e
def test_script_get_keeps_a_quoted_base_class_path_intact(godot_project):
    # `extends "res://Base.gd"` (base-class-by-path) is legal GDScript. The
    # metadata parser keeps the quoted string whole up to its closing quote —
    # including a '#' inside the path, which is part of the string, not an inline
    # comment — rather than truncating at the '#' or splitting on whitespace.
    script_path = godot_project / "derived.gd"
    source = 'extends "res://weapons/a#b.gd"\n'

    created = gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["extends"] == '"res://weapons/a#b.gd"'

    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["extends"] == '"res://weapons/a#b.gd"'


@pytest.mark.e2e
def test_script_list_enumerates_created_scripts(godot_project):
    # script list (issue #117) enumerates the project's .gd scripts by walking
    # res://: two scripts created at different depths both appear, each with its
    # res:// path and the class_name/extends parsed from raw source. The listing
    # IS the structured-level verification of what script create wrote.
    gda = Gda(godot_project)

    assert (
        gda(
            "script",
            "create",
            "res://hero.gd",
            "--content",
            "class_name Hero\nextends Node2D\n",
            "--json",
        ).returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://lib/util.gd", "--extends", "RefCounted", "--json"
        ).returncode
        == 0
    )

    listed = gda("script", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    scripts = json.loads(listed.stdout)["scripts"]
    by_path = {s["path"]: s for s in scripts}
    assert by_path["res://hero.gd"]["class_name"] == "Hero"
    assert by_path["res://hero.gd"]["extends"] == "Node2D"
    assert by_path["res://lib/util.gd"]["class_name"] is None
    assert by_path["res://lib/util.gd"]["extends"] == "RefCounted"


@pytest.mark.e2e
def test_script_list_on_empty_project_is_an_empty_listing(godot_project):
    # A project with no scripts is a valid, empty listing — not an error (the
    # res://.godot import cache must not leak in as a phantom script).
    gda = Gda(godot_project)

    listed = gda("script", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)["scripts"] == []


@pytest.mark.e2e
def test_script_list_without_project_yields_project_not_found(tmp_path):
    # script list cannot enumerate res:// projectless: run from a non-project
    # directory with no --project, it must refuse with the structured
    # project_not_found code rather than return a misleading empty listing.
    err = gda.error("script", "list", "--json", cwd=tmp_path, code="project_not_found")

    assert "--project" in err["message"]


@pytest.mark.e2e
def test_script_delete_removes_a_script_and_names_what_was_removed(godot_project):
    # script delete (issue #117) removes a script file and names the removed
    # script's metadata. The round-trip verifier: script list before shows the
    # script, delete reports the removed class_name/extends, and script list
    # after no longer shows it.
    gda = Gda(godot_project)
    assert (
        gda(
            "script",
            "create",
            "res://hero.gd",
            "--content",
            "class_name Hero\nextends Node2D\n",
            "--json",
        ).returncode
        == 0
    )
    script_path = godot_project / "hero.gd"
    assert script_path.exists()
    listed_before = json.loads(gda("script", "list", "--json").stdout)["scripts"]
    assert any(s["path"] == "res://hero.gd" for s in listed_before)

    deleted = gda("script", "delete", "res://hero.gd", "--json")

    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    data = json.loads(deleted.stdout)
    assert data["path"] == "res://hero.gd"
    assert data["class_name"] == "Hero"
    assert data["extends"] == "Node2D"
    # The file is gone from disk, not just from the report.
    assert not script_path.exists()
    assert json.loads(gda("script", "list", "--json").stdout)["scripts"] == []


@pytest.mark.e2e
def test_script_delete_missing_file_yields_path_not_found(godot_project):
    missing = godot_project / "nope.gd"

    err = gda.error("script", "delete", str(missing), "--json", code="path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_script_delete_wrong_extension_yields_invalid_path_and_leaves_it(godot_project):
    # The delete safety boundary mirrors create/get: delete only removes a .gd
    # script, so a non-.gd target is refused with invalid_path and left on disk —
    # delete never erases arbitrary files.
    notes = godot_project / "notes.txt"
    notes.write_text("not a script\n", encoding="utf-8")

    err = gda.error("script", "delete", str(notes), "--json", code="invalid_path")
    assert ".gd" in err["message"]
    assert str(notes) in err["message"]
    # The non-script file survives the refusal.
    assert notes.read_text(encoding="utf-8") == "not a script\n"


@pytest.mark.e2e
def test_script_set_search_replace_edits_in_place_and_round_trips_via_get(
    godot_project,
):
    # search-replace mode (issue #118): every literal occurrence of --search is
    # replaced with --replace; script get round-trips the edited source on disk.
    script_path = godot_project / "hero.gd"
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        "extends Node\nvar a := Node\n",
        "--json",
    )

    edited = gda(
        "script",
        "set",
        str(script_path),
        "--search",
        "Node",
        "--replace",
        "Node2D",
        "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    assert json.loads(edited.stdout)["extends"] == "Node2D"
    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    # Both occurrences replaced; the edited source IS what get reports.
    assert json.loads(got.stdout)["source"] == "extends Node2D\nvar a := Node2D\n"
    assert (
        script_path.read_text(encoding="utf-8") == "extends Node2D\nvar a := Node2D\n"
    )


@pytest.mark.e2e
def test_script_set_with_external_edit_in_window_yields_file_changed_externally(
    godot_project,
):
    # Staleness guard for the text-write path (issue #226): script set reads the .gd,
    # transforms it, then writes it back; if the file changes on disk in that window a
    # blind write would clobber the external edit. The production-inert seam
    # (GDA_TEST_PERTURB_BEFORE_SAVE) simulates that edit, and the guard refuses.
    script_path = godot_project / "hero.gd"
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        "extends Node\nvar a := 1\n",
        "--json",
    )

    err = gda.error(
        "script",
        "set",
        str(script_path),
        "--search",
        "1",
        "--replace",
        "2",
        "--json",
        extra_env={"GDA_TEST_PERTURB_BEFORE_SAVE": "1"},
        code="file_changed_externally",
    )
    assert str(script_path) in err["message"]

    # The edit did NOT land: the original "var a := 1" is still present (the seam only
    # appends one byte, so assert the EFFECT — the search/replace did not apply).
    assert "var a := 1" in script_path.read_text(encoding="utf-8")
    assert not list(godot_project.rglob(".gda-*"))


@pytest.mark.e2e
def test_script_set_line_range_replaces_the_span_and_round_trips_via_get(godot_project):
    # line-range mode: replace lines 2..3 (1-based, inclusive) with new content;
    # the rest of the file is untouched. Lines are the parts split on "\n".
    script_path = godot_project / "actor.gd"
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        "extends Node\nvar a := 1\nvar b := 2\nfunc f(): pass\n",
        "--json",
    )

    edited = gda(
        "script",
        "set",
        str(script_path),
        "--start-line",
        "2",
        "--end-line",
        "3",
        "--content",
        "var x := 9",
        "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    got = gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["source"] == (
        "extends Node\nvar x := 9\nfunc f(): pass\n"
    )


@pytest.mark.e2e
def test_script_set_line_range_defaults_end_to_start_for_a_single_line(godot_project):
    # --end-line defaults to --start-line: a single-line replace.
    script_path = godot_project / "single.gd"
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        "extends Node\nvar a := 1\nvar b := 2\n",
        "--json",
    )

    edited = gda(
        "script",
        "set",
        str(script_path),
        "--start-line",
        "2",
        "--content",
        "var a := 99",
        "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    got = gda("script", "get", str(script_path), "--json")
    assert json.loads(got.stdout)["source"] == "extends Node\nvar a := 99\nvar b := 2\n"


@pytest.mark.e2e
def test_script_set_line_range_preserves_crlf_line_endings(godot_project):
    # line-range splits/rejoins on the file's OWN newline, so editing a CRLF
    # script keeps CRLF (not a mixed-ending span). The replacement text's own
    # endings are normalized onto the file's.
    script_path = godot_project / "crlf.gd"
    script_path.write_bytes(b"extends Node\r\nvar a := 1\r\nvar b := 2\r\n")

    edited = gda(
        "script",
        "set",
        str(script_path),
        "--start-line",
        "2",
        "--content",
        "var x := 9",
        "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    # CRLF preserved on every line, including the untouched ones — no LF/CRLF mix.
    assert script_path.read_bytes() == b"extends Node\r\nvar x := 9\r\nvar b := 2\r\n"


@pytest.mark.e2e
def test_script_set_full_overwrites_the_whole_file_and_round_trips_via_get(
    godot_project,
):
    # full mode: --content with no --start-line overwrites the entire file.
    script_path = godot_project / "full.gd"
    gda("script", "create", str(script_path), "--content", "extends Node\n", "--json")

    new_source = "class_name Hero\nextends Node2D\n\nvar speed := 100\n"
    edited = gda("script", "set", str(script_path), "--content", new_source, "--json")

    assert edited.returncode == 0, edited.stdout + edited.stderr
    data = json.loads(edited.stdout)
    assert data["class_name"] == "Hero"
    assert data["extends"] == "Node2D"
    got = gda("script", "get", str(script_path), "--json")
    assert json.loads(got.stdout)["source"] == new_source


@pytest.mark.e2e
def test_script_set_no_search_match_is_refused_and_leaves_file_untouched(godot_project):
    # A search string the source does not contain is refused with no_search_match
    # and the file is left exactly as it was — the edit landed nowhere.
    script_path = godot_project / "hero.gd"
    gda("script", "create", str(script_path), "--content", "extends Node\n", "--json")
    before = script_path.read_text(encoding="utf-8")

    gda.error(
        "script",
        "set",
        str(script_path),
        "--search",
        "Sprite2D",
        "--replace",
        "Node2D",
        "--json",
        code="no_search_match",
    )
    assert script_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_set_out_of_bounds_line_range_is_refused_and_leaves_file_untouched(
    godot_project,
):
    # A line range past the file's bounds is refused with invalid_line_range and
    # the file is left untouched.
    script_path = godot_project / "hero.gd"
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        "extends Node\nvar a := 1\n",
        "--json",
    )
    before = script_path.read_text(encoding="utf-8")

    gda.error(
        "script",
        "set",
        str(script_path),
        "--start-line",
        "9",
        "--content",
        "var x := 0",
        "--json",
        code="invalid_line_range",
    )
    assert script_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_set_missing_file_yields_path_not_found(godot_project):
    # set edits an existing script; a missing target is path_not_found, never a
    # silent create.
    missing = godot_project / "nope.gd"

    err = gda.error(
        "script",
        "set",
        str(missing),
        "--content",
        "extends Node\n",
        "--json",
        code="path_not_found",
    )
    assert str(missing) in err["message"]
    assert not missing.exists()


# --- script validate (issue #118) ---


@pytest.mark.e2e
def test_script_validate_valid_script_reports_valid_true_no_diagnostics(godot_project):
    # The mechanism gate (issue #118): a self-contained `extends Node` script
    # compiles (GDScript.reload() == OK), so validate reports valid=true, no
    # error_string, no diagnostics — exit 0.
    #
    # Bound to its project since ADR-0006's 2026-08-31 amendment (#697): the script
    # lives in one, so validating it without naming it is now refused. The genuinely
    # projectless arm — a loose `.gd` no project.godot claims — is
    # `tests/project/test_e2e_res_containment.py`.
    gda = Gda(godot_project)
    script_path = godot_project / "ok.gd"
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        'extends Node\n\nfunc greet() -> String:\n\treturn "hi"\n',
        "--json",
    )

    validated = gda("script", "validate", str(script_path), "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True
    assert len(data["scripts"]) == 1
    assert data["scripts"][0]["error_string"] is None
    assert data["scripts"][0]["diagnostics"] == []


@pytest.mark.e2e
@pytest.mark.parametrize("form", ["ok.gd", "res://ok.gd"])
def test_script_validate_accepts_both_path_forms(godot_project, form):
    # The `script validate` half of #675's AC: the group has always taken both the
    # project-relative and the res:// form, and `script run` now takes the same two (see
    # tests/script/test_e2e_script_run.py). Pinned here so the shared representation is
    # a guarded contract on BOTH commands rather than an accident of this build — the
    # property that lets an agent address a script once and use it for either.
    gda = Gda(godot_project)
    (godot_project / "ok.gd").write_text("extends Node\n", encoding="utf-8")

    validated = gda("script", "validate", form, "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True
    assert data["scripts"][0]["diagnostics"] == []


@pytest.mark.e2e
def test_script_validate_broken_script_is_success_with_a_real_diagnostic(godot_project):
    # The mechanism gate's hard half: a deliberately BROKEN script is a SUCCESSFUL
    # op (exit 0) reporting valid=false, and at least one diagnostic with a real
    # `line` and non-empty `message` — proving the stderr-parsing regex against
    # the REAL engine output, not a fixture.
    gda = Gda(godot_project)
    script_path = godot_project / "broken.gd"
    # `var x =` with no initializer is a parse error the engine reports on its line.
    gda(
        "script",
        "create",
        str(script_path),
        "--content",
        "extends Node\n\nvar x =\n",
        "--json",
    )

    validated = gda("script", "validate", str(script_path), "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    entry = data["scripts"][0]
    assert entry["error_string"] is not None
    # Exactly one diagnostic, at the error's real source line (3: `var x =`) —
    # pinned (not just `len>=1`/`line>=1`) so a regression in the stderr pairing
    # (a borrowed/duplicated frame line) fails this real-engine gate.
    assert len(entry["diagnostics"]) == 1
    diag = entry["diagnostics"][0]
    assert diag["line"] == 3
    assert diag["message"]
    # Column is unavailable on the standard build.
    assert diag["column"] is None


@pytest.mark.e2e
def test_script_validate_relative_preload_resolves_at_the_real_res_path(godot_project):
    # The #131 fix: validate compiles the script AT ITS REAL res:// path, so a
    # relative `preload("sibling.gd")` resolves against the script's own res://
    # location exactly as the engine loads it. The sibling is present and compiles,
    # so the dependent script is valid=true under --project — not a false negative
    # from compiling an anonymous in-memory GDScript that has no res:// location to
    # resolve the relative reference against.
    gda = Gda(godot_project)
    assert (
        gda(
            "script",
            "create",
            "res://sibling.gd",
            "--content",
            "extends Node\nclass_name Sibling\n",
            "--json",
        ).returncode
        == 0
    )
    assert (
        gda(
            "script",
            "create",
            "res://uses_sibling.gd",
            "--content",
            'extends Node\n\nconst S = preload("sibling.gd")\n\n'
            "func use() -> void:\n\tvar _x = S.new()\n",
            "--json",
        ).returncode
        == 0
    )

    validated = gda("script", "validate", "res://uses_sibling.gd", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True
    assert data["scripts"][0]["error_string"] is None
    assert data["scripts"][0]["diagnostics"] == []


@pytest.mark.e2e
def test_script_validate_broken_script_under_project_still_reports_diagnostics(
    godot_project,
):
    # The #131 regression guard: compiling at the real res:// path must not break a
    # genuinely broken script's verdict — it is still a SUCCESSFUL op (exit 0)
    # reporting valid=false, and the stderr-parsed line/message diagnostic still
    # works under --project (the reload frame now names the real res:// path, which
    # the diagnostics parser pairs exactly as before).
    gda = Gda(godot_project)
    # `var x =` with no initializer is a parse error the engine reports on its line.
    assert (
        gda(
            "script",
            "create",
            "res://broken.gd",
            "--content",
            "extends Node\n\nvar x =\n",
            "--json",
        ).returncode
        == 0
    )

    validated = gda("script", "validate", "res://broken.gd", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    entry = data["scripts"][0]
    assert entry["error_string"] is not None
    assert len(entry["diagnostics"]) == 1
    diag = entry["diagnostics"][0]
    assert diag["line"] == 3
    assert diag["message"]
    assert diag["column"] is None


@pytest.mark.e2e
def test_script_validate_missing_file_yields_path_not_found(godot_project):
    # validate only op-fails for op errors: a missing file is path_not_found, NOT
    # a valid=false success. Named with its project (#697) so the op-level answer is
    # what the call reaches — a path inside an UNNAMED project is refused for the
    # project context first, which is a different (and equally true) verdict.
    missing = godot_project / "nope.gd"

    err = Gda(godot_project).error(
        "script", "validate", str(missing), "--json", code="path_not_found"
    )
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_script_validate_wrong_extension_yields_invalid_path(godot_project):
    notes = godot_project / "notes.txt"
    notes.write_text("not a script\n", encoding="utf-8")

    err = Gda(godot_project).error(
        "script", "validate", str(notes), "--json", code="invalid_path"
    )
    assert ".gd" in err["message"]


# --- script validate: batch and project mode (#663, GDA-DF-008) ---


def _batch_project(root, name: str = "game"):
    """A project holding two compiling scripts and one that does not.

    The GDA-DF-008 shape at its smallest: the related scripts a change touches
    together, one of which is broken. ``bad.gd``'s `var x =` is a parse error the
    engine reports on its own line (3), so the per-file diagnostic is checkable.
    """
    project = root / name
    project.mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot("gda-e2e-batch"), encoding="utf-8"
    )
    (project / "a.gd").write_text("extends Node\n", encoding="utf-8")
    (project / "bad.gd").write_text("extends Node\n\nvar x =\n", encoding="utf-8")
    (project / "c.gd").write_text(
        "extends Node\n\nfunc top() -> int:\n\treturn 3\n", encoding="utf-8"
    )
    return project


@pytest.mark.e2e
def test_script_validate_batch_uses_one_engine_launch_for_every_script(tmp_path):
    # The #663 AC, against the real engine: one invocation validates three scripts
    # in ONE launch, reports a per-file verdict for each, and the aggregate is
    # false because one of them is broken — while the command still exits 0.
    #
    # The launch count is read off the engine's own stderr: `operations.gd` logs
    # `running operation: script-validate` once per dispatched op, and one op
    # dispatch is one process. Three occurrences would be the pre-#663 behaviour
    # (one launch per script) passing every other assertion here.
    project = _batch_project(tmp_path)
    gda = Gda(project)

    validated = gda(
        "script", "validate", "res://a.gd", "res://bad.gd", "res://c.gd", "--json"
    )

    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert validated.stderr.count("running operation: script-validate") == 1
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["project_root"] == str(project)
    assert [entry["path"] for entry in data["scripts"]] == [
        "res://a.gd",
        "res://bad.gd",
        "res://c.gd",
    ]
    assert [entry["valid"] for entry in data["scripts"]] == [True, False, True]
    # Per-FILE diagnostics: the broken script's parse error is attributed to IT,
    # at its real source line, and the two valid scripts carry none.
    assert data["scripts"][0]["diagnostics"] == []
    assert data["scripts"][2]["diagnostics"] == []
    broken = data["scripts"][1]
    assert broken["error_string"] is not None
    assert len(broken["diagnostics"]) == 1
    assert broken["diagnostics"][0]["line"] == 3
    assert broken["diagnostics"][0]["message"]


@pytest.mark.e2e
def test_script_validate_all_validates_every_script_in_the_project(tmp_path):
    # Project mode: `--all` enumerates the project's res:// tree itself and reports
    # the same shape, so an agent can screen a whole project in one launch without
    # first listing its scripts.
    project = _batch_project(tmp_path)
    gda = Gda(project)

    validated = gda("script", "validate", "--all", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert validated.stderr.count("running operation: script-validate") == 1
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    # Every .gd in the project, in the engine's sorted enumeration order.
    assert [entry["path"] for entry in data["scripts"]] == [
        "res://a.gd",
        "res://bad.gd",
        "res://c.gd",
    ]
    assert [entry["valid"] for entry in data["scripts"]] == [True, False, True]
    assert data["scripts"][1]["diagnostics"][0]["line"] == 3


@pytest.mark.e2e
def test_script_validate_batch_reports_a_repeated_path_once_per_occurrence(tmp_path):
    # The documented duplicate behaviour, and it needs a REAL engine: each compile
    # calls `GDScript.take_over_path(path)`, so a repeated path claims the same
    # res:// cache slot twice inside one process. Whether the engine tolerates that
    # — and still reports the same verdict and the same diagnostic the second time
    # — is exactly what a fake runner cannot vouch for. It must, because gda
    # promises entry i corresponds to argument i and so never deduplicates.
    project = _batch_project(tmp_path)
    gda = Gda(project)

    validated = gda(
        "script", "validate", "res://bad.gd", "res://a.gd", "res://bad.gd", "--json"
    )

    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert validated.stderr.count("running operation: script-validate") == 1
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert [entry["path"] for entry in data["scripts"]] == [
        "res://bad.gd",
        "res://a.gd",
        "res://bad.gd",
    ]
    assert [entry["valid"] for entry in data["scripts"]] == [False, True, False]
    # Both occurrences carry the SAME verdict and the SAME diagnostic: the second
    # take_over_path did not degrade the compile into a different answer.
    assert data["scripts"][0] == data["scripts"][2]
    assert data["scripts"][0]["diagnostics"][0]["line"] == 3
    assert data["scripts"][1]["diagnostics"] == []


@pytest.mark.e2e
def test_script_validate_all_enumerates_a_nested_dot_godot_directory(tmp_path):
    # The exclusion is the engine's ONE cache directory, `res://.godot` — not every
    # directory that happens to be named `.godot`. A nested one is user content
    # (an addon vendoring a sample project, a fixture tree), and skipping it made
    # `--all` report `valid: true` for a project holding an invalid script: a
    # FALSE-POSITIVE aggregate, which is the one thing this command must never
    # produce. The root cache stays excluded — the engine owns it, and its contents
    # are import artefacts no agent authored.
    project = tmp_path / "nested-cache"
    (project / "nested" / ".godot").mkdir(parents=True)
    (project / ".godot").mkdir(parents=True, exist_ok=True)
    (project / "project.godot").write_text(
        project_godot("gda-e2e-nested-cache"), encoding="utf-8"
    )
    (project / "top.gd").write_text("extends Node\n", encoding="utf-8")
    (project / "nested" / ".godot" / "hidden.gd").write_text(
        "extends Node\n\nvar x =\n", encoding="utf-8"
    )
    # Authored INTO the engine's own cache: it must stay invisible to both
    # commands, or the fix would have swapped one wrong enumeration for another.
    (project / ".godot" / "engine_cache.gd").write_text(
        "extends Node\n\nvar y =\n", encoding="utf-8"
    )
    gda = Gda(project)

    validated = gda("script", "validate", "--all", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert [entry["path"] for entry in data["scripts"]] == [
        "res://nested/.godot/hidden.gd",
        "res://top.gd",
    ]
    assert data["valid"] is False
    assert data["scripts"][0]["diagnostics"][0]["line"] == 3

    # `script list` shares the enumeration, so the same correction is observable
    # there — deliberately, and covered here rather than left to be discovered.
    listed = gda("script", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert [entry["path"] for entry in json.loads(listed.stdout)["scripts"]] == [
        "res://nested/.godot/hidden.gd",
        "res://top.gd",
    ]


@pytest.mark.e2e
def test_script_validate_all_on_a_project_with_no_scripts_is_vacuously_valid(tmp_path):
    # The empty-batch edge of project mode: a project holding no .gd at all is a
    # successful, EMPTY listing with a vacuously true aggregate — not a failure and
    # not a false negative. Same reading as `script list` on an empty project.
    project = tmp_path / "bare"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot("gda-e2e-bare"), encoding="utf-8"
    )

    validated = Gda(project)("script", "validate", "--all", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["scripts"] == []
    assert data["valid"] is True
    assert data["project_root"] == str(project)


@pytest.mark.e2e
def test_script_validate_refuses_a_batch_that_spans_two_projects(tmp_path):
    # ADR-0006's one resolved project, applied to the whole batch: a batch whose
    # paths span projects is refused before anything is compiled, rather than
    # compiling the outsider against a root that does not own it and reporting the
    # false res:// cascade for it.
    project = _batch_project(tmp_path)
    _, other_project, outsider = _nested_project_script(tmp_path / "elsewhere")

    validated = gda(
        "script",
        "validate",
        str(project / "a.gd"),
        str(outsider),
        "--project",
        str(project),
        "--json",
    )

    err = assert_operation_error(validated, "target_outside_project")
    assert str(outsider) in err["message"]
    assert str(project) in err["message"]
    assert other_project.exists()
    # Nothing was compiled: no verdict for the script that WAS inside, either.
    assert '"valid"' not in validated.stdout


# --- script validate: project context (#658, GDA-DF-035) ---


def _nested_project_script(root):
    """A project NESTED in a plain workspace dir, holding a res://-dependent script.

    The GDA-DF-035 shape: a game project that lives inside a larger repository,
    with a script whose ``res://`` preload only resolves against the project's own
    root. Returns ``(workspace, project, script)``.
    """
    workspace = root / "workspace"
    project = workspace / "game"
    (project / "scripts").mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot("gda-e2e-nested"), encoding="utf-8"
    )
    (project / "scripts" / "card.gd").write_text(
        "extends Node\n\nclass_name Card\n\nfunc rank() -> int:\n\treturn 3\n",
        encoding="utf-8",
    )
    script = project / "deck.gd"
    script.write_text(
        "extends Node\n\n"
        'const Card = preload("res://scripts/card.gd")\n\n'
        "func top() -> int:\n"
        "\tvar c := Card.new()\n"
        "\treturn c.rank()\n",
        encoding="utf-8",
    )
    return workspace, project, script


@pytest.mark.e2e
def test_script_validate_from_an_ancestor_is_refused_and_names_the_owner(tmp_path):
    # THE dogfooded invocation (GDA-DF-035 reading 1), and the pin that moved with
    # ADR-0006's 2026-08-31 amendment (#697). A game project inside a larger
    # repository, validated from the repository root: nothing resolves, so the
    # script used to be compiled by a PROJECTLESS engine, where `res://scripts/
    # card.gd` is missing and a type-inference error is derived from that miss — a
    # cascade of false errors on a script that is perfectly valid in its own
    # project, with `project_root: null` as the only clue.
    #
    # gda now refuses instead and names the project to pass. It still does not
    # DERIVE it: the owner is reported, resolution is untouched, and the true
    # verdict is one flag away — which the second half proves is the same verdict
    # as before.
    workspace, project, script = _nested_project_script(tmp_path)

    from_ancestor = gda("script", "validate", "game/deck.gd", "--json", cwd=workspace)

    assert_operation_error(from_ancestor, "target_outside_project")
    evidence = json.loads(from_ancestor.stdout)["error"]["evidence"]
    assert evidence["owning_project"] == str(project.resolve())
    # No engine ran, so the false cascade does not exist to be misread.
    assert '"valid"' not in from_ancestor.stdout

    with_owning_project = gda(
        "script", "validate", str(script), "--project", str(project), "--json"
    )

    assert with_owning_project.returncode == 0, (
        with_owning_project.stdout + with_owning_project.stderr
    )
    right_root = json.loads(with_owning_project.stdout)
    assert right_root["valid"] is True
    assert right_root["scripts"][0]["diagnostics"] == []
    assert right_root["project_root"] == str(project)


@pytest.mark.e2e
def test_script_validate_refuses_a_script_outside_the_resolved_project(tmp_path):
    # The refusal at the real-engine tier: pointed at a project that does not own
    # the script, gda reports the mismatch itself rather than the engine's false
    # dependency errors — and names both sides. The refusal is structured
    # (project_not_found, exit 4), so an agent branches on it instead of reading a
    # cascade of parse errors that describe nothing wrong with the file.
    _, project, script = _nested_project_script(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "project.godot").write_text(
        project_godot("gda-e2e-other"), encoding="utf-8"
    )

    validated = gda(
        "script", "validate", str(script), "--project", str(other), "--json"
    )

    err = assert_operation_error(validated, "target_outside_project")
    assert str(script) in err["message"]
    assert str(other) in err["message"]
    # Refused BEFORE parsing: no engine ran, so no diagnostic about the file.
    assert "res://scripts/card.gd" not in validated.stdout
    assert err["diagnostics"] == ""


@pytest.mark.e2e
def test_script_validate_accepts_a_file_symlinked_into_the_project(tmp_path):
    # The containment check judges a symlinked file by BOTH readings, and this is
    # the real-engine proof of the lexical one: the monorepo shared-addon layout
    # (game/addons/cardlib -> ../../libs/cardlib), where the file physically lives
    # outside the project but is addressed through the project's own tree.
    #
    # The engine agrees with that reading — the script's `res://addons/cardlib/
    # card.gd` preload resolves THROUGH the link — so `valid` is true. Judging the
    # target by its resolve()d location alone would refuse a call that demonstrably
    # works, and name a path the caller never typed.
    #
    # The second half is the guard that this is not a blanket escape hatch: the
    # SAME physical file, addressed by its outside spelling, is still refused.
    project = tmp_path / "game"
    (project / "addons").mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot("gda-e2e-symlinked"), encoding="utf-8"
    )
    library = tmp_path / "libs" / "cardlib"
    library.mkdir(parents=True)
    (library / "card.gd").write_text(
        "extends Node\n\nclass_name SymlinkedCard\n\nfunc rank() -> int:\n\treturn 3\n",
        encoding="utf-8",
    )
    (library / "deck.gd").write_text(
        "extends Node\n\n"
        'const Card = preload("res://addons/cardlib/card.gd")\n\n'
        "func top() -> int:\n"
        "\tvar c := Card.new()\n"
        "\treturn c.rank()\n",
        encoding="utf-8",
    )
    (project / "addons" / "cardlib").symlink_to(library, target_is_directory=True)
    through_the_link = project / "addons" / "cardlib" / "deck.gd"

    validated = gda(
        "script", "validate", str(through_the_link), "--project", str(project), "--json"
    )

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True, data
    assert data["scripts"][0]["diagnostics"] == []
    assert data["project_root"] == str(project)

    # Same file, outside spelling: outside under both readings, so still refused.
    gda.error(
        "script",
        "validate",
        str(library / "deck.gd"),
        "--project",
        str(project),
        "--json",
        code="target_outside_project",
    )


@pytest.mark.e2e
def test_script_validate_relative_target_from_an_ancestor_cwd_agrees_with_the_engine(
    tmp_path,
):
    # The full chain, against the real engine: run from the workspace ABOVE the
    # project and name both the project and the script relatively. gda hands the
    # path to the engine unchanged and the engine anchors it at `--path game`, so
    # the containment check has to anchor it there too — judging it against gda's
    # own cwd refused an invocation the engine validates fine, and that the README
    # documents. Both channels are covered because the argv and --params-json
    # paths share the recipe.
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot("gda-e2e-ancestor"), encoding="utf-8"
    )
    (project / "deck.gd").write_text(
        "extends Node\n\nfunc top() -> int:\n\treturn 3\n", encoding="utf-8"
    )

    from_workspace = Gda(cwd=tmp_path)

    argv = from_workspace(
        "script", "validate", "deck.gd", "--project", "game", "--json"
    )

    assert argv.returncode == 0, argv.stdout + argv.stderr
    data = json.loads(argv.stdout)
    assert data["valid"] is True, data
    # The engine found game/deck.gd, and the reported root is absolute — not the
    # bare relative "game" that was typed.
    assert data["project_root"] == str(project)

    params_json = from_workspace(
        "script",
        "validate",
        "--params-json",
        json.dumps({"paths": ["deck.gd"]}),
        "--project",
        "game",
        "--json",
    )

    assert params_json.returncode == 0, params_json.stdout + params_json.stderr
    assert json.loads(params_json.stdout) == data


@pytest.mark.e2e
def test_script_validate_refuses_a_symlink_dot_dot_pivot_out_of_the_project(tmp_path):
    # The containment bypass, at the real-engine tier: with
    # `game/pivot -> ../outside/deep`, the input `game/pivot/../deck.gd` collapses
    # textually to `game/deck.gd` while really naming `outside/deck.gd`. Trusting
    # the lexical reading there let the engine COMPILE the outside script and
    # report a verdict on it. It must now be refused, and no verdict may appear.
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot("gda-e2e-pivot"), encoding="utf-8"
    )
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deck.gd").write_text(
        "extends Node\n\nfunc outside_secret() -> int:\n\treturn 99\n", encoding="utf-8"
    )
    (project / "pivot").symlink_to(outside / "deep", target_is_directory=True)

    validated = gda(
        "script",
        "validate",
        str(project / "pivot" / ".." / "deck.gd"),
        "--project",
        str(project),
        "--json",
    )

    err = assert_operation_error(validated, "target_outside_project")
    # The refusal names where the target REALLY is, not the collapsed spelling.
    assert str((outside / "deck.gd").resolve()) in err["message"]
    # Nothing was compiled: no verdict, and no engine diagnostic about the file.
    assert '"valid"' not in validated.stdout
    assert err["diagnostics"] == ""


@pytest.mark.e2e
def test_script_validate_refuses_an_outside_path_that_merely_contains_a_scheme(
    tmp_path,
):
    # A colon is a legal POSIX filename character, so `<dir>://deck.gd` is an
    # ordinary filesystem path. Classifying it as engine-virtual skipped
    # containment and the engine opened the outside file; it is now refused.
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot("gda-e2e-scheme"), encoding="utf-8"
    )
    odd = tmp_path / "outside:"
    odd.mkdir()
    (odd / "deck.gd").write_text(
        "extends Node\n\nfunc scheme_secret() -> int:\n\treturn 7\n", encoding="utf-8"
    )

    validated = gda(
        "script", "validate", f"{odd}//deck.gd", "--project", str(project), "--json"
    )

    assert_operation_error(validated, "target_outside_project")
    assert '"valid"' not in validated.stdout


# --- script attach (issue #118) ---


@pytest.mark.e2e
def test_script_attach_binds_script_to_node_and_scene_references_it(godot_project):
    # script attach (issue #118) loads a scene, resolves a node by node path,
    # attaches a .gd, and saves. Verify by reading the saved .tscn back: the
    # script path now appears as an ext_resource the node references, the result
    # echoes the script's class_name, and the scene still re-loads (node list).
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script",
            "create",
            "res://hero.gd",
            "--content",
            "class_name Hero\nextends Node2D\n",
            "--json",
        ).returncode
        == 0
    )

    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://hero.gd",
        "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    data = json.loads(attached.stdout)
    assert data["node"] == "."
    assert data["script"] == "res://hero.gd"
    assert data["class_name"] == "Hero"
    # The saved .tscn now references the script as an ext_resource on the root.
    saved = (godot_project / "main.tscn").read_text(encoding="utf-8")
    assert "hero.gd" in saved
    assert 'type="Script"' in saved
    # The scene still re-loads after the mutation.
    listed = gda("node", "list", "res://main.tscn", "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr


@pytest.mark.e2e
def test_script_attach_to_a_descendant_node(godot_project):
    # Attach addresses the node by the #53 node path: a descendant, not just the
    # root. The script lands on that exact node.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "node",
            "add",
            "res://main.tscn",
            "--type",
            "Sprite2D",
            "--name",
            "Hero",
            "--json",
        ).returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://hero.gd", "--extends", "Sprite2D", "--json"
        ).returncode
        == 0
    )

    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        "Hero",
        "--script",
        "res://hero.gd",
        "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    assert json.loads(attached.stdout)["node"] == "Hero"
    saved = (godot_project / "main.tscn").read_text(encoding="utf-8")
    assert "hero.gd" in saved


@pytest.mark.e2e
def test_script_attach_no_class_name_echoes_null_class_name(godot_project):
    # A script with no class_name attaches fine and the result carries null.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://plain.gd", "--extends", "Node", "--json"
        ).returncode
        == 0
    )

    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://plain.gd",
        "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    assert json.loads(attached.stdout)["class_name"] is None


@pytest.mark.e2e
def test_script_attach_non_compiling_script_yields_script_compile_failed(godot_project):
    # attach REQUIRES the script to compile: the headless engine silently rejects
    # a non-compiling script from set_script (the bind never takes, a re-pack
    # saves no script), so attach must refuse with script_compile_failed rather
    # than report a phantom success over a scene with nothing attached. The scene
    # is left untouched.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    # `var x =` has no initializer — a genuine parse error; the script does not
    # compile. script validate would report valid=false on it.
    assert (
        gda(
            "script",
            "create",
            "res://broken.gd",
            "--content",
            "extends Node2D\n\nvar x =\n",
            "--json",
        ).returncode
        == 0
    )
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://broken.gd",
        "--json",
        code="script_compile_failed",
    )
    assert "broken.gd" in err["message"]
    # The refusal leaves the scene exactly as it was — no half-applied mutation.
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_attach_missing_preload_target_yields_missing_dependency(
    godot_project,
):
    # A missing preload target is a dependency-ordering problem, not generic
    # prose-only compile stderr: the structured error names the missing res://
    # path, and the scene is left untouched.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script",
            "create",
            "res://enemy.gd",
            "--content",
            'extends Node2D\n\nconst Projectile = preload("res://missing_projectile.tscn")\n',
            "--json",
        ).returncode
        == 0
    )
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://enemy.gd",
        "--json",
        code="missing_dependency",
    )
    assert "res://missing_projectile.tscn" in err["message"]
    assert "res://enemy.gd" in err["message"]
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_attach_ignores_preload_mentions_in_comments_and_strings(
    godot_project,
):
    # The missing-preload gate must follow executable GDScript syntax, not the
    # project reference graph's raw text scan. Mentioning future assets in comments
    # or string literals is not a preload dependency and must not block attach.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script",
            "create",
            "res://enemy.gd",
            "--content",
            "\n".join(
                [
                    "extends Node2D",
                    "",
                    '# preload("res://missing_projectile.tscn")',
                    'var note := "preload(\\"res://also_missing.tscn\\")"',
                    "",
                ]
            ),
            "--json",
        ).returncode
        == 0
    )

    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://enemy.gd",
        "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    saved = (godot_project / "main.tscn").read_text(encoding="utf-8")
    assert 'path="res://enemy.gd"' in saved


@pytest.mark.e2e
def test_script_attach_multiline_missing_preload_target_yields_missing_dependency(
    godot_project,
):
    # A valid preload call may split the opening paren and string literal across
    # lines. It should still get the same stable missing_dependency result as the
    # single-line form.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script",
            "create",
            "res://enemy.gd",
            "--content",
            "\n".join(
                [
                    "extends Node2D",
                    "",
                    "const Projectile = preload(",
                    '    "res://missing_projectile.tscn"',
                    ")",
                    "",
                ]
            ),
            "--json",
        ).returncode
        == 0
    )
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://enemy.gd",
        "--json",
        code="missing_dependency",
    )
    assert "res://missing_projectile.tscn" in err["message"]
    assert "res://enemy.gd" in err["message"]
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_attach_incompatible_node_type_yields_incompatible_script_type(
    godot_project,
):
    # A script that COMPILES but whose native base is incompatible with the node
    # (an `extends Node3D` script onto a Node2D root) is bounced by set_script for
    # a reason that is NOT a compile error. attach must report the distinct
    # incompatible_script_type — not script_compile_failed — so the agent fixes
    # the node/script pairing rather than chasing a non-existent syntax error. The
    # scene is left untouched.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    # A perfectly valid script — it compiles — but extends Node3D, incompatible
    # with the Node2D root.
    assert (
        gda(
            "script", "create", "res://spatial.gd", "--extends", "Node3D", "--json"
        ).returncode
        == 0
    )
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://spatial.gd",
        "--json",
        code="incompatible_script_type",
    )
    assert "Node3D" in err["message"]
    assert "Node2D" in err["message"]
    # The refusal leaves the scene untouched.
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_attach_missing_script_yields_path_not_found(godot_project):
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://nope.gd",
        "--json",
        code="path_not_found",
    )
    assert "nope.gd" in err["message"]


@pytest.mark.e2e
def test_script_attach_wrong_script_extension_yields_invalid_path(godot_project):
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    (godot_project / "notes.txt").write_text("not a script\n", encoding="utf-8")

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://notes.txt",
        "--json",
        code="invalid_path",
    )
    assert ".gd" in err["message"]


@pytest.mark.e2e
def test_script_attach_missing_node_yields_node_not_found_and_leaves_scene(
    godot_project,
):
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://hero.gd", "--extends", "Node2D", "--json"
        ).returncode
        == 0
    )
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    err = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        "Bogus",
        "--script",
        "res://hero.gd",
        "--json",
        code="node_not_found",
    )
    assert "Bogus" in err["message"]
    # The refusal leaves the scene untouched.
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_attach_missing_scene_yields_path_not_found(godot_project):
    gda = Gda(godot_project)
    assert (
        gda(
            "script", "create", "res://hero.gd", "--extends", "Node2D", "--json"
        ).returncode
        == 0
    )

    err = gda.error(
        "script",
        "attach",
        "res://missing.tscn",
        "--node",
        ".",
        "--script",
        "res://hero.gd",
        "--json",
        code="path_not_found",
    )
    assert "missing.tscn" in err["message"]


@pytest.mark.e2e
def test_script_attach_no_prior_script_reports_null_replaced_script(godot_project):
    # attach is overwrite-and-report (issue #132): a node with no prior script is
    # bound and replaced_script is null — the signal that nothing was displaced.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://hero.gd", "--extends", "Node2D", "--json"
        ).returncode
        == 0
    )

    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://hero.gd",
        "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    assert json.loads(attached.stdout)["replaced_script"] is None


@pytest.mark.e2e
def test_script_attach_overwrites_and_reports_the_displaced_script(godot_project):
    # The issue #132 core: re-attaching to an ALREADY-scripted node overwrites the
    # binding (attach is a mutation verb — there is no `script detach`, so refusing
    # would strand the node) but no longer hides the displacement: replaced_script
    # names the prior script's res:// path verbatim. The overwrite is real — the
    # saved .tscn now references the NEW script and no longer the old one.
    gda = Gda(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://old.gd", "--extends", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "script",
            "create",
            "res://new.gd",
            "--content",
            "class_name NewHero\nextends Node2D\n",
            "--json",
        ).returncode
        == 0
    )
    # First attach binds old.gd — the node is now already-scripted.
    first = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://old.gd",
        "--json",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout)["replaced_script"] is None

    # Second attach OVERWRITES old.gd with new.gd and REPORTS the displaced old.gd.
    second = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://new.gd",
        "--json",
    )

    assert second.returncode == 0, second.stdout + second.stderr
    data = json.loads(second.stdout)
    assert data["script"] == "res://new.gd"
    assert data["class_name"] == "NewHero"
    # The displaced script is reported verbatim by its resource_path.
    assert data["replaced_script"] == "res://old.gd"
    # The overwrite is real: the saved scene references the new script, not the old.
    saved = (godot_project / "main.tscn").read_text(encoding="utf-8")
    assert "new.gd" in saved
    assert "old.gd" not in saved


@pytest.mark.e2e
def test_script_attach_both_scene_and_script_missing_reports_the_scene_first(
    godot_project,
):
    # The scene-before-script ordering acceptance (issue #132, Part 2): with BOTH
    # the scene and the --script absent, the SCENE problem is reported first — the
    # primary subject (the scene loads + node exists) is validated before the
    # secondary input (the --script arg), one invariant with no exceptions. Before
    # the reorder this surfaced the script's path_not_found and masked the scene.
    gda = Gda(godot_project)

    err = gda.error(
        "script",
        "attach",
        "res://missing.tscn",
        "--node",
        ".",
        "--script",
        "res://also_missing.gd",
        "--json",
        code="path_not_found",
    )
    # The reported failure names the SCENE, not the script.
    assert "missing.tscn" in err["message"]
    assert "also_missing.gd" not in err["message"]


@pytest.mark.e2e
def test_script_create_empty_content_round_trips_as_empty_source(godot_project):
    # An empty file is legal source: --content "" writes an empty script, and get
    # reads it back as empty (the get_file_as_string empty-vs-error disambiguation
    # treats a readable empty file as empty source, not a read failure), with null
    # metadata.
    script_path = godot_project / "empty.gd"

    created = gda("script", "create", str(script_path), "--content", "", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] is None
    assert create_data["extends"] is None
    assert script_path.read_text(encoding="utf-8") == ""

    got = gda("script", "get", str(script_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["source"] == ""
    assert got_data["class_name"] is None
    assert got_data["extends"] is None


# --- script attach: sibling-script drop on re-pack (issue #164) ---

# A deterministic harness for the issue #164 corruption, run against the real
# engine. It drives gda's OWN operations.gd payload through the SAME product entry
# points a mutating op uses — `_load_for_mutation` (which internally captures the
# external-script snapshot) and `_repack_and_save` (which internally re-anchors
# before pack/save). The harness only supplies the deterministic engine
# precondition and the mutation in between; capture and re-anchor are NOT called by
# the harness. That is deliberate: it makes the test guard the actual production
# WIRING, so deleting the `_capture_external_scripts(root)` call in
# `_load_for_mutation` OR the `_reanchor_external_scripts(root)` call in
# `_repack_and_save` makes this go red (verified red→green).
#
# Why a harness and not a plain `gda script attach` call: the corruption needs two
# distinct in-memory Script objects sharing one res:// path. The engine creates
# that state itself when GDScriptCache upgrades a shallow script to a full one via
# Resource.set_path(take_over=true) — which evicts the previously cached object
# WITHOUT freeing it, so a sibling node still references the evicted orphan. That
# shallow→full eviction is engine-internal and does not fire deterministically
# from a fresh one-shot `gda` process (each call reuses the resource cache from
# scratch), so a CLI-only test would be as intermittent as the original bug. The
# harness reproduces the EXACT engine mechanism (take_over_path, i.e.
# set_path(take_over=true)) deterministically, in an unimported-project fixture
# (no .godot import metadata, no .uid sidecar -> scripts carry no uid://), AFTER
# `_load_for_mutation` has already taken its snapshot — matching the real ordering
# where the eviction happens while the op runs. Then it calls `_repack_and_save`,
# the real product tail. Pre-fix the sibling's `script = ExtResource(...)` is
# dropped; post-fix the wired capture+reanchor preserves it.
_ATTACH_DROP_HARNESS = r"""
extends SceneTree

func _emit(ok: bool, detail: String) -> void:
	print("<<<HARNESS>>>", JSON.stringify({"ok": ok, "detail": detail}), "<<<END>>>")

func _init() -> void:
	# Sibling-scripted scene on disk: node A carries a.gd, node B is bare. The
	# scripts are unimported (fresh project, no import pass) -> no uid://.
	FileAccess.open("res://a.gd", FileAccess.WRITE).store_string("extends Sprite2D\n")
	FileAccess.open("res://b.gd", FileAccess.WRITE).store_string("extends Sprite2D\n")
	var build_root := Node2D.new()
	build_root.name = "main"
	var build_a := Sprite2D.new(); build_a.name = "A"; build_root.add_child(build_a); build_a.owner = build_root
	var build_b := Sprite2D.new(); build_b.name = "B"; build_root.add_child(build_b); build_b.owner = build_root
	build_a.set_script(ResourceLoader.load("res://a.gd"))
	var seed := PackedScene.new(); seed.pack(build_root); ResourceSaver.save(seed, "res://main.tscn")
	build_root.free()

	# Drive gda's REAL operations payload through its REAL mutate entry points.
	var ops_script: GDScript = load("res://operations.gd")
	var ops: Object = ops_script.new()
	var params := {"path": "res://main.tscn", "project": "res://"}

	# Load + instantiate via the product's single mutate-entry. _load_for_mutation
	# is what (post-fix) captures the external-script snapshot the instant after
	# instantiate — the harness does NOT call _capture_external_scripts, so if that
	# wiring is removed the snapshot is empty and the drop is left to occur.
	var live: Node = ops.call("_load_for_mutation", params)
	if live == null:
		_emit(false, "_load_for_mutation returned null")
		ops.free(); quit(); return

	# Reproduce the engine's shallow->full eviction deterministically, AFTER the
	# snapshot was taken (matching the real ordering where attach's own --script load
	# triggers it mid-op): a second in-memory object for res://a.gd that
	# take_over_path()s the cache slot, leaving node A holding the evicted orphan
	# whose resource_path is now empty. This is the #164 precondition verbatim.
	var orphan_maker := GDScript.new()
	orphan_maker.source_code = "extends Sprite2D\n"
	orphan_maker.take_over_path("res://a.gd")
	orphan_maker.reload()

	# Attach b.gd to the sibling node B (the second-node attach the bug needs).
	live.get_node("B").set_script(ResourceLoader.load("res://b.gd"))

	# Re-pack + save via the product's single pack-and-save tail. _repack_and_save
	# is what (post-fix) re-anchors from the snapshot before packing — the harness
	# does NOT call _reanchor_external_scripts, so if that wiring is removed the
	# evicted orphan is serialized and the sibling's ext_resource is dropped.
	var ok: bool = ops.call("_repack_and_save", live, "res://main.tscn")
	ops.free()
	if not ok:
		_emit(false, "_repack_and_save reported failure")
		quit(); return

	var saved := FileAccess.get_file_as_string("res://main.tscn")
	_emit(true, saved)
	quit()
"""

# A broader-surface coverage harness (review finding 2): the fix hooks into the
# SHARED `_repack_and_save`, so it hardens every mutating re-pack op, not just
# `script attach`. This drives a representative non-attach mutation — adding a child
# node via _build_added_node + _repack_and_save — over the same unimported
# two-node scene with the same take_over_path eviction on the scripted sibling, and
# asserts the sibling's `script = ExtResource(...)` binding survives the re-pack.
# It proves the central hardening point holds for the broader surface, not only the
# attach path. (See the matching code comment at the _reanchor_external_scripts
# call site in operations.gd.)
_NODE_ADD_PRESERVES_SIBLING_HARNESS = r"""
extends SceneTree

func _emit(ok: bool, detail: String) -> void:
	print("<<<HARNESS>>>", JSON.stringify({"ok": ok, "detail": detail}), "<<<END>>>")

func _init() -> void:
	# Same unimported sibling-scripted fixture: node A carries a.gd, node B is bare.
	FileAccess.open("res://a.gd", FileAccess.WRITE).store_string("extends Sprite2D\n")
	var build_root := Node2D.new()
	build_root.name = "main"
	var build_a := Sprite2D.new(); build_a.name = "A"; build_root.add_child(build_a); build_a.owner = build_root
	var build_b := Sprite2D.new(); build_b.name = "B"; build_root.add_child(build_b); build_b.owner = build_root
	build_a.set_script(ResourceLoader.load("res://a.gd"))
	var seed := PackedScene.new(); seed.pack(build_root); ResourceSaver.save(seed, "res://main.tscn")
	build_root.free()

	var ops_script: GDScript = load("res://operations.gd")
	var ops: Object = ops_script.new()
	var params := {"path": "res://main.tscn", "project": "res://"}

	# Same shared mutate entry — captures the snapshot.
	var live: Node = ops.call("_load_for_mutation", params)
	if live == null:
		_emit(false, "_load_for_mutation returned null")
		ops.free(); quit(); return

	# Same deterministic eviction of the scripted sibling A's cache slot.
	var orphan_maker := GDScript.new()
	orphan_maker.source_code = "extends Sprite2D\n"
	orphan_maker.take_over_path("res://a.gd")
	orphan_maker.reload()

	# A NON-attach mutation: add a fresh child node (no script). This is the
	# `node add` shared tail — it touches the same _repack_and_save as attach.
	var added := Node2D.new()
	added.name = "C"
	live.add_child(added)
	added.owner = live

	# Same shared pack-and-save tail — re-anchors the sibling before packing.
	var ok: bool = ops.call("_repack_and_save", live, "res://main.tscn")
	ops.free()
	if not ok:
		_emit(false, "_repack_and_save reported failure")
		quit(); return

	var saved := FileAccess.get_file_as_string("res://main.tscn")
	_emit(true, saved)
	quit()
"""


def _run_harness(project, harness: str = _ATTACH_DROP_HARNESS) -> str:
    """Run a #164 harness in `project` against the real engine; return saved .tscn."""
    # The harness drives gda's own operations.gd, so ship a copy into the fixture.
    shutil.copy(OPERATIONS_GD, project / "operations.gd")
    (project / "attach_drop_harness.gd").write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--path",
            str(project),
            "--script",
            "res://attach_drop_harness.gd",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    marker_begin, marker_end = "<<<HARNESS>>>", "<<<END>>>"
    out = proc.stdout
    assert marker_begin in out and marker_end in out, (
        "harness did not emit a result:\n" + proc.stdout + proc.stderr
    )
    payload = out.split(marker_begin, 1)[1].split(marker_end, 1)[0].strip()
    result = json.loads(payload)
    assert result["ok"], "harness failed: " + result["detail"] + proc.stderr
    return result["detail"]


@pytest.mark.e2e
def test_script_attach_preserves_sibling_script_on_repack_when_unimported(
    godot_project,
):
    # Issue #164 regression: attaching a script to one node must never drop a
    # SIBLING node's existing `script =` binding on the re-pack/save — including in
    # a freshly-created project whose scripts have not been imported (no uid://).
    #
    # Root cause: the editor build's text scene saver dedups ext_resources through
    # a PATH-keyed cache, not object identity. When two distinct in-memory Script
    # objects share one res:// path (the engine's shallow→full GDScriptCache
    # upgrade evicts-but-does-not-free the cached object a sibling still holds) and
    # the script is unimported (path is the only identity), the dedup collapses
    # them and the sibling's ext_resource is dropped / re-embedded as a sub_resource.
    #
    # This drives gda's real operations.gd entry points — `_load_for_mutation`
    # (captures the snapshot) then `_repack_and_save` (re-anchors before pack) — and
    # reproduces the engine precondition deterministically in between (see
    # _ATTACH_DROP_HARNESS). The harness does NOT call _capture_external_scripts or
    # _reanchor_external_scripts itself, so this guards the production WIRING: it
    # fails pre-fix and fails if EITHER wiring call is later removed.
    saved = _run_harness(godot_project)

    # Node A's sibling script survives as a clean external reference — not dropped,
    # not silently re-embedded as an inline sub_resource.
    assert 'path="res://a.gd"' in saved, (
        "sibling node A's a.gd ext_resource was DROPPED on re-pack:\n" + saved
    )
    assert 'sub_resource type="GDScript"' not in saved, (
        "sibling node A's script was silently re-embedded as a sub_resource:\n" + saved
    )
    # Both nodes keep their script bindings, each referencing its own external script.
    assert 'path="res://b.gd"' in saved, (
        "the attached b.gd reference is missing:\n" + saved
    )
    assert saved.count("script = ExtResource(") == 2, (
        "expected exactly two external script bindings to survive:\n" + saved
    )


@pytest.mark.e2e
def test_node_add_preserves_sibling_script_on_repack_when_unimported(godot_project):
    # Broader-surface coverage (issue #164, review finding 2): the fix re-anchors
    # from the SHARED `_repack_and_save` tail, so it hardens every mutating re-pack
    # op — not only `script attach`. A representative NON-attach mutation (`node
    # add`) over the same unimported two-node scene, with the same take_over_path
    # eviction on the scripted sibling A, must likewise preserve A's external script
    # binding through the shared re-pack. This proves the central hardening point
    # holds for the broader mutation surface, not just the path #164 reported.
    saved = _run_harness(godot_project, _NODE_ADD_PRESERVES_SIBLING_HARNESS)

    # The scripted sibling A survives the re-pack as a clean external reference.
    assert 'path="res://a.gd"' in saved, (
        "sibling node A's a.gd ext_resource was DROPPED on node-add re-pack:\n" + saved
    )
    assert 'sub_resource type="GDScript"' not in saved, (
        "sibling node A's script was silently re-embedded as a sub_resource:\n" + saved
    )
    assert saved.count("script = ExtResource(") == 1, (
        "expected sibling A's single external script binding to survive:\n" + saved
    )
