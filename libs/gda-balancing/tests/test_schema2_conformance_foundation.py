"""Permanent verified-artifact claim aggregation candidate tests."""

import json
from typing import Literal

import pytest
from pydantic import ValidationError

from gda_balancing.schema2.conformance import (
    MAX_ARTIFACT_JSON_DEPTH,
    MAX_ARTIFACT_PAYLOAD_BYTES,
    MAX_CLAIM_FACTS,
    OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
    VECTOR_RESULT_WIRE_SCHEMA_IDENTITY,
    CanonicalArtifactEnvelope,
    ClaimCandidateEvidence,
    ClaimCandidateReport,
    ClaimCandidateRequirement,
    Disposition,
    ExactSubjectIdentities,
    OperationAdmissionPayload,
    OperationRequirement,
    PublicObservableRequirement,
    PublicArtifactKind,
    ResearchEvidence,
    VectorRequirement,
    VectorRole,
    VectorResultPayload,
    artifact_content_identity,
    assess_claim_candidate,
    canonical_candidate_report,
    claim_definition_identity,
    make_artifact_envelope,
)


PUBLIC_WIRE_SCHEMA_IDENTITY = "sha256:" + "e" * 64


def _identity(digit: str) -> str:
    return f"sha256:{digit * 64}"


def _subject(*, ldb: str = "2", resolved_model: str = "5") -> ExactSubjectIdentities:
    return ExactSubjectIdentities(
        kernel_specification=_identity("1"),
        language_definition_bundle=_identity(ldb),
        package_lock=_identity("3"),
        rir_semantic_payload=_identity("4"),
        resolved_model=_identity(resolved_model),
        resolved_runtime_profile=_identity("6"),
        experiment_specification=_identity("7"),
    )


def _requirement(
    *, subject: ExactSubjectIdentities | None = None
) -> ClaimCandidateRequirement:
    return ClaimCandidateRequirement(
        schema_version="schema2-claim-candidate-requirement/1",
        claim_id="TRACE-RESOURCE-01",
        subject=subject or _subject(),
        operations=(
            OperationRequirement(
                operation_id="game.resource.reserve@1",
                package_release_identity=_identity("8"),
            ),
        ),
        vectors=(
            VectorRequirement(
                vector_id="trace.resource.reserve-positive-v1",
                role="positive",
                expected_disposition="success",
            ),
            VectorRequirement(
                vector_id="trace.resource.insufficient-outcome-v1",
                role="negative",
                expected_disposition="outcome",
            ),
        ),
        public_observables=(
            PublicObservableRequirement(
                field_id="trace.reservation_id",
                source_vector_id="trace.resource.reserve-positive-v1",
                artifact_kind="evaluation_run",
                wire_schema_identity=PUBLIC_WIRE_SCHEMA_IDENTITY,
                json_pointer="/trace/reservation_id",
            ),
        ),
    )


def _operation_artifact(
    *,
    operation_id: str = "game.resource.reserve@1",
    package_release_identity: str | None = None,
    subject: ExactSubjectIdentities | None = None,
    verification_failures: tuple[str, ...] = (),
) -> CanonicalArtifactEnvelope:
    return make_artifact_envelope(
        artifact_kind="operation_admission",
        wire_schema_identity=OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
        payload=OperationAdmissionPayload(
            schema_version="schema2-operation-admission-result/1",
            operation_id=operation_id,
            package_release_identity=package_release_identity or _identity("8"),
            subject=subject or _subject(),
            verification_failures=verification_failures,
        ),
    )


def _vector_artifact(
    vector_id: str,
    role: VectorRole,
    disposition: Disposition,
    *,
    subject: ExactSubjectIdentities | None = None,
    verification_failures: tuple[str, ...] = (),
    refusal_diagnostic_code: str | None = None,
) -> CanonicalArtifactEnvelope:
    return make_artifact_envelope(
        artifact_kind="normative_vector_result",
        wire_schema_identity=VECTOR_RESULT_WIRE_SCHEMA_IDENTITY,
        payload=VectorResultPayload(
            schema_version="schema2-normative-vector-result/1",
            vector_id=vector_id,
            role=role,
            disposition=disposition,
            subject=subject or _subject(),
            verification_failures=verification_failures,
            refusal_diagnostic_code=refusal_diagnostic_code,
        ),
    )


def _public_artifact(
    *,
    source_vector_id: str = "trace.resource.reserve-positive-v1",
    artifact_kind: PublicArtifactKind = "evaluation_run",
    wire_schema_identity: str = PUBLIC_WIRE_SCHEMA_IDENTITY,
    subject: ExactSubjectIdentities | None = None,
    trace: dict[str, str] | None = None,
) -> CanonicalArtifactEnvelope:
    return make_artifact_envelope(
        artifact_kind=artifact_kind,
        wire_schema_identity=wire_schema_identity,
        payload={
            "schema_version": "test-public-artifact/1",
            "source_vector_id": source_vector_id,
            "subject": (subject or _subject()).model_dump(mode="json"),
            "trace": trace if trace is not None else {"reservation_id": "r-1"},
        },
    )


def _evidence(
    requirement: ClaimCandidateRequirement | None = None,
) -> ClaimCandidateEvidence:
    requirement = requirement or _requirement()
    return ClaimCandidateEvidence(
        schema_version="schema2-claim-candidate-evidence/1",
        claim_definition_identity=claim_definition_identity(requirement),
        research=(
            ResearchEvidence(
                evidence_id="research-resource-contract-v1",
                source="urn:research:resource-contract",
            ),
        ),
        operation_artifacts=(_operation_artifact(),),
        vector_artifacts=(
            _vector_artifact(
                "trace.resource.reserve-positive-v1", "positive", "success"
            ),
            _vector_artifact(
                "trace.resource.insufficient-outcome-v1", "negative", "outcome"
            ),
        ),
        public_artifacts=(_public_artifact(),),
    )


def _codes(report: ClaimCandidateReport) -> list[str]:
    return [item.code for item in report.diagnostics]


def test_exact_artifact_closure_is_only_a_verification_candidate() -> None:
    requirement = _requirement()
    report = assess_claim_candidate(requirement, _evidence(requirement))

    assert report.status == "candidate"
    assert report.diagnostics == ()
    assert report.claim_definition_identity == claim_definition_identity(requirement)
    assert "closed" not in report.model_dump_json()
    rendered = canonical_candidate_report(report)
    assert (
        rendered
        == json.dumps(
            json.loads(rendered), ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        + "\n"
    )


def test_consumption_rehashes_payload_instead_of_trusting_old_identity() -> None:
    requirement = _requirement()
    original = _operation_artifact()
    payload = OperationAdmissionPayload(
        schema_version="schema2-operation-admission-result/1",
        operation_id="game.resource.commit@1",
        package_release_identity=_identity("8"),
        subject=_subject(),
    )
    tampered = original.model_copy(
        update={
            "payload": (
                json.dumps(payload.model_dump(mode="json"), sort_keys=True) + "\n"
            ).encode()
        }
    )
    evidence = _evidence(requirement).model_copy(
        update={"operation_artifacts": (tampered,)}
    )

    report = assess_claim_candidate(requirement, evidence)

    assert report.status == "open"
    assert set(_codes(report)) >= {
        "artifact_identity_mismatch",
        "extra_operation",
        "missing_operation",
    }


def test_envelope_validation_rejects_old_identity_after_payload_tamper() -> None:
    envelope = _operation_artifact()
    tampered = envelope.model_copy(update={"payload": b"{}\n"})

    with pytest.raises(ValidationError, match="content identity"):
        CanonicalArtifactEnvelope.model_validate(tampered.model_dump())


def test_valid_hash_cannot_turn_semantic_verification_failure_into_authority() -> None:
    requirement = _requirement()
    failed = _operation_artifact(verification_failures=("signature_mismatch",))
    evidence = _evidence(requirement).model_copy(
        update={"operation_artifacts": (failed,)}
    )

    report = assess_claim_candidate(requirement, evidence)

    assert report.status == "open"
    assert "operation_not_verified" in _codes(report)


def test_caller_passed_field_is_not_a_supported_result_contract() -> None:
    requirement = _requirement()
    valid = OperationAdmissionPayload(
        schema_version="schema2-operation-admission-result/1",
        operation_id="game.resource.reserve@1",
        package_release_identity=_identity("8"),
        subject=_subject(),
    ).model_dump(mode="json")
    valid["passed"] = True
    forged = make_artifact_envelope(
        artifact_kind="operation_admission",
        wire_schema_identity=OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
        payload=valid,
    )
    evidence = _evidence(requirement).model_copy(
        update={"operation_artifacts": (forged,)}
    )

    report = assess_claim_candidate(requirement, evidence)

    assert set(_codes(report)) >= {
        "artifact_payload_schema_invalid",
        "missing_operation",
    }


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        ("source", "public_observation_source_drift"),
        ("kind", "public_observation_artifact_kind_drift"),
        ("schema", "public_observation_wire_schema_drift"),
        ("pointer", "public_observation_pointer_missing"),
    ],
)
def test_public_observable_requires_exact_source_kind_schema_and_pointer(
    change: Literal["source", "kind", "schema", "pointer"], expected_code: str
) -> None:
    requirement = _requirement()
    if change == "source":
        wrong = _public_artifact(
            source_vector_id="trace.resource.insufficient-outcome-v1"
        )
    elif change == "kind":
        wrong = _public_artifact(artifact_kind="evidence_assertion")
    elif change == "schema":
        wrong = _public_artifact(wire_schema_identity=_identity("f"))
    else:
        wrong = _public_artifact(trace={})
    evidence = _evidence(requirement).model_copy(update={"public_artifacts": (wrong,)})

    report = assess_claim_candidate(requirement, evidence)

    assert report.status == "open"
    assert expected_code in _codes(report)
    assert "missing_public_observation" in _codes(report)


@pytest.mark.parametrize(
    "success_kind",
    [
        "evaluation_run",
        "metric_dataset",
        "replay_comparison",
        "cross_evaluator_comparison",
        "evidence_assertion",
    ],
)
def test_runtime_refusal_cannot_bind_a_success_artifact(
    success_kind: PublicArtifactKind,
) -> None:
    payload = _requirement().model_dump(mode="json")
    payload["vectors"][1] = {
        "vector_id": "trace.resource.insufficient-outcome-v1",
        "role": "negative",
        "expected_disposition": "refusal",
    }
    payload["public_observables"][0]["source_vector_id"] = (
        "trace.resource.insufficient-outcome-v1"
    )
    payload["public_observables"][0]["artifact_kind"] = success_kind

    with pytest.raises(ValidationError, match="terminal_audit"):
        ClaimCandidateRequirement.model_validate(payload)


def test_typed_runtime_refusal_can_form_only_a_terminal_audit_candidate() -> None:
    payload = _requirement().model_dump(mode="json")
    payload["vectors"][1]["expected_disposition"] = "refusal"
    payload["public_observables"][0].update(
        {
            "field_id": "audit.refusal_code",
            "source_vector_id": "trace.resource.insufficient-outcome-v1",
            "artifact_kind": "terminal_audit",
            "json_pointer": "/audit/refusal_code",
        }
    )
    requirement = ClaimCandidateRequirement.model_validate(payload)
    terminal = make_artifact_envelope(
        artifact_kind="terminal_audit",
        wire_schema_identity=PUBLIC_WIRE_SCHEMA_IDENTITY,
        payload={
            "schema_version": "test-terminal-audit/1",
            "source_vector_id": "trace.resource.insufficient-outcome-v1",
            "subject": _subject().model_dump(mode="json"),
            "audit": {"refusal_code": "runtime_budget_exhausted"},
        },
    )
    evidence = ClaimCandidateEvidence(
        schema_version="schema2-claim-candidate-evidence/1",
        claim_definition_identity=claim_definition_identity(requirement),
        operation_artifacts=(_operation_artifact(),),
        vector_artifacts=(
            _vector_artifact(
                "trace.resource.reserve-positive-v1", "positive", "success"
            ),
            _vector_artifact(
                "trace.resource.insufficient-outcome-v1",
                "negative",
                "refusal",
                refusal_diagnostic_code="runtime_budget_exhausted",
            ),
        ),
        public_artifacts=(terminal,),
    )

    report = assess_claim_candidate(requirement, evidence)

    assert report.status == "candidate"
    assert report.diagnostics == ()


@pytest.mark.parametrize(
    ("role", "disposition"),
    [("positive", "outcome"), ("positive", "refusal"), ("negative", "success")],
)
def test_illegal_vector_role_disposition_is_rejected(
    role: VectorRole, disposition: Disposition
) -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        VectorRequirement(
            vector_id="trace.illegal-v1",
            role=role,
            expected_disposition=disposition,
        )


def test_report_all_keeps_independent_failures_on_extra_facts() -> None:
    requirement = _requirement()
    changed_subject = _subject(ldb="d", resolved_model="e")
    extra_operation = _operation_artifact(
        operation_id="game.resource.commit@1",
        subject=changed_subject,
        verification_failures=("effect_mismatch",),
    )
    extra_vector = _vector_artifact(
        "trace.resource.unlisted-boundary-v1",
        "boundary",
        "outcome",
        subject=changed_subject,
        verification_failures=("observation_mismatch",),
    )
    extra_public = _public_artifact(source_vector_id="trace.resource.unknown-v1")
    baseline = _evidence(requirement)
    evidence = baseline.model_copy(
        update={
            "research": baseline.research + baseline.research,
            "operation_artifacts": baseline.operation_artifacts
            + (extra_operation, extra_operation),
            "vector_artifacts": baseline.vector_artifacts
            + (extra_vector, extra_vector),
            "public_artifacts": baseline.public_artifacts + (extra_public,),
        }
    )

    first = assess_claim_candidate(requirement, evidence)
    second = assess_claim_candidate(requirement, evidence)

    assert first == second
    assert set(_codes(first)) >= {
        "duplicate_operation_result",
        "duplicate_research_evidence",
        "duplicate_vector_result",
        "extra_operation",
        "extra_public_artifact",
        "extra_vector",
        "operation_identity_drift",
        "operation_not_verified",
        "public_observation_source_unknown",
        "vector_identity_drift",
        "vector_not_verified",
    }


def test_research_alone_never_satisfies_normative_or_public_facts() -> None:
    requirement = _requirement()
    evidence = ClaimCandidateEvidence(
        schema_version="schema2-claim-candidate-evidence/1",
        claim_definition_identity=claim_definition_identity(requirement),
        research=(
            ResearchEvidence(
                evidence_id="research-resource-contract-v1",
                source="urn:research:resource-contract",
            ),
        ),
    )

    report = assess_claim_candidate(requirement, evidence)

    assert report.status == "open"
    assert set(_codes(report)) >= {
        "missing_operation",
        "missing_vector",
        "missing_public_observation",
    }


def test_exact_subject_change_refuses_stale_artifacts_without_claiming_replay() -> None:
    original = _requirement()
    changed = _requirement(subject=_subject(ldb="d", resolved_model="e"))

    report = assess_claim_candidate(changed, _evidence(original))

    assert report.status == "open"
    assert set(_codes(report)) >= {
        "claim_definition_identity_drift",
        "operation_identity_drift",
        "vector_identity_drift",
        "public_observation_identity_drift",
    }
    assert "replay" not in report.model_dump_json().lower()


def test_empty_requirement_cannot_be_a_candidate() -> None:
    requirement = ClaimCandidateRequirement(
        schema_version="schema2-claim-candidate-requirement/1",
        claim_id="TRACE-EMPTY-01",
        subject=_subject(),
        operations=(),
        vectors=(),
        public_observables=(),
    )
    evidence = ClaimCandidateEvidence(
        schema_version="schema2-claim-candidate-evidence/1",
        claim_definition_identity=claim_definition_identity(requirement),
    )

    report = assess_claim_candidate(requirement, evidence)

    assert report.status == "open"
    assert set(_codes(report)) == {
        "missing_non_positive_vector_requirement",
        "missing_operation_requirement",
        "missing_positive_vector_requirement",
        "missing_public_observable_requirement",
    }


def test_duplicate_requirement_ids_are_reported() -> None:
    baseline = _requirement()
    duplicated = baseline.model_copy(
        update={
            "operations": baseline.operations + baseline.operations,
            "vectors": baseline.vectors + baseline.vectors,
            "public_observables": baseline.public_observables
            + baseline.public_observables,
        }
    )
    evidence = _evidence(duplicated)

    report = assess_claim_candidate(duplicated, evidence)

    assert set(_codes(report)) >= {
        "duplicate_operation_requirement",
        "duplicate_public_observable_requirement",
        "duplicate_vector_requirement",
    }


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("operation", "operation_id", "game.resource.reserve"),
        ("operation", "host_dispatch", "resource_reserve"),
        ("root", "kernel_override", _identity("0")),
    ],
)
def test_typed_claim_rejects_versionless_or_bypass_fields(
    target: str, field: str, value: str
) -> None:
    payload = _requirement().model_dump(mode="json")
    if target == "operation":
        payload["operations"][0][field] = value
    else:
        payload[field] = value

    with pytest.raises(ValidationError):
        ClaimCandidateRequirement.model_validate(payload)


def test_payload_parser_rejects_duplicate_members_and_excess_depth() -> None:
    duplicate = b'{"a": 1, "a": 2}\n'
    with pytest.raises(ValidationError, match="duplicate JSON member"):
        CanonicalArtifactEnvelope(
            schema_version="schema2-canonical-artifact-envelope/1",
            artifact_kind="operation_admission",
            wire_schema_identity=OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
            content_identity=artifact_content_identity(
                "operation_admission",
                OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
                duplicate,
            ),
            payload=duplicate,
        )

    deep_value: object = 0
    for _ in range(MAX_ARTIFACT_JSON_DEPTH + 1):
        deep_value = [deep_value]
    deep = (json.dumps(deep_value) + "\n").encode()
    with pytest.raises(ValidationError, match="depth limit"):
        CanonicalArtifactEnvelope(
            schema_version="schema2-canonical-artifact-envelope/1",
            artifact_kind="operation_admission",
            wire_schema_identity=OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
            content_identity=artifact_content_identity(
                "operation_admission",
                OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
                deep,
            ),
            payload=deep,
        )


def test_deterministic_resource_caps_reject_oversized_inputs() -> None:
    oversized = b" " * (MAX_ARTIFACT_PAYLOAD_BYTES + 1)
    with pytest.raises(ValidationError, match="at most"):
        CanonicalArtifactEnvelope(
            schema_version="schema2-canonical-artifact-envelope/1",
            artifact_kind="operation_admission",
            wire_schema_identity=OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
            content_identity=artifact_content_identity(
                "operation_admission",
                OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY,
                oversized,
            ),
            payload=oversized,
        )

    payload = _requirement().model_dump(mode="json")
    payload["operations"] = payload["operations"] * (MAX_CLAIM_FACTS + 1)
    with pytest.raises(ValidationError, match="at most"):
        ClaimCandidateRequirement.model_validate(payload)
