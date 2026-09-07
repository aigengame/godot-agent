"""Structured admission emits the diagnostic of its selected intrinsic reason."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.experiment import check_experiment_value
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
    admit_rir,
)
from gda_balancing.domain.structured_values import evaluate_structured_value_vector
from test_execution_dependency_closure import _structured_budget_context
from test_schema2_model_cli import _reidentify_language_bundle


_EXAMPLE = Path(__file__).parents[1] / "examples/schema2/structured-selection"
_CASES = [
    ("unknown-enum", "type-mismatch", "/value/candidates/0/kind"),
    ("type-mismatch", "unknown-enum", "/value/results/0/rank"),
    ("record-member-mismatch", "type-mismatch", "/value/selected"),
    ("resource-exhausted", "type-mismatch", "/value/selected"),
]


def _context(reason: str, other: str, *, remap: bool):
    base = _structured_budget_context(837 if reason == "resource-exhausted" else 1024)
    if not remap:
        return base
    kernel, language_bundle = base.mutable_pair()
    reasons = {row["id"]: row for row in language_bundle["language"]["reasons"]}
    left = reasons[f"structured.reason.{reason}"]
    right = reasons[f"structured.reason.{other}"]
    replacements = {
        left["diagnostic"]: right["diagnostic"],
        right["diagnostic"]: left["diagnostic"],
    }
    left["diagnostic"], right["diagnostic"] = right["diagnostic"], left["diagnostic"]
    identifiers = {left["id"], right["id"]}
    for vector in language_bundle["vectors"]:
        if vector.get("reason") in identifiers:
            vector["diagnostic"] = replacements[vector["diagnostic"]]
    _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    return context


@pytest.mark.parametrize("reason,other,pointer", _CASES)
def test_legal_structured_reason_mapping_reaches_experiment_and_vector_boundaries(
    reason: str, other: str, pointer: str
):
    source = json.loads((_EXAMPLE / "model-source.json").read_bytes())
    specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    envelope = specification["scenarios"][0]["assignments"][0]["value"]
    state = envelope["value"]
    if reason == "unknown-enum":
        state["candidates"][0]["kind"] = "unknown"
    elif reason == "type-mismatch":
        state["results"][0]["rank"] = "wrong-type"
    elif reason == "record-member-mismatch":
        del state["selected"]
    else:
        state["candidates"] *= 32
        state["results"] *= 32
    identities = []
    observations = []
    for remap in (False, True):
        context = _context(reason, other, remap=remap)
        model = check_model_source_value(source, authority_context=context)
        assert isinstance(model, CheckedModel), model
        artifacts = compile_checked_model(model)
        assert len(artifacts) == 8
        program = admit_rir(
            artifacts["rir-semantic-payload"], authority_context=context
        )
        rir = artifacts["rir-semantic-payload"]
        identities.append(rir["semantic_identity"])
        selected_reason = next(
            row["definition"]
            for row in cast(dict[str, Any], rir["selected_semantics"])[
                "diagnostic_reasons"
            ]
            if row["definition"]["id"] == f"structured.reason.{reason}"
        )
        value = deepcopy(specification)
        value["model"] = {"rir_semantic_identity": program.semantic_identity}
        refusal = check_experiment_value(value, program, authority_context=context)
        assert isinstance(refusal, Schema2RefusalReport), refusal
        assert refusal.stage == "static"
        assert len(refusal.diagnostics) == 1
        diagnostic = refusal.diagnostics[0]
        assert isinstance(diagnostic.primary, ArtifactLocation)
        assert diagnostic.primary.pointer == (
            "/scenarios/0/assignments/0/value" + pointer
        )
        assert (
            diagnostic.message
            == "Scenario assignment does not match its declared value"
        )
        vector_observation = evaluate_structured_value_vector(
            {"input": {"action": "admit", "left": envelope}},
            nominal_types=context.language_bundle["language"]["packages"],
            kernel=context.kernel,
            resource_limit=context.language_bundle["resources"]["max_rule_match_steps"],
        )
        observations.append(
            (diagnostic.code, vector_observation, selected_reason["diagnostic"])
        )
    assert identities[0] != identities[1]
    for code, vector, declared in observations:
        assert code == declared
        assert vector == {
            "code": declared,
            "outcome": "refused",
            "pointer": pointer,
            "type": None,
            "value": None,
        }


def test_lookup_fault_identity_follows_the_selected_kernel_signal():
    from gda_balancing.domain.structured_values import (
        StructuredValueFault,
        lookup_typed_value,
        selected_structured_value_index,
        structured_fault_reason,
    )

    kernel, language_bundle = _structured_budget_context(1024).mutable_pair()
    previous = "structured.reason.lookup-out-of-range"
    replacement = "structured.reason.selected-lookup-bound"
    reason = next(
        row for row in language_bundle["language"]["reasons"] if row["id"] == previous
    )
    reason["id"] = replacement
    owner = next(
        row
        for row in language_bundle["language"]["packages"]
        if previous in row["exports"]["reasons"]
    )
    owner["exports"]["reasons"] = [
        replacement if identifier == previous else identifier
        for identifier in owner["exports"]["reasons"]
    ]
    for vector in language_bundle["vectors"]:
        if vector.get("reason") == previous:
            vector["reason"] = replacement
    for operation in language_bundle["language"]["operations"]:
        operation["refusals"] = [
            replacement if identifier == previous else identifier
            for identifier in operation["refusals"]
        ]
    _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = json.loads((_EXAMPLE / "model-source.json").read_bytes())
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    admit_rir(artifacts["rir-semantic-payload"], authority_context=context)
    authority = selected_structured_value_index(
        cast(dict[str, Any], artifacts["rir-semantic-payload"]["selected_semantics"])
    )
    vector = next(
        row
        for vector_set in cast(
            LanguageBundleIndex, context.language_bundle
        ).package_conformance_vector_sets
        for row in vector_set["vector_definitions"]
        if row["id"] == "structured.refuse.list-index-out-of-range"
    )
    with pytest.raises(StructuredValueFault) as captured:
        lookup_typed_value(
            vector["input"]["left"],
            vector["input"]["key"],
            authority=authority,
            resource_limit=1024,
        )
    assert captured.value.reason_id == replacement
    assert structured_fault_reason(captured.value, authority=authority) == reason
    assert (
        evaluate_structured_value_vector(
            vector,
            nominal_types=context.language_bundle["language"]["packages"],
            kernel=context.kernel,
            resource_limit=1024,
        )
        == vector["expect"]
    )
