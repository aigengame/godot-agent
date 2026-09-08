"""Experiment artifact construction, semantic replay, and validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast
from gda_balancing.domain.artifact_set import (
    EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
    EXPERIMENT_SUCCESS_ARTIFACT_SET,
    EXPERIMENT_VERDICT_ARTIFACT_SET,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
)
from gda_balancing.domain.publication import PublicationMember
from gda_balancing.domain.operation_program import (
    OperationCoordinate,
    instruction_evaluation_sites,
    operation_coordinate,
    operation_body_instructions,
    selected_operation_index,
)
from gda_balancing.domain.runtime.scheduler import RuntimeScheduler
from gda_balancing.domain.experiment import (
    CheckedExperiment,
)
from gda_balancing.domain.experiment_artifact_replay import (
    ReplayEventEvidence,
    ReplayInitializationProgramFault as _InitializationProgramFault,
    replay_refusing_operation as _replay_refusing_operation,
    execution_path_segment as _execution_path_segment,
    operation_at_execution_path as _operation_at_execution_path,
    evaluate_initialization_programs as _evaluate_initialization_programs,
    execute_value_instruction as _execute_value_instruction,
    replay_event_evidence as _replay_event_evidence,
)
from gda_balancing.domain.runtime.projections import (
    RuntimeRefusalOutcome,
    artifact as _artifact,
    committed_event_projection as _committed_event_projection,
    empty_runtime_journal_identity as _empty_runtime_journal_identity,
    event_catalog_record as _event_catalog_record,
    extend_runtime_journal_identity as _extend_runtime_journal_identity,
    metric_definition_identity as _metric_definition_identity,
    named_value_rows as _named_value_rows,
    observation_event_id as _observation_event_id,
    operation_formula_slot as _operation_formula_slot,
    ordered_root_events as _ordered_root_events,
    pending_event_projection as _pending_event_projection,
    projected_runtime_identity as _projected_runtime_identity,
    resolved_display_names as _resolved_display_names,
    resolved_runtime_profile as _resolved_runtime_profile,
    root_event_id as _root_event_id,
    runtime_contract as _runtime_contract,
    runtime_journal_contract as _runtime_journal_contract,
    runtime_nodes as _runtime_nodes,
    scenario_transition_events as _scenario_transition_events,
    scheduled_event_id as _scheduled_event_id,
    scheduler_contract as _scheduler_contract,
    unsupported_evaluator_requirement as _unsupported_evaluator_requirement,
)

_INVALID_FORMULA_EVIDENCE = object()
_EXPERIMENT_RUNTIME_REFUSAL_NAMES = frozenset(
    member.logical_name for member in EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET
)
_EXPERIMENT_SUCCESS_NAMES = frozenset(
    member.logical_name for member in EXPERIMENT_SUCCESS_ARTIFACT_SET
)
_EXPERIMENT_VERDICT_NAMES = frozenset(
    member.logical_name for member in EXPERIMENT_VERDICT_ARTIFACT_SET
)


def _evaluate_formula_evidence_result(
    checked: CheckedExperiment,
    formula: dict[str, Any],
    arguments: list[dict[str, Any]],
) -> JsonValue | object:
    """Independently evaluate one traced Formula from admitted RIR semantics."""
    operations = selected_operation_index(checked.rir["selected_semantics"])
    formulas = {
        cast(str, row["identity"]): row
        for row in cast(list[dict[str, Any]], checked.rir["formulas"])
    }
    runtime_nodes = _runtime_nodes(checked)
    numeric = cast(dict[str, Any], _runtime_contract(checked)["numeric"])

    def operand_value(
        operand: dict[str, Any], values: dict[str, JsonValue]
    ) -> JsonValue | object:
        kind = operand.get("kind")
        if kind == "parameter":
            return values.get(
                cast(str, operand.get("parameter")), _INVALID_FORMULA_EVIDENCE
            )
        if kind == "local":
            return values.get(
                cast(str, operand.get("local")), _INVALID_FORMULA_EVIDENCE
            )
        if kind == "literal":
            return cast(JsonValue, operand.get("value"))
        return _INVALID_FORMULA_EVIDENCE

    def evaluate_operation(
        reference: dict[str, Any], values: dict[str, JsonValue]
    ) -> JsonValue | object:
        operation = operations.get(operation_coordinate(reference))
        if operation is None:
            return _INVALID_FORMULA_EVIDENCE
        variables: dict[str, Any] = dict(values)
        try:
            for instruction in cast(list[dict[str, Any]], operation["body"]):
                node = runtime_nodes.get(cast(str, instruction.get("node")))
                if node is None or node.get("family") != "expression":
                    return _INVALID_FORMULA_EVIDENCE
                _execute_value_instruction(instruction, variables, numeric, node)
            source = cast(dict[str, Any], operation["result"]["source"])
            if source.get("kind") not in {"local", "port"}:
                return _INVALID_FORMULA_EVIDENCE
            return cast(
                JsonValue,
                variables[cast(str, source["name"])],
            )
        except (KeyError, OverflowError, TypeError, ValueError):
            return _INVALID_FORMULA_EVIDENCE

    def evaluate_formula(
        selected_formula: dict[str, Any], parameters: dict[str, JsonValue]
    ) -> JsonValue | object:
        body = cast(dict[str, Any], selected_formula["body"])
        if body.get("node") == "parameter":
            return parameters.get(
                cast(str, body.get("parameter")), _INVALID_FORMULA_EVIDENCE
            )
        values = dict(parameters)
        for node in cast(list[dict[str, Any]], body.get("nodes", [])):
            kind = node.get("node")
            if kind == "operation-call":
                inputs: dict[str, JsonValue] = {}
                for argument in cast(list[dict[str, Any]], node["arguments"]):
                    value = operand_value(
                        cast(dict[str, Any], argument["operand"]), values
                    )
                    if value is _INVALID_FORMULA_EVIDENCE:
                        return value
                    inputs[cast(str, argument["port"])] = cast(JsonValue, value)
                result = evaluate_operation(
                    cast(dict[str, Any], node["operation"]), inputs
                )
            elif kind == "formula-call":
                child_reference = cast(dict[str, Any], node["formula"])
                child = formulas.get(cast(str, child_reference.get("identity")))
                if child is None:
                    return _INVALID_FORMULA_EVIDENCE
                inputs = {}
                for argument in cast(list[dict[str, Any]], node["arguments"]):
                    value = operand_value(
                        cast(dict[str, Any], argument["operand"]), values
                    )
                    if value is _INVALID_FORMULA_EVIDENCE:
                        return value
                    inputs[cast(str, argument["parameter"])] = cast(JsonValue, value)
                result = evaluate_formula(child, inputs)
            elif kind == "conditional":
                condition = operand_value(
                    cast(dict[str, Any], node["condition"]), values
                )
                if not isinstance(condition, bool):
                    return _INVALID_FORMULA_EVIDENCE
                result = operand_value(
                    cast(
                        dict[str, Any],
                        node["when_true"] if condition else node["when_false"],
                    ),
                    values,
                )
            else:
                return _INVALID_FORMULA_EVIDENCE
            if result is _INVALID_FORMULA_EVIDENCE:
                return result
            values[cast(str, node["id"])] = cast(JsonValue, result)
        return operand_value(cast(dict[str, Any], body["result"]), values)

    parameters = {
        cast(str, row["parameter"]): cast(JsonValue, row["value"]) for row in arguments
    }
    return evaluate_formula(formula, parameters)


def _event_operation_executions(
    checked: CheckedExperiment,
    event: dict[str, Any],
    root_reference: dict[str, Any] | None,
) -> dict[str, OperationCoordinate] | None:
    """Retain the qualified owner of each traced invocation path."""
    executions: dict[str, OperationCoordinate] = {}
    if isinstance(event.get("operation"), str):
        if root_reference is None or root_reference.get("id") != event["operation"]:
            return None
        entrypoint = event.get("entrypoint")
        root_path = (
            _execution_path_segment(cast(str, entrypoint["id"]))
            if isinstance(entrypoint, dict)
            else f"scheduled:{event.get('schedule_call_site_identity')}"
        )
        executions[root_path] = operation_coordinate(root_reference)
    else:
        return executions
    for call in cast(list[dict[str, Any]], event.get("calls", [])):
        call_operation = call.get("operation")
        call_path = call.get("site")
        if (
            not isinstance(call_path, str)
            or not isinstance(call_operation, dict)
            or call_path in executions
            or _operation_at_execution_path(
                checked, root_reference, root_path, call_path
            )
            != operation_coordinate(call_operation)
        ):
            return None
        executions[call_path] = operation_coordinate(call_operation)
    # Pure invocations have no Event outcome rows. Their selected Formula sites
    # still have graph-owned frames; the later value replay verifies that each
    # claimed dynamic frame actually executed with these exact inputs/results.
    for evaluation in cast(list[dict[str, Any]], event.get("formula_evaluations", [])):
        path = evaluation.get("call_path")
        if not isinstance(path, str):
            return None
        coordinate = _operation_at_execution_path(
            checked, root_reference, root_path, path
        )
        if coordinate is None:
            return None
        executions[path] = coordinate
    return executions


def _trace_formula_evaluations_are_authoritative(
    checked: CheckedExperiment,
    events: Sequence[dict[str, Any]],
) -> bool:
    """Check Formula evidence against explicitly qualified trace invocations."""
    entrypoints = {row["id"]: row["operation"] for row in checked.rir["entrypoints"]}
    scheduled_operations: dict[str, dict[str, Any]] = {}
    for event in events:
        for schedule in cast(list[dict[str, Any]], event.get("schedules", [])):
            event_id = cast(str, schedule["event_id"])
            if event_id in scheduled_operations:
                return False
            scheduled_operations[event_id] = cast(dict[str, Any], schedule["operation"])
    for event in events:
        entrypoint = event.get("entrypoint")
        root_reference = (
            entrypoints.get(entrypoint["id"])
            if isinstance(entrypoint, dict)
            else scheduled_operations.get(cast(str, event.get("event_id")))
        )
        executions = _event_operation_executions(checked, event, root_reference)
        if executions is None or not _event_formula_evaluations_are_authoritative(
            checked, event, executions
        ):
            return False
    return True


def _event_formula_evaluations_are_authoritative(
    checked: CheckedExperiment,
    event: dict[str, Any],
    executions: dict[str, OperationCoordinate],
) -> bool:
    evaluations = event.get("formula_evaluations")
    if not isinstance(evaluations, list):
        return False
    bindings = cast(list[dict[str, Any]], checked.rir["formula_bindings"])
    formulas = {
        cast(str, row["identity"]): row
        for row in cast(list[dict[str, Any]], checked.rir["formulas"])
    }
    operations = selected_operation_index(checked.rir["selected_semantics"])
    seen: set[tuple[str, str]] = set()
    for evaluation in evaluations:
        if not isinstance(evaluation, dict):
            return False
        site_identity = evaluation.get("evaluation_site_identity")
        binding_identity = evaluation.get("binding_identity")
        call_path = evaluation.get("call_path")
        matches = [
            binding
            for binding in bindings
            if binding.get("identity") == binding_identity
            and cast(dict[str, Any], binding.get("site", {})).get("identity")
            == site_identity
        ]
        if len(matches) != 1 or not isinstance(call_path, str):
            return False
        binding = matches[0]
        site = cast(dict[str, Any], binding["site"])
        operation_reference = cast(dict[str, Any], site["operation"])
        operation = operations.get(operation_coordinate(operation_reference))
        formula_reference = cast(dict[str, Any], binding["formula"])
        formula = formulas.get(cast(str, formula_reference["identity"]))
        slot = (
            _operation_formula_slot(operation, cast(str, site["slot"]))
            if operation is not None
            else None
        )
        if (
            operation is None
            or formula is None
            or slot is None
            or evaluation.get("formula") != formula_reference
            or evaluation.get("operation") != operation_reference
            or evaluation.get("slot") != site["slot"]
            or evaluation.get("context") != site["context"]
            or evaluation.get("frame_identity") != event.get("snapshot_before_identity")
            or executions.get(call_path) != operation_coordinate(operation_reference)
            or site_identity not in instruction_evaluation_sites(operation).values()
            or (call_path, cast(str, site_identity)) in seen
        ):
            return False
        seen.add((call_path, cast(str, site_identity)))
        formula_parameters = cast(list[dict[str, Any]], formula["parameters"])
        parameter_ids = [cast(str, row["id"]) for row in formula_parameters]
        binding_parameter_ids = [
            cast(str, row["parameter"])
            for row in cast(list[dict[str, Any]], binding["arguments"])
        ]
        arguments = evaluation.get("arguments")
        if (
            not isinstance(arguments, list)
            or binding_parameter_ids != sorted(parameter_ids)
            or [row.get("parameter") for row in arguments] != sorted(parameter_ids)
        ):
            return False
        domains = {
            cast(str, row["id"]): cast(dict[str, int], row["domain"])
            for row in formula_parameters
        }
        if any(
            not isinstance(row.get("value"), int)
            or isinstance(row["value"], bool)
            or not domains[cast(str, row["parameter"])]["minimum"]
            <= row["value"]
            <= domains[cast(str, row["parameter"])]["maximum"]
            for row in arguments
        ):
            return False
        result = _evaluate_formula_evidence_result(
            checked,
            formula,
            cast(list[dict[str, Any]], arguments),
        )
        if result is _INVALID_FORMULA_EVIDENCE or result != evaluation.get("result"):
            return False
    return True


def _event_catalog_record_is_valid(
    checked: CheckedExperiment,
    record: dict[str, Any],
) -> bool:
    event_spec = record.get("event_spec")
    if (
        set(record)
        != {
            "scenario",
            "event_id",
            "kind",
            "ordering_key",
            "event_spec",
            "event_spec_identity",
        }
        or not isinstance(event_spec, dict)
        or record.get("event_id") != event_spec.get("event_id")
        or record.get("kind") != event_spec.get("kind")
        or record.get("ordering_key") != event_spec.get("ordering_key")
    ):
        return False
    contract = _runtime_journal_contract(checked)["event_spec"]
    return record.get("event_spec_identity") == content_identity(
        cast(str, contract["domain"]),
        cast(JsonValue, event_spec),
    )


def _expected_root_event_catalog(
    checked: CheckedExperiment,
) -> dict[str, dict[str, JsonValue]]:
    expected: dict[str, dict[str, JsonValue]] = {}
    for scenario in checked.value["scenarios"]:
        for authored in _ordered_root_events(checked, scenario):
            event = dict(authored)
            event["event_id"] = _root_event_id(checked, scenario["id"], event)
            record = _event_catalog_record(
                checked,
                cast(str, scenario["id"]),
                _pending_event_projection(event),
            )
            expected[cast(str, event["event_id"])] = record
    return expected


def _scenario_initial_values(
    checked: CheckedExperiment, scenario: dict[str, Any]
) -> tuple[dict[bytes, Any], list[dict[str, Any]]]:
    """Recover authored initial inputs, before any Formula or Event work."""
    entrypoints = {cast(str, row["id"]): row for row in checked.rir["entrypoints"]}
    selected = [
        entrypoints[cast(str, event["entrypoint"])]
        for event in _scenario_transition_events(scenario)
    ]
    values: dict[bytes, Any] = {}
    for entrypoint in selected:
        for initializer in entrypoint["scenario_input_contract"]["initializers"]:
            identity = canonical_bytes(cast(JsonValue, initializer["target"]))
            value = initializer["value"]
            if identity in values and values[identity] != value:
                raise ValueError("Scenario initializers disagree")
            values[identity] = value
    for assignment in scenario["assignments"]:
        values[canonical_bytes(cast(JsonValue, assignment["target"]))] = assignment[
            "value"
        ]
    return values, selected


def _authoritative_event_actual_values(
    checked: CheckedExperiment,
    event_spec: dict[str, JsonValue],
    *,
    event_index: int,
    state_before: list[dict[str, JsonValue]],
    snapshot_identity: str,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> dict[bytes, Any] | None:
    declarations = _resolved_declarations(checked)
    display_names = _resolved_display_names(declarations)
    scenario = next(
        (row for row in checked.value["scenarios"] if row["id"] == scenario_id),
        None,
    )
    if scenario is None:
        return None
    try:
        actual_values, scenario_entrypoints = _scenario_initial_values(
            checked, scenario
        )
        _evaluate_initialization_programs(
            checked,
            actual_values,
            consumed_steps=0,
            runtime_limit=(1 << 63) - 1,
            cache=None,
            selected_entrypoints=scenario_entrypoints,
            frame_token={"scenario": scenario_id, "recovery": "initialization"},
            phase="initialization",
        )
        parent_index = event_index
        for prior_event in sorted(
            events_by_id.values(), key=lambda row: cast(int, row["index"])
        ):
            if cast(int, prior_event["index"]) >= parent_index:
                break
            prior_record = catalog_by_id.get(cast(str, prior_event["event_id"]))
            if prior_record is None or prior_record["scenario"] != scenario_id:
                continue
            prior_spec = cast(dict[str, JsonValue], prior_record["event_spec"])
            if prior_spec["kind"] != "external-input":
                continue
            for fact in cast(list[dict[str, JsonValue]], prior_spec["facts"]):
                actual_values[canonical_bytes(cast(JsonValue, fact["target"]))] = fact[
                    "value"
                ]
        state_by_name = {cast(str, row["name"]): row["value"] for row in state_before}
        for identity, display_name in display_names.items():
            if (
                declarations[identity]["role"] == "state"
                and display_name in state_by_name
            ):
                actual_values[identity] = state_by_name[display_name]
        if event_spec["kind"] == "transition-invocation":
            for payload in cast(list[dict[str, JsonValue]], event_spec["payload"]):
                actual_values[canonical_bytes(cast(JsonValue, payload["target"]))] = (
                    payload["value"]
                )
        _evaluate_initialization_programs(
            checked,
            actual_values,
            consumed_steps=0,
            runtime_limit=(1 << 63) - 1,
            cache=None,
            selected_entrypoints=scenario_entrypoints,
            frame_identity=snapshot_identity,
            phase="event",
        )
    except (
        KeyError,
        OverflowError,
        TypeError,
        ValueError,
        _InitializationProgramFault,
    ):
        return None
    return actual_values


def _event_arguments(
    checked: CheckedExperiment,
    event_spec: dict[str, JsonValue],
    *,
    event_index: int,
    state_before: list[dict[str, JsonValue]],
    snapshot_identity: str,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
    actual_values: dict[bytes, Any] | None = None,
) -> (
    tuple[
        dict[str, JsonValue],
        dict[str, dict[str, JsonValue]],
        dict[bytes, Any],
    ]
    | None
):
    if actual_values is None:
        actual_values = _authoritative_event_actual_values(
            checked,
            event_spec,
            event_index=event_index,
            state_before=state_before,
            snapshot_identity=snapshot_identity,
            scenario_id=scenario_id,
            catalog_by_id=catalog_by_id,
            events_by_id=events_by_id,
        )
    if actual_values is None:
        return None
    if event_spec["kind"] == "scheduled-transition":
        arguments = {
            cast(str, row["name"]): cast(JsonValue, row["value"])
            for row in cast(list[dict[str, JsonValue]], event_spec["arguments"])
        }
        state_references = {
            cast(str, row["name"]): cast(dict[str, JsonValue], row["target"])
            for row in cast(list[dict[str, JsonValue]], event_spec["state_references"])
        }
        for name, target in state_references.items():
            identity = canonical_bytes(cast(JsonValue, target))
            if identity not in actual_values:
                return None
            arguments[name] = actual_values[identity]
        return arguments, state_references, actual_values
    if event_spec["kind"] != "transition-invocation":
        return None
    entrypoint = next(
        (
            row
            for row in checked.rir["entrypoints"]
            if row["id"] == event_spec["entrypoint"]
        ),
        None,
    )
    if entrypoint is None:
        return None
    declarations = _resolved_declarations(checked)
    arguments: dict[str, JsonValue] = {}
    state_references: dict[str, dict[str, JsonValue]] = {}
    for binding in entrypoint["arguments"]:
        port = cast(str, binding["port"]["name"])
        operand = cast(dict[str, Any], binding["operand"])
        if operand["kind"] == "event-reference":
            reference_bindings = {
                cast(str, row["name"]): cast(str, row["root_event_ref"])
                for row in cast(
                    list[dict[str, JsonValue]],
                    event_spec.get("event_references", []),
                )
            }
            root_event_ref = reference_bindings.get(cast(str, operand.get("name")))
            matching_event_ids = [
                event_id
                for event_id, record in catalog_by_id.items()
                if record.get("scenario") == scenario_id
                and isinstance(record.get("event_spec"), dict)
                and cast(dict[str, JsonValue], record["event_spec"]).get("kind")
                == "transition-invocation"
                and cast(dict[str, JsonValue], record["event_spec"]).get(
                    "root_event_ref"
                )
                == root_event_ref
            ]
            if root_event_ref is None or len(matching_event_ids) != 1:
                return None
            arguments[port] = matching_event_ids[0]
            continue
        if operand["kind"] != "symbol":
            if "value" not in operand:
                return None
            arguments[port] = cast(JsonValue, operand["value"])
            continue
        target = cast(dict[str, JsonValue], operand["symbol"])
        identity = canonical_bytes(cast(JsonValue, target))
        if declarations[identity]["role"] == "state":
            if identity not in actual_values:
                return None
            arguments[port] = actual_values[identity]
            state_references[port] = target
        else:
            if identity not in actual_values:
                return None
            arguments[port] = actual_values[identity]
    return arguments, state_references, actual_values


def _replayed_event_evidence(
    checked: CheckedExperiment,
    parent_event: dict[str, JsonValue],
    parent_spec: dict[str, JsonValue],
    target_schedule: dict[str, JsonValue] | None,
    *,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> ReplayEventEvidence | None:
    root_arguments = _event_arguments(
        checked,
        parent_spec,
        event_index=cast(int, parent_event["index"]),
        state_before=cast(list[dict[str, JsonValue]], parent_event["state_before"]),
        snapshot_identity=cast(str, parent_event["snapshot_before_identity"]),
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
    )
    if root_arguments is None:
        return None
    return _replay_event_evidence(
        checked,
        parent_event,
        parent_spec,
        target_schedule,
        root_arguments,
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
    )


def _replayed_schedule_arguments(
    checked: CheckedExperiment,
    parent_event: dict[str, JsonValue],
    parent_spec: dict[str, JsonValue],
    target_schedule: dict[str, JsonValue],
    *,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None:
    replayed = _replayed_event_evidence(
        checked,
        parent_event,
        parent_spec,
        target_schedule,
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
    )
    return replayed.schedule_arguments if replayed is not None else None


def _event_formula_evaluations_match_replay(
    checked: CheckedExperiment,
    event: dict[str, JsonValue],
    record: dict[str, JsonValue],
    *,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> bool:
    evaluations = event.get("formula_evaluations")
    if not isinstance(evaluations, list):
        return False
    if not isinstance(event.get("operation"), str):
        return evaluations == []
    event_spec = record.get("event_spec")
    scenario_id = record.get("scenario")
    if not isinstance(event_spec, dict) or not isinstance(scenario_id, str):
        return False
    replayed = _replayed_event_evidence(
        checked,
        event,
        cast(dict[str, JsonValue], event_spec),
        None,
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
    )
    return replayed is not None and evaluations == replayed.formula_evaluations


def _scheduled_catalog_record_is_authoritative(
    checked: CheckedExperiment,
    record: dict[str, JsonValue],
    *,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> bool:
    event_spec = cast(dict[str, JsonValue], record["event_spec"])
    parent_id = cast(str, event_spec["parent_event_id"])
    parent_event = events_by_id.get(parent_id)
    parent_record = catalog_by_id.get(parent_id)
    if parent_event is None or parent_record is None:
        return False
    parent_spec = cast(dict[str, JsonValue], parent_record["event_spec"])
    parent_operation = parent_event.get("operation")
    if not isinstance(parent_operation, str):
        return False
    schedule_sequence = cast(int, event_spec["schedule_sequence"])
    schedules = cast(list[dict[str, JsonValue]], parent_event["schedules"])
    if not 0 <= schedule_sequence < len(schedules):
        return False
    schedule = schedules[schedule_sequence]
    schedule_parent_operation = schedule.get("parent_operation")
    schedule_call_path = schedule.get("call_path")
    if (
        not isinstance(schedule_parent_operation, str)
        or not isinstance(schedule_call_path, str)
        or not schedule_call_path
    ):
        return False
    ordering_key = cast(dict[str, JsonValue], event_spec["ordering_key"])
    if (
        record["scenario"] != parent_record["scenario"]
        or schedule.get("event_id") != event_spec["event_id"]
        or schedule.get("call_site_identity") != event_spec["call_site_identity"]
        or schedule.get("operation") != event_spec["operation"]
        or schedule.get("ordering_key") != ordering_key
        or schedule.get("arguments") != event_spec["arguments"]
        or schedule.get("state_references") != event_spec["state_references"]
        or _scheduled_event_id(
            checked,
            cast(str, record["scenario"]),
            {
                "parent_event_id": parent_id,
                "call_site_identity": event_spec["call_site_identity"],
                "schedule_sequence": schedule_sequence,
                "logical_time": ordering_key["logical_time"],
                "phase": ordering_key["phase"],
                "priority": ordering_key["priority"],
                "enqueue_sequence": ordering_key["enqueue_sequence"],
            },
        )
        != event_spec["event_id"]
    ):
        return False
    parent_entrypoint = parent_event.get("entrypoint")
    root_reference = (
        next(
            (
                row["operation"]
                for row in checked.rir["entrypoints"]
                if row["id"] == parent_entrypoint["id"]
            ),
            None,
        )
        if isinstance(parent_entrypoint, dict)
        else parent_spec.get("operation")
    )
    if not isinstance(root_reference, dict):
        return False
    executions = _event_operation_executions(
        checked, cast(dict[str, Any], parent_event), root_reference
    )
    if executions is None:
        return False
    parent_coordinate = executions.get(schedule_call_path)
    if parent_coordinate is None or parent_coordinate[1] != schedule_parent_operation:
        return False
    operation = selected_operation_index(checked.rir["selected_semantics"]).get(
        parent_coordinate
    )
    if operation is None:
        return False
    schedule_identity = _scheduler_contract(checked)["call_site_identity"]["schedule"]
    matching_instructions = []
    for instruction in operation_body_instructions(operation["body"]):
        if instruction["node"] != "schedule":
            continue
        call_site_identity = content_identity(
            cast(str, schedule_identity["domain"]),
            cast(
                JsonValue,
                {
                    "parent_event_id": parent_id,
                    "parent_operation": schedule_parent_operation,
                    "site": instruction["site"],
                    "operation": instruction["operation"],
                },
            ),
        )
        if call_site_identity == event_spec["call_site_identity"]:
            matching_instructions.append(instruction)
    if len(matching_instructions) != 1:
        return False
    instruction = matching_instructions[0]
    replayed_arguments = _replayed_schedule_arguments(
        checked,
        parent_event,
        parent_spec,
        schedule,
        scenario_id=cast(str, record["scenario"]),
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
    )
    if replayed_arguments is None:
        return False
    replayed_values, replayed_state_references = replayed_arguments
    expected_argument_rows = [
        {"name": name, "value": value}
        for name, value in sorted(replayed_values.items())
    ]
    expected_state_reference_rows = [
        {"name": name, "target": target}
        for name, target in sorted(replayed_state_references.items())
    ]
    scheduled_argument_rows = cast(list[dict[str, JsonValue]], schedule["arguments"])
    scheduled_state_reference_rows = cast(
        list[dict[str, JsonValue]], schedule["state_references"]
    )
    expected_zero_time_depth = (
        cast(int, parent_spec.get("zero_time_depth", 0)) + 1
        if ordering_key["logical_time"]
        == cast(dict[str, JsonValue], parent_spec["ordering_key"])["logical_time"]
        else 0
    )
    return (
        event_spec["operation"] == instruction["operation"]
        and ordering_key["logical_time"] == instruction["logical_time"]
        and ordering_key["phase"]
        == _scheduler_contract(checked)["schedule"]["child_phase"]
        and ordering_key["priority"] == instruction["priority"]
        and event_spec["zero_time_depth"] == expected_zero_time_depth
        and scheduled_argument_rows == expected_argument_rows
        and scheduled_state_reference_rows == expected_state_reference_rows
    )


def _event_catalog_records_are_authoritative(
    checked: CheckedExperiment,
    catalog: list[dict[str, JsonValue]],
    events: list[dict[str, JsonValue]],
    *,
    required_root_scenarios: set[str] | None = None,
) -> bool:
    expected_roots = _expected_root_event_catalog(checked)
    catalog_by_id = {cast(str, row["event_id"]): row for row in catalog}
    events_by_id = {cast(str, row["event_id"]): row for row in events}
    required_roots = {
        event_id: record
        for event_id, record in expected_roots.items()
        if required_root_scenarios is None
        or record["scenario"] in required_root_scenarios
    }
    if any(
        catalog_by_id.get(event_id) != record
        for event_id, record in required_roots.items()
    ) or len(catalog_by_id) != len(catalog):
        return False
    if required_root_scenarios is not None and any(
        record["scenario"] not in required_root_scenarios for record in catalog
    ):
        return False
    metric_identities = {
        _metric_definition_identity(metric) for metric in checked.value["metrics"]
    }
    for record in catalog:
        event_spec = cast(dict[str, JsonValue], record["event_spec"])
        kind = event_spec["kind"]
        if kind in {"external-input", "transition-invocation"}:
            if expected_roots.get(cast(str, record["event_id"])) != record:
                return False
        elif kind == "scheduled-transition":
            if not _scheduled_catalog_record_is_authoritative(
                checked,
                record,
                catalog_by_id=catalog_by_id,
                events_by_id=events_by_id,
            ):
                return False
        else:
            metric_identity = cast(str, event_spec["metric_definition_identity"])
            ordering_key = cast(dict[str, JsonValue], event_spec["ordering_key"])
            event = events_by_id.get(cast(str, event_spec["event_id"]))
            observation = (
                cast(dict[str, JsonValue], event["observation"])
                if event is not None and event.get("observation") is not None
                else None
            )
            if (
                metric_identity not in metric_identities
                or event is None
                or observation is None
                or event["ordering_key"] != ordering_key
                or observation["metric_definition_identity"] != metric_identity
                or _observation_event_id(
                    checked,
                    cast(str, record["scenario"]),
                    metric_identity,
                    logical_time=cast(int, ordering_key["logical_time"]),
                    enqueue_sequence=cast(int, ordering_key["enqueue_sequence"]),
                )
                != event_spec["event_id"]
                or ordering_key["phase"]
                != _scheduler_contract(checked)["observation"]["phase"]
                or ordering_key["priority"]
                != _scheduler_contract(checked)["observation"]["priority"]
            ):
                return False
    return True


def _resolved_declarations(
    checked: CheckedExperiment,
) -> dict[bytes, dict[str, Any]]:
    return {
        canonical_bytes(cast(JsonValue, row["resolved_symbol"])): row
        for row in checked.rir["declarations"]
    }


def runtime_terminal_audit_members(
    checked: CheckedExperiment,
    outcome: RuntimeRefusalOutcome,
    *,
    evaluator: PublicationMember,
    resolved_runtime: PublicationMember,
) -> dict[str, PublicationMember]:
    """Prepare the complete terminal-only artifact set for runtime refusal."""
    report = outcome.report
    if report.stage != "runtime":
        raise ValueError("terminal audit requires one runtime refusal")
    diagnostic = report.diagnostics[0]
    audit = _artifact(
        checked,
        "runtime-terminal-audit",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "scenario": outcome.scenario_id,
                "committed_trace_prefix": list(outcome.committed_trace_prefix),
                "event_catalog_prefix": list(outcome.event_catalog_prefix),
                "root_event_map": list(outcome.root_event_map),
                "terminal_condition": outcome.terminal_condition,
                "last_snapshot_identity": outcome.last_snapshot_identity,
                "last_snapshot_record": outcome.last_snapshot_record,
                "budget_counters": cast(JsonValue, outcome.budget_counters),
                "last_snapshot": _named_value_rows(outcome.last_state),
                "refusing_event": {
                    "index": outcome.refusing_event_index,
                    "event_id": outcome.refusing_event_id,
                    "event_spec": outcome.refusing_event_spec,
                    "attempted_calls": list(outcome.refusing_attempted_calls),
                    "ordering_key": outcome.refusing_ordering_key,
                    "snapshot_before_identity": (
                        outcome.refusing_snapshot_before_identity
                    ),
                    "entrypoint": {
                        "id": outcome.refusing_entrypoint_id,
                        "identity": outcome.refusing_entrypoint_identity,
                    },
                    "operation": outcome.refusing_operation,
                    "call_path": outcome.refusing_call_path,
                    "call_site_identity": outcome.refusing_call_site_identity,
                    "evaluation_site_identity": (
                        outcome.refusing_evaluation_site_identity
                    ),
                    "instruction_index": outcome.refusing_instruction_index,
                    "reason": diagnostic.code,
                },
                "rollback": {
                    "committed": False,
                    "state_before": _named_value_rows(outcome.state_before),
                    "state_after": _named_value_rows(outcome.state_after),
                },
                "diagnostic": {
                    **diagnostic.model_dump(mode="json"),
                    "stage": "runtime",
                },
            },
        ),
    )
    return {
        "runtime-terminal-audit": audit,
        "resolved-runtime-profile": resolved_runtime,
        "evaluator-capability-manifest": evaluator,
    }


def validate_experiment_member(
    checked: CheckedExperiment, logical_name: str, value: dict[str, Any]
) -> bool:
    """Re-admit one prepared output against its selected exact contract."""
    del logical_name
    kind = value.get("artifact_kind")
    contract = checked.output_contracts.get(kind) if isinstance(kind, str) else None
    if contract is None or not contract.verify(value):
        return False
    if kind == "event-trace":
        return _trace_formula_evaluations_are_authoritative(
            checked, cast(list[dict[str, Any]], value.get("events", []))
        )
    if kind == "runtime-terminal-audit":
        return _trace_formula_evaluations_are_authoritative(
            checked,
            cast(list[dict[str, Any]], value.get("committed_trace_prefix", [])),
        )
    return True


def _expected_root_event_map(
    checked: CheckedExperiment,
) -> list[dict[str, JsonValue]]:
    root_map: list[dict[str, JsonValue]] = []
    for scenario in checked.value["scenarios"]:
        for event in sorted(
            _ordered_root_events(checked, scenario),
            key=lambda item: cast(int, item["enqueue_sequence"]),
        ):
            root_map.append(
                {
                    "scenario": scenario["id"],
                    "root_event_ref": event["root_event_ref"],
                    "event_id": _root_event_id(checked, scenario["id"], event),
                }
            )
    return root_map


def _artifact_set_runtime_journals_are_valid(
    checked: CheckedExperiment,
    trace: dict[str, Any],
    snapshot_series: dict[str, Any],
    resolved_runtime_profile_identity: str,
    expected_root_map: list[dict[str, JsonValue]],
) -> bool:
    journal = _runtime_journal_contract(checked)
    scheduler = _scheduler_contract(checked)
    runtime_scheduler = RuntimeScheduler(scheduler)
    snapshots = cast(list[dict[str, Any]], snapshot_series["snapshots"])
    events = cast(list[dict[str, JsonValue]], trace["events"])
    catalog = cast(list[dict[str, JsonValue]], snapshot_series["event_catalog"])
    if (
        snapshot_series.get("event_trace_identity") != trace.get("content_identity")
        or snapshot_series.get("root_event_map") != expected_root_map
        or trace.get("root_event_map") != expected_root_map
        or any(
            not _event_catalog_record_is_valid(checked, record) for record in catalog
        )
        or not _event_catalog_records_are_authoritative(checked, catalog, events)
        or len({cast(str, row.get("event_id")) for row in catalog}) != len(catalog)
        or any(
            snapshot.get("index") != index for index, snapshot in enumerate(snapshots)
        )
        or any(event.get("index") != index for index, event in enumerate(events))
        or not _trace_formula_evaluations_are_authoritative(checked, events)
    ):
        return False
    catalog_by_id = {cast(str, row["event_id"]): row for row in catalog}
    events_by_id = {cast(str, row["event_id"]): row for row in events}
    if any(
        (record := catalog_by_id.get(cast(str, event["event_id"]))) is None
        or not _event_formula_evaluations_match_replay(
            checked,
            event,
            record,
            catalog_by_id=catalog_by_id,
            events_by_id=events_by_id,
        )
        for event in events
    ):
        return False
    snapshots_by_identity = {
        snapshot.get("snapshot_identity"): snapshot for snapshot in snapshots
    }
    events_by_scenario: dict[str, list[dict[str, JsonValue]]] = {}
    for event in events:
        before = snapshots_by_identity.get(event.get("snapshot_before_identity"))
        after = snapshots_by_identity.get(event.get("snapshot_after_identity"))
        if (
            before is None
            or after is None
            or before.get("scenario") != after.get("scenario")
            or after.get("event_id") != event.get("event_id")
            or before.get("values") != event.get("state_before")
            or after.get("values") != event.get("state_after")
        ):
            return False
        events_by_scenario.setdefault(cast(str, after["scenario"]), []).append(event)
    root_map_identity = content_identity(
        cast(str, journal["root_event_map"]["domain"]),
        cast(JsonValue, expected_root_map),
    )
    catalog_ids = {cast(str, row["event_id"]) for row in catalog}
    scheduled_ids = {
        cast(str, schedule["event_id"])
        for event in events
        for schedule in cast(list[dict[str, JsonValue]], event["schedules"])
    }
    canceled_ids = {
        cast(str, cancellation["event_id"])
        for event in events
        for cancellation in cast(list[dict[str, JsonValue]], event["cancellations"])
    }
    if catalog_ids != (
        {cast(str, event["event_id"]) for event in events}
        | scheduled_ids
        | canceled_ids
    ):
        return False
    for scenario in checked.value["scenarios"]:
        scenario_id = cast(str, scenario["id"])
        scenario_snapshots = [
            snapshot for snapshot in snapshots if snapshot["scenario"] == scenario_id
        ]
        scenario_events = events_by_scenario.get(scenario_id, [])
        scenario_catalog = [row for row in catalog if row["scenario"] == scenario_id]
        if (
            not scenario_snapshots
            or len(scenario_snapshots) != len(scenario_events) + 1
        ):
            return False
        ordering_keys = [
            runtime_scheduler.ordering_key(
                cast(dict[str, Any], event["ordering_key"]),
            )
            for event in scenario_events
        ]
        if ordering_keys != sorted(ordering_keys):
            return False
        catalog_prefixes = [_empty_runtime_journal_identity(journal["event_catalog"])]
        for record in scenario_catalog:
            catalog_prefixes.append(
                _extend_runtime_journal_identity(
                    journal["event_catalog"], catalog_prefixes[-1], record
                )
            )
        trace_prefixes = [_empty_runtime_journal_identity(journal["committed_trace"])]
        canceled_prefixes: list[set[str]] = [set()]
        canceled: set[str] = set()
        for event in scenario_events:
            trace_prefixes.append(
                _extend_runtime_journal_identity(
                    journal["committed_trace"],
                    trace_prefixes[-1],
                    _committed_event_projection(event),
                )
            )
            canceled.update(
                cast(str, cancellation["event_id"])
                for cancellation in cast(
                    list[dict[str, JsonValue]], event["cancellations"]
                )
            )
            canceled_prefixes.append(set(canceled))
        for position, snapshot in enumerate(scenario_snapshots):
            continuation = cast(dict[str, Any], snapshot["continuation"])
            catalog_ref = cast(dict[str, Any], continuation["event_catalog"])
            trace_ref = cast(dict[str, Any], continuation["committed_trace"])
            catalog_count = catalog_ref.get("count")
            trace_count = trace_ref.get("count")
            if (
                not isinstance(catalog_count, int)
                or not isinstance(trace_count, int)
                or not 0 <= catalog_count < len(catalog_prefixes)
                or trace_count != position
            ):
                return False
            catalog_prefix = scenario_catalog[:catalog_count]
            committed_ids = {
                cast(str, event["event_id"]) for event in scenario_events[:trace_count]
            }
            canceled_ids = canceled_prefixes[trace_count]
            catalog_prefix_ids = {
                cast(str, record["event_id"]) for record in catalog_prefix
            }
            if (
                not committed_ids.isdisjoint(canceled_ids)
                or not committed_ids | canceled_ids <= catalog_prefix_ids
            ):
                return False
            pending_records = [
                record
                for record in catalog_prefix
                if record["event_id"] not in committed_ids | canceled_ids
            ]
            pending_order = [
                runtime_scheduler.ordering_key(
                    cast(dict[str, Any], record["ordering_key"]),
                )
                for record in pending_records
            ]
            next_pending_id = (
                cast(
                    str,
                    pending_records[pending_order.index(min(pending_order))][
                        "event_id"
                    ],
                )
                if pending_order
                else None
            )
            next_committed_id = (
                cast(str, scenario_events[trace_count]["event_id"])
                if trace_count < len(scenario_events)
                else None
            )
            if (
                catalog_ref.get("prefix_identity") != catalog_prefixes[catalog_count]
                or trace_ref.get("prefix_identity") != trace_prefixes[trace_count]
                or continuation.get("pending_event_count") != len(pending_records)
                or len(set(pending_order)) != len(pending_order)
                or (
                    next_committed_id is not None
                    and next_committed_id in catalog_prefix_ids
                    and next_pending_id != next_committed_id
                )
                or continuation.get("root_event_map_identity") != root_map_identity
                or continuation.get("resolved_runtime_profile_identity")
                != resolved_runtime_profile_identity
                or _projected_runtime_identity(
                    _scheduler_contract(checked)["snapshot_identity"],
                    {
                        "experiment_identity": checked.content_identity,
                        "scenario_id": scenario_id,
                        "index": snapshot["index"],
                        "logical_time": snapshot["logical_time"],
                        "event_id": snapshot["event_id"],
                        "values": snapshot["values"],
                        "continuation": continuation,
                    },
                )
                != snapshot["snapshot_identity"]
            ):
                return False
    return True


def _terminal_statuses_are_valid(
    trace: dict[str, Any], snapshot_series: dict[str, Any]
) -> bool:
    snapshots = cast(list[dict[str, Any]], snapshot_series["snapshots"])
    events = cast(list[dict[str, Any]], trace["events"])
    snapshots_by_identity = {
        snapshot["snapshot_identity"]: snapshot for snapshot in snapshots
    }
    events_by_id = {event["event_id"]: event for event in events}
    for status in cast(list[dict[str, Any]], trace["terminal_statuses"]):
        scenario = status["scenario"]
        terminal_event = events_by_id.get(status["terminal_event_id"])
        terminal_snapshot = snapshots_by_identity.get(
            status["terminal_snapshot_identity"]
        )
        final_snapshot = snapshots_by_identity.get(status["final_snapshot_identity"])
        observation_ids = cast(list[str], status["observation_event_ids"])
        scenario_runtime_events = [
            event
            for event in events
            if event["observation"] is None
            and snapshots_by_identity[event["snapshot_after_identity"]]["scenario"]
            == scenario
        ]
        if (
            terminal_event is None
            or terminal_snapshot is None
            or final_snapshot is None
            or terminal_event.get("observation") is not None
            or terminal_snapshot.get("event_id") != terminal_event.get("event_id")
            or terminal_snapshot.get("scenario") != scenario
            or final_snapshot.get("scenario") != scenario
            or final_snapshot
            is not [
                snapshot for snapshot in snapshots if snapshot["scenario"] == scenario
            ][-1]
            or status.get("event_count") != len(scenario_runtime_events)
            or terminal_event is not scenario_runtime_events[-1]
            or status.get("logical_time")
            != cast(dict[str, Any], terminal_event["ordering_key"])["logical_time"]
            or any(
                event_id not in events_by_id
                or events_by_id[event_id].get("observation") is None
                or snapshots_by_identity[
                    events_by_id[event_id]["snapshot_after_identity"]
                ]["scenario"]
                != scenario
                for event_id in observation_ids
            )
        ):
            return False
        condition = cast(dict[str, Any], status["condition"])
        if condition["kind"] == "event-count" and (
            status["reason"] != "event-count-reached"
            or status["event_count"] < condition["maximum"]
        ):
            return False
        if condition["kind"] == "queue-drained" and (
            status["reason"] != "queue-drained"
            or cast(dict[str, Any], terminal_snapshot["continuation"])[
                "pending_event_count"
            ]
            != 0
        ):
            return False
    return True


def _runtime_state_rows_are_valid(rows: list[dict[str, Any]]) -> bool:
    names = [row.get("name") for row in rows]
    if not all(isinstance(name, str) and name for name in names):
        return False
    typed_names = cast(list[str], names)
    return typed_names == sorted(typed_names) and len(set(typed_names)) == len(
        typed_names
    )


@dataclass(frozen=True)
class _TerminalPrefixEvidence:
    snapshot_event_steps: int
    snapshot_node_steps: int
    node_steps: int
    actual_values: dict[bytes, Any]
    state: list[dict[str, JsonValue]]
    selected_entrypoints: list[dict[str, Any]]
    observation_fault: _InitializationProgramFault | None


def _terminal_prefix_evidence(
    checked: CheckedExperiment,
    events: list[dict[str, Any]],
    catalog_by_id: dict[str, dict[str, JsonValue]],
    *,
    scenario_index: int,
    refusing_event_id: str,
    runtime_limit: int,
) -> _TerminalPrefixEvidence:
    """Replay completed work from checked inputs; snapshots do not supply counters.

    A committed Snapshot precedes observation Formula work. Keep that ledger
    separate from the cumulative run charge used by the following Event.
    """
    declarations = _resolved_declarations(checked)
    names = _resolved_display_names(declarations)
    state_ids = {
        name: identity
        for identity, name in names.items()
        if declarations[identity]["role"] == "state"
    }
    scheduler = RuntimeScheduler(_scheduler_contract(checked))
    step = _runtime_contract(checked)["step"]
    roles, stops = step["boundary_roles"], step["stop"]
    events_by_id = {cast(str, event["event_id"]): event for event in events}
    node_steps = 0
    snapshot_node_steps = 0
    snapshot_event_steps = 0
    actual_values: dict[bytes, Any] = {}
    selected: list[dict[str, Any]] = []
    observation_fault = None
    for position, scenario in enumerate(
        checked.value["scenarios"][: scenario_index + 1]
    ):
        scenario_id = scenario["id"]
        actual_values, selected = _scenario_initial_values(checked, scenario)
        node_steps = _evaluate_initialization_programs(
            checked,
            actual_values,
            consumed_steps=node_steps,
            runtime_limit=runtime_limit,
            cache=None,
            selected_entrypoints=selected,
            frame_token={"scenario": scenario_id, "recovery": "initialization"},
            phase="initialization",
        )
        state = {
            name: actual_values[identity]
            for name, identity in state_ids.items()
            if identity in actual_values
        }
        snapshot_node_steps, snapshot_event_steps = node_steps, 0
        pending = {
            event_id
            for event_id, record in catalog_by_id.items()
            if record["scenario"] == scenario_id
            and cast(dict[str, Any], record["event_spec"]).get("root_event_ref")
            is not None
        }
        scenario_events = [
            event
            for event in events
            if catalog_by_id[cast(str, event["event_id"])]["scenario"] == scenario_id
        ]
        condition = scenario["terminal_condition"]
        maximum = condition["maximum"] if condition["kind"] == "event-count" else None
        event_position = 0
        terminal = False
        observation_count = 0
        for event in scenario_events:
            event_id = cast(str, event["event_id"])
            spec = cast(dict[str, Any], catalog_by_id[event_id]["event_spec"])
            if event["state_before"] != _named_value_rows(state):
                raise ValueError("Committed prefix does not start from checked state")
            if spec["kind"] == "observation":
                if not terminal or event["state_after"] != event["state_before"]:
                    raise ValueError("Metric observation precedes scenario completion")
                if event["formula_evaluations"] != []:
                    raise ValueError("Metric observation invents Formula work")
                observation_count += 1
                snapshot_node_steps, snapshot_event_steps = node_steps, 0
                continue
            if (
                terminal
                or not pending
                or event_id
                != min(
                    pending,
                    key=lambda identity: scheduler.ordering_key(
                        cast(dict[str, Any], catalog_by_id[identity]["ordering_key"])
                    ),
                )
            ):
                raise ValueError("Committed prefix is not the next scheduled Event")
            pending.remove(event_id)
            event_values = dict(actual_values)
            for payload in spec.get("payload", []):
                event_values[canonical_bytes(cast(JsonValue, payload["target"]))] = (
                    payload["value"]
                )
            if spec["kind"] == "external-input":
                if (
                    event["state_after"] != event["state_before"]
                    or event["formula_evaluations"] != []
                ):
                    raise ValueError("External input invents state or Formula work")
                for fact in spec["facts"]:
                    event_values[canonical_bytes(cast(JsonValue, fact["target"]))] = (
                        fact["value"]
                    )
                actual_values.update(event_values)
                event_steps = 0
            else:
                node_steps = _evaluate_initialization_programs(
                    checked,
                    event_values,
                    consumed_steps=node_steps,
                    runtime_limit=runtime_limit,
                    cache=None,
                    selected_entrypoints=selected,
                    frame_identity=event["snapshot_before_identity"],
                    phase="event",
                )
                arguments = _event_arguments(
                    checked,
                    spec,
                    event_index=event["index"],
                    state_before=event["state_before"],
                    snapshot_identity=event["snapshot_before_identity"],
                    scenario_id=scenario_id,
                    catalog_by_id=catalog_by_id,
                    events_by_id=events_by_id,
                    actual_values=event_values,
                )
                replay = (
                    None
                    if arguments is None
                    else _replay_event_evidence(
                        checked,
                        event,
                        spec,
                        None,
                        arguments,
                        scenario_id=scenario_id,
                        catalog_by_id=catalog_by_id,
                        events_by_id=events_by_id,
                        node_steps_before_operation=node_steps,
                    )
                )
                if (
                    replay is None
                    or event["formula_evaluations"] != replay.formula_evaluations
                ):
                    raise ValueError("Committed Event does not replay")
                node_steps, event_steps = replay.node_steps, replay.event_steps
                state = {row["name"]: row["value"] for row in event["state_after"]}
                for name, value in state.items():
                    actual_values[state_ids[name]] = value
            pending.update(row["event_id"] for row in event["schedules"])
            pending.difference_update(row["event_id"] for row in event["cancellations"])
            event_position += 1
            snapshot_node_steps, snapshot_event_steps = node_steps, event_steps
            later_time = (
                bool(pending)
                and min(
                    cast(dict[str, Any], catalog_by_id[identity]["ordering_key"])[
                        "logical_time"
                    ]
                    for identity in pending
                )
                != event["ordering_key"]["logical_time"]
            )
            boundary = (
                roles["terminal"]
                if not pending
                or (later_time and maximum is not None and event_position >= maximum)
                else roles["logical"]
                if later_time
                else None
            )
            if boundary not in stops:
                continue
            terminal = boundary == roles["terminal"]
            try:
                node_steps = _evaluate_initialization_programs(
                    checked,
                    actual_values,
                    consumed_steps=node_steps,
                    runtime_limit=runtime_limit,
                    cache=None,
                    selected_entrypoints=selected,
                    frame_identity=event["snapshot_after_identity"],
                    phase="observation",
                )
            except _InitializationProgramFault as fault:
                if (
                    position != scenario_index
                    or event_id != refusing_event_id
                    or event is not events[-1]
                ):
                    raise ValueError(
                        "Claimed prefix continues past a Formula refusal"
                    ) from fault
                observation_fault = fault
                node_steps = fault.consumed_steps
        if position < scenario_index and (
            not terminal or observation_count != len(checked.value["metrics"])
        ):
            raise ValueError("Claimed prefix omits a prior scenario's work")
    if observation_fault is None:
        refusing_record = catalog_by_id.get(refusing_event_id)
        if refusing_record is None:
            if not terminal:
                raise ValueError("Metric refusal precedes scenario completion")
        elif (
            terminal
            or not pending
            or refusing_event_id
            != min(
                pending,
                key=lambda identity: scheduler.ordering_key(
                    cast(dict[str, Any], catalog_by_id[identity]["ordering_key"])
                ),
            )
        ):
            raise ValueError("Refusal skips the next scheduled Event")
    return _TerminalPrefixEvidence(
        snapshot_event_steps,
        snapshot_node_steps,
        node_steps,
        actual_values,
        _named_value_rows(state),
        selected,
        observation_fault,
    )


def _terminal_audit_is_valid(
    checked: CheckedExperiment,
    audit: dict[str, Any],
    *,
    expected_root_map: list[dict[str, JsonValue]],
) -> bool:
    scheduler = _scheduler_contract(checked)
    runtime_scheduler = RuntimeScheduler(scheduler)
    scenario_id = audit.get("scenario")
    scenario_rows = [
        (index, scenario)
        for index, scenario in enumerate(checked.value["scenarios"])
        if scenario["id"] == scenario_id
    ]
    if len(scenario_rows) != 1:
        return False
    scenario_index, scenario = scenario_rows[0]
    diagnostic = cast(dict[str, Any], audit["diagnostic"])
    refusing_event = cast(dict[str, Any], audit["refusing_event"])
    refusing_event_spec = cast(dict[str, Any], refusing_event["event_spec"])
    rollback = cast(dict[str, Any], audit["rollback"])
    last_snapshot_values = cast(list[dict[str, Any]], audit["last_snapshot"])
    last_snapshot = cast(dict[str, Any], audit["last_snapshot_record"])
    state_before = cast(list[dict[str, Any]], rollback["state_before"])
    state_after = cast(list[dict[str, Any]], rollback["state_after"])
    runtime_diagnostics = {
        row["definition"]["code"]
        for row in checked.rir["selected_semantics"]["diagnostics"]
        if row["definition"]["stage"] == "runtime"
    }
    if (
        audit.get("terminal_condition") != scenario["terminal_condition"]
        or audit.get("last_snapshot_identity")
        != refusing_event.get("snapshot_before_identity")
        or refusing_event.get("reason") != diagnostic.get("code")
        or diagnostic.get("stage") != "runtime"
        or diagnostic.get("code") not in runtime_diagnostics
        or diagnostic.get("primary")
        != {
            "kind": "artifact",
            "content_identity": checked.content_identity,
            "pointer": f"/scenarios/{scenario_index}/entrypoint",
        }
        or diagnostic.get("related") != []
        or rollback.get("committed") is not False
        or state_before != state_after
        or state_before != last_snapshot_values
        or last_snapshot.get("values") != last_snapshot_values
        or not _runtime_state_rows_are_valid(last_snapshot_values)
        or audit.get("last_snapshot_identity") != last_snapshot.get("snapshot_identity")
        or refusing_event.get("event_id") != refusing_event_spec.get("event_id")
        or refusing_event.get("ordering_key") != refusing_event_spec.get("ordering_key")
    ):
        return False
    budget = cast(dict[str, Any], audit["budget_counters"])
    ordering_key = cast(dict[str, Any], refusing_event["ordering_key"])
    if budget.get("logical_time") != ordering_key.get("logical_time") or any(
        not isinstance(budget.get(member), int) or budget[member] < 0
        for member in (
            "event_steps",
            "logical_time",
            "node_steps",
            "queue_events",
            "total_events",
            "zero_time_depth",
        )
    ):
        return False

    root_records = {cast(str, row["event_id"]): row for row in expected_root_map}
    scenario_positions = {
        cast(str, row["id"]): index
        for index, row in enumerate(checked.value["scenarios"])
    }
    events = cast(list[dict[str, Any]], audit["committed_trace_prefix"])
    catalog = cast(list[dict[str, JsonValue]], audit["event_catalog_prefix"])
    required_root_scenarios = {
        cast(str, row["id"]) for row in checked.value["scenarios"][: scenario_index + 1]
    }
    if (
        any(not _event_catalog_record_is_valid(checked, record) for record in catalog)
        or not _trace_formula_evaluations_are_authoritative(checked, events)
        or not _event_catalog_records_are_authoritative(
            checked,
            catalog,
            cast(list[dict[str, JsonValue]], events),
            required_root_scenarios=required_root_scenarios,
        )
    ):
        return False
    catalog_by_id = {cast(str, row["event_id"]): row for row in catalog}
    events_by_id = {cast(str, row["event_id"]): row for row in events}
    if refusing_event.get("index") != len(events):
        return False
    event_scenarios: dict[str, str] = {}
    seen_event_ids: set[str] = set()
    seen_snapshot_after: set[str] = set()
    previous_event: dict[str, Any] | None = None
    previous_scenario: str | None = None
    previous_ordering: tuple[int, ...] | None = None
    current_scenario_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        event_id = cast(str, event["event_id"])
        root_record = root_records.get(event_id)
        if root_record is not None:
            event_scenario = cast(str, root_record["scenario"])
            if event.get("root_event_ref") != root_record["root_event_ref"]:
                return False
        elif "parent_event_id" in event:
            event_scenario = event_scenarios.get(
                cast(str, event["parent_event_id"]), ""
            )
            if not event_scenario:
                return False
        elif event.get("observation") is not None and previous_event is not None:
            if event.get("snapshot_before_identity") != previous_event.get(
                "snapshot_after_identity"
            ):
                return False
            event_scenario = cast(str, previous_scenario)
        else:
            return False
        ordering = runtime_scheduler.ordering_key(
            cast(dict[str, Any], event["ordering_key"])
        )
        if (
            event.get("index") != index
            or event_id in seen_event_ids
            or event.get("snapshot_after_identity") in seen_snapshot_after
            or not _runtime_state_rows_are_valid(
                cast(list[dict[str, Any]], event["state_before"])
            )
            or not _runtime_state_rows_are_valid(
                cast(list[dict[str, Any]], event["state_after"])
            )
        ):
            return False
        if event_scenario == previous_scenario:
            if (
                previous_event is None
                or event.get("snapshot_before_identity")
                != previous_event.get("snapshot_after_identity")
                or event.get("state_before") != previous_event.get("state_after")
                or previous_ordering is None
                or ordering < previous_ordering
            ):
                return False
        elif (
            root_record is None
            or previous_scenario is not None
            and scenario_positions[event_scenario]
            <= scenario_positions[previous_scenario]
        ):
            return False
        event_scenarios[event_id] = event_scenario
        seen_event_ids.add(event_id)
        seen_snapshot_after.add(cast(str, event["snapshot_after_identity"]))
        if event_scenario == scenario_id:
            current_scenario_events.append(event)
        previous_event = event
        previous_scenario = event_scenario
        previous_ordering = ordering

    required_root_ids = {
        event_id
        for event_id, record in root_records.items()
        if record["scenario"] in required_root_scenarios
    }
    scheduled_ids = {
        cast(str, schedule["event_id"])
        for event in events
        for schedule in cast(list[dict[str, JsonValue]], event["schedules"])
    }
    committed_observation_ids = {
        cast(str, event["event_id"])
        for event in events
        if event.get("observation") is not None
    }
    catalog_ids = {cast(str, record["event_id"]) for record in catalog}
    if (
        catalog_ids != required_root_ids | scheduled_ids | committed_observation_ids
        or any(
            record["scenario"] != event_scenarios.get(cast(str, record["event_id"]))
            for record in catalog
            if record["event_id"] in event_scenarios
        )
    ):
        return False

    refusing_event_id = cast(str, refusing_event["event_id"])
    refusing_root = root_records.get(refusing_event_id)
    catalog_by_id = {cast(str, row["event_id"]): row for row in catalog}
    refusing_catalog_record = catalog_by_id.get(refusing_event_id)
    continuation = cast(dict[str, Any], last_snapshot["continuation"])
    refusing_metric: dict[str, Any] | None = None
    if refusing_catalog_record is not None:
        if (
            refusing_catalog_record["scenario"] != scenario_id
            or refusing_catalog_record["event_spec"] != refusing_event_spec
        ):
            return False
    elif refusing_event_spec.get("kind") == "observation":
        metric_identity = cast(str, refusing_event_spec["metric_definition_identity"])
        committed_observation_count = sum(
            record["scenario"] == scenario_id
            and cast(dict[str, JsonValue], record["event_spec"])["kind"]
            == "observation"
            for record in catalog
        )
        refusing_metric = (
            checked.value["metrics"][committed_observation_count]
            if committed_observation_count < len(checked.value["metrics"])
            else None
        )
        expected_ordering_key = {
            "logical_time": last_snapshot["logical_time"],
            "phase": scheduler["observation"]["phase"],
            "priority": scheduler["observation"]["priority"],
            "enqueue_sequence": continuation["next_enqueue_sequence"],
        }
        if (
            refusing_metric is None
            or _metric_definition_identity(refusing_metric) != metric_identity
            or ordering_key != expected_ordering_key
            or _observation_event_id(
                checked,
                cast(str, scenario_id),
                metric_identity,
                logical_time=cast(int, expected_ordering_key["logical_time"]),
                enqueue_sequence=cast(int, expected_ordering_key["enqueue_sequence"]),
            )
            != refusing_event_id
        ):
            return False
    else:
        return False
    boundary_formula_refusal = (
        refusing_event_id in seen_event_ids
        and bool(current_scenario_events)
        and current_scenario_events[-1]["event_id"] == refusing_event_id
        and refusing_event.get("evaluation_site_identity") is not None
    )
    if (
        refusing_event_id in seen_event_ids
        and not boundary_formula_refusal
        or refusing_root is not None
        and refusing_root["scenario"] != scenario_id
    ):
        return False
    expected_last_event = (
        current_scenario_events[-1] if current_scenario_events else None
    )
    if current_scenario_events:
        last_event = current_scenario_events[-1]
        if (
            audit.get("last_snapshot_identity")
            != last_event.get("snapshot_after_identity")
            or last_snapshot_values != last_event.get("state_after")
            or runtime_scheduler.ordering_key(ordering_key)
            < runtime_scheduler.ordering_key(
                cast(dict[str, Any], last_event["ordering_key"]),
            )
        ):
            return False
    expected_snapshot_event_id = (
        expected_last_event["event_id"] if expected_last_event is not None else None
    )
    expected_snapshot_logical_time = (
        cast(dict[str, Any], expected_last_event["ordering_key"])["logical_time"]
        if expected_last_event is not None
        else None
    )
    journal = _runtime_journal_contract(checked)
    scenario_catalog = [
        record for record in catalog if record["scenario"] == scenario_id
    ]
    catalog_identity = _empty_runtime_journal_identity(journal["event_catalog"])
    for record in scenario_catalog:
        catalog_identity = _extend_runtime_journal_identity(
            journal["event_catalog"], catalog_identity, record
        )
    trace_identity = _empty_runtime_journal_identity(journal["committed_trace"])
    canceled_ids: set[str] = set()
    for event in current_scenario_events:
        trace_identity = _extend_runtime_journal_identity(
            journal["committed_trace"],
            trace_identity,
            _committed_event_projection(cast(dict[str, JsonValue], event)),
        )
        canceled_ids.update(
            cast(str, cancellation["event_id"])
            for cancellation in cast(list[dict[str, Any]], event["cancellations"])
        )
    committed_ids = {cast(str, event["event_id"]) for event in current_scenario_events}
    pending_ids = {
        cast(str, record["event_id"])
        for record in scenario_catalog
        if record["event_id"] not in committed_ids | canceled_ids
    }
    root_map_identity = content_identity(
        cast(str, journal["root_event_map"]["domain"]),
        cast(JsonValue, expected_root_map),
    )
    catalog_ref = cast(dict[str, Any], continuation["event_catalog"])
    trace_ref = cast(dict[str, Any], continuation["committed_trace"])
    current_snapshot_ref = cast(dict[str, Any], continuation["current_snapshot"])
    ledger = cast(dict[str, Any], continuation["resource_ledger"])
    next_enqueue_sequence = (
        max(
            cast(int, cast(dict[str, Any], record["ordering_key"])["enqueue_sequence"])
            for record in scenario_catalog
        )
        + 1
    )
    if (
        last_snapshot.get("scenario") != scenario_id
        or last_snapshot.get("index") != len(events) + scenario_index
        or last_snapshot.get("event_id") != expected_snapshot_event_id
        or last_snapshot.get("logical_time") != expected_snapshot_logical_time
        or catalog_ref
        != {"count": len(scenario_catalog), "prefix_identity": catalog_identity}
        or trace_ref
        != {
            "count": len(current_scenario_events),
            "prefix_identity": trace_identity,
        }
        or continuation.get("pending_event_count") != len(pending_ids)
        or current_snapshot_ref
        != {
            "index": last_snapshot["index"],
            "event_id": expected_snapshot_event_id,
            "logical_time": expected_snapshot_logical_time,
        }
        or ledger.get("queue_events") != len(pending_ids)
        or ledger.get("total_events") != len(scenario_catalog)
        or continuation.get("next_enqueue_sequence") != next_enqueue_sequence
        or continuation.get("scenario_cursor") != scenario_index
        or continuation.get("root_event_map_identity") != root_map_identity
        or _projected_runtime_identity(
            _scheduler_contract(checked)["snapshot_identity"],
            {
                "experiment_identity": checked.content_identity,
                "scenario_id": cast(str, scenario_id),
                "index": last_snapshot["index"],
                "logical_time": last_snapshot["logical_time"],
                "event_id": last_snapshot["event_id"],
                "values": last_snapshot["values"],
                "continuation": continuation,
            },
        )
        != last_snapshot["snapshot_identity"]
    ):
        return False
    refusing_is_pending = refusing_event_id in pending_ids
    expected_queue_events = len(pending_ids) - (1 if refusing_is_pending else 0)
    runtime_profile = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == checked.value["runtime"]["profile"]
    )
    bounds = cast(dict[str, int], runtime_profile["resource_bounds"])
    try:
        prefix = _terminal_prefix_evidence(
            checked,
            events,
            catalog_by_id,
            scenario_index=scenario_index,
            refusing_event_id=refusing_event_id,
            runtime_limit=bounds["max_node_steps"],
        )
    except _InitializationProgramFault:
        return False
    if (
        last_snapshot_values != prefix.state
        or ledger["event_steps"] != prefix.snapshot_event_steps
        or ledger["node_steps"] != prefix.snapshot_node_steps
    ):
        return False
    resolved_entrypoints = {
        cast(str, row["id"]): row for row in checked.rir["entrypoints"]
    }
    expected_entrypoint = None
    root_operation = None
    root_path = None
    if refusing_event_spec["kind"] == "transition-invocation":
        root_entrypoint = resolved_entrypoints[refusing_event_spec["entrypoint"]]
        expected_entrypoint = {
            "id": root_entrypoint["id"],
            "identity": root_entrypoint["identity"],
        }
        root_operation = root_entrypoint["operation"]["id"]
        root_path = _execution_path_segment(root_entrypoint["id"])
    elif refusing_event_spec["kind"] == "scheduled-transition":
        identity = refusing_event_spec["call_site_identity"]
        expected_entrypoint = {"id": f"scheduled:{identity}", "identity": identity}
        root_operation = refusing_event_spec["operation"]["id"]
        root_path = _execution_path_segment(f"scheduled:{identity}")
    elif refusing_event_spec["kind"] == "external-input" and boundary_formula_refusal:
        entrypoint_id = f"input:{refusing_event_spec['root_event_ref']}"
        expected_entrypoint = {"id": entrypoint_id, "identity": refusing_event_id}
        root_operation = "external-input"
        root_path = _execution_path_segment(entrypoint_id)
    event_values = dict(prefix.actual_values)
    formula_fault = prefix.observation_fault
    node_steps = prefix.node_steps
    if not boundary_formula_refusal and refusing_event_spec["kind"] != "observation":
        for payload in refusing_event_spec.get("payload", []):
            event_values[canonical_bytes(cast(JsonValue, payload["target"]))] = payload[
                "value"
            ]
        try:
            node_steps = _evaluate_initialization_programs(
                checked,
                event_values,
                consumed_steps=node_steps,
                runtime_limit=bounds["max_node_steps"],
                cache=None,
                selected_entrypoints=prefix.selected_entrypoints,
                frame_identity=refusing_event["snapshot_before_identity"],
                phase="event",
            )
        except _InitializationProgramFault as fault:
            formula_fault = fault
    if refusing_event_spec["kind"] == "observation":
        exact_event_steps = 0
        exact_node_steps = node_steps
        if (
            formula_fault is not None
            or len(scenario_catalog) < bounds["max_total_events"]
            or refusing_metric is None
            or refusing_event["entrypoint"]
            != {
                "id": f"observation:{refusing_metric['id']}",
                "identity": _metric_definition_identity(refusing_metric),
            }
            or refusing_event["operation"] != "observation"
            or refusing_event["call_path"] != f"observation/{refusing_metric['id']}"
            or refusing_event["attempted_calls"] != []
            or refusing_event["call_site_identity"] is not None
            or refusing_event["evaluation_site_identity"] is not None
            or refusing_event["instruction_index"] is not None
            or not any(
                reason.get("stage") == "runtime"
                and reason["diagnostic"] == diagnostic["code"]
                and reason.get("signal") == "event-limit"
                for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
                for reason in [row["definition"]]
            )
        ):
            return False
    elif formula_fault is not None:
        expected_calls = (
            events_by_id[refusing_event_id]["calls"] if boundary_formula_refusal else []
        )
        if (
            expected_entrypoint is None
            or refusing_event["entrypoint"] != expected_entrypoint
            or refusing_event["operation"] != root_operation
            or refusing_event["call_path"] != root_path
            or refusing_event["attempted_calls"] != expected_calls
            or refusing_event["evaluation_site_identity"]
            != formula_fault.evaluation_site_identity
            or refusing_event["instruction_index"] is not None
            or refusing_event["call_site_identity"] is not None
            or not any(
                reason.get("stage") == "runtime"
                and reason["diagnostic"] == diagnostic["code"]
                and reason.get("signal") == formula_fault.signal
                for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
                for reason in [row["definition"]]
            )
        ):
            return False
        exact_event_steps = (
            prefix.snapshot_event_steps if boundary_formula_refusal else 0
        )
        exact_node_steps = formula_fault.consumed_steps
    elif boundary_formula_refusal:
        return False
    else:
        if (
            expected_entrypoint is None
            or refusing_event["entrypoint"] != expected_entrypoint
        ):
            return False
        root_arguments = _event_arguments(
            checked,
            refusing_event_spec,
            event_index=cast(int, refusing_event["index"]),
            state_before=cast(list[dict[str, JsonValue]], state_before),
            snapshot_identity=cast(str, refusing_event["snapshot_before_identity"]),
            scenario_id=cast(str, scenario_id),
            catalog_by_id=catalog_by_id,
            events_by_id=cast(dict[str, dict[str, JsonValue]], events_by_id),
            actual_values=event_values,
        )
        if root_arguments is None:
            return False
        replayed = _replay_refusing_operation(
            checked,
            refusing_event_spec,
            root_arguments,
            index=cast(int, refusing_event["index"]),
            state_before=cast(list[dict[str, JsonValue]], state_before),
            snapshot_identity=cast(str, refusing_event["snapshot_before_identity"]),
            attempted_calls=refusing_event["attempted_calls"],
            scenario_id=cast(str, scenario_id),
            catalog_by_id=catalog_by_id,
            events_by_id=cast(dict[str, dict[str, JsonValue]], events_by_id),
            node_steps_before_operation=node_steps,
            bounds=bounds,
        )
        if replayed is None or any(
            refusing_event.get(member) != getattr(replayed, member)
            for member in (
                "operation",
                "call_path",
                "call_site_identity",
                "instruction_index",
                "evaluation_site_identity",
            )
        ):
            return False
        # A diagnostic may represent several reasons. Require the exact first
        # executed signal to be one of those selected reasons, not just a match
        # of the broad step-limit/non-step category.
        if not any(
            reason.get("stage") == "runtime"
            and reason["diagnostic"] == diagnostic["code"]
            and reason.get("signal") == replayed.signal
            for row in checked.rir["selected_semantics"]["diagnostic_reasons"]
            for reason in [row["definition"]]
        ):
            return False
        exact_event_steps = replayed.event_steps
        exact_node_steps = replayed.node_steps
    if (
        budget["total_events"] != len(scenario_catalog)
        or budget["queue_events"] != expected_queue_events
        or budget["zero_time_depth"]
        != cast(int, refusing_event_spec.get("zero_time_depth", 0))
        or budget["event_steps"] != exact_event_steps
        or budget["node_steps"] != exact_node_steps
        or budget["event_steps"] > bounds["max_event_steps"] + 1
    ):
        return False
    return True


def _metric_dataset_matches_observations(
    checked: CheckedExperiment,
    trace: dict[str, Any],
    snapshot_series: dict[str, Any],
    dataset: dict[str, Any],
    primary_name: str,
    primary: dict[str, Any],
) -> bool:
    """Derive complete samples from the already validated committed evidence."""
    metrics = {
        _metric_definition_identity(metric): metric
        for metric in checked.value["metrics"]
    }
    snapshots = {row["snapshot_identity"]: row for row in snapshot_series["snapshots"]}
    scenario_events: dict[str, list[dict[str, Any]]] = {
        scenario["id"]: [] for scenario in checked.value["scenarios"]
    }
    observations: dict[tuple[str, str], dict[str, Any]] = {}
    for event in trace["events"]:
        snapshot = snapshots[event["snapshot_after_identity"]]
        scenario_id = snapshot["scenario"]
        if scenario_id not in scenario_events:
            return False
        observation = event["observation"]
        if observation is None:
            scenario_events[scenario_id].append(event)
            continue
        identity = observation["metric_definition_identity"]
        metric = metrics.get(identity)
        key = (scenario_id, identity)
        if (
            metric is None
            or key in observations
            or observation
            != {
                "metric": metric["id"],
                "metric_definition_identity": identity,
                "window": metric["window"],
            }
        ):
            return False
        observations[key] = event
    if set(observations) != {
        (scenario_id, identity)
        for scenario_id in scenario_events
        for identity in metrics
    }:
        return False

    expected_samples: list[dict[str, Any]] = []
    for identity, metric in metrics.items():
        selector = metric["observation"]
        replications = 0
        for scenario_id, events in scenario_events.items():
            event = observations[scenario_id, identity]
            snapshot = snapshots[event["snapshot_after_identity"]]
            if selector["source"] == "event":
                values = [
                    fact["integer"]
                    for observed_event in events
                    if observed_event["outcome"]["id"] == selector["name"]
                    for fact in observed_event["facts"]
                    if fact["name"] == selector["member"] and fact["kind"] == "integer"
                ]
            else:
                if selector["name"] not in {"terminal", f"{scenario_id}:terminal"}:
                    continue
                values = [
                    row["value"]
                    for row in snapshot["values"]
                    if row["name"] == selector["member"]
                ]
            if len(values) != 1 or type(values[0]) is not int:
                return False
            value = values[0]
            replications += 1
            expected_samples.append(
                {
                    "metric": metric["id"],
                    "metric_definition_identity": identity,
                    "scenario": scenario_id,
                    "status": "value",
                    "value": value,
                    "unit": metric["unit"],
                    "logical_time": event["ordering_key"]["logical_time"],
                    "event_id": event["event_id"],
                    "snapshot_identity": snapshot["snapshot_identity"],
                    "window": metric["window"]["name"],
                    "dimensions": metric["dimensions"],
                    "replication_identity": scenario_id,
                    "source_kind": "simulated",
                    "provenance": {
                        "scenario": scenario_id,
                        "observation_source": selector["source"],
                        "observation_name": selector["name"],
                        "observation_member": selector["member"],
                    },
                    "within_target": metric["target"]["minimum"]
                    <= value
                    <= metric["target"]["maximum"],
                    "source": selector["source"],
                    "member": selector["member"],
                }
            )
        if replications == 0:
            return False
    expected_samples.sort(
        key=lambda row: (
            row["metric_definition_identity"].encode("utf-8"),
            row["replication_identity"].encode("utf-8"),
        )
    )
    if dataset["metric_definition_identities"] != sorted(metrics) or canonical_bytes(
        dataset["samples"]
    ) != canonical_bytes(cast(JsonValue, expected_samples)):
        return False
    failed_metrics = [
        sample["metric"] for sample in expected_samples if not sample["within_target"]
    ]
    return (
        primary_name == "experiment-verdict"
        and primary["outcome"] == "rejected"
        and primary["failed_metrics"] == failed_metrics
        if failed_metrics
        else primary_name == "evaluation-run" and primary["outcome"] == "accepted"
    )


def validate_experiment_artifact_set(
    checked: CheckedExperiment, artifacts: dict[str, dict[str, Any]]
) -> bool:
    """Revalidate exact semantic bindings across one Experiment artifact set."""
    try:
        if not all(
            validate_experiment_member(checked, name, value)
            for name, value in artifacts.items()
        ):
            return False
        resolved_runtime = _resolved_runtime_profile(checked)
        artifact_names = set(artifacts)
        if (
            artifacts.get("resolved-runtime-profile") != resolved_runtime.value
            or _unsupported_evaluator_requirement(
                checked, artifacts["evaluator-capability-manifest"]
            )
            is not None
        ):
            return False
        if artifact_names == _EXPERIMENT_RUNTIME_REFUSAL_NAMES:
            audit = artifacts["runtime-terminal-audit"]
            return (
                audit.get("experiment_identity") == checked.content_identity
                and audit.get("resolved_runtime_profile_identity")
                == resolved_runtime.content_identity
                and audit.get("root_event_map") == _expected_root_event_map(checked)
                and _terminal_audit_is_valid(
                    checked,
                    audit,
                    expected_root_map=_expected_root_event_map(checked),
                )
            )
        if artifact_names not in (
            _EXPERIMENT_SUCCESS_NAMES,
            _EXPERIMENT_VERDICT_NAMES,
        ):
            return False
        primary_name = (
            "evaluation-run" if "evaluation-run" in artifacts else "experiment-verdict"
        )
        primary = artifacts[primary_name]
        trace = artifacts["event-trace"]
        snapshot_series = artifacts["snapshot-series"]
        dataset = artifacts["metric-dataset"]
        expected_root_map = _expected_root_event_map(checked)
        expected_bindings = {
            "experiment_identity": checked.content_identity,
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "event_trace_identity": trace["content_identity"],
            "snapshot_series_identity": snapshot_series["content_identity"],
            "metric_dataset_identity": dataset["content_identity"],
        }
        if (
            any(primary.get(name) != value for name, value in expected_bindings.items())
            or primary.get("root_event_map") != expected_root_map
            or primary.get("terminal_statuses") != trace.get("terminal_statuses")
            or trace.get("experiment_identity") != checked.content_identity
            or trace.get("resolved_runtime_profile_identity")
            != resolved_runtime.content_identity
            or snapshot_series.get("experiment_identity") != checked.content_identity
            or snapshot_series.get("resolved_runtime_profile_identity")
            != resolved_runtime.content_identity
            or dataset.get("experiment_identity") != checked.content_identity
            or dataset.get("resolved_runtime_profile_identity")
            != resolved_runtime.content_identity
            or not _artifact_set_runtime_journals_are_valid(
                checked,
                trace,
                snapshot_series,
                resolved_runtime.content_identity,
                expected_root_map,
            )
            or not _terminal_statuses_are_valid(trace, snapshot_series)
        ):
            return False
        return _metric_dataset_matches_observations(
            checked, trace, snapshot_series, dataset, primary_name, primary
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False
