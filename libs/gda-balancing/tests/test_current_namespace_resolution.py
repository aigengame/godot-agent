"""Current namespace closure without historical package-version selection."""

from __future__ import annotations

import json
from itertools import combinations, permutations, product
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import (
    CurrentPackage,
    resolve_current_namespaces,
)


def _package(
    namespace: str,
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    provides: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
    definitions: tuple[tuple[str, str, Any], ...] = (),
) -> CurrentPackage:
    return CurrentPackage(
        namespace, required, optional, provides, requires, definitions
    )


@pytest.mark.parametrize("edge_mask", range(64))
def test_every_three_namespace_graph_has_order_independent_required_closure(edge_mask):
    names = ("alpha", "beta", "gamma")
    possible_edges = tuple(
        (left, right) for left in names for right in names if left != right
    )
    edges = {edge for bit, edge in enumerate(possible_edges) if edge_mask & (1 << bit)}
    packages = tuple(
        _package(
            name, required=tuple(right for left, right in sorted(edges) if left == name)
        )
        for name in names
    )

    # Boolean transitive closure is an independent oracle for the selected graph.
    reachable = {
        (left, right): (left, right) in edges for left in names for right in names
    }
    for middle in names:
        for left in names:
            for right in names:
                reachable[left, right] |= (
                    reachable[left, middle] and reachable[middle, right]
                )
    cyclic = any(reachable[name, name] for name in names)
    root_sets = (
        (names,)
        if cyclic
        else tuple(roots for size in range(1, 4) for roots in combinations(names, size))
    )

    for package_order in permutations(packages):
        for roots in root_sets:
            expected = set(roots) | {
                name for root in roots for name in names if reachable[root, name]
            }
            for root_order in permutations(roots):
                if cyclic:
                    with pytest.raises(ValueError, match="cycl"):
                        resolve_current_namespaces(package_order, root_order)
                    continue
                selected = resolve_current_namespaces(package_order, root_order)
                assert tuple(
                    package.namespace for package in selected.packages
                ) == tuple(sorted(expected))
                assert selected.dependency_edges == tuple(
                    sorted(edge for edge in edges if edge[0] in expected)
                )
                assert selected.capability_bindings == ()
                assert dict(selected.definitions) == {}


def test_diamond_closure_coalesces_shared_dependencies_and_canonicalizes_set_order():
    leaf = _package("leaf", provides=("read", "write"))
    other = _package("other")
    auxiliary = _package("auxiliary")
    unused = _package("unused", provides=("read", "write"))
    left = _package("left", required=("leaf",))
    right = _package("right", required=("leaf",))
    baseline = None
    for required, optional, provided, needed in product(
        permutations(("left", "right")),
        permutations(("other", "auxiliary")),
        permutations(("root.read", "root.write")),
        permutations(("read", "write")),
    ):
        root = _package(
            "root",
            required=required,
            optional=optional,
            provides=provided,
            requires=needed,
        )
        selected = resolve_current_namespaces(
            (unused, other, right, root, auxiliary, leaf, left),
            (name for name in ("root", "root")),
        )
        assert tuple(package.namespace for package in selected.packages) == (
            "leaf",
            "left",
            "right",
            "root",
        )
        assert selected.dependency_edges == (
            ("left", "leaf"),
            ("right", "leaf"),
            ("root", "left"),
            ("root", "right"),
        )
        assert selected.capability_bindings == (
            ("read", "leaf"),
            ("root.read", "root"),
            ("root.write", "root"),
            ("write", "leaf"),
        )
        if baseline is None:
            baseline = selected
        else:
            assert selected == baseline


@pytest.mark.parametrize("missing", ("root", "required", "optional"))
def test_missing_namespace_is_refused_at_the_declared_boundary(missing):
    packages = (
        _package(
            "root",
            required=("absent",) if missing == "required" else (),
            optional=("absent",) if missing == "optional" else (),
        ),
    )
    roots = ("absent",) if missing == "root" else ("root",)
    with pytest.raises(ValueError, match="absent"):
        resolve_current_namespaces(packages, roots)


def test_available_optional_namespace_is_never_automatically_selected():
    packages = (_package("root", optional=("optional",)), _package("optional"))
    selected = resolve_current_namespaces(packages, ("root",))
    assert tuple(package.namespace for package in selected.packages) == ("root",)
    assert selected.packages[0].optional == ("optional",)
    assert selected.dependency_edges == ()
    both = resolve_current_namespaces(packages, ("root", "optional"))
    assert tuple(package.namespace for package in both.packages) == ("optional", "root")
    assert both.dependency_edges == ()


@pytest.mark.parametrize(
    ("required", "optional"),
    ((("leaf", "leaf"), ()), ((), ("leaf", "leaf")), (("leaf",), ("leaf",))),
    ids=("required", "optional", "required-and-optional"),
)
def test_duplicate_dependency_declarations_are_refused(required, optional):
    with pytest.raises(ValueError, match="duplicate"):
        resolve_current_namespaces(
            (_package("root", required=required, optional=optional), _package("leaf")),
            ("root",),
        )


@pytest.mark.parametrize(
    "packages",
    (
        (_package("root", required=("root",)),),
        (_package("root", required=("child",)), _package("child", required=("root",))),
    ),
    ids=("self", "indirect"),
)
def test_required_cycles_refuse_instead_of_returning_a_partial_selection(packages):
    with pytest.raises(ValueError, match="cycl"):
        resolve_current_namespaces(packages, ("root",))


def test_unselected_required_cycle_still_breaks_graph_closure():
    packages = (
        _package("root"),
        _package("left", required=("right",)),
        _package("right", required=("left",)),
    )
    with pytest.raises(ValueError, match="cycl"):
        resolve_current_namespaces(packages, ("root",))


def test_optional_edges_do_not_create_required_cycles():
    packages = (
        _package("root", optional=("child",)),
        _package("child", optional=("root",)),
    )
    selected = resolve_current_namespaces(packages, ("root",))
    assert tuple(package.namespace for package in selected.packages) == ("root",)
    assert selected.dependency_edges == ()


@pytest.mark.parametrize("selected_duplicate", (False, True))
def test_equal_duplicate_namespace_records_are_never_silently_coalesced(
    selected_duplicate,
):
    duplicate = _package("duplicate")
    with pytest.raises(ValueError, match="duplicate"):
        resolve_current_namespaces(
            (_package("root"), duplicate, duplicate),
            ("duplicate",) if selected_duplicate else ("root",),
        )


def test_capability_provider_must_be_in_the_selected_required_closure():
    requester = _package("requester", requires=("calculate",))
    provider = _package("provider", provides=("calculate",))
    with pytest.raises(ValueError, match="calculate"):
        resolve_current_namespaces((requester, provider), ("requester",))
    selected = resolve_current_namespaces(
        (requester, provider), ("requester", "provider")
    )
    assert selected.capability_bindings == (("calculate", "provider"),)
    assert selected.dependency_edges == ()


def test_selected_capability_ambiguity_is_refused_and_unselected_providers_are_ignored():
    packages = (
        _package("requester", required=("chosen",), requires=("calculate",)),
        _package("chosen", provides=("calculate",)),
        _package("alternative", provides=("calculate",)),
    )
    for order in permutations(packages):
        selected = resolve_current_namespaces(order, ("requester",))
        assert selected.capability_bindings == (("calculate", "chosen"),)
        with pytest.raises(ValueError, match="calculate"):
            resolve_current_namespaces(order, ("requester", "alternative"))


def test_equal_nominal_definitions_keep_namespace_and_collection_identity():
    shape = {"kind": "record", "fields": []}
    packages = (
        _package("alpha", definitions=(("language.nominal_types", "Shared", shape),)),
        _package(
            "beta",
            definitions=(
                ("language.nominal_types", "Shared", shape),
                ("language.operations", "Shared", shape),
            ),
        ),
    )
    selected = resolve_current_namespaces(packages, ("beta", "alpha"))
    assert set(selected.definitions) == {
        ("alpha", "language.nominal_types", "Shared"),
        ("beta", "language.nominal_types", "Shared"),
        ("beta", "language.operations", "Shared"),
    }
    assert all(value == shape for value in selected.definitions.values())


@pytest.mark.parametrize("equal_payload", (False, True))
def test_duplicate_definition_owner_refuses_even_when_payloads_are_equal(equal_payload):
    first = {"kind": "record", "fields": []}
    second = first if equal_payload else {"kind": "scalar"}
    duplicate = _package(
        "owner",
        definitions=(
            ("language.nominal_types", "Shared", first),
            ("language.nominal_types", "Shared", second),
        ),
    )
    with pytest.raises(ValueError, match="duplicate"):
        resolve_current_namespaces((duplicate,), ("owner",))


def test_definition_and_operation_body_order_remains_authored_order():
    body = [{"node": "copy", "target": "z"}, {"node": "copy", "target": "a"}]
    definitions = (
        ("language.operations", "z-operation", {"body": body}),
        ("language.operations", "a-operation", {"body": list(reversed(body))}),
    )
    selected = resolve_current_namespaces(
        (_package("owner", definitions=definitions),), ("owner",)
    )
    assert [name for _path, name, _value in selected.packages[0].definitions] == [
        "z-operation",
        "a-operation",
    ]
    assert set(selected.definitions) == {
        ("owner", "language.operations", "z-operation"),
        ("owner", "language.operations", "a-operation"),
    }
    assert (
        selected.definitions["owner", "language.operations", "z-operation"]["body"]
        == body
    )
    assert selected.definitions["owner", "language.operations", "a-operation"][
        "body"
    ] == list(reversed(body))


_CURRENT_REQUIRED = {
    "core.quantity": {"standard.compiler"},
    "game.build": {
        "core.quantity",
        "game.generation",
        "standard.runtime",
        "standard.schema",
    },
    "game.check": {"core.quantity", "standard.runtime"},
    "game.combat": {"core.quantity", "game.check", "game.resource", "standard.runtime"},
    "game.effect": {"core.quantity", "standard.runtime"},
    "game.generation": {"core.quantity", "standard.runtime", "standard.schema"},
    "game.progression": {"core.quantity"},
    "game.resource": {"core.quantity", "standard.runtime"},
    "standard.compiler": set(),
    "standard.conformance.structured": {
        "core.quantity",
        "standard.runtime",
        "standard.schema",
    },
    "standard.experiment": set(),
    "standard.runtime": set(),
    "standard.schema": set(),
}


@pytest.mark.parametrize(
    ("example", "expected_namespaces"),
    (
        (
            "progression-periodic-effect",
            {
                "core.quantity",
                "game.effect",
                "game.progression",
                "standard.compiler",
                "standard.runtime",
            },
        ),
        (
            "roguelike-reward-build",
            {
                "core.quantity",
                "game.build",
                "game.generation",
                "standard.compiler",
                "standard.runtime",
                "standard.schema",
            },
        ),
        (
            "rpg-combat-cast",
            {
                "core.quantity",
                "game.check",
                "game.combat",
                "game.resource",
                "standard.compiler",
                "standard.runtime",
            },
        ),
        (
            "rpg-periodic-effect",
            {
                "core.quantity",
                "game.check",
                "game.combat",
                "game.effect",
                "game.resource",
                "standard.compiler",
                "standard.runtime",
            },
        ),
        (
            "rpg-stat-composition",
            {
                "core.quantity",
                "game.build",
                "game.check",
                "game.combat",
                "game.effect",
                "game.generation",
                "game.progression",
                "game.resource",
                "standard.compiler",
                "standard.runtime",
                "standard.schema",
            },
        ),
        (
            "structured-selection",
            {
                "core.quantity",
                "standard.compiler",
                "standard.conformance.structured",
                "standard.runtime",
                "standard.schema",
            },
        ),
    ),
)
def test_maintained_sources_resolve_the_expected_current_namespace_closure(
    example, expected_namespaces
):
    context = packaged_authority_context()
    packages = context.current_namespace_packages()
    assert {
        package.namespace: set(package.required) for package in packages
    } == _CURRENT_REQUIRED
    source_path = (
        Path(__file__).parents[1]
        / "examples"
        / "schema2"
        / example
        / "model-source.json"
    )
    source = json.loads(source_path.read_text(encoding="utf-8"))
    roots = [requirement["id"] for requirement in source["package_requirements"]]

    selected = resolve_current_namespaces(packages, roots)

    assert {package.namespace for package in selected.packages} == expected_namespaces
    assert set(selected.dependency_edges) == {
        (namespace, dependency)
        for namespace in expected_namespaces
        for dependency in _CURRENT_REQUIRED[namespace]
    }
    assert dict(selected.capability_bindings)["quantity.lower"] == "core.quantity"
    if "standard.schema" in expected_namespaces:
        assert (
            dict(selected.capability_bindings)["structured.lower"] == "standard.schema"
        )


def test_current_projection_retains_complete_operations_and_cannot_mutate_admitted_bodies():
    context = packaged_authority_context()
    original_bytes = context.canonical_language_bundle_bytes
    packages = context.current_namespace_packages()
    selected = resolve_current_namespaces(packages, ("game.build", "game.effect"))
    expected_operations = {
        "core.quantity": {
            "quantity.add",
            "quantity.floor-divide",
            "quantity.floor-zero",
            "quantity.identity",
            "quantity.less-than",
            "quantity.maximum",
            "quantity.minimum",
            "quantity.multiply",
            "quantity.subtract",
        },
        "game.build": {"game.build.contribution@1", "game.build.replace-reward-v1"},
        "game.effect": {
            "game.effect.apply-live-periodic-v1",
            "game.effect.apply-snapshot-periodic-v1",
            "game.effect.contribute@1",
            "game.effect.expire-periodic-v1",
            "game.effect.tick-live-periodic-v1",
            "game.effect.tick-snapshot-periodic-v1",
        },
    }
    for namespace, operations in expected_operations.items():
        assert {
            name
            for owner, path, name in selected.definitions
            if owner == namespace and path == "language.operations"
        } == operations
        owner = next(
            package
            for package in context.language_bundle["language"]["packages"]
            if package["id"] == namespace
        )
        authored_operations = next(
            entry["definitions"]
            for entry in owner["semantic_closure"]
            if entry["authority_path"] == "language.operations"
        )
        for operation in authored_operations:
            projected = selected.definitions[
                namespace, "language.operations", operation["id"]
            ]
            assert projected["body"] == operation["body"]

    key = ("core.quantity", "language.operations", "quantity.add")
    operation = selected.definitions[key]
    assert operation["body"][0]["node"] == "add"
    with pytest.raises(TypeError):
        cast(Any, selected.definitions)[key] = {"body": []}
    with pytest.raises(TypeError):
        cast(Any, operation)["body"][0]["node"] = "subtract"
    assert context.canonical_language_bundle_bytes == original_bytes
    fresh = resolve_current_namespaces(
        context.current_namespace_packages(), ("core.quantity",)
    )
    assert fresh.definitions[key]["body"][0]["node"] == "add"
