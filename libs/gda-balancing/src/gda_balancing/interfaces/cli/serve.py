"""Descriptor and composition binding for the local HTTP service."""

import ipaddress
from collections.abc import Callable
from typing import Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gda_balancing.infrastructure.distribution import distribution_version
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.interfaces.http.api_v1 import PROTOCOL_VERSION, create_api_v1
from gda_balancing.interfaces.http.local_host import LocalHostReadiness, run_local_host


class ServeInput(BaseModel):
    """Loopback binding selected by the owning local client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)

    @field_validator("host")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError("host must be a numeric loopback address") from error
        if not address.is_loopback:
            raise ValueError("host must be a loopback address")
        return value


class ServeReadiness(BaseModel):
    """The single stdout result emitted after the local host accepts requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"] = "ready"
    protocol: Literal["v1"] = PROTOCOL_VERSION
    toolkit_version: str
    host: str
    port: int = Field(ge=1, le=65535)
    base_url: str
    capability_token: str = Field(min_length=43)


ReadyEmitter = Callable[[BaseModel], None]


def run_serve(inp: ServeInput, emit_ready: ReadyEmitter, _stderr: TextIO) -> int:
    """Assemble and run the one local companion host."""

    def report_ready(bound: LocalHostReadiness) -> None:
        url_host = (
            f"[{bound.host}]"
            if ipaddress.ip_address(bound.host).version == 6
            else bound.host
        )
        emit_ready(
            ServeReadiness(
                toolkit_version=distribution_version("gda-balancing"),
                host=bound.host,
                port=bound.port,
                base_url=f"http://{url_host}:{bound.port}",
                capability_token=bound.capability_token,
            )
        )

    return run_local_host(
        host=inp.host,
        port=inp.port,
        application_factory=create_api_v1,
        emit_ready=report_ready,
    )


SERVE = CommandDescriptor(
    group=None,
    command="serve",
    description="Run the loopback-only local HTTP execution service.",
    input_model=ServeInput,
    output_model=ServeReadiness,
    handler=None,
    foreground_runner=run_serve,
    execution_lifecycle="foreground-service",
    fixtures=ConformanceFixtures(
        foreground_readiness={
            "status": "ready",
            "protocol": "v1",
            "toolkit_version": "0.1.0",
            "host": "127.0.0.1",
            "port": 1,
            "base_url": "http://127.0.0.1:1",
            "capability_token": "x" * 43,
        }
    ),
    schema_major=2,
    structured_params=True,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
)
