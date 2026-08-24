"""Schema 2.0 Evidence candidate verification."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.application.evidence_verify as evidence_verify_module
from gda_balancing.application.evidence_verify import (
    EvidenceVerifyInput,
    verify_evidence,
)
from gda_balancing.application.experiment_run import (
    ExperimentRunPublication,
    ExperimentVerdictPublication,
    run_experiment,
)
from gda_balancing.domain.artifacts import (
    identified_artifact,
    verify_artifact,
    wire_schema_identity,
)
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2RefusalReport,
    reason_by_id,
)
from gda_balancing.domain.evidence_verification import (
    EvidenceGraphProjectionInput,
    EvidenceCandidate,
    EvidenceGraph,
    EvidencePrerequisite,
    EvidenceSubject,
    EvidenceVerificationIssue,
    evidence_claim_kind,
    evaluate_evidence_candidate,
    project_evidence_graph,
)
from gda_balancing.domain.model import ExactResolvedModelBindingError
from gda_balancing.domain.publication import (
    publish_artifact_set,
    read_authenticated_artifact_set,
)
from gda_balancing.domain.publication_types import PublicationMember
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_runtime_refusal_experiment,
    prepare_valid_experiment,
    prepare_verdict_experiment,
)
from gda_balancing.interfaces.cli.descriptors import artifact_sets_for_input
from gda_balancing.interfaces.cli.evidence_verify import EVIDENCE_VERIFY
from gda_balancing.interfaces.cli.experiment_run import EXPERIMENT_RUN
from gda_balancing.interfaces.cli.surface import descriptor_identity


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


def _verify(inp: EvidenceVerifyInput) -> EvidenceCandidate | Schema2RefusalReport:
    inputs = {item.receipt_field: item for item in EVIDENCE_VERIFY.input_artifact_sets}
    model_build_input = inputs["model_build_receipt"]
    experiment_outcome_input = inputs["experiment_outcome_receipt"]
    return verify_evidence(
        inp,
        model_build_descriptor_identity=descriptor_identity(model_build_input.producer),
        experiment_run_descriptor_identity=descriptor_identity(
            experiment_outcome_input.producer
        ),
        model_build_artifact_set=artifact_sets_for_input(model_build_input)[0],
        experiment_outcome_artifact_sets=artifact_sets_for_input(
            experiment_outcome_input
        ),
    )


def _prepare_outcome_input(
    tmp_path: Path, token: int, *, verdict: bool = False
) -> EvidenceVerifyInput:
    prepare = prepare_verdict_experiment if verdict else prepare_valid_experiment
    specification_value = prepare(tmp_path, token)
    specification_path = tmp_path / "experiment.json"
    specification_path.write_text(specification_value, encoding="utf-8")
    outcome_path = tmp_path / "experiment-outcome.json"
    outcome_receipt_path = tmp_path / "experiment-outcome-receipt.json"
    publication = run_experiment(
        str(specification_path),
        str(outcome_path),
        "e" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        EXPERIMENT_RUN.artifact_set,
        cast(tuple[Any, ...], EXPERIMENT_RUN.verdict_artifact_set),
        EXPERIMENT_RUN.refusal_artifact_sets[0].members,
    )
    expected_type = (
        ExperimentVerdictPublication if verdict else ExperimentRunPublication
    )
    assert isinstance(publication, expected_type)
    outcome_receipt_path.write_bytes(
        canonical_bytes(cast(JsonValue, publication.receipt))
    )
    return EvidenceVerifyInput(
        claim_kind="evaluable",
        source=str(tmp_path / f"experiment-model-{token}.json"),
        specification=str(specification_path),
        model_build_receipt=str(tmp_path / f"experiment-model-{token}-receipt.json"),
        experiment_outcome_receipt=str(outcome_receipt_path),
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


def test_domain_projects_exact_artifacts_into_the_evaluable_graph() -> None:
    complete = _complete_graph()
    identities = {subject.role: subject.identity for subject in complete.subjects}
    claim_kind = evidence_claim_kind(
        packaged_authority_context().language_bundle,
        "evaluable",
    )
    assert claim_kind is not None

    graph = project_evidence_graph(
        claim_kind,
        EvidenceGraphProjectionInput(
            kernel={"content_identity": identities["kernel"]},
            language_bundle={
                "content_identity": identities["language-bundle"],
                "kernel_identity": identities["kernel"],
            },
            model_source_identity=identities["model-source"],
            model_build_receipt_identity=identities["model-build-receipt"],
            model_artifacts={
                "resolved-model": {
                    "content_identity": identities["resolved-model"],
                    "kernel_identity": identities["kernel"],
                    "language_bundle_identity": identities["language-bundle"],
                },
                "build-receipt": {
                    "content_identity": "sha256:" + "a" * 64,
                    "source_identity": identities["model-source"],
                    "resolved_model_identity": identities["resolved-model"],
                },
            },
            experiment_identity=identities["experiment"],
            experiment={
                "kernel_identity": identities["kernel"],
                "language_bundle_identity": identities["language-bundle"],
                "model": {
                    "resolved_model_identity": identities["resolved-model"],
                    "build_receipt_identity": "sha256:" + "a" * 64,
                },
            },
            experiment_outcome_receipt_identity=identities[
                "experiment-outcome-receipt"
            ],
            outcome_artifacts={
                "evaluation-run": {},
                "evaluator-capability-manifest": {
                    "content_identity": identities["evaluator-capability-manifest"],
                    "kernel_identity": identities["kernel"],
                    "language_bundle_identity": identities["language-bundle"],
                },
                "resolved-runtime-profile": {
                    "content_identity": identities["resolved-runtime-profile"],
                    "kernel_identity": identities["kernel"],
                    "language_bundle_identity": identities["language-bundle"],
                    "resolved_model_identity": identities["resolved-model"],
                    "experiment_identity": identities["experiment"],
                    "evaluator_manifest_identity": identities[
                        "evaluator-capability-manifest"
                    ],
                },
                "reproduction-receipt": {
                    "experiment_identity": identities["experiment"],
                    "resolved_runtime_profile_identity": identities[
                        "resolved-runtime-profile"
                    ],
                    "evaluator_manifest_identity": identities[
                        "evaluator-capability-manifest"
                    ],
                },
            },
        ),
    )

    assert graph == complete


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


def test_application_verifies_one_real_success_publication(
    tmp_path: Path,
) -> None:
    result = _verify(_prepare_outcome_input(tmp_path, 541))

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_kind == "evaluable"
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "success"


@pytest.mark.parametrize("error_type", (RuntimeError, ValueError))
def test_application_does_not_relabel_an_unexpected_model_validation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    inp = _prepare_outcome_input(tmp_path, 551)

    def fail_unexpectedly(*_args, **_kwargs) -> None:
        raise error_type("unexpected compiled-artifact validator defect")

    monkeypatch.setattr(
        evidence_verify_module,
        "validate_compiled_artifacts",
        fail_unexpectedly,
    )

    with pytest.raises(
        error_type,
        match="unexpected compiled-artifact validator defect",
    ):
        _verify(inp)


def test_application_maps_an_expected_exact_model_binding_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 552)

    def reject_binding(*_args, **_kwargs) -> None:
        raise ExactResolvedModelBindingError(
            "member-set-mismatch",
            "package-lock",
            "exact Model binding member set is not closed",
        )

    monkeypatch.setattr(
        evidence_verify_module,
        "project_compiled_model_binding",
        reject_binding,
    )

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "evaluation.evaluable_mismatched_prerequisite"
    ]


def test_application_uses_outcome_neutral_publication_diagnostics(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 542)
    invalid_receipt = tmp_path / "invalid-outcome-receipt.json"
    invalid_receipt.write_text("not JSON", encoding="utf-8")

    result = _verify(replace(inp, experiment_outcome_receipt=str(invalid_receipt)))

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "ingress"
    assert result.diagnostics[0].message == (
        "Artifact-set receipt is not an admissible JSON artifact"
    )


def test_application_refuses_an_unknown_evidence_claim_kind(tmp_path: Path) -> None:
    inp = _prepare_outcome_input(tmp_path, 543)

    result = _verify(replace(inp, claim_kind="unsupported"))

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert result.diagnostics[0].code == "evaluation.unknown_evidence_claim_kind"
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.pointer == "/claim_kind"


def test_application_refuses_a_source_changed_after_model_build(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 546)
    source_path = Path(inp.source)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["manifest"]["id"] = "example.changed-after-build"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert result.diagnostics[0].code == (
        "evaluation.evaluable_mismatched_prerequisite"
    )
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.pointer == (
        "/prerequisites/model-build-receipt"
    )


def test_application_refuses_an_unauthenticated_outcome_receipt(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 547)
    receipt_path = Path(inp.experiment_outcome_receipt)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["content_identity"] = "sha256:" + "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "ingress"
    assert result.diagnostics[0].code == "kernel.identity_mismatch"
    assert result.diagnostics[0].message == (
        "Artifact-set receipt failed exact-authority admission"
    )


def test_application_refuses_an_outcome_bound_to_another_experiment(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 548)
    specification_path = Path(inp.specification)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    specification["metrics"][0]["target"]["maximum"] = 999
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "evaluation.evaluable_mismatched_prerequisite"
    }
    artifact_locations = {
        diagnostic.primary.pointer
        for diagnostic in result.diagnostics
        if isinstance(diagnostic.primary, ArtifactLocation)
    }
    assert "/prerequisites/experiment-outcome-receipt/experiment" in (
        artifact_locations
    )


def test_application_verifies_one_real_verdict_publication(tmp_path: Path) -> None:
    result = _verify(_prepare_outcome_input(tmp_path, 544, verdict=True))

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "verdict"


def _prepare_runtime_refusal_input(tmp_path: Path, token: int) -> EvidenceVerifyInput:
    specification_value = prepare_runtime_refusal_experiment(tmp_path, token)
    specification_path = tmp_path / "experiment.json"
    specification_path.write_text(specification_value, encoding="utf-8")
    outcome_receipt_path = tmp_path / "experiment-outcome-receipt.json"
    refusal = run_experiment(
        str(specification_path),
        str(tmp_path / "runtime-refusal.json"),
        "f" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        EXPERIMENT_RUN.artifact_set,
        cast(tuple[Any, ...], EXPERIMENT_RUN.verdict_artifact_set),
        EXPERIMENT_RUN.refusal_artifact_sets[0].members,
    )
    assert isinstance(refusal, Schema2RefusalReport)
    assert refusal.variant == "post-dispatch"
    assert refusal.terminal_audit is not None
    outcome_receipt_path.write_bytes(
        canonical_bytes(cast(JsonValue, refusal.terminal_audit))
    )
    return EvidenceVerifyInput(
        claim_kind="evaluable",
        source=str(tmp_path / f"experiment-model-{token}.json"),
        specification=str(specification_path),
        model_build_receipt=str(tmp_path / f"experiment-model-{token}-receipt.json"),
        experiment_outcome_receipt=str(outcome_receipt_path),
    )


def test_application_verifies_one_real_post_dispatch_refusal_publication(
    tmp_path: Path,
) -> None:
    result = _verify(_prepare_runtime_refusal_input(tmp_path, 545))

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "runtime-refusal"


def test_application_refuses_an_authenticated_incomplete_terminal_audit(
    tmp_path: Path,
) -> None:
    inp = _prepare_runtime_refusal_input(tmp_path, 550)
    artifact_set = EXPERIMENT_RUN.refusal_artifact_sets[0].members
    admitted = read_authenticated_artifact_set(
        inp.experiment_outcome_receipt,
        descriptor_identity(EXPERIMENT_RUN),
        artifact_set,
    )
    values = deepcopy(admitted.artifacts)
    audit = values["runtime-terminal-audit"]
    audit_payload = {
        key: value
        for key, value in audit.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    audit_payload["reproduction_receipt_identity"] = "sha256:" + "0" * 64
    values["runtime-terminal-audit"] = cast(
        dict[str, Any],
        identified_artifact(
            admitted.authority_context.language_bundle,
            "runtime-terminal-audit",
            cast(dict[str, JsonValue], audit_payload),
        ),
    )
    members = {
        name: PublicationMember(
            value=value,
            artifact_kind=cast(str, value["artifact_kind"]),
            wire_schema_identity=wire_schema_identity(
                admitted.authority_context.language_bundle,
                cast(str, value["artifact_kind"]),
            ),
            content_identity=cast(str, value["content_identity"]),
        )
        for name, value in values.items()
    }
    malformed_receipt = publish_artifact_set(
        members,
        str(tmp_path / "malformed-runtime-refusal.json"),
        "a" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        "sha256:" + "1" * 64,
        admitted.authority_context.language_bundle,
        artifact_set,
        lambda _name, value: verify_artifact(
            value, admitted.authority_context.language_bundle
        ),
    )
    malformed_receipt_path = tmp_path / "malformed-runtime-refusal-receipt.json"
    malformed_receipt_path.write_bytes(
        canonical_bytes(cast(JsonValue, malformed_receipt))
    )

    result = _verify(
        replace(
            inp,
            experiment_outcome_receipt=str(malformed_receipt_path),
        )
    )

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert result.diagnostics[0].code == (
        "evaluation.evaluable_mismatched_prerequisite"
    )
