"""S1 (e2e): the script create → get round-trip against the real Godot engine.

The script-group tracer (issue #110): ``gda script create`` writes a .gd
script (from a template or verbatim --content), no-clobber; ``gda script get``
reads its source back with class_name/extends metadata — ``script get`` IS the
structured-level verification of ``script create``'s effect (create → get
returns the source).
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()


def _gda(*args: str) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


def _gda_project(project) -> "callable":
    """A ``_gda`` bound to ``--project`` for res:// enumeration/resolution."""
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [gda_bin, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


@pytest.mark.e2e
def test_script_create_default_template_then_get_round_trip(godot_project):
    # The bare template: create writes `extends Node`, get reads it back. The
    # source on disk IS what get reports — the round-trip proves the write.
    script_path = godot_project / "actor.gd"

    created = _gda("script", "create", str(script_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(script_path)
    assert data["extends"] == "Node"
    assert data["class_name"] is None
    assert script_path.exists()

    got = _gda("script", "get", str(script_path), "--json")

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

    created = _gda("script", "create", str(script_path), "--extends", "Node2D", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["extends"] == "Node2D"

    got = _gda("script", "get", str(script_path), "--json")
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

    created = _gda(
        "script", "create", str(script_path), "--content", source, "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] == "Hero"
    assert create_data["extends"] == "Node2D"

    got = _gda("script", "get", str(script_path), "--json")

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
    def gda(*args: str) -> subprocess.CompletedProcess:
        return _gda(*args, "--project", str(godot_project))

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

    created = _gda("script", "create", str(script_path), "--json")

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
    _gda("script", "create", str(script_path), "--extends", "Node2D", "--json")
    before = script_path.read_text(encoding="utf-8")

    again = _gda("script", "create", str(script_path), "--extends", "Sprite2D", "--json")

    err = _assert_operation_error(again, "already_exists")
    assert str(script_path) in err["message"]
    assert script_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_create_wrong_extension_yields_invalid_path(godot_project):
    # A target that is not a .gd script is an invalid path param; nothing is
    # written.
    target = godot_project / "notes.txt"

    created = _gda("script", "create", str(target), "--json")

    err = _assert_operation_error(created, "invalid_path")
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

    created = _gda("script", "create", str(target), "--json")

    err = _assert_operation_error(created, "invalid_path")
    assert ".gd" in err["message"]
    assert str(target) in err["message"]
    assert not target.exists()


@pytest.mark.e2e
def test_script_get_missing_file_yields_path_not_found(godot_project):
    missing = godot_project / "nope.gd"

    got = _gda("script", "get", str(missing), "--json")

    err = _assert_operation_error(got, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_script_get_wrong_extension_yields_invalid_path(godot_project):
    notes = godot_project / "notes.txt"
    notes.write_text("not a script\n", encoding="utf-8")

    got = _gda("script", "get", str(notes), "--json")

    err = _assert_operation_error(got, "invalid_path")
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

    created = _gda("script", "create", str(script_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["path"] == str(script_path)

    got = _gda("script", "get", str(script_path), "--json")
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

    created = _gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] == "Widget"
    assert create_data["extends"] == "Control"

    got = _gda("script", "get", str(script_path), "--json")
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
        "extends Node\n"
        "\n"
        'var doc := """\n'
        "class_name Injected\n"
        "extends Injected\n"
        '"""\n'
    )

    created = _gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["extends"] == "Node"
    assert create_data["class_name"] is None

    got = _gda("script", "get", str(script_path), "--json")
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

    created = _gda("script", "create", str(script_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["extends"] == '"res://weapons/a#b.gd"'

    got = _gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["extends"] == '"res://weapons/a#b.gd"'


@pytest.mark.e2e
def test_script_list_enumerates_created_scripts(godot_project):
    # script list (issue #117) enumerates the project's .gd scripts by walking
    # res://: two scripts created at different depths both appear, each with its
    # res:// path and the class_name/extends parsed from raw source. The listing
    # IS the structured-level verification of what script create wrote.
    gda = _gda_project(godot_project)

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
    gda = _gda_project(godot_project)

    listed = gda("script", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)["scripts"] == []


@pytest.mark.e2e
def test_script_list_without_project_yields_project_not_found(tmp_path):
    # script list cannot enumerate res:// projectless: run from a non-project
    # directory with no --project, it must refuse with the structured
    # project_not_found code rather than return a misleading empty listing.
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    listed = subprocess.run(
        [gda_bin, "script", "list", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    err = _assert_operation_error(listed, "project_not_found")
    assert "--project" in err["message"]


@pytest.mark.e2e
def test_script_delete_removes_a_script_and_names_what_was_removed(godot_project):
    # script delete (issue #117) removes a script file and names the removed
    # script's metadata. The round-trip verifier: script list before shows the
    # script, delete reports the removed class_name/extends, and script list
    # after no longer shows it.
    gda = _gda_project(godot_project)
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

    deleted = _gda("script", "delete", str(missing), "--json")

    err = _assert_operation_error(deleted, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_script_delete_wrong_extension_yields_invalid_path_and_leaves_it(godot_project):
    # The delete safety boundary mirrors create/get: delete only removes a .gd
    # script, so a non-.gd target is refused with invalid_path and left on disk —
    # delete never erases arbitrary files.
    notes = godot_project / "notes.txt"
    notes.write_text("not a script\n", encoding="utf-8")

    deleted = _gda("script", "delete", str(notes), "--json")

    err = _assert_operation_error(deleted, "invalid_path")
    assert ".gd" in err["message"]
    assert str(notes) in err["message"]
    # The non-script file survives the refusal.
    assert notes.read_text(encoding="utf-8") == "not a script\n"


@pytest.mark.e2e
def test_script_set_search_replace_edits_in_place_and_round_trips_via_get(godot_project):
    # search-replace mode (issue #118): every literal occurrence of --search is
    # replaced with --replace; script get round-trips the edited source on disk.
    script_path = godot_project / "hero.gd"
    _gda(
        "script", "create", str(script_path),
        "--content", "extends Node\nvar a := Node\n", "--json",
    )

    edited = _gda(
        "script", "set", str(script_path),
        "--search", "Node", "--replace", "Node2D", "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    assert json.loads(edited.stdout)["extends"] == "Node2D"
    got = _gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    # Both occurrences replaced; the edited source IS what get reports.
    assert json.loads(got.stdout)["source"] == "extends Node2D\nvar a := Node2D\n"
    assert script_path.read_text(encoding="utf-8") == "extends Node2D\nvar a := Node2D\n"


@pytest.mark.e2e
def test_script_set_line_range_replaces_the_span_and_round_trips_via_get(godot_project):
    # line-range mode: replace lines 2..3 (1-based, inclusive) with new content;
    # the rest of the file is untouched. Lines are the parts split on "\n".
    script_path = godot_project / "actor.gd"
    _gda(
        "script", "create", str(script_path),
        "--content", "extends Node\nvar a := 1\nvar b := 2\nfunc f(): pass\n", "--json",
    )

    edited = _gda(
        "script", "set", str(script_path),
        "--start-line", "2", "--end-line", "3", "--content", "var x := 9", "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    got = _gda("script", "get", str(script_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["source"] == (
        "extends Node\nvar x := 9\nfunc f(): pass\n"
    )


@pytest.mark.e2e
def test_script_set_line_range_defaults_end_to_start_for_a_single_line(godot_project):
    # --end-line defaults to --start-line: a single-line replace.
    script_path = godot_project / "single.gd"
    _gda(
        "script", "create", str(script_path),
        "--content", "extends Node\nvar a := 1\nvar b := 2\n", "--json",
    )

    edited = _gda(
        "script", "set", str(script_path),
        "--start-line", "2", "--content", "var a := 99", "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    got = _gda("script", "get", str(script_path), "--json")
    assert json.loads(got.stdout)["source"] == "extends Node\nvar a := 99\nvar b := 2\n"


@pytest.mark.e2e
def test_script_set_full_overwrites_the_whole_file_and_round_trips_via_get(godot_project):
    # full mode: --content with no --start-line overwrites the entire file.
    script_path = godot_project / "full.gd"
    _gda("script", "create", str(script_path), "--content", "extends Node\n", "--json")

    new_source = "class_name Hero\nextends Node2D\n\nvar speed := 100\n"
    edited = _gda("script", "set", str(script_path), "--content", new_source, "--json")

    assert edited.returncode == 0, edited.stdout + edited.stderr
    data = json.loads(edited.stdout)
    assert data["class_name"] == "Hero"
    assert data["extends"] == "Node2D"
    got = _gda("script", "get", str(script_path), "--json")
    assert json.loads(got.stdout)["source"] == new_source


@pytest.mark.e2e
def test_script_set_no_search_match_is_refused_and_leaves_file_untouched(godot_project):
    # A search string the source does not contain is refused with no_search_match
    # and the file is left exactly as it was — the edit landed nowhere.
    script_path = godot_project / "hero.gd"
    _gda("script", "create", str(script_path), "--content", "extends Node\n", "--json")
    before = script_path.read_text(encoding="utf-8")

    edited = _gda(
        "script", "set", str(script_path),
        "--search", "Sprite2D", "--replace", "Node2D", "--json",
    )

    _assert_operation_error(edited, "no_search_match")
    assert script_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_set_out_of_bounds_line_range_is_refused_and_leaves_file_untouched(
    godot_project,
):
    # A line range past the file's bounds is refused with invalid_line_range and
    # the file is left untouched.
    script_path = godot_project / "hero.gd"
    _gda(
        "script", "create", str(script_path),
        "--content", "extends Node\nvar a := 1\n", "--json",
    )
    before = script_path.read_text(encoding="utf-8")

    edited = _gda(
        "script", "set", str(script_path),
        "--start-line", "9", "--content", "var x := 0", "--json",
    )

    _assert_operation_error(edited, "invalid_line_range")
    assert script_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_set_missing_file_yields_path_not_found(godot_project):
    # set edits an existing script; a missing target is path_not_found, never a
    # silent create.
    missing = godot_project / "nope.gd"

    edited = _gda(
        "script", "set", str(missing), "--content", "extends Node\n", "--json"
    )

    err = _assert_operation_error(edited, "path_not_found")
    assert str(missing) in err["message"]
    assert not missing.exists()


# --- script validate (issue #118) ---


@pytest.mark.e2e
def test_script_validate_valid_script_reports_valid_true_no_diagnostics(godot_project):
    # The mechanism gate (issue #118): a self-contained `extends Node` script
    # compiles (GDScript.reload() == OK) projectless, so validate reports valid=
    # true, no error_string, no diagnostics — exit 0.
    script_path = godot_project / "ok.gd"
    _gda(
        "script", "create", str(script_path),
        "--content", "extends Node\n\nfunc greet() -> String:\n\treturn \"hi\"\n",
        "--json",
    )

    validated = _gda("script", "validate", str(script_path), "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True
    assert data["error_string"] is None
    assert data["diagnostics"] == []


@pytest.mark.e2e
def test_script_validate_broken_script_is_success_with_a_real_diagnostic(godot_project):
    # The mechanism gate's hard half: a deliberately BROKEN script is a SUCCESSFUL
    # op (exit 0) reporting valid=false, and at least one diagnostic with a real
    # `line` and non-empty `message` — proving the stderr-parsing regex against
    # the REAL engine output, not a fixture.
    script_path = godot_project / "broken.gd"
    # `var x =` with no initializer is a parse error the engine reports on its line.
    _gda(
        "script", "create", str(script_path),
        "--content", "extends Node\n\nvar x =\n", "--json",
    )

    validated = _gda("script", "validate", str(script_path), "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["error_string"] is not None
    assert len(data["diagnostics"]) >= 1
    diag = data["diagnostics"][0]
    assert isinstance(diag["line"], int)
    assert diag["line"] >= 1
    assert diag["message"]
    # Column is unavailable on the standard build.
    assert diag["column"] is None


@pytest.mark.e2e
def test_script_validate_missing_file_yields_path_not_found(godot_project):
    # validate only op-fails for op errors: a missing file is path_not_found, NOT
    # a valid=false success.
    missing = godot_project / "nope.gd"

    validated = _gda("script", "validate", str(missing), "--json")

    err = _assert_operation_error(validated, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_script_validate_wrong_extension_yields_invalid_path(godot_project):
    notes = godot_project / "notes.txt"
    notes.write_text("not a script\n", encoding="utf-8")

    validated = _gda("script", "validate", str(notes), "--json")

    err = _assert_operation_error(validated, "invalid_path")
    assert ".gd" in err["message"]


# --- script attach (issue #118) ---


@pytest.mark.e2e
def test_script_attach_binds_script_to_node_and_scene_references_it(godot_project):
    # script attach (issue #118) loads a scene, resolves a node by node path,
    # attaches a .gd, and saves. Verify by reading the saved .tscn back: the
    # script path now appears as an ext_resource the node references, the result
    # echoes the script's class_name, and the scene still re-loads (node list).
    gda = _gda_project(godot_project)
    assert (
        gda("scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json")
        .returncode
        == 0
    )
    assert (
        gda(
            "script", "create", "res://hero.gd",
            "--content", "class_name Hero\nextends Node2D\n", "--json",
        ).returncode
        == 0
    )

    attached = gda(
        "script", "attach", "res://main.tscn",
        "--node", ".", "--script", "res://hero.gd", "--json",
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
    gda = _gda_project(godot_project)
    assert (
        gda("scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json")
        .returncode
        == 0
    )
    assert (
        gda("node", "add", "res://main.tscn", "--type", "Sprite2D", "--name", "Hero",
            "--json").returncode
        == 0
    )
    assert (
        gda("script", "create", "res://hero.gd", "--extends", "Sprite2D", "--json")
        .returncode
        == 0
    )

    attached = gda(
        "script", "attach", "res://main.tscn",
        "--node", "Hero", "--script", "res://hero.gd", "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    assert json.loads(attached.stdout)["node"] == "Hero"
    saved = (godot_project / "main.tscn").read_text(encoding="utf-8")
    assert "hero.gd" in saved


@pytest.mark.e2e
def test_script_attach_no_class_name_echoes_null_class_name(godot_project):
    # A script with no class_name attaches fine and the result carries null.
    gda = _gda_project(godot_project)
    assert (
        gda("scene", "create", "res://main.tscn", "--root-type", "Node", "--json")
        .returncode
        == 0
    )
    assert (
        gda("script", "create", "res://plain.gd", "--extends", "Node", "--json")
        .returncode
        == 0
    )

    attached = gda(
        "script", "attach", "res://main.tscn",
        "--node", ".", "--script", "res://plain.gd", "--json",
    )

    assert attached.returncode == 0, attached.stdout + attached.stderr
    assert json.loads(attached.stdout)["class_name"] is None


@pytest.mark.e2e
def test_script_attach_missing_script_yields_path_not_found(godot_project):
    gda = _gda_project(godot_project)
    assert (
        gda("scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json")
        .returncode
        == 0
    )

    attached = gda(
        "script", "attach", "res://main.tscn",
        "--node", ".", "--script", "res://nope.gd", "--json",
    )

    err = _assert_operation_error(attached, "path_not_found")
    assert "nope.gd" in err["message"]


@pytest.mark.e2e
def test_script_attach_wrong_script_extension_yields_invalid_path(godot_project):
    gda = _gda_project(godot_project)
    assert (
        gda("scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json")
        .returncode
        == 0
    )
    (godot_project / "notes.txt").write_text("not a script\n", encoding="utf-8")

    attached = gda(
        "script", "attach", "res://main.tscn",
        "--node", ".", "--script", "res://notes.txt", "--json",
    )

    err = _assert_operation_error(attached, "invalid_path")
    assert ".gd" in err["message"]


@pytest.mark.e2e
def test_script_attach_missing_node_yields_node_not_found_and_leaves_scene(godot_project):
    gda = _gda_project(godot_project)
    assert (
        gda("scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json")
        .returncode
        == 0
    )
    assert (
        gda("script", "create", "res://hero.gd", "--extends", "Node2D", "--json")
        .returncode
        == 0
    )
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    attached = gda(
        "script", "attach", "res://main.tscn",
        "--node", "Bogus", "--script", "res://hero.gd", "--json",
    )

    err = _assert_operation_error(attached, "node_not_found")
    assert "Bogus" in err["message"]
    # The refusal leaves the scene untouched.
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_script_attach_missing_scene_yields_path_not_found(godot_project):
    gda = _gda_project(godot_project)
    assert (
        gda("script", "create", "res://hero.gd", "--extends", "Node2D", "--json")
        .returncode
        == 0
    )

    attached = gda(
        "script", "attach", "res://missing.tscn",
        "--node", ".", "--script", "res://hero.gd", "--json",
    )

    err = _assert_operation_error(attached, "path_not_found")
    assert "missing.tscn" in err["message"]


@pytest.mark.e2e
def test_script_create_empty_content_round_trips_as_empty_source(godot_project):
    # An empty file is legal source: --content "" writes an empty script, and get
    # reads it back as empty (the get_file_as_string empty-vs-error disambiguation
    # treats a readable empty file as empty source, not a read failure), with null
    # metadata.
    script_path = godot_project / "empty.gd"

    created = _gda("script", "create", str(script_path), "--content", "", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] is None
    assert create_data["extends"] is None
    assert script_path.read_text(encoding="utf-8") == ""

    got = _gda("script", "get", str(script_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["source"] == ""
    assert got_data["class_name"] is None
    assert got_data["extends"] is None
