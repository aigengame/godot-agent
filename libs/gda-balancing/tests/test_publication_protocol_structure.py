"""Publication framing is one fixed protocol, without authored shadows or markers."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from gda_balancing.domain.artifacts import select_protocol_artifact_contract
from gda_balancing.domain.authority.publication_projection import (
    publication_protocol_schema,
)
from gda_balancing.domain.canonical import canonical_bytes
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_production_support import _consumer_a
from test_bounded_fold_public import _source
from test_current_namespace_public import _PublicCandidate, _members
from test_receipt_protocol_structure import _definitions
from test_trace_protocol_structure import _authored, _graph


# Exact authored Schemas at b0605e9a, before removing their redundant markers.
# Keep these independent snapshots to preserve the admitted-but-unpublishable RED.
_BASELINE_SCHEMAS = json.loads(r"""
{
  "artifact-set-manifest": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "properties": {
      "artifact_kind": {
        "const": "artifact-set-manifest"
      },
      "artifact_version": {
        "const": "2.0.0"
      },
      "content_identity": {
        "minLength": 1,
        "type": "string"
      },
      "frame": {
        "const": "typed-logical-member-map-v1"
      },
      "members": {
        "items": {
          "properties": {
            "artifact_kind": {
              "minLength": 1,
              "type": "string"
            },
            "content_identity": {
              "minLength": 1,
              "type": "string"
            },
            "logical_name": {
              "minLength": 1,
              "type": "string"
            },
            "wire_schema_identity": {
              "minLength": 1,
              "type": "string"
            }
          },
          "required": [
            "logical_name",
            "artifact_kind",
            "wire_schema_identity",
            "content_identity"
          ],
          "type": "object",
          "unevaluatedProperties": false
        },
        "minItems": 1,
        "type": "array"
      },
      "wire_schema_identity": {
        "minLength": 1,
        "type": "string"
      }
    },
    "required": [
      "artifact_kind",
      "artifact_version",
      "wire_schema_identity",
      "frame",
      "members",
      "content_identity"
    ],
    "type": "object",
    "unevaluatedProperties": false
  },
  "publication-index": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "properties": {
      "adapter": {
        "minLength": 1,
        "type": "string"
      },
      "artifact_kind": {
        "const": "publication-index"
      },
      "artifact_version": {
        "const": "2.0.0"
      },
      "command_input_identity": {
        "minLength": 1,
        "type": "string"
      },
      "content_identity": {
        "minLength": 1,
        "type": "string"
      },
      "descriptor_identity": {
        "minLength": 1,
        "type": "string"
      },
      "invocation_key": {
        "minLength": 1,
        "type": "string"
      },
      "receipt_identity": {
        "minLength": 1,
        "type": "string"
      },
      "wire_schema_identity": {
        "minLength": 1,
        "type": "string"
      }
    },
    "required": [
      "artifact_kind",
      "artifact_version",
      "wire_schema_identity",
      "adapter",
      "descriptor_identity",
      "invocation_key",
      "command_input_identity",
      "receipt_identity",
      "content_identity"
    ],
    "type": "object",
    "unevaluatedProperties": false
  }
}
""")


def _publication_rows(authored, role):
    schema = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == role
    )
    contract = next(
        row
        for row in _definitions(authored, "language.artifact_contracts")
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def _rename_publication(authored):
    """Change actual declarations and exports, leaving protocol/data roles intact."""
    for part, role in (
        ("manifest", "artifact-set-manifest"),
        ("receipt", "artifact-set-receipt"),
        ("index", "publication-index"),
    ):
        schema, contract = _publication_rows(authored, role)
        old_schema, old_kind = schema["artifact_kind"], contract["artifact_kind"]
        schema["artifact_kind"] = f"review.{part}.schema"
        contract["schema_kind"] = schema["artifact_kind"]
        contract["artifact_kind"] = f"review.{part}.artifact"
        for package in authored["packages"]:
            for collection, old, new in (
                ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
                ("artifact_contracts", old_kind, contract["artifact_kind"]),
            ):
                package["exports"][collection] = [
                    new if value == old else value
                    for value in package["exports"][collection]
                ]


def _payload(role) -> dict[str, Any]:
    if role == "artifact-set-manifest":
        return {
            "members": [
                {
                    "logical_name": "member",
                    "artifact_kind": "member-kind",
                    "wire_schema_identity": "sha256:" + "1" * 64,
                    "content_identity": "sha256:" + "2" * 64,
                }
            ]
        }
    assert role == "publication-index"
    return {
        "descriptor_identity": "sha256:" + "3" * 64,
        "invocation_key": "4" * 64,
        "command_input_identity": "sha256:" + "5" * 64,
        "receipt_identity": "sha256:" + "6" * 64,
    }


@pytest.mark.parametrize(
    "role,marker",
    [("artifact-set-manifest", "frame"), ("publication-index", "adapter")],
)
def test_publication_keeps_exact_retained_schema_encoding_and_deletes_markers(
    role, marker
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    row, contract = _publication_rows(authored, role)
    assert "schema" not in row
    protocols = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]
    assert "receipt_structure" not in protocols
    assert set(protocols["publication_structure"]) == {"manifest", "receipt", "index"}
    expected = deepcopy(_BASELINE_SCHEMAS[role])
    del expected["properties"][marker]
    expected["required"].remove(marker)
    selected = select_protocol_artifact_contract(ldb, role)
    assert canonical_bytes(selected.schema) == canonical_bytes(expected)
    assert selected.schema == publication_protocol_schema(
        kernel, role, contract["artifact_kind"]
    )
    assert selected.definition["identity_excluded_members"] == []
    payload = _payload(role)
    current = selected.identify(payload)
    assert selected.verify(current)
    payload[marker] = "retired-marker"
    with pytest.raises(jsonschema.ValidationError):
        selected.identify(payload)


@pytest.mark.parametrize(
    "role,old,new",
    [
        ("artifact-set-manifest", "members", "framed_members"),
        ("publication-index", "receipt_identity", "published_receipt_identity"),
    ],
)
def test_original_admitted_publication_schema_rename_now_refuses_before_build(
    tmp_path, role, old, new
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    row, _ = _publication_rows(authored, role)
    row["schema"] = deepcopy(_BASELINE_SCHEMAS[role])
    schema = row["schema"]
    schema["properties"][new] = schema["properties"].pop(old)
    schema["required"] = [
        new if field == old else field for field in schema["required"]
    ]
    graph = _graph(kernel, authored)
    observation = _consumer_a(kernel, graph)
    assert observation["admitted"] is False
    assert observation["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(_source())
    output = public.directory / "build"
    refused = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(output),
        "--invocation-key",
        "e1" * 32,
        success=False,
    )
    assert public.receipts[-1]["returncode"] == 2
    assert [row["code"] for row in refused["error"]["diagnostics"]] == [
        "kernel.vector_mismatch"
    ]
    assert not output.exists()
    assert not list((public.directory / "store").rglob("artifact-set-receipt.json"))


@pytest.mark.parametrize("role", ["artifact-set-manifest", "publication-index"])
def test_even_matching_publication_schema_override_is_not_an_authored_input(role):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    schema, contract = _publication_rows(authored, role)
    schema["schema"] = publication_protocol_schema(
        kernel, role, contract["artifact_kind"]
    )
    observation = _consumer_a(kernel, _graph(kernel, authored))
    assert not observation["admitted"]
    assert observation["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-part",
        "unknown-part",
        "retired-entry",
        "missing-member",
        "unknown-type",
        "duplicate-owner",
        "duplicate-required",
    ],
)
def test_incomplete_publication_contracts_cannot_project(mutation):
    kernel, _ = mutable_authorities()
    protocols = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]
    law = protocols["publication_structure"]
    if mutation == "missing-part":
        del law["manifest"]
    elif mutation == "unknown-part":
        law["other"] = deepcopy(law["index"])
    elif mutation == "retired-entry":
        protocols["receipt_structure"] = deepcopy(law["receipt"])
    elif mutation == "missing-member":
        del law["index"]["field_types"]["receipt_identity"]
    elif mutation == "unknown-type":
        law["index"]["field_types"]["receipt_identity"]["type"] = "unknown-payload-type"
    elif mutation == "duplicate-owner":
        law["index"]["field_types"]["artifact_kind"] = {"type": "non-empty-string"}
    else:
        law["index"]["required_members"].append("receipt_identity")
    with pytest.raises(ValueError):
        publication_protocol_schema(kernel, "publication-index", "publication-index")


@pytest.mark.parametrize(
    "role,mutation",
    [
        ("artifact-set-manifest", "empty-members"),
        ("artifact-set-manifest", "missing-name"),
        ("artifact-set-manifest", "missing-kind"),
        ("artifact-set-manifest", "missing-schema"),
        ("artifact-set-manifest", "missing-content"),
        ("artifact-set-manifest", "unknown-member"),
        ("publication-index", "missing-descriptor"),
        ("publication-index", "missing-invocation"),
        ("publication-index", "missing-input"),
        ("publication-index", "missing-receipt"),
        ("publication-index", "nonstring-receipt"),
    ],
)
def test_actual_publication_payloads_preserve_closed_member_and_binding_contracts(
    role, mutation
):
    _, ldb = mutable_authorities()
    selected = select_protocol_artifact_contract(ldb, role)
    payload = _payload(role)
    if mutation == "empty-members":
        payload["members"] = []
    elif mutation == "unknown-member":
        payload["members"][0]["unowned"] = "data"
    elif mutation == "nonstring-receipt":
        payload["receipt_identity"] = 4
    else:
        name = {
            "missing-name": "logical_name",
            "missing-kind": "artifact_kind",
            "missing-schema": "wire_schema_identity",
            "missing-content": "content_identity",
            "missing-descriptor": "descriptor_identity",
            "missing-invocation": "invocation_key",
            "missing-input": "command_input_identity",
            "missing-receipt": "receipt_identity",
        }[mutation]
        del (payload["members"][0] if role == "artifact-set-manifest" else payload)[
            name
        ]
    with pytest.raises(jsonschema.ValidationError):
        selected.identify(payload)


@pytest.mark.parametrize(
    "role,member",
    [
        ("artifact-set-manifest", "logical_name"),
        ("artifact-set-manifest", "artifact_kind"),
        ("artifact-set-manifest", "wire_schema_identity"),
        ("artifact-set-manifest", "content_identity"),
        ("publication-index", "descriptor_identity"),
        ("publication-index", "invocation_key"),
        ("publication-index", "command_input_identity"),
        ("publication-index", "receipt_identity"),
    ],
)
def test_each_actual_publication_binding_contributes_to_identity(role, member):
    _, ldb = mutable_authorities()
    selected = select_protocol_artifact_contract(ldb, role)
    payload = _payload(role)
    before = selected.identify(deepcopy(payload))
    (payload["members"][0] if role == "artifact-set-manifest" else payload)[member] = (
        "changed"
    )
    after = selected.identify(payload)
    assert before["content_identity"] != after["content_identity"]
    assert selected.verify(before) and selected.verify(after)


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "distinct-kinds"])
def test_publication_build_inspect_and_retry_use_the_same_closed_protocol(
    tmp_path, renamed
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    if renamed:
        _rename_publication(authored)
    graph = _graph(kernel, authored)
    observation = _consumer_a(kernel, graph)
    assert observation["admitted"], observation["diagnostics"]
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(_source())
    args = (
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "e2" * 32,
    )
    receipt = public.cli(*args)
    assert len(_members(receipt)) == 8
    manifest_path = Path(receipt["manifest_locator"])
    manifest = json.loads(manifest_path.read_text())
    index = json.loads((manifest_path.parent / "publication-index.json").read_text())
    assert "frame" not in manifest and "adapter" not in index
    assert set(manifest["members"][0]) == {
        "logical_name",
        "artifact_kind",
        "wire_schema_identity",
        "content_identity",
    }
    assert index["receipt_identity"] == receipt["content_identity"]
    assert index["descriptor_identity"] == receipt["descriptor_identity"]
    assert index["invocation_key"] == receipt["invocation_key"]
    assert index["command_input_identity"]
    assert receipt["manifest_identity"] == manifest["content_identity"]
    for role, artifact in (
        ("artifact-set-manifest", manifest),
        ("artifact-set-receipt", receipt),
        ("publication-index", index),
    ):
        _, binding = _publication_rows(authored, role)
        assert artifact["artifact_kind"] == binding["artifact_kind"]
    receipt_path = public.directory / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    assert public.cli("model", "inspect", str(receipt_path))
    assert public.cli(*args) == receipt
