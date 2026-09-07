"""Check one Standard Schema Experiment Specification."""

from dataclasses import dataclass

from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class ExperimentCheckReport:
    """Successful Experiment admission and its resolved bindings."""

    experiment_identity: str
    rir_semantic_identity: str
    runtime_profile: str


def check_experiment_specification(
    specification: str,
    rir: str,
    *,
    authority_context: AdmittedAuthorityContext | None = None,
) -> ExperimentCheckReport | Schema2RefusalReport:
    """Admit one Experiment Specification and report its public bindings."""
    checked = check_experiment_inputs(
        specification,
        rir,
        authority_context=authority_context,
    )
    if isinstance(checked, Schema2RefusalReport):
        return checked
    return ExperimentCheckReport(
        experiment_identity=checked.content_identity,
        rir_semantic_identity=checked.rir["semantic_identity"],
        runtime_profile=checked.value["runtime"]["profile"],
    )
