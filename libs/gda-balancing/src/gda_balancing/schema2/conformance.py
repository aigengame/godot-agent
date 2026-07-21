"""Rejected research utility for one Standard Schema 2.x claim row.

Independent review rejected this implementation as a permanent Gate 2
sub-slice.  It is retained only to reproduce dogfooding findings and cannot
serve as claim-candidate or claim-closure authority.
"""

from collections import Counter
from hashlib import sha256
import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StringConstraints,
    ValidationError,
    model_validator,
)

from gda_balancing.emit import canonical_json, model_payload


MAX_ARTIFACT_PAYLOAD_BYTES = 65_536
MAX_ARTIFACT_JSON_DEPTH = 64
MAX_CLAIM_FACTS = 256
MAX_RESEARCH_ITEMS = 128
MAX_VERIFICATION_FAILURES = 64

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
JsonPointer = Annotated[
    str,
    StringConstraints(
        pattern=r"^/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])*)*$",
        max_length=512,
    ),
]

VectorRole = Literal["positive", "negative", "boundary"]
Disposition = Literal["success", "outcome", "refusal"]
ArtifactKind = Literal[
    "operation_admission",
    "normative_vector_result",
    "command_result",
    "evaluation_run",
    "metric_dataset",
    "terminal_audit",
    "replay_comparison",
    "cross_evaluator_comparison",
    "evidence_assertion",
]
PublicArtifactKind = Literal[
    "command_result",
    "evaluation_run",
    "metric_dataset",
    "terminal_audit",
    "replay_comparison",
    "cross_evaluator_comparison",
    "evidence_assertion",
]

_ARTIFACT_IDENTITY_DOMAIN = b"gda-balancing:schema2-artifact-envelope:v1"
_CLAIM_IDENTITY_DOMAIN = b"gda-balancing:schema2-claim-definition:v1"
_WIRE_SCHEMA_IDENTITY_DOMAIN = b"gda-balancing:schema2-wire-schema:v1"
_LEGAL_DISPOSITIONS: dict[VectorRole, frozenset[Disposition]] = {
    "positive": frozenset({"success"}),
    "negative": frozenset({"outcome", "refusal"}),
    "boundary": frozenset({"success", "outcome", "refusal"}),
}


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _framed(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def _domain_identity(domain: bytes, *values: bytes) -> str:
    digest = sha256(domain + b"".join(_framed(value) for value in values)).hexdigest()
    return f"sha256:{digest}"


def artifact_content_identity(
    artifact_kind: ArtifactKind,
    wire_schema_identity: ContentIdentity,
    payload: bytes,
) -> str:
    """Hash exact payload bytes with kind and wire-schema domain separation."""

    return _domain_identity(
        _ARTIFACT_IDENTITY_DOMAIN,
        artifact_kind.encode("utf-8"),
        wire_schema_identity.encode("ascii"),
        payload,
    )


def _wire_schema_identity(schema_version: str) -> str:
    return _domain_identity(
        _WIRE_SCHEMA_IDENTITY_DOMAIN, schema_version.encode("ascii")
    )


OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY = _wire_schema_identity(
    "schema2-operation-admission-result/1"
)
VECTOR_RESULT_WIRE_SCHEMA_IDENTITY = _wire_schema_identity(
    "schema2-normative-vector-result/1"
)


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _assert_json_depth(payload: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in payload:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x7B, 0x5B}:
            depth += 1
            if depth > MAX_ARTIFACT_JSON_DEPTH:
                raise ValueError("artifact payload exceeds the JSON depth limit")
        elif byte in {0x7D, 0x5D}:
            depth -= 1
            if depth < 0:
                raise ValueError("artifact payload is not balanced JSON")
    if in_string or depth != 0:
        raise ValueError("artifact payload is not balanced JSON")


def _decode_canonical_payload(payload: bytes) -> Any:
    if len(payload) > MAX_ARTIFACT_PAYLOAD_BYTES:
        raise ValueError("artifact payload exceeds the byte limit")
    _assert_json_depth(payload)

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"artifact payload is not strict JSON: {exc}") from exc
    if canonical_json(parsed).encode("utf-8") != payload:
        raise ValueError("artifact payload is not canonical JSON")
    return parsed


class CanonicalArtifactEnvelope(_ClosedModel):
    """Bounded payload bytes whose kind, schema, and identity are re-verifiable."""

    schema_version: Literal["schema2-canonical-artifact-envelope/1"]
    artifact_kind: ArtifactKind
    wire_schema_identity: ContentIdentity
    content_identity: ContentIdentity
    payload: Annotated[StrictBytes, Field(max_length=MAX_ARTIFACT_PAYLOAD_BYTES)]

    @model_validator(mode="after")
    def _verify_integrity(self) -> "CanonicalArtifactEnvelope":
        expected = artifact_content_identity(
            self.artifact_kind, self.wire_schema_identity, self.payload
        )
        if self.content_identity != expected:
            raise ValueError("artifact content identity does not match payload bytes")
        _decode_canonical_payload(self.payload)
        return self


def make_artifact_envelope(
    *,
    artifact_kind: ArtifactKind,
    wire_schema_identity: ContentIdentity,
    payload: BaseModel | dict[str, Any],
) -> CanonicalArtifactEnvelope:
    """Canonicalize and seal one artifact for verified aggregation."""

    value = model_payload(payload) if isinstance(payload, BaseModel) else payload
    payload_bytes = canonical_json(value).encode("utf-8")
    return CanonicalArtifactEnvelope(
        schema_version="schema2-canonical-artifact-envelope/1",
        artifact_kind=artifact_kind,
        wire_schema_identity=wire_schema_identity,
        content_identity=artifact_content_identity(
            artifact_kind, wire_schema_identity, payload_bytes
        ),
        payload=payload_bytes,
    )


class ExactSubjectIdentities(_ClosedModel):
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
    vector_id: StableId
    role: VectorRole
    expected_disposition: Disposition

    @model_validator(mode="after")
    def _validate_role_disposition(self) -> "VectorRequirement":
        if self.expected_disposition not in _LEGAL_DISPOSITIONS[self.role]:
            raise ValueError("vector role and expected disposition are incompatible")
        return self


class PublicObservableRequirement(_ClosedModel):
    field_id: StableId
    source_vector_id: StableId
    artifact_kind: PublicArtifactKind
    wire_schema_identity: ContentIdentity
    json_pointer: JsonPointer


class ClaimCandidateRequirement(_ClosedModel):
    schema_version: Literal["schema2-claim-candidate-requirement/1"]
    claim_id: ClaimId
    subject: ExactSubjectIdentities
    operations: Annotated[
        tuple[OperationRequirement, ...], Field(max_length=MAX_CLAIM_FACTS)
    ]
    vectors: Annotated[tuple[VectorRequirement, ...], Field(max_length=MAX_CLAIM_FACTS)]
    public_observables: Annotated[
        tuple[PublicObservableRequirement, ...], Field(max_length=MAX_CLAIM_FACTS)
    ]

    @model_validator(mode="after")
    def _validate_public_sources(self) -> "ClaimCandidateRequirement":
        vectors = {item.vector_id: item for item in self.vectors}
        for observable in self.public_observables:
            vector = vectors.get(observable.source_vector_id)
            if vector is None:
                raise ValueError("public observable references an unrequired vector")
            if vector.expected_disposition == "refusal":
                if observable.artifact_kind != "terminal_audit":
                    raise ValueError(
                        "a refusal vector can be observed only through terminal_audit"
                    )
            elif observable.artifact_kind == "terminal_audit":
                raise ValueError(
                    "a successful or outcome vector cannot use a refusal terminal_audit"
                )
        return self


def claim_definition_identity(requirement: ClaimCandidateRequirement) -> str:
    payload = canonical_json(model_payload(requirement)).encode("utf-8")
    return _domain_identity(_CLAIM_IDENTITY_DOMAIN, payload)


class ResearchEvidence(_ClosedModel):
    """Non-normative context; it never satisfies a closure fact."""

    evidence_id: StableId
    source: Annotated[str, Field(min_length=1, max_length=2048)]


class OperationAdmissionPayload(_ClosedModel):
    schema_version: Literal["schema2-operation-admission-result/1"]
    operation_id: OperationId
    package_release_identity: ContentIdentity
    subject: ExactSubjectIdentities
    verification_failures: Annotated[
        tuple[StableId, ...], Field(max_length=MAX_VERIFICATION_FAILURES)
    ] = ()


class VectorResultPayload(_ClosedModel):
    schema_version: Literal["schema2-normative-vector-result/1"]
    vector_id: StableId
    role: VectorRole
    disposition: Disposition
    subject: ExactSubjectIdentities
    verification_failures: Annotated[
        tuple[StableId, ...], Field(max_length=MAX_VERIFICATION_FAILURES)
    ] = ()
    refusal_diagnostic_code: StableId | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> "VectorResultPayload":
        if self.disposition not in _LEGAL_DISPOSITIONS[self.role]:
            raise ValueError("vector role and disposition are incompatible")
        if self.disposition == "refusal" and self.refusal_diagnostic_code is None:
            raise ValueError("a refusal result requires a typed diagnostic code")
        if self.disposition != "refusal" and self.refusal_diagnostic_code is not None:
            raise ValueError(
                "only a refusal result may carry a refusal diagnostic code"
            )
        return self


class ClaimCandidateEvidence(_ClosedModel):
    schema_version: Literal["schema2-claim-candidate-evidence/1"]
    claim_definition_identity: ContentIdentity
    research: Annotated[
        tuple[ResearchEvidence, ...], Field(max_length=MAX_RESEARCH_ITEMS)
    ] = ()
    operation_artifacts: Annotated[
        tuple[CanonicalArtifactEnvelope, ...], Field(max_length=MAX_CLAIM_FACTS)
    ] = ()
    vector_artifacts: Annotated[
        tuple[CanonicalArtifactEnvelope, ...], Field(max_length=MAX_CLAIM_FACTS)
    ] = ()
    public_artifacts: Annotated[
        tuple[CanonicalArtifactEnvelope, ...], Field(max_length=MAX_CLAIM_FACTS)
    ] = ()


class CandidateDiagnostic(_ClosedModel):
    """Aggregation finding, not a Kernel/LDB typed-refusal Diagnostic."""

    code: StableId
    subject: DiagnosticSubject
    message: Annotated[str, Field(max_length=512)]


class ClaimCandidateReport(_ClosedModel):
    schema_version: Literal["schema2-claim-candidate-report/1"]
    claim_id: ClaimId
    claim_definition_identity: ContentIdentity
    subject: ExactSubjectIdentities
    status: Literal["candidate", "open"]
    diagnostics: tuple[CandidateDiagnostic, ...]


def _duplicate_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(value for value, count in Counter(values).items() if count > 1))


def _diagnostic(code: str, subject: str, message: str) -> CandidateDiagnostic:
    return CandidateDiagnostic(code=code, subject=subject, message=message)


def _inspect_envelope(
    envelope: CanonicalArtifactEnvelope,
    subject: str,
    diagnostics: list[CandidateDiagnostic],
) -> tuple[Any | None, bool]:
    valid = True
    expected = artifact_content_identity(
        envelope.artifact_kind, envelope.wire_schema_identity, envelope.payload
    )
    if envelope.content_identity != expected:
        diagnostics.append(
            _diagnostic(
                "artifact_identity_mismatch",
                subject,
                "Artifact content identity does not match its exact payload bytes.",
            )
        )
        valid = False
    try:
        payload = _decode_canonical_payload(envelope.payload)
    except ValueError:
        diagnostics.append(
            _diagnostic(
                "artifact_payload_invalid",
                subject,
                "Artifact payload is not bounded canonical strict JSON.",
            )
        )
        return None, False
    return payload, valid


def _parse_typed_payload(
    model: type[BaseModel],
    payload: Any,
    subject: str,
    diagnostics: list[CandidateDiagnostic],
) -> BaseModel | None:
    try:
        return model.model_validate(payload)
    except ValidationError:
        diagnostics.append(
            _diagnostic(
                "artifact_payload_schema_invalid",
                subject,
                "Artifact payload does not match its closed result schema.",
            )
        )
        return None


def _resolve_json_pointer(payload: Any, pointer: str) -> tuple[bool, Any]:
    current = payload
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _public_header(
    payload: Any,
    subject: str,
    diagnostics: list[CandidateDiagnostic],
) -> tuple[ExactSubjectIdentities, str] | None:
    if not isinstance(payload, dict):
        diagnostics.append(
            _diagnostic(
                "public_artifact_header_invalid",
                subject,
                "Public artifact payload must be an object.",
            )
        )
        return None
    try:
        artifact_subject = ExactSubjectIdentities.model_validate(payload["subject"])
        source_vector_id = payload["source_vector_id"]
        if not isinstance(source_vector_id, str) or not source_vector_id:
            raise ValueError
        if not source_vector_id[0].isalpha() or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in source_vector_id
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, ValidationError):
        diagnostics.append(
            _diagnostic(
                "public_artifact_header_invalid",
                subject,
                "Public artifact must bind a valid exact subject and source vector id.",
            )
        )
        return None
    return artifact_subject, source_vector_id


def assess_claim_candidate(
    requirement: ClaimCandidateRequirement,
    evidence: ClaimCandidateEvidence,
) -> ClaimCandidateReport:
    """Report every bounded, independently observable closure defect."""

    diagnostics: list[CandidateDiagnostic] = []
    definition_identity = claim_definition_identity(requirement)
    if evidence.claim_definition_identity != definition_identity:
        diagnostics.append(
            _diagnostic(
                "claim_definition_identity_drift",
                "evidence.claim_definition_identity",
                "Evidence was assembled for a different canonical claim definition.",
            )
        )

    if not requirement.operations:
        diagnostics.append(
            _diagnostic(
                "missing_operation_requirement",
                "operations",
                "A claim row must require at least one versioned Operation.",
            )
        )
    if not any(item.role == "positive" for item in requirement.vectors):
        diagnostics.append(
            _diagnostic(
                "missing_positive_vector_requirement",
                "vectors.positive",
                "A claim row must require at least one positive vector.",
            )
        )
    if not any(item.role in {"negative", "boundary"} for item in requirement.vectors):
        diagnostics.append(
            _diagnostic(
                "missing_non_positive_vector_requirement",
                "vectors.non_positive",
                "A claim row must require a negative or boundary vector.",
            )
        )
    if not requirement.public_observables:
        diagnostics.append(
            _diagnostic(
                "missing_public_observable_requirement",
                "public_observables",
                "A claim row must require at least one public observable.",
            )
        )

    for operation_id in _duplicate_ids(
        tuple(item.operation_id for item in requirement.operations)
    ):
        diagnostics.append(
            _diagnostic(
                "duplicate_operation_requirement",
                operation_id,
                "Required Operation ids must be unique.",
            )
        )
    for vector_id in _duplicate_ids(
        tuple(item.vector_id for item in requirement.vectors)
    ):
        diagnostics.append(
            _diagnostic(
                "duplicate_vector_requirement",
                vector_id,
                "Required vector ids must be unique.",
            )
        )
    for field_id in _duplicate_ids(
        tuple(item.field_id for item in requirement.public_observables)
    ):
        diagnostics.append(
            _diagnostic(
                "duplicate_public_observable_requirement",
                field_id,
                "Required public observable field ids must be unique.",
            )
        )
    for evidence_id in _duplicate_ids(
        tuple(item.evidence_id for item in evidence.research)
    ):
        diagnostics.append(
            _diagnostic(
                "duplicate_research_evidence",
                evidence_id,
                "Research evidence ids must be unique.",
            )
        )

    required_operations = {item.operation_id: item for item in requirement.operations}
    seen_operations: list[str] = []
    for index, envelope in enumerate(evidence.operation_artifacts):
        label = f"operation_artifacts[{index}]"
        payload, integrity_ok = _inspect_envelope(envelope, label, diagnostics)
        kind_ok = envelope.artifact_kind == "operation_admission"
        schema_ok = (
            envelope.wire_schema_identity == OPERATION_ADMISSION_WIRE_SCHEMA_IDENTITY
        )
        if not kind_ok:
            diagnostics.append(
                _diagnostic(
                    "operation_artifact_kind_invalid",
                    label,
                    "Operation evidence must be an operation_admission artifact.",
                )
            )
        if not schema_ok:
            diagnostics.append(
                _diagnostic(
                    "operation_wire_schema_invalid",
                    label,
                    "Operation evidence uses an unknown wire schema.",
                )
            )
        parsed = _parse_typed_payload(
            OperationAdmissionPayload, payload, label, diagnostics
        )
        if not isinstance(parsed, OperationAdmissionPayload):
            continue
        seen_operations.append(parsed.operation_id)
        expected = required_operations.get(parsed.operation_id)
        if expected is None:
            diagnostics.append(
                _diagnostic(
                    "extra_operation",
                    parsed.operation_id,
                    "Operation admission is not required by this claim.",
                )
            )
        elif parsed.package_release_identity != expected.package_release_identity:
            diagnostics.append(
                _diagnostic(
                    "operation_package_identity_drift",
                    parsed.operation_id,
                    "Operation admission binds a different package release.",
                )
            )
        if parsed.verification_failures:
            diagnostics.append(
                _diagnostic(
                    "operation_not_verified",
                    parsed.operation_id,
                    "Operation admission artifact records verification failures.",
                )
            )
        if parsed.subject != requirement.subject:
            diagnostics.append(
                _diagnostic(
                    "operation_identity_drift",
                    parsed.operation_id,
                    "Operation admission binds a different exact subject.",
                )
            )
        if not integrity_ok or not kind_ok or not schema_ok:
            continue
    for operation_id in required_operations:
        if operation_id not in seen_operations:
            diagnostics.append(
                _diagnostic(
                    "missing_operation",
                    operation_id,
                    "The required admitted Operation has no artifact.",
                )
            )
    for operation_id in _duplicate_ids(tuple(seen_operations)):
        diagnostics.append(
            _diagnostic(
                "duplicate_operation_result",
                operation_id,
                "Operation admission artifacts must be unique.",
            )
        )

    required_vectors = {item.vector_id: item for item in requirement.vectors}
    seen_vectors: list[str] = []
    for index, envelope in enumerate(evidence.vector_artifacts):
        label = f"vector_artifacts[{index}]"
        payload, integrity_ok = _inspect_envelope(envelope, label, diagnostics)
        kind_ok = envelope.artifact_kind == "normative_vector_result"
        schema_ok = envelope.wire_schema_identity == VECTOR_RESULT_WIRE_SCHEMA_IDENTITY
        if not kind_ok:
            diagnostics.append(
                _diagnostic(
                    "vector_artifact_kind_invalid",
                    label,
                    "Vector evidence must be a normative_vector_result artifact.",
                )
            )
        if not schema_ok:
            diagnostics.append(
                _diagnostic(
                    "vector_wire_schema_invalid",
                    label,
                    "Vector evidence uses an unknown wire schema.",
                )
            )
        parsed = _parse_typed_payload(VectorResultPayload, payload, label, diagnostics)
        if not isinstance(parsed, VectorResultPayload):
            continue
        seen_vectors.append(parsed.vector_id)
        expected = required_vectors.get(parsed.vector_id)
        if expected is None:
            diagnostics.append(
                _diagnostic(
                    "extra_vector",
                    parsed.vector_id,
                    "Normative vector result is not required by this claim.",
                )
            )
        else:
            if parsed.role != expected.role:
                diagnostics.append(
                    _diagnostic(
                        "vector_role_drift",
                        parsed.vector_id,
                        "Normative vector role differs from the claim.",
                    )
                )
            if parsed.disposition != expected.expected_disposition:
                diagnostics.append(
                    _diagnostic(
                        "vector_disposition_drift",
                        parsed.vector_id,
                        "Normative vector disposition differs from the claim.",
                    )
                )
        if parsed.verification_failures:
            diagnostics.append(
                _diagnostic(
                    "vector_not_verified",
                    parsed.vector_id,
                    "Normative vector artifact records verification failures.",
                )
            )
        if parsed.subject != requirement.subject:
            diagnostics.append(
                _diagnostic(
                    "vector_identity_drift",
                    parsed.vector_id,
                    "Normative vector result binds a different exact subject.",
                )
            )
        if not integrity_ok or not kind_ok or not schema_ok:
            continue
    for vector_id in required_vectors:
        if vector_id not in seen_vectors:
            diagnostics.append(
                _diagnostic(
                    "missing_vector",
                    vector_id,
                    "The required normative vector has no artifact.",
                )
            )
    for vector_id in _duplicate_ids(tuple(seen_vectors)):
        diagnostics.append(
            _diagnostic(
                "duplicate_vector_result",
                vector_id,
                "Normative vector artifacts must be unique.",
            )
        )

    public_records: list[
        tuple[CanonicalArtifactEnvelope, Any, ExactSubjectIdentities, str, bool]
    ] = []
    for index, envelope in enumerate(evidence.public_artifacts):
        label = f"public_artifacts[{index}]"
        payload, integrity_ok = _inspect_envelope(envelope, label, diagnostics)
        header = _public_header(payload, label, diagnostics)
        if header is None:
            diagnostics.append(
                _diagnostic(
                    "extra_public_artifact",
                    envelope.content_identity,
                    "Public artifact cannot satisfy a required observable.",
                )
            )
            continue
        artifact_subject, source_vector_id = header
        if source_vector_id not in required_vectors:
            diagnostics.append(
                _diagnostic(
                    "public_observation_source_unknown",
                    source_vector_id,
                    "Public artifact names an unrequired vector source.",
                )
            )
        if artifact_subject != requirement.subject:
            diagnostics.append(
                _diagnostic(
                    "public_observation_identity_drift",
                    envelope.content_identity,
                    "Public artifact binds a different exact subject.",
                )
            )
        public_records.append(
            (envelope, payload, artifact_subject, source_vector_id, integrity_ok)
        )

    used_public_identities: set[str] = set()
    for required in requirement.public_observables:
        satisfying: list[str] = []
        pointer_seen = False
        for (
            envelope,
            payload,
            artifact_subject,
            source_vector_id,
            integrity_ok,
        ) in public_records:
            present, _ = _resolve_json_pointer(payload, required.json_pointer)
            if not present:
                continue
            pointer_seen = True
            if source_vector_id != required.source_vector_id:
                diagnostics.append(
                    _diagnostic(
                        "public_observation_source_drift",
                        required.field_id,
                        "Public observable comes from a different vector.",
                    )
                )
                continue
            if envelope.artifact_kind != required.artifact_kind:
                diagnostics.append(
                    _diagnostic(
                        "public_observation_artifact_kind_drift",
                        required.field_id,
                        "Public observable uses a different artifact kind.",
                    )
                )
                continue
            if envelope.wire_schema_identity != required.wire_schema_identity:
                diagnostics.append(
                    _diagnostic(
                        "public_observation_wire_schema_drift",
                        required.field_id,
                        "Public observable uses a different wire schema.",
                    )
                )
                continue
            if artifact_subject != requirement.subject or not integrity_ok:
                continue
            satisfying.append(envelope.content_identity)
            used_public_identities.add(envelope.content_identity)
        if not satisfying:
            diagnostics.append(
                _diagnostic(
                    "missing_public_observation",
                    required.field_id,
                    "No exact bound public artifact contains the required JSON pointer.",
                )
            )
            if not pointer_seen:
                diagnostics.append(
                    _diagnostic(
                        "public_observation_pointer_missing",
                        required.field_id,
                        "Required JSON pointer is absent from all public artifacts.",
                    )
                )
        if len(satisfying) > 1:
            diagnostics.append(
                _diagnostic(
                    "duplicate_public_observation",
                    required.field_id,
                    "Multiple public artifacts satisfy one observable requirement.",
                )
            )
    for envelope, _, _, _, _ in public_records:
        if envelope.content_identity not in used_public_identities:
            diagnostics.append(
                _diagnostic(
                    "extra_public_artifact",
                    envelope.content_identity,
                    "Public artifact satisfies no exact observable requirement.",
                )
            )
    for identity in _duplicate_ids(
        tuple(item.content_identity for item in evidence.public_artifacts)
    ):
        diagnostics.append(
            _diagnostic(
                "duplicate_public_artifact",
                identity,
                "Public artifact identities must be unique.",
            )
        )

    unique = {(item.code, item.subject, item.message): item for item in diagnostics}
    ordered = tuple(
        sorted(
            unique.values(), key=lambda item: (item.code, item.subject, item.message)
        )
    )
    return ClaimCandidateReport(
        schema_version="schema2-claim-candidate-report/1",
        claim_id=requirement.claim_id,
        claim_definition_identity=definition_identity,
        subject=requirement.subject,
        status="open" if ordered else "candidate",
        diagnostics=ordered,
    )


def canonical_candidate_report(report: ClaimCandidateReport) -> str:
    return canonical_json(model_payload(report))
