"""Closed transport and service-error responses for the local HTTP protocol."""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response


SMALL_HTTP_REQUEST_BYTES = 65_536


ServiceErrorCode = Literal[
    "authentication_required",
    "internal_error",
    "invalid_request",
    "method_not_allowed",
    "request_too_large",
    "service_shutting_down",
    "unsupported_media_type",
    "unknown_endpoint",
    "unknown_execution_session",
    "unknown_experiment_revision",
]


class InvalidHttpRequest(ValueError):
    """The request body does not match its closed HTTP schema."""


class HttpRequestTooLarge(Exception):
    """The request body exceeds its route-specific protocol bound."""


class UnsupportedHttpMediaType(Exception):
    """An execution route received a body outside the JSON transport."""


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
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Render one closed protocol error without a Domain refusal."""
    return JSONResponse(
        ServiceErrorEnvelope(error=ServiceError(code=code, message=message)).model_dump(
            mode="json"
        ),
        status_code=status_code,
        headers=headers,
    )


def internal_service_error_response() -> JSONResponse:
    """Render the one sanitized response for an unexpected service fault."""
    return service_error_response(
        code="internal_error",
        message="the local service failed unexpectedly",
        status_code=500,
    )


async def read_bounded_request_body(
    request: Request,
    *,
    max_bytes: int,
) -> bytes:
    """Read one request body without trusting declared or streamed length."""
    if request.scope.get("query_string", b""):
        raise InvalidHttpRequest
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            declared = int(declared_length)
        except ValueError as error:
            raise InvalidHttpRequest from error
        if declared < 0:
            raise InvalidHttpRequest
        if declared > max_bytes:
            raise HttpRequestTooLarge
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_bytes:
                raise HttpRequestTooLarge
            body.extend(chunk)
    except ClientDisconnect as error:
        raise InvalidHttpRequest from error
    return bytes(body)


async def require_empty_request(request: Request) -> None:
    """Apply the bounded empty schema used by bodyless protocol routes."""
    if await read_bounded_request_body(
        request,
        max_bytes=SMALL_HTTP_REQUEST_BYTES,
    ):
        raise InvalidHttpRequest


async def invalid_http_request_response(
    _request: Request,
    _error: Exception,
) -> Response:
    return service_error_response(
        code="invalid_request",
        message="the request does not match the closed HTTP schema",
        status_code=400,
    )


async def request_too_large_response(
    _request: Request,
    _error: Exception,
) -> Response:
    return service_error_response(
        code="request_too_large",
        message="the request body exceeds the HTTP protocol limit",
        status_code=413,
    )


async def unsupported_media_type_response(
    _request: Request,
    _error: Exception,
) -> Response:
    return service_error_response(
        code="unsupported_media_type",
        message="the request content type must be application/json",
        status_code=415,
    )


async def http_exception_response(
    _request: Request,
    error: Exception,
) -> Response:
    if not isinstance(error, HTTPException):
        return internal_service_error_response()
    if error.status_code == 404:
        return service_error_response(
            code="unknown_endpoint",
            message="the HTTP endpoint does not exist",
            status_code=404,
        )
    if error.status_code == 405:
        return service_error_response(
            code="method_not_allowed",
            message="the HTTP method is not allowed for this endpoint",
            status_code=405,
            headers=error.headers,
        )
    return internal_service_error_response()
