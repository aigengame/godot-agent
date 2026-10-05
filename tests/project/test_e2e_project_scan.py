"""E2E: `gda project scan` owns the engine class index in a headless workflow (#1073).

A project the editor never opened has no `.godot/global_script_class_cache.cfg`.
The GDScript analyzer finds a project `class_name` only through that index, so a
script typed with a project class does not compile until an editor filesystem
scan has run. `gda project scan` runs the engine import pass, which is that scan.
Run e2e SERIALLY; not a fresh empty HOME.
"""

import base64

import pytest

from gda.core.project.import_evidence import CACHE_ROOT_REL
from tests.conftest import project_godot
from tests.project.class_index_project import components_project
from tests.support import PNG_1X1_B64, Gda


@pytest.mark.e2e
def test_a_scan_lets_a_never_opened_project_compile_its_class_types(tmp_path):
    project = components_project(tmp_path / "p")
    gda = Gda(project, json_output=True, timeout=300)

    before = gda.json("script", "validate", "res://holder.gd")
    assert before["valid"] is False

    scanned = gda.json("project", "scan")
    classes = {entry["name"]: entry["path"] for entry in scanned["classes"]}
    assert classes == {
        "AttackComponent": "res://attack_component.gd",
        "FireAttack": "res://fire_attack.gd",
        "Mover": "res://mover.gd",
    }

    after = gda.json("script", "validate", "res://holder.gd")
    assert after["valid"] is True, after
    attached = gda.json(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://holder.gd",
    )
    assert attached["script"] == "res://holder.gd"
    created = gda.json("resource", "create", "res://fire.tres", "--type", "FireAttack")
    assert created["path"] == "res://fire.tres"
    assert 'script_class="FireAttack"' in (project / "fire.tres").read_text()


# Godot's csv_translation importer writes a `<name>.<locale>.translation` resource
# BESIDE the source, which the pass rewrites when the CSV changes: the shape that
# shows a rewritten file in the report, as `export run`'s mutation e2e uses it.
_TRANSLATION_CSV = "keys,en\nGREET,Hello\n"
_TRANSLATION_CSV_EDITED = "keys,en\nGREET,Hello there\nBYE,Goodbye\n"


@pytest.mark.e2e
def test_a_scan_reports_what_the_pass_did_to_the_tree_and_the_classes(tmp_path):
    project = components_project(tmp_path / "p")
    (project / "icon.png").write_bytes(base64.b64decode(PNG_1X1_B64))
    (project / "ui.csv").write_text(_TRANSLATION_CSV, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)

    # (1) A COLD project: the pass creates the cache and the files beside the
    # sources, classified as `export run` classifies them.
    cold = gda.json("project", "scan")
    report = cold["project_tree_mutations"]
    assert report["cache_root"] == "res://" + CACHE_ROOT_REL
    created = {entry["path"]: entry["classification"] for entry in report["created"]}
    assert {path for path, kind in created.items() if kind == "source_adjacent"} == {
        "res://attack_component.gd.uid",
        "res://fire_attack.gd.uid",
        "res://holder.gd.uid",
        "res://mover.gd.uid",
        "res://icon.png.import",
        "res://ui.csv.import",
        "res://ui.en.translation",
    }
    assert created["res://.godot/global_script_class_cache.cfg"] == "cache_owned"
    assert all(
        kind == "cache_owned"
        for path, kind in created.items()
        if path.startswith(report["cache_root"] + "/")
    )
    assert report["modified"] == []
    assert [c["name"] for c in cold["classes"]] == [
        "AttackComponent",
        "FireAttack",
        "Mover",
    ]
    assert cold["engine_errors"] == []
    assert cold["engine_errors_truncated"] is False

    # (2) THE SAME SCAN AGAIN, no source changed: nothing is created outside the
    # cache root and nothing is rewritten.
    warm = gda.json("project", "scan")["project_tree_mutations"]
    assert [
        entry["path"]
        for entry in warm["created"]
        if not entry["path"].startswith(warm["cache_root"] + "/")
    ] == []
    assert warm["modified"] == []

    # (3) A SOURCE CHANGED: the pass re-imports the CSV and rewrites the tracked
    # translation beside it, which the report names with both sizes.
    (project / "ui.csv").write_text(_TRANSLATION_CSV_EDITED, encoding="utf-8")
    rewrote = gda.json("project", "scan")["project_tree_mutations"]
    rewritten = {entry["path"]: entry for entry in rewrote["modified"]}
    assert set(rewritten) == {"res://ui.en.translation"}
    entry = rewritten["res://ui.en.translation"]
    assert entry["size"] == (project / "ui.en.translation").stat().st_size
    assert entry["size_before"] < entry["size"]


@pytest.mark.e2e
def test_an_import_error_is_data_and_a_broken_script_keeps_its_class(tmp_path):
    project = components_project(tmp_path / "p")
    (project / "bad.png").write_text("not a png at all", encoding="utf-8")
    (project / "broken.gd").write_text(
        "class_name Broken extends Resource\n\nfunc f(\n", encoding="utf-8"
    )
    gda = Gda(project, json_output=True, timeout=300)

    scanned = gda.json("project", "scan")

    assert "ERROR: Error importing 'res://bad.png'." in scanned["engine_errors"]
    assert all(
        line.startswith(("ERROR:", "SCRIPT ERROR:", "SHADER ERROR:"))
        for line in scanned["engine_errors"]
    )
    assert scanned["engine_errors_truncated"] is False
    classes = {entry["name"]: entry["path"] for entry in scanned["classes"]}
    assert classes["Broken"] == "res://broken.gd"


# The Project-code execution surface states ONCE what the engine import pass runs
# (#1073), and the `project scan` and `resource import` points refer to it. This
# pins that statement on the engine: each spy writes a marker file named after the
# callback that ran, into a directory the test passes through the environment the
# engine inherits from gda.
_MARK = (
    "func _mark(what: String) -> void:\n"
    '\tvar dir := OS.get_environment("GDA_TEST_MARKER_DIR")\n'
    "\tFileAccess.open(dir.path_join(what), FileAccess.WRITE).store_string(what)\n"
)
_TOOL_SPY_GD = (
    "@tool\nextends Node\n\nvar _seen := false\n\n"
    'func _init() -> void:\n\t_mark("tool_init")\n\n'
    'func _enter_tree() -> void:\n\t_mark("tool_enter_tree")\n\n'
    'func _ready() -> void:\n\t_mark("tool_ready")\n\n'
    "func _process(_delta: float) -> void:\n"
    '\tif not _seen:\n\t\t_seen = true\n\t\t_mark("tool_process")\n\n' + _MARK
)
_PLAIN_SPY_GD = (
    "extends Node\n\n"
    'func _init() -> void:\n\t_mark("plain_init")\n\n'
    'func _ready() -> void:\n\t_mark("plain_ready")\n\n' + _MARK
)
_PLUGIN_GD = (
    "@tool\nextends EditorPlugin\n\n"
    'func _enter_tree() -> void:\n\t_mark("plugin_enter_tree")\n\n'
    'func _ready() -> void:\n\t_mark("plugin_ready")\n\n' + _MARK
)
_PLUGIN_CFG = (
    '[plugin]\n\nname="spy"\ndescription=""\nauthor=""\nversion="1"\n'
    'script="plugin.gd"\n'
)
_PASS_RUNS = {
    "tool_init",
    "tool_enter_tree",
    "tool_ready",
    "tool_process",
    "plugin_enter_tree",
    "plugin_ready",
}


def _surface_project(directory):
    (directory / "addons" / "spy").mkdir(parents=True)
    (directory / "project.godot").write_text(
        project_godot(
            name="gda-pass-surface",
            extra=(
                "[autoload]\n\n"
                'ToolSpy="*res://tool_spy.gd"\n'
                'PlainSpy="*res://plain_spy.gd"\n\n'
                "[editor_plugins]\n\n"
                'enabled=PackedStringArray("res://addons/spy/plugin.cfg")\n'
            ),
        ),
        encoding="utf-8",
    )
    (directory / "tool_spy.gd").write_text(_TOOL_SPY_GD, encoding="utf-8")
    (directory / "plain_spy.gd").write_text(_PLAIN_SPY_GD, encoding="utf-8")
    (directory / "addons" / "spy" / "plugin.cfg").write_text(
        _PLUGIN_CFG, encoding="utf-8"
    )
    (directory / "addons" / "spy" / "plugin.gd").write_text(
        _PLUGIN_GD, encoding="utf-8"
    )
    (directory / "data.csv").write_text("keys,en\nHELLO,Hello\n", encoding="utf-8")
    return directory


@pytest.mark.e2e
def test_the_import_pass_runs_tool_autoloads_and_editor_plugins_only(tmp_path):
    # `resource import` of an uncached asset runs the pass and nothing else.
    project = _surface_project(tmp_path / "p")
    markers = tmp_path / "markers"
    markers.mkdir()
    gda = Gda(
        project,
        json_output=True,
        timeout=300,
        extra_env={"GDA_TEST_MARKER_DIR": str(markers)},
    )

    gda.json("resource", "import", "res://data.csv")

    assert {path.name for path in markers.iterdir()} == _PASS_RUNS


@pytest.mark.e2e
def test_a_scan_runs_the_pass_then_one_ordinary_project_op(tmp_path):
    # `project scan` runs the same pass, then reads the class list in an ordinary
    # `--project` op, which starts every autoload as any such op does: so the plain
    # autoload runs here, and only through that read.
    project = _surface_project(tmp_path / "p")
    markers = tmp_path / "markers"
    markers.mkdir()
    gda = Gda(
        project,
        json_output=True,
        timeout=300,
        extra_env={"GDA_TEST_MARKER_DIR": str(markers)},
    )

    gda.json("project", "scan")

    assert {path.name for path in markers.iterdir()} == _PASS_RUNS | {
        "plain_init",
        "plain_ready",
    }
