"""Selected publication contracts survive real commit and retry recovery."""

import json
from pathlib import Path

import pytest

import gda_balancing.domain.publication as publication_module
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionSuccess,
    execute_checked_experiment,
)
from gda_balancing.domain.artifact_set import EXPERIMENT_SUCCESS_ARTIFACT_SET
from gda_balancing.domain.experiment import CheckedExperiment, experiment_input_identity
from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.domain.experiment_artifacts import (
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.publication import (
    publish_artifact_set,
    recover_committed_artifact_set,
    select_publication_contracts,
)
from gda_balancing.interfaces.cli.experiment_fixtures import prepare_valid_experiment


def test_committed_recovery_consumes_only_selected_framing_and_member_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specification = tmp_path / "experiment.json"
    fixture = prepare_valid_experiment(tmp_path, 874)
    specification.write_text(fixture.specification, encoding="utf-8")
    checked = check_experiment_inputs(str(specification), fixture.rir)
    assert isinstance(checked, CheckedExperiment)
    execution = execute_checked_experiment(checked)
    assert isinstance(execution, ExperimentExecutionSuccess)
    contracts = select_publication_contracts(checked.language_bundle)

    def ambient_lookup_forbidden(*_args, **_kwargs):
        raise AssertionError(
            "publication consulted an authority catalog after selection"
        )

    monkeypatch.setattr(
        publication_module, "_verify_artifact", ambient_lookup_forbidden
    )
    monkeypatch.setattr(
        publication_module, "select_artifact_contract", ambient_lookup_forbidden
    )
    out = tmp_path / "evaluation.json"
    invocation_key = "8" * 64
    descriptor_identity = "sha256:" + "7" * 64
    input_identity = experiment_input_identity(checked.value)

    def member_validator(name, value):
        return validate_experiment_member(checked, name, value)

    def set_validator(values):
        return validate_experiment_artifact_set(checked, values)

    with pytest.raises(RuntimeError, match="injected publication fault after commit"):
        publish_artifact_set(
            execution.members,
            str(out),
            invocation_key,
            descriptor_identity,
            input_identity,
            contracts,
            EXPERIMENT_SUCCESS_ARTIFACT_SET,
            member_validator,
            "after-commit",
            artifact_set_validator=set_validator,
        )
    assert not out.exists()
    recovered = recover_committed_artifact_set(
        str(out),
        invocation_key,
        descriptor_identity,
        input_identity,
        contracts,
        (EXPERIMENT_SUCCESS_ARTIFACT_SET,),
        member_validator,
        artifact_set_validator=set_validator,
    )
    assert recovered is not None
    assert recovered.artifacts == {
        name: member.value for name, member in execution.members.items()
    }
    assert contracts.receipt.verify(recovered.receipt)
    assert (
        json.loads(out.read_text(encoding="utf-8"))
        == execution.members["evaluation-run"].value
    )
