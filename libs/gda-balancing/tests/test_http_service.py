"""Public end-to-end behavior of the local HTTP execution service."""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from copy import deepcopy
from pathlib import Path
from queue import Queue
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError
from starlette.types import Receive, Scope, Send

from gda_balancing.application.execution_sessions import (
    ExecutionSessionCreated,
    ExecutionSessions,
    ExperimentRevisionAdmitted,
)
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.domain.runtime.projections import evaluator_build_identity
from gda_balancing.interfaces.execution_service_language import (
    EXECUTION_SERVICE_LANGUAGE_REVISION,
    AdmitExperimentRevisionRequest,
    CreateExecutionSessionRequest,
    ExecutionServiceErrorCode,
    ExecutionSessionCreatedResponse,
    ExecutionSessionDeletedResponse,
    ExperimentRevisionAdmittedResponse,
    RefusalResponse,
    RunExperimentRequest,
    RunRefusalResponse,
    RunSuccessResponse,
    RunVerdictResponse,
    execution_service_error,
)
from gda_balancing.interfaces.http.api_v1 import create_api_v1
from gda_balancing.interfaces.http.local_host import (
    LocalHostReadiness,
    run_local_host,
)
from http_service_support import (
    ExecutionHttpTestService,
    console_script,
    request_error,
    request_json,
    running_execution_http_service,
)
from rpg_combat_test_support import one_action_experiment


_PACKAGE_ROOT = Path(__file__).parents[1]
_ROGUELIKE_EXAMPLE = _PACKAGE_ROOT / "examples" / "schema2" / "roguelike-reward-build"
_RPG_COMBAT_EXAMPLE = _PACKAGE_ROOT / "examples" / "schema2" / "rpg-combat-cast"


def _run_console(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [console_script(), *arguments],
        capture_output=True,
        text=True,
    )


def _roguelike_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads(
            (_ROGUELIKE_EXAMPLE / "model-source.json").read_text(encoding="utf-8")
        ),
        json.loads(
            (_ROGUELIKE_EXAMPLE / "experiment.json").read_text(encoding="utf-8")
        ),
    )


def _rpg_combat_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads(
            (_RPG_COMBAT_EXAMPLE / "model-source.json").read_text(encoding="utf-8")
        ),
        json.loads(
            (_RPG_COMBAT_EXAMPLE / "experiment.json").read_text(encoding="utf-8")
        ),
    )


def _example_refusal() -> Schema2RefusalReport:
    return Schema2RefusalReport(
        stage="ingress",
        diagnostics=(
            Schema2Diagnostic(
                code="language.invalid_source",
                message="the source is invalid",
                primary=ArtifactLocation(
                    content_identity="sha256:source",
                    pointer="/",
                ),
            ),
        ),
        truncated=False,
    )


def test_execution_service_language_establish_session_contract_is_closed() -> None:
    payload = {
        "model_source": {"schema_version": "2.0.0"},
        "experiment_specification": {"schema_version": "2.0.0"},
    }

    request = CreateExecutionSessionRequest.model_validate(payload)
    response = ExecutionSessionCreatedResponse(
        session_id="session-1",
        resolved_model_identity="sha256:resolved-model",
        revision_id="sha256:experiment",
    )

    assert EXECUTION_SERVICE_LANGUAGE_REVISION == 1
    assert request.model_dump(mode="json") == payload
    assert response.model_dump(mode="json") == {
        "outcome": "success",
        "session_id": "session-1",
        "resolved_model_identity": "sha256:resolved-model",
        "revision_id": "sha256:experiment",
    }
    with pytest.raises(ValidationError):
        CreateExecutionSessionRequest.model_validate(
            {**payload, "implicit_active_revision": True}
        )


def test_execution_service_language_admit_revision_contract_is_closed() -> None:
    payload = {"experiment_specification": {"schema_version": "2.0.0"}}

    request = AdmitExperimentRevisionRequest.model_validate(payload)
    response = ExperimentRevisionAdmittedResponse(
        revision_id="sha256:experiment",
        created=True,
    )

    assert request.model_dump(mode="json") == payload
    assert response.model_dump(mode="json") == {
        "outcome": "success",
        "revision_id": "sha256:experiment",
        "created": True,
    }
    with pytest.raises(ValidationError):
        AdmitExperimentRevisionRequest.model_validate(
            {**payload, "replace_active_revision": True}
        )


def test_execution_service_language_run_success_contract_is_closed() -> None:
    payload = {"revision_id": "sha256:experiment"}
    artifacts = {"evaluation-run": {"artifact_kind": "evaluation-run"}}

    request = RunExperimentRequest.model_validate(payload)
    response = RunSuccessResponse(artifacts=artifacts)

    assert request.model_dump(mode="json") == payload
    assert response.model_dump(mode="json") == {
        "outcome": "success",
        "artifacts": artifacts,
    }
    with pytest.raises(ValidationError):
        RunExperimentRequest.model_validate({**payload, "latest": True})


def test_execution_service_language_reuses_the_domain_refusal_contract() -> None:
    refusal = _example_refusal()

    response = RefusalResponse(refusal=refusal)
    mutated = response.model_dump(mode="json")
    mutated["refusal"]["transport_extension"] = True

    assert response.refusal is refusal
    assert "Schema2RefusalReport" in RefusalResponse.model_json_schema()["$defs"]
    with pytest.raises(ValidationError):
        RefusalResponse.model_validate(mutated)


def test_execution_service_language_run_outcomes_share_one_artifact_shape() -> None:
    artifacts = {"evaluation-run": {"artifact_kind": "evaluation-run"}}
    refusal = _example_refusal()

    verdict = RunVerdictResponse(
        failed_metrics=["damage-per-turn"],
        artifacts=artifacts,
    )
    refused = RunRefusalResponse(refusal=refusal, artifacts=artifacts)

    assert verdict.model_dump(mode="json") == {
        "outcome": "verdict",
        "failed_metrics": ["damage-per-turn"],
        "artifacts": artifacts,
    }
    assert refused.model_dump(mode="json") == {
        "outcome": "refusal",
        "refusal": refusal.model_dump(mode="json"),
        "artifacts": artifacts,
    }
    assert refused.refusal is refusal


def test_execution_service_language_release_session_contract_is_closed() -> None:
    response = ExecutionSessionDeletedResponse(session_id="session-1")

    assert response.model_dump(mode="json") == {
        "outcome": "success",
        "session_id": "session-1",
    }
    with pytest.raises(ValidationError):
        ExecutionSessionDeletedResponse.model_validate(
            {
                "outcome": "success",
                "session_id": "session-1",
                "remaining_revisions": 0,
            }
        )


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            "unknown_execution_session",
            "the Execution session does not exist",
        ),
        (
            "unknown_experiment_revision",
            "the Experiment revision does not exist",
        ),
    ],
)
def test_execution_service_language_owns_shared_selection_errors(
    code: ExecutionServiceErrorCode,
    message: str,
) -> None:
    error = execution_service_error(code)

    assert error.model_dump(mode="json") == {
        "error": {
            "category": "service",
            "code": code,
            "message": message,
        }
    }


@pytest.fixture(scope="module")
def shared_execution_http_service() -> Iterator[ExecutionHttpTestService]:
    """Keep one real process for tests that exercise only session semantics."""
    with running_execution_http_service() as service:
        yield service


def test_serve_reports_status_and_shuts_down() -> None:
    with running_execution_http_service() as service:
        readiness = service.readiness
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

        status = service.status()
        assert status == {
            "protocol": readiness["protocol"],
            "status": "ready",
            "toolkit_version": readiness["toolkit_version"],
        }

        shutdown = service.shutdown()
        assert shutdown == {"status": "shutting-down"}
        assert service.process.wait(timeout=10) == 0
        assert service.process.stdout is not None
        assert service.process.stdout.read() == ""


def test_session_creation_admits_complete_model_and_experiment_values(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)

    assert created["outcome"] == "success"
    assert created["session_id"]
    assert (
        created["resolved_model_identity"]
        == (experiment["model"]["resolved_model_identity"])
    )
    assert created["revision_id"].startswith("sha256:")


def test_identical_experiment_revision_admission_is_idempotent(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    admitted = service.admit_revision(
        created["session_id"],
        experiment,
    )

    assert admitted == {
        "created": False,
        "outcome": "success",
        "revision_id": created["revision_id"],
    }


def test_run_returns_the_complete_existing_artifact_set_inline(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    run = service.run(created["session_id"], created["revision_id"])

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


def test_deleting_a_session_makes_it_an_unknown_service_resource(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)

    deleted = service.delete_session(created["session_id"])
    status, error = service.request_error(
        f"/v1/execution-sessions/{created['session_id']}/runs",
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


def test_revision_refusal_leaves_existing_revisions_runnable(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    invalid_revision = deepcopy(experiment)
    invalid_revision["kernel_identity"] = "sha256:not-the-admitted-kernel"
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)

    refused = service.admit_revision(created["session_id"], invalid_revision)
    rerun = service.run(
        created["session_id"],
        created["revision_id"],
    )

    assert refused["outcome"] == "refusal"
    assert refused["refusal"]["diagnostics"][0]["code"] == (
        "language.resolved_authority_mismatch"
    )
    assert rerun["outcome"] == "success"


def test_each_run_explicitly_selects_one_immutable_revision(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    later_experiment = deepcopy(experiment)
    later_experiment["seed"]["value"] += 1
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    later_revision = service.admit_revision(
        created["session_id"],
        later_experiment,
    )

    first_run = service.run(created["session_id"], created["revision_id"])
    later_run = service.run(
        created["session_id"],
        later_revision["revision_id"],
    )

    assert later_revision["created"] is True
    assert later_revision["revision_id"] != created["revision_id"]
    assert (
        first_run["artifacts"]["reproduction-receipt"]["experiment_identity"]
        == created["revision_id"]
    )
    assert (
        later_run["artifacts"]["reproduction-receipt"]["experiment_identity"]
        == later_revision["revision_id"]
    )


def test_reciprocal_combat_service_stops_on_defeat_and_links_ineligibility() -> None:
    model_source, baseline = _rpg_combat_documents()
    state = {
        row["target"]["name"]: row["value"]
        for row in baseline["scenarios"][0]["assignments"]
    }
    action_outcomes = []
    actions = ("player-attacks-enemy", "enemy-attacks-player")

    with running_execution_http_service() as service:
        created = service.create_session(model_source, baseline)

        for index in range(1, 7):
            root_event_ref = actions[(index - 1) % 2]
            revision = one_action_experiment(
                baseline,
                f"example.rpg-combat-cast.service-action-{index}",
                root_event_ref=root_event_ref,
                include_damage_metric=False,
            )
            for assignment in revision["scenarios"][0]["assignments"]:
                assignment["value"] = state[assignment["target"]["name"]]
            admitted = service.admit_revision(created["session_id"], revision)
            assert admitted["outcome"] == "success", admitted
            run = service.run(created["session_id"], admitted["revision_id"])
            assert run["outcome"] == "success", run
            transition = next(
                event
                for event in run["artifacts"]["event-trace"]["events"]
                if event["operation"] is not None
            )
            action_outcomes.append(transition["outcome"]["id"])
            state.update(
                {row["name"]: row["value"] for row in transition["state_after"]}
            )
            if transition["outcome"]["id"] == "target-defeated":
                break

        assert action_outcomes == [
            "cast-resolved",
            "cast-resolved",
            "cast-resolved",
            "cast-resolved",
            "target-defeated",
        ]
        assert state["enemy_health"] == 0

        # This is a boundary probe, not another action in the stopped duel loop.
        ineligible_revision = one_action_experiment(
            baseline,
            "example.rpg-combat-cast.service-ineligible-probe",
            root_event_ref="enemy-attacks-player",
            include_damage_metric=False,
        )
        for assignment in ineligible_revision["scenarios"][0]["assignments"]:
            assignment["value"] = state[assignment["target"]["name"]]
        admitted = service.admit_revision(
            created["session_id"],
            ineligible_revision,
        )
        assert admitted["outcome"] == "success", admitted
        run = service.run(created["session_id"], admitted["revision_id"])
        assert run["outcome"] == "success", run
        ineligible = next(
            event
            for event in run["artifacts"]["event-trace"]["events"]
            if event["operation"] is not None
        )

    assert ineligible["outcome"] == {
        "id": "actor-ineligible",
        "kind": "gameplay-alternative",
    }
    assert ineligible["state_after"] == ineligible["state_before"]
    assert ineligible["rng_draws"] == []
    assert "enemy_damage_dealt" not in {row["name"] for row in ineligible["facts"]}
    assert {row["name"]: row["value"] for row in ineligible["state_after"]}[
        "enemy_mana"
    ] == state["enemy_mana"]


def test_admitted_revisions_detach_from_caller_owned_values() -> None:
    model_source, experiment = _roguelike_documents()
    baseline_seed = experiment["seed"]["value"]
    sessions = ExecutionSessions()

    created = sessions.create(model_source, experiment)
    assert isinstance(created, ExecutionSessionCreated)
    model_source.clear()
    experiment["seed"]["value"] = baseline_seed + 100

    initial_run = sessions.run(created.session_id, created.revision_id)
    initial_receipt = initial_run.members["reproduction-receipt"].value
    assert initial_receipt["seed_value"] == baseline_seed

    later_experiment = deepcopy(experiment)
    later_experiment["seed"]["value"] = baseline_seed + 1
    admitted = sessions.admit_revision(created.session_id, later_experiment)
    assert isinstance(admitted, ExperimentRevisionAdmitted)
    later_experiment["seed"]["value"] = baseline_seed + 200

    later_run = sessions.run(created.session_id, admitted.revision_id)
    later_receipt = later_run.members["reproduction-receipt"].value
    assert later_receipt["seed_value"] == baseline_seed + 1


def test_closed_request_schema_rejects_unknown_members_before_application() -> None:
    model_source, experiment = _roguelike_documents()

    with running_execution_http_service() as service:
        status, error = service.request_error(
            "/v1/execution-sessions",
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


def test_routes_without_request_models_reject_bodies_before_side_effects() -> None:
    model_source, experiment = _roguelike_documents()

    with running_execution_http_service() as service:
        status_code, status_error = service.request_error(
            "/v1/status",
            body={"unexpected": True},
        )
        created = service.create_session(model_source, experiment)
        session_path = f"/v1/execution-sessions/{created['session_id']}"
        delete_code, delete_error = service.request_error(
            session_path,
            method="DELETE",
            body={"unexpected": True},
        )
        rerun = service.run(
            created["session_id"],
            created["revision_id"],
        )
        shutdown_code, shutdown_error = service.request_error(
            "/v1/shutdown",
            method="POST",
            body={"unexpected": True},
        )

        assert status_code == delete_code == shutdown_code == 400
        assert (
            status_error
            == delete_error
            == shutdown_error
            == {
                "error": {
                    "category": "service",
                    "code": "invalid_request",
                    "message": "the request does not match the closed HTTP schema",
                }
            }
        )
        assert rerun["outcome"] == "success"
        assert service.process.poll() is None


def test_declared_routes_reject_undeclared_query_input() -> None:
    with running_execution_http_service() as service:
        status_code, status_error = service.request_error(
            "/v1/status?unknown=true",
        )
        run_code, run_error = service.request_error(
            "/v1/execution-sessions/unknown/runs?unknown=true",
            method="POST",
            body={"revision_id": "unknown"},
        )
        shutdown_code, shutdown_error = service.request_error(
            "/v1/shutdown?unknown=true",
            method="POST",
        )

        assert status_code == run_code == shutdown_code == 400
        assert (
            status_error
            == run_error
            == shutdown_error
            == {
                "error": {
                    "category": "service",
                    "code": "invalid_request",
                    "message": "the request does not match the closed HTTP schema",
                }
            }
        )
        assert service.process.poll() is None


def test_unknown_routes_methods_and_trailing_slashes_use_closed_errors() -> None:
    with running_execution_http_service() as service:
        unknown_status, unknown_error = service.request_error(
            "/v1/unknown",
        )
        trailing_status, trailing_error = service.request_error(
            "/v1/status/",
        )
        request = Request(
            service.url("/v1/status"),
            data=b"",
            method="POST",
            headers={
                "Authorization": f"Bearer {service.capability_token}",
            },
        )
        with pytest.raises(HTTPError) as response:
            urlopen(request, timeout=10)
        method_error = json.load(response.value)
        shutdown_request = Request(
            service.url("/v1/shutdown"),
            method="GET",
            headers={
                "Authorization": f"Bearer {service.capability_token}",
            },
        )
        with pytest.raises(HTTPError) as shutdown_response:
            urlopen(shutdown_request, timeout=10)
        shutdown_method_error = json.load(shutdown_response.value)
        head_request = Request(
            service.url("/v1/status"),
            method="HEAD",
            headers={
                "Authorization": f"Bearer {service.capability_token}",
            },
        )
        with pytest.raises(HTTPError) as head_response:
            urlopen(head_request, timeout=10)

        assert unknown_status == trailing_status == 404
        assert (
            unknown_error
            == trailing_error
            == {
                "error": {
                    "category": "service",
                    "code": "unknown_endpoint",
                    "message": "the HTTP endpoint does not exist",
                }
            }
        )
        assert response.value.code == 405
        assert response.value.headers["Allow"] in {"GET", "GET, HEAD", "HEAD, GET"}
        assert method_error == {
            "error": {
                "category": "service",
                "code": "method_not_allowed",
                "message": "the HTTP method is not allowed for this endpoint",
            }
        }
        assert shutdown_response.value.code == 405
        assert shutdown_response.value.headers["Allow"] == "POST"
        assert shutdown_method_error == method_error
        assert head_response.value.code == 405
        assert head_response.value.headers["Allow"] == "GET"
        assert head_response.value.headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    "body",
    [
        b'{"model_source":{},"model_source":{},"experiment_specification":{}}',
        b'{"model_source":{"schema_version":"2.0.0","schema_version":"2.1.0"},'
        b'"experiment_specification":{}}',
    ],
    ids=["root", "nested"],
)
def test_request_json_rejects_duplicate_object_members(body: bytes) -> None:
    with running_execution_http_service() as service:
        connection = HTTPConnection(service.host, service.port, timeout=10)
        try:
            connection.request(
                "POST",
                "/v1/execution-sessions",
                body=body,
                headers={
                    "Authorization": f"Bearer {service.capability_token}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            error = json.load(response)
        finally:
            connection.close()

        assert response.status == 400
        assert error == {
            "error": {
                "category": "service",
                "code": "invalid_request",
                "message": "the request does not match the closed HTTP schema",
            }
        }


def test_shutdown_closes_request_admission_before_acknowledgement() -> None:
    with running_execution_http_service() as service:
        connection = HTTPConnection(service.host, service.port, timeout=10)
        headers = {
            "Authorization": f"Bearer {service.capability_token}",
        }
        try:
            connection.request("POST", "/v1/shutdown", body=b"", headers=headers)
            shutdown_response = connection.getresponse()
            shutdown = json.load(shutdown_response)
            connection.request("GET", "/v1/status", headers=headers)
            status_response = connection.getresponse()
            error = json.load(status_response)
        finally:
            connection.close()

        assert shutdown_response.status == 200
        assert shutdown == {"status": "shutting-down"}
        assert status_response.status == 503
        assert error == {
            "error": {
                "category": "service",
                "code": "service_shutting_down",
                "message": "the local service is shutting down",
            }
        }
        assert service.process.wait(timeout=10) == 0


def test_request_body_limit_rejects_input_before_schema_parsing() -> None:
    with running_execution_http_service() as service:
        status, error = service.request_error(
            "/v1/execution-sessions/unknown/runs",
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


def test_session_body_limit_rejects_declared_size_before_reading() -> None:
    with running_execution_http_service() as service:
        connection = HTTPConnection(service.host, service.port, timeout=10)
        try:
            connection.putrequest("POST", "/v1/execution-sessions")
            connection.putheader("Authorization", f"Bearer {service.capability_token}")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(2**40))
            connection.endheaders()
            response = connection.getresponse()
            error = json.load(response)
        finally:
            connection.close()

        assert response.status == 413
        assert error["error"]["code"] == "request_too_large"


def test_process_capability_protects_execution_and_shutdown_routes() -> None:
    with running_execution_http_service() as service:
        status_code, status_error = request_error(
            service.url("/v1/status"),
            "wrong-capability",
        )
        shutdown_code, shutdown_error = request_error(
            service.url("/v1/shutdown"),
            "wrong-capability",
            method="POST",
        )

        assert status_code == 401
        assert shutdown_code == 401
        assert status_error["error"]["code"] == "authentication_required"
        assert shutdown_error == status_error
        assert service.process.poll() is None
        assert service.status()["status"] == "ready"


def test_execution_routes_require_json_media_type() -> None:
    with running_execution_http_service() as service:
        request = Request(
            service.url("/v1/execution-sessions"),
            data=b"{}",
            method="POST",
            headers={
                "Authorization": f"Bearer {service.capability_token}",
                "Content-Type": "text/plain",
            },
        )
        try:
            urlopen(request, timeout=10)
        except HTTPError as error:
            status = error.code
            body = json.load(error)
        else:
            raise AssertionError("non-JSON request unexpectedly succeeded")

        assert status == 415
        assert body["error"] == {
            "category": "service",
            "code": "unsupported_media_type",
            "message": "the request content type must be application/json",
        }


def test_cli_publication_and_http_inline_execution_are_semantically_identical(
    tmp_path: Path,
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    model_out = tmp_path / "resolved-model.json"
    run_out = tmp_path / "evaluation-run.json"
    built = _run_console(
        "model",
        "build",
        str(_ROGUELIKE_EXAMPLE / "model-source.json"),
        "--out",
        str(model_out),
        "--invocation-key",
        "a" * 64,
    )
    assert (built.returncode, built.stderr) == (0, ""), built.stdout
    cli_run = _run_console(
        "experiment",
        "run",
        str(_ROGUELIKE_EXAMPLE / "experiment.json"),
        "--out",
        str(run_out),
        "--invocation-key",
        "b" * 64,
    )
    assert (cli_run.returncode, cli_run.stderr) == (0, ""), cli_run.stdout
    cli_receipt = json.loads(cli_run.stdout)
    cli_artifacts = {
        row["logical_name"]: json.loads(
            Path(row["locator"]).read_text(encoding="utf-8")
        )
        for row in cli_receipt["member_locators"]
    }

    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    http_run = service.run(created["session_id"], created["revision_id"])

    assert http_run["outcome"] == "success"
    assert http_run["artifacts"] == cli_artifacts
    assert "artifact-set-receipt" not in {
        artifact["artifact_kind"] for artifact in http_run["artifacts"].values()
    }


def test_aggregate_http_limit_preserves_the_model_source_ingress_refusal(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    max_source_bytes = packaged_authority_context().language_bundle["resources"][
        "max_source_bytes"
    ]
    model_source["oversized_padding"] = "x" * max_source_bytes

    refused = shared_execution_http_service.create_session(model_source, experiment)

    assert refused["outcome"] == "refusal"
    assert refused["refusal"]["stage"] == "ingress"
    assert refused["refusal"]["diagnostics"][0]["code"] == ("language.source_too_large")


def test_sessions_do_not_share_revision_state(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    later_experiment = deepcopy(experiment)
    later_experiment["seed"]["value"] += 1

    service = shared_execution_http_service
    first = service.create_session(model_source, experiment)
    second = service.create_session(model_source, experiment)
    first_revision = service.admit_revision(
        first["session_id"],
        later_experiment,
    )
    status, error = service.request_error(
        f"/v1/execution-sessions/{second['session_id']}/runs",
        method="POST",
        body={"revision_id": first_revision["revision_id"]},
    )

    assert first["session_id"] != second["session_id"]
    assert first["resolved_model_identity"] == second["resolved_model_identity"]
    assert status == 404
    assert error["error"]["code"] == "unknown_experiment_revision"


def test_restart_does_not_recover_process_local_sessions() -> None:
    model_source, experiment = _roguelike_documents()

    with running_execution_http_service() as first_service:
        created = first_service.create_session(model_source, experiment)
        first_service.shutdown()
        assert first_service.process.wait(timeout=10) == 0

    with running_execution_http_service() as second_service:
        status, error = second_service.request_error(
            f"/v1/execution-sessions/{created['session_id']}/runs",
            method="POST",
            body={"revision_id": created["revision_id"]},
        )

        assert status == 404
        assert error["error"]["code"] == "unknown_execution_session"


def test_disconnected_run_has_no_durable_result_and_can_be_rerun(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    connection = HTTPConnection(service.host, service.port, timeout=10)
    connection.request(
        "POST",
        f"/v1/execution-sessions/{created['session_id']}/runs",
        body=json.dumps({"revision_id": created["revision_id"]}),
        headers={
            "Authorization": f"Bearer {service.capability_token}",
            "Content-Type": "application/json",
        },
    )
    connection.close()

    rerun = service.run(created["session_id"], created["revision_id"])

    assert service.process.poll() is None
    assert rerun["outcome"] == "success"
    assert (
        rerun["artifacts"]["reproduction-receipt"]["experiment_identity"]
        == created["revision_id"]
    )


def test_disconnect_during_request_body_does_not_stop_the_service() -> None:
    with running_execution_http_service() as service:
        connection = socket.create_connection(
            (service.host, service.port),
            timeout=10,
        )
        try:
            request_head = (
                "POST /v1/execution-sessions HTTP/1.1\r\n"
                f"Host: {service.host}:{service.port}\r\n"
                f"Authorization: Bearer {service.capability_token}\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: 1024\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii")
            connection.sendall(request_head + b'{"model_source":')
        finally:
            connection.close()
        time.sleep(0.5)

        status = service.status()

        assert service.process.poll() is None
        assert status["status"] == "ready"


def test_graceful_shutdown_waits_for_an_admitted_run() -> None:
    model_source, experiment = _roguelike_documents()

    with running_execution_http_service() as service:
        created = service.create_session(model_source, experiment)
        with ThreadPoolExecutor(max_workers=1) as executor:
            run_future = executor.submit(
                service.run,
                created["session_id"],
                created["revision_id"],
            )
            time.sleep(0.2)
            shutdown = service.shutdown()
            run = run_future.result(timeout=20)

        assert shutdown == {"status": "shutting-down"}
        assert run["outcome"] == "success"
        assert (
            run["artifacts"]["evaluator-capability-manifest"][
                "evaluator_build_identity"
            ]
            == evaluator_build_identity()
        )
        assert service.process.wait(timeout=10) == 0
        assert service.process.stdout is not None
        assert service.process.stdout.read() == ""


def test_forced_process_termination_discards_all_session_state() -> None:
    model_source, experiment = _roguelike_documents()

    with running_execution_http_service() as first_service:
        created = first_service.create_session(model_source, experiment)
        first_service.process.kill()
        assert first_service.process.wait(timeout=10) != 0
        assert first_service.process.stdout is not None
        assert first_service.process.stdout.read() == ""

    with running_execution_http_service() as second_service:
        status, error = second_service.request_error(
            f"/v1/execution-sessions/{created['session_id']}/runs",
            method="POST",
            body={"revision_id": created["revision_id"]},
        )

        assert status == 404
        assert error["error"]["code"] == "unknown_execution_session"


def test_bind_failure_uses_the_descriptor_internal_error_contract() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = _run_console(
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        )
    finally:
        listener.close()

    assert result.returncode == 4
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["category"] == "internal"
    assert error["code"] == "internal_error"
    assert error["message"] == "the toolkit failed unexpectedly (OSError)"


def test_serve_refuses_a_non_loopback_binding_before_startup() -> None:
    result = _run_console(
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "0",
    )

    assert result.returncode == 3
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["category"] == "usage"
    assert error["code"] == "invalid_argument"


def test_post_readiness_application_fault_stops_the_local_host() -> None:
    readiness_queue: Queue[LocalHostReadiness] = Queue(maxsize=1)

    async def failing_application(
        _scope: Scope,
        _receive: Receive,
        _send: Send,
    ) -> None:
        raise RuntimeError("injected post-readiness fault")

    with ThreadPoolExecutor(max_workers=1) as executor:
        serving = executor.submit(
            run_local_host,
            host="127.0.0.1",
            port=0,
            application_factory=lambda: failing_application,
            emit_ready=readiness_queue.put,
        )
        readiness = readiness_queue.get(timeout=10)
        try:
            request = Request(
                f"http://{readiness.host}:{readiness.port}/v1/status",
                headers={
                    "Authorization": f"Bearer {readiness.capability_token}",
                },
            )
            with pytest.raises(HTTPError) as response:
                urlopen(request, timeout=10)
            assert response.value.code == 500
            assert json.load(response.value) == {
                "error": {
                    "category": "service",
                    "code": "internal_error",
                    "message": "the local service failed unexpectedly",
                }
            }

            with pytest.raises(
                RuntimeError,
                match="injected post-readiness fault",
            ):
                serving.result(timeout=10)
        finally:
            if not serving.done():
                request_json(
                    f"http://{readiness.host}:{readiness.port}/v1/shutdown",
                    readiness.capability_token,
                    method="POST",
                )


def test_post_readiness_production_route_fault_stops_the_local_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness_queue: Queue[LocalHostReadiness] = Queue(maxsize=1)

    def fail_session_creation(
        _sessions: ExecutionSessions,
        _model_source: dict[str, Any],
        _experiment_specification: dict[str, Any],
    ) -> None:
        raise RuntimeError("injected production route fault")

    monkeypatch.setattr(ExecutionSessions, "create", fail_session_creation)

    with ThreadPoolExecutor(max_workers=1) as executor:
        serving = executor.submit(
            run_local_host,
            host="127.0.0.1",
            port=0,
            application_factory=create_api_v1,
            emit_ready=readiness_queue.put,
        )
        readiness = readiness_queue.get(timeout=10)
        try:
            request = Request(
                f"http://{readiness.host}:{readiness.port}/v1/execution-sessions",
                data=json.dumps(
                    {
                        "model_source": {},
                        "experiment_specification": {},
                    }
                ).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {readiness.capability_token}",
                    "Content-Type": "application/json",
                },
            )
            with pytest.raises(HTTPError) as response:
                urlopen(request, timeout=10)
            assert response.value.code == 500
            assert json.load(response.value) == {
                "error": {
                    "category": "service",
                    "code": "internal_error",
                    "message": "the local service failed unexpectedly",
                }
            }

            with pytest.raises(
                RuntimeError,
                match="injected production route fault",
            ):
                serving.result(timeout=10)
        finally:
            if not serving.done():
                request_json(
                    f"http://{readiness.host}:{readiness.port}/v1/shutdown",
                    readiness.capability_token,
                    method="POST",
                )


def test_built_wheel_starts_the_service_and_executes_packaged_authority(
    tmp_path: Path,
) -> None:
    distribution_dir = tmp_path / "dist"
    built = subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(distribution_dir),
        ],
        capture_output=True,
        cwd=_PACKAGE_ROOT,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(distribution_dir.glob("gda_balancing-*.whl"))
    assert len(wheels) == 1
    wheel_environment = os.environ.copy()
    wheel_environment["PYTHONPATH"] = str(wheels[0])
    model_source, experiment = _roguelike_documents()

    with running_execution_http_service(
        command_prefix=[sys.executable, "-m", "gda_balancing"],
        cwd=tmp_path,
        env=wheel_environment,
    ) as service:
        created = service.create_session(model_source, experiment)
        run = service.run(created["session_id"], created["revision_id"])
        service.shutdown()

        assert run["outcome"] == "success"
        assert service.process.wait(timeout=10) == 0


def test_admitted_run_finishes_before_later_session_work_and_deletion(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    later_experiment = deepcopy(experiment)
    later_experiment["seed"]["value"] += 1

    service = shared_execution_http_service
    first = service.create_session(model_source, experiment)
    second = service.create_session(model_source, experiment)

    def timed_request(
        action: Callable[..., dict[str, Any]],
        *arguments: Any,
    ) -> tuple[dict[str, Any], float]:
        result = action(*arguments)
        return result, time.monotonic()

    with ThreadPoolExecutor(max_workers=3) as executor:
        run_future = executor.submit(
            timed_request,
            service.run,
            first["session_id"],
            first["revision_id"],
        )
        time.sleep(0.2)
        revision_future = executor.submit(
            timed_request,
            service.admit_revision,
            second["session_id"],
            later_experiment,
        )
        delete_future = executor.submit(
            timed_request,
            service.delete_session,
            first["session_id"],
        )
        run, run_finished = run_future.result(timeout=20)
        revision, revision_finished = revision_future.result(timeout=20)
        deleted, delete_finished = delete_future.result(timeout=20)

    assert run["outcome"] == "success"
    assert revision["outcome"] == "success"
    assert deleted["outcome"] == "success"
    assert run_finished <= revision_finished
    assert run_finished <= delete_finished


def test_metric_rejection_returns_a_complete_verdict_artifact_set(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    for metric in experiment["metrics"]:
        metric["target"] = {"minimum": 1000, "maximum": 1000}

    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    run = service.run(created["session_id"], created["revision_id"])

    assert run["outcome"] == "verdict"
    assert run["failed_metrics"] == ["reward_score", "build_score"]
    assert set(run["artifacts"]) == {
        "evaluator-capability-manifest",
        "event-trace",
        "experiment-verdict",
        "metric-dataset",
        "reproduction-receipt",
        "resolved-runtime-profile",
        "snapshot-series",
    }


def test_runtime_refusal_returns_existing_terminal_audit_artifacts(
    shared_execution_http_service: ExecutionHttpTestService,
) -> None:
    model_source, experiment = _roguelike_documents()
    reward_pool = next(
        assignment
        for assignment in experiment["scenarios"][0]["assignments"]
        if assignment["target"]["name"] == "reward_pool"
    )["value"]["value"]
    reward_pool["options"] = []
    reward_pool["no_reward_on_empty"] = []

    service = shared_execution_http_service
    created = service.create_session(model_source, experiment)
    run = service.run(created["session_id"], created["revision_id"])

    assert run["outcome"] == "refusal"
    assert run["refusal"]["stage"] == "runtime"
    assert run["refusal"]["variant"] == "post-dispatch"
    assert run["refusal"]["diagnostics"][0]["code"] == (
        "game.generation.selection_exhausted"
    )
    assert set(run["artifacts"]) == {
        "evaluator-capability-manifest",
        "reproduction-receipt",
        "resolved-runtime-profile",
        "runtime-terminal-audit",
    }
