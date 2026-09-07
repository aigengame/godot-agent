"""Terminal audit admission must bind the actual refusing execution frame."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import (
    runtime_terminal_audit_members,
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.runtime.execution import (
    PreparedExperiment,
    RuntimeRefusalOutcome,
    evaluate_prepared_experiment,
    prepare_experiment,
)
from test_schema2_experiment_cli import (
    _experiment,
    _rpg_model_source,
    _widen_mitigated_damage_formula,
)
from test_selected_runtime_reason_decoding import _reason_context


def _terminal_members(
    tmp_path: Path, *, event_limit: int | None, shared_mapping: bool = False
) -> tuple[CheckedExperiment, dict[str, dict[str, Any]]]:
    source = _rpg_model_source()
    next(
        row for row in source["modules"][0]["symbols"] if row["symbol"] == "base_damage"
    )["domain"]["maximum"] = (1 << 63) - 1
    _widen_mitigated_damage_formula(source, damage_before_defense_maximum=(1 << 63) - 1)
    context = _reason_context(
        remap=shared_mapping, event_limit=event_limit, shared=shared_mapping
    )
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    compiled = compile_checked_model(model)
    program = admit_rir(compiled["rir-semantic-payload"], authority_context=context)
    receipt: dict[str, Any] = {"member_locators": []}
    for name, artifact in compiled.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        receipt["member_locators"].append({"logical_name": name, "locator": str(path)})
    specification = _experiment(build_receipt=receipt, base_damage=1 << 62)
    next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "critical_threshold"
    )["value"] = 100
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment), prepared
    outcome = evaluate_prepared_experiment(prepared)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    members = {
        name: deepcopy(cast(dict[str, Any], member.value))
        for name, member in runtime_terminal_audit_members(
            checked,
            outcome,
            evaluator=prepared.evaluator,
            resolved_runtime=prepared.resolved_runtime,
        ).items()
    }
    # A guaranteed critical doubles 2**62 beyond Int64. With a one-step Event
    # bound, the first invoke and its callee's first instruction refuse earlier.
    expected_signal = "numeric-overflow" if event_limit is None else "step-limit"
    expected_reason = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
        if row["definition"].get("signal") == expected_signal
    )
    audit = members["runtime-terminal-audit"]
    assert audit["diagnostic"]["code"] == expected_reason["diagnostic"]
    assert audit["refusing_event"]["reason"] == expected_reason["diagnostic"]
    assert validate_experiment_artifact_set(checked, members)
    return checked, members


def _assert_reidentified_audit_refuses(
    checked: CheckedExperiment,
    members: dict[str, dict[str, Any]],
    mutated_audit: dict[str, Any],
) -> None:
    contract = checked.output_contracts["runtime-terminal-audit"]
    payload = {
        key: value
        for key, value in mutated_audit.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    reidentified = contract.identify(payload)
    assert contract.verify(reidentified)
    assert validate_experiment_member(checked, "runtime-terminal-audit", reidentified)
    assert (
        reidentified["content_identity"]
        != members["runtime-terminal-audit"]["content_identity"]
    )
    tampered = {**members, "runtime-terminal-audit": reidentified}
    assert not validate_experiment_artifact_set(checked, tampered)


@pytest.mark.parametrize(
    "event_limit", [None, 1], ids=["numeric-overflow", "step-limit"]
)
def test_terminal_audit_rejects_another_admitted_call_site(
    tmp_path: Path, event_limit: int | None
):
    checked, members = _terminal_members(tmp_path, event_limit=event_limit)
    audit = deepcopy(members["runtime-terminal-audit"])
    original_identity = audit["refusing_event"]["call_site_identity"]
    assert isinstance(original_identity, str)
    replacement = next(
        row["identity"]
        for row in checked.rir["call_sites"]
        if row["identity"] != original_identity
    )
    audit["refusing_event"]["call_site_identity"] = replacement
    _assert_reidentified_audit_refuses(checked, members, audit)


def test_terminal_audit_rejects_wrong_root_before_any_completed_call(tmp_path: Path):
    checked, members = _terminal_members(tmp_path, event_limit=1)
    audit = deepcopy(members["runtime-terminal-audit"])
    refusing_event = audit["refusing_event"]
    assert refusing_event["attempted_calls"] == []
    original_root, separator, suffix = refusing_event["call_path"].partition("/")
    assert separator and suffix
    replacement_root = f"{original_root}-not-admitted"
    assert replacement_root not in {row["id"] for row in checked.rir["entrypoints"]}
    refusing_event["call_path"] = f"{replacement_root}/{suffix}"
    _assert_reidentified_audit_refuses(checked, members, audit)


@pytest.mark.parametrize("shared_mapping", [False, True], ids=["distinct", "shared"])
def test_terminal_audit_rejects_different_non_step_reason(
    tmp_path: Path, shared_mapping: bool
):
    checked, members = _terminal_members(
        tmp_path, event_limit=None, shared_mapping=shared_mapping
    )
    audit = deepcopy(members["runtime-terminal-audit"])
    original_code = audit["refusing_event"]["reason"]
    replacement = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
        if row["definition"].get("stage") == "runtime"
        and row["definition"].get("signal")
        not in {None, "numeric-overflow", "step-limit"}
        and row["definition"]["diagnostic"] != original_code
    )
    # Both fields describe the same diagnostic. Keep their equality, framing,
    # budget and rollback intact while substituting a different declared signal.
    audit["refusing_event"]["reason"] = replacement["diagnostic"]
    audit["diagnostic"]["code"] = replacement["diagnostic"]
    _assert_reidentified_audit_refuses(checked, members, audit)


@pytest.mark.parametrize(
    "event_limit", [None, 1], ids=["numeric-overflow", "step-limit"]
)
def test_terminal_audit_rejects_another_existing_instruction(
    tmp_path: Path, event_limit: int | None
):
    checked, members = _terminal_members(tmp_path, event_limit=event_limit)
    audit = deepcopy(members["runtime-terminal-audit"])
    refusing_event = audit["refusing_event"]
    operation = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == refusing_event["operation"]
    )
    original_index = refusing_event["instruction_index"]
    assert original_index in range(len(operation["body"]))
    replacement = next(
        index for index in range(len(operation["body"])) if index != original_index
    )
    refusing_event["instruction_index"] = replacement
    _assert_reidentified_audit_refuses(checked, members, audit)
