"""Ephemeral coordination for publication-independent Experiment execution."""

from dataclasses import dataclass
import secrets
from typing import Any

from gda_balancing.application.experiment_execution import (
    ExperimentExecutionOutcome,
    execute_checked_experiment,
)
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.model import (
    authority_context_for_checked,
    check_model_source_value,
    compile_checked_model,
)


@dataclass(frozen=True)
class ExecutionSessionCreated:
    """Public identities established by one admitted session creation."""

    session_id: str
    resolved_model_identity: str
    revision_id: str


@dataclass(frozen=True)
class ExperimentRevisionAdmitted:
    """Identity and insertion state of one admitted Experiment revision."""

    revision_id: str
    created: bool


class ExecutionSessionNotFound(LookupError):
    """The requested process-local Execution session does not exist."""


class ExperimentRevisionNotFound(LookupError):
    """The requested immutable Experiment revision does not exist."""


@dataclass
class _ExecutionSession:
    authority_context: AdmittedAuthorityContext
    model_artifacts: dict[str, dict[str, Any]]
    revisions: dict[str, CheckedExperiment]


class ExecutionSessions:
    """Coordinate isolated in-memory sessions behind one small Application API."""

    def __init__(self) -> None:
        self._sessions: dict[str, _ExecutionSession] = {}

    def create(
        self,
        model_source: dict[str, Any],
        experiment_specification: dict[str, Any],
    ) -> ExecutionSessionCreated | Schema2RefusalReport:
        """Admit one Model and initial Experiment before publishing the session."""
        checked_model = check_model_source_value(model_source)
        if isinstance(checked_model, Schema2RefusalReport):
            return checked_model
        authority_context = authority_context_for_checked(checked_model)
        model_artifacts = compile_checked_model(checked_model)
        checked_experiment = check_experiment_value(
            experiment_specification,
            model_artifacts,
            authority_context=authority_context,
        )
        if isinstance(checked_experiment, Schema2RefusalReport):
            return checked_experiment
        session_id = secrets.token_urlsafe(24)
        self._sessions[session_id] = _ExecutionSession(
            authority_context=authority_context,
            model_artifacts=model_artifacts,
            revisions={checked_experiment.content_identity: checked_experiment},
        )
        return ExecutionSessionCreated(
            session_id=session_id,
            resolved_model_identity=str(
                model_artifacts["resolved-model"]["content_identity"]
            ),
            revision_id=checked_experiment.content_identity,
        )

    def admit_revision(
        self,
        session_id: str,
        experiment_specification: dict[str, Any],
    ) -> ExperimentRevisionAdmitted | Schema2RefusalReport:
        """Fully admit one immutable revision before making it runnable."""
        try:
            session = self._sessions[session_id]
        except KeyError as error:
            raise ExecutionSessionNotFound(session_id) from error
        checked = check_experiment_value(
            experiment_specification,
            session.model_artifacts,
            authority_context=session.authority_context,
        )
        if isinstance(checked, Schema2RefusalReport):
            return checked
        created = checked.content_identity not in session.revisions
        if created:
            session.revisions[checked.content_identity] = checked
        return ExperimentRevisionAdmitted(
            revision_id=checked.content_identity,
            created=created,
        )

    def run(
        self,
        session_id: str,
        revision_id: str,
    ) -> ExperimentExecutionOutcome:
        """Run one explicitly selected revision with fresh Runtime state."""
        try:
            session = self._sessions[session_id]
        except KeyError as error:
            raise ExecutionSessionNotFound(session_id) from error
        try:
            checked = session.revisions[revision_id]
        except KeyError as error:
            raise ExperimentRevisionNotFound(revision_id) from error
        return execute_checked_experiment(checked)
