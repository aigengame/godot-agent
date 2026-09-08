"""A bounded priority protocol computes pending actions through the public path."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import AdmittedRir, admit_rir
from priority_protocol_support import (
    A,
    RESOLUTION_TIME,
    authorities,
    source,
    specification,
)
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root
from test_current_namespace_public import _PublicCandidate, _members


@dataclass(frozen=True)
class _BuiltProtocol:
    candidate: _PublicCandidate
    context: AdmittedAuthorityContext
    program: AdmittedRir
    rir: dict[str, Any]
    rir_path: str


@pytest.fixture(scope="module")
def protocol(tmp_path_factory) -> _BuiltProtocol:
    kernel, language, turn = authorities()
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    candidate = _PublicCandidate(
        tmp_path_factory.mktemp("priority-protocol"), authorities=(kernel, language)
    )
    candidate.write_source(source(turn))
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "build"),
        "--invocation-key",
        "a1" * 32,
    )
    members = _members(receipt)
    assert len(members) == 8
    rir = members["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    return _BuiltProtocol(candidate, context, program, rir, rir_path)


def _run(protocol: _BuiltProtocol, value, name: str, *, success=True):
    candidate = protocol.candidate
    path = candidate.directory / f"{name}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    checked_result = candidate.cli(
        "experiment", "check", str(path), "--rir", protocol.rir_path
    )
    assert checked_result["checked"] is True
    result = candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        protocol.rir_path,
        "--out",
        str(candidate.directory / name),
        "--invocation-key",
        hashlib.sha256(name.encode()).hexdigest(),
        success=success,
    )
    receipt = result if success else result["error"]["terminal_audit"]
    members = _members(receipt)
    checked = check_experiment_value(
        value, protocol.program, authority_context=protocol.context
    )
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, members)
    return result, members


def _state(event):
    return {row["name"]: row["value"] for row in event["state_after"]}


def _counter(actor: int, target: int):
    return {
        "counter": {
            "type": {"package": A, "id": "Counter"},
            "value": {"actor": actor, "target": target},
        }
    }


def _pending(state):
    return (
        state["root_id"],
        state["next_id"],
        state["ids"]["value"],
        [row["target"] for row in state["counters"]["value"]],
        state["priority"],
        state["passes"],
        state["window_open"],
        state["canceled_ids"]["value"],
        state["final_power"],
        state["status"]["value"],
    )


@pytest.mark.parametrize("variant", [False, True], ids=["counter-to-counter", "pass"])
def test_public_priority_computes_each_boundary_and_final_action(protocol, variant):
    value = specification(protocol.rir, variant)
    _, members = _run(protocol, value, f"priority-{variant}")
    trace = members["event-trace"]
    transitions = [row for row in trace["events"] if row["operation"] is not None]
    expected = [
        (1, 1, [], [], 1, 0, 1, [], 0, "pending"),
        (1, 2, [2], [1], 0, 0, 1, [], 0, "pending"),
    ]
    if variant:
        expected += [
            (1, 2, [2], [1], 1, 1, 1, [], 0, "pending"),
            (1, 2, [2], [1], 0, 2, 0, [], 0, "pending"),
            (1, 2, [2], [1], 0, 2, 0, [1], 0, "canceled"),
        ]
        expected_operations = ["open", "respond", "pass", "pass", "resolve"]
    else:
        expected += [
            (1, 3, [2, 3], [1, 2], 1, 0, 1, [], 0, "pending"),
            (1, 3, [2, 3], [1, 2], 0, 1, 1, [], 0, "pending"),
            (1, 3, [2, 3], [1, 2], 1, 2, 0, [], 0, "pending"),
            (1, 3, [2, 3], [1, 2], 1, 2, 0, [2], 7, "resolved"),
        ]
        expected_operations = ["open", "respond", "respond", "pass", "pass", "resolve"]
    assert [row["operation"] for row in transitions] == expected_operations
    assert [_pending(_state(row)) for row in transitions] == expected
    assert [row["ordering_key"]["logical_time"] for row in transitions] == [
        *range(len(transitions) - 1),
        RESOLUTION_TIME,
    ]
    # Inputs change authored choices; only actual Operations allocate IDs or write state.
    inputs = [
        row for row in trace["events"] if row["outcome"]["id"] == "input-admitted"
    ]
    assert len(inputs) == len(transitions) - 1
    assert all(row["state_before"] == row["state_after"] for row in inputs)
    assert {row["ordering_key"]["phase"] for row in inputs} == {"input"}
    assert {row["ordering_key"]["phase"] for row in transitions} == {"transition"}
    assert trace["events"][-1]["ordering_key"]["phase"] == "observation"
    assert all(row["schedules"] == [] for row in transitions[:-2])
    scheduled = transitions[-2]["schedules"]
    assert len(scheduled) == 1
    assert scheduled[0]["event_id"] == transitions[-1]["event_id"]
    assert scheduled[0]["ordering_key"] == transitions[-1]["ordering_key"]
    assert scheduled[0]["operation"] == {"package": A, "id": "resolve"}
    captured = {row["name"]: row["value"] for row in scheduled[0]["arguments"]}
    assert captured["ids"] == _state(transitions[-2])["ids"]
    assert captured["counters"] == _state(transitions[-2])["counters"]
    assert captured["status"]["value"] == "pending"
    assert transitions[-2]["outcome"] == {"id": "closed", "kind": "success"}
    assert all(row["cancellations"] == [] for row in transitions)
    assert members["metric-dataset"]["samples"][0]["value"] == (0 if variant else 7)
    assert members["evaluation-run"]["outcome"] == "accepted"
    ledgers = [
        row["continuation"]["resource_ledger"]
        for row in members["snapshot-series"]["snapshots"]
    ]
    assert ledgers[-1]["node_steps"] == (90 if variant else 127)
    assert max(row["event_steps"] for row in ledgers) == (28 if variant else 44)
    roots = {row["root_event_ref"]: row["event_id"] for row in trace["root_event_map"]}
    assert len(set(roots.values())) == len(roots)
    assert [roots[f"advance-{index}"] for index in range(len(transitions) - 1)] == [
        row["event_id"] for row in transitions[:-1]
    ]
    # Stable action IDs and the canonical Event identities survive a separate real run.
    _, repeated = _run(protocol, value, f"priority-{variant}-repeat")
    assert repeated["event-trace"] == trace
    assert (
        sum(
            row["arguments"][:2] == ("model", "build")
            for row in protocol.candidate.receipts
        )
        == 1
    )


@pytest.mark.parametrize(
    ("actor", "target", "outcome"),
    [(0, 1, "wrong-priority"), (1, 2, "unknown-target")],
    ids=["wrong-responder", "unknown-target"],
)
def test_public_priority_rejects_choice_without_allocating_pending_identity(
    protocol, actor, target, outcome
):
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("respond", _counter(actor, target)),
        ("respond", _counter(1, 1)),
        ("pass", {"actor": 0}),
        ("pass", {"actor": 1}),
    ]
    _, members = _run(
        protocol, specification(protocol.rir, True, choices=choices), outcome
    )
    transitions = [
        row for row in members["event-trace"]["events"] if row["operation"] is not None
    ]
    rejected = transitions[1]
    assert rejected["outcome"] == {"id": outcome, "kind": "gameplay-alternative"}
    assert rejected["state_before"] == rejected["state_after"]
    if outcome == "wrong-priority":
        assert rejected["calls"] == []
    else:
        assert len(rejected["calls"]) == 1
        assert rejected["calls"][0]["outcome"]["id"] == "unknown-target"
    assert _state(rejected)["next_id"] == 1
    assert _state(rejected)["ids"]["value"] == []
    assert _state(rejected)["counters"]["value"] == []
    assert _state(transitions[2])["ids"]["value"] == [2]
    assert _state(transitions[-1])["canceled_ids"]["value"] == [1]
    assert _state(transitions[-1])["final_power"] == 0


def test_public_priority_window_cannot_reopen_with_stale_pending_identities(protocol):
    value = specification(protocol.rir, True)
    scenario = value["scenarios"][0]
    scenario["event_plan"] += [
        {
            "kind": "external-input",
            "root_event_ref": "reopen-choice",
            "logical_time": 4,
            "priority": 0,
            "source_identity": "sha256:" + "a" * 64,
            "source_sequence": 4,
            "facts": [
                {
                    "target": {
                        "model": "example.priority-window",
                        "module": "main",
                        "name": "actor",
                    },
                    "value": 0,
                }
            ],
        },
        {
            "kind": "transition-invocation",
            "root_event_ref": "reopen",
            "logical_time": 4,
            "priority": 0,
            "entrypoint": "open",
            "payload": [],
        },
    ]
    _, members = _run(protocol, value, "reopen")
    reopened = [
        row for row in members["event-trace"]["events"] if row["operation"] == "open"
    ][-1]
    assert reopened["outcome"] == {"id": "already-used", "kind": "gameplay-alternative"}
    assert reopened["state_before"] == reopened["state_after"]
    assert len(reopened["calls"]) == 1
    assert reopened["calls"][0]["outcome"]["id"] == "already-used"
    assert _state(reopened)["ids"]["value"] == [2]
    assert _state(reopened)["window_open"] == 0


def test_public_priority_response_depth_refuses_before_allocating_a_fourth_action(
    protocol,
):
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("respond", _counter(1, 1)),
        ("respond", _counter(0, 2)),
        ("respond", _counter(1, 3)),
        ("pass", {"actor": 0}),
        ("pass", {"actor": 1}),
    ]
    result, members = _run(
        protocol,
        specification(protocol.rir, choices=choices),
        "over-depth",
        success=False,
    )
    assert result["error"]["stage"] == "runtime"
    assert (
        result["error"]["diagnostics"][0]["code"]
        == "runtime.structured_list_capacity_exceeded"
    )
    audit = members["runtime-terminal-audit"]
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
    assert audit["refusing_event"]["call_path"] == "respond/create-counter"
    assert audit["refusing_event"]["operation"] == "append-counter"
    last = {
        row["name"]: row["value"] for row in audit["last_snapshot_record"]["values"]
    }
    assert last["next_id"] == 3
    assert last["ids"]["value"] == [2, 3]
    assert last["canceled_ids"]["value"] == []
    assert last["final_power"] == 0
    assert not any(row["schedules"] for row in audit["committed_trace_prefix"])
    assert {
        row["operation"]
        for row in audit["committed_trace_prefix"]
        if row["operation"] is not None
    } == {"open", "respond"}


@pytest.mark.parametrize("mutation", ["callback", "fourth-phase", "unbounded-list"])
def test_public_priority_refuses_non_language_escape_hatches(tmp_path: Path, mutation):
    kernel, language, turn = authorities()
    owner = "game.action" if mutation == "unbounded-list" else "game.turn"
    package = next(
        row for row in language["language"]["packages"] if row["id"] == owner
    )
    entries = {
        row["authority_path"]: row["definitions"] for row in package["semantic_closure"]
    }
    if mutation == "unbounded-list":
        nominal = next(
            row for row in entries["language.nominal_types"] if row["id"] == "Counters"
        )
        del nominal["definition"]["maximum_length"]
    elif mutation == "callback":
        operation = next(
            row for row in entries["language.operations"] if row["id"] == "open"
        )
        operation["result"]["source"] = {"kind": "host-callback", "name": "execute"}
    else:
        operation = next(
            row for row in entries["language.operations"] if row["id"] == "pass"
        )
        operation["body"][-1]["body"][-1]["phase"] = "reaction"
    # Rebind every declared body probe and all content identities: failure must come
    # from the unsupported meaning, not a stale digest or stale expected body.
    vectors = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == owner
    )
    operations = {row["id"]: row for row in entries["language.operations"]}
    for vector in vectors["vector_definitions"]:
        selected = operations[vector["operation"]]
        for member in vector["probe"]["path"].split("."):
            selected = selected[member]
        vector["expect"] = selected
    _bind_package_vector_set(package, vectors)
    _reidentify_graph_root(language)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, language))
    candidate.write_source(source(turn))
    result = candidate.cli("model", "check", str(candidate.source), success=False)
    assert result["error"]["stage"] == "static"
    assert result["error"]["diagnostics"][0]["code"] == "kernel.vector_mismatch"
    diagnostic = result["error"]["diagnostics"][0]
    assert diagnostic["primary"]["pointer"].endswith(
        {
            "callback": "/result/source",
            "fourth-phase": "/members",
            "unbounded-list": "/typing",
        }[mutation]
    )


def test_action_owner_checks_target_without_a_turn_wrapper(protocol):
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("append-counter", _counter(1, 2)),
        ("respond", _counter(1, 1)),
        ("pass", {"actor": 0}),
        ("pass", {"actor": 1}),
    ]
    _, members = _run(
        protocol,
        specification(protocol.rir, True, choices=choices),
        "direct-invalid-target",
    )
    event = next(
        row
        for row in members["event-trace"]["events"]
        if row["operation"] == "append-counter"
    )
    assert event["outcome"] == {"id": "unknown-target", "kind": "gameplay-alternative"}
    assert event["state_before"] == event["state_after"]
    assert _state(event)["next_id"] == 1
    assert _state(event)["ids"]["value"] == []
    assert _state(event)["counters"]["value"] == []


def test_priority_passes_reset_after_each_counter_at_longest_choice_boundary(protocol):
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("pass", {"actor": 1}),
        ("respond", _counter(0, 1)),
        ("pass", {"actor": 1}),
        ("respond", _counter(0, 2)),
        ("pass", {"actor": 1}),
        ("pass", {"actor": 0}),
    ]
    _, members = _run(
        protocol, specification(protocol.rir, choices=choices), "longest-window"
    )
    events = [
        row for row in members["event-trace"]["events"] if row["operation"] is not None
    ]
    assert [row["ordering_key"]["logical_time"] for row in events] == list(range(8))
    assert [_state(row)["passes"] for row in events] == [0, 1, 0, 1, 0, 1, 2, 2]
    assert [_state(row)["priority"] for row in events] == [1, 0, 1, 0, 1, 0, 1, 1]
    assert not any(row["schedules"] for row in events[:-2])
    assert events[-2]["outcome"] == {"id": "closed", "kind": "success"}
    assert events[-2]["schedules"][0]["event_id"] == events[-1]["event_id"]
    final = _state(events[-1])
    assert final["ids"]["value"] == [2, 3]
    assert final["canceled_ids"]["value"] == [2]
    assert final["final_power"] == 7
    ledger = members["snapshot-series"]["snapshots"][-1]["continuation"][
        "resource_ledger"
    ]
    assert ledger["node_steps"] == 151
    assert (
        max(
            row["continuation"]["resource_ledger"]["event_steps"]
            for row in members["snapshot-series"]["snapshots"]
        )
        == 44
    )


def test_priority_close_after_declared_final_slot_refuses_backward_schedule(protocol):
    value = specification(protocol.rir)
    for event in value["scenarios"][0]["event_plan"]:
        if event["logical_time"] == 4:
            event["logical_time"] = RESOLUTION_TIME + 1
    result, members = _run(protocol, value, "late-close", success=False)
    assert result["error"]["stage"] == "runtime"
    assert result["error"]["diagnostics"][0]["code"] == "runtime.schedule_backward"
    audit = members["runtime-terminal-audit"]
    assert audit["refusing_event"]["operation"] == "pass"
    assert audit["refusing_event"]["call_path"] == "pass"
    assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
    last = {
        row["name"]: row["value"] for row in audit["last_snapshot_record"]["values"]
    }
    assert last["window_open"] == 1
    assert last["passes"] == 1
    assert last["ids"]["value"] == [2, 3]
    assert last["canceled_ids"]["value"] == []
    assert last["final_power"] == 0
    assert not any(row["schedules"] for row in audit["committed_trace_prefix"])


def test_action_owner_refuses_second_proposal_without_a_turn_wrapper(protocol):
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("propose", {"authored_power": 9}),
        ("respond", _counter(1, 1)),
        ("pass", {"actor": 0}),
        ("pass", {"actor": 1}),
    ]
    _, members = _run(
        protocol, specification(protocol.rir, True, choices=choices), "direct-reopen"
    )
    event = next(
        row for row in members["event-trace"]["events"] if row["operation"] == "propose"
    )
    assert event["outcome"] == {"id": "already-used", "kind": "gameplay-alternative"}
    assert event["state_before"] == event["state_after"]
    assert _state(event)["next_id"] == 1
    assert _state(event)["root_id"] == 1
    assert _state(event)["power"] == 7


def test_public_priority_refuses_an_actor_outside_the_two_responder_domain(protocol):
    value = specification(protocol.rir)
    actor = value["scenarios"][0]["event_plan"][0]["facts"][0]
    assert actor["target"]["name"] == "actor"
    actor["value"] = 2
    path = protocol.candidate.directory / "invalid-actor.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    result = protocol.candidate.cli(
        "experiment", "check", str(path), "--rir", protocol.rir_path, success=False
    )
    assert result["error"]["stage"] == "static"
    diagnostic = result["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.invalid_domain"
    assert diagnostic["primary"]["pointer"] == "/scenarios/0/event_plan/0/facts/0/value"
    assert "terminal_audit" not in result["error"]


def test_action_owner_refuses_a_counter_before_any_proposal_exists(protocol):
    choices = [
        ("append-counter", _counter(1, 0)),
        ("open", {"actor": 0, "authored_power": 7}),
        ("respond", _counter(1, 1)),
        ("pass", {"actor": 0}),
        ("pass", {"actor": 1}),
    ]
    _, members = _run(
        protocol,
        specification(protocol.rir, True, choices=choices),
        "counter-before-root",
    )
    event = next(
        row
        for row in members["event-trace"]["events"]
        if row["operation"] == "append-counter"
    )
    assert event["outcome"] == {"id": "unknown-target", "kind": "gameplay-alternative"}
    assert event["state_before"] == event["state_after"]
    assert _state(event)["root_id"] == 0
    assert _state(event)["next_id"] == 0
    assert _state(event)["ids"]["value"] == []
    assert _state(event)["counters"]["value"] == []


def test_same_depth_counter_target_changes_final_action_without_changing_rules(
    protocol,
):
    choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        ("respond", _counter(1, 1)),
        ("respond", _counter(0, 1)),
        ("pass", {"actor": 1}),
        ("pass", {"actor": 0}),
    ]
    _, members = _run(
        protocol,
        specification(protocol.rir, True, choices=choices),
        "same-depth-retarget",
    )
    events = [
        row for row in members["event-trace"]["events"] if row["operation"] is not None
    ]
    assert [row["operation"] for row in events] == [
        "open",
        "respond",
        "respond",
        "pass",
        "pass",
        "resolve",
    ]
    before_resolution = _state(events[-2])
    assert before_resolution["ids"]["value"] == [2, 3]
    assert [row["target"] for row in before_resolution["counters"]["value"]] == [1, 1]
    assert before_resolution["canceled_ids"]["value"] == []
    assert before_resolution["final_power"] == 0
    final = _state(events[-1])
    assert final["status"]["value"] == "canceled"
    assert final["canceled_ids"]["value"] == [1, 1]
    assert final["final_power"] == 0
    assert members["metric-dataset"]["samples"][0]["value"] == 0
