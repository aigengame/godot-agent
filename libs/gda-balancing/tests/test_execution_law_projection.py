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


# These complementary maintained programs exercise typed values/guarded refusal
# and transitive invocation/scheduling/cancellation. Each witness is selected by
# a real Source build; unrelated Kernel nodes are deliberately not manufactured.
_NODE_WITNESSES = (
    ("structured-selection", "constant"),
    ("structured-selection", "draw"),
    ("structured-selection", "equal"),
    ("structured-selection", "guard-block"),
    ("structured-selection", "if"),
    ("structured-selection", "is-empty"),
    ("structured-selection", "lookup"),
    ("structured-selection", "require"),
    ("structured-selection", "write-state"),
    ("rpg-combat-cast", "add"),
    ("rpg-combat-cast", "cancel"),
    ("rpg-combat-cast", "copy"),
    ("rpg-combat-cast", "invoke"),
    ("rpg-combat-cast", "less-than-or-equal"),
    ("rpg-combat-cast", "maximum"),
    ("rpg-combat-cast", "multiply"),
    ("rpg-combat-cast", "precondition-greater-than-or-equal"),
    ("rpg-combat-cast", "schedule"),
    ("rpg-combat-cast", "subtract"),
    ("rpg-combat-cast", "subtract-state"),
)

_REASON_WITNESSES = (
    ("structured-selection", "evaluation.reason.observation-unavailable"),
    ("structured-selection", "runtime.reason.capability-unsupported"),
    ("structured-selection", "runtime.reason.event-limit"),
    ("structured-selection", "runtime.reason.logical-time-limit"),
    ("structured-selection", "runtime.reason.numeric-overflow"),
    ("structured-selection", "runtime.reason.queue-limit"),
    ("structured-selection", "runtime.reason.step-limit"),
    ("structured-selection", "standard.conformance.reason.candidate-mismatch"),
    ("structured-selection", "structured.reason.lookup-out-of-range"),
    ("structured-selection", "structured.reason.record-member-mismatch"),
    ("structured-selection", "structured.reason.resource-exhausted"),
    ("structured-selection", "structured.reason.type-mismatch"),
    ("structured-selection", "structured.reason.unknown-enum"),
    ("rpg-combat-cast", "game.combat.reason.invalid-defeat-threshold"),
    ("rpg-combat-cast", "runtime.reason.cancel-active"),
    ("rpg-combat-cast", "runtime.reason.cancel-completed"),
    ("rpg-combat-cast", "runtime.reason.cancel-unknown"),
    ("rpg-combat-cast", "runtime.reason.schedule-backward"),
    ("rpg-combat-cast", "runtime.reason.schedule-hidden-input"),
    ("rpg-combat-cast", "runtime.reason.schedule-illegal-same-time-priority"),
    ("rpg-combat-cast", "runtime.reason.zero-time-depth-limit"),
)

_DIAGNOSTIC_WITNESSES = (
    ("structured-selection", "evaluation.observation_unavailable"),
    ("structured-selection", "language.structured_value_record_member_mismatch"),
    ("structured-selection", "language.structured_value_resource_exhausted"),
    ("structured-selection", "language.structured_value_type_mismatch"),
    ("structured-selection", "language.structured_value_unknown_enum"),
    ("structured-selection", "runtime.capability_unsupported"),
    ("structured-selection", "runtime.event_limit_exceeded"),
    ("structured-selection", "runtime.logical_time_exceeded"),
    ("structured-selection", "runtime.numeric_overflow"),
    ("structured-selection", "runtime.queue_limit_exceeded"),
    ("structured-selection", "runtime.step_limit_exceeded"),
    ("structured-selection", "runtime.structured_lookup_out_of_range"),
    ("structured-selection", "standard.conformance.candidate_mismatch"),
    ("rpg-combat-cast", "game.combat.invalid_defeat_threshold"),
    ("rpg-combat-cast", "runtime.cancel_active"),
    ("rpg-combat-cast", "runtime.cancel_completed"),
    ("rpg-combat-cast", "runtime.cancel_unknown"),
    ("rpg-combat-cast", "runtime.schedule_backward"),
    ("rpg-combat-cast", "runtime.schedule_hidden_input"),
    ("rpg-combat-cast", "runtime.schedule_illegal_same_time_priority"),
    ("rpg-combat-cast", "runtime.zero_time_depth_exceeded"),
)


@pytest.fixture(scope="module")
def closure_examples():
    artifacts = {}
    for example in ("structured-selection", "rpg-combat-cast"):
        source = json.loads(
            (
                Path(__file__).parents[1]
                / "examples/schema2"
                / example
                / "model-source.json"
            ).read_bytes()
        )
        checked = check_model_source_value(source)
        assert isinstance(checked, CheckedModel), checked
        built = compile_checked_model(checked)
        assert admit_resolved_model(_trio(built)).admitted
        artifacts[example] = built
    return artifacts


def _assert_reidentified_meaning_is_refused(original, mutated, path):
    _rebind(mutated)
    assert (
        mutated["rir-semantic-payload"]["semantic_identity"]
        != original["rir-semantic-payload"]["semantic_identity"]
    ), path
    admission = admit_resolved_model(mutated)
    assert not admission.admitted, path


@pytest.mark.parametrize(
    "law_path",
    [
        ("runtime_program", "version"),
        ("runtime_program", "numeric"),
        ("runtime_program", "named_rng"),
        ("runtime_program", "scheduler"),
        ("runtime_program", "event_atomicity"),
        ("runtime_program", "invocation_contract"),
        ("runtime_program", "runtime_configuration"),
        ("runtime_program", "transition"),
        ("runtime_program", "step"),
        ("runtime_program", "fixed_value_contracts"),
        ("typed_envelope_profile",),
    ],
    ids=lambda path: "/".join(path),
)
def test_each_selected_execution_law_is_an_independently_admitted_dependency(
    compiled, law_path
):
    mutated = _trio(compiled)
    parent = mutated["rir-semantic-payload"]["selected_semantics"]["execution_laws"]
    for member in law_path[:-1]:
        parent = parent[member]
    del parent[law_path[-1]]
    _assert_reidentified_meaning_is_refused(compiled, mutated, law_path)


@pytest.mark.parametrize("example,node_id", _NODE_WITNESSES)
def test_each_selected_node_charge_is_an_independently_admitted_dependency(
    closure_examples, example, node_id
):
    original = closure_examples[example]
    mutated = _trio(original)
    nodes = mutated["rir-semantic-payload"]["selected_semantics"]["execution_laws"][
        "runtime_program"
    ]["nodes"]
    node = next(row for row in nodes if row["id"] == node_id)
    node["resource_charge"]["amount"] += 1
    _assert_reidentified_meaning_is_refused(original, mutated, ("nodes", node_id))


@pytest.mark.parametrize("example,reason_id", _REASON_WITNESSES)
def test_each_selected_reason_is_an_independently_admitted_dependency(
    closure_examples, example, reason_id
):
    original = closure_examples[example]
    mutated = _trio(original)
    reasons = mutated["rir-semantic-payload"]["selected_semantics"][
        "diagnostic_reasons"
    ]
    reasons.remove(next(row for row in reasons if row["definition"]["id"] == reason_id))
    _assert_reidentified_meaning_is_refused(original, mutated, ("reasons", reason_id))


@pytest.mark.parametrize("example,code", _DIAGNOSTIC_WITNESSES)
def test_each_selected_diagnostic_is_an_independently_admitted_dependency(
    closure_examples, example, code
):
    original = closure_examples[example]
    mutated = _trio(original)
    diagnostics = mutated["rir-semantic-payload"]["selected_semantics"]["diagnostics"]
    diagnostics.remove(
        next(row for row in diagnostics if row["definition"]["code"] == code)
    )
    _assert_reidentified_meaning_is_refused(original, mutated, ("diagnostics", code))
