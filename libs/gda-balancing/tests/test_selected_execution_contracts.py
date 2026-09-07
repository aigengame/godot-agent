"""Selected output contracts and detached admitted Experiment requests (#874)."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.artifacts import select_artifact_contract
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
    admit_rir,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)


_EXAMPLE = Path(__file__).parents[1] / "examples" / "schema2" / "rpg-combat-cast"


@pytest.fixture(scope="module")
def admitted_model():
    context = packaged_authority_context()
    source = json.loads((_EXAMPLE / "model-source.json").read_bytes())
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    return (
        context,
        artifacts,
        admit_rir(artifacts["rir-semantic-payload"], authority_context=context),
    )


def test_selected_artifact_contract_preserves_bytes_and_detaches_authority(
    admitted_model,
):
    context, artifacts, _program = admitted_model
    _kernel, mutable_language = context.mutable_pair()
    assert len(artifacts) == 8
    for kind, value in artifacts.items():
        contract = select_artifact_contract(mutable_language, kind)
        payload = {
            key: item
            for key, item in value.items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
        assert canonical_bytes(contract.identify(payload)) == canonical_bytes(value)
        assert contract.verify(value)
        wrong_kind = deepcopy(value)
        wrong_kind["artifact_kind"] = "another-kind"
        assert not contract.verify(wrong_kind)
        changed_content = deepcopy(value)
        changed_content["content_identity"] = "sha256:" + "0" * 64
        assert not contract.verify(changed_content)

        # This is caller mutation after selection, not admission of a new law.
        original = next(
            row
            for row in mutable_language["language"]["artifact_contracts"]
            if row["artifact_kind"] == kind
        )
        original["identity_domain"] = "caller-changed-after-selection"
        assert canonical_bytes(contract.identify(payload)) == canonical_bytes(value)
        assert contract.verify(value)
        with pytest.raises(TypeError):
            contract.definition["identity_domain"] = "mutated"
        with pytest.raises(TypeError):
            contract.schema["properties"]["artifact_kind"]["const"] = "mutated"


@pytest.fixture
def admitted_experiment(admitted_model):
    context, artifacts, program = admitted_model
    value = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    value["model"] = {
        "rir_semantic_identity": artifacts["rir-semantic-payload"]["semantic_identity"]
    }
    checked = check_experiment_value(value, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    return context, program, value, checked


def test_checked_experiment_pins_nested_inputs_and_output_contracts(
    admitted_experiment,
):
    context, program, value, checked = admitted_experiment
    original_seed = value["seed"]["value"]
    expected = evaluate_experiment(checked)
    assert isinstance(expected, EvaluationArtifacts), expected
    expected_bytes = {
        name: canonical_bytes(member.value) for name, member in expected.members.items()
    }
    assert validate_experiment_artifact_set(
        checked,
        {
            name: cast(dict[str, Any], member.value)
            for name, member in expected.members.items()
        },
    )

    value["seed"]["value"] += 1
    expected.members["metric-dataset"].value["samples"][0]["value"] = -999
    assert checked.value["seed"]["value"] == original_seed
    with pytest.raises(TypeError):
        checked.value["seed"]["value"] = 0
    with pytest.raises(TypeError):
        checked.rir["selected_semantics"]["packages"].append({"id": "injected"})
    with pytest.raises(TypeError):
        checked.output_contracts["event-trace"].schema["properties"].clear()

    repeated = evaluate_experiment(checked)
    assert isinstance(repeated, EvaluationArtifacts), repeated
    assert {
        name: canonical_bytes(member.value) for name, member in repeated.members.items()
    } == expected_bytes
    assert validate_experiment_artifact_set(
        checked,
        {
            name: cast(dict[str, Any], member.value)
            for name, member in repeated.members.items()
        },
    )
    next_checked = check_experiment_value(value, program, authority_context=context)
    assert isinstance(next_checked, CheckedExperiment), next_checked
    assert next_checked.value["seed"]["value"] == original_seed + 1
    assert next_checked.content_identity != checked.content_identity


def test_execution_and_independent_validation_need_no_ingress_authorities(
    admitted_experiment,
):
    _context, _program, _value, checked = admitted_experiment

    class ExecutionBoundary:
        """Expose admitted data while trapping a return to an ingress catalog.

        This is a dependency-cut regression, not an alternative admission path.
        The unwrapped request above passes normal authority and Model admission.
        """

        def __getattr__(self, name):
            if name in {"kernel", "language_bundle", "authority_context"}:
                raise AssertionError(
                    f"execution returned to an ingress authority: {name}"
                )
            return getattr(checked, name)

    closed = cast(CheckedExperiment, ExecutionBoundary())
    execution = evaluate_experiment(closed)
    assert isinstance(execution, EvaluationArtifacts), execution
    assert validate_experiment_artifact_set(
        closed,
        {
            name: cast(dict[str, Any], member.value)
            for name, member in execution.members.items()
        },
    )
    original = evaluate_experiment(checked)
    assert isinstance(original, EvaluationArtifacts), original
    assert {
        name: canonical_bytes(member.value)
        for name, member in execution.members.items()
    } == {
        name: canonical_bytes(member.value) for name, member in original.members.items()
    }
