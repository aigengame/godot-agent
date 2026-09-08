"""Interpreted Operation relations own selectors and canonical projection copies."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.graph import (
    LanguageBundleGraph,
    derive_language_index,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import AdmittedRir, admit_rir
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    TokenOccurrence,
    _child,
    _pointer_value,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
)
from schema2_extension_renaming_support import (
    _reseal_authored_graph,
    _rewrite_positions,
)
from test_current_namespace_public import _PublicCandidate, _members


_EXAMPLE = Path(__file__).parents[1] / "examples/schema2/progression-periodic-effect"


@pytest.fixture(scope="module")
def witness():
    kernel, language = mutable_authorities()
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert result["admitted"], result["diagnostics"]
    graph = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
        "source": json.loads((_EXAMPLE / "model-source.json").read_bytes()),
    }
    before = _encoded(graph)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert _encoded(graph) == before
    return kernel, graph, inventory


def _surfaces(kernel, graph):
    kind = next(
        row
        for row in kernel["meta_format"]["package_vector"]["kinds"]
        if row["id"] == "operation-relation"
    )
    roots = set()
    for pi, package in enumerate(graph["packages"]):
        metadata_paths = {
            policy["operation"]: policy["contract"]["path"]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == kind["policy_authority_path"]
            for definition in closure["definitions"]
            for policy in definition.get("extensions", {}).get(
                kind["policy_extension"], []
            )
        }
        for ci, closure in enumerate(package["semantic_closure"]):
            if closure["authority_path"] not in {
                "language.operations",
                kind["policy_authority_path"],
            }:
                continue
            for di, definition in enumerate(closure["definitions"]):
                extension = definition.get("extensions", {})
                pointer = (
                    f"/packages/{pi}/semantic_closure/{ci}/definitions/{di}/extensions"
                )
                if kind["declaration_extension"] in extension:
                    roots.add(_child(pointer, kind["declaration_extension"]))
                    selected = pointer.removesuffix("/extensions")
                    for member in metadata_paths[definition["id"]]:
                        selected = _child(selected, member)
                    roots.add(selected)
                if kind["policy_extension"] in extension:
                    roots.add(_child(pointer, kind["policy_extension"]))
    vectors = {
        f"/vector_sets/{vi}/vector_definitions/{di}"
        for vi, group in enumerate(graph["vector_sets"])
        for di, row in enumerate(group["vector_definitions"])
        if row.get("kind") == kind["id"]
    }
    return roots, vectors


def _authored(graph):
    return LanguageBundleGraph(
        root=graph["ldb_root"],
        package_releases=graph["packages"],
        package_conformance_vector_sets=graph["vector_sets"],
        root_byte_size=len(_encoded(graph["ldb_root"])),
        package_byte_sizes=[len(_encoded(row)) for row in graph["packages"]],
        vector_set_byte_sizes=[len(_encoded(row)) for row in graph["vector_sets"]],
    )


def _renamed(kernel, graph, inventory):
    # This is a bounded mechanical witness, not authorization of a full rename:
    # unrelated gap families remain and the public all-token API still refuses.
    names = {}
    for i, token in enumerate(sorted(inventory.tokens)):
        if token == AuthorityToken("language.capabilities", (), "game.effect.periodic"):
            names[token] = "opaque.capability"
        elif token.role == "operation-relation":
            names[token] = f"opaque.relation.{i}"
        elif token.role == "operation-extension-member":
            names[token] = {"period": "duration", "duration": "period"}.get(
                token.name, f"opaque.member.{i}"
            )
    pairs = dict(token_bijection_from_names(inventory, names))
    positions = [row for row in inventory.occurrences if row.token in names]
    assert {row.location for row in positions} == {"key", "value"}
    candidate = _rewrite_positions(
        graph,
        {row.pointer: names[row.token] for row in positions if row.location == "value"},
        {row.pointer: names[row.token] for row in positions if row.location == "key"},
    )
    _reseal_authored_graph(kernel, candidate)
    renamed_inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed_inventory)
    assert set(pairs.values()) <= renamed_inventory.tokens - renamed_inventory.reserved
    assert set(names).isdisjoint(renamed_inventory.tokens)
    return candidate


def test_relation_inventory_closes_only_actual_policy_and_projection_surfaces(witness):
    kernel, graph, inventory = witness
    surfaces, vectors = _surfaces(kernel, graph)
    assert len(surfaces) == 5  # Two metadata/declaration owners plus one policy owner.
    assert len(vectors) == 12
    assert not any(
        gap.pointer == root or gap.pointer.startswith(root + "/")
        for gap in inventory.uncovered
        for root in surfaces | vectors
    )
    assert inventory.uncovered
    assert any("Runtime profile extension" in gap.reason for gap in inventory.uncovered)
    assert any("remaining vector families" in gap.reason for gap in inventory.uncovered)
    members = [
        row
        for row in inventory.occurrences
        if row.token.role == "operation-extension-member"
    ]
    # Same member spelling in two independently authored Operations has two owners.
    assert len({row.token for row in members if row.token.name == "duration"}) == 2
    assert any("/contract/expect/" in row.pointer for row in members)
    assert any("/relations/" in row.pointer for row in members)
    assert any(
        row.pointer.startswith("/vector_sets/") and "/expect/" in row.pointer
        for row in members
    )
    assert any(
        row.pointer.startswith("/vector_sets/") and "/probe/" in row.pointer
        for row in members
    )
    assert not any("/instance/stream" in row.pointer for row in inventory.occurrences)
    assert (
        _pointer_value(
            graph,
            next(root for root in surfaces if root.endswith("game.effect.periodic")),
        )["version"]
        == "1.0.0"
    )


def _edge(inventory, selector):
    return next(row for row in inventory.occurrences if selector(row))


@pytest.mark.parametrize(
    "surface",
    [
        "metadata-key",
        "selector",
        "role",
        "policy-operation",
        "schedule-copy",
        "vector-probe",
        "vector-expect",
    ],
)
@pytest.mark.parametrize("mutation", ["erase", "misown"])
def test_relation_reverse_coverage_refuses_erased_and_misowned_edges(
    witness, surface, mutation
):
    kernel, graph, inventory = witness
    selectors = {
        "metadata-key": lambda row: (
            row.token.role == "operation-extension-member"
            and row.location == "key"
            and row.use == "declaration"
        ),
        "selector": lambda row: (
            row.token.role == "operation-extension-member"
            and row.pointer.endswith("/probe/left_path/3")
        ),
        "role": lambda row: (
            row.token.role == "operation-relation" and row.use == "declaration"
        ),
        "policy-operation": lambda row: (
            "/standard.operation-relation-policy/" in row.pointer
            and row.pointer.endswith("/operation")
        ),
        "schedule-copy": lambda row: (
            "/game.effect.periodic/schedule/" in row.pointer
            and row.token.role == "language.operations"
        ),
        "vector-probe": lambda row: (
            row.pointer.startswith("/vector_sets/")
            and "/probe/" in row.pointer
            and row.token.role == "operation-extension-member"
        ),
        "vector-expect": lambda row: (
            row.pointer.startswith("/vector_sets/")
            and "/expect/" in row.pointer
            and row.token.role == "operation-extension-member"
        ),
    }
    selected = _edge(inventory, selectors[surface])
    other = (
        next(
            token
            for token in inventory.tokens
            if token.role == selected.token.role
            and token.name == selected.token.name
            and token.owner != selected.token.owner
        )
        if selected.token.role != "language.operations"
        else replace(selected.token, owner=("wrong.owner",))
    )
    candidate = replace(
        inventory,
        occurrences=tuple(
            replace(row, token=other) if row == selected else row
            for row in inventory.occurrences
            if mutation != "erase" or row != selected
        ),
    )
    if mutation == "misown":
        candidate = replace(candidate, tokens=candidate.tokens | {other})
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, candidate)


def test_canonical_metadata_cannot_be_reclassified_by_equal_spelling(witness):
    kernel, graph, inventory = witness
    surfaces, _ = _surfaces(kernel, graph)
    pointer = (
        next(root for root in surfaces if root.endswith("game.effect.periodic"))
        + "/instance/stream"
    )
    token = AuthorityToken("named-stream", (), "effect-instance")
    assert token in inventory.tokens
    forged = TokenOccurrence(
        token, pointer, "reference", "/meta_format/runtime_program/nodes"
    )
    with pytest.raises(InventoryRefusal, match="Operation relation coverage"):
        validate_extension_inventory(
            kernel,
            graph,
            replace(inventory, occurrences=inventory.occurrences + (forged,)),
        )


@pytest.mark.parametrize(
    "defect",
    [
        "missing-selector",
        "duplicate-role",
        "wrong-policy",
        "wrong-vector",
        "broken-schedule",
        "false-duration",
    ],
)
def test_relation_refusals_survive_resealing_and_both_consumers(witness, defect):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    operation = next(
        row
        for package in candidate["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "game.effect.apply-live-periodic-v1"
    )
    declarations = operation["extensions"]["standard.operation-relations"]
    metadata = operation["extensions"]["game.effect.periodic"]
    if defect == "missing-selector":
        declarations[0]["probe"]["left_path"][-1] = "missing"
    elif defect == "duplicate-role":
        declarations[1]["id"] = declarations[0]["id"]
    elif defect == "wrong-policy":
        policy = next(
            row
            for package in candidate["packages"]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.capabilities"
            for row in closure["definitions"]
            if row["id"] == "game.effect.periodic"
        )
        policy["extensions"]["standard.operation-relation-policy"][0]["operation"] = (
            "missing"
        )
    elif defect == "wrong-vector":
        vector = next(
            row
            for group in candidate["vector_sets"]
            for row in group["vector_definitions"]
            if row.get("kind") == "operation-relation"
        )
        vector["probe"]["right_value"] = 1
    elif defect == "broken-schedule":
        metadata["schedule"][0]["operation"]["id"] = "game.effect.expire-periodic-v1"
    else:
        metadata["timing"]["duration"] = 0
    if defect in {
        "missing-selector",
        "duplicate-role",
        "broken-schedule",
        "false-duration",
    }:
        # Synchronize declared copies so refusal must detect the actual missing
        # address, duplicate role, schedule disagreement, or false integer law.
        # Numerical observations are not recalculated from a desired verdict.
        for package in candidate["packages"]:
            for closure in package["semantic_closure"]:
                if closure["authority_path"] != "language.capabilities":
                    continue
                for definition in closure["definitions"]:
                    for policy in definition.get("extensions", {}).get(
                        "standard.operation-relation-policy", []
                    ):
                        if policy["operation"] == operation["id"]:
                            policy["contract"]["expect"] = deepcopy(metadata)
                            policy["relations"] = deepcopy(declarations)
        for group in candidate["vector_sets"]:
            for vector in group["vector_definitions"]:
                if vector.get("operation") != operation["id"]:
                    continue
                if (
                    vector.get("kind") == "operation-contract"
                    and vector["probe"]["path"] == "extensions"
                ):
                    vector["expect"] = deepcopy(operation["extensions"])
                elif vector.get("kind") == "operation-relation":
                    relation = next(
                        (row for row in declarations if row["id"] == vector["role"]),
                        None,
                    )
                    if relation is not None:
                        vector["probe"] = deepcopy(relation["probe"])
    _reseal_authored_graph(kernel, candidate)
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, candidate)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, _authored(candidate))
        assert not result["admitted"], defect
        assert result["diagnostics"], defect


def test_simultaneous_relation_and_member_rename_preserves_public_periodic_execution(
    witness, tmp_path
):
    kernel, graph, inventory = witness
    before = _encoded(graph)
    candidate = _renamed(kernel, graph, inventory)
    assert _encoded(graph) == before
    assert candidate["source"] == graph["source"]
    for member, owner_key in (("packages", "id"), ("vector_sets", "package_id")):
        assert [
            row for row in candidate[member] if row[owner_key] != "game.effect"
        ] == [row for row in graph[member] if row[owner_key] != "game.effect"]
    renamed_inventory = read_extension_inventory(kernel, candidate)
    assert (
        AuthorityToken("language.capabilities", (), "opaque.capability")
        in renamed_inventory.tokens
    )
    assert all(
        token.name != "opaque.capability"
        for token in renamed_inventory.tokens
        if token.role == "operation-extension-member"
    )
    assert (
        candidate["ldb_root"]["content_identity"]
        != graph["ldb_root"]["content_identity"]
    )
    observations = []
    for label, value in (("original", graph), ("renamed", candidate)):
        authored = _authored(value)
        for consumer in (_consumer_a, _consumer_b):
            result = consumer(kernel, authored)
            assert result["admitted"], result["diagnostics"]
        index = derive_language_index(
            authored.root,
            authored.package_releases,
            authored.package_conformance_vector_sets,
            kernel["admission"]["required_language_members"],
            kernel=kernel,
            root_byte_size=authored.root_byte_size,
            package_byte_sizes=list(authored.package_byte_sizes),
            vector_set_byte_sizes=list(authored.vector_set_byte_sizes),
            descriptor_order=kernel["meta_format"]["language_bundle"][
                "package_descriptor"
            ]["canonical_order"],
        )
        context = admit_authority_context(kernel, index)
        assert isinstance(context, AdmittedAuthorityContext), context
        public = _PublicCandidate(tmp_path / label, authorities=(kernel, authored))
        public.write_source(value["source"])
        assert public.cli("model", "check", str(public.source))["checked"] is True
        build = public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(public.directory / "build"),
            "--invocation-key",
            "41" * 32,
        )
        rir = _members(build)["rir-semantic-payload"]
        locator = next(
            row["locator"]
            for row in build["member_locators"]
            if row["logical_name"] == "rir-semantic-payload"
        )
        admitted = admit_rir(rir, authority_context=context)
        assert isinstance(admitted, AdmittedRir), admitted
        specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
        specification["model"] = {"rir_semantic_identity": rir["semantic_identity"]}
        checked = check_experiment_value(
            specification, admitted, authority_context=context
        )
        assert isinstance(checked, CheckedExperiment), checked
        path = public.directory / "experiment.json"
        path.write_text(json.dumps(specification))
        assert (
            public.cli("experiment", "check", str(path), "--rir", locator)["checked"]
            is True
        )
        receipt = public.cli(
            "experiment",
            "run",
            str(path),
            "--rir",
            locator,
            "--out",
            str(public.directory / "run"),
            "--invocation-key",
            "42" * 32,
        )
        members = _members(receipt)
        assert validate_experiment_artifact_set(checked, members)
        assert members["evaluation-run"]["outcome"] == "accepted"
        events = members["event-trace"]["events"]
        transition = [
            row for row in events if row["ordering_key"]["phase"] == "transition"
        ]
        assert [
            (row["operation"], row["ordering_key"]["logical_time"])
            for row in transition
        ] == [
            ("game.effect.apply-snapshot-periodic-v1", 0),
            ("game.effect.tick-snapshot-periodic-v1", 1),
            ("game.effect.tick-snapshot-periodic-v1", 2),
            ("game.effect.expire-periodic-v1", 3),
        ]
        terminal = {row["name"]: row["value"] for row in transition[-1]["state_after"]}
        assert terminal["target_health"] == 70
        assert terminal["effect_active"] == 0
        assert terminal["effect_instance_id"] > 0
        # Compare full states at every ordered transition. Artifact identities
        # and provenance intentionally change with authored Operation metadata;
        # every complete artifact set above is admitted independently.
        observations.append(
            [(row["state_before"], row["state_after"]) for row in transition]
        )
    assert observations[0] == observations[1]
