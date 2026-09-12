"""One fixed Template container owner retains mutable member Schema semantics."""

from copy import deepcopy
from dataclasses import replace
import json
import hashlib

import pytest

from gda_balancing.domain.artifacts import select_protocol_artifact_contract
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.template_projection import template_protocol_schema
from gda_balancing.domain.template import minimal_release
from gda_balancing.interfaces.cli.template_catalog import (
    TEMPLATE_GET,
    template_get_handler,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_template_schema,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    read_extension_inventory,
    validate_extension_inventory,
)
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_template_cli import _reidentify_release
from test_receipt_protocol_structure import _definitions
from test_trace_protocol_structure import _authored, _graph


# Independent exact Schema bytes captured at 96ca2645, before deleting the
# authored copies. Changed Kernel/LDB provenance does not change this wire shape.
_SCHEMA_DIGESTS = {
    "template-instantiate-command-input": (
        "878b2001ec26c5120603155b10186702f93a1530e6dde4bbc0fbbf4e543fbc3b"
    ),
    "template-instantiation-receipt": (
        "7c98c966bcb27c7283f09af82789cc17dbf49155ef99e7ce7f2bfcd300160976"
    ),
    "template-release": (
        "681fce20f820e6cf0e24e361da3b5b1e822274783822818ae0c7d1317b550a80"
    ),
}


def _row(authored, role):
    return next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == role
    )


@pytest.mark.parametrize("role", _SCHEMA_DIGESTS)
def test_template_fixed_containers_have_one_owner_and_exact_wire(role):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    assert "schema" not in _row(authored, role)
    selected = select_protocol_artifact_contract(ldb, role)
    assert (
        hashlib.sha256(canonical_bytes(selected.schema)).hexdigest()
        == (_SCHEMA_DIGESTS[role])
    )
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, _graph(kernel, deepcopy(authored)))
        assert result["admitted"], result
    inventory = read_extension_inventory(kernel, authored)
    validate_extension_inventory(kernel, authored, inventory)
    assert not any(
        gap.pointer.endswith(f"/definitions/{index}")
        and "/packages/12/semantic_closure/2/" in gap.pointer
        for gap in inventory.uncovered
        for index in (0, 1, 2)
    )
    # Source, Resolution and unrelated Artifact families stay open.
    assert len(inventory.uncovered) == 4


@pytest.mark.parametrize("role", _SCHEMA_DIGESTS)
@pytest.mark.parametrize("rename", [False, True], ids=["exact-shadow", "field-rename"])
def test_template_authored_container_override_refuses_before_public_workflow(
    tmp_path, role, rename
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    schema = deepcopy(select_protocol_artifact_contract(ldb, role).schema)
    if rename:
        old = "members" if role == "template-release" else "template_identity"
        schema["properties"]["renamed_" + old] = schema["properties"].pop(old)
        schema["required"] = [
            "renamed_" + old if name == old else name for name in schema["required"]
        ]
    _row(authored, role)["schema"] = schema
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    args = ["template", "get", "--id", "standard.quantity-minimal"]
    if role != "template-release":
        args = [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--package-id",
            "example.template-wire",
            "--out",
            str(public.directory / "editable.json"),
            "--invocation-key",
            "a8" * 32,
        ]
    refused = public.cli(*args, success=False)
    assert public.receipts[-1]["returncode"] == 2
    assert [row["code"] for row in refused["error"]["diagnostics"]] == [
        "kernel.vector_mismatch"
    ]
    assert not list((public.directory / "store").rglob("artifact-set-receipt.json"))


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-part",
        "unknown-part",
        "missing-field",
        "duplicate-owner",
        "duplicate-required",
        "member-open",
        "payload-owner",
        "collection-owner",
    ],
)
def test_template_container_contract_is_closed_in_both_projections(mutation):
    kernel, _ = mutable_authorities()
    structure = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["template_structure"]
    if mutation == "missing-part":
        del structure["member"]
    elif mutation == "unknown-part":
        structure["unknown"] = {}
    elif mutation == "missing-field":
        del structure["release"]["field_types"]["id"]
    elif mutation == "duplicate-owner":
        structure["release"]["field_types"]["members"] = {"type": "canonical-json"}
    elif mutation == "duplicate-required":
        structure["member"]["required_members"].append("payload")
    elif mutation == "member-open":
        structure["member"]["type"] = "object"
    elif mutation == "payload-owner":
        structure["member"]["field_types"]["payload"] = {"type": "string"}
    else:
        structure["member_collection"]["items"] = {"type": "canonical-json"}
    for project in (template_protocol_schema, _consumer_b_template_schema):
        with pytest.raises((KeyError, ValueError)):
            project(kernel, "template-release", "template-release")


def test_template_schema_and_artifact_names_are_distinct_public_bindings(tmp_path):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    kinds = {}
    for index, role in enumerate(_SCHEMA_DIGESTS):
        schema = _row(authored, role)
        contract = next(
            row
            for row in _definitions(authored, "language.artifact_contracts")
            if row["schema_kind"] == schema["artifact_kind"]
        )
        old_schema, old_kind = schema["artifact_kind"], contract["artifact_kind"]
        schema["artifact_kind"] = f"frame.schema.{index}"
        contract["schema_kind"] = schema["artifact_kind"]
        contract["artifact_kind"] = kinds[role] = f"frame.artifact.{index}"
        for package in authored["packages"]:
            for collection, old, new in (
                ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
                ("artifact_contracts", old_kind, contract["artifact_kind"]),
            ):
                package["exports"][collection] = [
                    new if value == old else value
                    for value in package["exports"][collection]
                ]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    release = public.cli("template", "get", "--id", "standard.quantity-minimal")
    assert release["artifact_kind"] == kinds["template-release"]
    out = public.directory / "source.json"
    receipt = public.cli(
        "template",
        "instantiate",
        "--id",
        release["id"],
        "--package-id",
        "example.template-wire",
        "--out",
        str(out),
        "--invocation-key",
        "b8" * 32,
    )
    source = json.loads(out.read_text())
    member = _members(receipt)["template-instantiation-receipt"]
    assert member["artifact_kind"] == kinds["template-instantiation-receipt"]
    starter = next(
        m["payload"]
        for m in release["members"]
        if m["member_kind"] == "model-source-package"
    )
    assert member["starter_identity"] == content_identity(
        "model-source-package-v2", starter
    )
    assert member["model_source_identity"] == content_identity(
        "model-source-package-v2", source
    )
    assert member["starter_identity"] != member["model_source_identity"]
    assert (
        source["manifest"]["template_provenance"]["template_identity"]
        == release["content_identity"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "member-schema",
        "member-digest",
        "manifest",
        "kernel-binding",
        "ldb-binding",
        "starter-binding",
    ],
)
def test_fixed_template_containers_preserve_real_member_and_binding_refusals(
    run_cli, mutation
):
    context = packaged_authority_context()
    release = json.loads(canonical_bytes(minimal_release(context)))
    member = release["members"][0]
    if mutation == "member-schema":
        member["member_schema_identity"] = "sha256:" + "0" * 64
        _reidentify_release(release)
    elif mutation == "member-digest":
        member["content_identity"] = "sha256:" + "0" * 64
        release["manifest"][0]["content_identity"] = member["content_identity"]
    elif mutation == "manifest":
        release["manifest"][0]["logical_name"] = "wrong-member"
    elif mutation == "kernel-binding":
        release["kernel_identity"] = "sha256:" + "0" * 64
    elif mutation == "ldb-binding":
        release["language_bundle_identity"] = "sha256:" + "0" * 64
    else:
        experiment = next(
            m["payload"]
            for m in release["members"]
            if m["member_kind"] == "experiment-template"
        )
        experiment["model_source_identity"] = "sha256:" + "0" * 64
        _reidentify_release(release)
    release["content_identity"] = content_identity(
        "template-release-v2",
        {k: v for k, v in release.items() if k != "content_identity"},
    )
    contract = select_protocol_artifact_contract(
        context.language_bundle, "template-release"
    )
    assert contract.verify(release)  # A valid outer container is insufficient.
    descriptor = replace(TEMPLATE_GET, handler=template_get_handler(lambda _: release))
    code, stdout, stderr = run_cli(
        ["template", "get", "--id", release["id"]], registry=(descriptor,)
    )
    assert (code, stderr) == (2, "")
    assert "diagnostics" in json.loads(stdout)["error"]
