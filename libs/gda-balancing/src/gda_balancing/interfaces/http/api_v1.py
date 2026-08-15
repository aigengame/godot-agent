"""The versioned, application-agnostic local Execution HTTP API."""

from copy import deepcopy
import json
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from gda_balancing.application.execution_sessions import (
    ExecutionSessionCreated,
    ExecutionSessionNotFound,
    ExecutionSessions,
    ExperimentRevisionNotFound,
    ExperimentRevisionAdmitted,
)
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionRefusal,
    ExperimentExecutionSuccess,
    ExperimentExecutionVerdict,
)
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.infrastructure.distribution import distribution_version
from gda_balancing.interfaces.http.service_errors import (
    internal_service_error_response,
    service_error_response,
)

PROTOCOL_VERSION = "v1"
_PROTOCOL_ENVELOPE_BYTES = 65_536
_SMALL_REQUEST_BYTES = 65_536
RequestModel = TypeVar("RequestModel", bound=BaseModel)


class InvalidHttpRequest(ValueError):
    """The JSON body does not match its closed request schema."""


class HttpRequestTooLarge(Exception):
    """The request body exceeds its route-specific protocol bound."""


class UnsupportedHttpMediaType(Exception):
    """An execution route received a body outside the JSON transport."""


async def _request_model(
    request: Request,
    model: type[RequestModel],
    *,
    max_bytes: int,
) -> RequestModel:
    media_type = request.headers.get("content-type", "").partition(";")[0].strip()
    if media_type.lower() != "application/json":
        raise UnsupportedHttpMediaType
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_bytes:
                raise HttpRequestTooLarge
        except ValueError as error:
            raise InvalidHttpRequest from error
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_bytes:
                raise HttpRequestTooLarge
            body.extend(chunk)
    except ClientDisconnect as error:
        raise InvalidHttpRequest from error
    try:
        return model.model_validate(json.loads(bytes(body)))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
        raise InvalidHttpRequest from error


class StatusResponse(BaseModel):
    """Technical status of one ready local service process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"] = "ready"
    protocol: Literal["v1"] = PROTOCOL_VERSION
    toolkit_version: str


class CreateExecutionSessionRequest(BaseModel):
    """Complete authored values required to establish one session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_source: dict[str, Any]
    experiment_specification: dict[str, Any]


class ExecutionSessionCreatedResponse(BaseModel):
    """Exact identities established by successful session admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    session_id: str
    resolved_model_identity: str
    revision_id: str


class RefusalResponse(BaseModel):
    """Existing Domain refusal returned through the HTTP transport."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["refusal"] = "refusal"
    refusal: Schema2RefusalReport


class AdmitExperimentRevisionRequest(BaseModel):
    """One complete Experiment value for an existing session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_specification: dict[str, Any]


class ExperimentRevisionAdmittedResponse(BaseModel):
    """Identity and insertion state of an admitted revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    revision_id: str
    created: bool


class RunExperimentRequest(BaseModel):
    """The exact immutable revision selected for one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: str


class RunSuccessResponse(BaseModel):
    """A successful execution with its existing artifacts inline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    artifacts: dict[str, dict[str, Any]]


class RunVerdictResponse(BaseModel):
    """A metric verdict with its existing artifacts inline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["verdict"] = "verdict"
    failed_metrics: list[str]
    artifacts: dict[str, dict[str, Any]]


class RunRefusalResponse(BaseModel):
    """A typed refusal with any terminal-audit artifacts inline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["refusal"] = "refusal"
    refusal: Schema2RefusalReport
    artifacts: dict[str, dict[str, Any]]


class ExecutionSessionDeletedResponse(BaseModel):
    """Acknowledgement that one process-local session was released."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    session_id: str


def create_api_v1() -> ASGIApp:
    """Create execution routes without local-host lifecycle or authentication."""
    toolkit_version = distribution_version("gda-balancing")
    sessions = ExecutionSessions()
    max_source_bytes = cast(
        int,
        packaged_authority_context().language_bundle["resources"]["max_source_bytes"],
    )

    async def status(_request: Request) -> Response:
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
        if isinstance(result, Schema2RefusalReport):
            body = RefusalResponse(refusal=result)
        else:
            assert isinstance(result, ExecutionSessionCreated)
            body = ExecutionSessionCreatedResponse(
                session_id=result.session_id,
                resolved_model_identity=result.resolved_model_identity,
                revision_id=result.revision_id,
            )
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
            return service_error_response(
                code="unknown_execution_session",
                message="the Execution session does not exist",
                status_code=404,
            )
        if isinstance(result, Schema2RefusalReport):
            body = RefusalResponse(refusal=result)
        else:
            assert isinstance(result, ExperimentRevisionAdmitted)
            body = ExperimentRevisionAdmittedResponse(
                revision_id=result.revision_id,
                created=result.created,
            )
        return JSONResponse(body.model_dump(mode="json"))

    async def run_experiment_revision(request: Request) -> Response:
        payload = await _request_model(
            request,
            RunExperimentRequest,
            max_bytes=_SMALL_REQUEST_BYTES,
        )
        try:
            result = await run_in_threadpool(
                sessions.run,
                request.path_params["session_id"],
                payload.revision_id,
            )
        except ExecutionSessionNotFound:
            return service_error_response(
                code="unknown_execution_session",
                message="the Execution session does not exist",
                status_code=404,
            )
        except ExperimentRevisionNotFound:
            return service_error_response(
                code="unknown_experiment_revision",
                message="the Experiment revision does not exist",
                status_code=404,
            )
        artifacts = {
            name: deepcopy(member.value) for name, member in result.members.items()
        }
        if isinstance(result, ExperimentExecutionSuccess):
            body = RunSuccessResponse(artifacts=artifacts)
        elif isinstance(result, ExperimentExecutionVerdict):
            body = RunVerdictResponse(
                failed_metrics=list(result.failed_metrics),
                artifacts=artifacts,
            )
        else:
            assert isinstance(result, ExperimentExecutionRefusal)
            body = RunRefusalResponse(
                refusal=result.report,
                artifacts=artifacts,
            )
        return JSONResponse(body.model_dump(mode="json"))

    async def delete_execution_session(request: Request) -> Response:
        session_id = request.path_params["session_id"]
        try:
            await run_in_threadpool(sessions.delete, session_id)
        except ExecutionSessionNotFound:
            return service_error_response(
                code="unknown_execution_session",
                message="the Execution session does not exist",
                status_code=404,
            )
        return JSONResponse(
            ExecutionSessionDeletedResponse(session_id=session_id).model_dump(
                mode="json"
            )
        )

    async def invalid_http_request(_request: Request, _error: Exception) -> Response:
        return service_error_response(
            code="invalid_request",
            message="the request does not match the closed HTTP schema",
            status_code=400,
        )

    async def request_too_large(_request: Request, _error: Exception) -> Response:
        return service_error_response(
            code="request_too_large",
            message="the request body exceeds the HTTP protocol limit",
            status_code=413,
        )

    async def unsupported_media_type(_request: Request, _error: Exception) -> Response:
        return service_error_response(
            code="unsupported_media_type",
            message="the request content type must be application/json",
            status_code=415,
        )

    async def unexpected_internal_error(
        _request: Request,
        _error: Exception,
    ) -> Response:
        return internal_service_error_response()

    return Starlette(
        debug=False,
        exception_handlers={
            InvalidHttpRequest: invalid_http_request,
            HttpRequestTooLarge: request_too_large,
            UnsupportedHttpMediaType: unsupported_media_type,
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
