"""Lock transport shape delegates semantic content to exact Authority admission."""

from copy import deepcopy
import json
from pathlib import Path

import jsonschema

import pytest

from gda_balancing.domain.artifacts import _identified_artifact, verify_artifact
from gda_balancing.domain.canonical import content_identity
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _consumer_b_model_schema
from schema2_bootstrap_production_support import _consumer_a
from schema2_model_companions_independent_support import (
    reference_admits_model_artifacts,
    reference_model_artifacts,
)
from test_model_protocol_structure import _model_rows
from test_trace_protocol_structure import _authored, _graph


ROLES = ("package-lock", "capability-manifest")


def _assert_owned_mutable_schema(value):
    if isinstance(value, dict):
        for name, child in list(value.items()):
            value[name] = child
            _assert_owned_mutable_schema(child)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            value[index] = child
            _assert_owned_mutable_schema(child)


@pytest.mark.parametrize("role", ROLES)
def test_namespace_schema_has_only_its_kernel_owner(role, monkeypatch):
    from gda_balancing.domain.authority.model_projection import model_protocol_schema

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    definition, contract = _model_rows(authored, role)
    assert set(definition) == {"artifact_kind", "protocol_role"}
    a = model_protocol_schema(kernel, role, contract["artifact_kind"])
    assert a == _consumer_b_model_schema(kernel, role, contract["artifact_kind"])
    from gda_balancing.domain.authority.context import packaged_authority_context

    frozen = packaged_authority_context().kernel
    for project in (model_protocol_schema, _consumer_b_model_schema):
        _assert_owned_mutable_schema(project(frozen, role, contract["artifact_kind"]))
    assert (
        a["properties"]["operations"]["items"]["properties"]["definition"][
            "properties"
        ]["extensions"]
        == {}
    )
    if role == "package-lock":
        entries = a["properties"]["package_semantic_closures"]["items"]["properties"][
            "definitions"
        ]["items"]["oneOf"]
        assert all("items" in entry["properties"]["definitions"] for entry in entries)
    monkeypatch.setattr(
        "gda_balancing.domain.authority.model_projection.model_protocol_schema",
        lambda *args: pytest.fail("B called A's Model Schema projector"),
    )
    assert _consumer_b(kernel, _graph(kernel, authored))["admitted"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("mutation", ("shadow", "omitted-role", "duplicate-role"))
def test_namespace_authored_override_and_missing_owners_refuse(role, mutation):
    from gda_balancing.domain.artifacts import select_protocol_artifact_contract

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    definition, _ = _model_rows(authored, role)
    if mutation == "shadow":
        definition["schema"] = deepcopy(
            select_protocol_artifact_contract(ldb, role).schema
        )
    elif mutation == "omitted-role":
        del definition["protocol_role"]
    else:
        other, _ = _model_rows(authored, "debug-map")
        other["protocol_role"] = role
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, _graph(kernel, authored))
        assert not result["admitted"], result


@pytest.fixture(scope="module")
def namespace_pair(tmp_path_factory):
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source,
        compile_checked_model,
    )
    from test_schema2_model_lowerer_conformance import (
        _reference_check_source,
        _source,
        _symbol,
        ModelSourceContext,
    )

    kernel, ldb = mutable_authorities()
    source = _source([_symbol("amount", "constant")])
    source["package_requirements"] += ["standard.schema", "game.effect"]
    path = tmp_path_factory.mktemp("model-namespace") / "source.json"
    path.write_text(json.dumps(source))
    checked = check_model_source(str(path))
    assert isinstance(checked, CheckedModel), checked
    reference = _reference_check_source(source, kernel, ldb)
    assert isinstance(reference, ModelSourceContext), reference
    original = compile_checked_model(checked)
    original["model-build-command-input"] = _identified_artifact(
        ldb,
        "model-build-command-input",
        {
            "source_identity": checked.source_identity,
            "kernel_identity": kernel["content_identity"],
            "language_bundle_identity": ldb["content_identity"],
        },
    )
    producer = {
        "compiler": original["build-receipt"]["compiler"],
        "resolver": original["resolution-receipt"]["resolver"],
    }
    assert reference_model_artifacts(reference, producer=producer) == original
    return checked, reference, original, producer


def _reseal_companions(candidate, ldb):
    lock = candidate["package-lock"]
    for name in lock["selected_semantics"]:
        if name == "packages":
            lock["selected_semantics"][name] = [
                {field: row[field] for field in ("id", "semantic_identity")}
                for row in lock[name]
            ]
        else:
            lock["selected_semantics"][name] = deepcopy(lock[name])
    lock["semantic_identity"] = content_identity(
        "package-lock-selected-semantics-v2", lock["selected_semantics"]
    )

    def seal(role):
        value = candidate[role]
        candidate[role] = _identified_artifact(
            ldb,
            role,
            {
                key: child
                for key, child in value.items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            },
        )

    seal("package-lock")
    for role in ("resolved-model", "resolution-receipt", "capability-manifest"):
        candidate[role]["package_lock_identity"] = candidate["package-lock"][
            "content_identity"
        ]
        if role == "capability-manifest":
            candidate[role]["resolved_model_identity"] = candidate["resolved-model"][
                "content_identity"
            ]
            for member in (
                "types",
                "components",
                "conversions",
                "operations",
                "numeric_profiles",
                "runtime_profiles",
            ):
                candidate[role][member] = deepcopy(lock[member])
        seal(role)
    for field, role in (
        ("package_lock_identity", "package-lock"),
        ("resolved_model_identity", "resolved-model"),
        ("resolution_receipt_identity", "resolution-receipt"),
        ("capability_manifest_identity", "capability-manifest"),
    ):
        candidate["build-receipt"][field] = candidate[role]["content_identity"]
    seal("build-receipt")


@pytest.mark.parametrize(
    "mutation",
    (
        "added-extension",
        "changed-extension",
        "schema-body",
        "closure-definition",
        "operation-owner",
        "missing-operation",
        "duplicate-operation",
        "wrong-profile",
    ),
)
def test_coordinated_namespace_forgeries_reach_and_fail_both_semantic_consumers(
    namespace_pair, mutation
):
    from gda_balancing.domain.model import validate_compiled_artifacts

    checked, reference, original, producer = namespace_pair
    candidate = deepcopy(original)
    lock = candidate["package-lock"]
    if mutation in {"added-extension", "changed-extension"}:
        operation = next(
            row["definition"]
            for row in lock["operations"]
            if row["definition"].get("extensions")
        )
        if mutation == "added-extension":
            operation["extensions"]["not-in-the-actual-authority"] = {"value": 7}
        else:
            operation["extensions"][next(iter(operation["extensions"]))] = {
                "altered": True
            }
    elif mutation in {"schema-body", "closure-definition"}:
        entries = [
            entry
            for package in lock["package_semantic_closures"]
            for entry in package["definitions"]
        ]
        if mutation == "schema-body":
            definition = next(
                definition
                for entry in entries
                if entry["authority_path"] == "language.artifact_wire_schemas"
                for definition in entry["definitions"]
                if "schema" in definition
            )
            definition["schema"]["properties"]["content_identity"] = {"type": "integer"}
        else:
            definition = next(
                definition
                for entry in entries
                if entry["authority_path"] == "language.operations"
                for definition in entry["definitions"]
            )
            definition["extensions"] = {"copied-but-unowned": [1, 2, 3]}
    elif mutation == "operation-owner":
        lock["operations"][0]["package"] = "standard.schema"
    elif mutation == "missing-operation":
        lock["operations"].pop()
    elif mutation == "duplicate-operation":
        lock["operations"].append(deepcopy(lock["operations"][0]))
    else:
        lock["resolution_profile"]["id"] = "not-the-selected-profile"
    _reseal_companions(candidate, checked.language_bundle)
    # No framing, digest or stale companion mismatch can explain these refusals.
    assert all(
        verify_artifact(value, checked.language_bundle) for value in candidate.values()
    )
    assert not reference_admits_model_artifacts(candidate, reference, producer=producer)
    with pytest.raises(RuntimeError):
        validate_compiled_artifacts(
            {
                role: value
                for role, value in candidate.items()
                if role != "model-build-command-input"
            },
            checked.source_identity,
            checked.authority_context,
        )


def test_runtime_profile_has_no_retired_extension_shape(namespace_pair):
    checked, _, original, _ = namespace_pair
    value = deepcopy(original["package-lock"])
    value["runtime_profiles"][0]["extensions"] = {"retired": True}
    with pytest.raises(jsonschema.ValidationError):
        value = _identified_artifact(
            checked.language_bundle,
            "package-lock",
            {
                key: child
                for key, child in value.items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            },
        )


def test_namespace_inventory_removes_only_lock_and_capability_schema_rows():
    from schema2_extension_inventory_support import (
        read_extension_inventory,
        validate_extension_inventory,
    )
    from test_model_protocol_structure import REMAINING_GAPS

    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    before = deepcopy(graph)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert graph == before
    assert len(inventory.uncovered) == 2
    assert {row.pointer for row in inventory.uncovered} == REMAINING_GAPS


@pytest.mark.parametrize(
    "model",
    (
        "bounded-fold",
        "progression-periodic-effect",
        "roguelike-reward-build",
        "rpg-combat-cast",
        "rpg-periodic-effect",
        "rpg-stat-composition",
        "structured-selection",
    ),
)
def test_maintained_models_have_independent_namespace_companions(model):
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source,
        compile_checked_model,
    )
    from test_schema2_model_lowerer_conformance import (
        _reference_check_source,
        ModelSourceContext,
    )

    path = Path(__file__).parents[1] / "examples/schema2" / model / "model-source.json"
    checked = check_model_source(str(path))
    assert isinstance(checked, CheckedModel), checked
    reference = _reference_check_source(
        json.loads(path.read_bytes()), checked.kernel, checked.language_bundle
    )
    assert isinstance(reference, ModelSourceContext), reference
    actual = compile_checked_model(checked)
    producer = {
        "compiler": actual["build-receipt"]["compiler"],
        "resolver": actual["resolution-receipt"]["resolver"],
    }
    independent = reference_model_artifacts(reference, producer=producer)
    assert len(actual) == 8
    assert all(value == independent[role] for role, value in actual.items())


def test_namespace_binding_rename_runs_public_build_and_inspect(tmp_path, monkeypatch):
    import test_model_protocol_structure as model_protocol

    # Reuse the complete public Model gate with this slice's two real bindings.
    monkeypatch.setattr(model_protocol, "MODEL_ROLES", ROLES)
    model_protocol.test_public_eight_member_build_and_inspect_with_independent_companions(
        tmp_path, True
    )
