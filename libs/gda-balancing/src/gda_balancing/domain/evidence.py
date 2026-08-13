"""Evidence construction, replay, terminal audit, and set validation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
)
from gda_balancing.domain.artifacts import (
    verify_artifact,
)
from gda_balancing.domain.publication import PublicationMember
from gda_balancing.domain.operation_program import (
    guard_expanded_instruction_indices,
    instruction_evaluation_sites,
)
from gda_balancing.domain.runtime.scheduler import RuntimeScheduler
from gda_balancing.domain.experiment import (
    CheckedExperiment,
)
from gda_balancing.domain.evidence_replay import (
    ReplayInitializationProgramFault as _InitializationProgramFault,
    ReplayNamedRng as _NamedRng,
    admit_declared_value as _admit_declared_value,
    evaluate_initialization_programs as _evaluate_initialization_programs,
    execute_value_instruction as _execute_value_instruction,
    integer_compare as _integer_compare,
)
from gda_balancing.domain.runtime.projections import (
    RuntimeRefusalOutcome,
    artifact as _artifact,
    committed_event_projection as _committed_event_projection,
    empty_runtime_journal_identity as _empty_runtime_journal_identity,
    evaluator_manifest as _evaluator_manifest,
    event_catalog_record as _event_catalog_record,
    extend_runtime_journal_identity as _extend_runtime_journal_identity,
    formula_programs_reachable_from_entrypoints as _formula_programs_reachable_from_entrypoints,
    metric_definition_identity as _metric_definition_identity,
    named_value_rows as _named_value_rows,
    observation_event_id as _observation_event_id,
    operation_formula_evaluation_record as _operation_formula_evaluation_record,
    operation_formula_slot as _operation_formula_slot,
    ordered_root_events as _ordered_root_events,
    pending_event_projection as _pending_event_projection,
    projected_runtime_identity as _projected_runtime_identity,
    resolved_display_names as _resolved_display_names,
    resolved_runtime_profile as _resolved_runtime_profile,
    root_event_id as _root_event_id,
    reproduction_receipt as _reproduction_receipt,
    runtime_contract as _runtime_contract,
    runtime_journal_contract as _runtime_journal_contract,
    runtime_nodes as _runtime_nodes,
    scenario_transition_events as _scenario_transition_events,
    scheduled_event_id as _scheduled_event_id,
    scheduler_contract as _scheduler_contract,
)
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    selected_structured_value_index,
)


_INVALID_FORMULA_EVIDENCE = object()


def _evaluate_formula_evidence_result(
    checked: CheckedExperiment,
    formula: dict[str, Any],
    arguments: list[dict[str, Any]],
) -> JsonValue | object:
    """Independently evaluate one traced Formula from admitted RIR semantics."""
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(
            list[dict[str, Any]], checked.rir["selected_semantics"]["packages"]
        )
    }
    operations = {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, row["definition"]["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(
            list[dict[str, Any]], checked.rir["selected_semantics"]["operations"]
        )
    }
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
        operation = operations.get(
            (
                cast(str, reference.get("package")),
                cast(str, reference.get("version")),
                cast(str, reference.get("id")),
            )
        )
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


def _event_formula_evaluations_are_authoritative(
    checked: CheckedExperiment, event: dict[str, Any]
) -> bool:
    evaluations = event.get("formula_evaluations")
    if not isinstance(evaluations, list):
        return False
    bindings = cast(list[dict[str, Any]], checked.rir["formula_bindings"])
    formulas = {
        cast(str, row["identity"]): row
        for row in cast(list[dict[str, Any]], checked.rir["formulas"])
    }
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(
            list[dict[str, Any]], checked.rir["selected_semantics"]["packages"]
        )
    }
    operations = {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, row["definition"]["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(
            list[dict[str, Any]], checked.rir["selected_semantics"]["operations"]
        )
    }
    executions: dict[str, str] = {}
    entrypoint = event.get("entrypoint")
    operation_id = event.get("operation")
    if isinstance(operation_id, str):
        root_path = (
            cast(str, entrypoint["id"])
            if isinstance(entrypoint, dict)
            else f"scheduled:{event.get('schedule_call_site_identity')}"
        )
        executions[root_path] = operation_id
    for call in cast(list[dict[str, Any]], event.get("calls", [])):
        call_operation = call.get("operation")
        if not isinstance(call.get("site"), str) or not isinstance(
            call_operation, dict
        ):
            return False
        executions[cast(str, call["site"])] = cast(str, call_operation.get("id"))

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
        operation = operations.get(
            (
                cast(str, operation_reference["package"]),
                cast(str, operation_reference["version"]),
                cast(str, operation_reference["id"]),
            )
        )
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
            or executions.get(call_path) != operation_reference["id"]
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


def _authoritative_event_actual_values(
    checked: CheckedExperiment,
    event: dict[str, JsonValue],
    event_spec: dict[str, JsonValue],
    *,
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
    entrypoints = {cast(str, row["id"]): row for row in checked.rir["entrypoints"]}
    scenario_entrypoints: list[dict[str, Any]] = []
    actual_values: dict[bytes, Any] = {}
    try:
        for root_event in _scenario_transition_events(scenario):
            selected_entrypoint = entrypoints[cast(str, root_event["entrypoint"])]
            scenario_entrypoints.append(selected_entrypoint)
            contract = cast(
                dict[str, Any], selected_entrypoint["scenario_input_contract"]
            )
            for initializer in cast(list[dict[str, Any]], contract["initializers"]):
                identity = canonical_bytes(cast(JsonValue, initializer["target"]))
                value = initializer["value"]
                if identity in actual_values and actual_values[identity] != value:
                    return None
                actual_values[identity] = value
        for assignment in scenario["assignments"]:
            actual_values[canonical_bytes(cast(JsonValue, assignment["target"]))] = (
                assignment["value"]
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
        parent_index = cast(int, event["index"])
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
        state_before = {
            cast(str, row["name"]): row["value"]
            for row in cast(list[dict[str, JsonValue]], event["state_before"])
        }
        for identity, display_name in display_names.items():
            if (
                declarations[identity]["role"] == "state"
                and display_name in state_before
            ):
                actual_values[identity] = state_before[display_name]
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
            frame_identity=cast(str, event["snapshot_before_identity"]),
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


def _committed_event_arguments(
    checked: CheckedExperiment,
    event: dict[str, JsonValue],
    event_spec: dict[str, JsonValue],
    *,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> (
    tuple[
        dict[str, JsonValue],
        dict[str, dict[str, JsonValue]],
        dict[bytes, Any],
    ]
    | None
):
    actual_values = _authoritative_event_actual_values(
        checked,
        event,
        event_spec,
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
) -> (
    tuple[
        tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None,
        list[dict[str, JsonValue]],
    ]
    | None
):
    root_arguments = _committed_event_arguments(
        checked,
        parent_event,
        parent_spec,
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
    )
    parent_operation_id = parent_event.get("operation")
    if root_arguments is None or not isinstance(parent_operation_id, str):
        return None
    operations = {
        cast(str, row["definition"]["id"]): row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    formula_bindings_by_site = {
        cast(str, cast(dict[str, Any], binding["site"])["identity"]): binding
        for binding in cast(list[dict[str, Any]], checked.rir["formula_bindings"])
        if cast(dict[str, Any], binding["site"])["kind"] == "operation-slot"
    }
    root_operation = operations.get(parent_operation_id)
    if root_operation is None:
        return None
    declarations = _resolved_declarations(checked)
    display_names = _resolved_display_names(declarations)
    state: dict[bytes, JsonValue] = {
        identity: values_by_name[display_name]
        for identity, display_name in display_names.items()
        if display_name
        in (
            values_by_name := {
                cast(str, row["name"]): row["value"]
                for row in cast(
                    list[dict[str, JsonValue]], parent_event["state_before"]
                )
            }
        )
    }
    actual_values = root_arguments[2]
    calls = cast(list[dict[str, JsonValue]], parent_event["calls"])
    schedules = cast(list[dict[str, JsonValue]], parent_event["schedules"])
    draws = cast(list[dict[str, JsonValue]], parent_event["rng_draws"])
    draw_index = 0
    formula_evaluations: list[dict[str, JsonValue]] = []
    rng = _NamedRng(
        cast(int, checked.value["seed"]["value"]),
        cast(dict[str, Any], _runtime_contract(checked)["named_rng"]),
    )

    def consume_authoritative_draw(
        traced: dict[str, JsonValue],
    ) -> int | None:
        try:
            value, index, candidate, accepted = rng.draw(
                cast(str, traced["stream"]),
                cast(int, traced["minimum"]),
                cast(int, traced["maximum"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        expected = {
            "stream": traced["stream"],
            "index": index,
            "candidate_hex": rng.encode_candidate(candidate),
            "accepted": accepted,
            "minimum": traced["minimum"],
            "maximum": traced["maximum"],
            "value": value,
        }
        return value if traced == expected else None

    for prior_event in sorted(
        events_by_id.values(), key=lambda row: cast(int, row["index"])
    ):
        if cast(int, prior_event["index"]) >= cast(int, parent_event["index"]):
            break
        prior_record = catalog_by_id.get(cast(str, prior_event["event_id"]))
        if prior_record is None:
            return None
        if prior_record["scenario"] != scenario_id:
            continue
        if any(
            consume_authoritative_draw(draw) is None
            for draw in cast(list[dict[str, JsonValue]], prior_event["rng_draws"])
        ):
            return None
    numeric = cast(dict[str, Any], _runtime_contract(checked)["numeric"])
    node_contracts = _runtime_nodes(checked)
    structured_authority = selected_structured_value_index(
        cast(dict[str, Any], checked.rir["selected_semantics"]),
        kernel=checked.kernel,
    )
    structured_resource_limit = cast(
        int, checked.language_bundle["resources"]["max_rule_match_steps"]
    )
    schedule_identity = _scheduler_contract(checked)["call_site_identity"]["schedule"]

    def execute(
        operation: dict[str, Any],
        arguments: dict[str, JsonValue],
        state_references: dict[str, dict[str, JsonValue]],
        call_path: tuple[str, ...],
    ) -> tuple[
        str,
        JsonValue,
        tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None,
    ]:
        nonlocal draw_index
        operation_before = dict(state)
        variables: dict[str, Any] = dict(arguments)
        extensions = operation.get("extensions", {})
        snapshot_operands = (
            extensions.get("standard.snapshot-operands")
            if isinstance(extensions, dict)
            else None
        )
        if isinstance(snapshot_operands, dict):
            for row in cast(
                list[dict[str, Any]], snapshot_operands.get("operands", [])
            ):
                identity = canonical_bytes(cast(JsonValue, row["resolved_symbol"]))
                if identity not in actual_values:
                    return "", None, None
                variables[cast(str, row["name"])] = actual_values[identity]
        operation_results: dict[str, JsonValue] = {}
        outcome = cast(str, operation["default_outcome"])
        evaluation_sites = instruction_evaluation_sites(operation)
        for instruction_index, instruction in enumerate(
            cast(list[dict[str, Any]], operation["body"])
        ):
            evaluation_site_identity = evaluation_sites.get(instruction_index)
            node_contract = node_contracts[instruction["node"]]
            operator = node_contract["semantics"]["operator"]
            if operator == "invoke-operation":
                child = operations.get(cast(str, instruction["operation"]["id"]))
                if child is None:
                    return "", None, None
                child_arguments: dict[str, JsonValue] = {}
                child_state_references: dict[str, dict[str, JsonValue]] = {}
                for binding in instruction["arguments"]:
                    operand = binding["operand"]
                    name = cast(str, binding["port"])
                    if operand["kind"] == "port":
                        source = cast(str, operand["port"])
                        child_arguments[name] = cast(JsonValue, variables[source])
                        if source in state_references:
                            child_state_references[name] = state_references[source]
                    elif operand["kind"] == "local":
                        child_arguments[name] = cast(
                            JsonValue, variables[operand["local"]]
                        )
                    else:
                        child_arguments[name] = cast(JsonValue, operand["literal"])
                child_path = (*call_path, cast(str, instruction["site"]))
                child_outcome, child_result, found = execute(
                    child,
                    child_arguments,
                    child_state_references,
                    child_path,
                )
                if found is not None:
                    return "", None, found
                call = next(
                    (
                        row
                        for row in calls
                        if row["site"] == "/".join(child_path)
                        and cast(dict[str, JsonValue], row["operation"])["id"]
                        == child["id"]
                    ),
                    None,
                )
                if (
                    call is None
                    or cast(dict[str, JsonValue], call["outcome"])["id"]
                    != child_outcome
                ):
                    return "", None, None
                result_binding = instruction["result"]
                if result_binding["kind"] == "local":
                    variables[result_binding["name"]] = child_result
                elif result_binding["kind"] == "operation-result":
                    operation_results[instruction["site"]] = child_result
                for alias, target in state_references.items():
                    variables[alias] = state[canonical_bytes(cast(JsonValue, target))]
                mapping = next(
                    row
                    for row in instruction["outcomes"]
                    if row["outcome"] == child_outcome
                )
                if mapping["action"]["kind"] == "propagate":
                    outcome = cast(str, mapping["action"]["outcome"])
                    break
                continue
            if operator == "schedule-operation":
                child_arguments = {}
                child_state_references = {}
                for binding in instruction["arguments"]:
                    operand = binding["operand"]
                    name = cast(str, binding["port"])
                    if operand["kind"] == "port":
                        source = cast(str, operand["port"])
                        child_arguments[name] = cast(JsonValue, variables[source])
                        if source in state_references:
                            child_state_references[name] = state_references[source]
                    elif operand["kind"] == "local":
                        child_arguments[name] = cast(
                            JsonValue, variables[operand["local"]]
                        )
                    else:
                        child_arguments[name] = cast(JsonValue, operand["literal"])
                call_site_identity = content_identity(
                    cast(str, schedule_identity["domain"]),
                    cast(
                        JsonValue,
                        {
                            "parent_event_id": parent_event["event_id"],
                            "parent_operation": operation["id"],
                            "site": instruction["site"],
                            "operation": instruction["operation"],
                        },
                    ),
                )
                if (
                    target_schedule is not None
                    and target_schedule["call_site_identity"] == call_site_identity
                    and target_schedule["call_path"] == "/".join(call_path)
                ):
                    return "", None, (child_arguments, child_state_references)
                scheduled = next(
                    (
                        row
                        for row in schedules
                        if row["call_site_identity"] == call_site_identity
                        and row["call_path"] == "/".join(call_path)
                    ),
                    None,
                )
                if scheduled is None:
                    return "", None, None
                variables[instruction["result"]["name"]] = scheduled["event_id"]
                continue
            if operator == "cancel-event":
                continue
            if operator == "gameplay-precondition":
                if not _integer_compare(
                    node_contract["semantics"]["comparison"],
                    cast(int, variables[instruction["left"]]),
                    cast(int, variables[instruction["right"]]),
                ):
                    outcome = cast(str, instruction["outcome"])
                    break
            elif operator == "typed-require":
                if variables[instruction["condition"]] != instruction["expected"]:
                    return "", None, None
            elif operator == "guarded-outcome-block":
                if variables[instruction["condition"]]:
                    guarded_operation = {
                        "body": instruction["body"],
                        "default_outcome": instruction["outcome"],
                        "extensions": {},
                        "id": operation["id"],
                        "outcomes": list(operation["outcomes"]),
                        "result": {"source": {"kind": "unit"}},
                    }
                    guarded_outcome, _guarded_result, found = execute(
                        guarded_operation,
                        variables,
                        state_references,
                        call_path,
                    )
                    if found is not None:
                        return "", None, found
                    if guarded_outcome != instruction["outcome"]:
                        return "", None, None
                    outcome = cast(str, instruction["outcome"])
                    break
            elif operator == "named-integer-draw":
                if draw_index >= len(draws):
                    return "", None, None
                draw = draws[draw_index]
                draw_index += 1
                if (
                    draw["stream"] != instruction["stream"]
                    or draw["minimum"] != instruction["minimum"]
                    or draw["maximum"] != instruction["maximum"]
                ):
                    return "", None, None
                value = consume_authoritative_draw(draw)
                if value is None:
                    return "", None, None
                variables[instruction["target"]] = value
            elif node_contract["family"] == "expression":
                _execute_value_instruction(
                    instruction,
                    variables,
                    numeric,
                    node_contract,
                    structured_authority=structured_authority,
                    structured_resource_limit=structured_resource_limit,
                )
            elif operator in {"state-integer-subtract", "state-write"}:
                formal = cast(str, instruction["symbol"])
                target = canonical_bytes(cast(JsonValue, state_references[formal]))
                declaration = declarations.get(target)
                if declaration is None:
                    return "", None, None
                state[target] = _admit_declared_value(
                    cast(int, state[target])
                    - cast(int, variables[instruction["value"]])
                    if operator == "state-integer-subtract"
                    else variables[instruction["value"]],
                    numeric,
                    declaration,
                    structured_authority=structured_authority,
                    structured_resource_limit=structured_resource_limit,
                )
                for alias, alias_target in state_references.items():
                    if canonical_bytes(cast(JsonValue, alias_target)) == target:
                        variables[alias] = state[target]
            else:
                return "", None, None
            if (
                evaluation_site_identity is not None
                and evaluation_sites.get(instruction_index + 1)
                != evaluation_site_identity
            ):
                binding = formula_bindings_by_site.get(evaluation_site_identity)
                if binding is None:
                    return "", None, None
                evaluation = _operation_formula_evaluation_record(
                    operation,
                    binding,
                    variables,
                    evaluation_site_identity=evaluation_site_identity,
                    frame_identity=cast(
                        JsonValue, parent_event["snapshot_before_identity"]
                    ),
                    call_path=call_path,
                )
                if evaluation is None:
                    return "", None, None
                formula_evaluations.append(evaluation)
        outcome_definition = next(
            row for row in operation["outcomes"] if row["id"] == outcome
        )
        if outcome_definition["state_policy"] == "rollback":
            state.clear()
            state.update(operation_before)
        result_source = operation["result"]["source"]
        if outcome_definition["kind"] != "success":
            result: JsonValue = None
        elif result_source["kind"] in {"local", "port"}:
            result = cast(JsonValue, variables[result_source["name"]])
        elif result_source["kind"] == "operation-result":
            result = operation_results[result_source["site"]]
        else:
            result = None
        return outcome, result, None

    root_state_references = {name: target for name, target in root_arguments[1].items()}
    root_path = (
        (cast(str, cast(dict[str, JsonValue], parent_event["entrypoint"])["id"]),)
        if parent_event.get("entrypoint") is not None
        else (f"scheduled:{parent_spec['call_site_identity']}",)
    )
    try:
        replayed_outcome, _result, found = execute(
            root_operation,
            root_arguments[0],
            root_state_references,
            root_path,
        )
    except (
        KeyError,
        OverflowError,
        StopIteration,
        StructuredValueFault,
        TypeError,
        ValueError,
    ):
        return None
    if not replayed_outcome and found is None:
        return None
    return found, formula_evaluations


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
    return replayed[0] if replayed is not None else None


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
    return replayed is not None and evaluations == replayed[1]


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
    operation = next(
        (
            row["definition"]
            for row in checked.rir["selected_semantics"]["operations"]
            if row["definition"]["id"] == schedule_parent_operation
        ),
        None,
    )
    if operation is None:
        return False
    if schedule_parent_operation != parent_operation and not any(
        call.get("site") == schedule_call_path
        and cast(dict[str, JsonValue], call["operation"]).get("id")
        == schedule_parent_operation
        for call in cast(list[dict[str, JsonValue]], parent_event["calls"])
    ):
        return False
    schedule_identity = _scheduler_contract(checked)["call_site_identity"]["schedule"]
    matching_instructions = []
    for instruction in operation["body"]:
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
    traced_arguments = {
        cast(str, row["name"]): cast(JsonValue, row["value"])
        for row in scheduled_argument_rows
    }
    traced_state_references = {
        cast(str, row["name"]): cast(dict[str, JsonValue], row["target"])
        for row in scheduled_state_reference_rows
    }
    instruction_ports = {
        cast(str, binding["port"]) for binding in instruction["arguments"]
    }
    if (
        set(traced_arguments) != instruction_ports
        or not set(traced_state_references) <= instruction_ports
    ):
        return False
    parent_arguments = (
        _committed_event_arguments(
            checked,
            parent_event,
            parent_spec,
            scenario_id=cast(str, record["scenario"]),
            catalog_by_id=catalog_by_id,
            events_by_id=events_by_id,
        )
        if schedule_parent_operation == parent_operation
        else None
    )
    direct_arguments = parent_arguments[0] if parent_arguments is not None else {}
    direct_state_references = (
        parent_arguments[1] if parent_arguments is not None else {}
    )
    for binding in instruction["arguments"]:
        name = cast(str, binding["port"])
        operand = cast(dict[str, Any], binding["operand"])
        if operand["kind"] == "port":
            source = cast(str, operand["port"])
            if parent_arguments is not None and (
                source not in direct_arguments
                or traced_arguments[name] != direct_arguments[source]
                or traced_state_references.get(name)
                != direct_state_references.get(source)
            ):
                return False
        elif operand["kind"] == "literal":
            if (
                traced_arguments[name] != operand["literal"]
                or name in traced_state_references
            ):
                return False
        elif operand["kind"] == "local":
            if name in traced_state_references:
                return False
        else:
            return False
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
) -> dict[str, PublicationMember]:
    """Prepare the complete terminal-only artifact set for runtime refusal."""
    report = outcome.report
    if report.stage != "runtime":
        raise ValueError("terminal audit requires one runtime refusal")
    evaluator = _evaluator_manifest(checked)
    resolved_runtime = _resolved_runtime_profile(checked, evaluator)
    reproduction = _reproduction_receipt(checked, evaluator, resolved_runtime)
    diagnostic = report.diagnostics[0]
    audit = _artifact(
        checked,
        "runtime-terminal-audit",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "evaluator_manifest_identity": evaluator.content_identity,
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
                "reproduction_receipt_identity": reproduction.content_identity,
            },
        ),
    )
    return {
        "runtime-terminal-audit": audit,
        "reproduction-receipt": reproduction,
        "resolved-runtime-profile": resolved_runtime,
        "evaluator-capability-manifest": evaluator,
    }


def validate_experiment_member(
    checked: CheckedExperiment, logical_name: str, value: dict[str, Any]
) -> bool:
    """Re-admit one prepared Experiment output against the exact LDB."""
    del logical_name
    if not verify_artifact(value, checked.language_bundle):
        return False
    kind = value.get("artifact_kind")
    if kind == "event-trace":
        return all(
            _event_formula_evaluations_are_authoritative(checked, event)
            for event in cast(list[dict[str, Any]], value.get("events", []))
        )
    if kind == "runtime-terminal-audit":
        return all(
            _event_formula_evaluations_are_authoritative(checked, event)
            for event in cast(
                list[dict[str, Any]], value.get("committed_trace_prefix", [])
            )
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
        or any(
            not _event_formula_evaluations_are_authoritative(checked, event)
            for event in events
        )
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


def _formula_charge_through_evaluation_site(
    checked: CheckedExperiment,
    *,
    phase: str,
    evaluation_site_identity: str | None,
    selected_entrypoints: Sequence[dict[str, Any]],
) -> int | None:
    if evaluation_site_identity is None:
        return None
    programs = _formula_programs_reachable_from_entrypoints(
        checked,
        selected_entrypoints,
        phase=phase,
    )
    program_targets = {
        canonical_bytes(cast(JsonValue, program["target"])) for program in programs
    }
    completed_targets: set[bytes] = set()
    pending = list(programs)
    consumed = 0
    while pending:
        progressed = False
        for program in list(pending):
            dependencies = {
                canonical_bytes(cast(JsonValue, operand["resolved_symbol"]))
                for row in cast(list[dict[str, Any]], program["inputs"])
                if (operand := cast(dict[str, Any], row["operand"]))["kind"]
                != "literal"
                and canonical_bytes(cast(JsonValue, operand["resolved_symbol"]))
                in program_targets
            }
            if not dependencies <= completed_targets:
                continue
            consumed += cast(int, program["resource_bounds"]["max_steps"])
            program_sites = {
                cast(str, cast(dict[str, Any], program["site"])["identity"]),
                *(
                    cast(str, row["evaluation_site_identity"])
                    for row in cast(list[dict[str, Any]], program["body"])
                ),
            }
            if evaluation_site_identity in program_sites:
                return consumed
            completed_targets.add(canonical_bytes(cast(JsonValue, program["target"])))
            pending.remove(program)
            progressed = True
        if not progressed:
            return None
    return None


def _attempted_operation_charge(
    checked: CheckedExperiment,
    refusing_event: dict[str, Any],
    refusing_event_spec: dict[str, Any],
    *,
    node_steps_before_operation: int,
    bounds: dict[str, int],
    require_budget_breach: bool,
) -> int | None:
    evaluation_site_identity = refusing_event.get("evaluation_site_identity")
    target_instruction_index = refusing_event.get("instruction_index")
    target_path = refusing_event.get("call_path")
    if (
        not isinstance(target_path, str)
        or not isinstance(target_instruction_index, int)
        and not isinstance(evaluation_site_identity, str)
    ):
        return None
    operations = {
        cast(str, row["definition"]["id"]): row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    if refusing_event_spec["kind"] == "transition-invocation":
        entrypoint = next(
            (
                row
                for row in checked.rir["entrypoints"]
                if row["id"] == refusing_event_spec["entrypoint"]
            ),
            None,
        )
        root_operation_id = (
            cast(str, entrypoint["operation"]["id"]) if entrypoint is not None else None
        )
    elif refusing_event_spec["kind"] == "scheduled-transition":
        operation_reference = refusing_event_spec.get("operation")
        root_operation_id = (
            cast(str, operation_reference["id"])
            if isinstance(operation_reference, dict)
            and isinstance(operation_reference.get("id"), str)
            else None
        )
    else:
        return None
    root_operation = operations.get(root_operation_id) if root_operation_id else None
    if root_operation is None:
        return None
    root_path = target_path.split("/", 1)[0]
    calls = cast(list[dict[str, JsonValue]], refusing_event["attempted_calls"])
    used_calls: set[int] = set()
    node_contracts = _runtime_nodes(checked)
    event_charge = 0
    node_steps = node_steps_before_operation

    def is_target(
        operation: dict[str, Any],
        call_path: str,
        instruction_index: int,
        sites: dict[int, str],
    ) -> bool:
        return (
            call_path == target_path
            and operation["id"] == refusing_event["operation"]
            and (
                instruction_index == target_instruction_index
                if isinstance(target_instruction_index, int)
                else sites.get(instruction_index) == evaluation_site_identity
            )
        )

    def charge_instruction(
        operation: dict[str, Any],
        operation_charge: int,
        instruction: dict[str, Any],
    ) -> tuple[int, bool]:
        nonlocal event_charge, node_steps
        amount = cast(
            int, node_contracts[instruction["node"]]["resource_charge"]["amount"]
        )
        operation_charge += amount
        event_charge += amount
        node_steps += amount
        breached = (
            operation_charge > cast(int, operation["resource_bounds"]["max_steps"])
            or event_charge > bounds["max_event_steps"]
            or node_steps > bounds["max_node_steps"]
        )
        return operation_charge, breached

    def completed_invocation(
        instruction: dict[str, Any], parent_path: str
    ) -> dict[str, Any] | None:
        child_path = f"{parent_path}/{instruction['site']}"
        child = operations.get(cast(str, instruction["operation"]["id"]))
        call_rows = [
            (index, row)
            for index, row in enumerate(calls)
            if row["site"] == child_path
            and cast(dict[str, JsonValue], row["operation"])["id"]
            == instruction["operation"]["id"]
        ]
        if child is None or len(call_rows) != 1:
            return None
        call_index, call = call_rows[0]
        child_outcome = cast(str, cast(dict[str, JsonValue], call["outcome"])["id"])
        if not completed_operation(child, child_path, child_outcome):
            return None
        mapping = next(
            (row for row in instruction["outcomes"] if row["outcome"] == child_outcome),
            None,
        )
        if mapping is None:
            return None
        used_calls.add(call_index)
        return cast(dict[str, Any], mapping["action"])

    def completed_operation(
        operation: dict[str, Any],
        call_path: str,
        expected_outcome: str,
    ) -> bool:
        operation_charge = 0
        outcome = cast(str, operation["default_outcome"])
        sites = instruction_evaluation_sites(operation)
        body = cast(list[dict[str, Any]], operation["body"])
        expanded_indices = guard_expanded_instruction_indices(body)
        for body_index, instruction in enumerate(body):
            instruction_index = expanded_indices[body_index]
            operation_charge, breached = charge_instruction(
                operation,
                operation_charge,
                instruction,
            )
            if breached or is_target(operation, call_path, instruction_index, sites):
                return False
            operator = node_contracts[instruction["node"]]["semantics"]["operator"]
            if operator == "invoke-operation":
                action = completed_invocation(instruction, call_path)
                if action is None:
                    return False
                if action["kind"] == "propagate":
                    outcome = cast(str, action["outcome"])
                    break
            elif operator == "guarded-outcome-block":
                if instruction["outcome"] != expected_outcome:
                    continue
                for guard_instruction in cast(
                    list[dict[str, Any]], instruction["body"]
                ):
                    operation_charge, breached = charge_instruction(
                        operation,
                        operation_charge,
                        guard_instruction,
                    )
                    if breached:
                        return False
                    guard_operator = node_contracts[guard_instruction["node"]][
                        "semantics"
                    ]["operator"]
                    if guard_operator != "invoke-operation":
                        continue
                    action = completed_invocation(guard_instruction, call_path)
                    if action is None or action["kind"] == "propagate":
                        return False
                outcome = expected_outcome
                break
            elif (
                operator == "gameplay-precondition"
                and instruction["outcome"] == expected_outcome
            ):
                outcome = expected_outcome
                break
        return outcome == expected_outcome

    def charge_to_target(
        operation: dict[str, Any],
        call_path: str,
    ) -> bool:
        operation_charge = 0
        sites = instruction_evaluation_sites(operation)
        body = cast(list[dict[str, Any]], operation["body"])
        expanded_indices = guard_expanded_instruction_indices(body)
        for body_index, instruction in enumerate(body):
            instruction_index = expanded_indices[body_index]
            operation_charge, breached = charge_instruction(
                operation,
                operation_charge,
                instruction,
            )
            target = is_target(operation, call_path, instruction_index, sites)
            if breached or target:
                return target and (breached or not require_budget_breach)
            operator = node_contracts[instruction["node"]]["semantics"]["operator"]
            if operator == "guarded-outcome-block":
                guard_body = cast(list[dict[str, Any]], instruction["body"])
                guard_start = instruction_index + 1
                guard_stop = guard_start + len(guard_body)
                target_is_directly_in_guard = (
                    call_path == target_path
                    and operation["id"] == refusing_event["operation"]
                    and isinstance(target_instruction_index, int)
                    and guard_start <= target_instruction_index < guard_stop
                )
                target_is_in_guard_call = any(
                    node_contracts[guard_instruction["node"]]["semantics"]["operator"]
                    == "invoke-operation"
                    and (
                        target_path == f"{call_path}/{guard_instruction['site']}"
                        or target_path.startswith(
                            f"{call_path}/{guard_instruction['site']}/"
                        )
                    )
                    for guard_instruction in guard_body
                )
                target_is_in_guard = (
                    target_is_directly_in_guard or target_is_in_guard_call
                )
                if not target_is_in_guard:
                    continue
                for guard_offset, guard_instruction in enumerate(guard_body):
                    operation_charge, breached = charge_instruction(
                        operation,
                        operation_charge,
                        guard_instruction,
                    )
                    guard_index = guard_start + guard_offset
                    target = is_target(operation, call_path, guard_index, sites)
                    if breached or target:
                        return target and (breached or not require_budget_breach)
                    guard_operator = node_contracts[guard_instruction["node"]][
                        "semantics"
                    ]["operator"]
                    if guard_operator != "invoke-operation":
                        continue
                    child_path = f"{call_path}/{guard_instruction['site']}"
                    child = operations.get(
                        cast(str, guard_instruction["operation"]["id"])
                    )
                    if child is None:
                        return False
                    if target_path == child_path or target_path.startswith(
                        f"{child_path}/"
                    ):
                        return charge_to_target(child, child_path)
                    action = completed_invocation(guard_instruction, call_path)
                    if action is None or action["kind"] == "propagate":
                        return False
                return False
            if operator != "invoke-operation":
                continue
            child_path = f"{call_path}/{instruction['site']}"
            child = operations.get(cast(str, instruction["operation"]["id"]))
            if child is None:
                return False
            if target_path == child_path or target_path.startswith(f"{child_path}/"):
                return charge_to_target(child, child_path)
            action = completed_invocation(instruction, call_path)
            if action is None or action["kind"] == "propagate":
                return False
        return False

    reached_target = charge_to_target(root_operation, root_path)
    if not reached_target or used_calls != set(range(len(calls))):
        return None
    return event_charge


def _terminal_audit_is_valid(
    checked: CheckedExperiment,
    audit: dict[str, Any],
    *,
    expected_root_map: list[dict[str, JsonValue]],
    reproduction_identity: str,
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
        row["code"]
        for row in checked.language_bundle["diagnostics"]
        if row["stage"] == "runtime"
    }
    if (
        audit.get("terminal_condition") != scenario["terminal_condition"]
        or audit.get("reproduction_receipt_identity") != reproduction_identity
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
        or any(
            not _event_formula_evaluations_are_authoritative(checked, event)
            for event in events
        )
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
    if any(
        (record := catalog_by_id.get(cast(str, event["event_id"]))) is None
        or not _event_formula_evaluations_match_replay(
            checked,
            cast(dict[str, JsonValue], event),
            record,
            catalog_by_id=catalog_by_id,
            events_by_id=events_by_id,
        )
        for event in events
    ):
        return False
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
        metric = (
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
            metric is None
            or _metric_definition_identity(metric) != metric_identity
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
    evaluation_site_identity = cast(
        str | None, refusing_event.get("evaluation_site_identity")
    )
    scenario = next(
        row for row in checked.value["scenarios"] if row["id"] == scenario_id
    )
    resolved_entrypoints = {
        cast(str, row["id"]): row for row in checked.rir["entrypoints"]
    }
    selected_entrypoints = [
        resolved_entrypoints[cast(str, event["entrypoint"])]
        for event in _scenario_transition_events(scenario)
    ]
    event_formula_programs = _formula_programs_reachable_from_entrypoints(
        checked,
        selected_entrypoints,
        phase="event",
    )
    event_formula_charge = sum(
        cast(int, program["resource_bounds"]["max_steps"])
        for program in event_formula_programs
    )
    event_formula_fault_charge = _formula_charge_through_evaluation_site(
        checked,
        phase="event",
        evaluation_site_identity=evaluation_site_identity,
        selected_entrypoints=selected_entrypoints,
    )
    observation_formula_fault_charge = _formula_charge_through_evaluation_site(
        checked,
        phase="observation",
        evaluation_site_identity=evaluation_site_identity,
        selected_entrypoints=selected_entrypoints,
    )
    if refusing_event_spec["kind"] == "observation":
        exact_event_steps = 0
        exact_node_steps = cast(int, ledger["node_steps"])
    elif boundary_formula_refusal:
        if observation_formula_fault_charge is None:
            return False
        exact_event_steps = cast(int, ledger["event_steps"])
        exact_node_steps = (
            cast(int, ledger["node_steps"]) + observation_formula_fault_charge
        )
    elif event_formula_fault_charge is not None:
        exact_event_steps = 0
        exact_node_steps = cast(int, ledger["node_steps"]) + event_formula_fault_charge
    else:
        attempted_operation_charge = _attempted_operation_charge(
            checked,
            refusing_event,
            refusing_event_spec,
            node_steps_before_operation=(
                cast(int, ledger["node_steps"]) + event_formula_charge
            ),
            bounds=bounds,
            require_budget_breach=(diagnostic["code"] == "runtime.step_limit_exceeded"),
        )
        if attempted_operation_charge is None:
            return False
        exact_event_steps = attempted_operation_charge
        exact_node_steps = (
            cast(int, ledger["node_steps"]) + event_formula_charge + exact_event_steps
        )
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
        evaluator = _evaluator_manifest(checked)
        resolved_runtime = _resolved_runtime_profile(checked, evaluator)
        reproduction = _reproduction_receipt(checked, evaluator, resolved_runtime)
        common = {
            "reproduction-receipt",
            "resolved-runtime-profile",
            "evaluator-capability-manifest",
        }
        primary_names = set(artifacts) - common
        if (
            artifacts.get("evaluator-capability-manifest") != evaluator.value
            or artifacts.get("resolved-runtime-profile") != resolved_runtime.value
            or artifacts.get("reproduction-receipt") != reproduction.value
        ):
            return False
        if primary_names == {"runtime-terminal-audit"}:
            audit = artifacts["runtime-terminal-audit"]
            return (
                audit.get("experiment_identity") == checked.content_identity
                and audit.get("resolved_runtime_profile_identity")
                == resolved_runtime.content_identity
                and audit.get("evaluator_manifest_identity")
                == evaluator.content_identity
                and audit.get("root_event_map") == _expected_root_event_map(checked)
                and _terminal_audit_is_valid(
                    checked,
                    audit,
                    expected_root_map=_expected_root_event_map(checked),
                    reproduction_identity=reproduction.content_identity,
                )
            )
        if primary_names not in (
            {
                "evaluation-run",
                "event-trace",
                "snapshot-series",
                "metric-dataset",
            },
            {
                "experiment-verdict",
                "event-trace",
                "snapshot-series",
                "metric-dataset",
            },
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
            "reproduction_receipt_identity": reproduction.content_identity,
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
            or cast(dict[str, Any], dataset.get("source_provenance", {})).get(
                "resolved_runtime_profile_identity"
            )
            != resolved_runtime.content_identity
            or cast(dict[str, Any], dataset.get("source_provenance", {})).get(
                "evaluator_manifest_identity"
            )
            != evaluator.content_identity
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
        event_ids = {
            event["event_id"] for event in cast(list[dict[str, Any]], trace["events"])
        }
        snapshot_ids = {
            snapshot["snapshot_identity"]
            for snapshot in cast(list[dict[str, Any]], snapshot_series["snapshots"])
        }
        metric_identities = sorted(
            _metric_definition_identity(metric) for metric in checked.value["metrics"]
        )
        return dataset.get("metric_definition_identities") == metric_identities and all(
            sample.get("event_id") in event_ids
            and sample.get("snapshot_identity") in snapshot_ids
            and sample.get("metric_definition_identity") in metric_identities
            and cast(dict[str, Any], sample.get("provenance", {})).get("scenario")
            == sample.get("scenario")
            for sample in cast(list[dict[str, Any]], dataset["samples"])
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False
