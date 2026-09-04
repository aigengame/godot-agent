"""S3: gda shader create/get/set + theme create success paths (issue #115).

The asset-file groups author the asset-file types headlessly: a .gdshader is
plain shader source authored/read/edited as text, while theme create produces a
loadable .tres Theme. These tests drive the same proven pipeline as the scene,
node and script groups — Typer → binary resolution → runner → sentinel parse →
typed model → JSON — with canned engine output, no real Godot. The shader set
edit-mode interface is the script set interface (issue #118), reused here.
"""

import json


from gda.commands.script import ScriptSetMode
from tests.support import (
    SHADER_CREATE_RESULT,
    SHADER_GET_RESULT,
    SHADER_SET_RESULT,
    THEME_CREATE_RESULT,
    invoke_cli,
    sentinel,
)

# --- shader create ---------------------------------------------------------


def test_shader_create_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "create",
            "/tmp/proj/wave.gdshader",
            "--shader-type",
            "canvas_item",
            "--json",
        ],
        stdout=sentinel(SHADER_CREATE_RESULT),
        stderr="engine diagnostic\n",
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/wave.gdshader"
    assert data["shader_type"] == "canvas_item"
    # Dispatched by name with the typed params; with --shader-type and no
    # --content, content is null.
    assert fake.calls == [
        (
            "shader-create",
            {
                "path": "/tmp/proj/wave.gdshader",
                "content": None,
                "shader_type": "canvas_item",
            },
        )
    ]
    assert "engine diagnostic" in result.stderr


def test_shader_create_default_template_passes_null_content_and_type(monkeypatch):
    # The bare template: no --content, no --shader-type. Both pass through as
    # null, so the operation writes its default canvas_item template.
    result, fake = invoke_cli(
        monkeypatch,
        ["shader", "create", "/tmp/proj/wave.gdshader", "--json"],
        stdout=sentinel(SHADER_CREATE_RESULT),
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "shader-create",
            {"path": "/tmp/proj/wave.gdshader", "content": None, "shader_type": None},
        )
    ]


def test_shader_create_content_passes_verbatim_source(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "create",
            "/tmp/proj/x.gdshader",
            "--content",
            "shader_type spatial;\n",
            "--json",
        ],
        stdout=sentinel(
            {
                "path": "/tmp/proj/x.gdshader",
                "shader_type": "spatial",
                "created_dirs": [],
            }
        ),
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "shader-create",
            {
                "path": "/tmp/proj/x.gdshader",
                "content": "shader_type spatial;\n",
                "shader_type": None,
            },
        )
    ]


def test_shader_create_content_and_type_are_mutually_exclusive(monkeypatch):
    # Verbatim content is not templated, so a shader_type has nowhere to go;
    # supplying both is a usage error (exit 2), never a silent precedence rule.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "create",
            "/tmp/proj/wave.gdshader",
            "--content",
            "shader_type canvas_item;\n",
            "--shader-type",
            "spatial",
            "--json",
        ],
        stdout=sentinel(SHADER_CREATE_RESULT),
    )

    assert result.exit_code == 2
    # The usage error fires before any dispatch — the engine is never reached.
    assert fake.calls == []


# --- shader get ------------------------------------------------------------


def test_shader_get_json_emits_source_and_metadata_and_exit_zero(monkeypatch):
    # shader get is the verifier (issue #115): it reads a shader's source back as
    # raw text with its shader_type, so a create round-trips.
    result, fake = invoke_cli(
        monkeypatch,
        ["shader", "get", "/tmp/proj/wave.gdshader", "--json"],
        stdout=sentinel(SHADER_GET_RESULT),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["source"] == "shader_type canvas_item;\n"
    assert data["shader_type"] == "canvas_item"
    assert fake.calls == [("shader-get", {"path": "/tmp/proj/wave.gdshader"})]


# --- shader set: reuses the script set edit-mode interface (issue #115) -----


def test_shader_set_search_replace_dispatches_search_and_replace(monkeypatch):
    # search-replace mode: --search/--replace ride through; the other mode params
    # pass as null. The CLI resolves the edit mode once and stamps the explicit
    # `mode` discriminator (issue #133) — the SAME ScriptSetMode as script set.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "set",
            "/tmp/proj/wave.gdshader",
            "--search",
            "canvas_item",
            "--replace",
            "spatial",
            "--json",
        ],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "shader-set",
            {
                "path": "/tmp/proj/wave.gdshader",
                "mode": ScriptSetMode.SEARCH_REPLACE,
                "search": "canvas_item",
                "replace": "spatial",
                "start_line": None,
                "end_line": None,
                "content": None,
            },
        )
    ]


def test_shader_set_line_range_dispatches_start_end_and_content(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "set",
            "/tmp/proj/wave.gdshader",
            "--start-line",
            "1",
            "--end-line",
            "1",
            "--content",
            "shader_type spatial;",
            "--json",
        ],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "shader-set",
            {
                "path": "/tmp/proj/wave.gdshader",
                "mode": ScriptSetMode.LINE_RANGE,
                "search": None,
                "replace": None,
                "start_line": 1,
                "end_line": 1,
                "content": "shader_type spatial;",
            },
        )
    ]


def test_shader_set_full_overwrite_dispatches_content_only(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "set",
            "/tmp/proj/wave.gdshader",
            "--content",
            "shader_type spatial;\n",
            "--json",
        ],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "shader-set",
            {
                "path": "/tmp/proj/wave.gdshader",
                "mode": ScriptSetMode.FULL,
                "search": None,
                "replace": None,
                "start_line": None,
                "end_line": None,
                "content": "shader_type spatial;\n",
            },
        )
    ]


def _assert_set_usage_error(fake, result):
    # A mode-validation error is a usage error (exit 2) that fires before any
    # dispatch — the engine is never reached. Reuses the script set rule.
    assert result.exit_code == 2
    assert fake.calls == []


def test_shader_set_no_flags_is_a_usage_error(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["shader", "set", "/tmp/proj/wave.gdshader", "--json"],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    _assert_set_usage_error(fake, result)


def test_shader_set_search_without_replace_is_a_usage_error(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["shader", "set", "/tmp/proj/wave.gdshader", "--search", "x", "--json"],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    _assert_set_usage_error(fake, result)


def test_shader_set_search_replace_and_content_are_mutually_exclusive(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        [
            "shader",
            "set",
            "/tmp/proj/wave.gdshader",
            "--search",
            "x",
            "--replace",
            "y",
            "--content",
            "z",
            "--json",
        ],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    _assert_set_usage_error(fake, result)


# --- theme create: engine-backed .tres -------------------------------------


def test_theme_create_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["theme", "create", "/tmp/proj/ui.tres", "--json"],
        stdout=sentinel(THEME_CREATE_RESULT),
        stderr="engine diagnostic\n",
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/ui.tres"
    assert data["type"] == "Theme"
    assert fake.calls == [("theme-create", {"path": "/tmp/proj/ui.tres"})]
    assert "engine diagnostic" in result.stderr


# --- human-readable output (no --json) -------------------------------------


def test_shader_create_human_output(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch,
        ["shader", "create", "/tmp/proj/wave.gdshader"],
        stdout=sentinel(SHADER_CREATE_RESULT),
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == "created /tmp/proj/wave.gdshader (shader_type canvas_item)"
    )


def test_shader_get_human_output_renders_metadata_then_source(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch,
        ["shader", "get", "/tmp/proj/wave.gdshader"],
        stdout=sentinel(SHADER_GET_RESULT),
    )

    assert result.exit_code == 0
    assert "/tmp/proj/wave.gdshader (shader_type canvas_item)" in result.stdout
    assert "shader_type canvas_item;" in result.stdout


def test_shader_set_human_output_renders_metadata(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch,
        ["shader", "set", "/tmp/proj/wave.gdshader", "--content", "x"],
        stdout=sentinel(SHADER_SET_RESULT),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "set /tmp/proj/wave.gdshader (shader_type spatial)"


def test_theme_create_human_output(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch,
        ["theme", "create", "/tmp/proj/ui.tres"],
        stdout=sentinel(THEME_CREATE_RESULT),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "created /tmp/proj/ui.tres (Theme)"
