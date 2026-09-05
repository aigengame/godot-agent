"""S3: gda project static-analysis reads against a fake runner (issue #116).

The project analysis group — find-references, dependencies,
find-unused-resources, statistics — are read-only, project-wide reads backed by
a single static scan, all headless. These tests drive the same proven pipeline
as the scene/node/script groups — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json


from tests.support import (
    DEPENDENCIES_RESULT,
    FIND_REFERENCES_RESULT,
    STATISTICS_RESULT,
    UNUSED_RESULT,
    invoke_cli,
    sentinel,
)


def test_dependencies_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["project", "dependencies", "--json"],
        stdout=sentinel(DEPENDENCIES_RESULT),
        stderr="engine diagnostic\n",
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["dependencies"][0]["path"] == "res://main.tscn"
    assert data["dependencies"][0]["depends_on"][0]["path"] == "res://hero.tscn"
    # dependencies takes no operation params — the project is process context.
    assert fake.calls == [("project-dependencies", {})]
    assert "engine diagnostic" in result.stderr


def test_dependencies_human_output_lists_each_scene_and_its_deps(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch, ["project", "dependencies"], stdout=sentinel(DEPENDENCIES_RESULT)
    )

    assert result.exit_code == 0
    assert "res://main.tscn" in result.stdout
    assert "res://hero.tscn" in result.stdout


def test_find_references_passes_target_param(monkeypatch):
    stdout = sentinel(FIND_REFERENCES_RESULT)
    result, fake = invoke_cli(
        monkeypatch,
        ["project", "find-references", "res://hero.gd", "--json"],
        stdout=stdout,
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["target"] == "res://hero.gd"
    assert data["references"][0]["path"] == "res://hero.tscn"
    assert data["references"][0]["kind"] == "ext_resource"
    # The target rides through as the one operation param.
    assert fake.calls == [("project-find-references", {"target": "res://hero.gd"})]


def test_find_references_normalizes_filesystem_target_but_not_res_path(monkeypatch):
    # A res:// virtual path passes through untouched (the engine resolves it);
    # a class_name target (no '://') is left as-is too, not treated as a file.
    result, fake = invoke_cli(
        monkeypatch,
        ["project", "find-references", "Hero", "--json"],
        stdout=sentinel({"target": "Hero", "references": []}),
    )

    assert result.exit_code == 0
    assert fake.calls == [("project-find-references", {"target": "Hero"})]


def test_find_unused_resources_json(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["project", "find-unused-resources", "--json"],
        stdout=sentinel(UNUSED_RESULT),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["unused"] == ["res://orphan.png", "res://orphan.tres"]
    assert fake.calls == [("project-find-unused-resources", {})]


def test_statistics_json(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["project", "statistics", "--json"],
        stdout=sentinel(STATISTICS_RESULT),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total_files"] == 5
    assert data["autoloads"][0]["name"] == "GameState"
    assert data["plugins"] == ["res://addons/widget/plugin.cfg"]
    assert fake.calls == [("project-statistics", {})]


def test_statistics_human_output_summarizes_counts(monkeypatch):
    result, _ = invoke_cli(
        monkeypatch, ["project", "statistics"], stdout=sentinel(STATISTICS_RESULT)
    )

    assert result.exit_code == 0
    assert "5" in result.stdout  # total files
    assert "GameState" in result.stdout
