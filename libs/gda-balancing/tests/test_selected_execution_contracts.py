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
    project_compiled_model_binding,
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
    return context, artifacts, project_compiled_model_binding(artifacts, context)


def test_selected_artifact_contract_preserves_bytes_and_detaches_authority(
    admitted_model,
):
    context, artifacts, _binding = admitted_model
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


def test_checked_experiment_pins_nested_inputs_and_output_contracts(admitted_model):
    context, artifacts, binding = admitted_model
    value = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    build = artifacts["build-receipt"]
    value["kernel_identity"] = build["kernel_identity"]
    value["language_bundle_identity"] = build["language_bundle_identity"]
    value["model"] = {
        key: build["content_identity"]
        if key == "build_receipt_identity"
        else build[key]
        for key in value["model"]
    }
    checked = check_experiment_value(value, binding, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
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
    next_checked = check_experiment_value(value, binding, authority_context=context)
    assert isinstance(next_checked, CheckedExperiment), next_checked
    assert next_checked.value["seed"]["value"] == original_seed + 1
    assert next_checked.content_identity != checked.content_identity
