"""The versioned, application-agnostic local Execution HTTP API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from gda_balancing.application.execution_sessions import (
    ExecutionSessionCreated,
    ExecutionSessions,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.infrastructure.distribution import distribution_version

PROTOCOL_VERSION = "v1"


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


def create_api_v1() -> ASGIApp:
    """Create execution routes without local-host lifecycle or authentication."""
    toolkit_version = distribution_version("gda-balancing")
    sessions = ExecutionSessions()

    async def status(_request: Request) -> Response:
        return JSONResponse(
            StatusResponse(toolkit_version=toolkit_version).model_dump(mode="json")
        )

    async def create_execution_session(request: Request) -> Response:
        payload = CreateExecutionSessionRequest.model_validate(await request.json())
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

    return Starlette(
        debug=False,
        routes=[
            Route("/v1/status", status, methods=["GET"]),
            Route(
                "/v1/execution-sessions",
                create_execution_session,
                methods=["POST"],
            ),
        ],
    )
