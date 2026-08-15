"""Closed transport and service-error responses for the local HTTP protocol."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse


ServiceErrorCode = Literal[
    "authentication_required",
    "invalid_request",
    "request_too_large",
    "unknown_execution_session",
    "unknown_experiment_revision",
]


class ServiceError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["service"] = "service"
    code: ServiceErrorCode
    message: str


class ServiceErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ServiceError


def service_error_response(
    *,
    code: ServiceErrorCode,
    message: str,
    status_code: int,
) -> JSONResponse:
    """Render one closed protocol error without a Domain refusal."""
    return JSONResponse(
        ServiceErrorEnvelope(error=ServiceError(code=code, message=message)).model_dump(
            mode="json"
        ),
        status_code=status_code,
    )
