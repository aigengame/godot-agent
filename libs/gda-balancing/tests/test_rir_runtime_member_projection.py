"""Runtime member projection has one owner and cannot discard executable fields."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)
from gda_balancing.domain.canonical import canonical_bytes
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate
from test_rir_protocol_structure import _definitions, public_rir as public_rir
from test_trace_protocol_structure import _authored, _graph


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("excluded_members", ["vectors", member])
        for member in ("id", "body", "inputs", "resource_bounds")
    ]
    + [
        ("excluded_members", []),
        ("excluded_members", ["vectors"]),
        ("excluded_extension_members", []),
        ("excluded_extension_members", ["standard.formula-notation"]),
    ],
    ids=[
        "id",
        "body",
        "inputs",
        "resource-bounds",
        "empty-members",
        "vectors",
        "empty-extensions",
        "notation",
    ],
)
def test_removed_collection_exclusions_refuse_at_actual_public_entry(
    tmp_path, field, value
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    lowering = _definitions(authored, "language.model_lowerings")[0]
    collection = next(
        row
        for row in lowering["runtime_projection"]["collections"]
        if row["source"].get("authority_path") == "language.operations"
    )
    collection[field] = deepcopy(value)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result
        assert [tuple(row) for row in result["diagnostics"]] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    source = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    candidate.write_source(json.loads(source.read_text()))
    refusal = candidate.cli("model", "check", str(candidate.source), success=False)
    assert candidate.receipts[-1]["returncode"] == 2
    assert refusal["error"]["stage"] == "static"
    assert refusal["error"]["diagnostics"][0]["code"] == "kernel.vector_mismatch"
    assert "KeyError" not in json.dumps(refusal)


def test_fixed_member_projection_preserves_execution_with_renamed_collections(
    public_rir,
):
    context, rir, _, artifacts = public_rir
    selected = rir["selected_semantics"]
    operation_rows = selected["operations"]
    closure_rows = [
        definition
        for package in selected["package_semantic_closures"]
        for closure in package["definitions"]
        if closure["authority_path"] == "language.operations"
        for definition in closure["definitions"]
    ]
    assert operation_rows and closure_rows
    for definition in [row["definition"] for row in operation_rows] + closure_rows:
        assert "vectors" not in definition
        assert {"id", "body", "inputs", "resource_bounds"} <= definition.keys()
        assert "standard.formula-notation" not in definition.get("extensions", {})
    kernel, language = context.mutable_pair()
    law = kernel["meta_format"]["package_release"]["semantic_identity_projection"]
    notation_source = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"]["operation_source"]
    notation_count = 0
    projected_operations = {}
    for package in language["language"]["packages"]:
        actual = cast(
            list[dict[str, Any]], package_runtime_semantic_closure(package, kernel)
        )
        for entry in actual:
            if entry["authority_path"] == "language.operations":
                for definition in entry["definitions"]:
                    assert "vectors" in definition
                    projected_operations[(package["id"], definition["id"])] = {
                        name: value
                        for name, value in definition.items()
                        if name != "vectors"
                    }
            for definition in entry["definitions"]:
                if isinstance(definition, dict):
                    assert notation_source["extension_member"] not in definition.get(
                        "extensions", {}
                    )
        notation_count += sum(
            notation_source["extension_member"] in definition.get("extensions", {})
            for entry in package[law["source_member"]]
            if entry[law["path_member"]] == notation_source["authority_path"]
            for definition in entry["definitions"]
            if isinstance(definition, dict)
        )
    assert notation_count > 0
    assert artifacts["event-trace"]["events"]
    assert all(row["within_target"] for row in artifacts["metric-dataset"]["samples"])
    for row in operation_rows:
        authored = projected_operations[(row["package"], row["definition"]["id"])]
        # Formula slot specialization owns the compiled body; projection preserves
        # the remaining executable signature and bounds exactly.
        for member in ("id", "inputs", "resource_bounds"):
            assert canonical_bytes(row["definition"][member]) == canonical_bytes(
                authored[member]
            )
