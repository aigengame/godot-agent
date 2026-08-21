"""Schema 2.0 Evidence candidate verification."""

from typing import Any, cast

import pytest

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import reason_by_id
from gda_balancing.domain.evidence_verification import (
    EvidenceCandidate,
    EvidenceGraph,
    EvidencePrerequisite,
    EvidenceSubject,
    EvidenceVerificationIssue,
    evaluate_evidence_candidate,
)


def _evaluable_claim_kind() -> dict[str, Any]:
    language = packaged_authority_context().language_bundle["language"]
    return cast(dict[str, Any], language["evidence_claim_kinds"][0])


def _complete_graph() -> EvidenceGraph:
    claim_kind = _evaluable_claim_kind()
    identities = {
        role: f"sha256:{index:064x}"
        for index, role in enumerate(claim_kind["subject_roles"], start=1)
    }
    return EvidenceGraph(
        subjects=tuple(
            EvidenceSubject(role=role, identity=identity)
            for role, identity in identities.items()
        ),
        prerequisites=tuple(
            EvidencePrerequisite(
                subject=edge["subject"],
                subject_identity=identities[edge["subject"]],
                prerequisite=edge["prerequisite"],
                prerequisite_identity=identities[edge["prerequisite"]],
            )
            for edge in claim_kind["prerequisite_edges"]
        ),
        producing_outcome="success",
        runtime_dispatch="reached",
        runtime_refusal_variant="not-applicable",
    )


def test_packaged_ldb_owns_the_complete_evaluable_claim_kind() -> None:
    language = packaged_authority_context().language_bundle["language"]

    assert language["evidence_claim_kinds"] == [
        {
            "id": "evaluable",
            "version": "1.0.0",
            "subject_roles": [
                "kernel",
                "language-bundle",
                "model-source",
                "resolved-model",
                "model-build-receipt",
                "experiment",
                "evaluator-capability-manifest",
                "resolved-runtime-profile",
                "experiment-outcome-receipt",
            ],
            "prerequisite_edges": [
                {"subject": "language-bundle", "prerequisite": "kernel"},
                {"subject": "resolved-model", "prerequisite": "kernel"},
                {
                    "subject": "resolved-model",
                    "prerequisite": "language-bundle",
                },
                {"subject": "resolved-model", "prerequisite": "model-source"},
                {
                    "subject": "model-build-receipt",
                    "prerequisite": "model-source",
                },
                {
                    "subject": "model-build-receipt",
                    "prerequisite": "resolved-model",
                },
                {"subject": "experiment", "prerequisite": "kernel"},
                {"subject": "experiment", "prerequisite": "language-bundle"},
                {"subject": "experiment", "prerequisite": "resolved-model"},
                {
                    "subject": "evaluator-capability-manifest",
                    "prerequisite": "kernel",
                },
                {
                    "subject": "evaluator-capability-manifest",
                    "prerequisite": "language-bundle",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "kernel",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "language-bundle",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "resolved-model",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "experiment",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "evaluator-capability-manifest",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "model-build-receipt",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "experiment",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "resolved-runtime-profile",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "evaluator-capability-manifest",
                },
            ],
            "eligibility": {
                "claim_state": "candidate",
                "runtime_dispatch": "required",
                "producing_outcomes": ["runtime-refusal", "success", "verdict"],
                "runtime_refusal_variant": "post-dispatch",
            },
            "permitted_issuer_classes": [],
            "permitted_verifier_classes": [],
            "vectors": [
                {
                    "id": "evaluable.success",
                    "kind": "positive",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "success",
                        "runtime_dispatch": "reached",
                        "runtime_refusal_variant": "not-applicable",
                    },
                    "expect": "candidate",
                },
                {
                    "id": "evaluable.verdict",
                    "kind": "positive",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "verdict",
                        "runtime_dispatch": "reached",
                        "runtime_refusal_variant": "not-applicable",
                    },
                    "expect": "candidate",
                },
                {
                    "id": "evaluable.runtime-refusal",
                    "kind": "positive",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "runtime-refusal",
                        "runtime_dispatch": "reached",
                        "runtime_refusal_variant": "post-dispatch",
                    },
                    "expect": "candidate",
                },
                {
                    "id": "evaluable.pre-dispatch",
                    "kind": "negative",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "runtime-refusal",
                        "runtime_dispatch": "not-reached",
                        "runtime_refusal_variant": "pre-dispatch",
                    },
                    "expect": "refusal",
                },
                *[
                    {
                        "id": f"evaluable.graph-{graph}",
                        "kind": "negative",
                        "input": {
                            "graph": graph,
                            "producing_outcome": "success",
                            "runtime_dispatch": "reached",
                            "runtime_refusal_variant": "not-applicable",
                        },
                        "expect": "refusal",
                    }
                    for graph in (
                        "missing",
                        "extra",
                        "mismatched",
                        "cyclic",
                        "unresolved",
                    )
                ],
            ],
        }
    ]


def test_complete_success_graph_is_an_open_evaluable_candidate() -> None:
    result = evaluate_evidence_candidate(_evaluable_claim_kind(), _complete_graph())

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_kind == "evaluable"
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "success"
    assert result.subjects == _complete_graph().subjects


def test_graph_judgment_reports_all_structural_fault_classes_in_order() -> None:
    complete = _complete_graph()
    subjects = tuple(
        subject for subject in complete.subjects if subject.role != "model-source"
    ) + (EvidenceSubject("unexpected", "sha256:" + "f" * 64),)
    prerequisites = list(complete.prerequisites)
    prerequisites.remove(
        next(
            edge
            for edge in prerequisites
            if edge.subject == "resolved-model" and edge.prerequisite == "model-source"
        )
    )
    first = prerequisites[0]
    prerequisites[0] = EvidencePrerequisite(
        subject=first.subject,
        subject_identity="sha256:" + "e" * 64,
        prerequisite=first.prerequisite,
        prerequisite_identity=first.prerequisite_identity,
    )
    identities = {subject.role: subject.identity for subject in subjects}
    prerequisites.extend(
        (
            EvidencePrerequisite(
                subject="kernel",
                subject_identity=identities["kernel"],
                prerequisite="language-bundle",
                prerequisite_identity=identities["language-bundle"],
            ),
            EvidencePrerequisite(
                subject="unknown",
                subject_identity="sha256:" + "d" * 64,
                prerequisite="kernel",
                prerequisite_identity=identities["kernel"],
            ),
        )
    )
    graph = EvidenceGraph(
        subjects=subjects,
        prerequisites=tuple(prerequisites),
        producing_outcome=complete.producing_outcome,
        runtime_dispatch=complete.runtime_dispatch,
        runtime_refusal_variant=complete.runtime_refusal_variant,
    )

    result = evaluate_evidence_candidate(_evaluable_claim_kind(), graph)

    assert isinstance(result, tuple)
    assert all(isinstance(issue, EvidenceVerificationIssue) for issue in result)
    assert {issue.reason for issue in result} == {
        "evaluation.reason.evaluable-cyclic-prerequisite",
        "evaluation.reason.evaluable-extra-prerequisite",
        "evaluation.reason.evaluable-mismatched-prerequisite",
        "evaluation.reason.evaluable-missing-prerequisite",
        "evaluation.reason.evaluable-unresolved-prerequisite",
    }
    assert result == tuple(
        sorted(result, key=lambda issue: (issue.reason, issue.subject))
    )


@pytest.mark.parametrize(
    ("producing_outcome", "runtime_dispatch", "runtime_refusal_variant", "eligible"),
    (
        ("success", "reached", "not-applicable", True),
        ("verdict", "reached", "not-applicable", True),
        ("runtime-refusal", "reached", "post-dispatch", True),
        ("runtime-refusal", "not-reached", "pre-dispatch", False),
    ),
)
def test_evaluable_eligibility_requires_runtime_dispatch(
    producing_outcome: str,
    runtime_dispatch: str,
    runtime_refusal_variant: str,
    eligible: bool,
) -> None:
    complete = _complete_graph()
    graph = EvidenceGraph(
        subjects=complete.subjects,
        prerequisites=complete.prerequisites,
        producing_outcome=producing_outcome,
        runtime_dispatch=runtime_dispatch,
        runtime_refusal_variant=runtime_refusal_variant,
    )

    result = evaluate_evidence_candidate(_evaluable_claim_kind(), graph)

    if eligible:
        assert isinstance(result, EvidenceCandidate)
        assert result.producing_outcome == producing_outcome
    else:
        assert isinstance(result, tuple)
        assert [issue.reason for issue in result] == [
            "evaluation.reason.evaluable-ineligible-outcome"
        ]


def test_evaluable_faults_use_ldb_owned_evaluation_reasons() -> None:
    language_bundle = packaged_authority_context().language_bundle

    for suffix in (
        "cyclic-prerequisite",
        "extra-prerequisite",
        "ineligible-outcome",
        "mismatched-prerequisite",
        "missing-prerequisite",
        "unresolved-prerequisite",
    ):
        reason = reason_by_id(
            language_bundle,
            f"evaluation.reason.evaluable-{suffix}",
        )
        assert reason["stage"] == "evaluation"
        assert reason["diagnostic"] == "evaluation.evaluable_" + suffix.replace(
            "-", "_"
        )
