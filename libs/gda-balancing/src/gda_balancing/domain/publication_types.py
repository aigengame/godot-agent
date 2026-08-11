"""Values shared by artifact-set publication rules and their callers."""

from dataclasses import dataclass
from typing import Any, Literal

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue


class PublicationAdmissionError(ValueError):
    """A supplied receipt or committed artifact set failed authentication."""

    def __init__(self, code: str, subject: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.subject = subject
        self.message = message


class PublicationError(Exception):
    """A publication could not safely bind or materialize its requested paths."""

    def __init__(
        self,
        reason: Literal[
            "unsafe_path",
            "output_unavailable",
            "invocation_key_conflict",
            "invalid_configuration",
        ],
        message: str,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class PublicationMember:
    """One pre-admitted value and its published artifact metadata."""

    value: dict[str, Any]
    artifact_kind: str
    wire_schema_identity: str
    content_identity: str


@dataclass(frozen=True)
class RecoveredArtifactSet:
    """One authenticated committed outcome recovered without recomputation."""

    receipt: dict[str, JsonValue]
    artifact_set: tuple[ArtifactSetMemberSpec, ...]
    artifacts: dict[str, dict[str, Any]]
