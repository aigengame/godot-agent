"""In-process loopback ASGI host lifecycle for the local Execution API."""

import asyncio
import ipaddress
import secrets
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import uvicorn
from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class LocalHostReadiness:
    host: str
    port: int
    capability_token: str


ApplicationFactory = Callable[[], ASGIApp]
ReadinessEmitter = Callable[[LocalHostReadiness], None]


class ShutdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["shutting-down"] = "shutting-down"


class ServiceError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["service"] = "service"
    code: Literal["authentication_required"]
    message: str


class ServiceErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ServiceError


class BearerCapabilityMiddleware:
    """Require the process capability on every versioned local-host route."""

    def __init__(self, app: ASGIApp, capability_token: str) -> None:
        self._app = app
        self._authorization = f"Bearer {capability_token}".encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/"):
            await self._app(scope, receive, send)
            return
        authorization = next(
            (value for name, value in scope["headers"] if name == b"authorization"),
            b"",
        )
        if not secrets.compare_digest(authorization, self._authorization):
            response = JSONResponse(
                ServiceErrorEnvelope(
                    error=ServiceError(
                        code="authentication_required",
                        message="a valid local process capability is required",
                    )
                ).model_dump(mode="json"),
                status_code=401,
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


def _local_companion_app(
    execution_api: ASGIApp,
    capability_token: str,
    request_shutdown: Callable[[], None],
) -> ASGIApp:
    async def shutdown(_request: Request) -> Response:
        response = JSONResponse(ShutdownResponse().model_dump(mode="json"))
        request_shutdown()
        return response

    app = Starlette(
        debug=False,
        routes=[
            Route("/v1/shutdown", shutdown, methods=["POST"]),
            Mount("/", app=execution_api),
        ],
    )
    return BearerCapabilityMiddleware(app, capability_token)


def run_local_host(
    *,
    host: str,
    port: int,
    application_factory: ApplicationFactory,
    emit_ready: ReadinessEmitter,
) -> int:
    """Bind one loopback socket, serve until requested shutdown, and return 0."""
    address = ipaddress.ip_address(host)
    if not address.is_loopback:
        raise ValueError("the local service accepts only loopback bindings")
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen()
        listener.setblocking(False)
        actual_port = listener.getsockname()[1]
        return asyncio.run(
            _serve(
                listener=listener,
                host=host,
                port=actual_port,
                application_factory=application_factory,
                emit_ready=emit_ready,
            )
        )
    finally:
        listener.close()


async def _serve(
    *,
    listener: socket.socket,
    host: str,
    port: int,
    application_factory: ApplicationFactory,
    emit_ready: ReadinessEmitter,
) -> int:
    capability_token = secrets.token_urlsafe(32)
    server_ref: list[uvicorn.Server] = []

    def request_shutdown() -> None:
        server_ref[0].should_exit = True

    app = _local_companion_app(
        application_factory(), capability_token, request_shutdown
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        access_log=False,
        date_header=False,
        lifespan="off",
        log_level="warning",
        proxy_headers=False,
        server_header=False,
        timeout_graceful_shutdown=10,
        workers=1,
    )
    server = uvicorn.Server(config)
    server_ref.append(server)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        if task.done():
            await task
            raise RuntimeError("the local service stopped during startup")
        await asyncio.sleep(0.01)
    emit_ready(
        LocalHostReadiness(
            host=host,
            port=port,
            capability_token=capability_token,
        )
    )
    await task
    return 0
