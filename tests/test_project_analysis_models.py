"""S2: the project static-analysis result models (issue #116).

The four read-only project-wide analysis commands — find-references,
dependencies, find-unused-resources, statistics — each carry their result in a
typed model (ADR-0004), so the same model backs ``--json`` and ``--schema``.
These unit tests validate each model from the dict shape its operation emits
through the sentinel, exactly as the existing model tests do.
"""

import json

import jsonschema

from gda.models import (
    ProjectDependenciesResult,
    ProjectFindReferencesResult,
    ProjectFindUnusedResourcesResult,
    ProjectStatisticsResult,
)


def test_find_references_validates_from_operation_payload():
    payload = {
        "target": "res://hero.gd",
        "references": [
            {
                "path": "res://main.tscn",
                "kind": "ext_resource",
                "context": 'res://main.tscn type="Script"',
            },
            {
                "path": "res://enemy.gd",
                "kind": "preload",
                "context": 'preload("res://hero.gd")',
            },
        ],
    }

    result = ProjectFindReferencesResult.model_validate(payload)

    assert result.target == "res://hero.gd"
    assert len(result.references) == 2
    assert result.references[0].path == "res://main.tscn"
    assert result.references[0].kind == "ext_resource"
    assert result.references[1].kind == "preload"


def test_find_references_empty_is_a_valid_result_not_a_failure():
    # A target nothing references is a valid, empty result.
    result = ProjectFindReferencesResult.model_validate(
        {"target": "res://orphan.gd", "references": []}
    )
    assert result.references == []


def test_dependencies_validates_from_operation_payload():
    payload = {
        "dependencies": [
            {
                "path": "res://main.tscn",
                "depends_on": [
                    {"path": "res://hero.tscn", "kind": "ext_resource"},
                    {"path": "res://icon.png", "kind": "ext_resource"},
                ],
            },
            {"path": "res://hero.tscn", "depends_on": []},
        ]
    }

    result = ProjectDependenciesResult.model_validate(payload)

    assert len(result.dependencies) == 2
    main = result.dependencies[0]
    assert main.path == "res://main.tscn"
    assert [d.path for d in main.depends_on] == ["res://hero.tscn", "res://icon.png"]
    assert result.dependencies[1].depends_on == []


def test_find_unused_resources_validates_from_operation_payload():
    payload = {
        "unused": [
            "res://unused_sprite.png",
            "res://orphan.tres",
        ]
    }

    result = ProjectFindUnusedResourcesResult.model_validate(payload)

    assert result.unused == ["res://unused_sprite.png", "res://orphan.tres"]


def test_statistics_validates_from_operation_payload():
    payload = {
        "total_files": 12,
        "total_lines": 340,
        "by_extension": [
            {"extension": "gd", "files": 4, "lines": 300},
            {"extension": "tscn", "files": 3, "lines": 40},
        ],
        "autoloads": [
            {"name": "GameState", "path": "res://game_state.gd"},
        ],
        "plugins": ["res://addons/my_plugin/plugin.cfg"],
        "scene_count": 3,
        "script_count": 4,
        "resource_count": 5,
    }

    result = ProjectStatisticsResult.model_validate(payload)

    assert result.total_files == 12
    assert result.total_lines == 340
    assert result.by_extension[0].extension == "gd"
    assert result.by_extension[0].files == 4
    assert result.autoloads[0].name == "GameState"
    assert result.autoloads[0].path == "res://game_state.gd"
    assert result.plugins == ["res://addons/my_plugin/plugin.cfg"]
    assert result.scene_count == 3


def test_all_four_models_round_trip_to_json_objects():
    # Each model serializes to a JSON object that re-validates — the --json
    # contract round-trips.
    refs = ProjectFindReferencesResult(target="res://a.gd", references=[])
    deps = ProjectDependenciesResult(dependencies=[])
    unused = ProjectFindUnusedResourcesResult(unused=[])
    stats = ProjectStatisticsResult(
        total_files=0,
        total_lines=0,
        by_extension=[],
        autoloads=[],
        plugins=[],
        scene_count=0,
        script_count=0,
        resource_count=0,
    )
    for model in (refs, deps, unused, stats):
        assert json.loads(model.model_dump_json()) == model.model_dump()


def test_emitted_schemas_are_valid_json_schema():
    for model in (
        ProjectFindReferencesResult,
        ProjectDependenciesResult,
        ProjectFindUnusedResourcesResult,
        ProjectStatisticsResult,
    ):
        jsonschema.Draft202012Validator.check_schema(model.model_json_schema())
