"""Standard Schema 1.x refusal values."""

from pydantic import BaseModel, ConfigDict, Field


REFUSAL_BOUND = 1000
JSON_POINTER_PATTERN = r"^(/([^/~]|~[01])*)*$"


class Refusal(BaseModel):
    """One element-level Standard Schema 1.x refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    path: str = Field(pattern=JSON_POINTER_PATTERN)
    detail: str


class RefusalReport(BaseModel):
    """One bounded Standard Schema 1.x refusal outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    refusals: tuple[Refusal, ...] = Field(min_length=1, max_length=REFUSAL_BOUND)
    truncated: bool
