"""Permanent Schema 2.0 claim-row closure gate.

These tests exercise the public conformance API.  The fixtures describe a
generic package operation and deliberately make no genre-support claim.
"""

import json

import pytest
from pydantic import ValidationError

from gda_balancing.schema2.conformance import (
    ClaimClosureEvidence,
    ClaimClosureRequirement,
    ExactSubjectIdentities,
    OperationAdmission,
    OperationRequirement,
    PublicArtifactObservation,
    PublicObservableRequirement,
    ResearchEvidence,
    VectorRequirement,
    VectorResult,
    assess_claim_closure,
    canonical_closure_report,
)


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


def _requirement() -> ClaimClosureRequirement:
    return ClaimClosureRequirement(
        schema_version="schema2-claim-closure/1",
        claim_id="TRACE-RESOURCE-01",
        claim_definition_identity=_identity("d"),
        subject=_subject(),
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
            PublicObservableRequirement(field_id="trace.reservation_id"),
        ),
    )


def _evidence() -> ClaimClosureEvidence:
    subject = _subject()
    return ClaimClosureEvidence(
        schema_version="schema2-claim-closure-evidence/1",
        claim_definition_identity=_identity("d"),
        subject=subject,
        research=(
            ResearchEvidence(
                evidence_id="research-resource-contract-v1",
                source="urn:research:resource-contract",
            ),
        ),
        operations=(
            OperationAdmission(
                operation_id="game.resource.reserve@1",
                package_release_identity=_identity("8"),
                result_identity=_identity("9"),
                subject=subject,
                passed=True,
            ),
        ),
        vectors=(
            VectorResult(
                vector_id="trace.resource.reserve-positive-v1",
                role="positive",
                disposition="success",
                result_identity=_identity("a"),
                subject=subject,
                passed=True,
            ),
            VectorResult(
                vector_id="trace.resource.insufficient-outcome-v1",
                role="negative",
                disposition="outcome",
                result_identity=_identity("b"),
                subject=subject,
                passed=True,
            ),
        ),
        public_observations=(
            PublicArtifactObservation(
                field_id="trace.reservation_id",
                source_vector_id="trace.resource.reserve-positive-v1",
                artifact_kind="evaluation_run",
                artifact_identity=_identity("c"),
                subject=subject,
                passed=True,
            ),
        ),
    )


def test_exact_normative_and_public_closure_can_close_a_claim_row() -> None:
    report = assess_claim_closure(_requirement(), _evidence())

    assert report.status == "closed"
    assert report.diagnostics == ()
    assert report.schema_version == "schema2-claim-closure-report/1"
    assert report.claim_definition_identity == _identity("d")
    assert report.subject == _subject()
    rendered = canonical_closure_report(report)
    assert rendered == (
        json.dumps(
            json.loads(rendered),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def test_report_remains_bound_to_the_exact_claim_definition() -> None:
    original = assess_claim_closure(_requirement(), _evidence())
    revised_requirement = _requirement().model_copy(
        update={"claim_definition_identity": _identity("e")}
    )
    revised = assess_claim_closure(revised_requirement, _evidence())

    assert original.claim_id == revised.claim_id
    assert original.claim_definition_identity != revised.claim_definition_identity
    assert original != revised
    assert revised.status == "open"
    assert [(item.code, item.subject) for item in revised.diagnostics] == [
        ("claim_definition_identity_drift", "evidence.claim_definition_identity")
    ]


def test_research_evidence_alone_reports_every_normative_and_public_gap() -> None:
    report = assess_claim_closure(
        _requirement(),
        ClaimClosureEvidence(
            schema_version="schema2-claim-closure-evidence/1",
            claim_definition_identity=_identity("d"),
            subject=_subject(),
            research=(
                ResearchEvidence(
                    evidence_id="research-resource-contract-v1",
                    source="urn:research:resource-contract",
                ),
            ),
            operations=(),
            vectors=(),
            public_observations=(),
        ),
    )

    assert report.status == "open"
    assert [(item.code, item.subject) for item in report.diagnostics] == [
        ("missing_operation", "game.resource.reserve@1"),
        ("missing_public_observation", "trace.reservation_id"),
        ("missing_vector", "trace.resource.insufficient-outcome-v1"),
        ("missing_vector", "trace.resource.reserve-positive-v1"),
    ]


def test_unused_package_identity_blast_radius_is_not_closure_or_replay() -> None:
    changed_subject = _subject().model_copy(
        update={
            "language_definition_bundle": _identity("d"),
            "resolved_model": _identity("e"),
            "resolved_runtime_profile": _identity("f"),
            "experiment_specification": _identity("0"),
        }
    )
    requirement = _requirement().model_copy(
        update={
            "claim_definition_identity": _identity("e"),
            "subject": changed_subject,
        }
    )

    first = assess_claim_closure(requirement, _evidence())
    second = assess_claim_closure(requirement, _evidence())

    assert first == second
    assert first.status == "open"
    assert [(item.code, item.subject) for item in first.diagnostics] == [
        ("claim_definition_identity_drift", "evidence.claim_definition_identity"),
        ("identity_drift", "evidence.experiment_specification"),
        ("identity_drift", "evidence.language_definition_bundle"),
        ("identity_drift", "evidence.resolved_model"),
        ("identity_drift", "evidence.resolved_runtime_profile"),
        ("operation_identity_drift", "game.resource.reserve@1"),
        ("public_observation_identity_drift", "trace.reservation_id"),
        (
            "vector_identity_drift",
            "trace.resource.insufficient-outcome-v1",
        ),
        ("vector_identity_drift", "trace.resource.reserve-positive-v1"),
    ]
    assert "replay" not in json.dumps(first.model_dump(mode="json")).lower()


def test_report_all_rejects_duplicate_extra_unpassed_and_drifting_facts() -> None:
    baseline = _evidence()
    operation = baseline.operations[0].model_copy(
        update={
            "package_release_identity": _identity("0"),
            "passed": False,
        }
    )
    extra_operation = baseline.operations[0].model_copy(
        update={"operation_id": "game.resource.commit@1"}
    )
    vector = baseline.vectors[0].model_copy(
        update={
            "role": "boundary",
            "disposition": "refusal",
            "passed": False,
        }
    )
    extra_vector = baseline.vectors[1].model_copy(
        update={"vector_id": "trace.resource.unlisted-boundary-v1"}
    )
    observation = baseline.public_observations[0].model_copy(
        update={
            "source_vector_id": "trace.resource.unlisted-boundary-v1",
            "passed": False,
        }
    )
    extra_observation = baseline.public_observations[0].model_copy(
        update={"field_id": "trace.unlisted_field"}
    )
    evidence = baseline.model_copy(
        update={
            "research": baseline.research + baseline.research,
            "operations": (operation, operation, extra_operation),
            "vectors": (vector, vector, baseline.vectors[1], extra_vector),
            "public_observations": (
                observation,
                observation,
                extra_observation,
            ),
        }
    )

    report = assess_claim_closure(_requirement(), evidence)

    assert report.status == "open"
    assert [(item.code, item.subject) for item in report.diagnostics] == [
        ("duplicate_operation_result", "game.resource.reserve@1"),
        ("duplicate_public_observation", "trace.reservation_id"),
        ("duplicate_research_evidence", "research-resource-contract-v1"),
        ("duplicate_vector_result", "trace.resource.reserve-positive-v1"),
        ("extra_operation", "game.resource.commit@1"),
        ("extra_public_observation", "trace.unlisted_field"),
        ("extra_vector", "trace.resource.unlisted-boundary-v1"),
        ("operation_not_passed", "game.resource.reserve@1"),
        ("operation_package_identity_drift", "game.resource.reserve@1"),
        ("public_observation_not_passed", "trace.reservation_id"),
        ("public_observation_source_unknown", "trace.reservation_id"),
        ("vector_disposition_drift", "trace.resource.reserve-positive-v1"),
        ("vector_not_passed", "trace.resource.reserve-positive-v1"),
        ("vector_role_drift", "trace.resource.reserve-positive-v1"),
    ]


def test_empty_requirement_cannot_close_vacuously() -> None:
    requirement = _requirement().model_copy(
        update={"operations": (), "vectors": (), "public_observables": ()}
    )
    evidence = _evidence().model_copy(
        update={"operations": (), "vectors": (), "public_observations": ()}
    )

    report = assess_claim_closure(requirement, evidence)

    assert report.status == "open"
    assert [(item.code, item.subject) for item in report.diagnostics] == [
        ("missing_non_positive_vector_requirement", "vectors.non_positive"),
        ("missing_operation_requirement", "operations"),
        ("missing_positive_vector_requirement", "vectors.positive"),
        ("missing_public_observable_requirement", "public_observables"),
    ]


def test_duplicate_requirement_ids_are_reported_instead_of_overwritten() -> None:
    requirement = _requirement()
    duplicated = requirement.model_copy(
        update={
            "operations": requirement.operations + requirement.operations,
            "vectors": requirement.vectors + requirement.vectors,
            "public_observables": (
                requirement.public_observables + requirement.public_observables
            ),
        }
    )

    report = assess_claim_closure(duplicated, _evidence())

    assert report.status == "open"
    assert [(item.code, item.subject) for item in report.diagnostics] == [
        ("duplicate_operation_requirement", "game.resource.reserve@1"),
        ("duplicate_public_observable_requirement", "trace.reservation_id"),
        (
            "duplicate_vector_requirement",
            "trace.resource.insufficient-outcome-v1",
        ),
        (
            "duplicate_vector_requirement",
            "trace.resource.reserve-positive-v1",
        ),
    ]


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("operation", "operation_id", "game.resource.reserve"),
        ("operation", "host_dispatch", "resource_reserve"),
        ("root", "kernel_override", _identity("0")),
    ],
)
def test_typed_contract_rejects_versionless_or_bypass_fields(
    target: str, field: str, value: str
) -> None:
    payload = _requirement().model_dump(mode="json")
    if target == "operation":
        payload["operations"][0][field] = value
    else:
        payload[field] = value

    with pytest.raises(ValidationError):
        ClaimClosureRequirement.model_validate(payload)


def test_outcome_and_refusal_are_distinct_declared_dispositions() -> None:
    baseline_requirement = _requirement()
    baseline_evidence = _evidence()
    refused_result = baseline_evidence.vectors[1].model_copy(
        update={"disposition": "refusal"}
    )
    refused_evidence = baseline_evidence.model_copy(
        update={"vectors": (baseline_evidence.vectors[0], refused_result)}
    )

    mismatch = assess_claim_closure(baseline_requirement, refused_evidence)
    assert [(item.code, item.subject) for item in mismatch.diagnostics] == [
        (
            "vector_disposition_drift",
            "trace.resource.insufficient-outcome-v1",
        )
    ]

    refused_requirement = baseline_requirement.model_copy(
        update={
            "vectors": (
                baseline_requirement.vectors[0],
                baseline_requirement.vectors[1].model_copy(
                    update={"expected_disposition": "refusal"}
                ),
            )
        }
    )
    assert (
        assess_claim_closure(refused_requirement, refused_evidence).status == "closed"
    )
