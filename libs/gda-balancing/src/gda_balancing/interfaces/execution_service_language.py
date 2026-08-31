"""Published Language for the Execution Open Host Service (bADR-0027)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from gda_balancing.domain.diagnostics import Schema2RefusalReport


EXECUTION_SERVICE_LANGUAGE_REVISION = 1
ExecutionServiceErrorCode = Literal[
    "unknown_execution_session",
    "unknown_experiment_revision",
]

_ERROR_MESSAGES: dict[ExecutionServiceErrorCode, str] = {
    "unknown_execution_session": "the Execution session does not exist",
    "unknown_experiment_revision": "the Experiment revision does not exist",
}


class ExecutionServiceError(BaseModel):
    """One OHS-specific error independent of transport status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["service"] = "service"
    code: ExecutionServiceErrorCode
    message: str


class ExecutionServiceErrorEnvelope(BaseModel):
    """Shared OHS error framing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ExecutionServiceError


def execution_service_error(
    code: ExecutionServiceErrorCode,
) -> ExecutionServiceErrorEnvelope:
    """Return the contract-owned representation of one shared OHS error."""
    return ExecutionServiceErrorEnvelope(
        error=ExecutionServiceError(code=code, message=_ERROR_MESSAGES[code])
    )


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
    """An authority-owned Domain refusal returned by the OHS."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["refusal"] = "refusal"
    refusal: Schema2RefusalReport


class AdmitExperimentRevisionRequest(BaseModel):
    """One complete Experiment value for an existing session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_specification: dict[str, Any]


class ExperimentRevisionAdmittedResponse(BaseModel):
    """Identity and insertion state of an admitted revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    revision_id: str
    created: bool


class RunExperimentRequest(BaseModel):
    """The exact immutable revision selected for one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: str


class RunSuccessResponse(BaseModel):
    """A successful execution with its existing artifacts inline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    artifacts: dict[str, dict[str, Any]]


class RunVerdictResponse(BaseModel):
    """A metric verdict with its existing artifacts inline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["verdict"] = "verdict"
    failed_metrics: list[str]
    artifacts: dict[str, dict[str, Any]]


class RunRefusalResponse(BaseModel):
    """A typed refusal with any terminal-audit artifacts inline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["refusal"] = "refusal"
    refusal: Schema2RefusalReport
    artifacts: dict[str, dict[str, Any]]


class ExecutionSessionDeletedResponse(BaseModel):
    """Acknowledgement that one process-local session was released."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["success"] = "success"
    session_id: str
