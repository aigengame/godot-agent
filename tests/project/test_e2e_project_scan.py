"""E2E: `gda project scan` owns the engine class index in a headless workflow (#1073).

A project the editor never opened has no `.godot/global_script_class_cache.cfg`.
The GDScript analyzer finds a project `class_name` only through that index, so a
script typed with a project class does not compile until an editor filesystem
scan has run. `gda project scan` runs that scan in the `Editor context` (#1255):
one editor process, which also reads the class list, with the editor's
directories in a root of its own.
Run e2e SERIALLY; not a fresh empty HOME.
"""

import base64
import json
import re
import sys
from pathlib import Path

import pytest

from gda.core.project.import_evidence import CACHE_ROOT_REL
from gda.core.steps.editor_context import TIMEOUT_LABEL
from tests.conftest import project_godot
from tests.project.class_index_project import components_project, rename_class
from tests.support import EDITOR_DIR_VARIABLES, PNG_1X1_B64, Gda


# The RID leak record the editor prints at exit, even for an empty project
# (ADR-0048, Outcome note of 2026-10-31). It is an error line, so a scan can report
# it in `engine_errors`; the engine version decides whether it reaches stderr.
_EXIT_LEAK_RECORD = re.compile(
    r"ERROR: \d+ RID allocations of type '.+' were leaked at exit\."
)


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
    assert [
        line for line in cold["engine_errors"] if not _EXIT_LEAK_RECORD.fullmatch(line)
    ] == []
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
# (#1073), and the `project scan` and `resource import` points refer to it: the
# editor's boot scan is the same point. This pins that statement on the engine: each spy writes a marker file named after the
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
def test_a_resource_import_runs_tool_autoloads_and_editor_plugins_only(tmp_path):
    # `resource import` of an uncached asset boots the editor once and nothing
    # else (#1256).
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
def test_a_scan_runs_tool_autoloads_and_editor_plugins_only(tmp_path):
    # `project scan` boots the editor once and reads the class list in the same
    # process (#1255), so the plain autoload does not run.
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

    assert {path.name for path in markers.iterdir()} == _PASS_RUNS


# Project code shares stdout with the payload. In the editor context a `@tool`
# autoload's `_init` prints before the result, and an editor plugin's `_exit_tree`
# prints after it, because the editor exits its plugins after the payload quits.
# Each spy here prints sentinel text, then writes its marker, so the markers prove
# that the lines were printed (ADR-0002, Outcome note of 2026-10-31). The plugin's
# second line nests too deep for the decoder to read.
_LOUD_TOOL_GD = (
    "@tool\nextends Node\n\n"
    'func _init() -> void:\n\tprint("init <<<GDA:RESULT>>>")\n\t_mark("tool_init")\n\n'
    + _MARK
)
_LOUD_PLUGIN_GD = (
    "@tool\nextends EditorPlugin\n\n"
    "func _exit_tree() -> void:\n"
    '\tprint("cleanup <<<GDA:END>>>")\n'
    '\tprint("debug <<<GDA:RESULT>>>" + "[".repeat(100000))\n'
    '\t_mark("plugin_exit_tree")\n\n' + _MARK
)


@pytest.mark.e2e
def test_sentinel_text_that_project_code_prints_around_the_result_is_ignored(
    tmp_path,
):
    project = tmp_path / "p"
    (project / "addons" / "loud").mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot(
            name="gda-loud-project",
            extra=(
                '[autoload]\n\nLoudTool="*res://loud_tool.gd"\n\n'
                "[editor_plugins]\n\n"
                'enabled=PackedStringArray("res://addons/loud/plugin.cfg")\n'
            ),
        ),
        encoding="utf-8",
    )
    (project / "loud_tool.gd").write_text(_LOUD_TOOL_GD, encoding="utf-8")
    (project / "addons" / "loud" / "plugin.cfg").write_text(
        _PLUGIN_CFG, encoding="utf-8"
    )
    (project / "addons" / "loud" / "plugin.gd").write_text(
        _LOUD_PLUGIN_GD, encoding="utf-8"
    )
    (project / "mover.gd").write_text(
        "class_name Mover\nextends Node\n", encoding="utf-8"
    )
    markers = tmp_path / "markers"
    markers.mkdir()
    gda = Gda(
        project,
        json_output=True,
        timeout=300,
        extra_env={"GDA_TEST_MARKER_DIR": str(markers)},
    )

    scanned = gda.json("project", "scan")

    assert {path.name for path in markers.iterdir()} == {
        "tool_init",
        "plugin_exit_tree",
    }
    classes = {entry["name"]: entry["path"] for entry in scanned["classes"]}
    assert classes == {"Mover": "res://mover.gd"}


def _gda_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("gda: ")]


@pytest.mark.e2e
def test_a_scan_discloses_the_dialog_of_a_plugin_that_fails_to_load(tmp_path):
    # ADR-0048 decision 4 (#1257): a visible dialog is disclosure, not a verdict.
    # The plugin script does not compile, so the editor opens its warning dialog
    # and disables the plugin, and the scan still succeeds. The expected text is
    # the editor's own (`EditorNode::set_addon_plugin_enabled` and `show_warning`,
    # editor/editor_node.cpp, 4.6.3-stable), and its line break is escaped.
    project = tmp_path / "p"
    (project / "addons" / "broken").mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot(
            name="gda-broken-plugin",
            extra=(
                "[editor_plugins]\n\n"
                'enabled=PackedStringArray("res://addons/broken/plugin.cfg")\n'
            ),
        ),
        encoding="utf-8",
    )
    (project / "addons" / "broken" / "plugin.cfg").write_text(
        _PLUGIN_CFG, encoding="utf-8"
    )
    (project / "addons" / "broken" / "plugin.gd").write_text(
        "@tool\nextends EditorPlugin\n\nfunc _enter_tree(\n", encoding="utf-8"
    )

    result = Gda(project, json_output=True, timeout=300)("project", "scan")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gda_lines(result.stderr) == [
        "gda: running operation: project-scan",
        'gda: dialog AcceptDialog title="Warning!" text="Unable to load addon'
        " script from path: 'res://addons/broken/plugin.gd'. This might be due to"
        " a code error in that script.\\nDisabling the addon at"
        " 'res://addons/broken/plugin.cfg' to prevent further errors.\"",
    ]


@pytest.mark.e2e
def test_a_scan_with_no_visible_dialog_adds_no_line(tmp_path):
    # ADR-0048 decision 4 (#1257): the payload reads the dialogs, and with none
    # visible it prints nothing for them.
    project = tmp_path / "p"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-no-dialog"), encoding="utf-8"
    )

    result = Gda(project, json_output=True, timeout=300)("project", "scan")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gda_lines(result.stderr) == ["gda: running operation: project-scan"]


# The escapes Godot's `String::json_escape` writes for the line breaks it handles
# (core/string/ustring.cpp, 4.6.3-stable).
_JSON_ESCAPES = {"\n": "\\n", "\v": "\\v", "\f": "\\f", "\r": "\\r"}


@pytest.mark.e2e
def test_a_dialog_record_stays_one_line_for_every_line_break(tmp_path):
    # ADR-0048 decision 4 (#1257): gda reads the child's stderr in `str.splitlines`
    # lines (`gda.core.engine.engine_log`), so a dialog whose title and text hold
    # each code point that ends such a line is still one record, and no part of it
    # reads as an engine error line.
    breaks = [c for c in range(0x110000) if len(f"a{chr(c)}b".splitlines()) != 1]
    project = tmp_path / "p"
    (project / "addons" / "breaks").mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot(
            name="gda-dialog-breaks",
            extra=(
                "[editor_plugins]\n\n"
                'enabled=PackedStringArray("res://addons/breaks/plugin.cfg")\n'
            ),
        ),
        encoding="utf-8",
    )
    (project / "addons" / "breaks" / "plugin.cfg").write_text(
        _PLUGIN_CFG, encoding="utf-8"
    )
    (project / "addons" / "breaks" / "plugin.gd").write_text(
        "@tool\nextends EditorPlugin\n\n"
        "func _enter_tree() -> void:\n"
        '\tvar title := "T"\n'
        '\tvar text := "D"\n'
        f"\tfor code in {breaks}:\n"
        '\t\ttitle += char(code) + "ERROR: dialog segment"\n'
        '\t\ttext += char(code) + "ERROR: dialog segment"\n'
        "\tvar dialog := AcceptDialog.new()\n"
        "\tdialog.title = title\n"
        "\tdialog.dialog_text = text\n"
        "\tEditorInterface.get_base_control().add_child(dialog)\n"
        "\tdialog.popup_centered()\n",
        encoding="utf-8",
    )

    result = Gda(project, json_output=True, timeout=300)("project", "scan")

    assert result.returncode == 0, result.stdout + result.stderr

    def escaped(head: str) -> str:
        return head + "".join(
            _JSON_ESCAPES.get(chr(c), f"\\u{c:04x}") + "ERROR: dialog segment"
            for c in breaks
        )

    assert [line for line in result.stderr.splitlines() if "segment" in line] == [
        f'gda: dialog AcceptDialog title="{escaped("T")}" text="{escaped("D")}"'
    ]
    scanned = json.loads(result.stdout)
    assert not any("segment" in line for line in scanned["engine_errors"])


# Deeper than GDScript's call stack: `debug/settings/gdscript/max_call_stack`
# defaults to 1024 (modules/gdscript/gdscript.cpp, 4.6.3-stable).
_DEEP_TREE_GD = (
    "@tool\nextends EditorPlugin\n\n"
    "func _enter_tree() -> void:\n"
    "\tvar parent: Node = self\n"
    "\tfor i in 2048:\n"
    "\t\tvar child := Node.new()\n"
    "\t\tparent.add_child(child)\n"
    "\t\tparent = child\n"
)


@pytest.mark.e2e
def test_a_scan_of_a_tree_deeper_than_the_script_call_stack_adds_no_line(tmp_path):
    # ADR-0048 decision 4 (#1257): with no visible dialog, the dialog read adds
    # nothing to stderr, whatever the depth of the editor's tree.
    project = tmp_path / "p"
    (project / "addons" / "deep").mkdir(parents=True)
    (project / "project.godot").write_text(
        project_godot(
            name="gda-deep-tree",
            extra=(
                "[editor_plugins]\n\n"
                'enabled=PackedStringArray("res://addons/deep/plugin.cfg")\n'
            ),
        ),
        encoding="utf-8",
    )
    (project / "addons" / "deep" / "plugin.cfg").write_text(
        _PLUGIN_CFG, encoding="utf-8"
    )
    (project / "addons" / "deep" / "plugin.gd").write_text(
        _DEEP_TREE_GD, encoding="utf-8"
    )

    result = Gda(project, json_output=True, timeout=300)("project", "scan")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gda_lines(result.stderr) == ["gda: running operation: project-scan"]
    scanned = json.loads(result.stdout)
    assert [
        line
        for line in scanned["engine_errors"]
        if not _EXIT_LEAK_RECORD.fullmatch(line)
    ] == []


def _index_classes(project: Path) -> dict[str, str]:
    """The ``class`` -> ``path`` pairs of the index the engine wrote on disk."""
    text = (project / ".godot" / "global_script_class_cache.cfg").read_text()
    pairs = {}
    for entry in re.findall(r"\{[^{}]*\}", text):
        name = re.search(r'"class": &"([^"]+)"', entry)
        path = re.search(r'"path": "([^"]+)"', entry)
        assert name and path, entry
        pairs[name[1]] = path[1]
    return pairs


@pytest.mark.e2e
def test_after_a_rename_the_classes_are_the_index_the_scan_wrote(tmp_path):
    project = components_project(tmp_path / "p")
    gda = Gda(project, json_output=True, timeout=300)
    gda.json("project", "scan")
    rename_class(project, "mover.gd", "Mover", "Walker")

    scanned = gda.json("project", "scan")

    classes = {entry["name"]: entry["path"] for entry in scanned["classes"]}
    assert classes == _index_classes(project)
    assert classes["Walker"] == "res://mover.gd"
    assert "Mover" not in classes


# A `@tool` autoload that records where the editor's directories are, then wedges
# the editor when the test asks, so a timeout is the test's to cause.
_DIR_SPY_GD = """\
@tool
extends Node

func _ready() -> void:
	var dirs := {
		"config": OS.get_config_dir(),
		"data": OS.get_data_dir(),
		"cache": OS.get_cache_dir(),
	}
	var out := OS.get_environment("GDA_TEST_MARKER_DIR").path_join("dirs.json")
	FileAccess.open(out, FileAccess.WRITE).store_string(JSON.stringify(dirs))
	if OS.get_environment("GDA_TEST_WEDGE") == "1":
		printerr("SPY WEDGED")
		while true:
			OS.delay_msec(50)
"""


def _dir_spy_project(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "project.godot").write_text(
        project_godot(
            name="gda-editor-dirs",
            extra='[autoload]\n\nDirSpy="*res://dir_spy.gd"\n',
        ),
        encoding="utf-8",
    )
    (directory / "dir_spy.gd").write_text(_DIR_SPY_GD, encoding="utf-8")
    return directory


def _editor_dirs(markers: Path) -> list[Path]:
    dirs = json.loads((markers / "dirs.json").read_text(encoding="utf-8"))
    return [Path(dirs[key]).resolve() for key in ("config", "data", "cache")]


def _dirs_env(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    # TMPDIR decides where the private root goes; the platform's own variables
    # point at a stand-in for the real directories, which must stay empty.
    temp, stand_in, markers = (tmp_path / name for name in ("temp", "real", "m"))
    for directory in (temp, stand_in, markers):
        directory.mkdir()
    env = {
        "TMPDIR": str(temp),
        "GDA_TEST_MARKER_DIR": str(markers),
        **{name: str(stand_in) for name in EDITOR_DIR_VARIABLES[sys.platform]},
    }
    return temp, stand_in, markers, env


@pytest.mark.e2e
def test_the_editor_writes_into_a_private_root_that_is_removed_after_it(tmp_path):
    project = _dir_spy_project(tmp_path / "p")
    temp, stand_in, markers, env = _dirs_env(tmp_path)
    gda = Gda(project, json_output=True, timeout=300, extra_env=env)

    gda.json("project", "scan")

    dirs = _editor_dirs(markers)
    roots = {directory.relative_to(temp.resolve()).parts[0] for directory in dirs}
    [root] = roots
    assert root.startswith("gda-editor-")
    assert not (temp / root).exists()
    assert list(stand_in.iterdir()) == []


@pytest.mark.e2e
def test_a_timed_out_scan_is_launch_timeout_and_its_root_is_removed(tmp_path):
    project = _dir_spy_project(tmp_path / "p")
    temp, stand_in, markers, env = _dirs_env(tmp_path)
    gda = Gda(project, timeout=300, extra_env={**env, "GDA_TEST_WEDGE": "1"})

    run = gda("project", "scan", "--timeout", "10", "--json")

    assert run.returncode == 124, run.stdout + run.stderr
    error = json.loads(run.stdout)["error"]
    assert error["code"] == "launch_timeout"
    assert error["message"].startswith(f"{TIMEOUT_LABEL} launched but did not return")
    assert "SPY WEDGED" in error["diagnostics"]
    assert all(
        directory.is_relative_to(temp.resolve()) for directory in _editor_dirs(markers)
    )
    assert list(temp.glob("gda-editor-*")) == []
    assert list(stand_in.iterdir()) == []


@pytest.mark.e2e
def test_a_user_data_root_receives_the_editor_directories_and_is_kept(tmp_path):
    project = _dir_spy_project(tmp_path / "p")
    temp, stand_in, markers, env = _dirs_env(tmp_path)
    root = tmp_path / "kept"
    gda = Gda(project, json_output=True, timeout=300, extra_env=env)

    gda.json("--user-data-root", str(root), "project", "scan")

    assert all(
        directory.is_relative_to(root.resolve()) for directory in _editor_dirs(markers)
    )
    assert list(root.rglob("editor_settings-*.tres")) != []
    assert list(temp.glob("gda-editor-*")) == []
    assert list(stand_in.iterdir()) == []
