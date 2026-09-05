"""S1 (e2e): the resource create → get round-trip and resource uid resolution against the real Godot engine.

The resource-group tracer (issue #112): ``gda resource create`` writes a .tres
resource of a given type, no-clobber; ``gda resource get`` loads it and reports
its properties as typed JSON — ``resource get`` IS the structured-level
verification of ``resource create``'s effect (create → get reports the
resource). Establishes the .tres load/save plumbing the rest of the group
reuses.

The resource-uid tracer (issue #113): ``gda resource uid`` resolves a Godot
resource UID to/from its resource path in BOTH directions against the engine's
read-only UID cache (``res://.godot/uid_cache.bin``).

The cache is populated by a project import scan, so each uid test scaffolds the
relevant files and runs a one-shot ``godot --headless --import`` to write the
cache before querying it — that import is the realistic precondition for any UID
to resolve at all. A ``.gd`` script is auto-assigned a UID on import (a ``.uid``
sidecar plus a cache entry), which is what makes both resolution directions
resolve; a ``.tres`` resource imported without a sidecar exists but carries no
cached UID, which is the realistic ``no_uid_assigned`` case. Both directions,
plus the unknown-UID / invalid-UID / path-not-found / no-UID-assigned failure
modes, are exercised end to end.
"""

import json

import pytest

from tests.support import Gda, import_project

gda = Gda()

# A plain custom Resource .tres. On import (without a .uid sidecar) it exists as
# a resource but is NOT assigned a UID in the non-editor reverse cache, so it is
# the realistic no_uid_assigned case.
DATA_TRES = """\
[gd_resource type="Resource" format=3]

[resource]
"""


@pytest.fixture
def imported_project(godot_project):
    """A project fixture with a script (UID-cached) and a .tres (no cached UID)."""
    (godot_project / "hero.gd").write_text("extends Node\n", encoding="utf-8")
    (godot_project / "data.tres").write_text(DATA_TRES, encoding="utf-8")
    import_project(godot_project)
    return godot_project


@pytest.mark.e2e
def test_resource_create_then_get_round_trip(godot_project):
    # create writes a .tres of the requested type; get loads it back and reports
    # its type + properties. The round-trip proves the save: get reports the
    # resource create wrote.
    resource_path = godot_project / "palette.tres"

    created = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(resource_path)
    assert data["type"] == "Gradient"
    assert resource_path.exists()
    # The written file is a real Godot .tres declaring the resource type.
    assert 'type="Gradient"' in resource_path.read_text(encoding="utf-8")

    got = gda("resource", "get", str(resource_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    # Round-trip: get reports the same type create wrote, plus typed properties.
    assert got_data["path"] == str(resource_path)
    assert got_data["type"] == "Gradient"
    by_name = {p["name"]: p for p in got_data["properties"]}
    # A Gradient declares these storage properties, each with its declared Godot
    # type — the same typed projection node get reports.
    assert by_name["interpolation_mode"]["type"] == "int"
    assert by_name["resource_name"]["type"] == "String"


@pytest.mark.e2e
def test_resource_get_projects_packed_arrays_as_json_lists(godot_project):
    # ADR-0035: a Gradient's packed-array properties arrive structured — offsets
    # (PackedFloat32Array) as a JSON number list, colors (PackedColorArray) as a
    # list of [r, g, b, a] lists (each Color element re-enters the projection) —
    # not the Variant str() dump.
    resource_path = godot_project / "palette.tres"
    created = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    got = gda("resource", "get", str(resource_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    assert by_name["offsets"]["type"] == "PackedFloat32Array"
    assert by_name["offsets"]["value"] == [0.0, 1.0]
    assert by_name["colors"]["type"] == "PackedColorArray"
    # A default Gradient runs black -> white; each element is a 4-float list.
    assert by_name["colors"]["value"] == [
        [0.0, 0.0, 0.0, 1.0],
        [1.0, 1.0, 1.0, 1.0],
    ]


@pytest.mark.e2e
def test_resource_create_into_nested_dir_reports_created_dirs(godot_project):
    # create makes missing parent directories before saving and reports them,
    # outermost to innermost (mirrors scene/script create).
    resource_path = godot_project / "art" / "palettes" / "sunset.tres"

    created = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert resource_path.exists()
    assert data["created_dirs"] == [
        str(godot_project / "art"),
        str(godot_project / "art" / "palettes"),
    ]


@pytest.mark.e2e
def test_resource_create_no_clobber_yields_already_exists(godot_project):
    # No-clobber: a create whose target already exists is refused with
    # already_exists, leaving the existing file untouched.
    resource_path = godot_project / "palette.tres"
    first = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = resource_path.read_text(encoding="utf-8")

    err = gda.error(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "Curve",
        "--json",
        code="already_exists",
    )
    assert str(resource_path) in err["message"]
    # The original file is untouched — the clobber never happened.
    assert resource_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_resource_create_unknown_type_yields_invalid_resource_type(godot_project):
    resource_path = godot_project / "palette.tres"

    err = gda.error(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "Bogus",
        "--json",
        code="invalid_resource_type",
    )
    assert "Bogus" in err["message"]
    # Nothing was written for the rejected type.
    assert not resource_path.exists()


@pytest.mark.e2e
def test_resource_create_non_resource_type_yields_invalid_resource_type(godot_project):
    # A real Godot class that is NOT a Resource (a Node) cannot be saved as a
    # .tres, so it is refused with the same code as an unknown type.
    resource_path = godot_project / "thing.tres"

    err = gda.error(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "Node2D",
        "--json",
        code="invalid_resource_type",
    )
    assert "Node2D" in err["message"]
    assert not resource_path.exists()


# --- resource create by class_name (issue #342): resolve a project-defined
# GDScript `class_name Foo extends Resource` the same way node add resolves a
# class_name --type, so a custom Resource type creates and saves as a .tres. ---


# A project-defined custom Resource with typed exported fields at explicit,
# non-default values — the round-trip payload the positive test asserts.
PANDA_STATS_GD = """\
class_name PandaStats
extends Resource

@export var tint: Color = Color(0.25, 0.5, 0.75, 1.0)
@export var offset: Vector2 = Vector2(3, 4)
@export var speed: float = 2.5
"""


DROP_TABLE_STATS_GD = """\
class_name DropTableStats
extends Resource

@export var drop_items: Dictionary = {"seed": 1}
"""


@pytest.mark.e2e
def test_resource_create_by_class_name_round_trips_typed_fields(godot_project):
    # The class_name half of --type's contract for resources (issue #342): a
    # class_name registered in the project's global class list resolves like a
    # built-in Resource type. create instantiates the script-backed Resource and
    # saves it as a .tres (recording the script as an ExtResource); get loads it
    # back and reports the exported fields with their declared Godot types and
    # values — create → get IS the round-trip proof for a custom Resource type.
    (godot_project / "panda_stats.gd").write_text(PANDA_STATS_GD, encoding="utf-8")
    import_project(godot_project)
    resource_path = godot_project / "panda.tres"

    created = gda(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "PandaStats",
        "--project",
        str(godot_project),
        "--json",
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(resource_path)
    # create echoes the requested type (the class_name), and the written .tres is
    # a real Godot resource carrying the script class.
    assert data["type"] == "PandaStats"
    assert resource_path.exists()
    assert 'script_class="PandaStats"' in resource_path.read_text(encoding="utf-8")

    got = gda(
        "resource",
        "get",
        str(resource_path),
        "--project",
        str(godot_project),
        "--json",
    )

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    # get reports the engine base class as type (a script-backed Resource's
    # get_class() is "Resource"); the exported fields carry the declared types.
    assert got_data["type"] == "Resource"
    by_name = {p["name"]: p for p in got_data["properties"]}
    assert by_name["tint"]["type"] == "Color"
    assert by_name["tint"]["value"] == [0.25, 0.5, 0.75, 1.0]
    assert by_name["offset"]["type"] == "Vector2"
    assert by_name["offset"]["value"] == [3.0, 4.0]
    assert by_name["speed"]["type"] == "float"
    assert by_name["speed"]["value"] == 2.5


@pytest.mark.e2e
def test_resource_create_by_class_name_round_trips_a_set_via_get(godot_project):
    # #342's full CRUD contract: a script-backed custom .tres round-trips through
    # resource set/get, not only create/get. set coerces the CLI string to a
    # custom exported field's declared type, saves the .tres, and get reports the
    # persisted value — resource get IS the structured-level proof that set landed
    # on a custom Resource type.
    (godot_project / "panda_stats.gd").write_text(PANDA_STATS_GD, encoding="utf-8")
    import_project(godot_project)
    resource_path = godot_project / "panda.tres"
    created = gda(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "PandaStats",
        "--project",
        str(godot_project),
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    was_set = gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "speed",
        "--value",
        "9.5",
        "--project",
        str(godot_project),
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_data = json.loads(was_set.stdout)
    # set reports the coerced value against the script-declared type.
    assert set_data["property"] == "speed"
    assert set_data["type"] == "float"
    assert set_data["value"] == 9.5

    got = gda(
        "resource",
        "get",
        str(resource_path),
        "--project",
        str(godot_project),
        "--json",
    )

    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    # Round-trip: get reports the value set persisted to the custom .tres.
    assert by_name["speed"]["type"] == "float"
    assert by_name["speed"]["value"] == 9.5


@pytest.mark.e2e
def test_resource_set_preserves_json_container_integer_and_float_types(
    godot_project,
):
    # #427: resource set writes through ResourceSaver, so verify both the
    # structured readback and the .tres text preserve JSON integer spelling.
    (godot_project / "drop_table_stats.gd").write_text(
        DROP_TABLE_STATS_GD, encoding="utf-8"
    )
    import_project(godot_project)
    resource_path = godot_project / "drop_table.tres"
    created = gda(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "DropTableStats",
        "--project",
        str(godot_project),
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    was_set = gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "drop_items",
        "--value",
        '{"a":2,"b":2.0,"items":[1,1.5]}',
        "--project",
        str(godot_project),
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_value = json.loads(was_set.stdout)["value"]
    assert type(set_value["a"]) is int
    assert type(set_value["b"]) is float
    assert type(set_value["items"][0]) is int
    assert type(set_value["items"][1]) is float

    text = resource_path.read_text(encoding="utf-8")
    assert '"a": 2,' in text
    assert '"a": 2.0' not in text
    assert '"b": 2.0' in text

    got = gda(
        "resource",
        "get",
        str(resource_path),
        "--project",
        str(godot_project),
        "--json",
    )
    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    got_value = by_name["drop_items"]["value"]
    assert type(got_value["a"]) is int
    assert type(got_value["b"]) is float
    assert type(got_value["items"][0]) is int
    assert type(got_value["items"][1]) is float


# A registered class_name whose script is healthy but NOT Resource-derived: a
# true type error (instantiable, but never savable as a .tres).
WIDGET_NODE_GD = """\
class_name WidgetNode
extends Node2D
"""


@pytest.mark.e2e
def test_resource_create_by_non_resource_class_name_yields_invalid_resource_type(
    godot_project,
):
    # The boundary of issue #342's distinction: a registered class_name whose
    # script is fine but not Resource-derived is a true type error — it stays
    # invalid_resource_type (not uninstantiable_script), with a message naming
    # the script and the real cause rather than "not a registered class_name".
    (godot_project / "widget_node.gd").write_text(WIDGET_NODE_GD, encoding="utf-8")
    import_project(godot_project)
    resource_path = godot_project / "widget.tres"

    err = gda.error(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "WidgetNode",
        "--project",
        str(godot_project),
        "--json",
        code="invalid_resource_type",
    )
    assert "WidgetNode" in err["message"]
    assert "not a Resource-derived script" in err["message"]
    assert "widget_node.gd" in err["message"]
    # Nothing was written for the rejected type.
    assert not resource_path.exists()


# The same class_name, valid at import then broken on disk: a parse error the
# import-time scan never saw, so the stale global class list still maps it.
STATS_GD = """\
class_name Stats
extends Resource
"""

BROKEN_STATS_GD = """\
class_name Stats
extends Resource
func broken( -> void:
"""


@pytest.mark.e2e
def test_resource_create_by_registered_but_broken_class_name_names_the_script(
    godot_project,
):
    # Issue #342's broken-class_name mode (mirrors node add's #65 split): the
    # class_name IS in the global class list (the import scanned a then-valid
    # script), but the script on disk has since broken. Reporting
    # invalid_resource_type ("not a registered class_name") would misdiagnose a
    # script problem as an unknown type — the agent fix is to repair the script,
    # not the type name. The failure must surface as the distinct
    # uninstantiable_script code naming the script, with nothing written.
    (godot_project / "stats.gd").write_text(STATS_GD, encoding="utf-8")
    import_project(godot_project)
    (godot_project / "stats.gd").write_text(BROKEN_STATS_GD, encoding="utf-8")
    resource_path = godot_project / "stats.tres"

    err = gda.error(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "Stats",
        "--project",
        str(godot_project),
        "--json",
        code="uninstantiable_script",
    )
    assert "Stats" in err["message"]
    assert "stats.gd" in err["message"]
    assert not resource_path.exists()


# A registered class_name that compiles and registers fine but cannot be
# constructed without arguments: script.new() has no args to give _init. Over an
# existing target its constructor must never run at all.
NEEDS_ARGS_STATS_GD = """\
class_name NeedsArgsStats
extends Resource


func _init(scale: float) -> void:
\tpass
"""


@pytest.mark.e2e
def test_resource_create_over_existing_target_refuses_before_constructing(
    godot_project,
):
    # No-clobber must win WITHOUT running the requested type's constructor (issue
    # #342 review): an existing target is refused with already_exists even when
    # --type is a registered class_name whose _init would fail. A broken
    # constructor over an existing file must stay already_exists, never turn into
    # uninstantiable_script — and getting already_exists (not uninstantiable_script)
    # is itself the proof that _init never ran, so no side effect touched the file.
    (godot_project / "needs_args_stats.gd").write_text(
        NEEDS_ARGS_STATS_GD, encoding="utf-8"
    )
    import_project(godot_project)
    resource_path = godot_project / "occupied.tres"
    # Occupy the target first with a plain built-in resource.
    first = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = resource_path.read_text(encoding="utf-8")

    err = gda.error(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "NeedsArgsStats",
        "--project",
        str(godot_project),
        "--json",
        code="already_exists",
    )
    assert str(resource_path) in err["message"]
    # The existing file is untouched — no clobber — and, because the code is
    # already_exists rather than uninstantiable_script, the broken constructor
    # never ran.
    assert resource_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_resource_create_non_tres_path_yields_invalid_path(godot_project):
    bad_path = godot_project / "palette.txt"

    err = gda.error(
        "resource",
        "create",
        str(bad_path),
        "--type",
        "Gradient",
        "--json",
        code="invalid_path",
    )
    assert ".tres" in err["message"]
    assert not bad_path.exists()


@pytest.mark.e2e
def test_resource_get_missing_yields_path_not_found(godot_project):
    missing = godot_project / "nope.tres"

    err = gda.error("resource", "get", str(missing), "--json", code="path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_resource_get_non_tres_path_yields_invalid_path(godot_project):
    bad_path = godot_project / "palette.txt"
    bad_path.write_text("not a resource", encoding="utf-8")

    err = gda.error("resource", "get", str(bad_path), "--json", code="invalid_path")
    assert ".tres" in err["message"]


# --- resource set / delete: round out .tres CRUD (issue #120) ------------


@pytest.mark.e2e
def test_resource_set_coerces_persists_and_round_trips_via_get(godot_project):
    # create → set → get: set coerces the CLI string to the property's declared
    # type, saves the .tres, and get reports the coerced value — resource get IS
    # the structured-level verification that set persisted.
    resource_path = godot_project / "palette.tres"
    created = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    was_set = gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "interpolation_mode",
        "--value",
        "1",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_data = json.loads(was_set.stdout)
    # The result reports the coerced value (the declared int, not the string).
    assert set_data["path"] == str(resource_path)
    assert set_data["property"] == "interpolation_mode"
    assert set_data["type"] == "int"
    assert set_data["value"] == 1

    got = gda("resource", "get", str(resource_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    # Round-trip: get reports the value set persisted to the .tres.
    assert by_name["interpolation_mode"]["value"] == 1


@pytest.mark.e2e
def test_resource_set_string_property_round_trips(godot_project):
    # A String property coerces trivially and round-trips through get.
    resource_path = godot_project / "palette.tres"
    gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")

    was_set = gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "resource_name",
        "--value",
        "Sunset",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    assert json.loads(was_set.stdout)["type"] == "String"

    got = gda("resource", "get", str(resource_path), "--json")
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    assert by_name["resource_name"]["value"] == "Sunset"


@pytest.mark.e2e
def test_resource_set_with_external_edit_in_window_yields_file_changed_externally(
    godot_project,
):
    # Staleness guard for the ResourceSaver path (issue #226): resource set loads the
    # .tres, coerces and sets a property, then re-saves; if the file changes on disk in
    # that window a blind save would clobber the external edit. The production-inert seam
    # (GDA_TEST_PERTURB_BEFORE_SAVE) simulates that edit, and the guard refuses.
    resource_path = godot_project / "palette.tres"
    created = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    err = gda.error(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "resource_name",
        "--value",
        "Sunset",
        "--json",
        extra_env={"GDA_TEST_PERTURB_BEFORE_SAVE": "1"},
        code="file_changed_externally",
    )
    assert str(resource_path) in err["message"]

    # The set did NOT land: resource_name is still empty (the default), not "Sunset".
    got = gda("resource", "get", str(resource_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    assert by_name["resource_name"]["value"] != "Sunset"
    assert not list(godot_project.rglob(".gda-*"))


@pytest.mark.e2e
def test_resource_set_unknown_property_is_a_clean_error(godot_project):
    # set edits an existing property; an unknown property is unknown_property,
    # never a silent create — the agent fixes the property name.
    resource_path = godot_project / "palette.tres"
    gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")

    err = gda.error(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "bogus_property",
        "--value",
        "1",
        "--json",
        code="unknown_property",
    )
    assert "bogus_property" in err["message"]


@pytest.mark.e2e
def test_resource_set_uncoercible_value_is_a_clean_error(godot_project):
    # An int property cannot take a non-numeric string — uncoercible_value (#55),
    # the .tres left untouched.
    resource_path = godot_project / "palette.tres"
    gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")
    before = resource_path.read_text(encoding="utf-8")

    err = gda.error(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "interpolation_mode",
        "--value",
        "not-a-number",
        "--json",
        code="uncoercible_value",
    )
    assert "not-a-number" in err["message"]
    # The file is untouched — the rejected coercion never wrote.
    assert resource_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_resource_set_missing_yields_path_not_found(godot_project):
    missing = godot_project / "nope.tres"

    err = gda.error(
        "resource",
        "set",
        str(missing),
        "--property",
        "x",
        "--value",
        "1",
        "--json",
        code="path_not_found",
    )
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_resource_delete_removes_file_and_round_trips_against_get(godot_project):
    # create → delete → get: delete removes the .tres and reports what was removed
    # (path + type); a subsequent get is now path_not_found, closing the lifecycle.
    resource_path = godot_project / "palette.tres"
    created = gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert resource_path.exists()

    deleted = gda("resource", "delete", str(resource_path), "--json")

    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    del_data = json.loads(deleted.stdout)
    assert del_data["path"] == str(resource_path)
    assert del_data["type"] == "Gradient"
    # The file is gone from disk.
    assert not resource_path.exists()

    # Round-trip: get now reports path_not_found — the lifecycle's now-not-found.
    gda.error("resource", "get", str(resource_path), "--json", code="path_not_found")


@pytest.mark.e2e
def test_resource_delete_missing_yields_path_not_found(godot_project):
    missing = godot_project / "nope.tres"

    err = gda.error("resource", "delete", str(missing), "--json", code="path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_resource_delete_non_tres_path_yields_invalid_path(godot_project):
    bad_path = godot_project / "palette.txt"
    bad_path.write_text("not a resource", encoding="utf-8")

    err = gda.error("resource", "delete", str(bad_path), "--json", code="invalid_path")
    assert ".tres" in err["message"]
    # The non-.tres file is untouched — the rejected addressing never deleted.
    assert bad_path.exists()


@pytest.mark.e2e
def test_resource_uid_resolves_both_directions_round_trip(imported_project):
    # path -> uid -> path: the script's import-assigned UID resolves back to the
    # same path. This is the bidirectional contract: query a path, get its UID;
    # query that UID, get the path back — proving both directions read one
    # consistent cache.
    gda = Gda(imported_project)

    path_to_uid = gda("resource", "uid", "res://hero.gd", "--json")
    assert path_to_uid.returncode == 0, path_to_uid.stdout + path_to_uid.stderr
    forward = json.loads(path_to_uid.stdout)
    assert forward["queried"] == "path"
    assert forward["path"] == "res://hero.gd"
    assert forward["uid"].startswith("uid://")

    uid = forward["uid"]
    uid_to_path = gda("resource", "uid", uid, "--json")
    assert uid_to_path.returncode == 0, uid_to_path.stdout + uid_to_path.stderr
    back = json.loads(uid_to_path.stdout)
    assert back["queried"] == "uid"
    assert back["uid"] == uid
    # The round-trip closes: the UID resolves back to the original path.
    assert back["path"] == "res://hero.gd"


@pytest.mark.e2e
def test_resource_uid_human_output_renders_uid_arrow_path(imported_project):
    # Without --json, a resolved mapping renders as `<uid> -> <path>`.
    gda = Gda(imported_project)

    proc = gda("resource", "uid", "res://hero.gd")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip().endswith("-> res://hero.gd")
    assert proc.stdout.strip().startswith("uid://")


@pytest.mark.e2e
def test_resource_uid_unknown_uid_is_unknown_uid(imported_project):
    # A syntactically valid uid:// not in the project's cache is unknown_uid.
    gda = Gda(imported_project)

    gda.error("resource", "uid", "uid://b00000000000b", "--json", code="unknown_uid")


@pytest.mark.e2e
def test_resource_uid_invalid_uid_is_invalid_uid(imported_project):
    # A uid:// whose body holds illegal characters fails text_to_id (INVALID_ID),
    # reported as invalid_uid — distinct from a well-formed-but-unknown UID.
    gda = Gda(imported_project)

    gda.error("resource", "uid", "uid://<invalid>", "--json", code="invalid_uid")


@pytest.mark.e2e
def test_resource_uid_path_not_found_is_path_not_found(imported_project):
    # A res:// path naming no resource is path_not_found.
    gda = Gda(imported_project)

    gda.error("resource", "uid", "res://missing.tres", "--json", code="path_not_found")


@pytest.mark.e2e
def test_resource_uid_path_without_uid_is_no_uid_assigned(imported_project):
    # A resource that exists but has no UID in the non-editor reverse cache is
    # no_uid_assigned — distinct from path_not_found (the file is there) and from
    # a UID-direction failure (the query was a path).
    gda = Gda(imported_project)

    gda.error("resource", "uid", "res://data.tres", "--json", code="no_uid_assigned")


@pytest.mark.e2e
def test_resource_uid_projectless_run_is_project_not_found():
    # Resolution queries the project's UID cache, so a projectless run is refused
    # with project_not_found rather than a misleading "no UID" answer.
    gda.error(
        "resource", "uid", "uid://b00000000000b", "--json", code="project_not_found"
    )
