"""Verify one exact Evidence prerequisite graph without issuing Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport, ingress_refusal
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
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
from gda_balancing.domain.publication import read_authenticated_declared_artifact_set
from gda_balancing.domain.publication_types import PublicationAdmissionError


@dataclass(frozen=True)
class EvidenceVerifyInput:
    """Explicit local inputs to one Evidence candidate judgment."""

    claim_kind: str
    rir: str
    specification: str
    experiment_run_artifact_set_receipt: str


def verify_evidence(
    inp: EvidenceVerifyInput,
    *,
    experiment_run_artifact_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
) -> EvidenceCandidate | Schema2RefusalReport:
    """Re-admit exact publications and derive one candidate/open judgment."""
    context = packaged_authority_context()
    try:
        outcome_publication = read_authenticated_declared_artifact_set(
            inp.experiment_run_artifact_set_receipt,
            experiment_run_artifact_sets,
            authority_context=context,
        )
    except PublicationAdmissionError as error:
        return ingress_refusal(error.code, error.subject, error.message)
    checked_experiment = check_experiment_inputs(
        inp.specification, inp.rir, authority_context=context
    )
    if isinstance(checked_experiment, Schema2RefusalReport):
        return checked_experiment
    claim_kind = evidence_claim_kind(checked_experiment.language_bundle, inp.claim_kind)
    if claim_kind is None:
        return unknown_evidence_claim_kind_refusal(
            checked_experiment.language_bundle,
            inp.claim_kind,
        )
    graph = project_evidence_graph(
        claim_kind,
        EvidenceGraphProjectionInput(
            rir_semantic_identity=cast(
                str, checked_experiment.rir["semantic_identity"]
            ),
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
            result, checked_experiment.language_bundle, identities
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
