"""Shared typed result from headless and live static model-content sampling."""

from typing import Literal

from pydantic import BaseModel, Field

from gda.models import EngineVersion


class ModelContent(BaseModel):
    """Bounded, deterministic content facts returned by the native sampler."""

    measurement: Literal["godot-static-model-content-v3"]
    engine_version: EngineVersion
    complete: bool
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    nodes: int = Field(ge=0)
    surfaces: int = Field(ge=0)
    vertices: int = Field(ge=0)
    unsupported: list[str]
    omitted: list[str]
