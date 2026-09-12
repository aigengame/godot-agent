"""The five fixed Model binding containers have a single Kernel owner."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from test_template_wire_structure import _definitions
from test_trace_protocol_structure import _authored, _graph


MODEL_ROLES = (
    "build-receipt",
    "resolution-receipt",
    "resolved-model",
    "model-build-command-input",
    "debug-map",
)


def _model_rows(authored, role):
    definition = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == role
    )
    contract = next(
        row
        for row in _definitions(authored, "language.artifact_contracts")
        if row["schema_kind"] == definition["artifact_kind"]
    )
    return definition, contract


@pytest.mark.parametrize("role", MODEL_ROLES)
def test_model_binding_schema_has_no_authored_owner(role):
    _, ldb = mutable_authorities()
    definition, _ = _model_rows(_authored(ldb), role)
    assert set(definition) == {"artifact_kind", "protocol_role"}


@pytest.fixture(scope="module")
def model_pair(tmp_path_factory):
    from gda_balancing.domain.model import check_model_source, compile_checked_model
    from gda_balancing.domain.model._resolution import (
        CheckedModel,
        ModelSourceContext,
        _RESOLVER_IMPLEMENTATION_IDENTITY,
    )
    from gda_balancing.domain.model._lowering import _LOWERER_IMPLEMENTATION_IDENTITY
    from gda_balancing.domain.artifacts import _identified_artifact
    from schema2_model_companions_independent_support import (
        reference_model_artifacts,
        reference_model_producer,
    )
    from test_schema2_model_lowerer_conformance import (
        _source,
        _symbol,
        _reference_check_source,
    )

    kernel, ldb = mutable_authorities()
    source = _source([_symbol("amount", "constant"), _symbol("stored", "state")])
    path = tmp_path_factory.mktemp("model-owners") / "source.json"
    path.write_text(json.dumps(source))
    checked = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, ldb)
    assert isinstance(checked, CheckedModel) and isinstance(
        reference, ModelSourceContext
    )
    produced = compile_checked_model(checked)
    produced["model-build-command-input"] = _identified_artifact(
        ldb,
        "model-build-command-input",
        {
            "source_identity": checked.source_identity,
            "kernel_identity": kernel["content_identity"],
            "language_bundle_identity": ldb["content_identity"],
        },
    )
    provenance = {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "resolver": _RESOLVER_IMPLEMENTATION_IDENTITY,
    }
    independent_provenance = reference_model_producer()
    independent = reference_model_artifacts(reference, producer=independent_provenance)
    return checked, reference, produced, independent, provenance, independent_provenance


@pytest.mark.parametrize("role", MODEL_ROLES)
def test_model_schema_is_independently_derived_and_preserves_original_wire(
    role, monkeypatch
):
    from gda_balancing.domain.authority.model_projection import model_protocol_schema
    from schema2_bootstrap_conformance_support import _consumer_b_model_schema
    from gda_balancing.domain.canonical import canonical_bytes

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _, contract = _model_rows(authored, role)
    a = model_protocol_schema(kernel, role, contract["artifact_kind"])
    b = _consumer_b_model_schema(kernel, role, contract["artifact_kind"])
    assert a == b
    assert hashlib.sha256(canonical_bytes(a)).hexdigest() == SCHEMA_DIGESTS[role]
    before = _encoded(authored)
    graph = _graph(kernel, authored)
    assert _consumer_a(kernel, graph)["admitted"]
    import gda_balancing.domain.authority.model_projection as projection

    monkeypatch.setattr(
        projection,
        "model_protocol_schema",
        lambda *args: pytest.fail("B called A projection"),
    )
    assert _consumer_b(kernel, graph)["admitted"]
    assert _encoded(authored) == before


@pytest.mark.parametrize("role", MODEL_ROLES)
@pytest.mark.parametrize(
    "rename", [False, True], ids=["exact-shadow", "binding-rename"]
)
def test_model_outer_override_refuses_after_truthful_reseal(role, rename):
    from gda_balancing.domain.artifacts import select_protocol_artifact_contract

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    definition, _ = _model_rows(authored, role)
    schema = deepcopy(select_protocol_artifact_contract(ldb, role).schema)
    member = "kernel_identity" if role == "resolved-model" else "source_identity"
    if rename:
        schema["properties"]["hidden_binding"] = schema["properties"].pop(member)
        schema["required"] = [
            "hidden_binding" if field == member else field
            for field in schema["required"]
        ]
    definition["schema"] = schema
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, _graph(kernel, authored))
        assert not result["admitted"], result
        assert result["diagnostics"][0][0] == "static", result


@pytest.mark.parametrize("role", MODEL_ROLES)
def test_independent_members_preserve_true_producer_and_all_bindings(model_pair, role):
    from gda_balancing.domain.artifacts import verify_artifact
    from schema2_model_companions_independent_support import (
        reference_admits_model_artifacts,
        reference_model_artifacts,
    )
    from gda_balancing.domain.model import validate_compiled_artifacts

    checked, reference, a, b, producer_a, producer_b = model_pair
    assert producer_a != producer_b
    assert reference_admits_model_artifacts(a, reference, producer=producer_a)
    assert reference_admits_model_artifacts(b, reference, producer=producer_b)
    assert reference_model_artifacts(reference, producer=producer_a)[role] == a[role]
    assert verify_artifact(b[role], checked.language_bundle)
    if role not in {"build-receipt", "resolution-receipt"}:
        assert a[role] == b[role]
    validate_compiled_artifacts(
        {k: v for k, v in a.items() if k != "model-build-command-input"},
        checked.source_identity,
        checked.authority_context,
    )
    with pytest.raises(RuntimeError, match="build receipt has invalid bindings"):
        validate_compiled_artifacts(
            {k: v for k, v in b.items() if k != "model-build-command-input"},
            checked.source_identity,
            checked.authority_context,
        )


_BINDING_MUTATIONS = (
    [
        ("build-receipt", field)
        for field in (
            "source_identity",
            "kernel_identity",
            "language_bundle_identity",
            "package_lock_identity",
            "rir_identity",
            "resolved_model_identity",
            "capability_manifest_identity",
            "debug_map_identity",
            "model_explanation_identity",
            "resolution_receipt_identity",
            "compiler",
        )
    ]
    + [
        ("resolution-receipt", field)
        for field in (
            "source_identity",
            "kernel_identity",
            "language_bundle_identity",
            "package_lock_identity",
            "resolution_profile",
            "resolver",
        )
    ]
    + [
        ("resolved-model", field)
        for field in (
            "kernel_identity",
            "language_bundle_identity",
            "package_lock_identity",
            "rir_content_identity",
            "rir_semantic_identity",
        )
    ]
    + [("debug-map", field) for field in ("source_identity", "rir_identity")]
    + [
        ("model-build-command-input", field)
        for field in ("source_identity", "kernel_identity", "language_bundle_identity")
    ]
)


@pytest.mark.parametrize(("role", "member"), _BINDING_MUTATIONS)
def test_resealed_model_binding_changes_refuse_independent_consumption(
    model_pair, role, member
):
    from gda_balancing.domain.artifacts import _identified_artifact, verify_artifact
    from schema2_model_companions_independent_support import (
        reference_admits_model_artifacts,
    )

    checked, reference, original, _, producer, _ = model_pair
    candidate = deepcopy(original)
    value = candidate[role]
    payload = {
        key: item
        for key, item in value.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    payload[member] = "wrong.actual.binding"
    candidate[role] = _identified_artifact(checked.language_bundle, role, payload)
    assert verify_artifact(candidate[role], checked.language_bundle)
    assert not reference_admits_model_artifacts(candidate, reference, producer=producer)
    if role == "model-build-command-input":
        from gda_balancing.domain.model import model_build_command_input_identity
        from gda_balancing.domain.publication import _require_matching_command_input
        from gda_balancing.domain.publication_types import PublicationError

        with pytest.raises(PublicationError, match="different canonical input"):
            _require_matching_command_input(
                {"command_input_identity": candidate[role]["content_identity"]},
                model_build_command_input_identity(checked),
            )
    else:
        from gda_balancing.domain.model import validate_compiled_artifacts

        with pytest.raises(RuntimeError):
            validate_compiled_artifacts(
                {
                    key: value
                    for key, value in candidate.items()
                    if key != "model-build-command-input"
                },
                checked.source_identity,
                checked.authority_context,
            )


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "wrong-source", "wrong-rir", "coordinated"]
)
def test_debug_pointer_forgery_refuses_even_with_resealed_companions(
    model_pair, mutation
):
    from gda_balancing.domain.artifacts import _identified_artifact, verify_artifact
    from schema2_model_companions_independent_support import (
        reference_admits_model_artifacts,
    )

    checked, reference, original, _, producer, _ = model_pair
    candidate = deepcopy(original)
    entries = candidate["debug-map"]["entries"]
    if mutation == "missing":
        entries.pop()
    elif mutation == "duplicate":
        entries.append(deepcopy(entries[0]))
    elif mutation == "wrong-rir":
        entries[0]["rir_pointer"] = "/declarations/999"
    else:
        entries[0]["source_pointer"] = "/modules/999/symbols/999"
    for role in ("debug-map", "model-explanation", "build-receipt"):
        if mutation == "coordinated":
            if role in {"model-explanation", "build-receipt"}:
                candidate[role]["debug_map_identity"] = candidate["debug-map"][
                    "content_identity"
                ]
            if role == "build-receipt":
                candidate[role]["model_explanation_identity"] = candidate[
                    "model-explanation"
                ]["content_identity"]
        payload = {
            key: item
            for key, item in candidate[role].items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
        candidate[role] = _identified_artifact(checked.language_bundle, role, payload)
        assert verify_artifact(candidate[role], checked.language_bundle)
    assert not reference_admits_model_artifacts(candidate, reference, producer=producer)


def test_model_inventory_retires_only_the_five_physical_schema_gaps():
    from schema2_extension_inventory_support import (
        read_extension_inventory,
        validate_extension_inventory,
    )

    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    original = _encoded(graph)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert _encoded(graph) == original
    assert len(inventory.uncovered) == 2
    assert {gap.pointer for gap in inventory.uncovered} == REMAINING_GAPS


# Exact original wire digests captured before physical deletion at 609823cab.
SCHEMA_DIGESTS = {
    "build-receipt": "2e3012452d7958e7c086a6c86649f930a9d2dca7fc2d3a6b51fa48317235bfe5",
    "debug-map": "bf3dd75d73fa87e1c2ccaade945ad0d9f6cf24fefa14345c149705b294d2f458",
    "model-build-command-input": "dc42d52112df3d6b3748a4af49bf53a9c4bee9186619d34d35d05fb949bb9435",
    "resolution-receipt": "efdcf248af29bbb1d224b5f80d43945d0c1cc967ced41fa98a3a413b0b478c71",
    "resolved-model": "058903b2865693f3314454ad66a8e9fab830e75cc80db9d4dc7293e2cfe791ce",
}

REMAINING_GAPS = {
    "/vector_sets",
    "/packages/12/semantic_closure/25/definitions/0",
}


@pytest.mark.parametrize("role", MODEL_ROLES)
@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_model_protocol_role_binding_is_total(role, mutation):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    definition, _ = _model_rows(authored, role)
    if mutation == "missing":
        del definition["protocol_role"]
    else:
        other, _ = _model_rows(
            authored, "debug-map" if role != "debug-map" else "resolved-model"
        )
        other["protocol_role"] = role
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, _graph(kernel, authored))
        assert not result["admitted"], result


@pytest.mark.parametrize(
    "rename", [False, True], ids=["original", "schema-kind-and-source-addresses"]
)
def test_public_eight_member_build_and_inspect_with_independent_companions(
    tmp_path, rename
):
    from gda_balancing.domain.artifacts import (
        artifacts_by_protocol_role,
        verify_artifact,
    )
    from gda_balancing.domain.authority.context import (
        admit_authority_context,
        AdmittedAuthorityContext,
    )
    from schema2_model_companions_independent_support import (
        reference_admits_model_artifacts,
        reference_model_artifacts,
    )
    from test_schema2_model_lowerer_conformance import (
        _reference_check_source,
        ModelSourceContext,
    )
    from test_current_namespace_public import _PublicCandidate, _members
    from test_source_fact_selector_inventory import _scoped_rename
    from schema2_extension_inventory_support import read_extension_inventory
    from test_trace_protocol_structure import _index

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    authored["source"] = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/progression-periodic-effect/model-source.json"
        ).read_text()
    )
    if rename:
        # The authority positions are closed independently of the still-open
        # Formula Source inventory. Transport these two actual Source keys
        # explicitly; this witness does not claim whole-graph bijection.
        source = authored.pop("source")
        inventory = read_extension_inventory(kernel, authored)
        names = {
            token: {"modules": "source/modules~", "symbols": "source/symbols~"}[
                token.name
            ]
            for token in inventory.tokens
            if token.role == "source-field" and token.name in {"modules", "symbols"}
        }
        assert {token.name for token in names} == {"modules", "symbols"}
        authored = _scoped_rename(authored, inventory, names)
        source["source/modules~"] = source.pop("modules")
        for module in source["source/modules~"]:
            module["source/symbols~"] = module.pop("symbols")
        authored["source"] = source
        for i, role in enumerate(MODEL_ROLES):
            definition, contract = _model_rows(authored, role)
            previous_schema, previous_kind = (
                definition["artifact_kind"],
                contract["artifact_kind"],
            )
            definition["artifact_kind"] = contract["schema_kind"] = (
                f"opaque.model.schema.{i}"
            )
            contract["artifact_kind"] = f"opaque.model.result.{i}"
            for package in authored["packages"]:
                for collection, old, new in (
                    (
                        "artifact_wire_schemas",
                        previous_schema,
                        definition["artifact_kind"],
                    ),
                    ("artifact_contracts", previous_kind, contract["artifact_kind"]),
                ):
                    package["exports"][collection] = [
                        new if name == old else name
                        for name in package["exports"][collection]
                    ]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    public = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    public.write_source(authored["source"])
    public.cli("model", "check", str(public.source))
    receipt = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(tmp_path / "build.json"),
        "--invocation-key",
        "71" * 32,
    )
    artifacts = artifacts_by_protocol_role(context.language_bundle, _members(receipt))
    assert len(artifacts) == 8
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text(json.dumps(receipt))
    inspected = public.cli("model", "inspect", str(receipt_file))
    assert inspected == artifacts["model-explanation"]
    reference = _reference_check_source(
        authored["source"], kernel, context.language_bundle
    )
    assert isinstance(reference, ModelSourceContext), reference
    producer = {
        "compiler": artifacts["build-receipt"]["compiler"],
        "resolver": artifacts["resolution-receipt"]["resolver"],
    }
    independently_derived = reference_model_artifacts(reference, producer=producer)
    assert all(
        independently_derived[role] == actual for role, actual in artifacts.items()
    )
    artifacts["model-build-command-input"] = independently_derived[
        "model-build-command-input"
    ]
    assert reference_admits_model_artifacts(artifacts, reference, producer=producer)
    assert all(
        verify_artifact(value, context.language_bundle)
        for value in independently_derived.values()
    )
    debug = artifacts["debug-map"]
    assert debug["entries"]
    assert artifacts["model-explanation"]["formula_explanations"]
    if rename:
        assert all(
            row["source_pointer"].startswith("/source~1modules~0/")
            for row in debug["entries"]
        )
    # Actual publication index retains the independently derived request binding.
    index = json.loads(
        next((tmp_path / "store").rglob("publication-index.json")).read_text()
    )
    assert (
        index["command_input_identity"]
        == independently_derived["model-build-command-input"]["content_identity"]
    )


def test_reference_companions_do_not_call_the_production_compiler(
    model_pair, monkeypatch
):
    import gda_balancing.domain.model._compilation as production
    from schema2_model_companions_independent_support import reference_model_artifacts

    _, reference, _, expected, _, producer = model_pair

    def forbidden(*args, **kwargs):
        pytest.fail("independent companion derivation called production")

    for name in ("lower_checked_model", "_model_explanation", "_capability_manifest"):
        monkeypatch.setattr(production, name, forbidden)
    assert reference_model_artifacts(reference, producer=producer) == expected
