"""S1 (e2e): asset-file authoring against the real Godot engine (issue #115).

The asset-file tracer: ``gda shader create`` → ``shader get`` → ``shader set``
round-trips a ``.gdshader`` (plain text authoring), and ``gda theme create``
produces a genuinely LOADABLE ``.tres`` Theme resource — verified here by loading
it back through the engine, which is the structured-level proof that the create
produced a real resource, not hand-written text.
"""

import json
import subprocess

import pytest

from tests.support import GODOT, Gda

gda = Gda()


# --- shader create → get → set round-trip ----------------------------------


@pytest.mark.e2e
def test_shader_create_default_template_then_get_round_trip(godot_project):
    # The bare template: create writes `shader_type canvas_item;`, get reads it
    # back. The source on disk IS what get reports — the round-trip proves the
    # write.
    shader_path = godot_project / "wave.gdshader"

    created = gda("shader", "create", str(shader_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(shader_path)
    assert data["shader_type"] == "canvas_item"
    assert shader_path.exists()

    got = gda("shader", "get", str(shader_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    # Round-trip: get returns exactly the source create wrote to disk.
    assert got_data["source"] == shader_path.read_text(encoding="utf-8")
    assert got_data["source"] == "shader_type canvas_item;\n"
    assert got_data["shader_type"] == "canvas_item"


@pytest.mark.e2e
def test_shader_create_with_type_parameterizes_the_template(godot_project):
    shader_path = godot_project / "world.gdshader"

    created = gda(
        "shader", "create", str(shader_path), "--shader-type", "spatial", "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["shader_type"] == "spatial"

    got = gda("shader", "get", str(shader_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["shader_type"] == "spatial"


@pytest.mark.e2e
def test_shader_create_with_content_round_trips_verbatim_source(godot_project):
    # --content supplies verbatim source; get reports it byte-identical and
    # parses the shader_type — without ever compiling the shader (issue #30).
    shader_path = godot_project / "blur.gdshader"
    source = (
        "shader_type canvas_item;\n\n"
        "void fragment() {\n"
        "\tCOLOR = texture(TEXTURE, UV) * 0.5;\n"
        "}\n"
    )

    created = gda("shader", "create", str(shader_path), "--content", source, "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["shader_type"] == "canvas_item"

    got = gda("shader", "get", str(shader_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["source"] == source


@pytest.mark.e2e
def test_shader_set_search_replace_round_trips_through_get(godot_project):
    # The full create → get → set round-trip, set's search-replace mode (the
    # reused script-set interface, issue #115): edit the shader_type and read it
    # back changed.
    shader_path = godot_project / "edit.gdshader"
    gda("shader", "create", str(shader_path), "--json")

    edited = gda(
        "shader",
        "set",
        str(shader_path),
        "--search",
        "canvas_item",
        "--replace",
        "spatial",
        "--json",
    )

    assert edited.returncode == 0, edited.stdout + edited.stderr
    assert json.loads(edited.stdout)["shader_type"] == "spatial"

    got = gda("shader", "get", str(shader_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["source"] == "shader_type spatial;\n"


@pytest.mark.e2e
def test_shader_set_full_overwrite_round_trips_through_get(godot_project):
    shader_path = godot_project / "full.gdshader"
    gda("shader", "create", str(shader_path), "--json")
    new_source = "shader_type particles;\n"

    edited = gda("shader", "set", str(shader_path), "--content", new_source, "--json")

    assert edited.returncode == 0, edited.stdout + edited.stderr
    got = gda("shader", "get", str(shader_path), "--json")
    assert json.loads(got.stdout)["source"] == new_source


# --- shader failure modes (against the real engine) ------------------------


@pytest.mark.e2e
def test_shader_create_no_clobber_existing_file(godot_project):
    shader_path = godot_project / "once.gdshader"
    assert gda("shader", "create", str(shader_path), "--json").returncode == 0
    before = shader_path.read_text(encoding="utf-8")

    gda.error(
        "shader",
        "create",
        str(shader_path),
        "--content",
        "shader_type spatial;\n",
        "--json",
        code="already_exists",
    )
    # The original file is untouched — no-clobber.
    assert shader_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_shader_get_missing_file_is_path_not_found(godot_project):
    gda.error(
        "shader",
        "get",
        str(godot_project / "nope.gdshader"),
        "--json",
        code="path_not_found",
    )


@pytest.mark.e2e
def test_shader_set_no_search_match_leaves_file_untouched(godot_project):
    shader_path = godot_project / "nomatch.gdshader"
    gda("shader", "create", str(shader_path), "--json")
    before = shader_path.read_text(encoding="utf-8")

    gda.error(
        "shader",
        "set",
        str(shader_path),
        "--search",
        "xyzzy",
        "--replace",
        "z",
        "--json",
        code="no_search_match",
    )
    assert shader_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_shader_set_invalid_line_range_is_invalid_line_range(godot_project):
    shader_path = godot_project / "range.gdshader"
    gda("shader", "create", str(shader_path), "--json")

    gda.error(
        "shader",
        "set",
        str(shader_path),
        "--start-line",
        "50",
        "--end-line",
        "99",
        "--content",
        "x",
        "--json",
        code="invalid_line_range",
    )


# --- theme create: a genuinely LOADABLE .tres ------------------------------


@pytest.mark.e2e
def test_theme_create_produces_a_loadable_tres(godot_project):
    # The acceptance core: theme create must produce a LOADABLE Theme resource,
    # not hand-written text. Create it, then load it back through the engine and
    # assert the loaded resource is a Theme — the structured-level proof.
    theme_path = godot_project / "ui.tres"

    created = gda("theme", "create", str(theme_path), "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(theme_path)
    assert data["type"] == "Theme"
    assert theme_path.exists()

    # Load the saved .tres back through Godot and confirm it is a real Theme.
    loaded = _load_resource_class(theme_path)
    assert loaded == "Theme", f"loaded class was {loaded!r}, expected Theme"


@pytest.mark.e2e
def test_theme_create_no_clobber_existing_file(godot_project):
    theme_path = godot_project / "dup.tres"
    assert gda("theme", "create", str(theme_path), "--json").returncode == 0

    gda.error("theme", "create", str(theme_path), "--json", code="already_exists")


@pytest.mark.e2e
def test_theme_create_wrong_extension_is_invalid_path(godot_project):
    gda.error(
        "theme", "create", str(godot_project / "ui.txt"), "--json", code="invalid_path"
    )


def _load_resource_class(resource_path) -> str:
    """Load ``resource_path`` through a one-shot headless Godot and report its class.

    A direct engine probe (separate from gda's own pipeline): proves theme create
    wrote a genuinely loadable resource by having the engine load it back.
    """
    probe = resource_path.parent / "_probe_load.gd"
    probe.write_text(
        "extends SceneTree\n"
        "func _initialize() -> void:\n"
        f'\tvar r := ResourceLoader.load("{resource_path}")\n'
        '\tprint("<<<CLASS>>>" + (r.get_class() if r != null else "NULL") + "<<<END>>>")\n'
        "func _process(_d):\n"
        "\tquit(0)\n"
        "\treturn true\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(GODOT), "--headless", "--script", str(probe)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout
    start = out.find("<<<CLASS>>>") + len("<<<CLASS>>>")
    end = out.find("<<<END>>>", start)
    return out[start:end]
