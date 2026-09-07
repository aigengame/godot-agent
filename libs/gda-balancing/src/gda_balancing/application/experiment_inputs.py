"""Admit the explicit program and authored intent for an Experiment use case."""

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment
from gda_balancing.domain.model import read_rir


def check_experiment_inputs(
    specification: str,
    rir: str,
    *,
    authority_context: AdmittedAuthorityContext | None = None,
) -> CheckedExperiment | Schema2RefusalReport:
    """Read and admit one RIR, then bind the Experiment to its semantic identity."""
    context = authority_context or packaged_authority_context()
    program = read_rir(rir, authority_context=context)
    if isinstance(program, Schema2RefusalReport):
        return program
    return check_experiment(specification, program, authority_context=context)
