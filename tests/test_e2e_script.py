"""S1 (e2e): the script create → get round-trip against the real Godot engine.

The script-group tracer (issue #110): ``gda script create`` writes a .gd/.cs
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
    # A target that is not a .gd/.cs script is an invalid path param; nothing is
    # written.
    target = godot_project / "notes.txt"

    created = _gda("script", "create", str(target), "--json")

    err = _assert_operation_error(created, "invalid_path")
    assert ".gd or .cs" in err["message"]
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
    assert ".gd or .cs" in err["message"]


@pytest.mark.e2e
def test_script_create_cs_round_trips_source_with_null_metadata(godot_project):
    # .cs handling (issue #110): a C# script created via --content round-trips
    # its source verbatim, but class_name/extends are null — C# class/base
    # semantics differ from GDScript's leading declarations, so this tracer
    # reports nulls for .cs rather than mis-parsing it as GDScript.
    script_path = godot_project / "Player.cs"
    source = (
        "using Godot;\n\npublic partial class Player : Node2D\n{\n}\n"
    )

    created = _gda(
        "script", "create", str(script_path), "--content", source, "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    create_data = json.loads(created.stdout)
    assert create_data["class_name"] is None
    assert create_data["extends"] is None

    got = _gda("script", "get", str(script_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["source"] == source
    assert got_data["class_name"] is None
    assert got_data["extends"] is None


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
