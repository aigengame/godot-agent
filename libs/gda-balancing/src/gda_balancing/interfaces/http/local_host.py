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
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gda_balancing.interfaces.http.service_errors import (
    HttpRequestTooLarge,
    InvalidHttpRequest,
    http_exception_response,
    internal_service_error_response,
    invalid_http_request_response,
    request_too_large_response,
    require_empty_request,
    service_error_response,
)


@dataclass(frozen=True)
class LocalHostReadiness:
    host: str
    port: int
    capability_token: str


ApplicationFactory = Callable[[], ASGIApp]
ReadinessEmitter = Callable[[LocalHostReadiness], None]
FaultReporter = Callable[[Exception], None]
AdmissionProbe = Callable[[], bool]


class ShutdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["shutting-down"] = "shutting-down"


class _ShutdownEndpoint:
    """Bind the exact process-control method before the catch-all mount."""

    def __init__(self, request_shutdown: Callable[[], None]) -> None:
        self._request_shutdown = request_shutdown

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if request.method != "POST":
            raise HTTPException(status_code=405, headers={"Allow": "POST"})
        await require_empty_request(request)
        response = JSONResponse(ShutdownResponse().model_dump(mode="json"))
        self._request_shutdown()
        await response(scope, receive, send)


class LocalHostAdmissionMiddleware:
    """Require the process capability and an accepting local host."""

    def __init__(
        self,
        app: ASGIApp,
        capability_token: str,
        accepts_requests: AdmissionProbe,
    ) -> None:
        self._app = app
        self._authorization = f"Bearer {capability_token}".encode("ascii")
        self._accepts_requests = accepts_requests

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/"):
            await self._app(scope, receive, send)
            return
        authorization = next(
            (value for name, value in scope["headers"] if name == b"authorization"),
            b"",
        )
        if not secrets.compare_digest(authorization, self._authorization):
            response = service_error_response(
                code="authentication_required",
                message="a valid local process capability is required",
                status_code=401,
            )
            await response(scope, receive, send)
            return
        if not self._accepts_requests():
            response = service_error_response(
                code="service_shutting_down",
                message="the local service is shutting down",
                status_code=503,
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


class FatalApplicationFaultMiddleware:
    """Stop the foreground host after one unexpected application fault."""

    def __init__(self, app: ASGIApp, report_fault: FaultReporter) -> None:
        self._app = app
        self._report_fault = report_fault

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response_started = False

        async def observe_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, observe_send)
        except Exception as error:
            self._report_fault(error)
            if not response_started:
                response = internal_service_error_response()
                await response(scope, receive, send)


def _local_companion_app(
    execution_api: ASGIApp,
    capability_token: str,
    accepts_requests: AdmissionProbe,
    request_shutdown: Callable[[], None],
) -> ASGIApp:
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
            Exception: unexpected_internal_error,
        },
        routes=[
            Route("/v1/shutdown", _ShutdownEndpoint(request_shutdown)),
            Mount("/", app=execution_api),
        ],
    )
    app.router.redirect_slashes = False
    return LocalHostAdmissionMiddleware(
        app,
        capability_token,
        accepts_requests,
    )


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
    fatal_error: list[Exception] = []
    accepting_requests = True

    def accepts_requests() -> bool:
        return accepting_requests

    def request_shutdown() -> None:
        nonlocal accepting_requests
        accepting_requests = False
        server_ref[0].should_exit = True

    def report_fault(error: Exception) -> None:
        if not fatal_error:
            fatal_error.append(error)
            request_shutdown()

    app = FatalApplicationFaultMiddleware(
        _local_companion_app(
            application_factory(),
            capability_token,
            accepts_requests,
            request_shutdown,
        ),
        report_fault,
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
        timeout_graceful_shutdown=None,
        workers=1,
        ws="none",
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
    if fatal_error:
        raise fatal_error[0]
    return 0
