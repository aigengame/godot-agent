"""Capacity refusals retain selected reason and exact independent execution facts."""

from copy import deepcopy

import pytest

from gda_balancing.application.experiment_execution import (
    ExperimentExecutionRefusal,
    execute_checked_experiment,
)
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from priority_protocol_support import authorities, source, specification
from test_bounded_fold_terminal_audit import _assert_reidentified_audit_refuses
from test_priority_protocol_public import _counter
from test_schema2_model_lowerer_conformance import _reidentify_language_bundle


def _rename_capacity_reason(value):
    if isinstance(value, dict):
        for key in value:
            value[key] = _rename_capacity_reason(value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _rename_capacity_reason(item)
    elif value == "structured.reason.list-capacity-exceeded":
        return "probe.reason.full-list"
    return value


@pytest.mark.parametrize("renamed", (False, True), ids=("original", "renamed-reason"))
def test_priority_capacity_audit_replays_selected_runtime_reason(renamed):
    kernel, language, turn = authorities()
    original_kernel = deepcopy(kernel)
    if renamed:
        _rename_capacity_reason(language)
        _reidentify_language_bundle(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert kernel == original_kernel
    model = check_model_source_value(source(turn), authority_context=context)
    assert isinstance(model, CheckedModel), model
    rir = compile_checked_model(model)["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("respond", _counter(1, 1)),
        ("respond", _counter(0, 2)),
        ("respond", _counter(1, 3)),
        ("pass", {"actor": 0}),
        ("pass", {"actor": 1}),
    ]
    checked = check_experiment_value(
        specification(rir, choices=choices), program, authority_context=context
    )
    assert isinstance(checked, CheckedExperiment), checked
    result = execute_checked_experiment(checked)
    assert isinstance(result, ExperimentExecutionRefusal), result
    members = {name: deepcopy(member.value) for name, member in result.members.items()}
    audit = members["runtime-terminal-audit"]
    reasons = [
        row["definition"]
        for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
    ]
    capacity = next(
        reason
        for reason in reasons
        if reason.get("stage") == "runtime"
        and reason.get("signal") == "structured-list-capacity-exceeded"
    )
    assert capacity["id"] == (
        "probe.reason.full-list"
        if renamed
        else "structured.reason.list-capacity-exceeded"
    )
    assert audit["diagnostic"]["code"] == capacity["diagnostic"]
    assert audit["refusing_event"]["reason"] == capacity["diagnostic"]
    assert audit["refusing_event"]["call_path"] == "respond/create-counter"
    assert audit["refusing_event"]["operation"] == "append-counter"
    # Seven root instructions reach invoke; seven child attempts reach append.
    assert audit["refusing_event"]["instruction_index"] == 6
    assert audit["budget_counters"]["event_steps"] == 14
    assert audit["budget_counters"]["node_steps"] == 71
    assert audit["refusing_event"]["attempted_calls"] == []
    assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
    assert audit["rollback"]["committed"] is False
    assert validate_experiment_artifact_set(checked, members)

    other_site = next(
        row["identity"]
        for row in checked.rir["call_sites"]
        if row["identity"] != audit["refusing_event"]["call_site_identity"]
    )
    for member, value in (
        ("instruction_index", 5),
        ("call_path", "respond"),
        ("call_site_identity", other_site),
    ):
        forged = deepcopy(audit)
        forged["refusing_event"][member] = value
        _assert_reidentified_audit_refuses(checked, members, forged)
    forged = deepcopy(audit)
    forged["budget_counters"]["event_steps"] -= 1
    forged["budget_counters"]["node_steps"] -= 1
    _assert_reidentified_audit_refuses(checked, members, forged)
    numeric = next(
        reason for reason in reasons if reason.get("signal") == "numeric-overflow"
    )
    assert numeric["diagnostic"] != capacity["diagnostic"]
    forged = deepcopy(audit)
    forged["diagnostic"]["code"] = numeric["diagnostic"]
    forged["refusing_event"]["reason"] = numeric["diagnostic"]
    _assert_reidentified_audit_refuses(checked, members, forged)
