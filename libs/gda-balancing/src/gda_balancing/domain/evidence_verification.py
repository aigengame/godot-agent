"""Pure Evidence prerequisite-graph and candidate judgments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast

from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bound_diagnostics,
    reason_by_id,
)


@dataclass(frozen=True)
class EvidenceSubject:
    """One exact subject identity in an Evidence prerequisite graph."""

    role: str
    identity: str


@dataclass(frozen=True)
class EvidencePrerequisite:
    """One exact directed prerequisite binding between graph subjects."""

    subject: str
    subject_identity: str
    prerequisite: str
    prerequisite_identity: str


@dataclass(frozen=True)
class EvidenceGraph:
    """The exact graph and producing outcome presented for judgment."""

    subjects: tuple[EvidenceSubject, ...]
    prerequisites: tuple[EvidencePrerequisite, ...]
    producing_outcome: str
    runtime_dispatch: str
    runtime_refusal_variant: str


@dataclass(frozen=True)
class EvidenceGraphProjectionInput:
    """Exact admitted artifacts from which the Domain projects one Evidence graph."""

    kernel: Mapping[str, Any]
    language_bundle: Mapping[str, Any]
    model_source_identity: str
    model_build_artifact_set_receipt_identity: str
    model_artifacts: Mapping[str, Mapping[str, Any]]
    experiment_identity: str
    experiment: Mapping[str, Any]
    experiment_run_artifact_set_receipt_identity: str
    outcome_artifacts: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class EvidenceCandidate:
    """An open candidate judgment; this value is not Evidence."""

    claim_kind: str
    claim_state: str
    producing_outcome: str
    subjects: tuple[EvidenceSubject, ...]


@dataclass(frozen=True)
class EvidenceVerificationIssue:
    """One LDB-addressable fault in a candidate judgment."""

    reason: str
    subject: str
    message: str


def evidence_verification_refusal(
    issues: tuple[EvidenceVerificationIssue, ...],
    language_bundle: dict[str, Any],
    identities: Mapping[str, str],
) -> Schema2RefusalReport:
    """Project Domain-owned Evidence issues into one bounded refusal."""
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


def unknown_evidence_claim_kind_refusal(
    language_bundle: dict[str, Any], claim_kind: str
) -> Schema2RefusalReport:
    """Refuse a claim kind that the admitted LDB does not own."""
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


def evidence_verification_issue(
    kind: str, subject: str, message: str
) -> EvidenceVerificationIssue:
    """Create one LDB-addressable Evidence prerequisite issue."""
    return EvidenceVerificationIssue(
        reason=f"evaluation.reason.evaluable-{kind}-prerequisite",
        subject=subject,
        message=message,
    )


def evidence_claim_kind(
    language_bundle: Mapping[str, Any], claim_kind: str
) -> Mapping[str, Any] | None:
    """Select one exact LDB-owned Evidence claim kind."""
    language = cast(Mapping[str, Any], language_bundle["language"])
    matches = [
        item
        for item in cast(
            list[Mapping[str, Any]],
            language["evidence_claim_kinds"],
        )
        if item["id"] == claim_kind
    ]
    return matches[0] if len(matches) == 1 else None


def project_evidence_graph(
    claim_kind: Mapping[str, Any],
    inp: EvidenceGraphProjectionInput,
) -> EvidenceGraph:
    """Project exact admitted artifact bindings into one Evidence graph."""
    build_receipt_member = inp.model_artifacts["build-receipt"]
    resolved_model = inp.model_artifacts["resolved-model"]
    evaluator_manifest = inp.outcome_artifacts["evaluator-capability-manifest"]
    runtime_profile = inp.outcome_artifacts["resolved-runtime-profile"]
    reproduction_receipt = inp.outcome_artifacts["reproduction-receipt"]
    if "evaluation-run" in inp.outcome_artifacts:
        producing_outcome = "success"
        runtime_refusal_variant = "not-applicable"
    elif "experiment-verdict" in inp.outcome_artifacts:
        producing_outcome = "verdict"
        runtime_refusal_variant = "not-applicable"
    else:
        producing_outcome = "runtime-refusal"
        runtime_refusal_variant = "post-dispatch"

    identities = {
        "kernel": cast(str, inp.kernel["content_identity"]),
        "language-bundle": cast(str, inp.language_bundle["content_identity"]),
        "model-source": inp.model_source_identity,
        "resolved-model": cast(str, resolved_model["content_identity"]),
        "model-build-artifact-set-receipt": inp.model_build_artifact_set_receipt_identity,
        "experiment": inp.experiment_identity,
        "evaluator-capability-manifest": cast(
            str, evaluator_manifest["content_identity"]
        ),
        "resolved-runtime-profile": cast(str, runtime_profile["content_identity"]),
        "experiment-run-artifact-set-receipt": inp.experiment_run_artifact_set_receipt_identity,
    }
    experiment_model = cast(Mapping[str, Any], inp.experiment["model"])
    experiment_build_receipt_member_identity = cast(
        str, experiment_model["build_receipt_identity"]
    )
    observed_model_build_artifact_set_receipt_identity = (
        inp.model_build_artifact_set_receipt_identity
        if experiment_build_receipt_member_identity
        == build_receipt_member["content_identity"]
        else experiment_build_receipt_member_identity
    )
    observed_bindings = {
        "language-bundle": {
            "kernel": inp.language_bundle["kernel_identity"],
        },
        "resolved-model": {
            "kernel": resolved_model["kernel_identity"],
            "language-bundle": resolved_model["language_bundle_identity"],
            "model-source": build_receipt_member["source_identity"],
        },
        "model-build-artifact-set-receipt": {
            "model-source": build_receipt_member["source_identity"],
            "resolved-model": build_receipt_member["resolved_model_identity"],
        },
        "experiment": {
            "kernel": inp.experiment["kernel_identity"],
            "language-bundle": inp.experiment["language_bundle_identity"],
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
        "experiment-run-artifact-set-receipt": {
            "model-build-artifact-set-receipt": (
                observed_model_build_artifact_set_receipt_identity
            ),
            "experiment": reproduction_receipt["experiment_identity"],
            "resolved-runtime-profile": reproduction_receipt[
                "resolved_runtime_profile_identity"
            ],
            "evaluator-capability-manifest": reproduction_receipt[
                "evaluator_manifest_identity"
            ],
        },
    }
    return EvidenceGraph(
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
            for edge in cast(list[Mapping[str, Any]], claim_kind["prerequisite_edges"])
        ),
        producing_outcome=producing_outcome,
        runtime_dispatch="reached",
        runtime_refusal_variant=runtime_refusal_variant,
    )


def _cyclic_roles(edges: set[tuple[str, str]]) -> set[str]:
    dependencies: dict[str, set[str]] = {}
    for subject, prerequisite in edges:
        dependencies.setdefault(subject, set()).add(prerequisite)
        dependencies.setdefault(prerequisite, set())
    visiting: set[str] = set()
    visited: set[str] = set()
    cyclic: set[str] = set()

    def visit(role: str, path: tuple[str, ...]) -> None:
        if role in visiting:
            start = path.index(role)
            cyclic.update(path[start:])
            return
        if role in visited:
            return
        visiting.add(role)
        for prerequisite in sorted(dependencies.get(role, ())):
            visit(prerequisite, (*path, prerequisite))
        visiting.remove(role)
        visited.add(role)

    for role in sorted(dependencies):
        visit(role, (role,))
    return cyclic


def _graph_issues(
    claim_kind: Mapping[str, Any], graph: EvidenceGraph
) -> tuple[EvidenceVerificationIssue, ...]:
    expected_roles = tuple(cast(list[str], claim_kind["subject_roles"]))
    expected_role_set = set(expected_roles)
    subjects: dict[str, EvidenceSubject] = {}
    issues: list[EvidenceVerificationIssue] = []
    for subject in graph.subjects:
        if subject.role in subjects:
            issues.append(
                evidence_verification_issue(
                    "mismatched",
                    subject.role,
                    "Evidence prerequisite graph repeats one subject role",
                )
            )
            continue
        subjects[subject.role] = subject
    for role in sorted(expected_role_set - set(subjects)):
        issues.append(
            evidence_verification_issue(
                "missing",
                role,
                "Evidence prerequisite graph is missing one required subject",
            )
        )
    for role in sorted(set(subjects) - expected_role_set):
        issues.append(
            evidence_verification_issue(
                "extra",
                role,
                "Evidence prerequisite graph contains an undeclared subject",
            )
        )

    expected_edges = {
        (cast(str, edge["subject"]), cast(str, edge["prerequisite"]))
        for edge in cast(list[dict[str, Any]], claim_kind["prerequisite_edges"])
    }
    actual_edges = {(edge.subject, edge.prerequisite) for edge in graph.prerequisites}
    for subject, prerequisite in sorted(expected_edges - actual_edges):
        issues.append(
            evidence_verification_issue(
                "missing",
                f"{subject}->{prerequisite}",
                "Evidence prerequisite graph is missing one required edge",
            )
        )
    for subject, prerequisite in sorted(actual_edges - expected_edges):
        issues.append(
            evidence_verification_issue(
                "extra",
                f"{subject}->{prerequisite}",
                "Evidence prerequisite graph contains an undeclared edge",
            )
        )
    for edge in graph.prerequisites:
        subject = subjects.get(edge.subject)
        prerequisite = subjects.get(edge.prerequisite)
        if subject is None or prerequisite is None:
            issues.append(
                evidence_verification_issue(
                    "unresolved",
                    f"{edge.subject}->{edge.prerequisite}",
                    "Evidence prerequisite edge does not resolve to graph subjects",
                )
            )
            continue
        if (
            edge.subject_identity != subject.identity
            or edge.prerequisite_identity != prerequisite.identity
        ):
            issues.append(
                evidence_verification_issue(
                    "mismatched",
                    f"{edge.subject}->{edge.prerequisite}",
                    "Evidence prerequisite edge does not bind the subject identities",
                )
            )
    resolved_edges = {
        (edge.subject, edge.prerequisite)
        for edge in graph.prerequisites
        if edge.subject in subjects and edge.prerequisite in subjects
    }
    cycle = _cyclic_roles(resolved_edges)
    if cycle:
        issues.append(
            evidence_verification_issue(
                "cyclic",
                ",".join(sorted(cycle)),
                "Evidence prerequisite graph contains a cycle",
            )
        )
    return tuple(sorted(set(issues), key=lambda issue: (issue.reason, issue.subject)))


def evaluate_evidence_candidate(
    claim_kind: Mapping[str, Any], graph: EvidenceGraph
) -> EvidenceCandidate | tuple[EvidenceVerificationIssue, ...]:
    """Evaluate one graph under its admitted LDB claim-kind definition."""
    issues = _graph_issues(claim_kind, graph)
    if issues:
        return issues
    eligibility = cast(Mapping[str, Any], claim_kind["eligibility"])
    producing_outcomes = set(cast(list[str], eligibility.get("producing_outcomes", [])))
    runtime_refusal_variant = cast(str, eligibility.get("runtime_refusal_variant", ""))
    eligible = (
        graph.producing_outcome in producing_outcomes
        and (
            eligibility.get("runtime_dispatch") != "required"
            or graph.runtime_dispatch == "reached"
        )
        and (
            (
                graph.producing_outcome == "runtime-refusal"
                and graph.runtime_refusal_variant == runtime_refusal_variant
            )
            or (
                graph.producing_outcome != "runtime-refusal"
                and graph.runtime_refusal_variant == "not-applicable"
            )
        )
    )
    if not eligible:
        return (
            EvidenceVerificationIssue(
                reason="evaluation.reason.evaluable-ineligible-outcome",
                subject=graph.producing_outcome,
                message=(
                    "Producing outcome did not reach the LDB-required Runtime "
                    "dispatch boundary"
                ),
            ),
        )
    return EvidenceCandidate(
        claim_kind=cast(str, claim_kind["id"]),
        claim_state=cast(str, eligibility["claim_state"]),
        producing_outcome=graph.producing_outcome,
        subjects=graph.subjects,
    )
