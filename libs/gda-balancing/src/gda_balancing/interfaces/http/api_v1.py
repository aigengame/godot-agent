"""The versioned, application-agnostic local Execution HTTP API."""

from copy import deepcopy
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
    service_error_response,
    unsupported_media_type_response,
)

PROTOCOL_VERSION = "v1"
_PROTOCOL_ENVELOPE_BYTES = 65_536
RequestModel = TypeVar("RequestModel", bound=BaseModel)


class _DuplicateObjectMember(ValueError):
    """A JSON object repeats a member name before schema admission."""


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
            max_bytes=SMALL_HTTP_REQUEST_BYTES,
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
        await require_empty_request(request)
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
