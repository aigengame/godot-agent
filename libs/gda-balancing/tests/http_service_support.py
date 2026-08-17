"""Concrete process and client support for Execution HTTP tests."""

from __future__ import annotations

import json
import selectors
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def console_script() -> str:
    """Return the installed console script used by public-boundary tests."""
    script = shutil.which("gda-balancing")
    assert script is not None, "gda-balancing console script is not installed"
    return script


def request_json(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one authenticated raw request and require a JSON success."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if method == "POST" and data is None:
        data = b""
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    with urlopen(request, timeout=10) as response:
        assert response.status == 200
        return json.load(response)


def request_error(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Send one authenticated raw request and require a closed JSON error."""
    try:
        request_json(url, token, method=method, body=body)
    except HTTPError as error:
        return error.code, json.load(error)
    raise AssertionError("request unexpectedly succeeded")


def _read_readiness(process: subprocess.Popen[str]) -> dict[str, Any]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        assert selector.select(timeout=20), "serve did not emit readiness"
        line = process.stdout.readline()
    finally:
        selector.close()
    assert line, "serve exited before readiness"
    return json.loads(line)


@dataclass(frozen=True)
class ExecutionHttpTestService:
    """A running local service with semantic actions and raw transport access."""

    process: subprocess.Popen[str]
    readiness: dict[str, Any]

    @property
    def base_url(self) -> str:
        return str(self.readiness["base_url"])

    @property
    def capability_token(self) -> str:
        return str(self.readiness["capability_token"])

    @property
    def host(self) -> str:
        return str(self.readiness["host"])

    @property
    def port(self) -> int:
        return int(self.readiness["port"])

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Use the authenticated raw transport escape path."""
        return request_json(
            self.url(path),
            self.capability_token,
            method=method,
            body=body,
        )

    def request_error(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Use the authenticated raw transport error path."""
        return request_error(
            self.url(path),
            self.capability_token,
            method=method,
            body=body,
        )

    def status(self) -> dict[str, Any]:
        return self.request("/v1/status")

    def create_session(
        self,
        model_source: dict[str, Any],
        experiment_specification: dict[str, Any],
    ) -> dict[str, Any]:
        return self.request(
            "/v1/execution-sessions",
            method="POST",
            body={
                "model_source": model_source,
                "experiment_specification": experiment_specification,
            },
        )

    def admit_revision(
        self,
        session_id: str,
        experiment_specification: dict[str, Any],
    ) -> dict[str, Any]:
        return self.request(
            f"/v1/execution-sessions/{session_id}/experiment-revisions",
            method="POST",
            body={"experiment_specification": experiment_specification},
        )

    def run(self, session_id: str, revision_id: str) -> dict[str, Any]:
        return self.request(
            f"/v1/execution-sessions/{session_id}/runs",
            method="POST",
            body={"revision_id": revision_id},
        )

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self.request(
            f"/v1/execution-sessions/{session_id}",
            method="DELETE",
        )

    def shutdown(self) -> dict[str, Any]:
        return self.request("/v1/shutdown", method="POST")


@contextmanager
def running_execution_http_service(
    *,
    command_prefix: list[str] | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Iterator[ExecutionHttpTestService]:
    """Start one real service and guarantee process cleanup."""
    process = subprocess.Popen(
        [
            *(command_prefix or [console_script()]),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=cwd,
        env=env,
    )
    try:
        yield ExecutionHttpTestService(
            process=process,
            readiness=_read_readiness(process),
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
