"""The versioned, application-agnostic local Execution HTTP API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from gda_balancing.infrastructure.distribution import distribution_version

PROTOCOL_VERSION = "v1"


class StatusResponse(BaseModel):
    """Technical status of one ready local service process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"] = "ready"
    protocol: Literal["v1"] = PROTOCOL_VERSION
    toolkit_version: str


def create_api_v1() -> ASGIApp:
    """Create execution routes without local-host lifecycle or authentication."""
    toolkit_version = distribution_version("gda-balancing")

    async def status(_request: Request) -> Response:
        return JSONResponse(
            StatusResponse(toolkit_version=toolkit_version).model_dump(mode="json")
        )

    return Starlette(
        debug=False,
        routes=[
            Route("/v1/status", status, methods=["GET"]),
        ],
    )
