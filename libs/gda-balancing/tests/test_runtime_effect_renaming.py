"""Runtime effect capabilities follow admitted, executable Operation closure."""

from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import admit_rir
from gda_balancing.domain.runtime import execution as runtime_execution, projections
from priority_protocol_support import authorities, source, specification
from schema2_bootstrap_conformance_support import _consumer_b
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import _reidentify_language_bundle


_EFFECT_RENAMES = {
    "event.commit": "renamed.effect.commit",
    "event.schedule": "renamed.effect.schedule",
    "metric.observe": "renamed.effect.observe",
    "snapshot.commit": "renamed.effect.snapshot",
}


def _rename_effects(value):
    # Exact effect IDs are LDB data. Kernel node/operator tokens are unchanged.
    if isinstance(value, dict):
        for key in value:
            value[key] = _rename_effects(value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _rename_effects(item)
    elif isinstance(value, str):
        return _EFFECT_RENAMES.get(value, value)
    return value


@dataclass(frozen=True)
class _Execution:
    candidate: _PublicCandidate
    checked: CheckedExperiment
    specification_path: Path
    rir_path: str
    effects: tuple[str, ...]


@pytest.fixture(scope="module", params=(False, True), ids=("original", "renamed"))
def execution(request, tmp_path_factory) -> _Execution:
    kernel, language, turn = authorities()
    original_kernel = deepcopy(kernel)
    model_source = source(turn)
    original_source = deepcopy(model_source)
    if request.param:
        _rename_effects(language)
        _reidentify_language_bundle(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    independent = _consumer_b(kernel, language)
    assert independent["admitted"], independent["diagnostics"]
    assert kernel == original_kernel
    assert source(turn) == original_source
    candidate = _PublicCandidate(
        tmp_path_factory.mktemp(f"runtime-effects-{request.param}"),
        authorities=(kernel, language),
    )
    candidate.write_source(model_source)
    checked_source = candidate.cli("model", "check", str(candidate.source))
    assert checked_source["checked"] is True
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "build"),
        "--invocation-key",
        "21" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    rir_path = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    program = admit_rir(rir, authority_context=context)
    value = specification(rir)
    path = candidate.directory / "experiment.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    checked_public = candidate.cli("experiment", "check", str(path), "--rir", rir_path)
    assert checked_public["checked"] is True
    checked = check_experiment_value(value, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    expected = tuple(
        sorted(_EFFECT_RENAMES.values() if request.param else _EFFECT_RENAMES)
    )
    assert value["runtime"]["required_evaluator"]["effects"] == list(expected)
    return _Execution(candidate, checked, path, rir_path, expected)


def test_public_runtime_executes_opaque_effect_labels(execution):
    candidate = execution.candidate
    receipt = candidate.cli(
        "experiment",
        "run",
        str(execution.specification_path),
        "--rir",
        execution.rir_path,
        "--out",
        str(candidate.directory / "run"),
        "--invocation-key",
        "22" * 32,
    )
    members = _members(receipt)
    assert validate_experiment_artifact_set(execution.checked, members)
    assert members["evaluation-run"]["outcome"] == "accepted"
    assert [sample["value"] for sample in members["metric-dataset"]["samples"]] == [7]
    manifest = members["evaluator-capability-manifest"]
    assert manifest["effects"] == list(execution.effects)
    profile = members["resolved-runtime-profile"]["runtime_profile"]
    # The admitted profile also permits unused cancellation and named RNG.
    # Those permissions neither confer reachable effects nor block this program.
    assert set(profile["effects"]) > set(execution.effects)
    assert profile["id"] in manifest["runtime_profiles"]


def test_required_effects_do_not_grant_evaluator_capabilities(execution):
    checked = execution.checked
    value = deepcopy(checked.value)
    value["runtime"]["required_evaluator"]["effects"].append("rng.named-stream")
    value["runtime"]["required_evaluator"]["effects"].sort()
    program = admit_rir(checked.rir, authority_context=checked.authority_context)
    refused = check_experiment_value(
        value, program, authority_context=checked.authority_context
    )
    assert isinstance(refused, Schema2RefusalReport)
    assert refused.stage == "resolution"
    location = refused.diagnostics[0].primary
    assert isinstance(location, ArtifactLocation)
    assert location.pointer == "/runtime/required_evaluator/effects"
    # Independently exercise the producer declaration boundary: copying the
    # caller requirement here must not manufacture support for an unused effect.
    forged = replace(checked, value=value)
    manifest = projections.evaluator_manifest(forged)
    assert manifest.value["effects"] == list(execution.effects)
    assert (
        projections.unsupported_evaluator_requirement(forged, manifest.value)
        == "effects"
    )


def test_unsupported_operator_refuses_before_dispatch(execution, monkeypatch):
    monkeypatch.setattr(
        projections,
        "SUPPORTED_RUNTIME_OPERATORS",
        projections.SUPPORTED_RUNTIME_OPERATORS - {"schedule-operation"},
    )
    manifest = projections.evaluator_manifest(execution.checked)
    assert "schedule" not in manifest.value["instruction_nodes"]
    assert manifest.value["effects"] == list(execution.effects)

    def forbidden_dispatch(_prepared):
        pytest.fail("unsupported program reached Runtime dispatch")

    monkeypatch.setattr(
        runtime_execution, "evaluate_prepared_experiment", forbidden_dispatch
    )
    refused = runtime_execution.evaluate_experiment(execution.checked)
    assert isinstance(refused, Schema2RefusalReport)
    assert refused.stage == "resolution"
    location = refused.diagnostics[0].primary
    assert isinstance(location, ArtifactLocation)
    assert location.pointer == "/runtime/required_evaluator/instruction_nodes"
