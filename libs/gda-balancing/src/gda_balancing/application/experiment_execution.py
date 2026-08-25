"""Publication-independent execution of one admitted Experiment."""

from dataclasses import dataclass

from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.evidence import runtime_terminal_audit_members
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.publication_types import PublicationMember
from gda_balancing.domain.runtime.execution import (
    PreparedExperiment,
    RuntimeRefusalOutcome,
    evaluate_prepared_experiment,
    prepare_experiment,
)


@dataclass(frozen=True)
class ExperimentExecutionSuccess:
    """A successful run and its complete semantic artifact members."""

    members: dict[str, PublicationMember]


@dataclass(frozen=True)
class ExperimentExecutionVerdict:
    """A metric verdict and its complete semantic artifact members."""

    failed_metrics: tuple[str, ...]
    members: dict[str, PublicationMember]


@dataclass(frozen=True)
class ExperimentExecutionRefusal:
    """A typed refusal and any terminal-audit artifact members."""

    report: Schema2RefusalReport
    members: dict[str, PublicationMember]


ExperimentExecutionOutcome = (
    ExperimentExecutionSuccess | ExperimentExecutionVerdict | ExperimentExecutionRefusal
)
PreparedExperimentExecution = PreparedExperiment


def prepare_checked_experiment(
    checked: CheckedExperiment,
) -> PreparedExperimentExecution | ExperimentExecutionRefusal:
    """Prepare complete reproduction identity without Event dispatch."""
    prepared = prepare_experiment(checked)
    if isinstance(prepared, Schema2RefusalReport):
        return ExperimentExecutionRefusal(report=prepared, members={})
    return prepared


def execute_prepared_experiment(
    prepared: PreparedExperimentExecution,
) -> ExperimentExecutionOutcome:
    """Execute one prepared Experiment without filesystem publication."""
    evaluation = evaluate_prepared_experiment(prepared)
    checked = prepared.checked
    if isinstance(evaluation, RuntimeRefusalOutcome):
        return ExperimentExecutionRefusal(
            report=evaluation.report,
            members=runtime_terminal_audit_members(checked, evaluation),
        )
    if isinstance(evaluation, Schema2RefusalReport):
        return ExperimentExecutionRefusal(report=evaluation, members={})
    if evaluation.accepted:
        return ExperimentExecutionSuccess(members=evaluation.members)
    return ExperimentExecutionVerdict(
        failed_metrics=evaluation.failed_metrics,
        members=evaluation.members,
    )


def execute_checked_experiment(
    checked: CheckedExperiment,
) -> ExperimentExecutionOutcome:
    """Execute a fully admitted Experiment without filesystem publication."""
    prepared = prepare_checked_experiment(checked)
    if isinstance(prepared, ExperimentExecutionRefusal):
        return prepared
    return execute_prepared_experiment(prepared)
