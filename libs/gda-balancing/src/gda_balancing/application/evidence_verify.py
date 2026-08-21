"""Verify one exact Evidence prerequisite graph without issuing Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bound_diagnostics,
    ingress_refusal,
    reason_by_id,
)
from gda_balancing.domain.evidence import validate_experiment_artifact_set
from gda_balancing.domain.evidence_verification import (
    EvidenceCandidate,
    EvidenceGraph,
    EvidencePrerequisite,
    EvidenceSubject,
    EvidenceVerificationIssue,
    evaluate_evidence_candidate,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source,
    project_compiled_model_binding,
    validate_compiled_artifacts,
)
from gda_balancing.domain.publication import read_authenticated_artifact_set
from gda_balancing.domain.publication_types import PublicationAdmissionError


@dataclass(frozen=True)
class EvidenceVerifyInput:
    """Explicit local inputs to one Evidence candidate judgment."""

    claim_kind: str
    source: str
    specification: str
    model_build_receipt: str
    experiment_outcome_receipt: str


def _refusal_for_issues(
    issues: tuple[EvidenceVerificationIssue, ...],
    language_bundle: dict[str, Any],
    identities: dict[str, str],
) -> Schema2RefusalReport:
    diagnostics: list[Schema2Diagnostic] = []
    for issue in issues:
        reason = reason_by_id(language_bundle, issue.reason)
        role = issue.subject.split("->", 1)[0].split(",", 1)[0]
        diagnostics.append(
            Schema2Diagnostic(
                code=cast(str, reason["diagnostic"]),
                message=issue.message,
                primary=ArtifactLocation(
                    content_identity=identities.get(role, "unidentified"),
                    pointer="/prerequisites/" + issue.subject.replace("->", "/"),
                ),
            )
        )
    bounded, truncated = bound_diagnostics(
        diagnostics,
        cast(int, language_bundle["resources"]["max_diagnostics"]),
    )
    return Schema2RefusalReport(
        stage="evaluation",
        diagnostics=bounded,
        truncated=truncated,
    )


def _claim_kind(
    language_bundle: dict[str, Any], claim_kind: str
) -> dict[str, Any] | None:
    matches = [
        item
        for item in cast(
            list[dict[str, Any]],
            language_bundle["language"]["evidence_claim_kinds"],
        )
        if item["id"] == claim_kind
    ]
    return matches[0] if len(matches) == 1 else None


def _unknown_claim_kind_refusal(
    language_bundle: dict[str, Any], claim_kind: str
) -> Schema2RefusalReport:
    reason = reason_by_id(
        language_bundle,
        "evaluation.reason.unknown-evidence-claim-kind",
    )
    return Schema2RefusalReport(
        stage="evaluation",
        diagnostics=(
            Schema2Diagnostic(
                code=cast(str, reason["diagnostic"]),
                message=f"Unknown Evidence claim kind: {claim_kind}",
                primary=ArtifactLocation(
                    content_identity="unidentified",
                    pointer="/claim_kind",
                ),
            ),
        ),
        truncated=False,
    )


def _authenticate_outcome(
    receipt_path: str,
    descriptor_identity: str,
    artifact_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
):
    last_error: PublicationAdmissionError | None = None
    for artifact_set in artifact_sets:
        try:
            return artifact_set, read_authenticated_artifact_set(
                receipt_path,
                descriptor_identity,
                artifact_set,
            )
        except PublicationAdmissionError as error:
            last_error = error
    assert last_error is not None
    raise last_error


def verify_evidence(
    inp: EvidenceVerifyInput,
    *,
    model_build_descriptor_identity: str,
    experiment_run_descriptor_identity: str,
    model_build_artifact_set: tuple[ArtifactSetMemberSpec, ...],
    experiment_outcome_artifact_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
) -> EvidenceCandidate | Schema2RefusalReport:
    """Re-admit exact publications and derive one candidate/open judgment."""
    checked_model = check_model_source(inp.source)
    if isinstance(checked_model, Schema2RefusalReport):
        return checked_model
    assert isinstance(checked_model, CheckedModel)
    claim_kind = _claim_kind(checked_model.language_bundle, inp.claim_kind)
    if claim_kind is None:
        return _unknown_claim_kind_refusal(
            checked_model.language_bundle,
            inp.claim_kind,
        )
    try:
        model_publication = read_authenticated_artifact_set(
            inp.model_build_receipt,
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
    except (RuntimeError, ValueError):
        issue = EvidenceVerificationIssue(
            reason="evaluation.reason.evaluable-mismatched-prerequisite",
            subject="model-build-receipt",
            message="Model build publication does not bind the admitted Model Source",
        )
        return _refusal_for_issues(
            (issue,),
            model_publication.authority_context.language_bundle,
            {
                "model-build-receipt": cast(
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
        artifact_set, outcome_publication = _authenticate_outcome(
            inp.experiment_outcome_receipt,
            experiment_run_descriptor_identity,
            experiment_outcome_artifact_sets,
        )
    except PublicationAdmissionError as error:
        return ingress_refusal(error.code, error.subject, error.message)
    logical_names = {member.logical_name for member in artifact_set}
    if "evaluation-run" in logical_names:
        producing_outcome = "success"
        runtime_refusal_variant = "not-applicable"
    elif "experiment-verdict" in logical_names:
        producing_outcome = "verdict"
        runtime_refusal_variant = "not-applicable"
    else:
        producing_outcome = "runtime-refusal"
        runtime_refusal_variant = "post-dispatch"
    artifacts = outcome_publication.artifacts
    build_record = model_publication.artifacts["build-receipt"]
    resolved_model = model_publication.artifacts["resolved-model"]
    evaluator_manifest = artifacts["evaluator-capability-manifest"]
    runtime_profile = artifacts["resolved-runtime-profile"]
    reproduction_receipt = artifacts["reproduction-receipt"]
    identities = {
        "kernel": cast(str, checked_model.kernel["content_identity"]),
        "language-bundle": cast(str, checked_model.language_bundle["content_identity"]),
        "model-source": checked_model.source_identity,
        "resolved-model": cast(str, resolved_model["content_identity"]),
        "model-build-receipt": cast(str, model_publication.receipt["content_identity"]),
        "experiment": checked_experiment.content_identity,
        "evaluator-capability-manifest": cast(
            str, evaluator_manifest["content_identity"]
        ),
        "resolved-runtime-profile": cast(str, runtime_profile["content_identity"]),
        "experiment-outcome-receipt": cast(
            str, outcome_publication.receipt["content_identity"]
        ),
    }
    experiment_model = cast(dict[str, Any], checked_experiment.value["model"])
    model_receipt_binding = cast(str, experiment_model["build_receipt_identity"])
    if model_receipt_binding == build_record["content_identity"]:
        model_receipt_binding = identities["model-build-receipt"]
    observed_bindings = {
        "language-bundle": {
            "kernel": checked_model.language_bundle["kernel_identity"],
        },
        "resolved-model": {
            "kernel": resolved_model["kernel_identity"],
            "language-bundle": resolved_model["language_bundle_identity"],
            "model-source": build_record["source_identity"],
        },
        "model-build-receipt": {
            "model-source": build_record["source_identity"],
            "resolved-model": build_record["resolved_model_identity"],
        },
        "experiment": {
            "kernel": checked_experiment.value["kernel_identity"],
            "language-bundle": checked_experiment.value["language_bundle_identity"],
            "resolved-model": experiment_model["resolved_model_identity"],
        },
        "evaluator-capability-manifest": {
            "kernel": evaluator_manifest["kernel_identity"],
            "language-bundle": evaluator_manifest["language_bundle_identity"],
        },
        "resolved-runtime-profile": {
            "kernel": runtime_profile["kernel_identity"],
            "language-bundle": runtime_profile["language_bundle_identity"],
            "resolved-model": runtime_profile["resolved_model_identity"],
            "experiment": runtime_profile["experiment_identity"],
            "evaluator-capability-manifest": runtime_profile[
                "evaluator_manifest_identity"
            ],
        },
        "experiment-outcome-receipt": {
            "model-build-receipt": model_receipt_binding,
            "experiment": reproduction_receipt["experiment_identity"],
            "resolved-runtime-profile": reproduction_receipt[
                "resolved_runtime_profile_identity"
            ],
            "evaluator-capability-manifest": reproduction_receipt[
                "evaluator_manifest_identity"
            ],
        },
    }
    graph = EvidenceGraph(
        subjects=tuple(
            EvidenceSubject(role=role, identity=identities[role])
            for role in cast(list[str], claim_kind["subject_roles"])
        ),
        prerequisites=tuple(
            EvidencePrerequisite(
                subject=cast(str, edge["subject"]),
                subject_identity=identities[cast(str, edge["subject"])],
                prerequisite=cast(str, edge["prerequisite"]),
                prerequisite_identity=cast(
                    str,
                    observed_bindings.get(cast(str, edge["subject"]), {}).get(
                        cast(str, edge["prerequisite"]),
                        "unresolved",
                    ),
                ),
            )
            for edge in cast(list[dict[str, Any]], claim_kind["prerequisite_edges"])
        ),
        producing_outcome=producing_outcome,
        runtime_dispatch="reached",
        runtime_refusal_variant=runtime_refusal_variant,
    )
    result = evaluate_evidence_candidate(claim_kind, graph)
    if isinstance(result, tuple):
        return _refusal_for_issues(result, checked_model.language_bundle, identities)
    if not validate_experiment_artifact_set(
        checked_experiment, outcome_publication.artifacts
    ):
        issue = EvidenceVerificationIssue(
            reason="evaluation.reason.evaluable-mismatched-prerequisite",
            subject="experiment-outcome-receipt",
            message="Experiment outcome publication does not bind the admitted Experiment",
        )
        return _refusal_for_issues(
            (issue,),
            outcome_publication.authority_context.language_bundle,
            {"experiment-outcome-receipt": identities["experiment-outcome-receipt"]},
        )
    return result
