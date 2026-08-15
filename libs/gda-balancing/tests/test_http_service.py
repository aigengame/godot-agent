"""Public end-to-end behavior of the local HTTP execution service."""

import json
import selectors
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


_ROGUELIKE_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "schema2" / "roguelike-reward-build"
)


def _console_script() -> str:
    script = shutil.which("gda-balancing")
    assert script is not None, "gda-balancing console script is not installed"
    return script


def _read_ready_line(process: subprocess.Popen[str]) -> dict[str, Any]:
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


@contextmanager
def _running_service() -> Iterator[tuple[subprocess.Popen[str], dict[str, Any]]]:
    process = subprocess.Popen(
        [_console_script(), "serve", "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        yield process, _read_ready_line(process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _request_json(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
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


def test_serve_reports_status_and_shuts_down() -> None:
    with _running_service() as (process, readiness):
        assert set(readiness) == {
            "base_url",
            "capability_token",
            "host",
            "port",
            "protocol",
            "status",
            "toolkit_version",
        }
        assert readiness["status"] == "ready"
        assert readiness["protocol"] == "v1"
        assert readiness["host"] == "127.0.0.1"
        assert readiness["port"] > 0
        assert readiness["base_url"] == (
            f"http://{readiness['host']}:{readiness['port']}"
        )
        assert len(readiness["capability_token"]) >= 43

        status = _request_json(
            f"{readiness['base_url']}/v1/status",
            readiness["capability_token"],
        )
        assert status == {
            "protocol": readiness["protocol"],
            "status": "ready",
            "toolkit_version": readiness["toolkit_version"],
        }

        shutdown = _request_json(
            f"{readiness['base_url']}/v1/shutdown",
            readiness["capability_token"],
            method="POST",
        )
        assert shutdown == {"status": "shutting-down"}
        assert process.wait(timeout=10) == 0
        assert process.stdout is not None
        assert process.stdout.read() == ""


def test_session_creation_admits_complete_model_and_experiment_values() -> None:
    model_source = json.loads(
        (_ROGUELIKE_EXAMPLE / "model-source.json").read_text(encoding="utf-8")
    )
    experiment = json.loads(
        (_ROGUELIKE_EXAMPLE / "experiment.json").read_text(encoding="utf-8")
    )

    with _running_service() as (_process, readiness):
        created = _request_json(
            f"{readiness['base_url']}/v1/execution-sessions",
            readiness["capability_token"],
            method="POST",
            body={
                "model_source": model_source,
                "experiment_specification": experiment,
            },
        )

        assert created["outcome"] == "success"
        assert created["session_id"]
        assert created["resolved_model_identity"] == (
            experiment["model"]["resolved_model_identity"]
        )
        assert created["revision_id"].startswith("sha256:")
