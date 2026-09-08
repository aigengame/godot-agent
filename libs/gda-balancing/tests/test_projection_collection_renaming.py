"""Projection collection labels are references, while their sources remain typed."""

from copy import deepcopy
from pathlib import Path

import pytest

from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _reidentify_package_release,
)
from schema2_bootstrap_production_support import _consumer_a, _reidentify_graph_root
from test_bounded_fold_public import (
    _admit_artifacts,
    _build,
    _check,
    _run,
    _source,
    _specification,
)
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
)


def _projection(language):
    return next(
        definition["runtime_projection"]
        for package in language["language"]["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.model_lowerings"
        for definition in closure["definitions"]
    )


def _seal(language):
    for package in language["language"]["packages"]:
        _reidentify_package_release(package)
    _reidentify_graph_root(language)


def _rename_collections(projection):
    # Change only declared labels and their four existing reference positions.
    names = {
        row["id"]: f"opaque.collection.{index}"
        for index, row in enumerate(projection["collections"])
    }
    assert len(names) == 16
    for row in projection["collections"]:
        row["id"] = names[row["id"]]
    for seed in projection["seeds"]:
        seed["collection"] = names[seed["collection"]]
    for edge in projection["edges"]:
        for member in ("source_collection", "target_collection"):
            edge[member] = names[edge[member]]
    for member in (
        "source_collection",
        "target_type_collection",
        "target_constructor_collection",
    ):
        closure = projection["type_reference_closure"]
        closure[member] = names[closure[member]]
    roots = projection["operation_roots"]
    roots["collection"] = names[roots["collection"]]
    return names


def test_all_projection_collection_labels_can_change_through_public_execution(
    tmp_path: Path,
):
    observations = []
    for renamed in (False, True):
        kernel, language = mutable_authorities()
        projection = _projection(language)
        if renamed:
            original = deepcopy(projection)
            names = _rename_collections(projection)
            assert set(names).isdisjoint(names.values())
            assert [row["source"] for row in projection["collections"]] == [
                row["source"] for row in original["collections"]
            ]
            _seal(language)
        for consumer in (_consumer_a, _consumer_b):
            result = consumer(kernel, language)
            assert result["admitted"], result["diagnostics"]
        independent = _reference_check_source(_source(), kernel, language)
        assert isinstance(independent, ModelSourceContext), independent
        expected = _reference_semantic_artifacts(independent)
        public = _PublicCandidate(
            tmp_path / ("renamed" if renamed else "control"),
            authorities=(kernel, language),
        )
        locator, rir = _build(public)
        assert rir == expected["rir-semantic-payload"]
        specification = _specification(rir, [1, 2, 3, 4])
        path, _ = _check(public, locator, specification)
        members = _members(_run(public, locator, path))
        _admit_artifacts(public, rir, specification, members)
        event = next(
            row
            for row in members["event-trace"]["events"]
            if row["observation"] is None
        )
        state = {row["name"]: row["value"] for row in event["state_after"]}
        assert state["selected_count"] == 2
        assert state["ordered_value"] == 1234
        assert state["selected_items"]["value"] == [1, 2]
        terminal = members["snapshot-series"]["snapshots"][-1]
        assert terminal["continuation"]["resource_ledger"]["node_steps"] == 46
        observations.append((rir, members))
    # All complete execution artifacts, including identities, stay equal: labels
    # alter compilation metadata, not selected meaning or any observed behavior.
    assert observations[0] == observations[1]


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("source_collection", "missing"),
        ("target_type_collection", "missing"),
        ("target_constructor_collection", "missing"),
        ("source_collection", "operations"),
        ("target_type_collection", "capability_bindings"),
        ("target_constructor_collection", "nominal_types"),
        ("source_collection", 1),
        ("target_type_collection", []),
        ("target_constructor_collection", None),
        ("source_definition_path", ["id"]),
        ("constructor_kind_path", ["value_rule", "kind"]),
        ("coordinate_members", ["id", "package"]),
        ("structural_kind_member", "id"),
        ("unexpected", "member"),
    ],
)
def test_type_reference_closure_rejects_wrong_references_and_paths(member, value):
    kernel, language = mutable_authorities()
    _projection(language)["type_reference_closure"][member] = value
    _seal(language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"], (member, value)
        assert result["diagnostics"]


@pytest.mark.parametrize(
    "defect", ["duplicate", "wrong-source", "wrong-package-path", "missing"]
)
def test_type_reference_closure_checks_actual_collection_definitions(defect):
    kernel, language = mutable_authorities()
    projection = _projection(language)
    rows = projection["collections"]
    if defect == "duplicate":
        rows.append(deepcopy(next(row for row in rows if row["id"] == "nominal_types")))
    elif defect == "wrong-source":
        row = next(row for row in rows if row["id"] == "nominal_types")
        row["source"]["authority_path"] = "language.operations"
    elif defect == "wrong-package-path":
        row = next(row for row in rows if row["id"] == "types")
        row["source"]["package_path"] = ["id"]
    else:
        del projection["type_reference_closure"]["target_type_collection"]
    _seal(language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"], defect
        assert result["diagnostics"]
