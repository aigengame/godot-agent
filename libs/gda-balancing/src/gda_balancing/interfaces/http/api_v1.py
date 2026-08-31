"""The versioned, application-agnostic local Execution HTTP API."""

import json
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from gda_balancing.application.execution_sessions import (
    ExecutionSessionNotFound,
    ExecutionSessions,
    ExperimentRevisionNotFound,
)
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.infrastructure.distribution import distribution_version
from gda_balancing.interfaces.execution_service_language import (
    AdmitExperimentRevisionRequest,
    CreateExecutionSessionRequest,
    ExecutionServiceErrorCode,
    ExecutionSessionDeletedResponse,
    RunExperimentRequest,
    admit_experiment_revision_response,
    establish_session_response,
    execution_service_error,
    run_experiment_revision_response,
)
from gda_balancing.interfaces.http.service_errors import (
    SMALL_HTTP_REQUEST_BYTES,
    HttpRequestTooLarge,
    InvalidHttpRequest,
    UnsupportedHttpMediaType,
    http_exception_response,
    internal_service_error_response,
    invalid_http_request_response,
    read_bounded_request_body,
    request_too_large_response,
    require_empty_request,
    unsupported_media_type_response,
)

PROTOCOL_VERSION = "v1"
_PROTOCOL_ENVELOPE_BYTES = 65_536
RequestModel = TypeVar("RequestModel", bound=BaseModel)


class _DuplicateObjectMember(ValueError):
    """A JSON object repeats a member name before schema admission."""


def _execution_service_error_response(
    code: ExecutionServiceErrorCode,
) -> JSONResponse:
    return JSONResponse(
        execution_service_error(code).model_dump(mode="json"),
        status_code=404,
    )


def _closed_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, member in pairs:
        if name in value:
            raise _DuplicateObjectMember(name)
        value[name] = member
    return value


async def _request_model(
    request: Request,
    model: type[RequestModel],
    *,
    max_bytes: int,
) -> RequestModel:
    media_type = request.headers.get("content-type", "").partition(";")[0].strip()
    if media_type.lower() != "application/json":
        raise UnsupportedHttpMediaType
    body = await read_bounded_request_body(request, max_bytes=max_bytes)
    try:
        value = json.loads(body, object_pairs_hook=_closed_json_object)
        return model.model_validate(value)
    except (
        _DuplicateObjectMember,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValidationError,
    ) as error:
        raise InvalidHttpRequest from error


class StatusResponse(BaseModel):
    """Technical status of one ready local service process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"] = "ready"
    protocol: Literal["v1"] = PROTOCOL_VERSION
    toolkit_version: str


def create_api_v1() -> ASGIApp:
    """Create execution routes without local-host lifecycle or authentication."""
    toolkit_version = distribution_version("gda-balancing")
    sessions = ExecutionSessions()
    max_source_bytes = cast(
        int,
        packaged_authority_context().language_bundle["resources"]["max_source_bytes"],
    )

    async def status(request: Request) -> Response:
        if request.method != "GET":
            raise HTTPException(status_code=405, headers={"Allow": "GET"})
        await require_empty_request(request)
        return JSONResponse(
            StatusResponse(toolkit_version=toolkit_version).model_dump(mode="json")
        )

    async def create_execution_session(request: Request) -> Response:
        payload = await _request_model(
            request,
            CreateExecutionSessionRequest,
            max_bytes=(2 * max_source_bytes) + _PROTOCOL_ENVELOPE_BYTES,
        )
        result = await run_in_threadpool(
            sessions.create,
            payload.model_source,
            payload.experiment_specification,
        )
        body = establish_session_response(result)
        return JSONResponse(body.model_dump(mode="json"))

    async def admit_experiment_revision(request: Request) -> Response:
        payload = await _request_model(
            request,
            AdmitExperimentRevisionRequest,
            max_bytes=max_source_bytes + _PROTOCOL_ENVELOPE_BYTES,
        )
        try:
            result = await run_in_threadpool(
                sessions.admit_revision,
                request.path_params["session_id"],
                payload.experiment_specification,
            )
        except ExecutionSessionNotFound:
            return _execution_service_error_response("unknown_execution_session")
        body = admit_experiment_revision_response(result)
        return JSONResponse(body.model_dump(mode="json"))

    async def run_experiment_revision(request: Request) -> Response:
        payload = await _request_model(
            request,
            RunExperimentRequest,
            max_bytes=SMALL_HTTP_REQUEST_BYTES,
        )
        try:
            result = await run_in_threadpool(
                sessions.run,
                request.path_params["session_id"],
                payload.revision_id,
            )
        except ExecutionSessionNotFound:
            return _execution_service_error_response("unknown_execution_session")
        except ExperimentRevisionNotFound:
            return _execution_service_error_response("unknown_experiment_revision")
        body = run_experiment_revision_response(result)
        return JSONResponse(body.model_dump(mode="json"))

    async def delete_execution_session(request: Request) -> Response:
        await require_empty_request(request)
        session_id = request.path_params["session_id"]
        try:
            await run_in_threadpool(sessions.delete, session_id)
        except ExecutionSessionNotFound:
            return _execution_service_error_response("unknown_execution_session")
        return JSONResponse(
            ExecutionSessionDeletedResponse(session_id=session_id).model_dump(
                mode="json"
            )
        )

    async def unexpected_internal_error(
        _request: Request,
        _error: Exception,
    ) -> Response:
        return internal_service_error_response()

    app = Starlette(
        debug=False,
        exception_handlers={
            HTTPException: http_exception_response,
            InvalidHttpRequest: invalid_http_request_response,
            HttpRequestTooLarge: request_too_large_response,
            UnsupportedHttpMediaType: unsupported_media_type_response,
            Exception: unexpected_internal_error,
        },
        routes=[
            Route("/v1/status", status, methods=["GET"]),
            Route(
                "/v1/execution-sessions",
                create_execution_session,
                methods=["POST"],
            ),
            Route(
                "/v1/execution-sessions/{session_id:str}/experiment-revisions",
                admit_experiment_revision,
                methods=["POST"],
            ),
            Route(
                "/v1/execution-sessions/{session_id:str}/runs",
                run_experiment_revision,
                methods=["POST"],
            ),
            Route(
                "/v1/execution-sessions/{session_id:str}",
                delete_execution_session,
                methods=["DELETE"],
            ),
        ],
    )
    app.router.redirect_slashes = False
    return app
