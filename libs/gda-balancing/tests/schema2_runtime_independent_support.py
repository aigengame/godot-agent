"""Finite independent Scenario execution and Runtime artifact consumption.

Execution reads selected RIR semantics. The independently checked source context
is used only to admit that RIR and to select input/output wire contracts.
"""

from copy import deepcopy
from pathlib import Path
import hashlib
import platform
from typing import Any

import jsonschema

from schema2_operation_execution_independent_support import (
    ReferenceEventFrame,
    _reference_fact_rows,
    reference_execute_event,
)
from test_schema2_model_lowerer_conformance import (
    ModelSourceContext,
    _reference_artifact,
    _reference_content_identity,
    _reference_semantic_artifacts,
)


class IndependentRuntimeUnsupported(ValueError):
    """This reference build refuses unsupported scope; not a language fault."""


def _coordinate(symbol):
    return tuple(symbol[key] for key in ("model", "module", "name"))


def _schema(context, name):
    return next(
        row["schema"]
        for row in context.language_bundle["language"]["artifact_wire_schemas"]
        if row["artifact_kind"] == name
    )


def _metric_identity(metric):
    members = (
        "id",
        "kind",
        "unit",
        "dimensions",
        "window",
        "aggregation",
        "replication",
        "missing",
        "censoring",
        "observation",
    )
    return _reference_content_identity(
        "metric-definition-v2", {name: metric[name] for name in members}
    )


def _build_identity():
    sources = []
    for name in (
        "schema2_runtime_independent_support.py",
        "schema2_operation_execution_independent_support.py",
        "test_schema2_model_lowerer_conformance.py",
    ):
        content = Path(__file__).with_name(name).read_bytes()
        sources.append(
            {"path": name, "content_sha256": hashlib.sha256(content).hexdigest()}
        )
    return _reference_content_identity("evaluator-build-v1", sources)


def _supported_shape(specification, rir):
    if len(specification["scenarios"]) != 1:
        raise IndependentRuntimeUnsupported("this checkpoint supports one Scenario")
    if rir["initialization_programs"] or rir["formula_bindings"]:
        raise IndependentRuntimeUnsupported(
            "Formula lifecycle execution is not implemented"
        )
    scenario = specification["scenarios"][0]
    if scenario["named_streams"]:
        raise IndependentRuntimeUnsupported(
            "Scenario RNG continuation is not implemented"
        )
    if any(
        event["kind"] != "transition-invocation" or event["payload"]
        for event in scenario["event_plan"]
    ):
        raise IndependentRuntimeUnsupported(
            "only transition roots without payload are implemented"
        )
    if scenario["terminal_condition"]["kind"] not in {"queue-drained", "event-count"}:
        raise IndependentRuntimeUnsupported("unsupported terminal condition")
    names = [row["resolved_symbol"]["name"] for row in rir["declarations"]]
    if len(names) != len(set(names)):
        raise IndependentRuntimeUnsupported(
            "ambiguous display names are not implemented"
        )
    for metric in specification["metrics"]:
        if not (
            metric["kind"] == "scalar"
            and metric["aggregation"] == "single"
            and metric["replication"] == {"unit": "scenario"}
            and metric["dimensions"] == []
            and metric["window"] == {"kind": "scenario", "name": "terminal-event"}
            and metric["observation"]["source"] == "snapshot"
            and metric["observation"]["name"] == "terminal"
            and metric["missing"] == "refuse"
            and metric["censoring"] == "none"
        ):
            raise IndependentRuntimeUnsupported("unsupported Metric projection")
    runtime = rir["selected_semantics"]["execution_laws"]["runtime_program"]
    allowed = {
        "integer-add",
        "integer-subtract",
        "integer-multiply",
        "integer-floor-divide",
        "typed-literal",
        "copy-value",
        "integer-compare",
        "select-value",
        "state-write",
        "invoke-operation",
        "bounded-pure-fold",
        "bounded-list-append",
    }
    # Capability names belong to this declared machine, not authored Operation IDs.
    operators = {row["id"]: row["semantics"]["operator"] for row in runtime["nodes"]}
    required = specification["runtime"]["required_evaluator"]
    missing = [
        node
        for node in required["instruction_nodes"]
        if operators.get(node) not in allowed
    ]
    if missing:
        raise IndependentRuntimeUnsupported(
            f"unimplemented instruction semantics: {missing}"
        )
    available = {
        "operation_kinds": ["event-program", "event-fragment", "pure-expression"],
        "instruction_nodes": sorted(
            node for node, operator in operators.items() if operator in allowed
        ),
        "effects": ["event.commit", "metric.observe", "snapshot.commit"],
        "numeric_policies": ["exact-int64"],
        "rng_algorithms": [runtime["named_rng"]["algorithm"]],
        "runtime_profiles": [specification["runtime"]["profile"]],
    }
    for member, values in required.items():
        if not set(values) <= set(available[member]):
            raise IndependentRuntimeUnsupported(
                f"unimplemented evaluator requirement: {member}"
            )
    return available


def reference_runtime_artifacts(
    context: ModelSourceContext, rir: dict[str, Any], specification: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Execute a supported Scenario independently, then identify its six members."""
    if rir != _reference_semantic_artifacts(context)["rir-semantic-payload"]:
        raise ValueError("RIR does not equal independent compilation")
    jsonschema.Draft202012Validator(
        _schema(context, "experiment-specification")
    ).validate(specification)
    if specification["model"] != {"rir_semantic_identity": rir["semantic_identity"]}:
        raise ValueError("Experiment selects a different semantic program")
    available = _supported_shape(specification, rir)
    semantic = rir["selected_semantics"]
    runtime = semantic["execution_laws"]["runtime_program"]
    scheduler = runtime["scheduler"]
    journal = scheduler["runtime_journal"]
    profile = next(
        row
        for row in semantic["runtime_profiles"]
        if row["id"] == specification["runtime"]["profile"]
    )
    bounds = profile["resource_bounds"]
    experiment_identity = _reference_content_identity(
        "experiment-specification-v2", specification
    )
    profile_domain = context.kernel["meta_format"]["runtime_profile_definition"][
        "domain"
    ]
    resolved_profile = _reference_artifact(
        context,
        "resolved-runtime-profile",
        {
            "experiment_identity": experiment_identity,
            "rir_semantic_identity": rir["semantic_identity"],
            "runtime_profile_definition_identity": _reference_content_identity(
                profile_domain, profile
            ),
            "runtime_profile": deepcopy(profile),
        },
    )
    binding = {
        "experiment_identity": experiment_identity,
        "resolved_runtime_profile_identity": resolved_profile["content_identity"],
    }
    scenario = specification["scenarios"][0]
    scenario_id = scenario["id"]
    identity_rule = scheduler["event_identity"]

    def order(event):
        result = []
        for rule in scheduler["ordering"]:
            value = event["ordering_key"][rule["member"]]
            if "rank" in rule:
                value = rule["rank"].index(value)
            result.append(-value if rule["direction"] == "descending" else value)
        return tuple(result)

    def identify_event(fields, projection):
        material = {
            "experiment_identity": experiment_identity,
            "scenario_id": scenario_id,
            **fields,
        }
        return _reference_content_identity(
            identity_rule["domain"], {key: material[key] for key in projection}
        )

    roots = []
    root_map = []
    for index, authored in enumerate(scenario["event_plan"]):
        ordering = {
            "logical_time": authored["logical_time"],
            "phase": scheduler["root_phases"][authored["kind"]],
            "priority": authored["priority"],
            "enqueue_sequence": index,
        }
        event_id = identify_event(
            {"root_event_ref": authored["root_event_ref"], **ordering},
            identity_rule["variants"]["root"],
        )
        roots.append(
            {
                "kind": authored["kind"],
                "event_id": event_id,
                "root_event_ref": authored["root_event_ref"],
                "entrypoint": authored["entrypoint"],
                "payload": deepcopy(authored["payload"]),
                "ordering_key": ordering,
                "zero_time_depth": 0,
            }
        )
        root_map.append(
            {
                "scenario": scenario_id,
                "root_event_ref": authored["root_event_ref"],
                "event_id": event_id,
            }
        )
    pending = sorted(roots, key=order)
    if not pending or len(pending) > bounds["max_queue_events"]:
        raise IndependentRuntimeUnsupported("empty root plan or queue budget refusal")
    if len(pending) + len(specification["metrics"]) > bounds["max_total_events"]:
        raise IndependentRuntimeUnsupported(
            "terminal-audit production is not implemented"
        )
    catalog = []
    events = []
    snapshots = []
    catalog_identity = _reference_content_identity(
        journal["event_catalog"]["domain"], []
    )
    trace_identity = _reference_content_identity(
        journal["committed_trace"]["domain"], []
    )
    root_map_identity = _reference_content_identity(
        journal["root_event_map"]["domain"], root_map
    )

    def catalog_event(event):
        nonlocal catalog_identity
        record = {
            "scenario": scenario_id,
            "event_id": event["event_id"],
            "kind": event["kind"],
            "ordering_key": deepcopy(event["ordering_key"]),
            "event_spec": deepcopy(event),
            "event_spec_identity": _reference_content_identity(
                journal["event_spec"]["domain"], event
            ),
        }
        catalog.append(record)
        catalog_identity = _reference_content_identity(
            journal["event_catalog"]["domain"],
            {"previous_identity": catalog_identity, "record": record},
        )

    for event in pending:
        catalog_event(event)
    declarations = {
        _coordinate(row["resolved_symbol"]): row for row in rir["declarations"]
    }
    state_keys = {key for key, row in declarations.items() if row["role"] == "state"}
    initializers = {}
    for entrypoint in rir["entrypoints"]:
        for row in entrypoint["scenario_input_contract"]["initializers"]:
            initializers[_coordinate(row["target"])] = deepcopy(row["value"])
    initializers.update(
        {
            _coordinate(row["target"]): deepcopy(row["value"])
            for row in scenario["assignments"]
        }
    )
    frame = ReferenceEventFrame(initializers, {}, {}, 0, {})
    next_sequence = len(roots)
    lifecycle = runtime["runtime_configuration"]["lifecycle_roles"]
    boundaries = runtime["step"]["boundary_roles"]

    def state_rows():
        return [
            {
                "name": declarations[key]["resolved_symbol"]["name"],
                "value": deepcopy(frame.values[key]),
            }
            for key in sorted(state_keys)
        ]

    def snapshot(event, event_steps, boundary, lifecycle_state, name):
        event_id = event["event_id"] if event else None
        logical_time = event["ordering_key"]["logical_time"] if event else None
        current = {
            "index": len(snapshots),
            "event_id": event_id,
            "logical_time": logical_time,
        }
        continuation = {
            "lifecycle_state": lifecycle_state,
            "step_boundary": boundary,
            "scenario_cursor": 0,
            "event_catalog": {
                "count": len(catalog),
                "prefix_identity": catalog_identity,
            },
            "pending_event_count": len(pending),
            "committed_trace": {
                "count": len(events),
                "prefix_identity": trace_identity,
            },
            "current_snapshot": current,
            "rng": [],
            "resource_ledger": {
                "event_steps": event_steps,
                "node_steps": frame.node_steps,
                "queue_events": len(pending),
                "total_events": len(catalog),
            },
            "next_enqueue_sequence": next_sequence,
            "root_event_map_identity": root_map_identity,
            "resolved_runtime_profile_identity": resolved_profile["content_identity"],
        }
        row = {
            **current,
            "name": name,
            "scenario": scenario_id,
            "values": state_rows(),
            "continuation": continuation,
        }
        fields = {
            "experiment_identity": experiment_identity,
            "scenario_id": scenario_id,
            **row,
        }
        contract = scheduler["snapshot_identity"]
        row["snapshot_identity"] = _reference_content_identity(
            contract["domain"], {key: fields[key] for key in contract["projection"]}
        )
        snapshots.append(row)
        return row["snapshot_identity"]

    def commit_event(event, charge, boundary, lifecycle_state, snapshot_name):
        nonlocal trace_identity
        events.append(event)
        trace_identity = _reference_content_identity(
            journal["committed_trace"]["domain"],
            {"previous_identity": trace_identity, "record": event},
        )
        event["snapshot_after_identity"] = snapshot(
            event, charge, boundary, lifecycle_state, snapshot_name
        )

    snapshot(
        None, 0, boundaries["initial"], lifecycle["ready"], f"{scenario_id}:initial"
    )
    operations = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in semantic["operations"]
    }
    entrypoints = {row["id"]: row for row in rir["entrypoints"]}
    maximum = scenario["terminal_condition"].get("maximum")
    committed = 0
    while pending:
        active = pending.pop(0)
        ordering = active["ordering_key"]
        if ordering["logical_time"] > bounds["max_logical_time"]:
            raise IndependentRuntimeUnsupported(
                "terminal-audit production is not implemented"
            )
        entrypoint = entrypoints[active["entrypoint"]]
        coordinate = (entrypoint["operation"]["package"], entrypoint["operation"]["id"])
        actual = reference_execute_event(
            {},
            operations[coordinate],
            operations,
            scenario,
            seed=specification["seed"]["value"],
            resolved_entrypoint=entrypoint,
            resolved_declarations=rir["declarations"],
            resolved_call_sites=rir["call_sites"],
            root_operation_coordinate=coordinate,
            selected_semantics=semantic,
            resource_limit=bounds["max_node_steps"],
            include_execution_evidence=True,
            frame=ReferenceEventFrame(
                frame.values,
                frame.rng_states,
                frame.rng_indices,
                frame.node_steps,
                ordering,
            ),
        )
        if "refusal" in actual:
            raise IndependentRuntimeUnsupported(
                f"terminal-audit production is not implemented: {actual['refusal']}"
            )
        charge = actual.pop("execution_evidence")["resource_charge"]
        frame = actual.pop("continuation")
        if charge > bounds["max_event_steps"]:
            raise IndependentRuntimeUnsupported(
                "terminal-audit production is not implemented"
            )
        actual.update(
            {
                "index": len(events),
                "event_id": active["event_id"],
                "root_event_ref": active["root_event_ref"],
                "ordering_key": deepcopy(ordering),
                "external_input_identity": None,
                "observation": None,
                "formula_evaluations": [],
                "snapshot_before_identity": snapshots[-1]["snapshot_identity"],
            }
        )
        committed += 1
        logical_boundary = (
            not pending
            or pending[0]["ordering_key"]["logical_time"] != ordering["logical_time"]
        )
        done = (
            not pending
            or maximum is not None
            and committed >= maximum
            and logical_boundary
        )
        boundary = (
            boundaries["terminal"]
            if done
            else boundaries["logical"]
            if logical_boundary
            else None
        )
        commit_event(
            actual,
            charge,
            boundary,
            lifecycle["ready"] if boundary is not None else lifecycle["active"],
            f"{scenario_id}:event:{active['event_id']}",
        )
        # Operation output bindings are Event facts, not persistent Scenario cells.
        frame = ReferenceEventFrame(
            {
                key: value
                for key, value in frame.values.items()
                if declarations[key]["role"] != "output"
            },
            frame.rng_states,
            frame.rng_indices,
            frame.node_steps,
            frame.ordering_key,
        )
        if done:
            break
    terminal_event = events[-1]
    terminal_snapshot = snapshots[-1]["snapshot_identity"]
    terminal_time = terminal_event["ordering_key"]["logical_time"]
    observations = []
    samples = []
    for index, metric in enumerate(specification["metrics"]):
        metric_id = _metric_identity(metric)
        ordering = {
            "logical_time": terminal_time,
            "phase": scheduler["observation"]["phase"],
            "priority": scheduler["observation"]["priority"],
            "enqueue_sequence": next_sequence,
        }
        event_id = identify_event(
            {"metric_definition_identity": metric_id, **ordering},
            identity_rule["variants"]["observation"],
        )
        next_sequence += 1
        catalog_event(
            {
                "kind": "observation",
                "event_id": event_id,
                "metric_definition_identity": metric_id,
                "ordering_key": ordering,
            }
        )
        event = {
            "index": len(events),
            "event_id": event_id,
            "ordering_key": ordering,
            "entrypoint": None,
            "operation": None,
            "outcome": {"id": "observation-emitted", "kind": "success"},
            "state_before": state_rows(),
            "state_after": state_rows(),
            "facts": _reference_fact_rows(
                {key[2]: value for key, value in frame.values.items()}
            ),
            "calls": [],
            "rng_draws": [],
            "schedules": [],
            "cancellations": [],
            "formula_evaluations": [],
            "external_input_identity": None,
            "observation": {
                "metric": metric["id"],
                "metric_definition_identity": metric_id,
                "window": deepcopy(metric["window"]),
            },
            "snapshot_before_identity": snapshots[-1]["snapshot_identity"],
        }
        last = index == len(specification["metrics"]) - 1
        commit_event(
            event,
            0,
            boundaries["terminal"] if last else boundaries["observation"],
            lifecycle["terminal"] if last else lifecycle["active"],
            f"{scenario_id}:terminal"
            if last
            else f"{scenario_id}:observation:{metric['id']}",
        )
        observations.append(event_id)
        value = next(
            row["value"]
            for row in event["state_after"]
            if row["name"] == metric["observation"]["member"]
        )
        if type(value) is not int:
            raise IndependentRuntimeUnsupported("noninteger Metric sample")
        observation = metric["observation"]
        samples.append(
            {
                "metric": metric["id"],
                "metric_definition_identity": metric_id,
                "scenario": scenario_id,
                "status": "value",
                "value": value,
                "unit": metric["unit"],
                "logical_time": terminal_time,
                "event_id": event_id,
                "snapshot_identity": snapshots[-1]["snapshot_identity"],
                "window": metric["window"]["name"],
                "dimensions": [],
                "replication_identity": scenario_id,
                "source_kind": "simulated",
                "provenance": {
                    "scenario": scenario_id,
                    "observation_source": observation["source"],
                    "observation_name": observation["name"],
                    "observation_member": observation["member"],
                },
                "within_target": metric["target"]["minimum"]
                <= value
                <= metric["target"]["maximum"],
                "source": observation["source"],
                "member": observation["member"],
            }
        )
    statuses = [
        {
            "scenario": scenario_id,
            "condition": deepcopy(scenario["terminal_condition"]),
            "reason": "event-count-reached"
            if maximum is not None and committed >= maximum
            else "queue-drained",
            "event_count": committed,
            "terminal_event_id": terminal_event["event_id"],
            "terminal_snapshot_identity": terminal_snapshot,
            "observation_event_ids": observations,
            "final_snapshot_identity": snapshots[-1]["snapshot_identity"],
            "logical_time": terminal_time,
        }
    ]
    common = {**binding, "root_event_map": root_map}
    trace = _reference_artifact(
        context,
        "event-trace",
        {
            **common,
            "scenario": scenario_id,
            "terminal_statuses": statuses,
            "events": events,
        },
    )
    series = _reference_artifact(
        context,
        "snapshot-series",
        {
            **common,
            "scenario": scenario_id,
            "event_trace_identity": trace["content_identity"],
            "event_catalog": catalog,
            "snapshots": snapshots,
        },
    )
    samples.sort(
        key=lambda row: (row["metric_definition_identity"], row["replication_identity"])
    )
    dataset = _reference_artifact(
        context,
        "metric-dataset",
        {
            **binding,
            "metric_definition_identities": sorted(
                {_metric_identity(row) for row in specification["metrics"]}
            ),
            "data_version": "1",
            "partition": "evaluation",
            "ordering": "metric-definition-identity,replication-identity",
            "ingestion_transformation_identity": None,
            "samples": samples,
        },
    )
    failed = [row["metric"] for row in samples if not row["within_target"]]
    primary_name = "experiment-verdict" if failed else "evaluation-run"
    primary = _reference_artifact(
        context,
        primary_name,
        {
            **common,
            "event_trace_identity": trace["content_identity"],
            "snapshot_series_identity": series["content_identity"],
            "metric_dataset_identity": dataset["content_identity"],
            "terminal_statuses": statuses,
            "outcome": "rejected" if failed else "accepted",
            **({"failed_metrics": failed} if failed else {}),
        },
    )
    manifest = _reference_artifact(
        context,
        "evaluator-capability-manifest",
        {
            "implementation": "gda-balancing.independent-runtime-test-consumer-v1",
            "evaluator_build_identity": _build_identity(),
            "platform": {
                "implementation": platform.python_implementation(),
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine() or "unknown",
            },
            **available,
        },
    )
    return {
        primary_name: primary,
        "event-trace": trace,
        "snapshot-series": series,
        "metric-dataset": dataset,
        "resolved-runtime-profile": resolved_profile,
        "evaluator-capability-manifest": manifest,
    }


def reference_admits_runtime_artifacts(context, rir, specification, artifacts):
    """Check supplied members against fresh independent execution and wire identity."""
    try:
        expected = reference_runtime_artifacts(context, rir, specification)
        if set(expected) != set(artifacts):
            return False
        for name, actual in artifacts.items():
            payload = {
                key: value
                for key, value in actual.items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
            if _reference_artifact(context, name, payload) != actual:
                return False
            if name != "evaluator-capability-manifest" and actual != expected[name]:
                return False
        available = artifacts["evaluator-capability-manifest"]
        return all(
            set(values) <= set(available[key])
            for key, values in specification["runtime"]["required_evaluator"].items()
        )
    except (KeyError, ValueError, TypeError, StopIteration, jsonschema.ValidationError):
        return False
