"""E2E: `gda project scan` owns the engine class index in a headless workflow (#1073).

A project the editor never opened has no `.godot/global_script_class_cache.cfg`.
The GDScript analyzer finds a project `class_name` only through that index, so a
script typed with a project class does not compile until an editor filesystem
scan has run. `gda project scan` runs the engine import pass, which is that scan.
Run e2e SERIALLY; not a fresh empty HOME.
"""

import base64

import pytest

from gda.import_evidence import CACHE_ROOT_REL
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
