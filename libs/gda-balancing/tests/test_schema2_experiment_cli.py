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
import gda_balancing.schema2.experiment as experiment_runtime_module
from gda_balancing.schema2.canonical import content_identity
from gda_balancing.schema2.surface import descriptor_identity

_EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "schema2" / "rpg-combat-cast"
_AUTHORITY_DIR = (
    Path(__file__).parents[1] / "src" / "gda_balancing" / "schema2" / "authorities"
)


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
    return {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "example.rpg-combat-cast",
            "version": "1.0.0",
            "entry_module": "combat",
        },
        "package_requirements": [
            {"id": "core.quantity", "version": "2.0.0"},
            {"id": "game.combat", "version": "1.0.0"},
        ],
        "modules": [
            {
                "id": "combat",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [
                    _rpg_value("actor_mana", "state"),
                    _rpg_value("action_cost", "parameter"),
                    _rpg_value("accuracy", "parameter"),
                    _rpg_value("base_damage", "parameter"),
                    _rpg_value("critical_threshold", "parameter"),
                    _rpg_value("target_defense", "input"),
                    _rpg_value("target_health", "state"),
                    _rpg_value("damage_dealt", "output"),
                ],
            }
        ],
        "entrypoints": [
            {
                "id": "combat.cast",
                "operation": {
                    "package": "game.combat",
                    "version": "1.0.0",
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
                        ("accuracy", "accuracy"),
                        ("base_damage", "base_damage"),
                        ("critical_threshold", "critical_threshold"),
                        ("hit_defense", "target_defense"),
                        ("damage_mitigation", "target_defense"),
                        ("target_health", "target_health"),
                    )
                ],
                "result": {
                    "kind": "symbol",
                    "module": "combat",
                    "symbol": "damage_dealt",
                },
            }
        ],
    }


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
    return {
        "stream": stream,
        "index": index,
        "candidate_hex": f"{candidate:016x}",
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
    state_cells = {
        name: cells[name] for name in state_targets if name in cells
    }
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
        assert numeric["minimum"] <= value <= numeric["maximum"]
        return value

    def execute(
        selected: dict[str, Any],
        arguments: dict[str, dict[str, Any]],
        stack: tuple[str, ...] = (),
        path: tuple[str, ...] = (),
    ) -> tuple[str, Any]:
        assert selected["id"] not in stack
        locals_: dict[str, dict[str, Any]] = {}
        frame_cells = {id(cell): cell for cell in arguments.values()}
        snapshot = {key: cell["value"] for key, cell in frame_cells.items()}
        outcome = selected["default_outcome"]

        def cell(name: str) -> dict[str, Any]:
            if name in locals_:
                return locals_[name]
            return arguments[name]

        def write_local(name: str, value: Any) -> None:
            locals_[name] = {"value": value}

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
                        actual = {"value": operand["value"]}
                    child_arguments[binding["port"]] = actual
                child_outcome, child_result = execute(
                    child,
                    child_arguments,
                    (*stack, selected["id"]),
                    (*path, instruction["site"]),
                )
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

        outcome_definition = next(
            row for row in selected["outcomes"] if row["id"] == outcome
        )
        if outcome_definition["state_policy"] == "rollback":
            for key, value in snapshot.items():
                frame_cells[key]["value"] = value
        source = selected["result"]["source"]
        if source["kind"] == "local":
            result = locals_.get(source["name"], {"value": 0})["value"]
        elif source["kind"] == "port":
            result = arguments[source["name"]]["value"]
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
            row["port"]: cells[row["operand"]["symbol"]]
            for row in root_arguments
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
    outcome, result = execute(
        operation,
        root_frame,
        path=((resolved_entrypoint["id"],) if resolved_entrypoint else ()),
    )
    if (
        resolved_entrypoint is not None
        and resolved_entrypoint["result"]["kind"] == "symbol"
    ):
        symbol = resolved_entrypoint["result"]["symbol"]
        coordinate = (symbol["model"], symbol["module"], symbol["name"])
        cells[coordinate] = {"value": result}
        display_names[coordinate] = symbol["name"]
    outcome_definition = next(
        row for row in operation["outcomes"] if row["id"] == outcome
    )
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
    assert (build_exit, build_stderr) == (0, "")
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


def test_public_experiment_uses_resolved_entrypoint_bindings_not_shared_names(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    symbols = source_value["modules"][0]["symbols"]
    symbols[:] = [
        symbol for symbol in symbols if symbol["symbol"] != "target_defense"
    ]
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
                "version": "1.0.0",
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
                    ("accuracy", "accuracy"),
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
        "identity": _member(build_receipt, "rir-semantic-payload")["entrypoints"][
            0
        ]["identity"],
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
    assert error["diagnostics"][0]["primary"]["pointer"] == "/entrypoints"


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

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification)]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/scenarios/0/assignments"
    )


def test_experiment_cannot_select_a_raw_ldb_operation(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    scenario = value["scenarios"][0]
    scenario.pop("entrypoint")
    scenario["operation"] = "game.combat.cast-v1"
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification)]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    pointer = error["diagnostics"][0]["primary"]["pointer"]
    assert pointer in {
        "/scenarios/0/entrypoint",
        "/scenarios/0/operation",
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
    first_path = tmp_path / "experiment-24.json"
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
            str(tmp_path / "evaluation-24.json"),
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
    _loaded_kernel, ldb = experiment_runtime_module.load_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    combat_vectors = next(
        vector_set["vector_definitions"]
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "game.combat"
        and vector_set["package_version"] == "1.0.0"
    )
    combat_vectors = {
        vector["id"]: vector
        for vector in combat_vectors
        if vector.get("kind") == "runtime-scenario"
    }

    def vector_projection(event):
        return {
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

    public_positive_expect = json.loads(
        json.dumps(combat_vectors["game.combat.cast.positive"]["expect"])
    )
    public_positive_expect["state_after"][0]["name"] = "actor_mana"
    assert vector_projection(first_trace["events"][0]) == public_positive_expect
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
        == 24
    )
    first_damage = next(
        sample["value"]
        for sample in first_metrics["samples"]
        if sample["metric"] == "damage_dealt"
    )

    tuned_spec = json.loads(json.dumps(first_spec))
    base_damage = next(
        row
        for row in tuned_spec["scenarios"][0]["assignments"]
        if row["target"]["name"] == "base_damage"
    )
    base_damage["value"] = 40
    tuned_path = tmp_path / "experiment-40.json"
    tuned_path.write_text(json.dumps(tuned_spec), encoding="utf-8")
    tuned_exit, tuned_stdout, tuned_stderr = run_cli(
        [
            "experiment",
            "run",
            str(tuned_path),
            "--out",
            str(tmp_path / "evaluation-40.json"),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (tuned_exit, tuned_stderr) == (0, "")
    tuned_receipt = json.loads(tuned_stdout)
    tuned_trace = _member(tuned_receipt, "event-trace")
    tuned_metrics = _member(tuned_receipt, "metric-dataset")
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
        == 40
    )
    assert tuned_damage > first_damage
    assert (
        tuned_trace["content_identity"] != first_trace["content_identity"]
        and tuned_metrics["content_identity"] != first_metrics["content_identity"]
    )
    public_tuned_expect = json.loads(
        json.dumps(combat_vectors["game.combat.cast.tuned-damage"]["expect"])
    )
    public_tuned_expect["state_after"][0]["name"] = "actor_mana"
    assert vector_projection(tuned_trace["events"][0]) == public_tuned_expect


def test_kernel_runtime_contract_vectors_and_rng_execute_in_reference_evaluator():
    kernel = json.loads((_AUTHORITY_DIR / "kernel.json").read_text(encoding="utf-8"))
    runtime = kernel["meta_format"]["runtime_program"]
    nodes = {row["id"]: row for row in runtime["nodes"]}
    node_vectors = [vector for vector in runtime["vectors"] if vector["kind"] == "node"]
    assert {vector["node"] for vector in node_vectors} == set(nodes)
    for vector in node_vectors:
        node = nodes[vector["node"]]
        assert vector["input"]["contract-probe"] == node["required_members"]
        assert vector["expect"] == {
            "operator": node["semantics"]["operator"],
            "result_kind": node["result"]["kind"],
            "charge": node["resource_charge"]["amount"],
        }

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
    kernel, ldb = experiment_runtime_module.load_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    vectors = [
        vector
        for vector in next(
            vector_set["vector_definitions"]
            for vector_set in ldb.package_conformance_vector_sets
            if vector_set["package_id"] == "game.combat"
            and vector_set["package_version"] == "1.0.0"
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

        def overflow_at_runtime(_value, _numeric):
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
        assert audit["refusing_event"]["entrypoint"]["identity"].startswith(
            "sha256:"
        )
        assert audit["refusing_event"]["call_path"] == (
            "combat.cast/spend-resource"
        )
        assert audit["refusing_event"]["call_site_identity"].startswith(
            "sha256:"
        )
        assert audit["diagnostic"] == {
            "stage": "runtime",
            **error["diagnostics"][0],
        }
    assert out.exists()
