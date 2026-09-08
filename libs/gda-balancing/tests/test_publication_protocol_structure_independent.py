"""Independent publication grammar follows the fixed three-part Kernel owner."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

import pytest

from gda_balancing.domain.artifacts import select_artifact_contract
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_project_publication_schema,
    _consumer_b_publication_bindings,
    _consumer_b_publication_schema,
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
from test_publication_protocol_structure import _BASELINE_SCHEMAS, _rename_publication
from test_receipt_protocol_structure_independent import _publication_roundtrip
from test_rir_protocol_structure_independent import _raw_language
from test_trace_protocol_structure import _authored, _graph


def test_publication_schema_parts_have_one_owner_and_independent_detached_views(
    monkeypatch,
):
    kernel, index = mutable_authorities()
    raw = _graph(kernel, _authored(index))
    language = _raw_language(raw)
    bindings = _consumer_b_publication_bindings(language)
    prior_bytes_minus_retired_markers = {
        "artifact-set-manifest": (
            811,
            "78a9e455a25f28a17e89de7b5355a82c15f94d69af3d072b8c610dc13282e662",
        ),
        "artifact-set-receipt": (
            950,
            "53908bd786b6daf916cd5f8ad2838626fb9413699869d00657a6d6bb45604c38",
        ),
        "publication-index": (
            693,
            "d99f55eb0c27d59be8a4b8ea2ac697e34400cad76a7fd35c9e3991aa5681190f",
        ),
    }
    original_kernel = _encoded(kernel)
    original_graph = _encoded(_authored(raw))
    for role, (schema, binding) in bindings.items():
        assert "schema" not in schema
        generated = _consumer_b_publication_schema(
            kernel, role, binding["artifact_kind"]
        )
        actual = next(
            row["schema"]
            for row in index["language"]["artifact_wire_schemas"]
            if row.get("protocol_role") == role
        )
        assert _encoded(generated) == _encoded(actual)
        assert (
            len(_encoded(generated)),
            hashlib.sha256(_encoded(generated)).hexdigest(),
        ) == prior_bytes_minus_retired_markers[role]
        assert _identity(
            binding["wire_schema_identity_domain"], generated
        ) == _identity(binding["wire_schema_identity_domain"], actual)
        generated["required"].append("caller-mutation")
        if role == "artifact-set-manifest":
            generated["properties"]["members"]["items"]["required"].append(
                "nested-mutation"
            )
    assert _encoded(kernel) == original_kernel
    assert _encoded(_authored(raw)) == original_graph

    def unavailable(*_args, **_kwargs):
        raise AssertionError("Consumer B called A's publication Schema projector")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.publication_projection.publication_protocol_schema",
        unavailable,
    )
    admitted = _consumer_b(kernel, raw)
    assert admitted["admitted"], admitted["diagnostics"]
    _consumer_b_project_publication_schema(kernel, language)
    assert all("schema" in schema for schema, _binding in bindings.values())
    assert _encoded(_authored(raw)) == original_graph


@pytest.mark.parametrize(
    "role,member,renamed",
    [
        ("artifact-set-manifest", "members", "framed_members"),
        ("publication-index", "receipt_identity", "published_receipt_identity"),
    ],
)
@pytest.mark.parametrize(
    "change_address", [False, True], ids=["old-placement", "formerly-admitted-rename"]
)
def test_publication_structure_reentry_refuses_on_correctly_resealed_raw_graph(
    role, member, renamed, change_address
):
    kernel, index = mutable_authorities()
    authored = _authored(index)
    schema = next(
        row
        for package in authored["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.artifact_wire_schemas"
        for row in entry["definitions"]
        if row.get("protocol_role") == role
    )
    schema["schema"] = deepcopy(_BASELINE_SCHEMAS[role])
    if change_address:
        schema["schema"]["properties"][renamed] = schema["schema"]["properties"].pop(
            member
        )
        schema["schema"]["required"] = [
            renamed if name == member else name for name in schema["schema"]["required"]
        ]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"]
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


@pytest.mark.parametrize("role", ["artifact-set-manifest", "publication-index"])
@pytest.mark.parametrize(
    "mutation",
    ["missing-role", "duplicate-role", "missing-binding", "duplicate-binding"],
)
def test_publication_projection_requires_each_actual_unique_role_binding(
    role, mutation
):
    kernel, index = mutable_authorities()
    language = _raw_language(index)
    schema, binding = _consumer_b_publication_bindings(language)[role]
    if mutation == "missing-role":
        language["artifact_wire_schemas"].remove(schema)
    elif mutation == "duplicate-role":
        language["artifact_wire_schemas"].append(deepcopy(schema))
    elif mutation == "missing-binding":
        language["artifact_contracts"].remove(binding)
    else:
        language["artifact_contracts"].append(deepcopy(binding))
    before = _encoded(language)
    with pytest.raises(ValueError):
        _consumer_b_project_publication_schema(kernel, language)
    assert _encoded(language) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-part",
        "extra-part",
        "missing-field",
        "unknown-field-type",
        "duplicate-owner",
    ],
)
def test_publication_projection_does_not_publish_partial_malformed_law_views(mutation):
    kernel, index = mutable_authorities()
    language = _raw_language(index)
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "publication_structure"
    ]
    if mutation == "missing-part":
        del law["index"]
    elif mutation == "extra-part":
        law["extra"] = deepcopy(law["index"])
    elif mutation == "missing-field":
        del law["manifest"]["field_types"]["members"]
    elif mutation == "unknown-field-type":
        law["manifest"]["field_types"]["members"] = {"type": "unknown-protocol-type"}
    else:
        law["index"]["field_types"]["artifact_kind"] = {"type": "non-empty-string"}
    before = _encoded(language)
    with pytest.raises((KeyError, ValueError)):
        _consumer_b_project_publication_schema(kernel, language)
    assert _encoded(language) == before


@pytest.mark.parametrize("role", ["artifact-set-manifest", "publication-index"])
def test_publication_inventory_removes_only_generated_schema_occurrences(role):
    kernel, index = mutable_authorities()
    graph = _authored(index)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    schema, binding = _consumer_b_publication_bindings(_raw_language(index))[role]
    token = AuthorityToken(
        "language.artifact_wire_schemas", (), schema["artifact_kind"]
    )
    producer = AuthorityToken(
        "language.artifact_contracts", (), binding["artifact_kind"]
    )
    declaration = next(
        o for o in inventory.occurrences if o.token == token and o.use == "declaration"
    )
    pointer = declaration.pointer.rsplit("/", 1)[0]
    assert not any(gap.pointer == pointer for gap in inventory.uncovered)
    assert not any(
        o.pointer.startswith(pointer + "/schema/") for o in inventory.occurrences
    )
    assert {token, producer} <= inventory.tokens - inventory.reserved
    link = next(
        o
        for o in inventory.occurrences
        if o.token == token and o.pointer.endswith("/schema_kind")
    )
    for changed in [None, replace(link, token=producer)]:
        occurrences = tuple(o for o in inventory.occurrences if o != link)
        if changed is not None:
            occurrences += (changed,)
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(
                kernel, graph, replace(inventory, occurrences=occurrences)
            )


def test_distinct_publication_names_and_opaque_labels_preserve_independent_consumption(
    tmp_path, monkeypatch
):
    public, index = _publication_roundtrip(
        tmp_path, monkeypatch, rename=_rename_publication
    )
    bindings = _consumer_b_publication_bindings(_raw_language(public.ldb))
    observations = []
    for log in public.receipts:
        if log["arguments"][:2] != ("model", "build"):
            continue
        receipt = json.loads(log["stdout"])
        manifest_path = Path(receipt["manifest_locator"])
        actual = {
            "artifact-set-receipt": receipt,
            "artifact-set-manifest": json.loads(manifest_path.read_text()),
            "publication-index": json.loads(
                (manifest_path.parent / "publication-index.json").read_text()
            ),
        }
        for role, value in actual.items():
            schema_row, binding = bindings[role]
            assert schema_row["artifact_kind"] != binding["artifact_kind"]
            schema = _consumer_b_publication_schema(
                public.kernel, role, binding["artifact_kind"]
            )
            selected = select_artifact_contract(index, binding["artifact_kind"])
            Draft202012Validator(schema).validate(value)
            assert value["artifact_kind"] == binding["artifact_kind"]
            assert value["wire_schema_identity"] == _identity(
                binding["wire_schema_identity_domain"], schema
            )
            transport = (
                public.kernel["meta_format"]["language_definitions"][
                    "wire_schema_protocol_roles"
                ]["publication_structure"]["receipt"]["transport"]
                if role == "artifact-set-receipt"
                else {}
            )
            identity_body = {
                name: child for name, child in value.items() if name not in transport
            }
            assert value["content_identity"] == _identity(
                binding["identity_domain"], identity_body
            )
            assert selected.verify(value)
            marker = {
                "artifact-set-manifest": "frame",
                "publication-index": "adapter",
            }.get(role)
            if marker is not None:
                assert marker not in value
                legacy_value = _BASELINE_SCHEMAS[role]["properties"][marker].get(
                    "const", "local-filesystem-directory-rename-v1"
                )
                legacy = {**value, marker: legacy_value}
                errors = list(Draft202012Validator(schema).iter_errors(legacy))
                assert [(list(error.path), error.validator) for error in errors] == [
                    ([], "unevaluatedProperties")
                ]
            observations.append(
                {
                    "role": role,
                    "schema_kind": schema_row["artifact_kind"],
                    "artifact_kind": binding["artifact_kind"],
                    "schema_sha256": hashlib.sha256(_encoded(schema)).hexdigest(),
                    "wire_schema_identity": value["wire_schema_identity"],
                    "content_identity": value["content_identity"],
                }
            )
        assert (
            actual["artifact-set-receipt"]["manifest_identity"]
            == actual["artifact-set-manifest"]["content_identity"]
        )
        assert (
            actual["publication-index"]["receipt_identity"]
            == actual["artifact-set-receipt"]["content_identity"]
        )
    assert len(observations) == 3
    (public.directory / "independent-publication-comparison.json").write_text(
        json.dumps(observations, indent=2) + "\n"
    )
