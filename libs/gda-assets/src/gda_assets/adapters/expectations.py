"""JSON syntax and shape for the small, project-owned expectation document."""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from gda_assets.application.ports import PortFailure
from gda_assets.domain.expectations import Expectation, validate_conditions


class ConditionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)


class NodeInput(ConditionInput):
    kind: Literal["node"]
    node: str
    type: str | None = Field(default=None, min_length=1)


class CountInput(ConditionInput):
    kind: Literal["count"]
    metric: Literal["node_count", "mesh_instance_count", "unique_mesh_count"]
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)


class DimensionsInput(ConditionInput):
    kind: Literal["dimensions"]
    min: list[float] | None = Field(default=None, min_length=3, max_length=3)
    max: list[float] | None = Field(default=None, min_length=3, max_length=3)


class MaterialInput(ConditionInput):
    kind: Literal["material"]
    node: str
    surface: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1)
    path: str | None = Field(default=None, min_length=1)


class BoneInput(ConditionInput):
    kind: Literal["bone"]
    node: str
    name: str = Field(min_length=1)


class SkinBindInput(ConditionInput):
    kind: Literal["skin_bind"]
    node: str
    bind: int = Field(ge=0)
    skeleton: str
    bone: str = Field(min_length=1)


class AnimationTargetInput(ConditionInput):
    kind: Literal["animation_target"]
    node: str
    animation: str = Field(min_length=1)
    track: int = Field(ge=0)
    target: str
    bone: str | None = Field(default=None, min_length=1)


class ExpectationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    checks: list[
        Annotated[
            NodeInput
            | CountInput
            | DimensionsInput
            | MaterialInput
            | BoneInput
            | SkinBindInput
            | AnimationTargetInput,
            Field(discriminator="kind"),
        ]
    ] = Field(min_length=1, max_length=256)

    @field_validator("checks")
    @classmethod
    def _unique_ids(cls, checks):
        if len({check.id for check in checks}) != len(checks):
            raise ValueError("check ids must be unique")
        return checks


def read_expectations(path: Path) -> tuple[Expectation, ...]:
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("expectation document exceeds 1 MiB")
        document = ExpectationDocument.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        conditions = tuple(
            Expectation(
                item.id,
                item.kind,
                getattr(item, "node", None),
                item.model_dump(exclude={"id", "kind", "node"}, exclude_none=True),
            )
            for item in document.checks
        )
        validate_conditions(conditions)
        return conditions
    except (OSError, ValueError, ValidationError) as exc:
        raise PortFailure("invalid_expectations", str(exc)) from exc
