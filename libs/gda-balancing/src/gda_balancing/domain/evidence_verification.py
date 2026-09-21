"""Eligibility judgments for validated Experiment outcome publications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, cast

from gda_balancing.domain.artifacts import artifacts_by_protocol_role
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    reason_by_id,
)

if TYPE_CHECKING:
    from gda_balancing.domain.experiment import CheckedExperiment
    from gda_balancing.domain.publication import AuthenticatedArtifactSet


@dataclass(frozen=True)
class EvidenceCandidate:
    """An open candidate judgment; this value is not Evidence."""

    claim_kind: str
    claim_state: str
    producing_outcome: str
    rir_semantic_identity: str
    experiment_identity: str
    resolved_runtime_profile_identity: str
    evaluator_capability_manifest_identity: str
    experiment_run_artifact_set_receipt_identity: str


def _refusal(
    language_bundle: dict[str, Any],
    reason_id: str,
    identity: str,
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    reason = reason_by_id(language_bundle, reason_id)
    return Schema2RefusalReport(
        stage="evaluation",
        diagnostics=(
            Schema2Diagnostic(
                code=cast(str, reason["diagnostic"]),
                message=message,
                primary=ArtifactLocation(content_identity=identity, pointer=pointer),
            ),
        ),
        truncated=False,
    )


def evidence_outcome_mismatch_refusal(
    language_bundle: dict[str, Any], receipt_identity: str
) -> Schema2RefusalReport:
    """Refuse a publication that fails complete Experiment outcome admission."""
    return _refusal(
        language_bundle,
        "evaluation.reason.evaluable-outcome-mismatch",
        receipt_identity,
        "/experiment-run-artifact-set-receipt",
        "Experiment outcome publication does not bind the admitted Experiment",
    )


def unknown_evidence_claim_kind_refusal(
    language_bundle: dict[str, Any], claim_kind: str
) -> Schema2RefusalReport:
    """Refuse a claim kind that the admitted LDB does not own."""
    return _refusal(
        language_bundle,
        "evaluation.reason.unknown-evidence-claim-kind",
        "unidentified",
        "/claim_kind",
        f"Unknown Evidence claim kind: {claim_kind}",
    )


def evidence_claim_kind(
    language_bundle: Mapping[str, Any], claim_kind: str
) -> Mapping[str, Any] | None:
    """Select one exact LDB-owned Evidence claim kind."""
    language = cast(Mapping[str, Any], language_bundle["language"])
    matches = [
        item
        for item in cast(list[Mapping[str, Any]], language["evidence_claim_kinds"])
        if item["id"] == claim_kind
    ]
    return matches[0] if len(matches) == 1 else None


def evaluate_evidence_candidate(
    claim_kind: Mapping[str, Any],
    checked: CheckedExperiment,
    publication: AuthenticatedArtifactSet,
) -> EvidenceCandidate | Schema2RefusalReport:
    """Judge eligibility after the existing complete-set semantic admission.

    Application authenticates the publication and validates its whole outcome
    against ``checked`` before calling this function. Outcome and dispatch are
    derived from those admitted members, never supplied as caller flags.
    """
    artifacts = artifacts_by_protocol_role(
        checked.language_bundle, publication.artifacts
    )
    if "evaluation-run" in artifacts:
        producing_outcome = "success"
        refusal_variant = "not-applicable"
    elif "experiment-verdict" in artifacts:
        producing_outcome = "verdict"
        refusal_variant = "not-applicable"
    elif "runtime-terminal-audit" in artifacts:
        # Complete terminal-audit admission establishes the post-dispatch variant;
        # a pre-dispatch refusal has no admissible Experiment outcome ArtifactSet.
        producing_outcome = "runtime-refusal"
        refusal_variant = "post-dispatch"
    else:
        raise ValueError("Evidence eligibility requires an admitted Runtime outcome")
    eligibility = cast(Mapping[str, Any], claim_kind["eligibility"])
    if producing_outcome not in eligibility["producing_outcomes"] or (
        producing_outcome == "runtime-refusal"
        and refusal_variant != eligibility["runtime_refusal_variant"]
    ):
        return _refusal(
            checked.language_bundle,
            "evaluation.reason.evaluable-ineligible-outcome",
            cast(str, publication.receipt["content_identity"]),
            "/producing_outcome",
            "Producing outcome is not eligible for the selected Evidence claim",
        )
    return EvidenceCandidate(
        claim_kind=cast(str, claim_kind["id"]),
        claim_state=cast(str, eligibility["claim_state"]),
        producing_outcome=producing_outcome,
        rir_semantic_identity=cast(str, checked.rir["semantic_identity"]),
        experiment_identity=checked.content_identity,
        resolved_runtime_profile_identity=cast(
            str, artifacts["resolved-runtime-profile"]["content_identity"]
        ),
        evaluator_capability_manifest_identity=cast(
            str, artifacts["evaluator-capability-manifest"]["content_identity"]
        ),
        experiment_run_artifact_set_receipt_identity=cast(
            str, publication.receipt["content_identity"]
        ),
    )
