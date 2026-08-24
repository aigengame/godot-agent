"""Verify one exact Evidence prerequisite graph without issuing Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue
from gda_balancing.domain.diagnostics import Schema2RefusalReport, ingress_refusal
from gda_balancing.domain.evidence import validate_experiment_artifact_set
from gda_balancing.domain.evidence_verification import (
    EvidenceCandidate,
    EvidenceGraphProjectionInput,
    evidence_claim_kind,
    evidence_verification_issue,
    evidence_verification_refusal,
    evaluate_evidence_candidate,
    project_evidence_graph,
    unknown_evidence_claim_kind_refusal,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment
from gda_balancing.domain.model import (
    CheckedModel,
    CompiledArtifactAdmissionError,
    ExactResolvedModelBindingError,
    check_model_source,
    project_compiled_model_binding,
    validate_compiled_artifacts,
)
from gda_balancing.domain.publication import (
    read_authenticated_artifact_set,
    read_authenticated_declared_artifact_set,
)
from gda_balancing.domain.publication_types import PublicationAdmissionError


@dataclass(frozen=True)
class EvidenceVerifyInput:
    """Explicit local inputs to one Evidence candidate judgment."""

    claim_kind: str
    source: str
    specification: str
    model_build_artifact_set_receipt: str
    experiment_run_artifact_set_receipt: str


def verify_evidence(
    inp: EvidenceVerifyInput,
    *,
    model_build_descriptor_identity: str,
    experiment_run_descriptor_identity: str,
    model_build_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    experiment_run_artifact_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
) -> EvidenceCandidate | Schema2RefusalReport:
    """Re-admit exact publications and derive one candidate/open judgment."""
    checked_model = check_model_source(inp.source)
    if isinstance(checked_model, Schema2RefusalReport):
        return checked_model
    assert isinstance(checked_model, CheckedModel)
    try:
        model_publication = read_authenticated_artifact_set(
            inp.model_build_artifact_set_receipt,
            model_build_descriptor_identity,
            model_build_artifact_set,
        )
    except PublicationAdmissionError as error:
        return ingress_refusal(error.code, error.subject, error.message)
    try:
        validate_compiled_artifacts(
            cast(dict[str, dict[str, JsonValue]], model_publication.artifacts),
            checked_model.source_identity,
            model_publication.authority_context,
        )
        model_binding = project_compiled_model_binding(
            cast(dict[str, dict[str, JsonValue]], model_publication.artifacts),
            model_publication.authority_context,
        )
    except (CompiledArtifactAdmissionError, ExactResolvedModelBindingError):
        issue = evidence_verification_issue(
            "mismatched",
            subject="model-build-artifact-set-receipt",
            message="Model build publication does not bind the admitted Model Source",
        )
        return evidence_verification_refusal(
            (issue,),
            model_publication.authority_context.language_bundle,
            {
                "model-build-artifact-set-receipt": cast(
                    str, model_publication.receipt["content_identity"]
                )
            },
        )
    checked_experiment = check_experiment(
        inp.specification,
        authority_context=model_publication.authority_context,
        model_binding=model_binding,
    )
    if isinstance(checked_experiment, Schema2RefusalReport):
        return checked_experiment
    assert isinstance(checked_experiment, CheckedExperiment)
    try:
        outcome_publication = read_authenticated_declared_artifact_set(
            inp.experiment_run_artifact_set_receipt,
            experiment_run_descriptor_identity,
            experiment_run_artifact_sets,
        )
    except PublicationAdmissionError as error:
        return ingress_refusal(error.code, error.subject, error.message)
    claim_kind = evidence_claim_kind(checked_model.language_bundle, inp.claim_kind)
    if claim_kind is None:
        return unknown_evidence_claim_kind_refusal(
            checked_model.language_bundle,
            inp.claim_kind,
        )
    graph = project_evidence_graph(
        claim_kind,
        EvidenceGraphProjectionInput(
            kernel=checked_model.kernel,
            language_bundle=checked_model.language_bundle,
            model_source_identity=checked_model.source_identity,
            model_build_artifact_set_receipt_identity=cast(
                str, model_publication.receipt["content_identity"]
            ),
            model_artifacts=model_publication.artifacts,
            experiment_identity=checked_experiment.content_identity,
            experiment=checked_experiment.value,
            experiment_run_artifact_set_receipt_identity=cast(
                str, outcome_publication.receipt["content_identity"]
            ),
            outcome_artifacts=outcome_publication.artifacts,
        ),
    )
    identities = {subject.role: subject.identity for subject in graph.subjects}
    result = evaluate_evidence_candidate(claim_kind, graph)
    if isinstance(result, tuple):
        return evidence_verification_refusal(
            result, checked_model.language_bundle, identities
        )
    if not validate_experiment_artifact_set(
        checked_experiment, outcome_publication.artifacts
    ):
        issue = evidence_verification_issue(
            "mismatched",
            subject="experiment-run-artifact-set-receipt",
            message="Experiment outcome publication does not bind the admitted Experiment",
        )
        return evidence_verification_refusal(
            (issue,),
            outcome_publication.authority_context.language_bundle,
            {
                "experiment-run-artifact-set-receipt": identities[
                    "experiment-run-artifact-set-receipt"
                ]
            },
        )
    return result
