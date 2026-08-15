"""Public end-to-end behavior of the local HTTP execution service."""

import json
import selectors
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
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


def _request_error(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        _request_json(url, token, method=method, body=body)
    except HTTPError as error:
        return error.code, json.load(error)
    raise AssertionError("request unexpectedly succeeded")


def _roguelike_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads(
            (_ROGUELIKE_EXAMPLE / "model-source.json").read_text(encoding="utf-8")
        ),
        json.loads(
            (_ROGUELIKE_EXAMPLE / "experiment.json").read_text(encoding="utf-8")
        ),
    )


def _create_session(
    readiness: dict[str, Any],
    model_source: dict[str, Any],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    return _request_json(
        f"{readiness['base_url']}/v1/execution-sessions",
        readiness["capability_token"],
        method="POST",
        body={
            "model_source": model_source,
            "experiment_specification": experiment,
        },
    )


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
    model_source, experiment = _roguelike_documents()

    with _running_service() as (_process, readiness):
        created = _create_session(readiness, model_source, experiment)

        assert created["outcome"] == "success"
        assert created["session_id"]
        assert created["resolved_model_identity"] == (
            experiment["model"]["resolved_model_identity"]
        )
        assert created["revision_id"].startswith("sha256:")


def test_identical_experiment_revision_admission_is_idempotent() -> None:
    model_source, experiment = _roguelike_documents()

    with _running_service() as (_process, readiness):
        created = _create_session(readiness, model_source, experiment)
        admitted = _request_json(
            (
                f"{readiness['base_url']}/v1/execution-sessions/"
                f"{created['session_id']}/experiment-revisions"
            ),
            readiness["capability_token"],
            method="POST",
            body={"experiment_specification": experiment},
        )

        assert admitted == {
            "created": False,
            "outcome": "success",
            "revision_id": created["revision_id"],
        }


def test_run_returns_the_complete_existing_artifact_set_inline() -> None:
    model_source, experiment = _roguelike_documents()

    with _running_service() as (_process, readiness):
        created = _create_session(readiness, model_source, experiment)
        run = _request_json(
            (
                f"{readiness['base_url']}/v1/execution-sessions/"
                f"{created['session_id']}/runs"
            ),
            readiness["capability_token"],
            method="POST",
            body={"revision_id": created["revision_id"]},
        )

        assert run["outcome"] == "success"
        assert set(run["artifacts"]) == {
            "evaluation-run",
            "evaluator-capability-manifest",
            "event-trace",
            "metric-dataset",
            "reproduction-receipt",
            "resolved-runtime-profile",
            "snapshot-series",
        }
        assert all(
            artifact["content_identity"].startswith("sha256:")
            for artifact in run["artifacts"].values()
        )


def test_deleting_a_session_makes_it_an_unknown_service_resource() -> None:
    model_source, experiment = _roguelike_documents()

    with _running_service() as (_process, readiness):
        created = _create_session(readiness, model_source, experiment)
        session_url = (
            f"{readiness['base_url']}/v1/execution-sessions/"
            f"{created['session_id']}"
        )

        deleted = _request_json(
            session_url,
            readiness["capability_token"],
            method="DELETE",
        )
        status, error = _request_error(
            f"{session_url}/runs",
            readiness["capability_token"],
            method="POST",
            body={"revision_id": created["revision_id"]},
        )

        assert deleted == {
            "outcome": "success",
            "session_id": created["session_id"],
        }
        assert status == 404
        assert error == {
            "error": {
                "category": "service",
                "code": "unknown_execution_session",
                "message": "the Execution session does not exist",
            }
        }


def test_revision_refusal_leaves_existing_revisions_runnable() -> None:
    model_source, experiment = _roguelike_documents()
    invalid_revision = deepcopy(experiment)
    invalid_revision["kernel_identity"] = "sha256:not-the-admitted-kernel"

    with _running_service() as (_process, readiness):
        created = _create_session(readiness, model_source, experiment)
        session_url = (
            f"{readiness['base_url']}/v1/execution-sessions/"
            f"{created['session_id']}"
        )

        refused = _request_json(
            f"{session_url}/experiment-revisions",
            readiness["capability_token"],
            method="POST",
            body={"experiment_specification": invalid_revision},
        )
        rerun = _request_json(
            f"{session_url}/runs",
            readiness["capability_token"],
            method="POST",
            body={"revision_id": created["revision_id"]},
        )

        assert refused["outcome"] == "refusal"
        assert refused["refusal"]["diagnostics"][0]["code"] == (
            "language.resolved_authority_mismatch"
        )
        assert rerun["outcome"] == "success"


def test_each_run_explicitly_selects_one_immutable_revision() -> None:
    model_source, experiment = _roguelike_documents()
    later_experiment = deepcopy(experiment)
    later_experiment["seed"]["value"] += 1

    with _running_service() as (_process, readiness):
        created = _create_session(readiness, model_source, experiment)
        session_url = (
            f"{readiness['base_url']}/v1/execution-sessions/"
            f"{created['session_id']}"
        )
        later_revision = _request_json(
            f"{session_url}/experiment-revisions",
            readiness["capability_token"],
            method="POST",
            body={"experiment_specification": later_experiment},
        )

        first_run = _request_json(
            f"{session_url}/runs",
            readiness["capability_token"],
            method="POST",
            body={"revision_id": created["revision_id"]},
        )
        later_run = _request_json(
            f"{session_url}/runs",
            readiness["capability_token"],
            method="POST",
            body={"revision_id": later_revision["revision_id"]},
        )

        assert later_revision["created"] is True
        assert later_revision["revision_id"] != created["revision_id"]
        assert first_run["artifacts"]["reproduction-receipt"][
            "experiment_identity"
        ] == created["revision_id"]
        assert later_run["artifacts"]["reproduction-receipt"][
            "experiment_identity"
        ] == later_revision["revision_id"]


def test_closed_request_schema_rejects_unknown_members_before_application() -> None:
    model_source, experiment = _roguelike_documents()

    with _running_service() as (_process, readiness):
        status, error = _request_error(
            f"{readiness['base_url']}/v1/execution-sessions",
            readiness["capability_token"],
            method="POST",
            body={
                "model_source": model_source,
                "experiment_specification": experiment,
                "implicit_active_revision": True,
            },
        )

        assert status == 400
        assert error == {
            "error": {
                "category": "service",
                "code": "invalid_request",
                "message": "the request does not match the closed HTTP schema",
            }
        }


def test_request_body_limit_rejects_input_before_schema_parsing() -> None:
    with _running_service() as (_process, readiness):
        status, error = _request_error(
            f"{readiness['base_url']}/v1/execution-sessions/unknown/runs",
            readiness["capability_token"],
            method="POST",
            body={"revision_id": "x" * 65_536},
        )

        assert status == 413
        assert error == {
            "error": {
                "category": "service",
                "code": "request_too_large",
                "message": "the request body exceeds the HTTP protocol limit",
            }
        }
