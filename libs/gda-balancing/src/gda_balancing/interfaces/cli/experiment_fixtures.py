"""Bind Application-owned Experiment fixtures to the Model build descriptor."""

from pathlib import Path

from gda_balancing.application.experiment_fixtures import (
    prepare_valid_experiment as _prepare_valid_experiment,
)
from gda_balancing.application.experiment_fixtures import (
    prepare_verdict_experiment as _prepare_verdict_experiment,
)
from gda_balancing.interfaces.cli.model_build import MODEL_BUILD
from gda_balancing.interfaces.cli.surface import descriptor_identity


def prepare_valid_experiment(root: Path, token: int) -> str:
    """Bind the fixture build to the public Model build contract."""
    return _prepare_valid_experiment(
        root,
        token,
        model_build_descriptor_identity=descriptor_identity(MODEL_BUILD),
    )


def prepare_verdict_experiment(root: Path, token: int) -> str:
    """Bind the rejecting fixture build to the public Model build contract."""
    return _prepare_verdict_experiment(
        root,
        token,
        model_build_descriptor_identity=descriptor_identity(MODEL_BUILD),
    )
