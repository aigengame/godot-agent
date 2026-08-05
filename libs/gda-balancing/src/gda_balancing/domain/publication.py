"""Standard Schema artifact-set publication contracts and orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.schema2.canonical import JsonValue

if TYPE_CHECKING:
    from gda_balancing.schema2.model import CheckedModel


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


def publication_authentication_key() -> bytes:
    """Load the configured key for authenticating publication anchors."""
    from gda_balancing.schema2.model import publication_authentication_key as load

    return load()


def publish_artifact_set(
    artifacts: dict[str, PublicationMember],
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    member_validator: Callable[[str, dict[str, Any]], bool],
    publication_fault: str | None = None,
    *,
    artifact_set_validator: Callable[[dict[str, dict[str, Any]]], bool] | None = None,
    authentication_key: bytes | None = None,
) -> dict[str, JsonValue]:
    """Publish one pre-admitted heterogeneous artifact set atomically."""
    from gda_balancing.schema2.model import publish_artifact_set as publish

    return publish(
        artifacts,
        out,
        invocation_key,
        descriptor_identity,
        command_input_identity,
        language_bundle,
        artifact_set,
        member_validator,
        publication_fault,
        artifact_set_validator=artifact_set_validator,
        authentication_key=authentication_key,
    )


def recover_committed_artifact_set(
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    candidate_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
    member_validator: Callable[[str, dict[str, Any]], bool],
    *,
    artifact_set_validator: Callable[[dict[str, dict[str, Any]]], bool] | None = None,
    authentication_key: bytes | None = None,
) -> RecoveredArtifactSet | None:
    """Recover and re-admit one committed artifact-set outcome."""
    from gda_balancing.schema2.model import recover_committed_artifact_set as recover

    return recover(
        out,
        invocation_key,
        descriptor_identity,
        command_input_identity,
        language_bundle,
        candidate_sets,
        member_validator,
        artifact_set_validator=artifact_set_validator,
        authentication_key=authentication_key,
    )


def publish_model_artifacts(
    checked: CheckedModel,
    source_path: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    publication_fault: str | None = None,
    *,
    authentication_key: bytes | None = None,
    compiler: Callable[[CheckedModel], dict[str, dict[str, JsonValue]]] | None = None,
) -> dict[str, JsonValue]:
    """Publish one checked Model while preserving recovery-before-compilation."""
    from gda_balancing.schema2.model import publish_model_artifacts as publish

    return publish(
        checked,
        source_path,
        out,
        invocation_key,
        descriptor_identity,
        artifact_set,
        publication_fault,
        authentication_key=authentication_key,
        compiler=compiler,
    )
