"""Execution meaning survives truthful producer changes without weaker validation."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.application.experiment_execution as application_execution
import gda_balancing.domain.experiment_artifacts as result_validation
import gda_balancing.domain.model._compilation as compilation
import gda_balancing.domain.runtime.projections as projections
import gda_balancing.domain.runtime.execution as runtime_execution
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
    read_rir,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    PreparedExperiment,
    evaluate_prepared_experiment,
    prepare_experiment,
)
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_runtime_refusal_experiment,
    prepare_valid_experiment,
    prepare_verdict_experiment,
)

_PRODUCER = "evaluator-capability-manifest"


def _checked(tmp_path: Path, outcome: str = "success") -> CheckedExperiment:
    fixture = {
        "success": prepare_valid_experiment,
        "verdict": prepare_verdict_experiment,
        "runtime-refusal": prepare_runtime_refusal_experiment,
    }[outcome](tmp_path, 875)
    context = packaged_authority_context()
    program = read_rir(fixture.rir, authority_context=context)
    assert isinstance(program, AdmittedRir)
    checked = check_experiment_value(
        json.loads(fixture.specification), program, authority_context=context
    )
    assert isinstance(checked, CheckedExperiment)
    return checked


def _evaluate(checked: CheckedExperiment) -> dict[str, dict[str, Any]]:
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment)
    outcome = evaluate_prepared_experiment(prepared)
    if isinstance(outcome, projections.RuntimeRefusalOutcome):
        members = result_validation.runtime_terminal_audit_members(
            checked,
            outcome,
            evaluator=prepared.evaluator,
            resolved_runtime=prepared.resolved_runtime,
        )
    else:
        assert isinstance(outcome, EvaluationArtifacts)
        members = outcome.members
    artifacts = {name: deepcopy(member.value) for name, member in members.items()}
    assert result_validation.validate_experiment_artifact_set(checked, artifacts)
    return artifacts


def _reidentify(
    checked: CheckedExperiment, artifacts: dict[str, dict[str, Any]], name: str
) -> None:
    payload = {
        key: value
        for key, value in artifacts[name].items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    artifacts[name] = checked.output_contracts[name].identify(payload)


@pytest.mark.parametrize("outcome", ["success", "verdict", "runtime-refusal"])
@pytest.mark.parametrize("producer_change", ["implementation", "platform", "source"])
def test_original_outcome_survives_a_different_producer(
    tmp_path, monkeypatch, outcome, producer_change
):
    checked = _checked(tmp_path, outcome)
    projections.evaluator_build_identity.cache_clear()
    original = _evaluate(checked)
    profile = original["resolved-runtime-profile"]
    selected_profile = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == checked.value["runtime"]["profile"]
    )
    assert profile["runtime_profile"] == selected_profile
    assert profile["runtime_profile"]["extensions"] == selected_profile["extensions"]
    assert profile["rir_semantic_identity"] == checked.rir["semantic_identity"]

    if producer_change == "implementation":
        monkeypatch.setattr(projections, "EVALUATOR_IMPLEMENTATION", "other-evaluator")
    elif producer_change == "platform":
        monkeypatch.setattr(projections.platform, "machine", lambda: "other-machine")
    else:
        read_source = projections.read_package_resource

        def changed_source(package: str, name: str) -> bytes:
            data = read_source(package, name)
            if name == "domain/model/_compilation.py":
                return data + b"\n# Compiler-only provenance witness.\n"
            return data

        monkeypatch.setattr(projections, "read_package_resource", changed_source)
        projections.evaluator_build_identity.cache_clear()
    try:
        current = _evaluate(checked)
        assert (
            original[_PRODUCER]["content_identity"]
            != current[_PRODUCER]["content_identity"]
        )
        if producer_change == "source":
            assert (
                original[_PRODUCER]["evaluator_build_identity"]
                != current[_PRODUCER]["evaluator_build_identity"]
            )
        assert {
            name: canonical_bytes(value)
            for name, value in original.items()
            if name != _PRODUCER
        } == {
            name: canonical_bytes(value)
            for name, value in current.items()
            if name != _PRODUCER
        }

        def unexpected_current_producer(_checked):
            pytest.fail(
                "original-result validation must not construct current provenance"
            )

        monkeypatch.setattr(
            projections, "evaluator_manifest", unexpected_current_producer
        )
        assert result_validation.validate_experiment_artifact_set(checked, original)
    finally:
        projections.evaluator_build_identity.cache_clear()


def test_changed_compiler_receipt_preserves_admitted_execution(tmp_path, monkeypatch):
    checked = _checked(tmp_path)
    original = _evaluate(checked)
    context = packaged_authority_context()
    language_bundle = cast(LanguageBundleIndex, context.language_bundle)
    vectors = next(
        row
        for row in language_bundle.package_conformance_vector_sets
        if row["package_id"] == "game.combat"
    )["vector_definitions"]
    source = next(
        row
        for row in vectors
        if row["id"] == "formula.combat.accept.damage-slot-binding"
    )["source_fixture"]["source"]
    checked_model = check_model_source_value(source, authority_context=context)
    assert isinstance(checked_model, CheckedModel)
    original_build = compile_checked_model(checked_model)
    monkeypatch.setattr(
        compilation, "_LOWERER_IMPLEMENTATION_IDENTITY", "other-compiler"
    )
    changed_build = compile_checked_model(checked_model)
    assert (
        original_build["build-receipt"]["content_identity"]
        != changed_build["build-receipt"]["content_identity"]
    )
    assert (
        original_build["rir-semantic-payload"] == changed_build["rir-semantic-payload"]
    )
    program = admit_rir(
        changed_build["rir-semantic-payload"], authority_context=context
    )
    assert isinstance(program, AdmittedRir)
    changed_checked = check_experiment_value(
        checked.value, program, authority_context=context
    )
    assert isinstance(changed_checked, CheckedExperiment)
    assert _evaluate(changed_checked) == original
    assert result_validation.validate_experiment_artifact_set(changed_checked, original)


@pytest.mark.parametrize("outcome", ["success", "verdict", "runtime-refusal"])
def test_original_producer_still_requires_actual_capability_coverage(tmp_path, outcome):
    checked = _checked(tmp_path, outcome)
    artifacts = _evaluate(checked)
    artifacts[_PRODUCER]["numeric_policies"] = ["unsupported-number-system"]
    _reidentify(checked, artifacts, _PRODUCER)
    assert result_validation.validate_experiment_member(
        checked, _PRODUCER, artifacts[_PRODUCER]
    )
    assert not result_validation.validate_experiment_artifact_set(checked, artifacts)


def test_new_execution_still_refuses_an_unsupported_actual_operator(
    tmp_path, monkeypatch
):
    checked = _checked(tmp_path)
    monkeypatch.setattr(
        projections,
        "SUPPORTED_RUNTIME_OPERATORS",
        projections.SUPPORTED_RUNTIME_OPERATORS - {"integer-subtract"},
    )
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, Schema2RefusalReport)
    assert prepared.stage == "resolution"
    assert isinstance(prepared.diagnostics[0].primary, ArtifactLocation)
    assert prepared.diagnostics[0].primary.pointer == (
        "/runtime/required_evaluator/instruction_nodes"
    )


@pytest.mark.parametrize("outcome", ["success", "verdict", "runtime-refusal"])
def test_reidentified_outcome_still_requires_semantic_evidence(tmp_path, outcome):
    checked = _checked(tmp_path, outcome)
    artifacts = _evaluate(checked)
    if outcome == "runtime-refusal":
        name = "runtime-terminal-audit"
        artifacts[name]["refusing_event"]["event_id"] = "forged-event"
        _reidentify(checked, artifacts, name)
    else:
        name = "evaluation-run" if outcome == "success" else "experiment-verdict"
        artifacts["metric-dataset"]["samples"][0]["event_id"] = "forged-event"
        _reidentify(checked, artifacts, "metric-dataset")
        artifacts[name]["metric_dataset_identity"] = artifacts["metric-dataset"][
            "content_identity"
        ]
        _reidentify(checked, artifacts, name)
    assert all(
        result_validation.validate_experiment_member(checked, name, value)
        for name, value in artifacts.items()
    )
    assert not result_validation.validate_experiment_artifact_set(checked, artifacts)


def test_terminal_provenance_retains_the_prepared_actual_producer(
    tmp_path, monkeypatch
):
    checked = _checked(tmp_path, "runtime-refusal")
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment)
    original_producer = deepcopy(prepared.evaluator.value)
    execute_instruction = runtime_execution._execute_value_instruction
    changed_during_execution = False

    def change_producer_during_instruction(*args, **kwargs):
        nonlocal changed_during_execution
        changed_during_execution = True
        monkeypatch.setattr(projections, "EVALUATOR_IMPLEMENTATION", "later-producer")
        return execute_instruction(*args, **kwargs)

    monkeypatch.setattr(
        runtime_execution,
        "_execute_value_instruction",
        change_producer_during_instruction,
    )
    outcome = application_execution.execute_prepared_experiment(prepared)
    assert changed_during_execution
    assert isinstance(outcome, application_execution.ExperimentExecutionRefusal)
    assert outcome.report.stage == "runtime"
    assert outcome.members[_PRODUCER].value == original_producer
    assert projections.evaluator_manifest(checked).value != original_producer
    artifacts = {name: member.value for name, member in outcome.members.items()}
    assert result_validation.validate_experiment_artifact_set(checked, artifacts)
