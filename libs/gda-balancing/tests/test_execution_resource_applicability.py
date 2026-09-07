"""An unused structured-value budget does not identify numeric execution (#874)."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.admission import _execution_projection_is_closed
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifact_replay import execute_value_instruction
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    CheckedModel,
    admit_resolved_model,
    check_model_source_value,
    compile_checked_model,
    project_compiled_model_binding,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    _execute_value_instruction,
    evaluate_experiment,
)
from gda_balancing.domain.structured_values import (
    _Budget,
    admit_typed_value,
    selected_structured_value_index,
)
from schema2_authority_support import mutable_authorities
from test_execution_law_projection import _contract_inputs, _rebind, _trio
from test_schema2_model_cli import _model_source, _reidentify_language_bundle


_EXAMPLES = Path(__file__).parents[1] / "examples" / "schema2"


def _budget_context(limit: int) -> AdmittedAuthorityContext:
    kernel, language_bundle = mutable_authorities()
    language_bundle["resources"]["max_rule_match_steps"] = limit
    for identifier, value in (
        ("model.accept.resolution-step-boundary", limit),
        ("model.refuse.resolution-step-budget", limit + 1),
    ):
        next(row for row in language_bundle["vectors"] if row["id"] == identifier)[
            "input"
        ]["value"] = value
    _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    return context


def _compile(source, context) -> dict[str, dict[str, Any]]:
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    artifacts = compile_checked_model(checked)
    assert len(artifacts) == 8
    return cast(dict[str, dict[str, Any]], artifacts)


def _numeric_observations(name, artifacts, context):
    value = json.loads((_EXAMPLES / name / "experiment.json").read_bytes())
    build = artifacts["build-receipt"]
    value["kernel_identity"] = build["kernel_identity"]
    value["language_bundle_identity"] = build["language_bundle_identity"]
    value["model"] = {
        key: build["content_identity"]
        if key == "build_receipt_identity"
        else build[key]
        for key in value["model"]
    }
    binding = project_compiled_model_binding(artifacts, context)
    checked = check_experiment_value(value, binding, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    outcome = evaluate_experiment(checked)
    assert isinstance(outcome, EvaluationArtifacts), outcome
    members = {name: member.value for name, member in outcome.members.items()}
    assert validate_experiment_artifact_set(checked, members)
    # Complete observed values are compared; producer/binding identifiers are
    # separately expected to change with the independently resealed LDB.
    return {
        "accepted": outcome.accepted,
        "failed_metrics": list(outcome.failed_metrics),
        "events": [
            {
                key: event.get(key)
                for key in (
                    "outcome",
                    "state_before",
                    "state_after",
                    "facts",
                    "rng_draws",
                )
            }
            for event in members["event-trace"]["events"]
        ],
        "metric_values": [row["value"] for row in members["metric-dataset"]["samples"]],
    }


@pytest.mark.parametrize("name", ["progression-periodic-effect", "rpg-combat-cast"])
def test_numeric_budget_changes_preserve_rir_meaning_and_complete_observations(name):
    source = json.loads((_EXAMPLES / name / "model-source.json").read_bytes())
    meanings = []
    observations = []
    for limit in (65535, 65536):
        context = _budget_context(limit)
        artifacts = _compile(source, context)
        rir = artifacts["rir-semantic-payload"]
        assert rir["selected_semantics"]["execution_resources"] == {}
        meanings.append(rir["semantic_identity"])
        observations.append(
            canonical_bytes(_numeric_observations(name, artifacts, context))
        )
    assert meanings[0] == meanings[1]
    assert observations[0] == observations[1]


def test_nonexecuting_quantity_omits_unused_budget_and_fixed_execution_laws():
    meanings = []
    for limit in (65535, 65536):
        artifacts = _compile(_model_source(), _budget_context(limit))
        rir = artifacts["rir-semantic-payload"]
        assert rir["entrypoints"] == []
        assert rir["selected_semantics"]["execution_resources"] == {}
        assert rir["selected_semantics"]["execution_laws"]["runtime_program"] == {
            "nodes": []
        }
        meanings.append(rir["semantic_identity"])
    assert meanings[0] == meanings[1]


@pytest.mark.parametrize("active_profile", [False, True])
def test_nonexecuting_model_refuses_before_constructing_runtime_consumers(
    active_profile,
):
    kernel, language_bundle = mutable_authorities()
    if active_profile:
        profiles = language_bundle["language"]["runtime_profiles"]
        compile_profile = next(
            row for row in profiles if row["id"] == "compile.exact-int64"
        )
        active = deepcopy(
            next(
                row for row in profiles if row["id"] == "standard.exact-int64-event-v1"
            )
        )
        active["id"] = compile_profile["id"]
        active.pop("extensions", None)
        compile_profile.clear()
        compile_profile.update(active)
        _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    artifacts = _compile(_model_source(), context)
    assert artifacts["rir-semantic-payload"]["entrypoints"] == []
    assert artifacts["rir-semantic-payload"]["selected_semantics"]["execution_laws"][
        "runtime_program"
    ] == {"nodes": []}
    value = json.loads(
        (_EXAMPLES / "progression-periodic-effect" / "experiment.json").read_bytes()
    )
    build = artifacts["build-receipt"]
    value["kernel_identity"] = build["kernel_identity"]
    value["language_bundle_identity"] = build["language_bundle_identity"]
    value["model"] = {
        key: build["content_identity"]
        if key == "build_receipt_identity"
        else build[key]
        for key in value["model"]
    }
    value["runtime"]["profile"] = "compile.exact-int64"
    value["runtime"]["required_evaluator"]["runtime_profiles"] = ["compile.exact-int64"]
    scenario = value["scenarios"][0]
    scenario["assignments"] = []
    scenario["named_streams"] = []
    scenario["event_plan"] = [
        {
            "kind": "external-input",
            "root_event_ref": "input",
            "logical_time": 0,
            "priority": 0,
            "source_identity": "sha256:" + "e" * 64,
            "source_sequence": 0,
            "facts": [
                {
                    "target": {
                        "model": "example.quantity-model",
                        "module": "main",
                        "name": "input_value",
                    },
                    "value": 1,
                }
            ],
        }
    ]
    binding = project_compiled_model_binding(artifacts, context)
    refused = check_experiment_value(value, binding, authority_context=context)
    assert isinstance(refused, Schema2RefusalReport), refused
    assert refused.stage == "resolution"
    assert refused.variant is None
    assert refused.terminal_audit is None
    assert len(refused.diagnostics) == 1
    diagnostic = refused.diagnostics[0]
    assert diagnostic.code == "language.resolution_binding_mismatch"
    assert isinstance(diagnostic.primary, ArtifactLocation)
    assert diagnostic.primary.pointer == "/model/rir_identity"
    assert diagnostic.message == "Experiment Model has no executable Event entrypoints"


@pytest.fixture(scope="module")
def numeric_execution():
    context = packaged_authority_context()
    source = json.loads(
        (_EXAMPLES / "rpg-combat-cast" / "model-source.json").read_bytes()
    )
    artifacts = _compile(source, context)
    return context, artifacts["rir-semantic-payload"]["selected_semantics"]


@pytest.mark.parametrize(
    "operands", [(4, 4, True), (4, 5, False), (True, False, False)]
)
@pytest.mark.parametrize(
    "execute",
    [_execute_value_instruction, execute_value_instruction],
    ids=["runtime", "independent-replay"],
)
def test_scalar_canonical_equality_never_consumes_the_structured_budget(
    operands, execute, monkeypatch, numeric_execution
):
    context, selected = numeric_execution
    assert selected["execution_resources"] == {}
    authority = selected_structured_value_index(selected)
    assert authority.typed_envelope_profile is None
    runtime = context.kernel["meta_format"]["runtime_program"]
    equality = next(
        row
        for row in runtime["nodes"]
        if row["semantics"]["operator"] == "canonical-equal"
    )

    def unexpected_charge(_budget, _pointer):
        pytest.fail("scalar equality consumed a structured-value budget")

    monkeypatch.setattr(_Budget, "consume", unexpected_charge)
    for limit in (None, 65535, 65536):
        values = {"left": operands[0], "right": operands[1]}
        execute(
            {
                "node": equality["id"],
                "left": "left",
                "right": "right",
                "target": "equal",
            },
            values,
            runtime["numeric"],
            equality,
            structured_authority=authority,
            structured_resource_limit=limit,
        )
        assert values["equal"] is operands[2]


def test_missing_selected_typed_profile_refuses_before_any_budget_charge(
    monkeypatch, numeric_execution
):
    _context, selected = numeric_execution
    authority = selected_structured_value_index(selected)

    def unexpected_charge(_budget, _pointer):
        pytest.fail("missing typed profile reached resource charging")

    monkeypatch.setattr(_Budget, "consume", unexpected_charge)
    with pytest.raises(ValueError, match="typed-envelope members are unavailable"):
        admit_typed_value(
            {"type": {"package": "core.quantity", "id": "Quantity"}, "value": 1},
            authority=authority,
            resource_limit=1,
        )


@pytest.mark.parametrize("mutation", ["omitted-when", "always", "required-schema"])
def test_resource_applicability_is_an_exact_machine_contract(mutation):
    contract, meta, bundle, properties = _contract_inputs()
    assert _execution_projection_is_closed(contract, meta, bundle, properties)
    if mutation == "omitted-when":
        del contract["resources"][0]["when"]
    elif mutation == "always":
        contract["resources"][0]["when"] = "always"
    else:
        properties["execution_resources"]["required"] = ["max_rule_match_steps"]
    assert not _execution_projection_is_closed(contract, meta, bundle, properties)


@pytest.mark.parametrize("typed", [False, True])
def test_reidentified_resource_presence_must_match_actual_applicability(typed):
    source = (
        json.loads((_EXAMPLES / "structured-selection/model-source.json").read_bytes())
        if typed
        else _model_source()
    )
    artifacts = _compile(source, packaged_authority_context())
    trio = _trio(artifacts)
    selected: dict[str, Any] = trio["rir-semantic-payload"]["selected_semantics"]
    if typed:
        assert selected["execution_resources"]["max_rule_match_steps"] > 0
        selected["execution_resources"] = {}
    else:
        assert selected["execution_resources"] == {}
        selected["execution_resources"] = {"max_rule_match_steps": 65536}
    _rebind(trio)
    assert not admit_resolved_model(trio).admitted
