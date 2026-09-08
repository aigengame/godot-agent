"""Receipt bindings and transport are derived independently from the supplied Kernel."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

from jsonschema import Draft202012Validator
import pytest

from gda_balancing.application.model_build import MODEL_BUILD_ARTIFACT_SET
from gda_balancing.domain.artifact_set import (
    ProtocolArtifactSetMemberSpec,
    label_artifacts,
    resolve_artifact_set,
)
from gda_balancing.domain.artifacts import (
    artifacts_by_protocol_role,
    select_artifact_contract,
    verify_artifact,
)
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.model import admit_resolved_model
from gda_balancing.domain.model._resolution import ModelSourceContext
from gda_balancing.domain.publication import (
    PublicationMember,
    publish_artifact_set,
    read_authenticated_declared_artifact_set,
    select_publication_contracts,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_artifact_contract_declarations,
    _consumer_b_project_receipt_schema,
    _consumer_b_receipt_schema,
    _encoded,
    _identity,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    validate_extension_inventory,
)
from test_bounded_fold_public import _source
from test_current_namespace_public import _PublicCandidate, _members
from test_receipt_protocol_structure import _rename_receipt
from test_rir_protocol_structure_independent import _raw_language
from test_schema2_model_lowerer_conformance import (
    _reference_admits_semantic_artifacts,
    _reference_check_source,
    _reference_semantic_artifacts,
)
from test_trace_protocol_structure import _authored, _graph, _index


def _receipt(language):
    schema = next(
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == "artifact-set-receipt"
    )
    contract = next(
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def test_receipt_independent_schema_preserves_baseline_bytes_and_opaque_inputs(
    monkeypatch,
):
    kernel, ldb = mutable_authorities()
    raw = _graph(kernel, _authored(ldb))
    language = _raw_language(raw)
    schema, contract = _receipt(language)
    assert "schema" not in schema
    assert all(
        "identity_excluded_members" not in row for row in language["artifact_contracts"]
    )
    projected = _consumer_b_receipt_schema(kernel, contract["artifact_kind"])
    # Exact original wire bytes, captured before deletion of its authored copy.
    assert len(_encoded(projected)) == 950
    assert hashlib.sha256(_encoded(projected)).hexdigest() == (
        "53908bd786b6daf916cd5f8ad2838626fb9413699869d00657a6d6bb45604c38"
    )
    generated_a = _receipt(ldb["language"])[0]["schema"]
    assert _encoded(projected) == _encoded(generated_a)
    assert _identity(contract["wire_schema_identity_domain"], projected) == (
        select_artifact_contract(
            ldb, _receipt(ldb["language"])[1]["artifact_kind"]
        ).wire_schema_identity
    )
    assert _consumer_a(kernel, raw)["admitted"]

    def unavailable(*_args, **_kwargs):
        raise AssertionError("B consumed the production receipt projector")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.receipt_projection.receipt_protocol_schema",
        unavailable,
    )
    observation = _consumer_b(kernel, raw)
    assert observation["admitted"], observation["diagnostics"]
    before = _encoded(kernel)
    projected["required"].reverse()
    projected["properties"]["member_locators"]["items"]["required"].append("changed")
    assert _encoded(kernel) == before
    assert "schema" not in schema


@pytest.mark.parametrize(
    "mutation",
    ["schema", "locator-schema", "empty", "binding", "unknown", "other-contract"],
)
def test_receipt_independent_admission_refuses_authored_shadow_and_exclusions(mutation):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    language = _raw_language(ldb)
    schema, binding = _receipt(language)
    for package in authored["packages"]:
        for entry in package["semantic_closure"]:
            if entry["authority_path"] == "language.artifact_wire_schemas":
                target = next(
                    (
                        row
                        for row in entry["definitions"]
                        if row.get("protocol_role") == "artifact-set-receipt"
                    ),
                    None,
                )
                if target is not None and mutation in {"schema", "locator-schema"}:
                    target["schema"] = _consumer_b_receipt_schema(
                        kernel, binding["artifact_kind"]
                    )
                    if mutation == "locator-schema":
                        target["schema"]["properties"]["transport_manifest"] = target[
                            "schema"
                        ]["properties"].pop("manifest_locator")
                        required = target["schema"]["required"]
                        required[required.index("manifest_locator")] = (
                            "transport_manifest"
                        )
            if entry["authority_path"] == "language.artifact_contracts":
                for target in entry["definitions"]:
                    selected = target["schema_kind"] == schema["artifact_kind"]
                    if selected and mutation in {"empty", "binding", "unknown"}:
                        target["identity_excluded_members"] = {
                            "empty": [],
                            "binding": ["descriptor_identity"],
                            "unknown": ["missing"],
                        }[mutation]
                    elif not selected and mutation == "other-contract":
                        target["identity_excluded_members"] = []
    raw = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, raw)
        assert not observation["admitted"]
        assert observation["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


@pytest.mark.parametrize(
    "mutation",
    ["missing-role", "duplicate-role", "missing-binding", "duplicate-binding"],
)
def test_receipt_independent_projection_requires_unique_actual_binding(mutation):
    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    schema, binding = _receipt(language)
    if mutation == "missing-role":
        language["artifact_wire_schemas"].remove(schema)
    elif mutation == "duplicate-role":
        language["artifact_wire_schemas"].append(deepcopy(schema))
    elif mutation == "missing-binding":
        language["artifact_contracts"].remove(binding)
    else:
        language["artifact_contracts"].append(deepcopy(binding))
    with pytest.raises(ValueError):
        _consumer_b_project_receipt_schema(kernel, language)


def test_receipt_binding_hashes_and_transport_relocation_follow_actual_law():
    kernel, ldb = mutable_authorities()
    selected = select_artifact_contract(
        ldb, _receipt(ldb["language"])[1]["artifact_kind"]
    )
    language = _raw_language(ldb)
    schema, binding = _receipt(language)
    schema["artifact_kind"] = binding["schema_kind"] = "receipt.schema.renamed"
    binding["artifact_kind"] = "receipt.artifact.renamed"
    _consumer_b_project_receipt_schema(kernel, language)
    assert schema["schema"]["properties"]["artifact_kind"] == {
        "const": binding["artifact_kind"]
    }
    declarations = _consumer_b_artifact_contract_declarations(
        kernel["meta_format"], language
    )
    assert all("identity_excluded_members" not in row for row in declarations)
    declarations[0]["artifact_kind"] = "caller-mutation"
    assert language["artifact_contracts"][0]["artifact_kind"] != "caller-mutation"
    binding["identity_excluded_members"].append("descriptor_identity")
    with pytest.raises(ValueError):
        _consumer_b_artifact_contract_declarations(kernel["meta_format"], language)

    payload = {
        "descriptor_identity": "descriptor-A",
        "invocation_key": "invocation-A",
        "manifest_identity": "manifest-A",
        "manifest_locator": "file:first-manifest",
        "member_locators": [
            {"logical_name": "opaque-label", "locator": "file:first-member"}
        ],
    }
    artifact = selected.identify(payload)
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "receipt_structure"
    ]
    independent_body = {
        name: value for name, value in artifact.items() if name not in law["transport"]
    }
    assert artifact["content_identity"] == _identity(
        selected.definition["identity_domain"], independent_body
    )
    for field in law["bindings"]:
        altered = deepcopy(payload)
        altered[field] += "-changed"
        assert (
            selected.identify(altered)["content_identity"]
            != artifact["content_identity"]
        )
    relocated = deepcopy(payload)
    relocated["manifest_locator"] = "file:second-manifest"
    relocated["member_locators"][0]["locator"] = "file:second-member"
    assert (
        selected.identify(relocated)["content_identity"] == artifact["content_identity"]
    )
    malformed = deepcopy(artifact)
    malformed["member_locators"] = []
    artifact_kind = artifact["artifact_kind"]
    assert isinstance(artifact_kind, str)
    errors = list(
        Draft202012Validator(
            _consumer_b_receipt_schema(kernel, artifact_kind)
        ).iter_errors(malformed)
    )
    assert [(list(error.path), error.validator) for error in errors] == [
        (["member_locators"], "minItems")
    ]


@pytest.mark.parametrize("corruption", ["omitted", "wrong-owner"])
def test_receipt_inventory_keeps_binding_tokens_without_authored_schema_ghosts(
    corruption,
):
    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    schema, binding = _receipt(_raw_language(ldb))
    schema_token = AuthorityToken(
        "language.artifact_wire_schemas", (), schema["artifact_kind"]
    )
    producer_token = AuthorityToken(
        "language.artifact_contracts", (), binding["artifact_kind"]
    )
    assert {schema_token, producer_token} <= set(inventory.tokens)
    occurrence = next(
        row
        for row in inventory.occurrences
        if row.token == schema_token and row.pointer.endswith("/schema_kind")
    )
    assert not any(
        gap.pointer
        == occurrence.pointer.rsplit("/", 1)[0] + "/identity_excluded_members"
        for gap in inventory.uncovered
    )
    for row in inventory.occurrences:
        if row.token == producer_token:
            assert "/schema/" not in row.pointer
    altered = replace(
        inventory,
        occurrences=tuple(row for row in inventory.occurrences if row != occurrence)
        + (
            (replace(occurrence, token=replace(schema_token, owner=("wrong-owner",))),)
            if corruption == "wrong-owner"
            else ()
        ),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, altered)


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "distinct-kinds"])
def test_receipt_renamed_public_build_and_labels_are_consumed_independently(
    tmp_path, monkeypatch, renamed
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    if renamed:
        _rename_receipt(authored)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert observation["admitted"], observation["diagnostics"]
    index = _index(kernel, graph)
    context = admit_authority_context(kernel, index)
    assert isinstance(context, AdmittedAuthorityContext), context
    schema_row, binding = _receipt(_raw_language(graph))
    schema_b = _consumer_b_receipt_schema(kernel, binding["artifact_kind"])
    selected = select_artifact_contract(index, binding["artifact_kind"])
    assert _encoded(schema_b) == _encoded(_receipt(index["language"])[0]["schema"])
    assert (
        _identity(binding["wire_schema_identity_domain"], schema_b)
        == selected.wire_schema_identity
    )
    if renamed:
        assert schema_row["artifact_kind"] != binding["artifact_kind"]
        inventory = read_extension_inventory(kernel, authored)
        validate_extension_inventory(kernel, authored, inventory)
        assert (
            AuthorityToken(
                "language.artifact_wire_schemas", (), schema_row["artifact_kind"]
            )
            in inventory.tokens - inventory.reserved
        )
        assert (
            AuthorityToken("language.artifact_contracts", (), binding["artifact_kind"])
            in inventory.tokens - inventory.reserved
        )

    source = _source()
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    receipt_a = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "d2" * 32,
    )
    built = artifacts_by_protocol_role(index, _members(receipt_a))
    assert len(built) == 8
    reference_checked = _reference_check_source(source, kernel, index)
    assert isinstance(reference_checked, ModelSourceContext), reference_checked
    reference = _reference_semantic_artifacts(reference_checked)
    assert all(
        _encoded(built[role]) == _encoded(value) for role, value in reference.items()
    )
    assert _reference_admits_semantic_artifacts(built, reference_checked)
    assert all(verify_artifact(value, index) for value in reference.values())
    assert admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted

    transport = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["receipt_structure"]["transport"]

    def reconstructed_receipt(value):
        Draft202012Validator(schema_b).validate(value)
        assert value["wire_schema_identity"] == _identity(
            binding["wire_schema_identity_domain"], schema_b
        )
        body = {
            name: child for name, child in value.items() if name != "content_identity"
        }
        reconstructed = {
            **body,
            "content_identity": _identity(
                binding["identity_domain"],
                {name: child for name, child in body.items() if name not in transport},
            ),
        }
        assert _encoded(reconstructed) == _encoded(value)
        assert selected.verify(reconstructed)
        return reconstructed

    receipt_b = reconstructed_receipt(receipt_a)
    receipt_path = public.directory / "independent-receipt.json"
    receipt_path.write_text(json.dumps(receipt_b))
    public.cli("model", "inspect", str(receipt_path))

    # Caller-chosen labels follow the same actual publication plan mechanism as
    # the existing protocol-label witness; neither Schema kind nor data spelling
    # is used to select a member's protocol responsibility.
    plan = tuple(
        ProtocolArtifactSetMemberSpec(
            member.protocol_role,
            logical_name=f"opaque-{23 - offset * 3}",
            role=member.role,
        )
        for offset, member in enumerate(MODEL_BUILD_ARTIFACT_SET)
    )
    resolved = resolve_artifact_set(index, plan)
    values = label_artifacts(built, resolved, lambda value: value["artifact_kind"])
    members = {
        label: PublicationMember(
            value=value,
            artifact_kind=value["artifact_kind"],
            wire_schema_identity=value["wire_schema_identity"],
            content_identity=value["content_identity"],
        )
        for label, value in values.items()
    }
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", public.env["GDA_BALANCING_STORE_DIR"])
    monkeypatch.setenv(
        "GDA_BALANCING_ANCHOR_KEY", public.env["GDA_BALANCING_ANCHOR_KEY"]
    )
    relabeled = publish_artifact_set(
        members,
        str(public.directory / "relabeled"),
        "d3" * 32,
        receipt_a["descriptor_identity"],
        reference_checked.source_identity,
        select_publication_contracts(index),
        resolved,
        lambda _name, value: verify_artifact(value, index),
        artifact_set_validator=lambda rows: _reference_admits_semantic_artifacts(
            artifacts_by_protocol_role(index, rows), reference_checked
        ),
    )
    receipt_path.write_text(json.dumps(reconstructed_receipt(relabeled)))
    restored = read_authenticated_declared_artifact_set(
        str(receipt_path), (MODEL_BUILD_ARTIFACT_SET,), authority_context=context
    )
    assert restored.artifacts == values
    locators = relabeled["member_locators"]
    assert isinstance(locators, list)
    assert all(isinstance(row, dict) for row in locators)
    assert [row["logical_name"] for row in locators if isinstance(row, dict)] == [
        member.logical_name for member in plan
    ]
    public.cli("model", "inspect", str(receipt_path))
    (public.directory / "independent-comparison.json").write_text(
        json.dumps(
            {
                "schema_bytes": len(_encoded(schema_b)),
                "schema_sha256": hashlib.sha256(_encoded(schema_b)).hexdigest(),
                "schema_kind": schema_row["artifact_kind"],
                "artifact_kind": binding["artifact_kind"],
                "wire_schema_identity": selected.wire_schema_identity,
                "receipt_identity": receipt_b["content_identity"],
                "relabeled_receipt_identity": relabeled["content_identity"],
                "four_artifact_identities": {
                    role: value["content_identity"] for role, value in reference.items()
                },
                "labels": [member.logical_name for member in plan],
            },
            indent=2,
        )
        + "\n"
    )
