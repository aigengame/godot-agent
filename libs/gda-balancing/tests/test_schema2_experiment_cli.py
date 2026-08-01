"""Public RPG Experiment tracer for Standard Schema 2.0 (#540)."""

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.commands.experiment as experiment_command_module
import gda_balancing.schema2.authority as authority_module
import gda_balancing.schema2.experiment as experiment_runtime_module
import gda_balancing.schema2.model as model_module
from gda_balancing.schema2.canonical import canonical_bytes, content_identity
from gda_balancing.schema2.surface import descriptor_identity

_EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "schema2" / "rpg-combat-cast"
_AUTHORITY_DIR = (
    Path(__file__).parents[1] / "src" / "gda_balancing" / "schema2" / "authorities"
)


def test_experiment_conformance_uses_only_prepared_public_documents():
    for descriptor in (
        experiment_command_module.EXPERIMENT_CHECK,
        experiment_command_module.EXPERIMENT_RUN,
    ):
        assert descriptor.fixtures.valid_document is None
        assert descriptor.fixtures.prepare_valid_document is not None
        assert descriptor.fixtures.has_valid_document is True


def test_tutorial_tuning_values_are_not_package_conformance_configuration():
    specification = json.loads(
        (_EXAMPLE_DIR / "experiment.json").read_text(encoding="utf-8")
    )
    tutorial_values = {
        row["target"]["name"]: row["value"]
        for row in specification["scenarios"][0]["assignments"]
    }
    _kernel, language_bundle = authority_module.load_authorities()
    combat_vectors = next(
        row
        for row in language_bundle.package_conformance_vector_sets
        if row["package_id"] == "game.combat"
    )
    positive = next(
        row
        for row in combat_vectors["vector_definitions"]
        if row["id"] == "game.combat.cast.positive"
    )
    vector_values = {row["name"]: row["value"] for row in positive["input"]["values"]}

    assert {
        name: tutorial_values[name]
        for name in ("action_cost", "accuracy", "base_damage")
    } == {
        "action_cost": 9,
        "accuracy": 25,
        "base_damage": 45,
    }
    assert {
        name: vector_values[name] for name in ("action_cost", "accuracy", "base_damage")
    } == {
        "action_cost": 8,
        "accuracy": 20,
        "base_damage": 40,
    }


def _rpg_value(name: str, role: str) -> dict[str, Any]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 1000},
        "numeric_policy": "exact-int64",
        "value_policy": {
            "mode": (
                "experiment-required"
                if role not in {"derived", "output", "random"}
                else "none"
            )
        },
    }


def _rpg_model_source() -> dict[str, Any]:
    return json.loads((_EXAMPLE_DIR / "model-source.json").read_text(encoding="utf-8"))


def _metric_contract(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        **metric,
        "dimensions": [],
        "window": {"kind": "scenario", "name": "terminal-event"},
        "aggregation": "single",
        "replication": {"unit": "scenario"},
        "missing": "refuse",
        "censoring": "none",
    }


def _member(receipt: dict[str, Any], logical_name: str) -> dict[str, Any]:
    locator = next(
        item["locator"]
        for item in receipt["member_locators"]
        if item["logical_name"] == logical_name
    )
    return json.loads(Path(locator).read_text(encoding="utf-8"))


def _reference_compare(comparison: str, left: int, right: int) -> bool:
    if comparison == "greater-than-or-equal":
        return left >= right
    if comparison == "less-than":
        return left < right
    if comparison == "less-than-or-equal":
        return left <= right
    raise AssertionError(f"unsupported comparison in authority: {comparison}")


def _reference_rng_draw(
    contract: dict[str, Any],
    seed: int,
    stream: str,
    minimum: int,
    maximum: int,
    states: dict[str, int],
    indices: dict[str, int],
) -> dict[str, Any]:
    mask = (1 << contract["word_bits"]) - 1
    if stream not in states:
        derivation = contract["stream_derivation"]
        digest = hashlib.sha256(
            stream.encode(contract["stream_name_encoding"])
        ).digest()
        digest_slice = derivation["digest_slice"]
        start = digest_slice["offset"]
        end = start + digest_slice["length"]
        states[stream] = (
            seed
            + int.from_bytes(
                digest[start:end],
                derivation["byte_order"],
            )
        ) & mask
        indices[stream] = 0
    transition = contract["state_transition"]
    state = (states[stream] + int(transition["increment_hex"], 16)) & mask
    states[stream] = state
    candidate = state
    for step in transition["mix_steps"]:
        candidate ^= candidate >> step["xor_shift_right"]
        if "multiply_hex" in step:
            candidate = (candidate * int(step["multiply_hex"], 16)) & mask
    index = indices[stream]
    indices[stream] = index + 1
    value = minimum + candidate % (maximum - minimum + 1)
    candidate_width = contract["candidate_encoding"]["width_bits"] // 4
    return {
        "stream": stream,
        "index": index,
        "candidate_hex": f"{candidate:0{candidate_width}x}",
        "accepted": True,
        "minimum": minimum,
        "maximum": maximum,
        "value": value,
    }


def _reference_fact_rows(values: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in sorted(values):
        value = values[name]
        if isinstance(value, bool):
            rows.append({"name": name, "kind": "boolean", "boolean": value})
        else:
            rows.append({"name": name, "kind": "integer", "integer": value})
    return rows


class _ReferenceRuntimeRefusal(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.operation: str | None = None
        self.call_path: str | None = None
        self.call_site_identity: str | None = None


def _reference_execute_event(
    kernel: dict[str, Any],
    operation: dict[str, Any],
    operations: dict[str, dict[str, Any]],
    scenario: dict[str, Any],
    *,
    seed: int,
    state_names: set[str] | None = None,
    resolved_entrypoint: dict[str, Any] | None = None,
    resolved_declarations: list[dict[str, Any]] | None = None,
    resolved_call_sites: list[dict[str, Any]] | None = None,
    resolved_initialization_programs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    runtime = kernel["meta_format"]["runtime_program"]
    numeric = runtime["numeric"]
    nodes = {row["id"]: row for row in runtime["nodes"]}
    variables: dict[str | tuple[str, str, str], Any]
    state_targets: set[str | tuple[str, str, str]]
    display_names: dict[str | tuple[str, str, str], str]
    if resolved_entrypoint is not None:
        assert resolved_declarations is not None
        declarations = {
            (
                row["resolved_symbol"]["model"],
                row["resolved_symbol"]["module"],
                row["resolved_symbol"]["name"],
            ): row
            for row in resolved_declarations
        }
        variables = {
            (
                row["target"]["model"],
                row["target"]["module"],
                row["target"]["name"],
            ): row["value"]
            for row in resolved_entrypoint["scenario_input_contract"]["initializers"]
        }
        variables.update(
            {
                (
                    row["target"]["model"],
                    row["target"]["module"],
                    row["target"]["name"],
                ): row["value"]
                for row in scenario["assignments"]
            }
        )
        pending_programs = list(resolved_initialization_programs or [])
        while pending_programs:
            progressed = False
            for program in list(pending_programs):
                values: dict[str, int] = {}
                ready = True
                for row in program["inputs"]:
                    operand = row["operand"]
                    if operand["kind"] == "literal":
                        values[row["name"]] = operand["value"]
                        continue
                    symbol = operand["resolved_symbol"]
                    coordinate = (
                        symbol["model"],
                        symbol["module"],
                        symbol["name"],
                    )
                    if coordinate not in variables:
                        ready = False
                        break
                    values[row["name"]] = variables[coordinate]
                if not ready:
                    continue
                for row in program["body"]:
                    instruction = row["instruction"]
                    node = instruction["node"]
                    if node == "constant":
                        result = instruction["literal"]
                    elif node == "copy":
                        result = values[instruction["value"]]
                    elif node == "add":
                        result = (
                            values[instruction["left"]] + values[instruction["right"]]
                        )
                    elif node == "subtract":
                        result = (
                            values[instruction["left"]] - values[instruction["right"]]
                        )
                    elif node == "multiply":
                        result = (
                            values[instruction["left"]] * values[instruction["right"]]
                        )
                    elif node == "maximum":
                        result = max(
                            values[instruction["left"]],
                            values[instruction["right"]],
                        )
                    else:
                        assert node == "if"
                        result = values[
                            instruction[
                                "when_true"
                                if values[instruction["condition"]]
                                else "when_false"
                            ]
                        ]
                    assert numeric["minimum"] <= result <= numeric["maximum"]
                    values[instruction["target"]] = result
                target = program["target"]
                result_source = program["result"]
                variables[(target["model"], target["module"], target["name"])] = values[
                    result_source["name"]
                ]
                pending_programs.remove(program)
                progressed = True
            assert progressed
        state_targets = {
            coordinate
            for coordinate, declaration in declarations.items()
            if declaration["role"] == "state"
        }
        display_names = {
            coordinate: declaration["resolved_symbol"]["name"]
            for coordinate, declaration in declarations.items()
        }
    else:
        assert state_names is not None
        legacy_variables: dict[str, Any] = {
            row["name"]: row["value"] for row in scenario["values"]
        }
        variables = cast(
            dict[str | tuple[str, str, str], Any],
            legacy_variables,
        )
        state_targets = set(state_names)
        display_names = {name: name for name in legacy_variables}
    cells = {name: {"value": value} for name, value in variables.items()}
    state_cells = {name: cells[name] for name in state_targets if name in cells}
    before = {name: cell["value"] for name, cell in state_cells.items()}
    rng_states: dict[str, int] = {}
    rng_indices: dict[str, int] = {}
    draws: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    call_sites = {
        (row["parent_operation"]["id"], row["site"]): row
        for row in (resolved_call_sites or [])
    }

    def exact(value: int) -> int:
        if not numeric["minimum"] <= value <= numeric["maximum"]:
            raise _ReferenceRuntimeRefusal("runtime.numeric_overflow")
        return value

    def execute(
        selected: dict[str, Any],
        arguments: dict[str, dict[str, Any]],
        stack: tuple[str, ...] = (),
        path: tuple[str, ...] = (),
    ) -> tuple[str, Any]:
        assert selected["id"] not in stack
        locals_: dict[str, dict[str, Any]] = {}
        operation_results: dict[str, Any] = {}
        frame_cells = {id(cell): cell for cell in arguments.values()}
        snapshot = {key: cell["value"] for key, cell in frame_cells.items()}
        outcome = selected["default_outcome"]

        def cell(name: str) -> dict[str, Any]:
            if name in locals_:
                return locals_[name]
            return arguments[name]

        def write_local(name: str, value: Any) -> None:
            locals_[name] = {"value": value}

        try:
            for instruction in selected["body"]:
                node = nodes[instruction["node"]]
                assert set(instruction) == set(node["required_members"])
                semantics = node["semantics"]
                operator = semantics["operator"]
                if operator == "invoke-operation":
                    child = operations[instruction["operation"]["id"]]
                    child_arguments: dict[str, dict[str, Any]] = {}
                    for binding in instruction["arguments"]:
                        operand = binding["operand"]
                        if operand["kind"] == "port":
                            actual = arguments[operand["port"]]
                        elif operand["kind"] == "local":
                            actual = locals_[operand["local"]]
                        else:
                            actual = {"value": operand["literal"]}
                        child_arguments[binding["port"]] = actual
                    try:
                        child_outcome, child_result = execute(
                            child,
                            child_arguments,
                            (*stack, selected["id"]),
                            (*path, instruction["site"]),
                        )
                    except _ReferenceRuntimeRefusal as refusal:
                        if resolved_call_sites is not None:
                            refusal.call_site_identity = call_sites[
                                (selected["id"], instruction["site"])
                            ]["identity"]
                        raise
                    if resolved_call_sites is not None:
                        call_site = call_sites[(selected["id"], instruction["site"])]
                        outcome_row = next(
                            row
                            for row in call_site["outcomes"]
                            if row["outcome"] == child_outcome
                        )
                        calls.append(
                            {
                                "call_site_identity": call_site["identity"],
                                "site": "/".join((*path, instruction["site"])),
                                "operation": call_site["operation"],
                                "outcome": {
                                    "id": child_outcome,
                                    "identity": outcome_row["identity"],
                                },
                                "arguments": [
                                    {
                                        "formal_port_identity": row["port"]["identity"],
                                        "actual_operand_identity": row["operand"][
                                            "identity"
                                        ],
                                    }
                                    for row in call_site["arguments"]
                                ],
                                "result_identity": call_site["result"]["identity"],
                            }
                        )
                    result_binding = instruction["result"]
                    if result_binding["kind"] == "local":
                        write_local(result_binding["name"], child_result)
                    elif result_binding["kind"] == "operation-result":
                        operation_results[instruction["site"]] = child_result
                    action = next(
                        row["action"]
                        for row in instruction["outcomes"]
                        if row["outcome"] == child_outcome
                    )
                    if action["kind"] == "propagate":
                        outcome = action["outcome"]
                        break
                    continue
                if operator == "gameplay-precondition":
                    if not _reference_compare(
                        semantics["comparison"],
                        cell(instruction["left"])["value"],
                        cell(instruction["right"])["value"],
                    ):
                        outcome = instruction["outcome"]
                        break
                elif operator == "named-integer-draw":
                    draw = _reference_rng_draw(
                        runtime["named_rng"],
                        seed,
                        instruction["stream"],
                        instruction["minimum"],
                        instruction["maximum"],
                        rng_states,
                        rng_indices,
                    )
                    draws.append(draw)
                    write_local(instruction["target"], draw["value"])
                elif operator == "integer-literal":
                    write_local(instruction["target"], instruction["literal"])
                elif operator == "copy-value":
                    write_local(
                        instruction["target"],
                        cell(instruction["value"])["value"],
                    )
                elif operator in {
                    "integer-add",
                    "integer-subtract",
                    "integer-multiply",
                    "integer-maximum",
                }:
                    left = cell(instruction["left"])["value"]
                    right = cell(instruction["right"])["value"]
                    result = {
                        "integer-add": lambda: left + right,
                        "integer-subtract": lambda: left - right,
                        "integer-multiply": lambda: left * right,
                        "integer-maximum": lambda: max(left, right),
                    }[operator]()
                    write_local(instruction["target"], exact(result))
                elif operator == "integer-compare":
                    write_local(
                        instruction["target"],
                        _reference_compare(
                            semantics["comparison"],
                            cell(instruction["left"])["value"],
                            cell(instruction["right"])["value"],
                        ),
                    )
                elif operator == "select-value":
                    choice = (
                        instruction["when_true"]
                        if cell(instruction["condition"])["value"]
                        else instruction["when_false"]
                    )
                    write_local(instruction["target"], cell(choice)["value"])
                elif operator == "state-integer-subtract":
                    target = arguments[instruction["symbol"]]
                    target["value"] = exact(
                        target["value"] - cell(instruction["value"])["value"]
                    )
                elif operator == "state-write":
                    arguments[instruction["symbol"]]["value"] = exact(
                        cell(instruction["value"])["value"]
                    )
                else:
                    raise AssertionError(
                        f"unsupported operator in authority: {operator}"
                    )
        except _ReferenceRuntimeRefusal as refusal:
            for key, value in snapshot.items():
                frame_cells[key]["value"] = value
            if refusal.operation is None:
                refusal.operation = selected["id"]
                refusal.call_path = "/".join(path)
            raise

        outcome_definition = next(
            row for row in selected["outcomes"] if row["id"] == outcome
        )
        if outcome_definition["state_policy"] == "rollback":
            for key, value in snapshot.items():
                frame_cells[key]["value"] = value
        source = selected["result"]["source"]
        if outcome_definition["kind"] != "success":
            result = None
        elif source["kind"] == "local":
            result = locals_[source["name"]]["value"]
        elif source["kind"] == "port":
            result = arguments[source["name"]]["value"]
        elif source["kind"] == "operation-result":
            result = operation_results[source["site"]]
        else:
            assert source["kind"] == "unit"
            result = None
        return outcome, result

    if resolved_entrypoint is None:
        root_arguments = [
            {
                "port": port["id"],
                "operand": {"kind": "symbol", "symbol": port["id"]},
            }
            for port in operation["inputs"]
        ]
        root_frame = {
            row["port"]: cells[row["operand"]["symbol"]] for row in root_arguments
        }
    else:
        root_frame = {}
        for argument in resolved_entrypoint["arguments"]:
            operand = argument["operand"]
            if operand["kind"] == "symbol":
                symbol = operand["symbol"]
                coordinate = (
                    symbol["model"],
                    symbol["module"],
                    symbol["name"],
                )
                actual = cells[coordinate]
            else:
                actual = {"value": operand["value"]}
            root_frame[argument["port"]["name"]] = actual
    try:
        outcome, result = execute(
            operation,
            root_frame,
            path=((resolved_entrypoint["id"],) if resolved_entrypoint else ()),
        )
    except _ReferenceRuntimeRefusal as refusal:
        return {
            "refusal": {
                "reason": refusal.reason,
                "operation": refusal.operation,
                "call_path": refusal.call_path,
                "call_site_identity": refusal.call_site_identity,
            },
            "state_before": [
                {"name": display_names[name], "value": before[name]}
                for name in sorted(before)
            ],
            "state_after": [
                {
                    "name": display_names[name],
                    "value": state_cells[name]["value"],
                }
                for name in sorted(state_cells)
            ],
        }
    outcome_definition = next(
        row for row in operation["outcomes"] if row["id"] == outcome
    )
    if (
        resolved_entrypoint is not None
        and resolved_entrypoint["result"]["kind"] == "symbol"
        and outcome_definition["kind"] == "success"
    ):
        symbol = resolved_entrypoint["result"]["symbol"]
        coordinate = (symbol["model"], symbol["module"], symbol["name"])
        cells[coordinate] = {"value": result}
        display_names[coordinate] = symbol["name"]
    if outcome_definition["state_policy"] == "rollback":
        for name, value in before.items():
            state_cells[name]["value"] = value
    facts: dict[str, Any] = {
        display_names[name]: cell["value"] for name, cell in cells.items()
    }
    event = {
        "operation": operation["id"],
        "outcome": {
            "id": outcome,
            "kind": outcome_definition["kind"],
        },
        "facts": _reference_fact_rows(facts),
        "state_before": [
            {"name": display_names[name], "value": before[name]}
            for name in sorted(before)
        ],
        "state_after": [
            {
                "name": display_names[name],
                "value": state_cells[name]["value"],
            }
            for name in sorted(state_cells)
        ],
        "rng_draws": draws,
    }
    if resolved_entrypoint is not None:
        event["entrypoint"] = {
            "id": resolved_entrypoint["id"],
            "identity": resolved_entrypoint["identity"],
        }
        event["calls"] = calls
    return event


def _reference_evaluate_value_program_vector(
    vector: dict[str, Any],
) -> dict[str, Any]:
    inp = vector["input"]
    instructions = inp["instructions"]
    numeric = inp["numeric"]
    operands = {row["name"]: row["value"] for row in inp["operands"]}
    cache: dict[bytes, int] = {}
    charge = 0
    result = None
    signal = None
    site = inp["site"]
    for _ in range(inp["evaluations"]):
        charge += len(instructions)
        if charge > inp["resource_limit"]:
            signal = "step-limit"
            result = None
            break
        key = canonical_bytes(
            {
                "instructions": instructions,
                "numeric": numeric,
                "operands": [
                    {"name": name, "value": value}
                    for name, value in sorted(operands.items())
                ],
                "result": inp["result"],
                "site": inp["site"],
            }
        )
        if inp["cache"] and key in cache:
            result = cache[key]
            continue
        values = dict(operands)
        for row in instructions:
            instruction = row["instruction"]
            node = instruction["node"]
            if node == "constant":
                value = instruction["literal"]
            elif node == "copy":
                value = values[instruction["value"]]
            elif node == "add":
                value = values[instruction["left"]] + values[instruction["right"]]
            elif node == "subtract":
                value = values[instruction["left"]] - values[instruction["right"]]
            elif node == "multiply":
                value = values[instruction["left"]] * values[instruction["right"]]
            elif node == "maximum":
                value = max(
                    values[instruction["left"]],
                    values[instruction["right"]],
                )
            else:
                assert node == "if"
                value = values[
                    instruction[
                        "when_true"
                        if values[instruction["condition"]]
                        else "when_false"
                    ]
                ]
            if not numeric["minimum"] <= value <= numeric["maximum"]:
                signal = "numeric-overflow"
                site = row["evaluation_site_identity"]
                result = None
                break
            values[instruction["target"]] = value
        if signal is not None:
            break
        result = values[inp["result"]]
        if inp["cache"]:
            cache[key] = result
    admitted = signal is None
    return {
        "cache_entries": len(cache),
        "charge": charge,
        "outcome": "admitted" if admitted else "refused",
        "result": result,
        "result_artifact": admitted,
        "signal": signal,
        "site": inp["site"] if admitted else site,
    }


def _observation_evidence(
    *,
    site: str,
    cache_entries: int,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    outcome: str,
    post_state_committed: bool,
    snapshot_identities: list[str],
    snapshot_indices: list[int],
) -> dict[str, Any]:
    return {
        "site": site,
        "cache_entries": cache_entries,
        "committed_event_indices": [event["index"] for event in events],
        "outcome": outcome,
        "post_state_committed": post_state_committed,
        "snapshot_identities": snapshot_identities,
        "snapshot_indices": snapshot_indices,
    }


def _assert_observation_evidence_matches_package_vector(
    language_bundle: Any,
    evidence: dict[str, Any],
) -> None:
    vector = next(
        row
        for vector_set in language_bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        and vector_set["package_version"] == "1.1.0"
        for row in vector_set["vector_definitions"]
        if row.get("kind") == "value-program"
        and row.get("input", {}).get("site") == evidence["site"]
    )
    snapshot_identities = evidence["snapshot_identities"]
    assert all(
        isinstance(identity, str)
        and identity.startswith("sha256:")
        and len(identity) == 71
        and all(character in "0123456789abcdef" for character in identity[7:])
        for identity in snapshot_identities
    )
    committed_event_indices = evidence["committed_event_indices"]
    snapshot_indices = evidence["snapshot_indices"]
    projected_operands = [
        {"name": "lifecycle_cache_entries", "value": evidence["cache_entries"]},
        {
            "name": "lifecycle_committed_event_signature",
            "value": (
                len(committed_event_indices) * 100
                + committed_event_indices[0] * 10
                + committed_event_indices[-1]
            ),
        },
        {
            "name": "lifecycle_outcome_admitted",
            "value": int(evidence["outcome"] == "admitted"),
        },
        {
            "name": "lifecycle_post_state_committed",
            "value": int(evidence["post_state_committed"]),
        },
        {
            "name": "lifecycle_snapshot_identity_signature",
            "value": (
                len(snapshot_identities) * 100
                + len(snapshot_identities) * 10
                + len(set(snapshot_identities))
            ),
        },
        {
            "name": "lifecycle_snapshot_index_signature",
            "value": (
                len(snapshot_indices) * 100
                + snapshot_indices[0] * 10
                + snapshot_indices[-1]
            ),
        },
    ]
    assert projected_operands == vector["input"]["operands"]
    production = experiment_runtime_module._evaluate_value_program_vector(vector)
    reference = _reference_evaluate_value_program_vector(vector)
    assert production == reference == vector["expect"]


def _experiment(
    *,
    kernel_identity: str,
    language_bundle_identity: str,
    source_identity: str,
    build_receipt: dict[str, Any],
    base_damage: int,
) -> dict[str, Any]:
    resolved = _member(build_receipt, "resolved-model")
    package_lock = _member(build_receipt, "package-lock")
    rir = _member(build_receipt, "rir-semantic-payload")
    build_record = _member(build_receipt, "build-receipt")
    return {
        "schema_version": "2.0.0",
        "id": "example.rpg-combat-cast.one-action",
        "version": "1.0.0",
        "kernel_identity": kernel_identity,
        "language_bundle_identity": language_bundle_identity,
        "model": {
            "source_identity": source_identity,
            "build_receipt_identity": build_record["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": package_lock["content_identity"],
            "rir_identity": rir["content_identity"],
        },
        "runtime": {
            "profile": "standard.exact-int64-event-v1",
            "required_evaluator": {
                "operation_kinds": ["event-fragment", "event-program"],
                "instruction_nodes": [
                    "add",
                    "constant",
                    "copy",
                    "draw",
                    "if",
                    "invoke",
                    "less-than-or-equal",
                    "maximum",
                    "multiply",
                    "precondition-greater-than-or-equal",
                    "subtract",
                    "subtract-state",
                ],
                "effects": [
                    "event.commit",
                    "metric.observe",
                    "rng.named-stream",
                    "snapshot.commit",
                ],
                "numeric_policies": ["exact-int64"],
                "rng_algorithms": ["splitmix64-v1"],
                "runtime_profiles": ["standard.exact-int64-event-v1"],
            },
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 20260726},
        "external_inputs": [],
        "scenarios": [
            {
                "id": "one-cast",
                "entrypoint": "combat.cast",
                "assignments": [
                    {
                        "target": {
                            "model": "example.rpg-combat-cast",
                            "module": "combat",
                            "name": name,
                        },
                        "value": value,
                    }
                    for name, value in (
                        ("actor_mana", 30),
                        ("action_cost", 8),
                        ("accuracy", 85),
                        ("base_damage", base_damage),
                        ("critical_threshold", 0),
                        ("target_defense", 6),
                        ("target_health", 100),
                    )
                ],
                "named_streams": ["critical", "hit"],
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            _metric_contract(
                {
                    "id": "damage_dealt",
                    "kind": "scalar",
                    "unit": "1",
                    "observation": {
                        "source": "event",
                        "name": "cast-resolved",
                        "member": "damage_dealt",
                    },
                    "target": {"minimum": 1, "maximum": 1000},
                }
            ),
            _metric_contract(
                {
                    "id": "target_health_remaining",
                    "kind": "scalar",
                    "unit": "1",
                    "observation": {
                        "source": "snapshot",
                        "name": "terminal",
                        "member": "target_health",
                    },
                    "target": {"minimum": 0, "maximum": 99},
                }
            ),
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }


def _write_built_experiment(tmp_path, run_cli, *, base_damage=24):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "1" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=base_damage,
    )
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    return spec_path


def test_initialization_formula_computes_a_read_only_derived_symbol_before_snapshot_zero(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    source_value["modules"][0]["symbols"].append(
        _rpg_value("derived_base_damage", "derived")
    )
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 1000},
        "numeric_policy": "exact-int64",
    }
    source_value["modules"][0]["formulas"].extend(
        [
            {
                "id": "derived-damage-inner",
                "parameters": [{"id": "base", **quantity_contract}],
                "result": quantity_contract,
                "body": {
                    "nodes": [
                        {
                            "id": "identity",
                            "node": "operation-call",
                            "operation": {
                                "package": "core.quantity",
                                "version": "2.1.0",
                                "id": "quantity.identity",
                            },
                            "arguments": [
                                {
                                    "port": "value",
                                    "operand": {
                                        "kind": "parameter",
                                        "parameter": "base",
                                    },
                                }
                            ],
                            "result": quantity_contract,
                        }
                    ],
                    "result": {"kind": "local", "local": "identity"},
                },
            },
            {
                "id": "derived-damage",
                "parameters": [{"id": "base", **quantity_contract}],
                "result": quantity_contract,
                "body": {
                    "nodes": [
                        {
                            "id": "inner",
                            "node": "formula-call",
                            "formula": {
                                "module": "combat",
                                "id": "derived-damage-inner",
                            },
                            "arguments": [
                                {
                                    "parameter": "base",
                                    "operand": {
                                        "kind": "parameter",
                                        "parameter": "base",
                                    },
                                }
                            ],
                        }
                    ],
                    "result": {"kind": "local", "local": "inner"},
                },
            },
        ]
    )
    source_value["formula_bindings"].append(
        {
            "site": {
                "kind": "derived-symbol",
                "module": "combat",
                "symbol": "derived_base_damage",
            },
            "formula": {"module": "combat", "id": "derived-damage"},
            "arguments": [
                {
                    "parameter": "base",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "base_damage",
                    },
                }
            ],
        }
    )
    base_binding = next(
        row
        for row in source_value["entrypoints"][0]["arguments"]
        if row["port"] == "base_damage"
    )
    base_binding["operand"]["symbol"] = "derived_base_damage"
    source = tmp_path / "formula-runtime-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "formula-runtime-model"),
            "--invocation-key",
            "d" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification_path = tmp_path / "formula-runtime-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    actual_values = {
        canonical_bytes(cast(Any, initializer["target"])): initializer["value"]
        for initializer in checked.rir["entrypoints"][0]["scenario_input_contract"][
            "initializers"
        ]
    }
    for assignment in checked.value["scenarios"][0]["assignments"]:
        actual_values[canonical_bytes(cast(Any, assignment["target"]))] = assignment[
            "value"
        ]
        exact_charge = sum(
            program["resource_bounds"]["max_steps"]
            for program in checked.rir["initialization_programs"]
            if program["site"]["context"]["phase"] == "initialization"
        )
    cache: dict[bytes, int] = {}
    consumed = experiment_runtime_module._evaluate_initialization_programs(
        checked,
        actual_values,
        consumed_steps=0,
        runtime_limit=exact_charge,
        cache=cache,
    )
    assert consumed == exact_charge
    derived_identity = canonical_bytes(
        cast(
            Any,
            {
                "model": "example.rpg-combat-cast",
                "module": "combat",
                "name": "derived_base_damage",
            },
        )
    )
    base_identity = canonical_bytes(
        cast(
            Any,
            {
                "model": "example.rpg-combat-cast",
                "module": "combat",
                "name": "base_damage",
            },
        )
    )
    assert actual_values[derived_identity] == 24
    assert (
        experiment_runtime_module._evaluate_initialization_programs(
            checked,
            actual_values,
            consumed_steps=0,
            runtime_limit=exact_charge,
            cache=cache,
        )
        == exact_charge
    )
    actual_values[base_identity] = 31
    assert (
        experiment_runtime_module._evaluate_initialization_programs(
            checked,
            actual_values,
            consumed_steps=0,
            runtime_limit=exact_charge,
            cache=cache,
        )
        == exact_charge
    )
    assert actual_values[derived_identity] == 31
    without_cache = dict(actual_values)
    without_cache[base_identity] = 32
    assert (
        experiment_runtime_module._evaluate_initialization_programs(
            checked,
            without_cache,
            consumed_steps=0,
            runtime_limit=exact_charge,
            cache=None,
        )
        == exact_charge
    )
    assert without_cache[derived_identity] == 32
    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    snapshots = artifacts.members["snapshot-series"].value["snapshots"]
    assert snapshots[0]["name"] == "one-cast:initial"
    event = artifacts.members["event-trace"].value["events"][0]
    derived = next(
        row for row in event["facts"] if row["name"] == "derived_base_damage"
    )
    assert derived == {"kind": "integer", "name": "derived_base_damage", "integer": 24}
    assert (
        next(row["integer"] for row in event["facts"] if row["name"] == "damage_dealt")
        == 18
    )


def test_example_effective_accuracy_formula_exercises_its_minimum_clamp(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    accuracy = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "accuracy"
    )
    accuracy["value"] = 0
    defense = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "target_defense"
    )
    defense["value"] = 2
    runtime = json.loads((_AUTHORITY_DIR / "kernel.json").read_text(encoding="utf-8"))[
        "meta_format"
    ]["runtime_program"]
    seed = next(
        candidate
        for candidate in range(10_000)
        if _reference_rng_draw(
            runtime["named_rng"],
            candidate,
            "hit",
            1,
            100,
            {},
            {},
        )["value"]
        == 1
    )
    specification["seed"]["value"] = seed
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "minimum-clamp-run"),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), stdout
    event = _member(json.loads(stdout), "event-trace")["events"][0]
    facts = {row["name"]: row["integer"] for row in event["facts"]}
    assert facts["effective_accuracy"] == 1
    assert (
        next(draw for draw in event["rng_draws"] if draw["stream"] == "hit")["value"]
        == 1
    )


def test_public_build_and_run_reaches_a_boolean_conditional_formula(tmp_path, run_cli):
    source_value = _rpg_model_source()
    formula = next(
        row
        for row in source_value["modules"][0]["formulas"]
        if row["id"] == "mitigated-damage"
    )
    boolean_contract = {
        "type": "Boolean",
        "representation": "Bool",
        "kind": "boolean",
        "unit": "1",
        "domain": {"kind": "boolean"},
        "numeric_policy": "exact-bool",
    }
    formula["body"] = {
        "nodes": [
            {
                "id": "fully-mitigated",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.less-than",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "damage_before_defense",
                        },
                    },
                    {
                        "port": "right",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "mitigation",
                        },
                    },
                ],
                "result": boolean_contract,
            },
            {
                "id": "bounded-damage",
                "node": "conditional",
                "condition": {"kind": "local", "local": "fully-mitigated"},
                "when_true": {"kind": "parameter", "parameter": "mitigation"},
                "when_false": {
                    "kind": "parameter",
                    "parameter": "damage_before_defense",
                },
            },
        ],
        "result": {"kind": "local", "local": "bounded-damage"},
    }
    source = tmp_path / "conditional-formula-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "conditional-formula-model"),
            "--invocation-key",
            "a" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
    build_receipt = json.loads(build_stdout)
    rir = _member(build_receipt, "rir-semantic-payload")
    resolved_formula = next(
        row for row in rir["formulas"] if row["id"] == formula["id"]
    )
    assert [node["node"] for node in resolved_formula["body"]["nodes"]] == [
        "operation-call",
        "conditional",
    ]

    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["runtime"]["required_evaluator"]["instruction_nodes"] = [
        "add",
        "constant",
        "copy",
        "draw",
        "if",
        "invoke",
        "less-than",
        "less-than-or-equal",
        "multiply",
        "precondition-greater-than-or-equal",
        "subtract-state",
    ]
    specification_path = tmp_path / "conditional-formula-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "conditional-formula-evaluation"),
            "--invocation-key",
            "b" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), stdout
    receipt = json.loads(stdout)
    trace = _member(receipt, "event-trace")
    assert trace["events"][0]["state_after"] == [
        {"name": "actor_mana", "value": 22},
        {"name": "target_health", "value": 76},
    ]


def test_initialization_formula_refusal_precedes_snapshot_zero_and_publication(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    lower = -(1 << 63)
    upper = (1 << 63) - 1
    for symbol_name in ("accuracy", "effective_accuracy"):
        symbol = next(
            row
            for row in source_value["modules"][0]["symbols"]
            if row["symbol"] == symbol_name
        )
        symbol["domain"] = {"minimum": lower, "maximum": upper}
    formula = next(
        row
        for row in source_value["modules"][0]["formulas"]
        if row["id"] == "effective-accuracy"
    )
    formula["parameters"][0]["domain"] = {"minimum": lower, "maximum": upper}
    formula["result"]["domain"] = {"minimum": lower, "maximum": upper}
    formula["body"] = {
        "nodes": [
            {
                "id": "underflow",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.subtract",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {"kind": "parameter", "parameter": "base"},
                    },
                    {
                        "port": "right",
                        "operand": {"kind": "literal", "value": 1},
                    },
                ],
                "result": deepcopy(formula["result"]),
            }
        ],
        "result": {"kind": "local", "local": "underflow"},
    }
    source = tmp_path / "initialization-overflow-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "initialization-overflow-model"),
            "--invocation-key",
            "e" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    accuracy = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "accuracy"
    )
    accuracy["value"] = lower
    specification_path = tmp_path / "initialization-overflow-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    out = tmp_path / "initialization-overflow-output.json"

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(out),
            "--invocation-key",
            "f" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    assert error["diagnostics"][0]["code"] == "runtime.numeric_overflow"
    assert error["diagnostics"][0]["primary"]["pointer"] == ("/scenarios/0/assignments")
    message = error["diagnostics"][0]["message"]
    assert "refused before Snapshot 0" in message
    assert "evaluation site sha256:" in message
    assert "immutable frame sha256:" in message
    assert "terminal_audit" not in error
    assert not out.exists()

    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    evaluation = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(evaluation, experiment_runtime_module.Schema2RefusalReport)
    assert evaluation.variant == "pre-event"


def test_derived_formula_re_evaluates_against_each_new_committed_snapshot(
    tmp_path, run_cli, monkeypatch
):
    source_value = _rpg_model_source()
    derived_binding = next(
        row
        for row in source_value["formula_bindings"]
        if row["site"]["kind"] == "derived-symbol"
    )
    derived_binding["arguments"][0]["operand"]["symbol"] = "target_health"
    source = tmp_path / "snapshot-derived-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "snapshot-derived-model"),
            "--invocation-key",
            "3" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["scenarios"][0]["assignments"] = [
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] != "accuracy"
    ]
    second = deepcopy(specification["scenarios"][0])
    second["id"] = "second-cast"
    specification["scenarios"].append(second)
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "first-terminal-health",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "snapshot",
                    "name": "one-cast:terminal",
                    "member": "target_health",
                },
                "target": {"minimum": 82, "maximum": 82},
            }
        )
    ]
    spec_path = tmp_path / "snapshot-derived-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_runtime_module.check_experiment(str(spec_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    observation_frames: list[str | None] = []
    observation_cache_growth: list[int] = []
    evaluate_programs = experiment_runtime_module._evaluate_initialization_programs

    def record_observation_frame(*args, **kwargs):
        cache = kwargs.get("cache")
        assert isinstance(cache, dict)
        cache_entries_before = len(cache)
        result = evaluate_programs(*args, **kwargs)
        if kwargs.get("phase") == "observation":
            observation_frames.append(kwargs.get("frame_identity"))
            observation_cache_growth.append(len(cache) - cache_entries_before)
        return result

    monkeypatch.setattr(
        experiment_runtime_module,
        "_evaluate_initialization_programs",
        record_observation_frame,
    )

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    events = artifacts.members["event-trace"].value["events"]
    snapshots = artifacts.members["snapshot-series"].value["snapshots"]
    terminal_snapshots = [
        snapshot for snapshot in snapshots if snapshot["name"].endswith(":terminal")
    ]
    snapshot_identity_domain = (
        experiment_runtime_module._formula_snapshot_identity_domain(checked)
    )
    assert observation_frames == [
        content_identity(snapshot_identity_domain, cast(Any, snapshot))
        for snapshot in terminal_snapshots
    ]
    assert len(set(observation_frames)) == 2
    assert observation_cache_growth == [1, 1]
    for event in events:
        facts = {row["name"]: row["integer"] for row in event["facts"]}
        assert facts["target_health"] == 82
        assert facts["effective_accuracy"] == facts["target_health"]
    positive_evidence = _observation_evidence(
        site="runtime.lifecycle-observation.positive",
        cache_entries=observation_cache_growth[0],
        events=events[:1],
        outcome="admitted",
        post_state_committed=(
            terminal_snapshots[0]["values"] == events[0]["state_after"]
        ),
        snapshot_identities=cast(list[str], observation_frames[:1]),
        snapshot_indices=[terminal_snapshots[0]["index"]],
    )
    boundary_evidence = _observation_evidence(
        site="runtime.lifecycle-observation.boundary",
        cache_entries=sum(observation_cache_growth),
        events=events,
        outcome="admitted",
        post_state_committed=(
            terminal_snapshots[-1]["values"] == events[-1]["state_after"]
        ),
        snapshot_identities=cast(list[str], observation_frames),
        snapshot_indices=[snapshot["index"] for snapshot in terminal_snapshots],
    )
    _assert_observation_evidence_matches_package_vector(
        checked.language_bundle,
        positive_evidence,
    )
    _assert_observation_evidence_matches_package_vector(
        checked.language_bundle,
        boundary_evidence,
    )


def test_observation_formula_refusal_preserves_the_committed_event_and_snapshot(
    tmp_path, run_cli, monkeypatch
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    second = deepcopy(specification["scenarios"][0])
    second["id"] = "second-cast"
    specification["scenarios"].append(second)
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    evaluate_programs = experiment_runtime_module._evaluate_initialization_programs
    observation_frames: list[str] = []
    observation_cache_growth: list[int] = []

    def refuse_observation(*args, **kwargs):
        if kwargs.get("phase") == "observation":
            frame_identity = kwargs.get("frame_identity")
            assert isinstance(frame_identity, str)
            observation_frames.append(frame_identity)
            if len(observation_frames) == 2:
                raise experiment_runtime_module._InitializationProgramFault(
                    signal="numeric-overflow",
                    program="formula.observation",
                    evaluation_site_identity="sha256:" + "f" * 64,
                    frame_identity=frame_identity,
                )
            cache = kwargs.get("cache")
            assert isinstance(cache, dict)
            cache_entries_before = len(cache)
            result = evaluate_programs(*args, **kwargs)
            observation_cache_growth.append(len(cache) - cache_entries_before)
            return result
        return evaluate_programs(*args, **kwargs)

    monkeypatch.setattr(
        experiment_runtime_module,
        "_evaluate_initialization_programs",
        refuse_observation,
    )

    outcome = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    assert outcome.report.variant == "post-dispatch"
    assert len(observation_frames) == 2
    assert all(frame.startswith("sha256:") for frame in observation_frames)
    assert outcome.committed_trace_prefix == (
        {
            "index": 0,
            "operation": "game.combat.cast-v1",
            "outcome": {"id": "cast-resolved", "kind": "success"},
        },
        {
            "index": 1,
            "operation": "game.combat.cast-v1",
            "outcome": {"id": "cast-resolved", "kind": "success"},
        },
    )
    assert outcome.refusing_event_index == 2
    assert outcome.last_state["target_health"] == 82
    assert outcome.state_before == outcome.state_after == outcome.last_state
    evidence = _observation_evidence(
        site="runtime.lifecycle-observation.refusal",
        cache_entries=sum(observation_cache_growth),
        events=outcome.committed_trace_prefix,
        outcome="refused",
        post_state_committed=(
            outcome.state_before == outcome.state_after == outcome.last_state
        ),
        snapshot_identities=observation_frames,
        snapshot_indices=[1, 3],
    )
    _assert_observation_evidence_matches_package_vector(
        checked.language_bundle,
        evidence,
    )


def test_event_formula_adds_its_symbol_to_the_scenario_input_contract(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    source_value["modules"][0]["symbols"].append(_rpg_value("formula_bonus", "input"))
    formula = next(
        row
        for row in source_value["modules"][0]["formulas"]
        if row["id"] == "mitigated-damage"
    )
    formula["body"] = {
        "nodes": [],
        "result": {
            "kind": "symbol",
            "module": "combat",
            "symbol": "formula_bonus",
        },
    }
    source = tmp_path / "event-symbol-formula-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "event-symbol-formula-model"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["scenarios"][0]["assignments"].append(
        {
            "target": {
                "model": "example.rpg-combat-cast",
                "module": "combat",
                "name": "formula_bonus",
            },
            "value": 31,
        }
    )
    requirements, _named_streams = (
        experiment_runtime_module.derive_scenario_program_requirements(
            _member(build_receipt, "rir-semantic-payload"),
            entrypoint_id=specification["scenarios"][0]["entrypoint"],
            runtime_profile=specification["runtime"]["profile"],
            rng_algorithm=specification["seed"]["algorithm"],
        )
    )
    specification["runtime"]["required_evaluator"] = requirements
    spec_path = tmp_path / "event-symbol-formula-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_runtime_module.check_experiment(str(spec_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    event = artifacts.members["event-trace"].value["events"][0]
    facts = {row["name"]: row["integer"] for row in event["facts"]}
    assert facts["damage_dealt"] == 31
    assert facts["target_health"] == 69


def test_public_experiment_uses_resolved_entrypoint_bindings_not_shared_names(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    symbols = source_value["modules"][0]["symbols"]
    symbols[:] = [symbol for symbol in symbols if symbol["symbol"] != "target_defense"]
    symbols.extend(
        [
            _rpg_value("hit_defense", "input"),
            _rpg_value("damage_mitigation", "input"),
        ]
    )
    for symbol in symbols:
        symbol["value_policy"] = {
            "mode": (
                "experiment-required"
                if symbol["role"] not in {"derived", "output", "random"}
                else "none"
            )
        }
    source_value["entrypoints"] = [
        {
            "id": "combat.cast",
            "operation": {
                "package": "game.combat",
                "version": "2.0.0",
                "id": "game.combat.cast-v1",
            },
            "arguments": [
                {
                    "port": port,
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": symbol,
                    },
                }
                for port, symbol in (
                    ("actor_resource", "actor_mana"),
                    ("action_cost", "action_cost"),
                    ("accuracy", "effective_accuracy"),
                    ("base_damage", "base_damage"),
                    ("critical_threshold", "critical_threshold"),
                    ("hit_defense", "hit_defense"),
                    ("damage_mitigation", "damage_mitigation"),
                    ("target_health", "target_health"),
                )
            ],
            "result": {
                "kind": "symbol",
                "module": "combat",
                "symbol": "damage_dealt",
            },
        }
    ]
    source = tmp_path / "explicit-bindings-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )

    def resolved_target(name):
        return {
            "model": "example.rpg-combat-cast",
            "module": "combat",
            "name": name,
        }

    specification["scenarios"] = [
        {
            "id": "one-cast",
            "entrypoint": "combat.cast",
            "assignments": [
                {"target": resolved_target(name), "value": value}
                for name, value in (
                    ("actor_mana", 30),
                    ("action_cost", 8),
                    ("accuracy", 85),
                    ("base_damage", 24),
                    ("critical_threshold", 0),
                    ("damage_mitigation", 1),
                    ("hit_defense", 6),
                    ("target_health", 100),
                )
            ],
            "named_streams": ["critical", "hit"],
            "terminal_condition": {"kind": "event-count", "maximum": 1},
        }
    ]
    specification["metrics"][0]["observation"]["member"] = "damage_dealt"
    spec_path = tmp_path / "explicit-bindings-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")

    run_exit, run_stdout, run_stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(tmp_path / "evaluation.json"),
            "--invocation-key",
            "b" * 64,
        ]
    )

    assert (run_exit, run_stderr) == (0, ""), run_stdout
    receipt = json.loads(run_stdout)
    trace = _member(receipt, "event-trace")
    event = trace["events"][0]
    facts = {
        row["name"]: row["integer"]
        for row in event["facts"]
        if row["kind"] == "integer"
    }
    assert facts["hit_defense"] == 6
    assert facts["damage_mitigation"] == 1
    assert facts["damage_dealt"] == 23
    assert event["entrypoint"] == {
        "id": "combat.cast",
        "identity": _member(build_receipt, "rir-semantic-payload")["entrypoints"][0][
            "identity"
        ],
    }
    assert [row["operation"]["id"] for row in event["calls"]] == [
        "game.resource.spend-v1",
        "game.check.hit-v1",
        "game.check.critical-v1",
        "game.combat.damage-v1",
    ]
    assert all(
        row["call_site_identity"].startswith("sha256:")
        and row["result_identity"].startswith("sha256:")
        and all(
            argument["formal_port_identity"].startswith("sha256:")
            and argument["actual_operand_identity"].startswith("sha256:")
            for argument in row["arguments"]
        )
        for row in event["calls"]
    )
    assert event["state_after"] == [
        {"name": "actor_mana", "value": 22},
        {"name": "target_health", "value": 77},
    ]


def test_model_entrypoint_refuses_conflicting_writable_actual_aliases(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    target_health = next(
        row
        for row in source_value["entrypoints"][0]["arguments"]
        if row["port"] == "target_health"
    )
    target_health["operand"]["symbol"] = "actor_mana"
    source = tmp_path / "writable-alias-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == ("/entrypoints/0/arguments")


@pytest.mark.parametrize("mutation", ("under", "over", "duplicate"))
def test_scenario_assignments_exactly_close_the_entrypoint_contract(
    tmp_path, run_cli, mutation
):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    assignments = value["scenarios"][0]["assignments"]
    if mutation == "under":
        assignments.pop()
    elif mutation == "over":
        assignments.append(
            {
                "target": {
                    "model": "example.rpg-combat-cast",
                    "module": "combat",
                    "name": "damage_dealt",
                },
                "value": 1,
            }
        )
    else:
        assignments.append(deepcopy(assignments[0]))
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == ("/scenarios/0/assignments")


def test_experiment_cannot_select_a_raw_ldb_operation(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    scenario = value["scenarios"][0]
    scenario.pop("entrypoint")
    scenario["operation"] = "game.combat.cast-v1"
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    pointer = error["diagnostics"][0]["primary"]["pointer"]
    assert pointer in {
        "/scenarios/0/entrypoint",
        "/scenarios/0/operation",
    }


def test_experiment_cannot_rebind_a_resolved_entrypoint(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    value["scenarios"][0]["bindings"] = [
        {
            "port": "base_damage",
            "target": {
                "model": "example.rpg-combat-cast",
                "module": "combat",
                "name": "accuracy",
            },
        }
    ]
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == "/scenarios/0/bindings"


def test_optional_experiment_override_uses_the_model_default_or_exact_override(
    tmp_path,
    run_cli,
):
    source_value = _rpg_model_source()
    base_damage = next(
        symbol
        for symbol in source_value["modules"][0]["symbols"]
        if symbol["symbol"] == "base_damage"
    )
    base_damage["value_policy"] = {"mode": "experiment-override", "value": 24}
    source = tmp_path / "optional-override-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "optional-override-model"),
            "--invocation-key",
            "c" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    baseline = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=30,
    )

    observed: dict[str, tuple[int, list[dict[str, int]]]] = {}
    for case, override in (("default", None), ("override", 30)):
        specification = deepcopy(baseline)
        assignments = specification["scenarios"][0]["assignments"]
        base_assignment = next(
            assignment
            for assignment in assignments
            if assignment["target"]["name"] == "base_damage"
        )
        if override is None:
            assignments.remove(base_assignment)
        else:
            base_assignment["value"] = override
        path = tmp_path / f"optional-{case}.json"
        path.write_text(json.dumps(specification), encoding="utf-8")

        checked = experiment_runtime_module.check_experiment(str(path))
        assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
        artifacts = experiment_runtime_module.evaluate_experiment(checked)
        assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
        event = artifacts.members["event-trace"].value["events"][0]
        observed[case] = (
            next(
                row["integer"]
                for row in event["facts"]
                if row["name"] == "damage_dealt"
            ),
            event["state_after"],
        )
    assert observed == {
        "default": (
            18,
            [
                {"name": "actor_mana", "value": 22},
                {"name": "target_health", "value": 82},
            ],
        ),
        "override": (
            24,
            [
                {"name": "actor_mana", "value": 22},
                {"name": "target_health", "value": 76},
            ],
        ),
    }


def test_public_rpg_tuning_loop_changes_trace_and_metric_explainably(tmp_path, run_cli):
    source_value = json.loads(
        (_EXAMPLE_DIR / "model-source.json").read_text(encoding="utf-8")
    )
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    model_out = tmp_path / "resolved-model.json"

    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(model_out),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (build_exit, build_stderr) == (0, ""), (
        build_stdout,
        build_stderr,
    )
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    source_identity = content_identity("model-source-package-v2", source_value)
    first_spec = json.loads(
        (_EXAMPLE_DIR / "experiment.json").read_text(encoding="utf-8")
    )
    assert first_spec["kernel_identity"] == build_record["kernel_identity"]
    assert (
        first_spec["language_bundle_identity"]
        == (build_record["language_bundle_identity"])
    )
    assert first_spec["model"] == {
        "source_identity": source_identity,
        "build_receipt_identity": build_record["content_identity"],
        "resolved_model_identity": build_record["resolved_model_identity"],
        "package_lock_identity": build_record["package_lock_identity"],
        "rir_identity": build_record["rir_identity"],
    }
    first_path = tmp_path / "experiment-45.json"
    first_path.write_text(json.dumps(first_spec), encoding="utf-8")

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(first_path)]
    )

    assert (check_exit, check_stderr) == (0, ""), check_stdout
    assert json.loads(check_stdout)["checked"] is True

    first_exit, first_stdout, first_stderr = run_cli(
        [
            "experiment",
            "run",
            str(first_path),
            "--out",
            str(tmp_path / "evaluation-45.json"),
            "--invocation-key",
            "2" * 64,
        ]
    )

    assert (first_exit, first_stderr) == (0, "")
    first_receipt = json.loads(first_stdout)
    first_trace = _member(first_receipt, "event-trace")
    first_metrics = _member(first_receipt, "metric-dataset")
    assert first_trace["events"][0]["operation"] == "game.combat.cast-v1"
    kernel = json.loads((_AUTHORITY_DIR / "kernel.json").read_text(encoding="utf-8"))
    _loaded_kernel, ldb = authority_module.load_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    operation = next(
        row for row in operations.values() if row["id"] == "game.combat.cast-v1"
    )
    rir = _member(build_receipt, "rir-semantic-payload")
    resolved_entrypoint = next(
        row for row in rir["entrypoints"] if row["id"] == "combat.cast"
    )
    reference_event = _reference_execute_event(
        kernel,
        operation,
        operations,
        first_spec["scenarios"][0],
        seed=first_spec["seed"]["value"],
        resolved_entrypoint=resolved_entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        resolved_initialization_programs=rir["initialization_programs"],
    )
    assert {
        key: value for key, value in first_trace["events"][0].items() if key != "index"
    } == reference_event
    assert (
        next(
            item["integer"]
            for item in first_trace["events"][0]["facts"]
            if item["name"] == "base_damage"
        )
        == 45
    )
    assert first_trace["events"][0]["state_after"] == [
        {"name": "actor_mana", "value": 26},
        {"name": "target_health", "value": 40},
    ]
    first_damage = next(
        sample["value"]
        for sample in first_metrics["samples"]
        if sample["metric"] == "damage_dealt"
    )
    assert first_damage == 60

    edited_source_value = deepcopy(source_value)
    edited_source_value["manifest"]["version"] = "1.1.0"
    damage_formula = next(
        formula
        for formula in edited_source_value["modules"][0]["formulas"]
        if formula["id"] == "mitigated-damage"
    )
    damage_formula["body"] = {
        "nodes": [
            {
                "id": "unmitigated-damage",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.identity",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "damage_before_defense",
                        },
                    }
                ],
                "result": deepcopy(damage_formula["result"]),
            }
        ],
        "result": {"kind": "local", "local": "unmitigated-damage"},
    }
    edited_source = tmp_path / "rpg-model-edited.json"
    edited_source.write_text(json.dumps(edited_source_value), encoding="utf-8")
    edited_model_out = tmp_path / "resolved-model-edited.json"
    edited_build_exit, edited_build_stdout, edited_build_stderr = run_cli(
        [
            "model",
            "build",
            str(edited_source),
            "--out",
            str(edited_model_out),
            "--invocation-key",
            "3" * 64,
        ]
    )
    assert (edited_build_exit, edited_build_stderr) == (0, "")
    edited_build_receipt = json.loads(edited_build_stdout)
    edited_build_record = _member(edited_build_receipt, "build-receipt")
    edited_rir = _member(edited_build_receipt, "rir-semantic-payload")
    assert (
        edited_build_record["kernel_identity"] == build_record["kernel_identity"]
        and edited_build_record["language_bundle_identity"]
        == build_record["language_bundle_identity"]
        and edited_build_record["package_lock_identity"]
        == build_record["package_lock_identity"]
        and edited_build_record["compiler"] == build_record["compiler"]
    )
    assert (
        edited_build_record["rir_identity"] != build_record["rir_identity"]
        and edited_build_record["resolved_model_identity"]
        != build_record["resolved_model_identity"]
    )
    baseline_formulas = {row["id"]: row["identity"] for row in rir["formulas"]}
    edited_formulas = {row["id"]: row["identity"] for row in edited_rir["formulas"]}
    assert edited_formulas["mitigated-damage"] != baseline_formulas["mitigated-damage"]
    assert (
        edited_formulas["effective-accuracy"] == baseline_formulas["effective-accuracy"]
    )

    stale_spec = deepcopy(first_spec)
    stale_spec["model"]["source_identity"] = content_identity(
        "model-source-package-v2",
        edited_source_value,
    )
    stale_path = tmp_path / "experiment-stale-model-binding.json"
    stale_path.write_text(json.dumps(stale_spec), encoding="utf-8")
    stale_exit, stale_stdout, stale_stderr = run_cli(
        ["experiment", "check", str(stale_path)]
    )
    assert (stale_exit, stale_stderr) == (2, "")
    assert json.loads(stale_stdout)["error"]["diagnostics"][0]["code"] == (
        "language.resolved_authority_mismatch"
    )

    tuned_spec = deepcopy(first_spec)
    tuned_spec["version"] = "1.1.0"
    tuned_spec["model"] = {
        "source_identity": content_identity(
            "model-source-package-v2",
            edited_source_value,
        ),
        "build_receipt_identity": edited_build_record["content_identity"],
        "resolved_model_identity": edited_build_record["resolved_model_identity"],
        "package_lock_identity": edited_build_record["package_lock_identity"],
        "rir_identity": edited_build_record["rir_identity"],
    }
    tuned_requirements, _named_streams = (
        experiment_runtime_module.derive_scenario_program_requirements(
            _member(edited_build_receipt, "rir-semantic-payload"),
            entrypoint_id=tuned_spec["scenarios"][0]["entrypoint"],
            runtime_profile=tuned_spec["runtime"]["profile"],
            rng_algorithm=tuned_spec["seed"]["algorithm"],
        )
    )
    tuned_spec["runtime"]["required_evaluator"] = tuned_requirements
    tuned_path = tmp_path / "experiment-formula-edited.json"
    tuned_path.write_text(json.dumps(tuned_spec), encoding="utf-8")
    tuned_check_exit, tuned_check_stdout, tuned_check_stderr = run_cli(
        ["experiment", "check", str(tuned_path)]
    )
    assert (tuned_check_exit, tuned_check_stderr) == (0, ""), tuned_check_stdout
    tuned_exit, tuned_stdout, tuned_stderr = run_cli(
        [
            "experiment",
            "run",
            str(tuned_path),
            "--out",
            str(tmp_path / "evaluation-formula-edited.json"),
            "--invocation-key",
            "4" * 64,
        ]
    )

    assert (tuned_exit, tuned_stderr) == (0, "")
    tuned_receipt = json.loads(tuned_stdout)
    tuned_trace = _member(tuned_receipt, "event-trace")
    tuned_metrics = _member(tuned_receipt, "metric-dataset")
    tuned_evaluator = _member(tuned_receipt, "evaluator-capability-manifest")
    baseline_evaluator = _member(first_receipt, "evaluator-capability-manifest")
    assert (
        tuned_evaluator["evaluator_build_identity"]
        == baseline_evaluator["evaluator_build_identity"]
    )
    assert tuned_trace["experiment_identity"] != first_trace["experiment_identity"]
    tuned_damage = next(
        sample["value"]
        for sample in tuned_metrics["samples"]
        if sample["metric"] == "damage_dealt"
    )
    assert (
        next(
            item["integer"]
            for item in tuned_trace["events"][0]["facts"]
            if item["name"] == "base_damage"
        )
        == 45
    )
    assert tuned_damage == 90 > first_damage
    assert tuned_trace["events"][0]["state_after"] == [
        {"name": "actor_mana", "value": 26},
        {"name": "target_health", "value": 10},
    ]
    assert (
        tuned_trace["content_identity"] != first_trace["content_identity"]
        and tuned_metrics["content_identity"] != first_metrics["content_identity"]
    )
    alternate_seed_spec = deepcopy(first_spec)
    alternate_seed_spec["seed"]["value"] = 4
    alternate_seed_path = tmp_path / "experiment-seed-4.json"
    alternate_seed_path.write_text(
        json.dumps(alternate_seed_spec),
        encoding="utf-8",
    )
    alternate_exit, alternate_stdout, alternate_stderr = run_cli(
        [
            "experiment",
            "run",
            str(alternate_seed_path),
            "--out",
            str(tmp_path / "evaluation-seed-4.json"),
            "--invocation-key",
            "5" * 64,
        ]
    )

    assert (alternate_exit, alternate_stderr) == (0, "")
    alternate_receipt = json.loads(alternate_stdout)
    alternate_trace = _member(alternate_receipt, "event-trace")
    alternate_metrics = _member(alternate_receipt, "metric-dataset")
    alternate_event = alternate_trace["events"][0]
    assert alternate_event["outcome"]["id"] == "cast-resolved"
    assert [
        (draw["stream"], draw["value"]) for draw in alternate_event["rng_draws"]
    ] == [
        ("hit", 22),
        ("critical", 72),
    ]
    assert alternate_event["state_after"] == [
        {"name": "actor_mana", "value": 26},
        {"name": "target_health", "value": 85},
    ]
    assert (
        next(
            sample["value"]
            for sample in alternate_metrics["samples"]
            if sample["metric"] == "damage_dealt"
        )
        == 15
    )
    assert (
        alternate_trace["content_identity"] != first_trace["content_identity"]
        and alternate_metrics["content_identity"] != first_metrics["content_identity"]
    )

    repeat_exit, repeat_stdout, repeat_stderr = run_cli(
        [
            "experiment",
            "run",
            str(first_path),
            "--out",
            str(tmp_path / "evaluation-45-repeat.json"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (repeat_exit, repeat_stderr) == (0, "")
    repeat_receipt = json.loads(repeat_stdout)
    first_locators = {
        row["logical_name"]: Path(row["locator"])
        for row in first_receipt["member_locators"]
    }
    repeat_locators = {
        row["logical_name"]: Path(row["locator"])
        for row in repeat_receipt["member_locators"]
    }
    assert set(repeat_locators) == set(first_locators)
    assert all(
        repeat_locators[name].read_bytes() == first_locators[name].read_bytes()
        for name in first_locators
    )

    evaluator = _member(first_receipt, "evaluator-capability-manifest")
    resolved_runtime = _member(first_receipt, "resolved-runtime-profile")
    runtime_definition = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == first_spec["runtime"]["profile"]
    )
    checked_experiment = experiment_runtime_module.check_experiment(str(first_path))
    assert isinstance(
        checked_experiment,
        experiment_runtime_module.CheckedExperiment,
    )
    runtime_definition_identity = (
        experiment_runtime_module._runtime_profile_definition_identity(
            checked_experiment,
            runtime_definition,
        )
    )
    assert (
        resolved_runtime["runtime_profile_definition_identity"]
        == runtime_definition_identity
    )
    changed_definition = deepcopy(runtime_definition)
    changed_definition["resource_bounds"]["max_steps"] += 1
    assert (
        experiment_runtime_module._runtime_profile_definition_identity(
            checked_experiment,
            changed_definition,
        )
        != runtime_definition_identity
    )
    assert resolved_runtime["runtime_profile"] == {
        "id": runtime_definition["id"],
        "version": runtime_definition["version"],
        "evaluation": runtime_definition["evaluation"],
        "numeric_policy": runtime_definition["numeric_policy"],
        "runtime_program_version": runtime_definition["runtime_program_version"],
        "numeric_law": runtime_definition["numeric_law"],
        "rng": runtime_definition["rng"],
        "budget_scopes": runtime_definition["budget_scopes"],
        "effects": runtime_definition["effects"],
        "max_steps": runtime_definition["resource_bounds"]["max_steps"],
    }
    identity_nodes = {
        runtime_definition_identity,
        evaluator["content_identity"],
        resolved_runtime["content_identity"],
    }

    def referenced_nodes(value: Any) -> set[str]:
        if isinstance(value, dict):
            return {
                reference
                for child in value.values()
                for reference in referenced_nodes(child)
            }
        if isinstance(value, list):
            return {
                reference for child in value for reference in referenced_nodes(child)
            }
        return {value} if isinstance(value, str) and value in identity_nodes else set()

    identity_graph = {
        runtime_definition_identity: referenced_nodes(runtime_definition),
        evaluator["content_identity"]: referenced_nodes(evaluator)
        - {evaluator["content_identity"]},
        resolved_runtime["content_identity"]: referenced_nodes(resolved_runtime)
        - {resolved_runtime["content_identity"]},
    }
    assert identity_graph == {
        runtime_definition_identity: set(),
        evaluator["content_identity"]: set(),
        resolved_runtime["content_identity"]: {
            runtime_definition_identity,
            evaluator["content_identity"],
        },
    }


def test_symbol_rename_reidentifies_the_exact_experiment_and_downstream_chain(
    tmp_path,
    run_cli,
):
    baseline = _rpg_model_source()
    renamed = deepcopy(baseline)
    defense = next(
        symbol
        for symbol in renamed["modules"][0]["symbols"]
        if symbol["symbol"] == "target_defense"
    )
    defense["symbol"] = "renamed_defense"
    for argument in renamed["entrypoints"][0]["arguments"]:
        operand = argument["operand"]
        if operand["kind"] == "symbol" and operand["symbol"] == "target_defense":
            operand["symbol"] = "renamed_defense"

    def build_and_run(
        label: str,
        source_value: dict[str, Any],
        build_key: str,
        experiment_key: str,
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, dict[str, Any]],
    ]:
        source_path = tmp_path / f"{label}-model.json"
        source_path.write_text(json.dumps(source_value), encoding="utf-8")
        build_exit, build_stdout, build_stderr = run_cli(
            [
                "model",
                "build",
                str(source_path),
                "--out",
                str(tmp_path / f"{label}-resolved-model.json"),
                "--invocation-key",
                build_key,
            ]
        )
        assert (build_exit, build_stderr) == (0, "")
        build_receipt = json.loads(build_stdout)
        build_record = _member(build_receipt, "build-receipt")
        specification = _experiment(
            kernel_identity=build_record["kernel_identity"],
            language_bundle_identity=build_record["language_bundle_identity"],
            source_identity=content_identity("model-source-package-v2", source_value),
            build_receipt=build_receipt,
            base_damage=24,
        )
        if label == "renamed":
            assignment = next(
                row
                for row in specification["scenarios"][0]["assignments"]
                if row["target"]["name"] == "target_defense"
            )
            assignment["target"]["name"] = "renamed_defense"
        specification_path = tmp_path / f"{label}-experiment.json"
        specification_path.write_text(json.dumps(specification), encoding="utf-8")
        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(specification_path),
                "--out",
                str(tmp_path / f"{label}-evaluation.json"),
                "--invocation-key",
                experiment_key,
            ]
        )
        assert (exit_code, stderr) == (0, "")
        receipt = json.loads(stdout)
        artifacts = {
            name: _member(receipt, name)
            for name in (
                "evaluation-run",
                "event-trace",
                "metric-dataset",
                "reproduction-receipt",
                "snapshot-series",
            )
        }
        return build_receipt, specification, receipt, artifacts

    baseline_build, baseline_spec, _baseline_receipt, baseline_artifacts = (
        build_and_run("baseline", baseline, "4" * 64, "6" * 64)
    )
    renamed_build, renamed_spec, _renamed_receipt, renamed_artifacts = build_and_run(
        "renamed", renamed, "5" * 64, "7" * 64
    )
    baseline_rir = _member(baseline_build, "rir-semantic-payload")
    renamed_rir = _member(renamed_build, "rir-semantic-payload")
    baseline_resolved = _member(baseline_build, "resolved-model")
    renamed_resolved = _member(renamed_build, "resolved-model")

    def defense_identities(
        rir: dict[str, Any],
    ) -> tuple[dict[str, str], set[str]]:
        declaration = next(
            row
            for row in rir["declarations"]
            if row["resolved_symbol"]["name"] in {"target_defense", "renamed_defense"}
        )
        entrypoint = next(
            row for row in rir["entrypoints"] if row["id"] == "combat.cast"
        )
        operands = {
            argument["operand"]["identity"]
            for argument in entrypoint["arguments"]
            if argument["port"]["name"] in {"hit_defense", "damage_mitigation"}
        }
        return declaration["resolved_symbol"], operands

    baseline_declaration, baseline_operands = defense_identities(baseline_rir)
    renamed_declaration, renamed_operands = defense_identities(renamed_rir)
    assert baseline_declaration != renamed_declaration
    assert len(baseline_operands) == len(renamed_operands) == 1
    assert baseline_operands != renamed_operands
    assert (
        baseline_rir["content_identity"] != renamed_rir["content_identity"]
        and baseline_resolved["content_identity"]
        != renamed_resolved["content_identity"]
    )
    assert experiment_runtime_module.experiment_input_identity(
        baseline_spec
    ) != experiment_runtime_module.experiment_input_identity(renamed_spec)
    assert all(
        baseline_artifacts[name]["content_identity"]
        != renamed_artifacts[name]["content_identity"]
        for name in baseline_artifacts
    )

    def numeric_projection(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        event = artifacts["event-trace"]["events"][0]
        return {
            "outcome": event["outcome"],
            "rng_draws": event["rng_draws"],
            "state_before": event["state_before"],
            "state_after": event["state_after"],
            "metrics": [
                {
                    "metric": sample["metric"],
                    "status": sample["status"],
                    "value": sample["value"],
                }
                for sample in artifacts["metric-dataset"]["samples"]
            ],
        }

    assert numeric_projection(baseline_artifacts) == numeric_projection(
        renamed_artifacts
    )


def test_artifact_lookup_skips_unrelated_damage_but_refuses_named_member_corruption(
    tmp_path,
    run_cli,
):
    source_value = _rpg_model_source()
    source = tmp_path / "lookup-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "lookup-resolved-model.json"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification_path = tmp_path / "lookup-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    unrelated_anchor = (
        Path(os.environ["GDA_BALANCING_STORE_DIR"])
        / "anchors"
        / "unrelated"
        / "damaged.json"
    )
    unrelated_anchor.parent.mkdir(parents=True)
    unrelated_anchor.write_text("not-json", encoding="utf-8")
    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (check_exit, check_stderr) == (0, "")
    assert json.loads(check_stdout)["checked"] is True

    build_locator = next(
        Path(row["locator"])
        for row in build_receipt["member_locators"]
        if row["logical_name"] == "build-receipt"
    )
    manifest_path = build_locator.parent / "artifact-set-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    replacement_manifest = json.loads(manifest_bytes)
    unrelated_member = next(
        row
        for row in replacement_manifest["members"]
        if row["logical_name"] != "build-receipt"
    )
    unrelated_member["content_identity"] = "sha256:" + "0" * 64
    replacement_body = {
        key: value
        for key, value in replacement_manifest.items()
        if key != "content_identity"
    }
    replacement_manifest["content_identity"] = content_identity(
        "artifact-set-manifest-v2",
        replacement_body,
    )
    manifest_path.write_bytes(canonical_bytes(replacement_manifest))
    context = authority_module.packaged_authority_context()
    assert (
        model_module.find_published_artifact(
            build_record["content_identity"],
            "build-receipt",
            context.language_bundle,
        )
        is None
    )
    manifest_path.write_bytes(manifest_bytes)

    corrupted = json.loads(build_locator.read_text(encoding="utf-8"))
    corrupted["source_identity"] = "sha256:" + "0" * 64
    build_locator.write_bytes(canonical_bytes(corrupted))

    refused_exit, refused_stdout, refused_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (refused_exit, refused_stderr) == (2, "")
    error = json.loads(refused_stdout)["error"]
    assert error["stage"] == "resolution"
    assert [row["code"] for row in error["diagnostics"]] == [
        "language.resolved_authority_mismatch"
    ]
    assert "failed integrity verification" in error["diagnostics"][0]["message"]


def test_kernel_runtime_contract_vectors_and_rng_execute_in_reference_evaluator():
    kernel = json.loads((_AUTHORITY_DIR / "kernel.json").read_text(encoding="utf-8"))
    runtime = kernel["meta_format"]["runtime_program"]
    nodes = {row["id"]: row for row in runtime["nodes"]}
    node_vectors = [vector for vector in runtime["vectors"] if vector["kind"] == "node"]
    assert {vector["node"] for vector in node_vectors} == set(nodes)
    for vector in node_vectors:
        node = nodes[vector["node"]]
        assert vector["input"]["contract-probe"] == node["required_members"]
        expected = {
            "operand_constraints": node["operand_constraints"],
            "operator": node["semantics"]["operator"],
            "result_kind": node["result"]["kind"],
            "charge": node["resource_charge"]["amount"],
        }
        if "typing" in node["result"]:
            expected["result_typing"] = node["result"]["typing"]
        assert vector["expect"] == expected

    rng_vectors = [vector for vector in runtime["vectors"] if vector["kind"] == "rng"]
    assert {vector["id"] for vector in rng_vectors} == {
        "rng.first-draw",
        "rng.multi-draw",
        "rng.cross-stream",
        "rng.interval-boundary",
    }
    for vector in rng_vectors:
        inputs = vector["input"]
        states: dict[str, int] = {}
        indices: dict[str, int] = {}
        draw = {}
        for _ in range(inputs["index"] + 1):
            draw = _reference_rng_draw(
                runtime["named_rng"],
                inputs["seed"],
                inputs["stream"],
                inputs["minimum"],
                inputs["maximum"],
                states,
                indices,
            )
        assert {
            "candidate_hex": draw["candidate_hex"],
            "accepted": draw["accepted"],
            "value": draw["value"],
        } == vector["expect"]


def test_package_runtime_scenario_vectors_execute_in_independent_reference_evaluator():
    kernel, ldb = authority_module.load_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    vectors = [
        vector
        for vector in next(
            vector_set["vector_definitions"]
            for vector_set in ldb.package_conformance_vector_sets
            if vector_set["package_id"] == "game.combat"
            and vector_set["package_version"] == "2.0.0"
        )
        if vector.get("kind") == "runtime-scenario"
    ]
    assert {vector["category"] for vector in vectors} == {
        "positive",
        "negative",
        "semantic-mutation",
        "outcome",
        "rollback-replay",
    }

    observed = {}
    for vector in vectors:
        operation = operations[vector["operation"]]
        scenario = {
            "id": vector["id"],
            "values": vector["input"]["values"],
        }
        event = _reference_execute_event(
            kernel,
            operation,
            operations,
            scenario,
            seed=vector["input"]["seed"],
            state_names=set(vector["input"]["state_names"]),
        )
        projection = {
            "outcome": event["outcome"]["id"],
            "rng_draws": [
                {
                    member: draw[member]
                    for member in ("candidate_hex", "index", "stream", "value")
                }
                for draw in event["rng_draws"]
            ],
            "state_after": event["state_after"],
        }
        assert projection == vector["expect"]
        replay = _reference_execute_event(
            kernel,
            operation,
            operations,
            scenario,
            seed=vector["input"]["seed"],
            state_names=set(vector["input"]["state_names"]),
        )
        assert replay == event
        observed[vector["id"]] = projection

    assert (
        observed["game.combat.cast.positive"]["rng_draws"]
        == observed["game.combat.cast.tuned-damage"]["rng_draws"]
    )
    assert (
        observed["game.combat.cast.positive"]["state_after"]
        != observed["game.combat.cast.tuned-damage"]["state_after"]
    )
    assert observed["game.combat.cast.miss-rollback"]["state_after"] == [
        {"name": "actor_resource", "value": 30},
        {"name": "target_health", "value": 100},
    ]


def test_package_value_program_vectors_execute_in_two_consumers():
    _kernel, ldb = authority_module.load_authorities()
    vectors = [
        vector
        for vector in next(
            vector_set["vector_definitions"]
            for vector_set in ldb.package_conformance_vector_sets
            if vector_set["package_id"] == "standard.runtime"
            and vector_set["package_version"] == "1.1.0"
        )
        if vector.get("kind") == "value-program"
    ]
    assert {vector["id"] for vector in vectors} == {
        "formula.runtime.accept.initialization-and-event-frames",
        "formula.runtime.refuse.initialization-atomically",
        "formula.runtime.boundary.cache-charge-invariant",
        "formula.runtime.observation.positive.post-transition-snapshot",
        "formula.runtime.observation.boundary.snapshot-cache-key",
        "formula.runtime.observation.refusal.atomic-prefix",
    }
    for vector in vectors:
        production = experiment_runtime_module._evaluate_value_program_vector(vector)
        reference = _reference_evaluate_value_program_vector(vector)
        assert production == reference == vector["expect"]


def test_package_observation_lifecycle_vectors_execute_in_two_consumers():
    _kernel, ldb = authority_module.load_authorities()
    vectors = [
        vector
        for vector in next(
            vector_set["vector_definitions"]
            for vector_set in ldb.package_conformance_vector_sets
            if vector_set["package_id"] == "standard.runtime"
            and vector_set["package_version"] == "1.1.0"
        )
        if ".observation." in vector["id"]
    ]
    assert {vector["id"] for vector in vectors} == {
        "formula.runtime.observation.positive.post-transition-snapshot",
        "formula.runtime.observation.boundary.snapshot-cache-key",
        "formula.runtime.observation.refusal.atomic-prefix",
    }
    expected_sites = {
        "runtime.lifecycle-observation.boundary",
        "runtime.lifecycle-observation.positive",
        "runtime.lifecycle-observation.refusal",
    }
    assert not any(
        row["artifact_kind"].startswith("formula-observation-")
        for row in ldb["language"]["artifact_wire_schemas"]
    )
    for vector in vectors:
        assert vector["kind"] == "value-program"
        assert vector["input"]["site"] in expected_sites
        production = experiment_runtime_module._evaluate_value_program_vector(vector)
        reference = _reference_evaluate_value_program_vector(vector)
        assert production == reference == vector["expect"]


def test_completed_negative_judgment_publishes_only_typed_verdict_set(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "4" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["metrics"][0]["target"] = {"minimum": 100, "maximum": 1000}
    spec_path = tmp_path / "negative-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(tmp_path / "negative-evaluation.json"),
            "--invocation-key",
            "5" * 64,
        ]
    )

    assert (exit_code, stderr) == (1, "")
    result = json.loads(stdout)
    assert result["outcome"] == "rejected"
    assert result["failed_metrics"] == ["damage_dealt"]
    receipt = result["artifact_set"]
    logical_names = {item["logical_name"] for item in receipt["member_locators"]}
    assert logical_names == {
        "evaluator-capability-manifest",
        "event-trace",
        "experiment-verdict",
        "metric-dataset",
        "reproduction-receipt",
        "resolved-runtime-profile",
        "snapshot-series",
    }
    assert "evaluation-run" not in logical_names
    verdict = _member(receipt, "experiment-verdict")
    assert verdict["outcome"] == "rejected"
    assert verdict["failed_metrics"] == ["damage_dealt"]


def test_evaluation_refusal_publishes_no_completed_outcome_artifacts(tmp_path, run_cli):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["metrics"][0]["observation"]["member"] = "missing_damage"
    spec_path = tmp_path / "unevaluable-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    out = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(out),
            "--invocation-key",
            "7" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert [item["code"] for item in error["diagnostics"]] == [
        "evaluation.observation_unavailable"
    ]
    assert not out.exists()
    assert "artifact_set" not in error


def test_predispatch_capability_refusal_publishes_no_terminal_audit(
    tmp_path, run_cli, monkeypatch
):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "8" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    monkeypatch.setattr(
        experiment_runtime_module,
        "_SUPPORTED_RUNTIME_OPERATORS",
        experiment_runtime_module._SUPPORTED_RUNTIME_OPERATORS - {"integer-multiply"},
    )
    spec_path = tmp_path / "runtime-refusal-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    out = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(out),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert [item["code"] for item in error["diagnostics"]] == [
        "runtime.capability_unsupported"
    ]
    assert "terminal_audit" not in error
    assert not out.exists()


def test_runtime_classifies_value_nodes_by_the_kernel_family(
    tmp_path, run_cli, monkeypatch
):
    specification = _write_built_experiment(tmp_path, run_cli)
    assert not hasattr(experiment_runtime_module, "_VALUE_RUNTIME_OPERATORS")
    monkeypatch.setattr(
        experiment_runtime_module,
        "_VALUE_RUNTIME_OPERATORS",
        frozenset(),
        raising=False,
    )

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "kernel-family-run"),
            "--invocation-key",
            "d" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), stdout


def test_experiment_check_refuses_duplicate_json_keys(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    text = specification.read_text(encoding="utf-8")
    specification.write_text(
        text.replace(
            '"schema_version": "2.0.0",',
            '"schema_version": "2.0.0", "schema_version": "2.0.0",',
            1,
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.source_parse_failure"
    ]


def test_experiment_refuses_nonempty_external_inputs_until_the_slice_consumes_them(
    tmp_path, run_cli
):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    value["external_inputs"] = [{"channel": "player", "index": 0, "value": 1}]
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == "/external_inputs"


def test_required_evaluator_must_exactly_close_the_selected_program(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    value["runtime"]["required_evaluator"]["instruction_nodes"].remove("multiply")
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/runtime/required_evaluator/instruction_nodes"
    )


def test_evaluator_manifest_binds_the_selected_runtime_profile(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "evaluation.json"),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    evaluator = _member(receipt, "evaluator-capability-manifest")
    runtime = _member(receipt, "resolved-runtime-profile")
    assert evaluator["runtime_profiles"] == ["standard.exact-int64-event-v1"]
    assert runtime["runtime_profile"]["id"] in evaluator["runtime_profiles"]


def test_evaluator_manifest_uses_selected_operation_closure_and_build_provenance(
    tmp_path, run_cli, monkeypatch
):
    specification = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_runtime_module.check_experiment(str(specification))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)

    first = experiment_runtime_module._evaluator_manifest(checked)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    assert set(first.value["instruction_nodes"]) == {
        instruction["node"]
        for scenario in checked.value["scenarios"]
        for instruction in experiment_runtime_module._expanded_operation_body(
            operations[entrypoints[scenario["entrypoint"]]["operation"]["id"]],
            operations,
        )
    }
    assert first.value["evaluator_build_identity"] == (
        experiment_runtime_module._evaluator_build_identity()
    )
    monkeypatch.setattr(
        experiment_runtime_module,
        "_evaluator_build_identity",
        lambda: "sha256:" + ("0" * 64),
    )
    changed_build = experiment_runtime_module._evaluator_manifest(checked)
    assert (
        changed_build.value["implementation_identity"]
        != (first.value["implementation_identity"])
    )
    assert changed_build.content_identity != first.content_identity


def test_metric_dataset_carries_the_complete_bounded_metric_contract(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    for index, metric in enumerate(value["metrics"]):
        metric.update(
            {
                "dimensions": [
                    {
                        "name": "difficulty",
                        "value": ("hard" if index == 0 else "normal"),
                    }
                ],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
            }
        )
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "metric-contract.json"),
            "--invocation-key",
            "f" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    dataset = _member(receipt, "metric-dataset")
    assert dataset["experiment_identity"]
    assert dataset["metric_definition_identities"]
    assert dataset["source_provenance"]["kind"] == "simulated"
    assert dataset["source_provenance"]["resolved_model_identity"]
    assert dataset["source_provenance"]["resolved_runtime_profile_identity"]
    assert dataset["data_version"] == "1"
    assert dataset["partition"] == "evaluation"
    assert dataset["ordering"] == "metric-definition-identity,replication-identity"
    assert dataset["ingestion_transformation_identity"] is None
    metrics = {metric["id"]: metric for metric in value["metrics"]}
    for sample in dataset["samples"]:
        assert (
            sample["metric_definition_identity"]
            in (dataset["metric_definition_identities"])
        )
        assert sample["status"] == "value"
        assert sample["logical_time"] == 0
        assert sample["window"] == "terminal-event"
        assert sample["dimensions"] == metrics[sample["metric"]]["dimensions"]
        assert sample["replication_identity"]
        assert sample["source_kind"] == "simulated"
        assert sample["provenance"]["scenario"]


def test_metric_dataset_canonicalizes_reversed_authored_metrics(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    value["metrics"].sort(
        key=experiment_runtime_module._metric_definition_identity,
        reverse=True,
    )
    authored_identities = [
        experiment_runtime_module._metric_definition_identity(metric)
        for metric in value["metrics"]
    ]
    assert authored_identities == sorted(authored_identities, reverse=True)
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "reversed-metrics.json"),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    dataset = _member(json.loads(stdout), "metric-dataset")
    assert dataset["metric_definition_identities"] == sorted(authored_identities)
    sample_order = [
        (
            sample["metric_definition_identity"],
            sample["replication_identity"],
        )
        for sample in dataset["samples"]
    ]
    assert sample_order == sorted(sample_order)


def test_metric_dataset_canonicalizer_orders_multiple_replications():
    samples = [
        {
            "metric_definition_identity": "sha256:b",
            "replication_identity": "replication-b",
        },
        {
            "metric_definition_identity": "sha256:a",
            "replication_identity": "replication-b",
        },
        {
            "metric_definition_identity": "sha256:a",
            "replication_identity": "replication-a",
        },
    ]

    identities, ordered = experiment_runtime_module._canonical_metric_dataset(samples)

    assert identities == ["sha256:a", "sha256:b"]
    assert [
        (
            sample["metric_definition_identity"],
            sample["replication_identity"],
        )
        for sample in ordered
    ] == [
        ("sha256:a", "replication-a"),
        ("sha256:a", "replication-b"),
        ("sha256:b", "replication-b"),
    ]


def test_numeric_overflow_rolls_back_the_entire_current_event(tmp_path, run_cli):
    source_value = _rpg_model_source()
    base_damage = next(
        symbol
        for symbol in source_value["modules"][0]["symbols"]
        if symbol["symbol"] == "base_damage"
    )
    base_damage["domain"]["maximum"] = (1 << 63) - 1
    source = tmp_path / "rpg-overflow-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-overflow-model.json"),
            "--invocation-key",
            "a" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=1 << 62,
    )
    threshold = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "critical_threshold"
    )
    threshold["value"] = 100
    spec_path = tmp_path / "overflow-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(tmp_path / "overflow-terminal-audit.json"),
            "--invocation-key",
            "b" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    assert [item["code"] for item in error["diagnostics"]] == [
        "runtime.numeric_overflow"
    ]
    audit = _member(error["terminal_audit"], "runtime-terminal-audit")
    assert audit["committed_trace_prefix"] == []
    assert audit["refusing_event"]["operation"] == "game.combat.damage-v1"
    assert audit["refusing_event"]["reason"] == "runtime.numeric_overflow"
    assert audit["refusing_event"]["entrypoint"]["id"] == "combat.cast"
    assert audit["refusing_event"]["entrypoint"]["identity"].startswith("sha256:")
    assert audit["refusing_event"]["call_path"] == "combat.cast/apply-damage"
    assert audit["refusing_event"]["call_site_identity"].startswith("sha256:")
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_before"] == [
        {"name": "actor_mana", "value": 30},
        {"name": "target_health", "value": 100},
    ]
    assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]
    kernel, ldb = authority_module.load_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    rir = _member(build_receipt, "rir-semantic-payload")
    resolved_entrypoint = next(
        row for row in rir["entrypoints"] if row["id"] == "combat.cast"
    )
    reference = _reference_execute_event(
        kernel,
        operations["game.combat.cast-v1"],
        operations,
        specification["scenarios"][0],
        seed=specification["seed"]["value"],
        resolved_entrypoint=resolved_entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        resolved_initialization_programs=rir["initialization_programs"],
    )
    assert reference == {
        "refusal": {
            "reason": audit["refusing_event"]["reason"],
            "operation": audit["refusing_event"]["operation"],
            "call_path": audit["refusing_event"]["call_path"],
            "call_site_identity": audit["refusing_event"]["call_site_identity"],
        },
        "state_before": audit["rollback"]["state_before"],
        "state_after": audit["rollback"]["state_after"],
    }


def test_formula_overflow_terminal_audit_names_the_exact_evaluation_site(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    target_defense = next(
        row
        for row in source_value["modules"][0]["symbols"]
        if row["symbol"] == "target_defense"
    )
    target_defense["domain"]["minimum"] = -(1 << 63)
    source = tmp_path / "formula-overflow-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "formula-overflow-model"),
            "--invocation-key",
            "4" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    rir = _member(build_receipt, "rir-semantic-payload")
    formula_site = next(
        row["site"]["identity"]
        for row in rir["formula_bindings"]
        if row["site"]["kind"] == "operation-slot"
    )
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    mitigation = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "target_defense"
    )
    mitigation["value"] = -(1 << 63)
    spec_path = tmp_path / "formula-overflow-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(tmp_path / "formula-overflow-terminal-audit.json"),
            "--invocation-key",
            "5" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    audit = _member(error["terminal_audit"], "runtime-terminal-audit")
    assert audit["refusing_event"]["reason"] == "runtime.numeric_overflow"
    assert audit["refusing_event"]["evaluation_site_identity"] == formula_site
    assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]


def test_ordered_writable_aliases_share_one_runtime_location(tmp_path, run_cli):
    specification_path = _write_built_experiment(
        tmp_path,
        run_cli,
        base_damage=90,
    )
    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    damage = operations["game.combat.damage-v1"]
    damage["alias_policy"]["writable_groups"] = [
        {
            "ports": ["mitigation", "target_health"],
            "semantics": "operation-body-order",
        }
    ]
    write = next(
        instruction
        for instruction in damage["body"]
        if instruction["node"] == "subtract-state"
    )
    damage["body"].remove(write)
    damage["body"].insert(0, {**write, "value": "base_damage"})
    cast_operation = operations["game.combat.cast-v1"]
    damage_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    mitigation = next(
        argument
        for argument in damage_call["arguments"]
        if argument["port"] == "mitigation"
    )
    mitigation["operand"]["port"] = "target_health"
    lowering = checked.language_bundle["language"]["model_lowerings"][0]
    rir["call_sites"] = model_module._resolved_call_sites(
        checked.kernel,
        rir["selected_semantics"],
        lowering["composition_policy"],
    )
    alias = next(
        row
        for call_site in rir["call_sites"]
        if call_site["site"] == "apply-damage"
        for row in cast(list[dict[str, Any]], call_site["aliases"])
    )
    assert alias == {
        "actual_operand_identity": alias["actual_operand_identity"],
        "ports": ["mitigation", "target_health"],
        "policy": "operation-body-order",
    }
    value = deepcopy(checked.value)
    value["scenarios"][0]["assignments"] = [
        {
            **assignment,
            "value": (
                90
                if assignment["target"]["name"] == "base_damage"
                else assignment["value"]
            ),
        }
        for assignment in value["scenarios"][0]["assignments"]
    ]
    candidate = replace(
        checked,
        value=value,
        content_identity=experiment_runtime_module.experiment_input_identity(value),
        rir=rir,
    )

    production = experiment_runtime_module.evaluate_experiment(candidate)

    assert isinstance(production, experiment_runtime_module.EvaluationArtifacts)
    production_event = production.members["event-trace"].value["events"][0]
    entrypoint = next(row for row in rir["entrypoints"] if row["id"] == "combat.cast")
    reference_event = _reference_execute_event(
        checked.kernel,
        operations["game.combat.cast-v1"],
        operations,
        value["scenarios"][0],
        seed=value["seed"]["value"],
        resolved_entrypoint=entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        resolved_initialization_programs=rir["initialization_programs"],
    )
    assert {
        key: item for key, item in production_event.items() if key != "index"
    } == reference_event
    assert (
        next(
            row["integer"]
            for row in production_event["facts"]
            if row["name"] == "damage_dealt"
        )
        == 80
    )
    assert production_event["state_after"] == [
        {"name": "actor_mana", "value": 22},
        {"name": "target_health", "value": 10},
    ]


def test_nested_integer_literal_is_observable_across_evaluators(tmp_path, run_cli):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    cast_operation = operations["game.combat.cast-v1"]
    spend_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "spend-resource"
    )
    cost = next(
        argument for argument in spend_call["arguments"] if argument["port"] == "cost"
    )
    cost["operand"] = {"kind": "literal", "literal": 8}
    lowering = checked.language_bundle["language"]["model_lowerings"][0]
    rir["call_sites"] = model_module._resolved_call_sites(
        checked.kernel,
        rir["selected_semantics"],
        lowering["composition_policy"],
    )
    candidate = replace(checked, rir=rir)

    production = experiment_runtime_module.evaluate_experiment(candidate)

    assert isinstance(production, experiment_runtime_module.EvaluationArtifacts)
    production_event = production.members["event-trace"].value["events"][0]
    entrypoint = next(row for row in rir["entrypoints"] if row["id"] == "combat.cast")
    reference_event = _reference_execute_event(
        checked.kernel,
        cast_operation,
        operations,
        checked.value["scenarios"][0],
        seed=checked.value["seed"]["value"],
        resolved_entrypoint=entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        resolved_initialization_programs=rir["initialization_programs"],
    )
    assert {
        key: value for key, value in production_event.items() if key != "index"
    } == reference_event
    assert production_event["state_after"] == [
        {"name": "actor_mana", "value": 22},
        {"name": "target_health", "value": 82},
    ]
    call_sites = cast(list[dict[str, Any]], rir["call_sites"])
    spend_site = next(row for row in call_sites if row["site"] == "spend-resource")
    cost_operand = next(
        row["operand"]
        for row in spend_site["arguments"]
        if row["port"]["name"] == "cost"
    )
    assert cost_operand["kind"] == "literal"
    assert cost_operand["value"] == 8
    assert cost_operand["context_type"]["id"] == "quantity.dimensionless-int64"


def test_nested_operation_result_is_observable_across_evaluators(tmp_path, run_cli):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    cast_operation = operations["game.combat.cast-v1"]
    damage_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    damage_call["result"] = {"kind": "operation-result"}
    cast_operation["result"]["source"] = {
        "kind": "operation-result",
        "site": "apply-damage",
    }
    lowering = checked.language_bundle["language"]["model_lowerings"][0]
    rir["call_sites"] = model_module._resolved_call_sites(
        checked.kernel,
        rir["selected_semantics"],
        lowering["composition_policy"],
    )
    candidate = replace(checked, rir=rir)

    production = experiment_runtime_module.evaluate_experiment(candidate)

    assert isinstance(production, experiment_runtime_module.EvaluationArtifacts)
    production_event = production.members["event-trace"].value["events"][0]
    entrypoint = next(row for row in rir["entrypoints"] if row["id"] == "combat.cast")
    reference_event = _reference_execute_event(
        checked.kernel,
        cast_operation,
        operations,
        checked.value["scenarios"][0],
        seed=checked.value["seed"]["value"],
        resolved_entrypoint=entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        resolved_initialization_programs=rir["initialization_programs"],
    )
    assert {
        key: value for key, value in production_event.items() if key != "index"
    } == reference_event
    assert (
        next(
            row["integer"]
            for row in production_event["facts"]
            if row["name"] == "damage_dealt"
        )
        == 18
    )


def test_ordered_writable_alias_write_is_visible_to_later_child_call(
    tmp_path,
    run_cli,
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_runtime_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_runtime_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    cast_operation = operations["game.combat.cast-v1"]
    cast_operation["alias_policy"]["writable_groups"] = [
        {
            "ports": ["actor_resource", "accuracy"],
            "semantics": "operation-body-order",
        }
    ]
    entrypoint = next(row for row in rir["entrypoints"] if row["id"] == "combat.cast")
    actor_resource = next(
        row
        for row in entrypoint["arguments"]
        if row["port"]["name"] == "actor_resource"
    )
    accuracy = next(
        row for row in entrypoint["arguments"] if row["port"]["name"] == "accuracy"
    )
    accuracy["operand"] = deepcopy(actor_resource["operand"])
    actual_identity = actor_resource["operand"]["identity"]
    entrypoint["aliases"] = [
        {
            "actual_operand_identity": actual_identity,
            "ports": ["actor_resource", "accuracy"],
            "policy": "operation-body-order",
        }
    ]
    value = deepcopy(checked.value)
    value["scenarios"][0]["assignments"] = [
        {
            **assignment,
            "value": (
                35
                if assignment["target"]["name"] == "target_defense"
                else assignment["value"]
            ),
        }
        for assignment in value["scenarios"][0]["assignments"]
    ]
    value["metrics"] = [
        _metric_contract(
            {
                "id": "target_health_remaining",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "target_health",
                },
                "target": {"minimum": 100, "maximum": 100},
            }
        )
    ]
    candidate = replace(
        checked,
        value=value,
        content_identity=experiment_runtime_module.experiment_input_identity(value),
        rir=rir,
    )

    production = experiment_runtime_module.evaluate_experiment(candidate)

    assert isinstance(production, experiment_runtime_module.EvaluationArtifacts)
    production_event = production.members["event-trace"].value["events"][0]
    reference_event = _reference_execute_event(
        checked.kernel,
        cast_operation,
        operations,
        value["scenarios"][0],
        seed=value["seed"]["value"],
        resolved_entrypoint=entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        resolved_initialization_programs=rir["initialization_programs"],
    )
    assert {
        key: item for key, item in production_event.items() if key != "index"
    } == reference_event
    assert production_event["outcome"]["id"] == "miss"
    assert production_event["state_after"] == [
        {"name": "actor_mana", "value": 30},
        {"name": "target_health", "value": 100},
    ]


def test_gameplay_alternative_is_a_committed_typed_event_not_a_refusal(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "c" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    actor_mana = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "actor_mana"
    )
    actor_mana["value"] = 4
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "actor_mana_remaining",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "event",
                    "name": "insufficient-resource",
                    "member": "actor_mana",
                },
                "target": {"minimum": 4, "maximum": 4},
            }
        ),
        _metric_contract(
            {
                "id": "target_health_remaining",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "target_health",
                },
                "target": {"minimum": 100, "maximum": 100},
            }
        ),
    ]
    spec_path = tmp_path / "insufficient-resource-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(tmp_path / "insufficient-resource-evaluation.json"),
            "--invocation-key",
            "d" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    trace = _member(json.loads(stdout), "event-trace")
    event = trace["events"][0]
    assert event["outcome"] == {
        "id": "insufficient-resource",
        "kind": "gameplay-alternative",
    }
    assert event["state_before"] == event["state_after"]


def test_gameplay_outcomes_are_closed_and_exhaustively_typed(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    scenarios = {
        "cast-resolved": value,
        "miss": json.loads(json.dumps(value)),
        "insufficient-resource": json.loads(json.dumps(value)),
    }
    for row in scenarios["miss"]["scenarios"][0]["assignments"]:
        if row["target"]["name"] == "accuracy":
            row["value"] = 0
        elif row["target"]["name"] == "target_defense":
            row["value"] = 1000
    for row in scenarios["insufficient-resource"]["scenarios"][0]["assignments"]:
        if row["target"]["name"] == "actor_mana":
            row["value"] = 0
    for outcome, scenario in scenarios.items():
        scenario["metrics"] = [
            _metric_contract(
                {
                    "id": "terminal-health",
                    "kind": "scalar",
                    "unit": "1",
                    "observation": {
                        "source": "snapshot",
                        "name": "terminal",
                        "member": "target_health",
                    },
                    "target": {"minimum": 0, "maximum": 1000},
                }
            )
        ]
        path = tmp_path / f"{outcome}.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(path),
                "--out",
                str(tmp_path / f"{outcome}-out.json"),
                "--invocation-key",
                {
                    "cast-resolved": "1",
                    "miss": "2",
                    "insufficient-resource": "3",
                }[outcome]
                * 64,
            ]
        )
        assert (exit_code, stderr) == (0, "")
        event = _member(json.loads(stdout), "event-trace")["events"][0]
        assert event["outcome"] == {
            "id": outcome,
            "kind": (
                "success" if outcome == "cast-resolved" else "gameplay-alternative"
            ),
        }


def test_operation_step_budget_is_scoped_per_event_not_across_scenarios(
    tmp_path, run_cli
):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    base_scenario = value["scenarios"][0]
    value["scenarios"] = []
    for index in range(5):
        scenario = json.loads(json.dumps(base_scenario))
        scenario["id"] = f"cast-{index}"
        value["scenarios"].append(scenario)
    value["metrics"] = [
        _metric_contract(
            {
                "id": "first-terminal-health",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "snapshot",
                    "name": "cast-0:terminal",
                    "member": "target_health",
                },
                "target": {"minimum": 0, "maximum": 1000},
            }
        )
    ]
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "multi-scenario.json"),
            "--invocation-key",
            "4" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    trace = _member(json.loads(stdout), "event-trace")
    assert len(trace["events"]) == 5


def test_second_scenario_runtime_refusal_binds_the_exact_scenario(tmp_path, run_cli):
    source_value = _rpg_model_source()
    base_damage = next(
        symbol
        for symbol in source_value["modules"][0]["symbols"]
        if symbol["symbol"] == "base_damage"
    )
    base_damage["domain"]["maximum"] = (1 << 63) - 1
    source = tmp_path / "rpg-overflow-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-overflow-model.json"),
            "--invocation-key",
            "5" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    value = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    second = json.loads(json.dumps(value["scenarios"][0]))
    second["id"] = "overflowing-cast"
    for row in second["assignments"]:
        if row["target"]["name"] == "base_damage":
            row["value"] = 1 << 62
        elif row["target"]["name"] == "critical_threshold":
            row["value"] = 100
    value["scenarios"].append(second)
    path = tmp_path / "second-scenario-overflow.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(path),
            "--out",
            str(tmp_path / "second-scenario-audit.json"),
            "--invocation-key",
            "6" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    audit = _member(error["terminal_audit"], "runtime-terminal-audit")
    assert audit["scenario"] == "overflowing-cast"
    assert audit["committed_trace_prefix"] == [
        {
            "index": 0,
            "operation": "game.combat.cast-v1",
            "outcome": {"id": "cast-resolved", "kind": "success"},
        }
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
    ],
)
def test_experiment_precommit_faults_leave_no_visible_or_partial_set(
    tmp_path, run_cli, fault
):
    specification = _write_built_experiment(tmp_path, run_cli)
    out = tmp_path / f"{fault}.json"
    key = "2" * 64
    faulting = replace(
        experiment_command_module.EXPERIMENT_RUN,
        handler=experiment_command_module.experiment_run_handler(
            publication_fault=fault
        ),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(out),
            "--invocation-key",
            key,
        ],
        registry=(faulting,),
    )

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    descriptor_key = descriptor_identity(
        experiment_command_module.EXPERIMENT_RUN
    ).removeprefix("sha256:")
    assert not (store / "invocations" / descriptor_key / key).exists()
    assert not (store / "anchors" / descriptor_key / f"{key}.json").exists()


@pytest.mark.parametrize("outcome", ["success", "verdict", "runtime"])
def test_postcommit_delivery_failure_recovers_every_outcome_without_rerunning(
    tmp_path, run_cli, monkeypatch, outcome
):
    specification = _write_built_experiment(tmp_path, run_cli)
    specification_value = json.loads(specification.read_text(encoding="utf-8"))
    if outcome == "verdict":
        specification_value["metrics"][0]["target"] = {
            "minimum": 100,
            "maximum": 1000,
        }
    elif outcome == "runtime":
        admit_numeric = experiment_runtime_module._admit_numeric
        numeric_admissions = 0

        def overflow_at_runtime(value, numeric):
            nonlocal numeric_admissions
            numeric_admissions += 1
            if numeric_admissions <= 3:
                return admit_numeric(value, numeric)
            raise OverflowError

        monkeypatch.setattr(
            experiment_runtime_module,
            "_admit_numeric",
            overflow_at_runtime,
        )
    specification.write_text(json.dumps(specification_value), encoding="utf-8")
    out = tmp_path / "recovered-evaluation.json"
    key = "3" * 64
    argv = [
        "experiment",
        "run",
        str(specification),
        "--out",
        str(out),
        "--invocation-key",
        key,
    ]
    faulting = replace(
        experiment_command_module.EXPERIMENT_RUN,
        handler=experiment_command_module.experiment_run_handler(
            publication_fault="after-commit"
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()

    def evaluator_must_not_run(_checked):
        raise AssertionError("Invocation-key recovery reran the evaluator")

    monkeypatch.setattr(
        experiment_command_module,
        "evaluate_experiment",
        evaluator_must_not_run,
    )
    recovered_exit, recovered_stdout, recovered_stderr = run_cli(
        argv,
        registry=(experiment_command_module.EXPERIMENT_RUN,),
    )

    assert recovered_stderr == ""
    recovered = json.loads(recovered_stdout)
    if outcome == "success":
        assert recovered_exit == 0
        assert recovered["invocation_key"] == key
    elif outcome == "verdict":
        assert recovered_exit == 1
        assert recovered["outcome"] == "rejected"
        assert recovered["artifact_set"]["invocation_key"] == key
    else:
        assert recovered_exit == 2
        error = recovered["error"]
        assert error["stage"] == "runtime"
        assert error["diagnostics"][0]["primary"]["pointer"] == (
            "/scenarios/0/entrypoint"
        )
        audit = _member(error["terminal_audit"], "runtime-terminal-audit")
        assert audit["refusing_event"]["entrypoint"]["id"] == "combat.cast"
        assert audit["refusing_event"]["entrypoint"]["identity"].startswith("sha256:")
        assert audit["refusing_event"]["call_path"] == ("combat.cast/spend-resource")
        assert audit["refusing_event"]["call_site_identity"].startswith("sha256:")
        assert audit["diagnostic"] == {
            "stage": "runtime",
            **error["diagnostics"][0],
        }
    assert out.exists()


@pytest.mark.parametrize(
    "presentation",
    ["invocation-member", "store-member", "symlink-ancestor"],
)
def test_committed_recovery_revalidates_the_presentation_trust_boundary(
    tmp_path, run_cli, monkeypatch, presentation
):
    specification = _write_built_experiment(tmp_path, run_cli)
    key = "4" * 64
    first = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "first-evaluation.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    receipt = json.loads(first[1])
    invocation_path = Path(receipt["manifest_locator"]).parent
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    if presentation == "invocation-member":
        recovered_out = invocation_path / "recovered-evaluation.json"
    elif presentation == "store-member":
        recovered_out = store / "recovered-evaluation.json"
    else:
        actual_parent = tmp_path / "actual-presentation"
        actual_parent.mkdir()
        alias_parent = tmp_path / "presentation-alias"
        alias_parent.symlink_to(actual_parent, target_is_directory=True)
        recovered_out = alias_parent / "recovered-evaluation.json"
    store_before = {
        path.relative_to(store): path.read_bytes()
        for path in store.rglob("*")
        if path.is_file()
    }

    def evaluator_must_not_run(_checked):
        raise AssertionError("invalid recovery presentation reran the evaluator")

    monkeypatch.setattr(
        experiment_command_module,
        "evaluate_experiment",
        evaluator_must_not_run,
    )
    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(recovered_out),
            "--invocation-key",
            key,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"
    assert not recovered_out.exists()
    assert {
        path.relative_to(store): path.read_bytes()
        for path in store.rglob("*")
        if path.is_file()
    } == store_before
