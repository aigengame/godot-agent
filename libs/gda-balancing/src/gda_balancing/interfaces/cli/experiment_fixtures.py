"""Bind Application-owned Experiment fixtures to the Model build descriptor."""

from pathlib import Path

from gda_balancing.application.experiment_fixtures import (
    ExperimentFixture,
    prepare_runtime_refusal_experiment as _prepare_runtime_refusal_experiment,
)
from gda_balancing.application.experiment_fixtures import (
    prepare_valid_experiment as _prepare_valid_experiment,
)
from gda_balancing.application.experiment_fixtures import (
    prepare_verdict_experiment as _prepare_verdict_experiment,
)
from gda_balancing.interfaces.cli.model_build import MODEL_BUILD
from gda_balancing.interfaces.cli.surface import descriptor_identity


def prepare_valid_experiment(root: Path, token: int) -> ExperimentFixture:
    """Bind the fixture build to the public Model build contract."""
    return _prepare_valid_experiment(
        root,
        token,
        model_build_descriptor_identity=descriptor_identity(MODEL_BUILD),
    )


def prepare_verdict_experiment(root: Path, token: int) -> ExperimentFixture:
    """Bind the rejecting fixture build to the public Model build contract."""
    return _prepare_verdict_experiment(
        root,
        token,
        model_build_descriptor_identity=descriptor_identity(MODEL_BUILD),
    )


def prepare_runtime_refusal_experiment(root: Path, token: int) -> ExperimentFixture:
    """Bind the runtime-refusal fixture build to the public Model contract."""
    return _prepare_runtime_refusal_experiment(
        root,
        token,
        model_build_descriptor_identity=descriptor_identity(MODEL_BUILD),
    )


def _fixture_args(
    root: Path, token: int, fixture: ExperimentFixture, refusing: bool
) -> tuple[str, ...]:
    specification = root / f"experiment-{token}.json"
    specification.write_text(
        "{}" if refusing else fixture.specification, encoding="utf-8"
    )
    return (str(specification), "--rir", fixture.rir)


def prepare_experiment_args(root: Path, token: int, refusing: bool) -> tuple[str, ...]:
    """Prepare both explicit inputs for the complete public admission path."""
    return _fixture_args(root, token, prepare_valid_experiment(root, token), refusing)


def prepare_experiment_verdict_args(root: Path, token: int) -> tuple[str, ...]:
    """Prepare a real Metric Verdict through the same explicit inputs."""
    return _fixture_args(root, token, prepare_verdict_experiment(root, token), False)
