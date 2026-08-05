"""Values shared by artifact-set publication rules and their callers."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue


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
