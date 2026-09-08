"""Typed logical membership of a Standard Schema artifact set."""

from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import Any


@dataclass(frozen=True)
class ArtifactSetMemberSpec:
    """One logical member and its artifact kind within a published set."""

    logical_name: str
    artifact_kind: str
    role: str = "companion"

    def __post_init__(self) -> None:
        if not self.logical_name or not self.artifact_kind:
            raise ValueError("artifact-set member names and kinds must be non-empty")
        if self.role not in {"primary", "companion"}:
            raise ValueError("artifact-set member role must be primary or companion")


@dataclass(frozen=True)
class ProtocolArtifactSetMemberSpec:
    """A core output responsibility with a caller-chosen publication label."""

    protocol_role: str
    logical_name: str = ""
    role: str = "companion"

    def __post_init__(self) -> None:
        if not self.protocol_role:
            raise ValueError("artifact protocol role must be non-empty")
        if not self.logical_name:
            object.__setattr__(self, "logical_name", self.protocol_role)
        if self.role not in {"primary", "companion"}:
            raise ValueError("artifact-set member role must be primary or companion")


type ArtifactSetPlan = tuple[ArtifactSetMemberSpec | ProtocolArtifactSetMemberSpec, ...]


def resolve_artifact_set(
    language_bundle: dict[str, Any], members: ArtifactSetPlan
) -> tuple[ArtifactSetMemberSpec, ...]:
    """Resolve core roles while retaining explicitly declared extension kinds."""
    from gda_balancing.domain.wire_schema import protocol_kind

    return tuple(
        ArtifactSetMemberSpec(
            member.logical_name,
            protocol_kind(language_bundle, member.protocol_role),
            member.role,
        )
        if isinstance(member, ProtocolArtifactSetMemberSpec)
        else member
        for member in members
    )


EXPERIMENT_SUCCESS_ARTIFACT_SET = (
    ProtocolArtifactSetMemberSpec("evaluation-run", role="primary"),
    ProtocolArtifactSetMemberSpec(
        "event-trace",
    ),
    ProtocolArtifactSetMemberSpec(
        "snapshot-series",
    ),
    ProtocolArtifactSetMemberSpec(
        "metric-dataset",
    ),
    ProtocolArtifactSetMemberSpec(
        "resolved-runtime-profile",
    ),
    ProtocolArtifactSetMemberSpec(
        "evaluator-capability-manifest",
    ),
)

EXPERIMENT_VERDICT_ARTIFACT_SET = (
    ProtocolArtifactSetMemberSpec("experiment-verdict", role="primary"),
    ProtocolArtifactSetMemberSpec(
        "event-trace",
    ),
    ProtocolArtifactSetMemberSpec(
        "snapshot-series",
    ),
    ProtocolArtifactSetMemberSpec(
        "metric-dataset",
    ),
    ProtocolArtifactSetMemberSpec(
        "resolved-runtime-profile",
    ),
    ProtocolArtifactSetMemberSpec(
        "evaluator-capability-manifest",
    ),
)

EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET = (
    ProtocolArtifactSetMemberSpec(
        "runtime-terminal-audit",
        role="primary",
    ),
    ProtocolArtifactSetMemberSpec(
        "resolved-runtime-profile",
    ),
    ProtocolArtifactSetMemberSpec(
        "evaluator-capability-manifest",
    ),
)


def label_artifacts[T](
    artifacts: Mapping[str, T],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    kind: Callable[[T], str],
) -> dict[str, T]:
    """Attach chosen labels to one core set with unique protocol member kinds."""
    by_kind = {kind(value): value for value in artifacts.values()}
    if len(by_kind) != len(artifacts) or set(by_kind) != {
        member.artifact_kind for member in artifact_set
    }:
        raise ValueError("protocol artifacts do not match the declared member kinds")
    return {
        member.logical_name: by_kind[member.artifact_kind] for member in artifact_set
    }
