"""Machine gate for a Standard Schema 2.x claim-row closure.

The models in this module are a validation-host contract, not language
authority.  Callers supply identities and normative requirements from admitted
Kernel/LDB/package/experiment artifacts; this module never dispatches an
Operation or supplies missing semantics from host code.  A ``closed`` report is
therefore an exact-claim evidence-closure result, not proof of type-system
completeness, semantic execution, replay, genre support, or full Schema 2.x
feasibility.
"""

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from gda_balancing.emit import canonical_json, model_payload


ContentIdentity = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
OperationId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+@[1-9][0-9]*$"),
]
StableId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9._-]*$")]
DiagnosticSubject = Annotated[
    str, StringConstraints(pattern=r"^[^\n]+$", max_length=512)
]
ClaimId = Annotated[
    str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+-[0-9]{2}$")
]

VectorRole = Literal["positive", "negative", "boundary"]
Disposition = Literal["success", "outcome", "refusal"]
ArtifactKind = Literal[
    "command_result",
    "evaluation_run",
    "metric_dataset",
    "terminal_audit",
    "comparison",
    "evidence_assertion",
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactSubjectIdentities(_ClosedModel):
    """Exact identities that define the claim's one execution subject."""

    kernel_specification: ContentIdentity
    language_definition_bundle: ContentIdentity
    package_lock: ContentIdentity
    rir_semantic_payload: ContentIdentity
    resolved_model: ContentIdentity
    resolved_runtime_profile: ContentIdentity
    experiment_specification: ContentIdentity


class OperationRequirement(_ClosedModel):
    operation_id: OperationId
    package_release_identity: ContentIdentity


class VectorRequirement(_ClosedModel):
    """One vector definition under ``requirement.subject``'s exact LDB.

    ``language_definition_bundle`` plus ``vector_id`` identifies the normative
    vector definition.  The id alone is deliberately not a global content
    identity.
    """

    vector_id: StableId
    role: VectorRole
    expected_disposition: Disposition


class PublicObservableRequirement(_ClosedModel):
    field_id: StableId


class ClaimClosureRequirement(_ClosedModel):
    schema_version: Literal["schema2-claim-closure/1"]
    claim_id: ClaimId
    claim_definition_identity: ContentIdentity
    subject: ExactSubjectIdentities
    operations: tuple[OperationRequirement, ...]
    vectors: tuple[VectorRequirement, ...]
    public_observables: tuple[PublicObservableRequirement, ...]


class ResearchEvidence(_ClosedModel):
    """Non-normative research context; never sufficient for closure."""

    evidence_id: StableId
    source: Annotated[str, Field(min_length=1, max_length=2048)]


class OperationAdmission(_ClosedModel):
    operation_id: OperationId
    package_release_identity: ContentIdentity
    result_identity: ContentIdentity
    subject: ExactSubjectIdentities
    passed: bool


class VectorResult(_ClosedModel):
    vector_id: StableId
    role: VectorRole
    disposition: Disposition
    result_identity: ContentIdentity
    subject: ExactSubjectIdentities
    passed: bool


class PublicArtifactObservation(_ClosedModel):
    field_id: StableId
    source_vector_id: StableId
    artifact_kind: ArtifactKind
    artifact_identity: ContentIdentity
    subject: ExactSubjectIdentities
    passed: bool


class ClaimClosureEvidence(_ClosedModel):
    schema_version: Literal["schema2-claim-closure-evidence/1"]
    claim_definition_identity: ContentIdentity
    subject: ExactSubjectIdentities
    research: tuple[ResearchEvidence, ...] = ()
    operations: tuple[OperationAdmission, ...]
    vectors: tuple[VectorResult, ...]
    public_observations: tuple[PublicArtifactObservation, ...]


class ClosureDiagnostic(_ClosedModel):
    """Gate-local finding, not a Kernel/LDB typed-refusal Diagnostic."""

    code: StableId
    subject: DiagnosticSubject
    message: str


class ClosureReport(_ClosedModel):
    schema_version: Literal["schema2-claim-closure-report/1"]
    claim_id: ClaimId
    claim_definition_identity: ContentIdentity
    subject: ExactSubjectIdentities
    status: Literal["closed", "open"]
    diagnostics: tuple[ClosureDiagnostic, ...]


_SUBJECT_IDENTITY_FIELDS = (
    "kernel_specification",
    "language_definition_bundle",
    "package_lock",
    "rir_semantic_payload",
    "resolved_model",
    "resolved_runtime_profile",
    "experiment_specification",
)


def _subjects_differ(
    expected: ExactSubjectIdentities, actual: ExactSubjectIdentities
) -> bool:
    return expected != actual


def _duplicate_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(value for value, count in Counter(values).items() if count > 1))


def assess_claim_closure(
    requirement: ClaimClosureRequirement,
    evidence: ClaimClosureEvidence,
) -> ClosureReport:
    """Assess whether the supplied normative and public facts close one row."""

    diagnostics: list[ClosureDiagnostic] = []

    if requirement.claim_definition_identity != evidence.claim_definition_identity:
        diagnostics.append(
            ClosureDiagnostic(
                code="claim_definition_identity_drift",
                subject="evidence.claim_definition_identity",
                message="Evidence was assembled for a different claim definition.",
            )
        )

    if not requirement.operations:
        diagnostics.append(
            ClosureDiagnostic(
                code="missing_operation_requirement",
                subject="operations",
                message="A claim row must require at least one versioned Operation.",
            )
        )
    if not any(item.role == "positive" for item in requirement.vectors):
        diagnostics.append(
            ClosureDiagnostic(
                code="missing_positive_vector_requirement",
                subject="vectors.positive",
                message="A claim row must require at least one positive vector.",
            )
        )
    if not any(item.role in {"negative", "boundary"} for item in requirement.vectors):
        diagnostics.append(
            ClosureDiagnostic(
                code="missing_non_positive_vector_requirement",
                subject="vectors.non_positive",
                message="A claim row must require a negative or boundary vector.",
            )
        )
    if not requirement.public_observables:
        diagnostics.append(
            ClosureDiagnostic(
                code="missing_public_observable_requirement",
                subject="public_observables",
                message="A claim row must require at least one public observable.",
            )
        )

    for operation_id in _duplicate_ids(
        tuple(item.operation_id for item in requirement.operations)
    ):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_operation_requirement",
                subject=operation_id,
                message="Required Operation ids must be unique.",
            )
        )
    for vector_id in _duplicate_ids(
        tuple(item.vector_id for item in requirement.vectors)
    ):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_vector_requirement",
                subject=vector_id,
                message="Required vector ids must be unique.",
            )
        )
    for field_id in _duplicate_ids(
        tuple(item.field_id for item in requirement.public_observables)
    ):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_public_observable_requirement",
                subject=field_id,
                message="Required public observable field ids must be unique.",
            )
        )

    for field_name in _SUBJECT_IDENTITY_FIELDS:
        if getattr(requirement.subject, field_name) != getattr(
            evidence.subject, field_name
        ):
            diagnostics.append(
                ClosureDiagnostic(
                    code="identity_drift",
                    subject=f"evidence.{field_name}",
                    message="Evidence binds a different exact subject identity.",
                )
            )

    for evidence_id in _duplicate_ids(
        tuple(item.evidence_id for item in evidence.research)
    ):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_research_evidence",
                subject=evidence_id,
                message="Research evidence ids must be unique.",
            )
        )

    required_operations = {item.operation_id: item for item in requirement.operations}
    admitted_operation_ids = {item.operation_id for item in evidence.operations}
    for item in requirement.operations:
        if item.operation_id not in admitted_operation_ids:
            diagnostics.append(
                ClosureDiagnostic(
                    code="missing_operation",
                    subject=item.operation_id,
                    message="The required admitted Operation has no result.",
                )
            )
    for operation_id in _duplicate_ids(
        tuple(item.operation_id for item in evidence.operations)
    ):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_operation_result",
                subject=operation_id,
                message="Operation admission results must be unique.",
            )
        )
    for item in evidence.operations:
        expected = required_operations.get(item.operation_id)
        if expected is None:
            diagnostics.append(
                ClosureDiagnostic(
                    code="extra_operation",
                    subject=item.operation_id,
                    message="Operation admission is not required by this claim.",
                )
            )
        else:
            if not item.passed:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="operation_not_passed",
                        subject=item.operation_id,
                        message="Operation admission did not pass.",
                    )
                )
            if item.package_release_identity != expected.package_release_identity:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="operation_package_identity_drift",
                        subject=item.operation_id,
                        message="Operation admission binds a different package release.",
                    )
                )
        if _subjects_differ(requirement.subject, item.subject):
            diagnostics.append(
                ClosureDiagnostic(
                    code="operation_identity_drift",
                    subject=item.operation_id,
                    message="Operation admission binds a different exact subject.",
                )
            )

    required_vectors = {item.vector_id: item for item in requirement.vectors}
    result_vector_ids = {item.vector_id for item in evidence.vectors}
    for item in requirement.vectors:
        if item.vector_id not in result_vector_ids:
            diagnostics.append(
                ClosureDiagnostic(
                    code="missing_vector",
                    subject=item.vector_id,
                    message="The required normative vector has no result.",
                )
            )
    for vector_id in _duplicate_ids(tuple(item.vector_id for item in evidence.vectors)):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_vector_result",
                subject=vector_id,
                message="Normative vector results must be unique.",
            )
        )
    for item in evidence.vectors:
        expected = required_vectors.get(item.vector_id)
        if expected is None:
            diagnostics.append(
                ClosureDiagnostic(
                    code="extra_vector",
                    subject=item.vector_id,
                    message="Normative vector result is not required by this claim.",
                )
            )
        else:
            if not item.passed:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="vector_not_passed",
                        subject=item.vector_id,
                        message="Normative vector did not pass.",
                    )
                )
            if item.role != expected.role:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="vector_role_drift",
                        subject=item.vector_id,
                        message="Normative vector role differs from the claim.",
                    )
                )
            if item.disposition != expected.expected_disposition:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="vector_disposition_drift",
                        subject=item.vector_id,
                        message="Normative vector disposition differs from the claim.",
                    )
                )
        if _subjects_differ(requirement.subject, item.subject):
            diagnostics.append(
                ClosureDiagnostic(
                    code="vector_identity_drift",
                    subject=item.vector_id,
                    message="Normative vector result binds a different exact subject.",
                )
            )

    required_observables = {
        item.field_id: item for item in requirement.public_observables
    }
    observed_field_ids = {item.field_id for item in evidence.public_observations}
    for item in requirement.public_observables:
        if item.field_id not in observed_field_ids:
            diagnostics.append(
                ClosureDiagnostic(
                    code="missing_public_observation",
                    subject=item.field_id,
                    message="The required field has no public artifact observation.",
                )
            )
    for field_id in _duplicate_ids(
        tuple(item.field_id for item in evidence.public_observations)
    ):
        diagnostics.append(
            ClosureDiagnostic(
                code="duplicate_public_observation",
                subject=field_id,
                message="Public artifact observations must be unique.",
            )
        )
    for item in evidence.public_observations:
        if item.field_id not in required_observables:
            diagnostics.append(
                ClosureDiagnostic(
                    code="extra_public_observation",
                    subject=item.field_id,
                    message="Public observation is not required by this claim.",
                )
            )
        else:
            if not item.passed:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="public_observation_not_passed",
                        subject=item.field_id,
                        message="Public artifact observation did not pass.",
                    )
                )
            if item.source_vector_id not in required_vectors:
                diagnostics.append(
                    ClosureDiagnostic(
                        code="public_observation_source_unknown",
                        subject=item.field_id,
                        message="Public observation names an unrequired vector source.",
                    )
                )
        if _subjects_differ(requirement.subject, item.subject):
            diagnostics.append(
                ClosureDiagnostic(
                    code="public_observation_identity_drift",
                    subject=item.field_id,
                    message="Public artifact observation binds a different exact subject.",
                )
            )

    unique = {(item.code, item.subject, item.message): item for item in diagnostics}
    ordered = tuple(
        sorted(
            unique.values(), key=lambda item: (item.code, item.subject, item.message)
        )
    )
    return ClosureReport(
        schema_version="schema2-claim-closure-report/1",
        claim_id=requirement.claim_id,
        claim_definition_identity=requirement.claim_definition_identity,
        subject=requirement.subject,
        status="open" if ordered else "closed",
        diagnostics=ordered,
    )


def canonical_closure_report(report: ClosureReport) -> str:
    """Emit a report through the package's one canonical JSON seam."""

    return canonical_json(model_payload(report))
