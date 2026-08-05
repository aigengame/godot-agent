"""Shared CLI result models for published artifact sets."""

from pydantic import BaseModel, ConfigDict


class ArtifactSetMemberLocator(BaseModel):
    """The public locator for one named artifact-set member."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_name: str
    locator: str
