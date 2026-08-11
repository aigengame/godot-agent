"""Typed logical membership of a Standard Schema artifact set."""

from dataclasses import dataclass


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
