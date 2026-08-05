"""Check one Standard Schema Experiment Specification."""

from dataclasses import dataclass

from gda_balancing.domain.experiment import check_experiment
from gda_balancing.schema2.authority import AdmittedAuthorityContext
from gda_balancing.schema2.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class ExperimentCheckReport:
    """Successful Experiment admission and its resolved bindings."""

    experiment_identity: str
    resolved_model_identity: str
    runtime_profile: str


def check_experiment_specification(
    specification: str,
    *,
    authority_context: AdmittedAuthorityContext | None = None,
) -> ExperimentCheckReport | Schema2RefusalReport:
    """Admit one Experiment Specification and report its public bindings."""
    checked = check_experiment(
        specification,
        authority_context=authority_context,
    )
    if isinstance(checked, Schema2RefusalReport):
        return checked
    return ExperimentCheckReport(
        experiment_identity=checked.content_identity,
        resolved_model_identity=checked.resolved_model["content_identity"],
        runtime_profile=checked.value["runtime"]["profile"],
    )
