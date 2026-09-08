"""Public bounded traversal preserves values, order, refusal and actual charges."""

from copy import deepcopy
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
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root
from test_current_namespace_public import _PublicCandidate, _members


_EXAMPLE = Path(__file__).parents[1] / "examples/schema2/bounded-fold"
_OWNER = "standard.conformance.structured"
_LIST = {"package": _OWNER, "id": "IntList4"}
_MAX = (1 << 63) - 1


def _source() -> dict[str, Any]:
    return json.loads((_EXAMPLE / "model-source.json").read_bytes())


def _specification(
    rir: dict[str, Any],
    items: list[int],
    *,
    count: int = 2,
    order: int = 1234,
    initial: list[int] | None = None,
) -> dict[str, Any]:
    values = {
        "items": {"type": _LIST, "value": items},
        "selected_items": {"type": _LIST, "value": initial or []},
        "selected_count": 0,
        "ordered_value": 0,
    }
    return {
        "schema_version": "2.0.0",
        "id": "example.bounded-fold",
        "model": {"rir_semantic_identity": rir["semantic_identity"]},
        "runtime": {
            "profile": "standard.exact-int64-event-v1",
            "required_evaluator": {
                "operation_kinds": ["event-program", "pure-expression"],
                "instruction_nodes": [
                    "add",
                    "constant",
                    "fold",
                    "if",
                    "less-than",
                    "list-append",
                    "multiply",
                    "write-state",
                ],
                "effects": ["event.commit", "metric.observe", "snapshot.commit"],
                "numeric_policies": ["exact-int64"],
                "rng_algorithms": ["splitmix64-v1"],
                "runtime_profiles": ["standard.exact-int64-event-v1"],
            },
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 20260907},
        "scenarios": [
            {
                "id": "fold-once",
                "event_plan": [
                    {
                        "kind": "transition-invocation",
                        "root_event_ref": "fold-once",
                        "logical_time": 0,
                        "priority": 0,
                        "entrypoint": "fold",
                        "payload": [],
                    }
                ],
                "assignments": [
                    {
                        "target": {
                            "model": "example.bounded-fold",
                            "module": "fold",
                            "name": name,
                        },
                        "value": value,
                    }
                    for name, value in values.items()
                ],
                "named_streams": [],
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            {
                "id": name,
                "kind": "scalar",
                "unit": "1",
                "dimensions": [],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": name,
                },
                "target": {"minimum": expected, "maximum": expected},
            }
            for name, expected in (("selected_count", count), ("ordered_value", order))
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }


def _build(candidate: _PublicCandidate):
    candidate.write_source(_source())
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "build"),
        "--invocation-key",
        "01" * 32,
    )
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    return rir_path, _members(receipt)["rir-semantic-payload"]


def _check(candidate: _PublicCandidate, rir_path: str, specification, *, success=True):
    path = candidate.directory / "experiment.json"
    path.write_text(json.dumps(specification), encoding="utf-8")
    result = candidate.cli(
        "experiment", "check", str(path), "--rir", rir_path, success=success
    )
    if success:
        assert result["checked"] is True
    return path, result


def _run(candidate: _PublicCandidate, rir_path: str, path: Path, *, success=True):
    return candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        rir_path,
        "--out",
        str(candidate.directory / "run"),
        "--invocation-key",
        "02" * 32,
        success=success,
    )


def _admit_artifacts(candidate, rir, specification, members):
    context = admit_authority_context(candidate.kernel, candidate.ldb)
    assert isinstance(context, AdmittedAuthorityContext), context
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, members)


@pytest.mark.parametrize(
    ("items", "selected", "count", "order", "steps"),
    [
        ([], [], 0, 0, 8),
        ([1], [1], 1, 1, 19),
        ([1, 2, 3, 4], [1, 2], 2, 1234, 46),
        ([1, 2, 3, 5], [1, 2], 2, 1235, 46),
        ([4, 3, 2, 1], [2, 1], 2, 4321, 46),
        ([3, 4], [], 0, 34, 24),
        ([1, 2, 1, 2], [1, 2, 1, 2], 4, 1212, 52),
    ],
    ids=[
        "empty",
        "singleton",
        "capacity",
        "later-item",
        "reversed",
        "rejected",
        "duplicates",
    ],
)
def test_public_fold_executes_ordered_input_and_admits_artifacts(
    tmp_path: Path, items, selected, count, order, steps
):
    candidate = _PublicCandidate(tmp_path, authorities=mutable_authorities())
    rir_path, rir = _build(candidate)
    specification = _specification(rir, items, count=count, order=order)
    if items == [1, 2, 3, 4]:
        maintained = json.loads((_EXAMPLE / "experiment.json").read_bytes())
        assert maintained == specification
        specification = maintained
    path, _ = _check(candidate, rir_path, specification)
    receipt = _run(candidate, rir_path, path)
    members = _members(receipt)
    _admit_artifacts(candidate, rir, specification, members)
    events = [
        row for row in members["event-trace"]["events"] if row["observation"] is None
    ]
    assert len(events) == 1
    event = events[0]
    assert event["outcome"]["id"] == "folded"
    assert event["calls"] == []  # Pure steps do not fabricate Event outcomes.
    assert {row["name"]: row["value"] for row in event["state_after"]} == {
        "selected_items": {"type": _LIST, "value": selected},
        "selected_count": count,
        "ordered_value": order,
    }
    snapshots = members["snapshot-series"]["snapshots"]
    assert snapshots[-1]["continuation"]["resource_ledger"]["node_steps"] == steps
    assert {
        row["metric"]: row["value"] for row in members["metric-dataset"]["samples"]
    } == {"selected_count": count, "ordered_value": order}


@pytest.mark.parametrize("change", ["over-capacity", "wrong-nominal", "wrong-item"])
def test_public_fold_refuses_invalid_authored_input_before_execution(
    tmp_path: Path, change
):
    candidate = _PublicCandidate(tmp_path, authorities=mutable_authorities())
    rir_path, rir = _build(candidate)
    specification = _specification(rir, [1, 2, 3, 4])
    supplied = specification["scenarios"][0]["assignments"][0]["value"]
    if change == "over-capacity":
        supplied["value"].append(5)
    elif change == "wrong-nominal":
        supplied["type"] = {"package": _OWNER, "id": "SelectionState"}
        supplied["value"] = {
            "candidates": [],
            "results": [],
            "selected": {"key": "candidate_a"},
        }
    else:
        supplied["value"][2] = True
    _path, result = _check(candidate, rir_path, specification, success=False)
    error = result["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == "language.structured_value_type_mismatch"
    assert "terminal_audit" not in error
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/scenarios/0/assignments/0/value/value/2"
        if change == "wrong-item"
        else "/scenarios/0/assignments/0/value/value"
    )
    assert not (tmp_path / "run").exists()


def _nonempty_accumulator_authorities():
    kernel, ldb = mutable_authorities()
    package = next(row for row in ldb["language"]["packages"] if row["id"] == _OWNER)
    operation = next(
        row
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "bounded-fold-v1"
    )
    operation["body"][2]["initial"] = "selected_items"
    vectors = next(
        row
        for row in ldb.package_conformance_vector_sets
        if row["package_id"] == _OWNER
    )
    next(
        row
        for row in vectors["vector_definitions"]
        if row["id"] == "bounded-fold.bounded-fold-v1.body"
    )["expect"] = deepcopy(operation["body"])
    _bind_package_vector_set(package, vectors, kernel=kernel)
    _reidentify_graph_root(ldb)
    return kernel, ldb


@pytest.mark.parametrize("cause", ["overflow", "eager-unselected-capacity"])
def test_public_fold_first_refusal_preserves_atomic_state_and_admits_audit(
    tmp_path: Path, cause
):
    eager = cause == "eager-unselected-capacity"
    authorities = (
        _nonempty_accumulator_authorities() if eager else mutable_authorities()
    )
    candidate = _PublicCandidate(tmp_path, authorities=authorities)
    rir_path, rir = _build(candidate)
    initial = [1, 2, 3, 4] if eager else []
    specification = _specification(rir, [9] if eager else [_MAX, 1], initial=initial)
    path, _ = _check(candidate, rir_path, specification)
    result = _run(candidate, rir_path, path, success=False)
    error = result["error"]
    assert error["stage"] == "runtime"
    assert error["diagnostics"][0]["code"] == (
        "runtime.structured_list_capacity_exceeded"
        if eager
        else "runtime.numeric_overflow"
    )
    members = _members(error["terminal_audit"])
    _admit_artifacts(candidate, rir, specification, members)
    audit = members["runtime-terminal-audit"]
    assert audit["committed_trace_prefix"] == []
    assert {
        row["name"]: row["value"] for row in audit["last_snapshot_record"]["values"]
    } == {
        "selected_items": {"type": _LIST, "value": initial},
        "selected_count": 0,
        "ordered_value": 0,
    }
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
    assert audit["budget_counters"]["node_steps"] == (6 if eager else 23)
    refusing = audit["refusing_event"]
    assert refusing["call_path"] == (
        "fold/filter-items/@0" if eager else "fold/ordered-items/@1"
    )
    assert refusing["instruction_index"] == 1
    assert refusing["call_site_identity"] is None
    assert refusing["attempted_calls"] == []


def _capacity_authorities(capacity: int):
    kernel, ldb = mutable_authorities()
    resources = deepcopy(ldb["resources"])
    profiles = deepcopy(ldb["language"]["runtime_profiles"])
    package = next(row for row in ldb["language"]["packages"] if row["id"] == _OWNER)
    nominal = next(
        row
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.nominal_types"
        for row in closure["definitions"]
        if row["id"] == "IntList4"
    )
    nominal["definition"]["maximum_length"] = capacity
    operation = next(
        row
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "bounded-fold-v1"
    )
    operation["resource_bounds"]["max_steps"] = 8 + 11 * capacity
    vectors = next(
        row
        for row in ldb.package_conformance_vector_sets
        if row["package_id"] == _OWNER
    )
    next(
        row
        for row in vectors["vector_definitions"]
        if row["id"] == "bounded-fold.bounded-fold-v1.resource-bound"
    )["expect"] = 8 + 11 * capacity
    _bind_package_vector_set(package, vectors, kernel=kernel)
    _reidentify_graph_root(ldb)
    assert ldb["resources"] == resources
    assert ldb["language"]["runtime_profiles"] == profiles
    return kernel, ldb


@pytest.mark.parametrize("capacity", [22, 23])
def test_public_fold_respects_event_budget_without_raising_system_limits(
    tmp_path: Path, capacity: int
):
    candidate = _PublicCandidate(tmp_path, authorities=_capacity_authorities(capacity))
    rir_path, rir = _build(candidate)
    specification = _specification(rir, [0] * capacity, count=capacity, order=0)
    path, _ = _check(candidate, rir_path, specification)
    result = _run(candidate, rir_path, path, success=capacity == 22)
    if capacity == 22:
        members = _members(result)
        _admit_artifacts(candidate, rir, specification, members)
        snapshot = members["snapshot-series"]["snapshots"][-1]
        assert snapshot["continuation"]["resource_ledger"]["node_steps"] == 250
        assert {row["name"]: row["value"] for row in snapshot["values"]} == {
            "selected_items": {"type": _LIST, "value": [0] * capacity},
            "selected_count": capacity,
            "ordered_value": 0,
        }
        return
    error = result["error"]
    assert error["stage"] == "runtime"
    assert error["diagnostics"][0]["code"] == "runtime.step_limit_exceeded"
    members = _members(error["terminal_audit"])
    _admit_artifacts(candidate, rir, specification, members)
    audit = members["runtime-terminal-audit"]
    assert audit["committed_trace_prefix"] == []
    assert audit["budget_counters"]["event_steps"] == 257
    assert audit["budget_counters"]["node_steps"] == 257
    assert audit["refusing_event"]["call_path"] == "fold/ordered-items/@22"
    assert audit["refusing_event"]["instruction_index"] == 1
    assert audit["refusing_event"]["call_site_identity"] is None
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]


def test_public_fold_composes_mapping_and_filtering_without_a_new_primitive(
    tmp_path: Path,
):
    kernel, ldb = mutable_authorities()
    package = next(row for row in ldb["language"]["packages"] if row["id"] == _OWNER)
    operations = {
        row["id"]: row
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
    }
    step = operations["bounded.filter-step"]
    step["body"][1]["item"] = "mapped"
    step["body"][:0] = [
        {"node": "constant", "target": "factor", "literal": 2},
        {"node": "multiply", "target": "mapped", "left": "item", "right": "factor"},
    ]
    step["refusals"].append("runtime.reason.numeric-overflow")
    step["resource_bounds"]["max_steps"] = 5
    operations["bounded-fold-v1"]["resource_bounds"]["max_steps"] = 60
    vectors = next(
        row
        for row in ldb.package_conformance_vector_sets
        if row["package_id"] == _OWNER
    )
    replacements = {
        "bounded-fold.bounded.filter-step.body": deepcopy(step["body"]),
        "bounded-fold.bounded.filter-step.resource-bound": 5,
        "bounded-fold.bounded-fold-v1.resource-bound": 60,
    }
    for vector in vectors["vector_definitions"]:
        if vector["id"] in replacements:
            vector["expect"] = replacements[vector["id"]]
    _bind_package_vector_set(package, vectors, kernel=kernel)
    _reidentify_graph_root(ldb)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, ldb))
    rir_path, rir = _build(candidate)
    specification = _specification(rir, [1, 2, 3, 4])
    path, _ = _check(candidate, rir_path, specification)
    members = _members(_run(candidate, rir_path, path))
    _admit_artifacts(candidate, rir, specification, members)
    event = next(
        row for row in members["event-trace"]["events"] if row["observation"] is None
    )
    assert event["calls"] == []
    assert {row["name"]: row["value"] for row in event["state_after"]} == {
        "selected_items": {"type": _LIST, "value": [2, 4]},
        "selected_count": 2,
        "ordered_value": 1234,
    }
    snapshot = members["snapshot-series"]["snapshots"][-1]
    assert snapshot["continuation"]["resource_ledger"]["node_steps"] == 54
    assert {
        row["metric"]: row["value"] for row in members["metric-dataset"]["samples"]
    } == {"selected_count": 2, "ordered_value": 1234}
