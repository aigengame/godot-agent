"""Final execution laws are selected meaning and independently admitted (#874)."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from gda_balancing.domain.artifacts import _identified_artifact
from gda_balancing.domain.authority.admission import _execution_projection_is_closed
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.model import (
    CheckedModel,
    admit_resolved_model,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.model._lowering import _identified_rir_artifact


@pytest.fixture(scope="module")
def compiled():
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/structured-selection/model-source.json"
        ).read_bytes()
    )
    checked = check_model_source_value(source)
    assert isinstance(checked, CheckedModel), checked
    return compile_checked_model(checked)


def _trio(artifacts):
    return {
        name: deepcopy(artifacts[name])
        for name in ("package-lock", "rir-semantic-payload", "resolved-model")
    }


def _rebind(trio):
    """Reidentify all affected envelopes, leaving semantic admission as the oracle."""
    context = packaged_authority_context()
    rir = trio["rir-semantic-payload"]
    trio["rir-semantic-payload"] = _identified_rir_artifact(
        context.language_bundle,
        {
            key: value
            for key, value in rir.items()
            if key not in {"artifact_kind", "content_identity", "semantic_identity"}
        },
    )
    rir = trio["rir-semantic-payload"]
    resolved = trio["resolved-model"]
    trio["resolved-model"] = _identified_artifact(
        context.language_bundle,
        "resolved-model",
        {
            **{
                key: value
                for key, value in resolved.items()
                if key not in {"artifact_kind", "content_identity"}
            },
            "rir_content_identity": rir["content_identity"],
            "rir_semantic_identity": rir["semantic_identity"],
        },
    )


def test_final_selected_nodes_and_owned_nested_refusals_are_closed(compiled):
    assert len(compiled) == 8
    assert admit_resolved_model(_trio(compiled)).admitted
    selected = compiled["rir-semantic-payload"]["selected_semantics"]
    runtime = selected["execution_laws"]["runtime_program"]
    nodes = {node["id"]: node for node in runtime["nodes"]}
    assert {"lookup", "equal", "is-empty", "require", "guard-block"} <= nodes.keys()
    assert {"schedule", "cancel", "invoke"}.isdisjoint(nodes)
    kernel = packaged_authority_context().kernel
    assert all(
        node
        == next(
            row
            for row in kernel["meta_format"]["runtime_program"]["nodes"]
            if row["id"] == name
        )
        for name, node in nodes.items()
    )
    assert "vectors" not in runtime
    reasons = {row["definition"]["id"]: row for row in selected["diagnostic_reasons"]}
    assert (
        reasons["standard.conformance.reason.candidate-mismatch"]["package"]
        == "standard.conformance.structured"
    )
    assert reasons["runtime.reason.step-limit"]["package"] == "standard.runtime"
    assert (
        reasons["evaluation.reason.observation-unavailable"]["package"]
        == "standard.experiment"
    )
    assert (
        reasons["structured.reason.resource-exhausted"]["package"] == "standard.schema"
    )
    assert "runtime.reason.cancel-active" not in reasons
    owned = {
        (closure["package"], entry["authority_path"]): entry["definitions"]
        for closure in selected["package_semantic_closures"]
        for entry in closure["definitions"]
    }
    for row in reasons.values():
        assert row["definition"] in owned[row["package"], "language.reasons"]


@pytest.mark.parametrize(
    "mutation",
    [
        "omit-law",
        "alter-charge",
        "resource",
        "omit-reason",
        "reason-owner",
        "diagnostic",
    ],
)
def test_reidentified_execution_dependency_tampering_is_refused(compiled, mutation):
    trio = _trio(compiled)
    selected = trio["rir-semantic-payload"]["selected_semantics"]
    if mutation == "omit-law":
        del selected["execution_laws"]["runtime_program"]["numeric"]
    elif mutation == "alter-charge":
        selected["execution_laws"]["runtime_program"]["nodes"][0]["resource_charge"][
            "amount"
        ] += 1
    elif mutation == "resource":
        selected["execution_resources"]["max_rule_match_steps"] += 1
    elif mutation == "omit-reason":
        selected["diagnostic_reasons"].pop()
    elif mutation == "reason-owner":
        selected["diagnostic_reasons"][0]["package"] = "standard.schema"
    else:
        selected["diagnostics"][0]["definition"]["stage"] = "runtime"
    _rebind(trio)
    assert (
        trio["rir-semantic-payload"]["semantic_identity"]
        != compiled["rir-semantic-payload"]["semantic_identity"]
    )
    assert not admit_resolved_model(trio).admitted


def _contract_inputs():
    kernel, bundle = packaged_authority_context().mutable_pair()
    properties = next(
        row["schema"]
        for row in bundle["language"]["artifact_wire_schemas"]
        if row["artifact_kind"] == "rir-semantic-payload"
    )["properties"]["selected_semantics"]["properties"]
    return (
        kernel["meta_format"]["runtime_projection"]["execution_closure"],
        kernel["meta_format"],
        bundle,
        properties,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "omitted",
        "missing-source",
        "duplicate",
        "wrong-resource",
        "missing-reason",
        "boolean-schema",
    ],
)
def test_machine_execution_selectors_fail_closed(mutation):
    contract, meta, bundle, properties = _contract_inputs()
    assert _execution_projection_is_closed(contract, meta, bundle, properties)
    if mutation == "omitted":
        contract["law_selectors"].pop(0)
    elif mutation == "missing-source":
        contract["law_selectors"][0]["source_path"][-1] = "unknown"
    elif mutation == "duplicate":
        contract["law_selectors"].append(deepcopy(contract["law_selectors"][0]))
    elif mutation == "wrong-resource":
        contract["resources"][0]["source_member"] = "max_runtime_projection_steps"
    elif mutation == "missing-reason":
        contract["reasons"]["roots"][0] = {"when": "executable", "id": "absent.reason"}
    else:
        properties["execution_laws"] = True
    assert not _execution_projection_is_closed(contract, meta, bundle, properties)


def test_overlapping_closed_node_shapes_require_union_not_exclusive_union(compiled):
    _, _, _, properties = _contract_inputs()
    node_schema = properties["execution_laws"]["properties"]["runtime_program"][
        "properties"
    ]["nodes"]["items"]
    constant = next(
        row
        for row in compiled["rir-semantic-payload"]["selected_semantics"][
            "execution_laws"
        ]["runtime_program"]["nodes"]
        if row["id"] == "constant"
    )
    matches = [
        shape
        for shape in node_schema["anyOf"]
        if jsonschema.Draft202012Validator(shape).is_valid(constant)
    ]
    assert len(matches) > 1
    assert jsonschema.Draft202012Validator(node_schema).is_valid(constant)
    assert not jsonschema.Draft202012Validator(
        {"oneOf": node_schema["anyOf"]}
    ).is_valid(constant)
    invalid: dict[str, Any] = deepcopy(constant)
    invalid["unowned-law"] = True
    assert not jsonschema.Draft202012Validator(node_schema).is_valid(invalid)
    assert canonical_bytes(constant)
