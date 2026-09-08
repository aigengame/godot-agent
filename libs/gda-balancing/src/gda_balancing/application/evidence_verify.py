"""Verify one authenticated Experiment outcome without issuing Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.domain.artifact_set import ArtifactSetPlan
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport, ingress_refusal
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.evidence_verification import (
    EvidenceCandidate,
    evidence_claim_kind,
    evidence_outcome_mismatch_refusal,
    evaluate_evidence_candidate,
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
    experiment_run_artifact_sets: tuple[ArtifactSetPlan, ...],
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
    if not validate_experiment_artifact_set(
        checked_experiment, outcome_publication.artifacts
    ):
        return evidence_outcome_mismatch_refusal(
            checked_experiment.language_bundle,
            cast(str, outcome_publication.receipt["content_identity"]),
        )
    return evaluate_evidence_candidate(
        claim_kind, checked_experiment, outcome_publication
    )
