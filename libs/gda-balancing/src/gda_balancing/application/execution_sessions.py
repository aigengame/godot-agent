"""Ephemeral coordination for publication-independent Experiment execution."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import secrets
import threading
from typing import Any

from gda_balancing.application.experiment_execution import (
    ExperimentExecutionOutcome,
    execute_checked_experiment,
)
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.model import (
    ExactResolvedModelBinding,
    authority_context_for_checked,
    check_model_source_value,
    compile_checked_model,
    project_compiled_model_binding,
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


class _OrderedGate:
    """Run admitted work in first-entry order without owning its behavior."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._next_ticket = 0
        self._serving = 0

    @contextmanager
    def hold(self) -> Iterator[None]:
        with self._condition:
            ticket = self._next_ticket
            self._next_ticket += 1
            while ticket != self._serving:
                self._condition.wait()
        try:
            yield
        finally:
            with self._condition:
                self._serving += 1
                self._condition.notify_all()


@dataclass
class _ExecutionSession:
    authority_context: AdmittedAuthorityContext
    model_binding: ExactResolvedModelBinding
    revisions: dict[str, CheckedExperiment]
    gate: _OrderedGate = field(default_factory=_OrderedGate)


class ExecutionSessions:
    """Coordinate isolated in-memory sessions behind one small Application API."""

    def __init__(self) -> None:
        self._sessions: dict[str, _ExecutionSession] = {}
        self._registry_lock = threading.RLock()
        self._execution_gate = _OrderedGate()

    def _session(self, session_id: str) -> _ExecutionSession:
        with self._registry_lock:
            try:
                return self._sessions[session_id]
            except KeyError as error:
                raise ExecutionSessionNotFound(session_id) from error

    def _require_current(
        self,
        session_id: str,
        session: _ExecutionSession,
    ) -> None:
        with self._registry_lock:
            if self._sessions.get(session_id) is not session:
                raise ExecutionSessionNotFound(session_id)

    def create(
        self,
        model_source: dict[str, Any],
        experiment_specification: dict[str, Any],
    ) -> ExecutionSessionCreated | Schema2RefusalReport:
        """Admit one Model and initial Experiment before publishing the session."""
        with self._execution_gate.hold():
            checked_model = check_model_source_value(model_source)
            if isinstance(checked_model, Schema2RefusalReport):
                return checked_model
            authority_context = authority_context_for_checked(checked_model)
            model_artifacts = compile_checked_model(checked_model)
            model_binding = project_compiled_model_binding(
                model_artifacts,
                authority_context,
            )
            checked_experiment = check_experiment_value(
                experiment_specification,
                model_binding,
                authority_context=authority_context,
            )
            if isinstance(checked_experiment, Schema2RefusalReport):
                return checked_experiment
            session_id = secrets.token_urlsafe(24)
            session = _ExecutionSession(
                authority_context=authority_context,
                model_binding=model_binding,
                revisions={checked_experiment.content_identity: checked_experiment},
            )
            with self._registry_lock:
                self._sessions[session_id] = session
        return ExecutionSessionCreated(
            session_id=session_id,
            resolved_model_identity=str(model_binding.resolved_model_identity),
            revision_id=checked_experiment.content_identity,
        )

    def admit_revision(
        self,
        session_id: str,
        experiment_specification: dict[str, Any],
    ) -> ExperimentRevisionAdmitted | Schema2RefusalReport:
        """Fully admit one immutable revision before making it runnable."""
        session = self._session(session_id)
        with session.gate.hold():
            self._require_current(session_id, session)
            with self._execution_gate.hold():
                checked = check_experiment_value(
                    experiment_specification,
                    session.model_binding,
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
        session = self._session(session_id)
        with session.gate.hold():
            self._require_current(session_id, session)
            try:
                checked = session.revisions[revision_id]
            except KeyError as error:
                raise ExperimentRevisionNotFound(revision_id) from error
            with self._execution_gate.hold():
                return execute_checked_experiment(checked)

    def delete(self, session_id: str) -> None:
        """Release one process-local session and all of its revisions."""
        session = self._session(session_id)
        with session.gate.hold():
            with self._registry_lock:
                if self._sessions.get(session_id) is not session:
                    raise ExecutionSessionNotFound(session_id)
                del self._sessions[session_id]
