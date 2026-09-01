"""Executable contract of Execution Service Language revision 1."""

import pytest
from pydantic import ValidationError

from gda_balancing.application.execution_sessions import (
    ExecutionSessionCreated,
    ExecutionSessionNotFound,
    ExperimentRevisionAdmitted,
    ExperimentRevisionNotFound,
)
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionRefusal,
    ExperimentExecutionSuccess,
    ExperimentExecutionVerdict,
)
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.domain.publication_types import PublicationMember
from gda_balancing.interfaces.execution_service_language import (
    EXECUTION_SERVICE_LANGUAGE_REVISION,
    AdmitExperimentRevisionRequest,
    EstablishExecutionSessionRequest,
    ExecutionServiceErrorCode,
    ExecutionSessionEstablishedResponse,
    ExecutionSessionReleasedResponse,
    ExperimentRevisionAdmittedResponse,
    RefusalResponse,
    ReleaseExecutionSessionRequest,
    RunExperimentRequest,
    RunRefusalResponse,
    RunSuccessResponse,
    RunVerdictResponse,
    admit_experiment_revision_response,
    establish_session_response,
    execution_service_error,
    execution_service_error_from_condition,
    run_experiment_revision_response,
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


def test_establish_session_contract_is_closed() -> None:
    payload = {
        "model_source": {"schema_version": "2.0.0"},
        "experiment_specification": {"schema_version": "2.0.0"},
    }

    request = EstablishExecutionSessionRequest.model_validate(payload)
    response = ExecutionSessionEstablishedResponse(
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
        EstablishExecutionSessionRequest.model_validate(
            {**payload, "implicit_active_revision": True}
        )


def test_establish_session_results_are_framed() -> None:
    created = ExecutionSessionCreated(
        session_id="session-1",
        resolved_model_identity="sha256:resolved-model",
        revision_id="sha256:experiment",
    )
    refusal = _example_refusal()

    success = establish_session_response(created)
    refused = establish_session_response(refusal)

    assert success == ExecutionSessionEstablishedResponse(
        session_id="session-1",
        resolved_model_identity="sha256:resolved-model",
        revision_id="sha256:experiment",
    )
    assert refused == RefusalResponse(refusal=refusal)


def test_admit_revision_contract_is_closed() -> None:
    payload = {
        "session_id": "session-1",
        "experiment_specification": {"schema_version": "2.0.0"},
    }

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


def test_revision_admission_results_are_framed() -> None:
    admitted = ExperimentRevisionAdmitted(
        revision_id="sha256:experiment",
        created=True,
    )
    refusal = _example_refusal()

    success = admit_experiment_revision_response(admitted)
    refused = admit_experiment_revision_response(refusal)

    assert success == ExperimentRevisionAdmittedResponse(
        revision_id="sha256:experiment",
        created=True,
    )
    assert refused == RefusalResponse(refusal=refusal)


def test_run_success_contract_is_closed() -> None:
    payload = {
        "session_id": "session-1",
        "revision_id": "sha256:experiment",
    }
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


def test_run_results_are_framed() -> None:
    artifact = {"artifact_kind": "evaluation-run", "events": [{"value": 7}]}
    member = PublicationMember(
        value=artifact,
        artifact_kind="evaluation-run",
        wire_schema_identity="sha256:wire-schema",
        content_identity="sha256:artifact",
    )
    refusal = _example_refusal()

    success = run_experiment_revision_response(
        ExperimentExecutionSuccess(members={"evaluation-run": member})
    )
    verdict = run_experiment_revision_response(
        ExperimentExecutionVerdict(
            failed_metrics=("damage-floor",),
            members={"evaluation-run": member},
        )
    )
    refused = run_experiment_revision_response(
        ExperimentExecutionRefusal(
            report=refusal,
            members={"evaluation-run": member},
        )
    )

    assert success == RunSuccessResponse(
        artifacts={"evaluation-run": artifact},
    )
    assert verdict == RunVerdictResponse(
        failed_metrics=["damage-floor"],
        artifacts={"evaluation-run": artifact},
    )
    assert refused == RunRefusalResponse(
        refusal=refusal,
        artifacts={"evaluation-run": artifact},
    )
    artifact["events"][0]["value"] = 99
    assert success.artifacts["evaluation-run"]["events"] == [{"value": 7}]


def test_domain_refusal_contract_is_reused() -> None:
    refusal = _example_refusal()

    response = RefusalResponse(refusal=refusal)
    mutated = response.model_dump(mode="json")
    mutated["refusal"]["transport_extension"] = True

    assert response.refusal is refusal
    assert "Schema2RefusalReport" in RefusalResponse.model_json_schema()["$defs"]
    with pytest.raises(ValidationError):
        RefusalResponse.model_validate(mutated)


def test_nested_standard_schema_values_remain_opaque_to_the_language() -> None:
    request = EstablishExecutionSessionRequest(
        model_source={"authority_owned_member": {"model": True}},
        experiment_specification={"authority_owned_member": {"experiment": True}},
    )
    response = RunSuccessResponse(
        artifacts={"result": {"authority_owned_member": {"artifact": True}}}
    )

    request_schema = EstablishExecutionSessionRequest.model_json_schema()["properties"]
    response_schema = RunSuccessResponse.model_json_schema()["properties"]

    assert request.model_source["authority_owned_member"] == {"model": True}
    assert request.experiment_specification["authority_owned_member"] == {
        "experiment": True
    }
    assert response.artifacts["result"]["authority_owned_member"] == {"artifact": True}
    assert request_schema["model_source"]["additionalProperties"] is True
    assert request_schema["experiment_specification"]["additionalProperties"] is True
    assert (
        response_schema["artifacts"]["additionalProperties"]["additionalProperties"]
        is True
    )


def test_run_outcomes_share_one_artifact_shape() -> None:
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


def test_release_session_contract_is_closed() -> None:
    request = ReleaseExecutionSessionRequest(session_id="session-1")
    response = ExecutionSessionReleasedResponse(session_id="session-1")

    assert request.model_dump(mode="json") == {"session_id": "session-1"}
    assert response.model_dump(mode="json") == {
        "outcome": "success",
        "session_id": "session-1",
    }
    with pytest.raises(ValidationError):
        ExecutionSessionReleasedResponse.model_validate(
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
def test_shared_selection_errors_are_owned(
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


@pytest.mark.parametrize(
    ("condition", "code"),
    [
        (ExecutionSessionNotFound("session-1"), "unknown_execution_session"),
        (
            ExperimentRevisionNotFound("sha256:experiment"),
            "unknown_experiment_revision",
        ),
    ],
)
def test_application_selection_conditions_are_mapped(
    condition: ExecutionSessionNotFound | ExperimentRevisionNotFound,
    code: ExecutionServiceErrorCode,
) -> None:
    error = execution_service_error_from_condition(condition)

    assert error.error.code == code
