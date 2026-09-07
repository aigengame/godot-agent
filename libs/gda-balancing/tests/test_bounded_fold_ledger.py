"""Terminal counters come from checked inputs and genuine completed work."""

from copy import deepcopy
import json
from typing import Any

import pytest

from gda_balancing.domain.authority.context import admit_authority_context
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
from gda_balancing.domain.runtime.projections import (
    projected_runtime_identity,
    scheduler_contract,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from schema2_authority_support import mutable_authorities
from test_bounded_fold_public import _source, _specification
from test_bounded_fold_replay import _fold_case
from test_public_formula_runtime_seam import _EXAMPLE, _limited_context
from test_schema2_model_cli import _reidentify_language_bundle


def _execute(context, source, specification):
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    rir = compile_checked_model(model)["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    checked = check_experiment_value(
        specification(rir), program, authority_context=context
    )
    assert isinstance(checked, CheckedExperiment), checked
    prepared = prepare_experiment(checked)
    assert isinstance(prepared, PreparedExperiment), prepared
    return checked, prepared, evaluate_prepared_experiment(prepared)


def _terminal(context, source, specification):
    checked, prepared, outcome = _execute(context, source, specification)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    members = {
        name: deepcopy(member.value)
        for name, member in runtime_terminal_audit_members(
            checked,
            outcome,
            evaluator=prepared.evaluator,
            resolved_runtime=prepared.resolved_runtime,
        ).items()
    }
    assert validate_experiment_artifact_set(checked, members)
    return checked, members


def _reseal_snapshot(checked, audit):
    snapshot = audit["last_snapshot_record"]
    old = snapshot["snapshot_identity"]
    new = projected_runtime_identity(
        scheduler_contract(checked)["snapshot_identity"],
        {
            "experiment_identity": checked.content_identity,
            "scenario_id": audit["scenario"],
            **{
                name: snapshot[name]
                for name in (
                    "index",
                    "logical_time",
                    "event_id",
                    "values",
                    "continuation",
                )
            },
        },
    )

    def replace(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return new if value == old else value

    return replace(audit)


def _assert_refuses(checked, members, audit):
    audit = _reseal_snapshot(checked, audit)
    contract = checked.output_contracts["runtime-terminal-audit"]
    audit = contract.identify(
        {
            key: value
            for key, value in audit.items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
    )
    assert contract.verify(audit)
    assert validate_experiment_member(checked, "runtime-terminal-audit", audit)
    assert not validate_experiment_artifact_set(
        checked, {**members, "runtime-terminal-audit": audit}
    )


@pytest.fixture(scope="module")
def no_prefix_overflow():
    checked, members = _fold_case()
    audit = members["runtime-terminal-audit"]
    assert audit["committed_trace_prefix"] == []
    assert audit["last_snapshot_record"]["continuation"]["resource_ledger"] == {
        "node_steps": 0,
        "event_steps": 0,
        "queue_events": 1,
        "total_events": 1,
    }
    assert audit["budget_counters"]["node_steps"] == 23
    assert audit["refusing_event"]["call_path"] == "fold/ordered-items/@1"
    return checked, members


@pytest.mark.parametrize("counter", ["node_steps", "event_steps"])
def test_initial_snapshot_cannot_author_its_starting_counter(
    no_prefix_overflow, counter
):
    checked, members = no_prefix_overflow
    audit = deepcopy(members["runtime-terminal-audit"])
    audit["last_snapshot_record"]["continuation"]["resource_ledger"][counter] = 100
    if counter == "node_steps":
        audit["budget_counters"][counter] += 100
    _assert_refuses(checked, members, audit)


def test_forged_ledger_cannot_replace_numeric_overflow_with_earlier_budget_refusal(
    no_prefix_overflow,
):
    checked, members = no_prefix_overflow
    audit = deepcopy(members["runtime-terminal-audit"])
    audit["last_snapshot_record"]["continuation"]["resource_ledger"]["node_steps"] = (
        4093
    )
    audit["budget_counters"].update(node_steps=4097, event_steps=4)
    reason = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
        if row["definition"].get("signal") == "step-limit"
    )
    audit["diagnostic"]["code"] = reason["diagnostic"]
    audit["refusing_event"].update(
        operation="bounded.filter-step",
        call_path="fold/filter-items/@0",
        instruction_index=0,
        reason=reason["diagnostic"],
    )
    _assert_refuses(checked, members, audit)


def _fold_prefix(rir, *, second_scenario):
    specification = _specification(rir, [1, 2, 3, 4])
    if second_scenario:
        second = _specification(rir, [(1 << 63) - 1, 1])["scenarios"][0]
        second["id"] = "second"
        specification["scenarios"].append(second)
    else:
        scenario = specification["scenarios"][0]
        second = deepcopy(scenario["event_plan"][0])
        second.update(root_event_ref="second", logical_time=1)
        scenario["event_plan"].append(second)
        scenario["terminal_condition"]["maximum"] = 2
    return specification


@pytest.mark.parametrize(
    ("second_scenario", "prefix_count", "snapshot_event", "attempted", "event_steps"),
    [(False, 1, 46, 61, 15), (True, 3, 0, 69, 23)],
    ids=["completed-event", "completed-scenario"],
)
def test_real_completed_fold_work_is_required_in_the_next_starting_ledger(
    second_scenario,
    prefix_count,
    snapshot_event,
    attempted,
    event_steps,
):
    context = (
        admit_authority_context(*mutable_authorities())
        if second_scenario
        else _limited_context(60)
    )
    checked, members = _terminal(
        context,
        _source(),
        lambda rir: _fold_prefix(rir, second_scenario=second_scenario),
    )
    original = members["runtime-terminal-audit"]
    assert len(original["committed_trace_prefix"]) == prefix_count
    assert original["last_snapshot_record"]["continuation"]["resource_ledger"] == {
        "event_steps": snapshot_event,
        "node_steps": 46,
        "queue_events": 1,
        "total_events": 1 if second_scenario else 2,
    }
    assert original["budget_counters"]["node_steps"] == attempted
    assert original["budget_counters"]["event_steps"] == event_steps
    for change in [-46, 100]:
        audit = deepcopy(original)
        audit["last_snapshot_record"]["continuation"]["resource_ledger"][
            "node_steps"
        ] += change
        audit["budget_counters"]["node_steps"] += change
        _assert_refuses(checked, members, audit)


def _progression(rir, *, second_scenario=False):
    specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    specification["model"] = {"rir_semantic_identity": rir["semantic_identity"]}
    if second_scenario:
        scenario = specification["scenarios"][0]
        scenario["terminal_condition"] = {"kind": "event-count", "maximum": 1}
        second = deepcopy(scenario)
        second["id"] = "second"
        specification["scenarios"].append(second)
    return specification


@pytest.mark.parametrize(
    (
        "limit",
        "committed",
        "snapshot_node",
        "snapshot_event",
        "attempted",
        "event_steps",
    ),
    [
        (5, 0, 3, 0, 6, 0),
        (20, 1, 19, 13, 22, 13),
        (24, 1, 19, 13, 25, 0),
        (40, 3, 33, 1, 41, 2),
    ],
    ids=[
        "initialization-before-event",
        "observation-refusal",
        "observation-before-next-event",
        "observation-before-operation",
    ],
)
def test_formula_work_separates_snapshot_charge_from_the_next_execution_total(
    limit,
    committed,
    snapshot_node,
    snapshot_event,
    attempted,
    event_steps,
):
    checked, members = _terminal(
        _limited_context(limit),
        json.loads((_EXAMPLE / "model-source.json").read_bytes()),
        _progression,
    )
    original = members["runtime-terminal-audit"]
    assert len(original["committed_trace_prefix"]) == committed
    ledger = original["last_snapshot_record"]["continuation"]["resource_ledger"]
    assert (ledger["node_steps"], ledger["event_steps"]) == (
        snapshot_node,
        snapshot_event,
    )
    assert (
        original["budget_counters"]["node_steps"],
        original["budget_counters"]["event_steps"],
    ) == (attempted, event_steps)
    for change in [-3, 100]:
        audit = deepcopy(original)
        audit["last_snapshot_record"]["continuation"]["resource_ledger"][
            "node_steps"
        ] += change
        audit["budget_counters"]["node_steps"] += change
        _assert_refuses(checked, members, audit)
    if limit in {24, 40}:
        # A successful observation costs three after the recorded Snapshot.
        # Omitting that genuine work must fail even with an unchanged Snapshot.
        audit = deepcopy(original)
        audit["budget_counters"]["node_steps"] -= 3
        _assert_refuses(checked, members, audit)


@pytest.mark.parametrize(
    ("limit", "second_scenario", "pointer"),
    [
        (2, False, "/scenarios/0/assignments"),
        (24, True, "/scenarios/1/assignments"),
    ],
)
def test_initialization_refuses_before_a_terminal_audit_can_claim_a_snapshot(
    limit,
    second_scenario,
    pointer,
):
    _checked, _prepared, outcome = _execute(
        _limited_context(limit),
        json.loads((_EXAMPLE / "model-source.json").read_bytes()),
        lambda rir: _progression(rir, second_scenario=second_scenario),
    )
    assert isinstance(outcome, Schema2RefusalReport), outcome
    assert outcome.variant == "pre-event"
    assert outcome.stage == "runtime"
    assert outcome.terminal_audit is None
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.code == "runtime.step_limit_exceeded"
    assert getattr(diagnostic.primary, "subject", None) == "formula-evaluation-site"
    assert any(
        getattr(location, "pointer", None) == pointer for location in diagnostic.related
    )


def test_later_scenario_initialization_adds_to_the_run_total():
    checked, members = _terminal(
        _limited_context(25),
        json.loads((_EXAMPLE / "model-source.json").read_bytes()),
        lambda rir: _progression(rir, second_scenario=True),
    )
    audit = members["runtime-terminal-audit"]
    assert audit["scenario"] == "second"
    assert len(audit["committed_trace_prefix"]) == 4  # One Event and three metrics.
    ledger = audit["last_snapshot_record"]["continuation"]["resource_ledger"]
    assert (ledger["node_steps"], ledger["event_steps"]) == (25, 0)
    assert audit["budget_counters"]["node_steps"] == 28
    changed = deepcopy(audit)
    changed["last_snapshot_record"]["continuation"]["resource_ledger"]["node_steps"] = 3
    changed["budget_counters"]["node_steps"] = 6
    _assert_refuses(checked, members, changed)


def test_refusal_cannot_skip_an_earlier_pending_root():
    def specification(rir):
        value = _fold_prefix(rir, second_scenario=False)
        next(
            row
            for row in value["scenarios"][0]["assignments"]
            if row["target"]["name"] == "items"
        )["value"]["value"] = [(1 << 63) - 1, 1]
        return value

    checked, members = _terminal(
        admit_authority_context(*mutable_authorities()), _source(), specification
    )
    audit = deepcopy(members["runtime-terminal-audit"])
    assert audit["committed_trace_prefix"] == []
    first, later = audit["event_catalog_prefix"]
    assert audit["refusing_event"]["event_id"] == first["event_id"]
    assert audit["budget_counters"]["node_steps"] == 23
    audit["refusing_event"].update(
        event_id=later["event_id"],
        event_spec=later["event_spec"],
        ordering_key=later["ordering_key"],
    )
    audit["budget_counters"]["logical_time"] = 1
    _assert_refuses(checked, members, audit)


def _resource_context(**bounds):
    kernel, bundle = mutable_authorities()
    profile = next(
        row
        for row in bundle["language"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    profile["resource_bounds"].update(bounds)
    _reidentify_language_bundle(bundle)
    return admit_authority_context(kernel, bundle)


def test_metric_event_refusal_includes_successful_final_observation_formula():
    checked, members = _terminal(
        _resource_context(max_total_events=4),
        json.loads((_EXAMPLE / "model-source.json").read_bytes()),
        _progression,
    )
    original = members["runtime-terminal-audit"]
    assert len(original["committed_trace_prefix"]) == 4
    assert original["refusing_event"]["event_spec"]["kind"] == "observation"
    ledger = original["last_snapshot_record"]["continuation"]["resource_ledger"]
    assert (ledger["node_steps"], ledger["event_steps"]) == (41, 2)
    assert original["budget_counters"]["node_steps"] == 44
    assert original["budget_counters"]["event_steps"] == 0
    assert original["refusing_event"]["reason"] == "runtime.event_limit_exceeded"
    audit = deepcopy(original)
    audit["budget_counters"]["node_steps"] = 41
    _assert_refuses(checked, members, audit)

    step_reason = next(
        row["definition"]
        for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
        if row["definition"].get("signal") == "step-limit"
    )
    audit = deepcopy(original)
    audit["diagnostic"]["code"] = step_reason["diagnostic"]
    audit["refusing_event"]["reason"] = step_reason["diagnostic"]
    _assert_refuses(checked, members, audit)

    # These all retain a genuine exhausted total-Event budget. Integrity and
    # member shape alone cannot establish the reason or observation location.
    identity = "sha256:" + "f" * 64
    for field, value in [
        ("operation", "forged-operation"),
        ("call_path", "forged-observation"),
        ("entrypoint", {"id": "forged-observation", "identity": identity}),
        (
            "entrypoint",
            {**original["refusing_event"]["entrypoint"], "identity": identity},
        ),
        ("call_site_identity", identity),
        ("evaluation_site_identity", identity),
        ("instruction_index", 0),
        (
            "attempted_calls",
            [
                {
                    "site": "forged-call",
                    "call_site_identity": identity,
                    "operation": {
                        "package": "game.effect",
                        "id": "apply-snapshot-periodic-v1",
                    },
                    "outcome": {"id": "invented", "identity": identity},
                    "arguments": [],
                    "result_identity": identity,
                }
            ],
        ),
    ]:
        audit = deepcopy(original)
        audit["refusing_event"][field] = value
        _assert_refuses(checked, members, audit)


def _terminal_pending_candidate():
    context = _resource_context(max_node_steps=60, max_total_events=2)

    def specification(rir, maximum):
        value = _fold_prefix(rir, second_scenario=False)
        value["scenarios"][0]["terminal_condition"]["maximum"] = maximum
        return value

    _control_checked, control_members = _terminal(
        context, _source(), lambda rir: specification(rir, 2)
    )
    checked, members = _terminal(context, _source(), lambda rir: specification(rir, 1))
    audit = deepcopy(members["runtime-terminal-audit"])
    assert len(audit["committed_trace_prefix"]) == 1
    assert audit["refusing_event"]["event_spec"]["kind"] == "observation"
    assert audit["refusing_event"]["reason"] == "runtime.event_limit_exceeded"
    assert audit["budget_counters"]["node_steps"] == 46
    later = audit["event_catalog_prefix"][1]
    # The same body's next genuine execution would exhaust 60 at step 61.
    # Under this checked terminal condition that pending Event cannot dispatch.
    control = control_members["runtime-terminal-audit"]
    assert control["budget_counters"]["node_steps"] == 61
    assert control["budget_counters"]["event_steps"] == 15
    audit["refusing_event"] = deepcopy(control["refusing_event"])
    audit["refusing_event"].update(
        event_id=later["event_id"],
        event_spec=later["event_spec"],
        ordering_key=later["ordering_key"],
        snapshot_before_identity=audit["last_snapshot_identity"],
    )
    audit["diagnostic"]["code"] = control["diagnostic"]["code"]
    audit["budget_counters"] = deepcopy(control["budget_counters"])
    return checked, members, audit


def test_pending_event_cannot_dispatch_after_the_terminal_boundary():
    checked, members, audit = _terminal_pending_candidate()
    _assert_refuses(checked, members, audit)


@pytest.mark.parametrize(
    ("limit", "kind", "committed", "phase"),
    [
        (5, "transition-invocation", 0, "event"),
        (20, "transition-invocation", 1, "observation"),
        (24, "scheduled-transition", 1, "event"),
        (28, "scheduled-transition", 2, "observation"),
    ],
)
def test_formula_refusal_binds_actual_root_dispatch_and_call_prefix(
    limit, kind, committed, phase
):
    checked, members = _terminal(
        _limited_context(limit),
        json.loads((_EXAMPLE / "model-source.json").read_bytes()),
        _progression,
    )
    original = members["runtime-terminal-audit"]
    assert len(original["committed_trace_prefix"]) == committed
    refusing = original["refusing_event"]
    assert refusing["event_spec"]["kind"] == kind
    expected_calls = (
        original["committed_trace_prefix"][-1]["calls"]
        if phase == "observation"
        else []
    )
    assert refusing["attempted_calls"] == expected_calls
    identity = "sha256:" + "f" * 64
    for field, value in [
        ("operation", "forged-operation"),
        ("call_path", "forged-root"),
        ("entrypoint", {"id": "forged-entrypoint", "identity": identity}),
        (
            "attempted_calls",
            [
                {
                    "site": "forged-call",
                    "call_site_identity": identity,
                    "operation": {
                        "package": "game.effect",
                        "id": "apply-snapshot-periodic-v1",
                    },
                    "outcome": {"id": "invented", "identity": identity},
                    "arguments": [],
                    "result_identity": identity,
                }
            ],
        ),
    ]:
        audit = deepcopy(original)
        audit["refusing_event"][field] = value
        _assert_refuses(checked, members, audit)


def test_observation_formula_refusal_preserves_genuine_nonempty_operation_calls(
    tmp_path,
):
    from test_public_formula_runtime_seam import _maximum_source, _maximum_specification

    def specification(rir):
        path = tmp_path / "rir.json"
        path.write_text(json.dumps(rir))
        receipt = {
            "member_locators": [
                {"logical_name": "rir-semantic-payload", "locator": str(path)}
            ]
        }
        return _maximum_specification(receipt, 85)

    checked, members = _terminal(
        _limited_context(31), _maximum_source(1), specification
    )
    original = members["runtime-terminal-audit"]
    assert original["budget_counters"]["node_steps"] == 32
    assert len(original["committed_trace_prefix"]) == 1
    calls = original["committed_trace_prefix"][0]["calls"]
    assert calls
    assert original["refusing_event"]["attempted_calls"] == calls
    audit = deepcopy(original)
    audit["refusing_event"]["attempted_calls"] = []
    _assert_refuses(checked, members, audit)
