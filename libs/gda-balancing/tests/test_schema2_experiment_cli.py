"""Public RPG Experiment tracer for Standard Schema 2.0 (#540)."""

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest
import jsonschema

import gda_balancing.application.experiment_run as experiment_run_application_module
import gda_balancing.domain.experiment as experiment_admission_module
import gda_balancing.domain.artifacts as artifacts_module
import gda_balancing.domain.evidence as experiment_evidence_module
import gda_balancing.domain.runtime.execution as experiment_runtime_module
import gda_balancing.interfaces.cli.experiment_check as experiment_check_command_module
import gda_balancing.interfaces.cli.experiment_run as experiment_command_module
import gda_balancing.domain.authority.context as authority_module
import gda_balancing.domain.authority.admission as bootstrap_module
import gda_balancing.domain.model._lowering as model_lowering_module
import gda_balancing.domain.publication as publication_module
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.infrastructure.input_bytes import (
    BoundedInputObservation,
    read_bounded_input_with_sha256,
)
from gda_balancing.domain.runtime.scheduler import RuntimeScheduler
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    package_structured_value_index,
)
from gda_balancing.interfaces.cli.surface import (
    descriptor_identity,
    schema2_error_envelope_schema,
)
from schema2_scheduler_production_support import (
    evaluate_runtime_scheduler_vector,
    require_complete_scheduler_detector_bindings,
    scheduler_detector_inventory,
)
from schema2_operation_execution_production_support import (
    evaluate_operation_execution_vector,
)
from schema2_authority_support import mutable_authorities

_EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "schema2" / "rpg-combat-cast"
_PERIODIC_EXAMPLE_DIR = (
    Path(__file__).parents[1] / "examples" / "schema2" / "rpg-periodic-effect"
)
_STRUCTURED_EXAMPLE_DIR = (
    Path(__file__).parents[1] / "examples" / "schema2" / "structured-selection"
)
_ROGUELIKE_EXAMPLE_DIR = (
    Path(__file__).parents[1] / "examples" / "schema2" / "roguelike-reward-build"
)
_AUTHORITY_DIR = (
    Path(__file__).parents[1] / "src" / "gda_balancing" / "schema2" / "authorities"
)
_REFERENCE_EVENT_RUNTIME_BINDINGS = {
    "index",
    "event_id",
    "root_event_ref",
    "ordering_key",
    "snapshot_before_identity",
    "snapshot_after_identity",
    "formula_evaluations",
    "external_input_identity",
    "observation",
}


def test_runtime_canonical_equality_rechecks_typed_envelope_identity():
    authority_context = authority_module.packaged_authority_context()
    structured_authority = package_structured_value_index(
        cast(
            list[dict[str, Any]],
            authority_context.language_bundle["language"]["packages"],
        ),
        kernel=authority_context.kernel,
    )
    equality_contract = next(
        row
        for row in authority_context.kernel["meta_format"]["runtime_program"]["nodes"]
        if row["id"] == "equal"
    )
    variables = {
        "left": {
            "type": {
                "id": "Quantity",
                "package": "core.quantity",
                "version": "2.1.0",
            },
            "value": 1,
        },
        "right": {
            "type": {
                "id": "RewardRarity",
                "package": "game.generation",
                "version": "1.0.0",
            },
            "value": 1,
        },
    }

    with pytest.raises(StructuredValueFault) as fault:
        experiment_runtime_module._execute_value_instruction(
            {
                "left": "left",
                "node": "equal",
                "right": "right",
                "target": "result",
            },
            variables,
            {"maximum": (1 << 63) - 1, "minimum": -(1 << 63)},
            equality_contract,
            structured_authority=structured_authority,
            structured_resource_limit=1024,
        )
    assert fault.value == StructuredValueFault(
        "language.structured_value_type_mismatch", "/type"
    )


def test_runtime_integer_projection_without_an_envelope_profile_is_not_applicable():
    authority_context = authority_module.packaged_authority_context()
    structured_authority = replace(
        package_structured_value_index(
            cast(
                list[dict[str, Any]],
                authority_context.language_bundle["language"]["packages"],
            ),
            kernel=authority_context.kernel,
        ),
        typed_envelope_profile=None,
    )

    assert (
        experiment_runtime_module._project_runtime_integer(
            {"type": "not-an-admitted-envelope", "value": 1},
            structured_authority,
        )
        is None
    )


def test_record_lookup_does_not_capture_an_unrelated_same_name_local():
    authority_context = authority_module.packaged_authority_context()
    structured_authority = package_structured_value_index(
        cast(
            list[dict[str, Any]],
            authority_context.language_bundle["language"]["packages"],
        ),
        kernel=authority_context.kernel,
    )
    lookup_contract = next(
        row
        for row in authority_context.kernel["meta_format"]["runtime_program"]["nodes"]
        if row["id"] == "lookup"
    )
    variables: dict[str, Any] = {
        "candidate": {
            "type": {
                "id": "Candidate",
                "package": "standard.conformance.structured",
                "version": "2.0.0",
            },
            "value": {"key": {"key": "candidate_a"}, "kind": "primary"},
        },
        "kind": 0,
    }

    experiment_runtime_module._execute_value_instruction(
        {
            "key": "kind",
            "node": "lookup",
            "target": "selected_kind",
            "value": "candidate",
        },
        variables,
        {"maximum": (1 << 63) - 1, "minimum": -(1 << 63)},
        lookup_contract,
        structured_authority=structured_authority,
        structured_resource_limit=1024,
    )

    assert variables["selected_kind"] == {
        "type": {
            "id": "CandidateKind",
            "package": "standard.conformance.structured",
            "version": "2.0.0",
        },
        "value": "primary",
    }


def test_list_lookup_requires_the_statically_resolved_index_local():
    authority_context = authority_module.packaged_authority_context()
    structured_authority = package_structured_value_index(
        cast(
            list[dict[str, Any]],
            authority_context.language_bundle["language"]["packages"],
        ),
        kernel=authority_context.kernel,
    )
    lookup_contract = next(
        row
        for row in authority_context.kernel["meta_format"]["runtime_program"]["nodes"]
        if row["id"] == "lookup"
    )
    variables = {
        "candidates": {
            "type": {
                "element": {
                    "id": "Candidate",
                    "kind": "nominal",
                    "package": "standard.conformance.structured",
                    "version": "2.0.0",
                },
                "kind": "list",
                "maximum_length": 16,
            },
            "value": [],
        }
    }

    with pytest.raises(ValueError, match="List lookup index local is unavailable"):
        experiment_runtime_module._execute_value_instruction(
            {
                "key": "missing_index",
                "node": "lookup",
                "target": "selected_candidate",
                "value": "candidates",
            },
            variables,
            {"maximum": (1 << 63) - 1, "minimum": -(1 << 63)},
            lookup_contract,
            structured_authority=structured_authority,
            structured_resource_limit=1024,
        )


def test_experiment_conformance_uses_only_prepared_public_documents():
    for descriptor in (
        experiment_check_command_module.EXPERIMENT_CHECK,
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
    _kernel, language_bundle = mutable_authorities()
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
        "action_cost": tutorial_values["player_action_cost"],
        "accuracy": tutorial_values["player_accuracy"],
        "base_damage": tutorial_values["player_base_damage"],
    } == {
        "action_cost": 9,
        "accuracy": 1000,
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
    """Project the stable one-actor #540 fixture from the reciprocal tutorial."""
    source = json.loads(
        (_EXAMPLE_DIR / "model-source.json").read_text(encoding="utf-8")
    )
    symbol_names = {
        "player_mana": "actor_mana",
        "player_action_cost": "action_cost",
        "player_accuracy": "accuracy",
        "player_base_damage": "base_damage",
        "player_critical_threshold": "critical_threshold",
        "enemy_defense": "target_defense",
        "enemy_health": "target_health",
        "player_effective_accuracy": "effective_accuracy",
        "player_damage_dealt": "damage_dealt",
    }
    module = source["modules"][0]
    module["symbols"] = [
        symbol for symbol in module["symbols"] if symbol["symbol"] in symbol_names
    ]
    for symbol in module["symbols"]:
        symbol["symbol"] = symbol_names[symbol["symbol"]]

    source["formula_bindings"] = [
        binding
        for binding in source["formula_bindings"]
        if binding["site"]["kind"] == "operation-slot"
        or binding["site"].get("symbol") == "player_effective_accuracy"
    ]
    cast_entrypoint = deepcopy(source["entrypoints"][0])
    cast_entrypoint["id"] = "combat.cast"
    plan_entrypoint = deepcopy(cast_entrypoint)
    plan_entrypoint["id"] = "combat.plan-casts"
    plan_entrypoint["operation"] = {
        "package": "game.combat",
        "version": "2.1.0",
        "id": "game.combat.plan-casts-v1",
    }
    plan_entrypoint["result"] = {"kind": "discard"}
    source["entrypoints"] = [cast_entrypoint, plan_entrypoint]

    def rename_symbols(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("symbol") in symbol_names:
                value["symbol"] = symbol_names[value["symbol"]]
            for member in value.values():
                rename_symbols(member)
        elif isinstance(value, list):
            for member in value:
                rename_symbols(member)

    rename_symbols(source["formula_bindings"])
    rename_symbols(source["entrypoints"])
    return source


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


def test_scenario_contract_union_refuses_cross_entrypoint_conflicts():
    target = {
        "model": "example.contract-union",
        "module": "main",
        "name": "shared",
    }
    rows = [
        {
            "target": target,
            "target_identity": "sha256:" + ("1" * 64),
            "owner": "experiment",
            "initialization_source": "scenario-assignment",
            "cardinality": "required",
            "override": False,
        },
        {
            "target": target,
            "target_identity": "sha256:" + ("1" * 64),
            "owner": "experiment",
            "initialization_source": "scenario-assignment",
            "cardinality": "optional",
            "override": True,
        },
    ]

    with pytest.raises(ValueError, match="conflicting Scenario Input Contract"):
        experiment_admission_module._canonical_contract_union(
            rows,
            contract_name="Scenario Input Contract",
        )


def test_experiment_check_reports_cross_entrypoint_contract_conflicts(
    tmp_path, run_cli, monkeypatch
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    specification["scenarios"][0]["event_plan"].append(
        {
            "kind": "transition-invocation",
            "root_event_ref": "plan-casts",
            "logical_time": 1,
            "priority": 0,
            "entrypoint": "combat.plan-casts",
            "payload": [],
        }
    )
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    original_find = experiment_admission_module.find_published_artifact
    original_admit = experiment_admission_module.admit_resolved_model
    original_rir: dict[str, Any] | None = None

    def find_with_conflicting_entrypoint(content_identity_value, artifact_kind, ldb):
        nonlocal original_rir
        artifact = original_find(content_identity_value, artifact_kind, ldb)
        if artifact_kind != "rir-semantic-payload" or artifact is None:
            return artifact
        original_rir = artifact
        conflicting = deepcopy(artifact)
        entrypoints = {row["id"]: row for row in conflicting["entrypoints"]}
        cast_targets = entrypoints["combat.cast"]["scenario_input_contract"]["targets"]
        plan_targets = entrypoints["combat.plan-casts"]["scenario_input_contract"][
            "targets"
        ]
        cast_target = next(
            row for row in cast_targets if row["cardinality"] == "required"
        )
        plan_target = next(
            row for row in plan_targets if row["target"] == cast_target["target"]
        )
        plan_target["cardinality"] = "optional"
        return conflicting

    def admit_original_model(artifacts, *, authority_context=None):
        assert original_rir is not None
        original_artifacts = {
            **artifacts,
            "rir-semantic-payload": original_rir,
        }
        return original_admit(
            original_artifacts,
            authority_context=authority_context,
        )

    monkeypatch.setattr(
        experiment_admission_module,
        "find_published_artifact",
        find_with_conflicting_entrypoint,
    )
    monkeypatch.setattr(
        experiment_admission_module,
        "admit_resolved_model",
        admit_original_model,
    )

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.source_contract_mismatch"
    assert diagnostic["primary"]["pointer"] == "/scenarios/0/assignments"
    assert diagnostic["message"] == "conflicting Scenario Input Contract rows"


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
        elif not isinstance(value, int):
            rows.append({"name": name, "kind": "structured", "value": value})
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
    language_bundle: dict[str, Any] | None = None,
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
        reachable_formula_targets = {
            (
                operand["symbol"]["model"],
                operand["symbol"]["module"],
                operand["symbol"]["name"],
            )
            for binding in resolved_entrypoint["arguments"]
            if (operand := binding["operand"])["kind"] == "symbol"
        }
        while True:
            previous_target_count = len(reachable_formula_targets)
            for program in pending_programs:
                target = program["target"]
                target_coordinate = (
                    target["model"],
                    target["module"],
                    target["name"],
                )
                if target_coordinate not in reachable_formula_targets:
                    continue
                reachable_formula_targets.update(
                    (
                        operand["resolved_symbol"]["model"],
                        operand["resolved_symbol"]["module"],
                        operand["resolved_symbol"]["name"],
                    )
                    for row in program["inputs"]
                    if (operand := row["operand"])["kind"] != "literal"
                )
            if len(reachable_formula_targets) == previous_target_count:
                break
        pending_programs = [
            program
            for program in pending_programs
            if (
                program["target"]["model"],
                program["target"]["module"],
                program["target"]["name"],
            )
            in reachable_formula_targets
        ]
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
    declared_domains_by_cell = (
        {
            id(cells[coordinate]): declaration["domain"]
            for coordinate, declaration in declarations.items()
            if coordinate in state_cells
            and declaration["domain_kind"] == "closed-interval"
        }
        if resolved_entrypoint is not None
        else {}
    )
    before = {name: cell["value"] for name, cell in state_cells.items()}
    rng_states: dict[str, int] = {}
    rng_indices: dict[str, int] = {}
    draws: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    call_sites = {
        (row["parent_operation"]["id"], row["site"]): row
        for row in (resolved_call_sites or [])
    }
    language = (
        language_bundle.get("language") if isinstance(language_bundle, dict) else None
    )
    nominal_types = {
        (row["package"], row["version"], row["id"]): row
        for row in (
            language.get("nominal_types", []) if isinstance(language, dict) else []
        )
        if isinstance(row, dict)
        and all(
            isinstance(row.get(member), str) for member in ("package", "version", "id")
        )
    }
    constructors = {
        row["id"]: row
        for row in (
            language.get("constructors", []) if isinstance(language, dict) else []
        )
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    structured_operations = [
        row
        for row in (
            language.get("structured_operations", [])
            if isinstance(language, dict)
            else []
        )
        if isinstance(row, dict)
    ]

    def structural(type_expression: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        definition = type_expression
        constructor = None
        if isinstance(type_expression, dict) and set(type_expression) >= {
            "id",
            "package",
            "version",
        }:
            nominal = nominal_types[
                (
                    type_expression["package"],
                    type_expression["version"],
                    type_expression["id"],
                )
            ]
            definition = nominal["definition"]
            constructor = constructors[nominal["constructor"]]
        if not isinstance(definition, dict):
            raise AssertionError("structured type is not admitted")
        if constructor is None:
            matches = [
                candidate
                for candidate in constructors.values()
                if candidate.get("value_rule", {}).get("definition_kind")
                == definition.get("kind")
            ]
            assert len(matches) == 1
            constructor = matches[0]
        return definition, constructor

    def structured_law(type_expression: Any, operator: str) -> dict[str, Any]:
        _definition, constructor = structural(type_expression)
        matches = [
            row["law"]
            for row in structured_operations
            if row.get("owner_constructor") == constructor["id"]
            and row.get("law", {}).get("operator") == operator
        ]
        assert len(matches) == 1
        return matches[0]

    def structured_lookup(envelope: Any, key: Any) -> dict[str, Any]:
        assert isinstance(envelope, dict) and set(envelope) == {"type", "value"}
        definition, constructor = structural(envelope["type"])
        selected_law = structured_law(envelope["type"], "bounded-lookup")
        rule = constructor["value_rule"]
        if selected_law["selector"] == "static-field":
            field = next(
                row
                for row in definition[rule["fields_member"]]
                if row[rule["field_name_member"]] == key
            )
            result_type = field[rule["field_type_member"]]
            result_value = envelope["value"][key]
        else:
            assert selected_law["selector"] == "local-index"
            result_type = definition[rule["element_member"]]
            result_value = envelope["value"][key]
        if isinstance(result_type, dict) and result_type.get("kind") == "nominal":
            result_type = {
                member: result_type[member] for member in ("id", "package", "version")
            }
        return {"type": result_type, "value": result_value}

    def structured_is_empty(envelope: Any) -> bool:
        assert isinstance(envelope, dict) and set(envelope) == {"type", "value"}
        definition, constructor = structural(envelope["type"])
        selected_law = structured_law(envelope["type"], "collection-is-empty")
        assert constructor["value_rule"]["operator"] == "bounded-list"
        assert selected_law["result_contract"] == "kernel-boolean"
        assert definition["kind"] == "list"
        return not envelope["value"]

    def exact(value: int, target: dict[str, Any] | None = None) -> int:
        if not numeric["minimum"] <= value <= numeric["maximum"]:
            raise _ReferenceRuntimeRefusal("runtime.numeric_overflow")
        domain = (
            declared_domains_by_cell.get(id(target)) if target is not None else None
        )
        if domain is not None and not domain["minimum"] <= value <= domain["maximum"]:
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

        def project_integer(value: Any) -> int | None:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if (
                isinstance(value, dict)
                and isinstance(value.get("value"), int)
                and not isinstance(value["value"], bool)
            ):
                return value["value"]
            return None

        def integer(value: Any) -> int:
            projected = project_integer(value)
            assert projected is not None
            return projected

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
                        integer(cell(instruction["left"])["value"]),
                        integer(cell(instruction["right"])["value"]),
                    ):
                        outcome = instruction["outcome"]
                        break
                elif operator == "typed-require":
                    if (
                        cell(instruction["condition"])["value"]
                        != instruction["expected"]
                    ):
                        raise _ReferenceRuntimeRefusal(instruction["reason"])
                elif operator == "guarded-outcome-block":
                    if cell(instruction["condition"])["value"]:
                        unit_contract = runtime["fixed_value_contracts"]["kernel-unit"]
                        guarded = {
                            "body": instruction["body"],
                            "default_outcome": instruction["outcome"],
                            "effects": selected["effects"],
                            "id": selected["id"],
                            "inputs": [],
                            "outcomes": [
                                {**row, "state_policy": "commit"}
                                for row in selected["outcomes"]
                            ],
                            "refusals": selected["refusals"],
                            "resource_bounds": selected["resource_bounds"],
                            "result": {
                                **unit_contract,
                                "access": "read",
                                "discardable": True,
                                "id": "result",
                                "source": {"kind": "unit"},
                            },
                        }
                        execute(
                            guarded,
                            {**arguments, **locals_},
                            stack,
                            path,
                        )
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
                elif operator == "typed-literal":
                    write_local(instruction["target"], instruction["literal"])
                elif operator == "copy-value":
                    write_local(
                        instruction["target"],
                        cell(instruction["value"])["value"],
                    )
                elif operator == "bounded-lookup":
                    key = instruction["key"]
                    container = cell(instruction["value"])["value"]
                    selector = structured_law(container["type"], "bounded-lookup")[
                        "selector"
                    ]
                    if selector == "local-index":
                        key = locals_[key]["value"]
                    write_local(
                        instruction["target"],
                        structured_lookup(container, key),
                    )
                elif operator == "canonical-equal":
                    left = cell(instruction["left"])["value"]
                    right = cell(instruction["right"])["value"]
                    left_integer = project_integer(left)
                    right_integer = project_integer(right)
                    if left_integer is not None and right_integer is not None:
                        if isinstance(left, dict) and isinstance(right, dict):
                            assert left["type"] == right["type"]
                        equal = left_integer == right_integer
                    else:
                        assert isinstance(left, dict) and isinstance(right, dict)
                        assert left["type"] == right["type"]
                        equal = left["value"] == right["value"]
                    write_local(
                        instruction["target"],
                        equal,
                    )
                elif operator == "collection-is-empty":
                    write_local(
                        instruction["target"],
                        structured_is_empty(cell(instruction["value"])["value"]),
                    )
                elif operator in {
                    "integer-add",
                    "integer-subtract",
                    "integer-multiply",
                    "integer-maximum",
                }:
                    left = integer(cell(instruction["left"])["value"])
                    right = integer(cell(instruction["right"])["value"])
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
                            integer(cell(instruction["left"])["value"]),
                            integer(cell(instruction["right"])["value"]),
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
                        target["value"] - cell(instruction["value"])["value"],
                        target,
                    )
                elif operator == "state-write":
                    target = arguments[instruction["symbol"]]
                    value = cell(instruction["value"])["value"]
                    if (
                        isinstance(target["value"], int)
                        and not isinstance(target["value"], bool)
                        and isinstance(value, dict)
                        and set(value) == {"type", "value"}
                    ):
                        value = value["value"]
                    target["value"] = (
                        exact(value, target)
                        if isinstance(value, int) and not isinstance(value, bool)
                        else value
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
        "schedules": [],
        "cancellations": [],
    }
    if resolved_entrypoint is None:
        event["result"] = result
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


def _reference_evaluate_formula_document(
    formula: dict[str, Any], arguments: list[dict[str, Any]]
) -> int:
    values = {row["parameter"]: row["value"] for row in arguments}

    def operand_value(operand: dict[str, Any]) -> int:
        if operand["kind"] == "parameter":
            return values[operand["parameter"]]
        if operand["kind"] == "local":
            return values[operand["local"]]
        assert operand["kind"] == "literal"
        return operand["value"]

    for node in formula["body"]["nodes"]:
        operands = {
            argument["port"]: operand_value(argument["operand"])
            for argument in node["arguments"]
        }
        operation = node["operation"]["id"]
        if operation == "quantity.add":
            result = operands["left"] + operands["right"]
        elif operation == "quantity.subtract":
            result = operands["left"] - operands["right"]
        elif operation == "quantity.multiply":
            result = operands["left"] * operands["right"]
        elif operation == "quantity.maximum":
            result = max(operands["left"], operands["right"])
        else:
            assert operation == "quantity.floor-zero"
            result = max(operands["value"], 0)
        assert -(1 << 63) <= result <= (1 << 63) - 1
        values[node["id"]] = result

    return operand_value(formula["body"]["result"])


@dataclass(frozen=True)
class _ReferenceSchedulerMutation:
    accept_backward: bool = False
    order_by_event_id: bool = False
    omit_enqueue_sequence: bool = False
    read_initial_state: bool = False
    share_scenario_state: bool = False


_REFERENCE_SCHEDULER_MUTATIONS = {
    "backward-scheduling": _ReferenceSchedulerMutation(accept_backward=True),
    "host-assigned-ordering": _ReferenceSchedulerMutation(order_by_event_id=True),
    "omitted-key": _ReferenceSchedulerMutation(omit_enqueue_sequence=True),
    "pre-commit-visibility": _ReferenceSchedulerMutation(read_initial_state=True),
    "scenario-as-timestep": _ReferenceSchedulerMutation(share_scenario_state=True),
}


def _reference_evaluate_scheduler_vector(
    kernel: dict[str, Any],
    vector: dict[str, Any],
    *,
    mutation: str | None = None,
) -> dict[str, Any]:
    require_complete_scheduler_detector_bindings(
        kernel,
        _REFERENCE_SCHEDULER_MUTATIONS,
        consumer="reference",
    )
    if mutation is None:
        mutant = _ReferenceSchedulerMutation()
    else:
        try:
            mutant = _REFERENCE_SCHEDULER_MUTATIONS[mutation]
        except KeyError as error:
            raise ValueError(f"unsupported scheduler mutation: {mutation}") from error
    scheduler = kernel["meta_format"]["runtime_program"]["scheduler"]
    events = deepcopy(vector["input"]["events"])
    initial_states = vector["input"]["initial_states"]
    scenario_order = {
        row["scenario"]: index for index, row in enumerate(initial_states)
    }
    states = {row["scenario"]: row["value"] for row in initial_states}
    by_id = {event["id"]: event for event in events}

    def refused(signal: str) -> dict[str, Any]:
        return {
            "event_order": [],
            "observations": [],
            "outcome": "refused",
            "signal": signal,
            "terminal_reason": None,
            "terminal_states": deepcopy(initial_states),
        }

    for event in events:
        if not event["cancel_requested"]:
            continue
        status = event["status"]
        if status not in scheduler["cancel"]["admitted_target_states"]:
            return refused(scheduler["cancel"]["refusal_signals"][status])
    for event in events:
        parent_id = event["parent_id"]
        if parent_id is None:
            continue
        parent = by_id[parent_id]
        if event["phase"] != scheduler["schedule"]["child_phase"]:
            return refused(scheduler["schedule"]["refusal_signals"]["hidden_input"])
        if (
            not mutant.accept_backward
            and event["logical_time"] < parent["logical_time"]
        ):
            return refused(scheduler["schedule"]["refusal_signals"]["backward"])
        if (
            event["logical_time"] == parent["logical_time"]
            and event["priority"] > parent["priority"]
        ):
            return refused(
                scheduler["schedule"]["refusal_signals"]["illegal_same_time_priority"]
            )

    phase_order = next(
        row["rank"] for row in scheduler["ordering"] if row["member"] == "phase"
    )
    phase_rank = {phase: index for index, phase in enumerate(phase_order)}

    def ordering_key(event: dict[str, Any]) -> tuple[Any, ...]:
        if mutant.order_by_event_id:
            return (event["id"],)
        key: tuple[Any, ...] = (
            scenario_order[event["scenario"]],
            event["logical_time"],
            phase_rank[event["phase"]],
            -event["priority"],
        )
        if not mutant.omit_enqueue_sequence:
            key = (*key, event["enqueue_sequence"])
        return key

    admitted = sorted(
        (
            event
            for event in events
            if event["status"] not in {"canceled", "completed"}
            and not event["cancel_requested"]
        ),
        key=ordering_key,
    )
    observations = []
    shared_state = next(iter(states.values()))
    for event in admitted:
        scenario = event["scenario"]
        before = shared_state if mutant.share_scenario_state else states[scenario]
        if mutant.read_initial_state:
            before = next(
                row["value"] for row in initial_states if row["scenario"] == scenario
            )
        after = before + event["state_delta"]
        if mutant.share_scenario_state:
            shared_state = after
        else:
            states[scenario] = after
        observations.append(
            {
                "event_id": event["id"],
                "scenario": scenario,
                "state_after": after,
                "state_before": before,
            }
        )
    if mutant.share_scenario_state:
        states = {scenario: shared_state for scenario in states}
    return {
        "event_order": [event["id"] for event in admitted],
        "observations": observations,
        "outcome": "admitted",
        "signal": None,
        "terminal_reason": vector["input"]["terminal_condition"],
        "terminal_states": [
            {"scenario": row["scenario"], "value": states[row["scenario"]]}
            for row in initial_states
        ],
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
        "scenarios": [
            {
                "id": "one-cast",
                "event_plan": [
                    {
                        "kind": "transition-invocation",
                        "root_event_ref": "cast",
                        "logical_time": 0,
                        "priority": 0,
                        "entrypoint": "combat.cast",
                        "payload": [],
                    }
                ],
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
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
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


def _write_built_periodic_experiment(tmp_path, run_cli):
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(_PERIODIC_EXAMPLE_DIR / "model-source.json"),
            "--out",
            str(tmp_path / "resolved-periodic-model.json"),
            "--invocation-key",
            "7" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = json.loads(
        (_PERIODIC_EXAMPLE_DIR / "experiment.json").read_text(encoding="utf-8")
    )
    specification["kernel_identity"] = build_record["kernel_identity"]
    specification["language_bundle_identity"] = build_record["language_bundle_identity"]
    specification["model"] = {
        "source_identity": build_record["source_identity"],
        "build_receipt_identity": build_record["content_identity"],
        "resolved_model_identity": build_record["resolved_model_identity"],
        "package_lock_identity": build_record["package_lock_identity"],
        "rir_identity": build_record["rir_identity"],
    }
    specification_path = tmp_path / "periodic-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    return specification_path, build_receipt


def _write_built_structured_experiment(tmp_path, run_cli):
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(_STRUCTURED_EXAMPLE_DIR / "model-source.json"),
            "--out",
            str(tmp_path / "resolved-structured-model.json"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = json.loads(
        (_STRUCTURED_EXAMPLE_DIR / "experiment.json").read_text(encoding="utf-8")
    )
    specification["kernel_identity"] = build_record["kernel_identity"]
    specification["language_bundle_identity"] = build_record["language_bundle_identity"]
    specification["model"] = {
        "source_identity": build_record["source_identity"],
        "build_receipt_identity": build_record["content_identity"],
        "resolved_model_identity": build_record["resolved_model_identity"],
        "package_lock_identity": build_record["package_lock_identity"],
        "rir_identity": build_record["rir_identity"],
    }
    specification_path = tmp_path / "structured-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    return specification_path, specification


def _write_built_roguelike_experiment(tmp_path, run_cli):
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(_ROGUELIKE_EXAMPLE_DIR / "model-source.json"),
            "--out",
            str(tmp_path / "resolved-roguelike-model.json"),
            "--invocation-key",
            "4" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = json.loads(
        (_ROGUELIKE_EXAMPLE_DIR / "experiment.json").read_text(encoding="utf-8")
    )
    assert specification["kernel_identity"] == build_record["kernel_identity"]
    assert (
        specification["language_bundle_identity"]
        == build_record["language_bundle_identity"]
    )
    assert specification["model"] == {
        "source_identity": build_record["source_identity"],
        "build_receipt_identity": build_record["content_identity"],
        "resolved_model_identity": build_record["resolved_model_identity"],
        "package_lock_identity": build_record["package_lock_identity"],
        "rir_identity": build_record["rir_identity"],
    }
    specification_path = tmp_path / "roguelike-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    return specification_path, specification


def test_public_seeded_reward_selection_exposes_policy_and_disposition(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (check_exit, check_stderr) == (0, ""), (check_stdout, check_stderr)

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "roguelike-evaluation.json"),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    event = _member(receipt, "event-trace")["events"][0]
    metrics = _member(receipt, "metric-dataset")
    reproduction = _member(receipt, "reproduction-receipt")
    pool = next(row for row in event["facts"] if row["name"] == "reward_pool")["value"][
        "value"
    ]
    result = next(row for row in event["facts"] if row["name"] == "reward_result")

    assert event["outcome"] == {"id": "selected", "kind": "success"}
    assert reproduction["seed_algorithm"] == specification["seed"]["algorithm"]
    assert reproduction["seed_value"] == specification["seed"]["value"] == 20260812
    assert event["rng_draws"] == [
        {
            "stream": "reward",
            "index": 0,
            "candidate_hex": "cb822c763bee22e2",
            "accepted": True,
            "minimum": 1,
            "maximum": 100,
            "value": 3,
        }
    ]
    assert [row["candidate"]["key"]["key"] for row in pool["options"]] == [
        "steady_guard",
        "volatile_crown",
    ]
    assert result["value"]["value"] == pool["options"][1]["selection"]
    assert result["value"]["value"]["disposition"] == "build"
    assert result["value"]["value"]["policy_before"] == pool["policy_before"]
    assert result["value"]["value"]["policy_after"]["draw_count"] == 1
    assert metrics["samples"][0]["value"] == 80


def test_public_reward_build_loop_exposes_the_atomic_replacement(tmp_path, run_cli):
    specification_path, _specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "reward-build-evaluation.json"),
            "--invocation-key",
            "7" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    trace = _member(receipt, "event-trace")
    metrics = _member(receipt, "metric-dataset")
    transitions = [event for event in trace["events"] if event["operation"] is not None]
    assert [event["outcome"] for event in transitions] == [
        {"id": "selected", "kind": "success"},
        {"id": "replaced", "kind": "success"},
    ]
    build_event = transitions[1]
    result = next(row for row in build_event["facts"] if row["name"] == "build_result")[
        "value"
    ]["value"]
    assert result == {
        "kind": "replaced",
        "previous": {"key": "starter_blade"},
        "selected": {"key": "volatile_crown"},
        "disposition": "build",
        "power_before": 10,
        "power_after": 90,
    }
    state_before = {row["name"]: row["value"] for row in build_event["state_before"]}
    state_after = {row["name"]: row["value"] for row in build_event["state_after"]}
    assert state_before["build_state"]["value"] == {
        "slot": {"key": "starter_blade"},
        "power": 10,
    }
    assert state_after["build_state"]["value"] == {
        "slot": {"key": "volatile_crown"},
        "power": 90,
    }
    assert state_after["build_decision"]["value"] == result
    assert state_after["build_score"] == 90
    assert {row["metric"]: row["value"] for row in metrics["samples"]} == {
        "build_score": 90,
        "reward_score": 80,
    }


def test_public_reward_tuning_changes_selection_without_changing_the_rng_draw(
    tmp_path, run_cli
):
    specification_path, baseline = _write_built_roguelike_experiment(tmp_path, run_cli)

    def run(specification, path, output, invocation_key):
        path.write_text(json.dumps(specification), encoding="utf-8")
        check_exit, check_stdout, check_stderr = run_cli(
            ["experiment", "check", str(path)]
        )
        assert (check_exit, check_stderr) == (0, ""), (
            check_stdout,
            check_stderr,
        )
        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(path),
                "--out",
                str(output),
                "--invocation-key",
                invocation_key,
            ]
        )
        assert (exit_code, stderr) == (0, ""), (stdout, stderr)
        receipt = json.loads(stdout)
        trace = _member(receipt, "event-trace")
        metrics = _member(receipt, "metric-dataset")
        transitions = [
            event for event in trace["events"] if event["operation"] is not None
        ]
        reward_result = next(
            row for row in transitions[0]["facts"] if row["name"] == "reward_result"
        )
        build_result = next(
            row for row in transitions[1]["facts"] if row["name"] == "build_result"
        )
        return trace, metrics, reward_result, build_result

    baseline_trace, baseline_metrics, baseline_result, baseline_build = run(
        baseline,
        specification_path,
        tmp_path / "baseline-evaluation.json",
        "a" * 64,
    )
    tuned = deepcopy(baseline)
    tuned["id"] = "roguelike.reward-build-feedback.lower-rare-weight"
    rare_weight = next(
        row
        for row in tuned["scenarios"][0]["assignments"]
        if row["target"]["name"] == "rare_weight"
    )
    rare_weight["value"] = 2
    tuned_trace, tuned_metrics, tuned_result, tuned_build = run(
        tuned,
        tmp_path / "tuned-experiment.json",
        tmp_path / "tuned-evaluation.json",
        "b" * 64,
    )

    assert tuned["kernel_identity"] == baseline["kernel_identity"]
    assert tuned["language_bundle_identity"] == baseline["language_bundle_identity"]
    assert tuned["model"] == baseline["model"]
    assert tuned["runtime"] == baseline["runtime"]
    assert tuned_trace["experiment_identity"] != baseline_trace["experiment_identity"]
    assert tuned_trace["content_identity"] != baseline_trace["content_identity"]
    assert (
        tuned_trace["events"][0]["rng_draws"]
        == baseline_trace["events"][0]["rng_draws"]
    )
    baseline_value = baseline_result["value"]["value"]
    tuned_value = tuned_result["value"]["value"]
    assert (
        baseline_value["selected"],
        baseline_value["selected_index"],
        baseline_value["reward_score"],
    ) == ({"key": "volatile_crown"}, 1, 80)
    assert (
        tuned_value["selected"],
        tuned_value["selected_index"],
        tuned_value["reward_score"],
    ) == ({"key": "steady_guard"}, 0, 20)
    assert baseline_build["value"]["value"] == {
        "kind": "replaced",
        "previous": {"key": "starter_blade"},
        "selected": {"key": "volatile_crown"},
        "disposition": "build",
        "power_before": 10,
        "power_after": 90,
    }
    assert tuned_build["value"]["value"] == {
        "kind": "replaced",
        "previous": {"key": "starter_blade"},
        "selected": {"key": "steady_guard"},
        "disposition": "build",
        "power_before": 10,
        "power_after": 30,
    }
    assert {row["metric"]: row["value"] for row in baseline_metrics["samples"]} == {
        "build_score": 90,
        "reward_score": 80,
    }
    assert {row["metric"]: row["value"] for row in tuned_metrics["samples"]} == {
        "build_score": 30,
        "reward_score": 20,
    }


def test_public_reward_selection_refuses_an_unsatisfied_pool_without_fallback(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )
    pool = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "reward_pool"
    )["value"]["value"]
    pool["options"] = []
    pool["no_reward_on_empty"] = []
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (check_exit, check_stderr) == (0, ""), (check_stdout, check_stderr)

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "unsatisfied-reward-pool.json"),
            "--invocation-key",
            "c" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    assert [row["code"] for row in error["diagnostics"]] == [
        "game.generation.selection_exhausted"
    ]
    audit = _member(error["terminal_audit"], "runtime-terminal-audit")
    assert audit["refusing_event"]["reason"] == ("game.generation.selection_exhausted")
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]
    assert audit["budget_counters"]["event_steps"] == 6


def test_public_reward_selection_can_return_a_declared_no_reward_outcome(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )
    pool = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "reward_pool"
    )["value"]["value"]
    pool["options"] = []
    pool["no_reward_on_empty"] = [
        {
            "selected": {"key": "no_reward"},
            "rarity": "common",
            "disposition": "no-reward",
            "selected_index": 0,
            "policy_before": {"kind": "fixed-weight", "draw_count": 0},
            "policy_after": {"kind": "fixed-weight", "draw_count": 0},
            "reward_score": 0,
        }
    ]
    fallback = pool["no_reward_on_empty"][0]
    plans = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "build_plans"
    )["value"]["value"]["plans"]
    plans.clear()
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (check_exit, check_stderr) == (0, ""), (
        check_stdout,
        check_stderr,
    )

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "declared-no-reward.json"),
            "--invocation-key",
            "d" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    transitions = [
        event
        for event in _member(receipt, "event-trace")["events"]
        if event["operation"] is not None
    ]
    assert [event["outcome"] for event in transitions] == [
        {"id": "no-reward", "kind": "gameplay-alternative"},
        {"id": "no-reward", "kind": "gameplay-alternative"},
    ]
    assert transitions[0]["rng_draws"] == []
    assert transitions[1]["rng_draws"] == []
    assert transitions[1]["state_after"] == transitions[1]["state_before"]
    assert not any(row["name"] == "reward_result" for row in transitions[0]["facts"])
    selected = next(
        row for row in transitions[0]["state_after"] if row["name"] == "selected_reward"
    )
    assert selected["value"]["value"] == fallback
    assert {
        row["metric"]: row["value"]
        for row in _member(receipt, "metric-dataset")["samples"]
    } == {"build_score": 10, "reward_score": 0}
    assert not any(
        row["logical_name"] == "runtime-terminal-audit"
        for row in receipt["member_locators"]
    )


def test_public_reward_configuration_reports_an_unknown_disposition(tmp_path, run_cli):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )
    pool = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "reward_pool"
    )["value"]["value"]
    pool["options"][0]["candidate"]["disposition"] = "host-default"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == ("language.structured_value_unknown_enum")
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/scenarios/0/assignments/0/value/value/options/0/candidate/disposition"
    )


def test_public_reward_configuration_rejects_a_non_integer_quantity(tmp_path, run_cli):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )
    pool = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "reward_pool"
    )["value"]["value"]
    pool["options"][0]["candidate"]["reward_score"] = "twenty"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == (
        "language.structured_value_type_mismatch"
    )
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/scenarios/0/assignments/0/value/value/options/0/candidate/reward_score"
    )


def test_public_reward_selection_rejects_contradictory_authored_results(
    tmp_path, run_cli
):
    _specification_path, baseline = _write_built_roguelike_experiment(tmp_path, run_cli)
    contradictions = (
        "rarity",
        "disposition",
        "selected-key",
        "selected-index",
        "reward-score",
        "policy-before",
        "draw-count",
    )
    for index, contradiction in enumerate(contradictions, start=1):
        specification = deepcopy(baseline)
        pool = next(
            row
            for row in specification["scenarios"][0]["assignments"]
            if row["target"]["name"] == "reward_pool"
        )["value"]["value"]
        option = pool["options"][1]
        candidate = option["candidate"]
        selection = option["selection"]
        if contradiction == "rarity":
            candidate["rarity"] = "common"
        elif contradiction == "disposition":
            candidate["disposition"] = "no-reward"
        elif contradiction == "selected-key":
            selection["selected"] = {"key": "steady_guard"}
        elif contradiction == "selected-index":
            selection["selected_index"] = 0
        elif contradiction == "reward-score":
            candidate["reward_score"] = 79
        elif contradiction == "policy-before":
            selection["policy_before"]["draw_count"] = 1
        else:
            selection["policy_after"]["draw_count"] = 2
        specification_path = tmp_path / f"contradictory-reward-{contradiction}.json"
        specification_path.write_text(json.dumps(specification), encoding="utf-8")

        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(specification_path),
                "--out",
                str(tmp_path / f"contradictory-reward-{contradiction}-artifacts"),
                "--invocation-key",
                str(index) * 64,
            ]
        )

        assert (exit_code, stderr) == (2, ""), (contradiction, stdout, stderr)
        error = json.loads(stdout)["error"]
        assert [row["code"] for row in error["diagnostics"]] == [
            "game.generation.invalid_option"
        ], contradiction
        audit = _member(error["terminal_audit"], "runtime-terminal-audit")
        assert audit["refusing_event"]["reason"] == (
            "game.generation.invalid_option"
        ), contradiction
        assert audit["rollback"]["committed"] is False, contradiction
        assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"], (
            contradiction
        )
        assert not any(
            row["name"] == "reward_result" for row in audit["last_snapshot"]
        ), contradiction


def test_public_build_conflict_is_a_gameplay_outcome_with_atomic_rollback(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )
    plans = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "build_plans"
    )["value"]["value"]["plans"]
    plans[1]["constraint"] = "conflict"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "build-conflict.json"),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    transitions = [
        event
        for event in _member(receipt, "event-trace")["events"]
        if event["operation"] is not None
    ]
    conflict = transitions[1]
    assert conflict["outcome"] == {
        "id": "build-conflict",
        "kind": "gameplay-alternative",
    }
    assert conflict["state_after"] == conflict["state_before"]
    assert not any(row["name"] == "build_result" for row in conflict["facts"])
    assert not any(
        row["logical_name"] == "runtime-terminal-audit"
        for row in receipt["member_locators"]
    )


def test_public_build_configuration_reports_an_unknown_constraint(tmp_path, run_cli):
    specification_path, specification = _write_built_roguelike_experiment(
        tmp_path, run_cli
    )
    plans = next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "build_plans"
    )["value"]["value"]["plans"]
    plans[0]["constraint"] = "host-default"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == ("language.structured_value_unknown_enum")
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/scenarios/0/assignments/4/value/value/plans/0/constraint"
    )


def test_public_build_replacement_rejects_contradictory_authored_plans(
    tmp_path, run_cli
):
    _specification_path, baseline = _write_built_roguelike_experiment(tmp_path, run_cli)
    contradictions = (
        "next-slot",
        "decision-kind",
        "decision-previous",
        "decision-selected",
        "decision-disposition",
        "power-before",
        "power-after",
        "score",
    )
    for index, contradiction in enumerate(contradictions, start=8):
        specification = deepcopy(baseline)
        plan = next(
            row
            for row in specification["scenarios"][0]["assignments"]
            if row["target"]["name"] == "build_plans"
        )["value"]["value"]["plans"][1]
        if contradiction == "next-slot":
            plan["next_state"]["slot"] = {"key": "steady_guard"}
        elif contradiction == "decision-kind":
            plan["decision"]["kind"] = "no-reward"
        elif contradiction == "decision-previous":
            plan["decision"]["previous"] = {"key": "steady_guard"}
        elif contradiction == "decision-selected":
            plan["decision"]["selected"] = {"key": "steady_guard"}
        elif contradiction == "decision-disposition":
            plan["decision"]["disposition"] = "no-reward"
        elif contradiction == "power-before":
            plan["decision"]["power_before"] = 11
        elif contradiction == "power-after":
            plan["decision"]["power_after"] = 89
        else:
            plan["score"] = 89
        specification_path = tmp_path / f"contradictory-build-{contradiction}.json"
        specification_path.write_text(json.dumps(specification), encoding="utf-8")

        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(specification_path),
                "--out",
                str(tmp_path / f"contradictory-build-{contradiction}-artifacts"),
                "--invocation-key",
                f"{index:x}" * 64,
            ]
        )

        assert (exit_code, stderr) == (2, ""), (contradiction, stdout, stderr)
        error = json.loads(stdout)["error"]
        assert [row["code"] for row in error["diagnostics"]] == [
            "game.build.invalid_plan"
        ], contradiction
        audit = _member(error["terminal_audit"], "runtime-terminal-audit")
        assert audit["refusing_event"]["reason"] == ("game.build.invalid_plan"), (
            contradiction
        )
        assert audit["rollback"]["committed"] is False, contradiction
        assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"], (
            contradiction
        )
        assert not any(row["name"] == "build_result" for row in audit["last_snapshot"])


def test_public_formula_edit_requires_rebuild_and_exact_experiment_rebinding(
    tmp_path, run_cli
):
    _baseline_path, baseline = _write_built_roguelike_experiment(tmp_path, run_cli)
    edited_source = json.loads(
        (_ROGUELIKE_EXAMPLE_DIR / "model-source.json").read_text(encoding="utf-8")
    )
    edited_source["manifest"]["version"] = "1.1.0"
    formula = deepcopy(edited_source["modules"][0]["formulas"][0])
    formula["id"] = "alternate-rare-threshold"
    edited_source["modules"][0]["formulas"].append(formula)
    edited_source["formula_bindings"][0]["formula"]["id"] = formula["id"]
    edited_source_path = tmp_path / "edited-roguelike-model.json"
    edited_source_path.write_text(json.dumps(edited_source), encoding="utf-8")

    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(edited_source_path),
            "--out",
            str(tmp_path / "edited-roguelike-model"),
            "--invocation-key",
            "8" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
    edited_receipt = json.loads(build_stdout)
    edited_build = _member(edited_receipt, "build-receipt")
    edited_rir = _member(edited_receipt, "rir-semantic-payload")

    assert edited_build["kernel_identity"] == baseline["kernel_identity"]
    assert (
        edited_build["language_bundle_identity"] == baseline["language_bundle_identity"]
    )
    assert (
        edited_build["package_lock_identity"]
        == baseline["model"]["package_lock_identity"]
    )
    assert edited_build["rir_identity"] != baseline["model"]["rir_identity"]
    edited_formula = next(
        row for row in edited_rir["formulas"] if row["id"] == formula["id"]
    )
    edited_binding = next(
        row
        for row in edited_rir["formula_bindings"]
        if row["site"]["slot"] == "rare-threshold-policy"
    )
    assert edited_formula["expression"] == "rare_weight"
    assert edited_binding["formula"]["id"] == formula["id"]

    stale = deepcopy(baseline)
    stale["model"]["source_identity"] = edited_build["source_identity"]
    stale_path = tmp_path / "stale-formula-binding.json"
    stale_path.write_text(json.dumps(stale), encoding="utf-8")
    stale_exit, stale_stdout, stale_stderr = run_cli(
        ["experiment", "check", str(stale_path)]
    )
    assert (stale_exit, stale_stderr) == (2, ""), (stale_stdout, stale_stderr)
    stale_error = json.loads(stale_stdout)["error"]
    assert stale_error["diagnostics"][0]["code"] == (
        "language.resolved_authority_mismatch"
    )
    assert stale_error["diagnostics"][0]["primary"]["pointer"] == "/model"

    rebound = deepcopy(baseline)
    rebound["id"] = "roguelike.reward-build-feedback.identity-formula"
    rebound["model"] = {
        "source_identity": edited_build["source_identity"],
        "build_receipt_identity": edited_build["content_identity"],
        "resolved_model_identity": edited_build["resolved_model_identity"],
        "package_lock_identity": edited_build["package_lock_identity"],
        "rir_identity": edited_build["rir_identity"],
    }
    rebound_path = tmp_path / "rebound-formula.json"
    rebound_path.write_text(json.dumps(rebound), encoding="utf-8")
    run_exit, run_stdout, run_stderr = run_cli(
        [
            "experiment",
            "run",
            str(rebound_path),
            "--out",
            str(tmp_path / "rebound-formula-evaluation.json"),
            "--invocation-key",
            "9" * 64,
        ]
    )
    assert (run_exit, run_stderr) == (0, ""), (run_stdout, run_stderr)
    transitions = [
        event
        for event in _member(json.loads(run_stdout), "event-trace")["events"]
        if event["operation"] is not None
    ]
    assert transitions[0]["formula_evaluations"][0]["result"] == 5
    assert transitions[1]["outcome"] == {"id": "replaced", "kind": "success"}


def test_public_structured_selection_is_reproducible_and_rolls_back_failed_write(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_structured_experiment(
        tmp_path, run_cli
    )

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (check_exit, check_stderr) == (0, ""), (check_stdout, check_stderr)

    def run(
        candidate: str,
        *,
        reordered: bool,
        selected_rank: int | None = None,
        invocation: str,
    ):
        scenario = specification["scenarios"][0]
        assignments = {row["target"]["name"]: row for row in scenario["assignments"]}
        scenario["event_plan"][0]["entrypoint"] = (
            f"structured.select-{candidate.replace('_', '-')}"
        )
        state = assignments["selection_state"]["value"]["value"]
        if reordered:
            state["candidates"].reverse()
            state["results"].reverse()
        if selected_rank is not None:
            state["results"][0]["rank"] = selected_rank
        specification_path.write_text(json.dumps(specification), encoding="utf-8")
        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(specification_path),
                "--out",
                str(tmp_path / f"evaluation-{invocation}.json"),
                "--invocation-key",
                invocation * 64,
            ]
        )
        assert (exit_code, stderr) == (0, ""), (stdout, stderr)
        receipt = json.loads(stdout)
        return (
            receipt,
            _member(receipt, "event-trace"),
            _member(receipt, "snapshot-series"),
            _member(receipt, "metric-dataset"),
        )

    _success_receipt, success_trace, success_snapshots, success_metrics = run(
        "candidate_a", reordered=False, invocation="7"
    )
    success = success_trace["events"][0]
    assert success["outcome"] == {"id": "selected", "kind": "success"}
    assert success["rng_draws"] == [
        {
            "stream": "selection",
            "index": 0,
            "candidate_hex": "e9d99c027e25cf36",
            "accepted": True,
            "minimum": 0,
            "maximum": 1,
            "value": 0,
        }
    ]
    output = next(row for row in success["facts"] if row["name"] == "selection_result")
    assert output["kind"] == "structured"
    assert output["value"]["value"] == {
        "selected": {"key": "candidate_a"},
        "kind": "primary",
        "rank": 3,
    }
    before_result = next(
        row for row in success["state_before"] if row["name"] == "selected_result"
    )
    after_result = next(
        row for row in success["state_after"] if row["name"] == "selected_result"
    )
    assert before_result["value"]["value"] == {
        "selected": {"key": "candidate_b"},
        "kind": "secondary",
        "rank": 9,
    }
    assert after_result["value"] == output["value"]
    assert success_metrics["samples"][0]["value"] == 3
    assert success_snapshots["snapshots"][-1]["values"] == success["state_after"]

    specification["scenarios"][0]["event_plan"][0]["entrypoint"] = (
        "structured.select-candidate-b"
    )
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    failure_exit, failure_stdout, failure_stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "evaluation-8.json"),
            "--invocation-key",
            "8" * 64,
        ]
    )
    assert (failure_exit, failure_stderr) == (2, ""), (
        failure_stdout,
        failure_stderr,
    )
    failure = json.loads(failure_stdout)["error"]
    assert failure["diagnostics"][0]["code"] == (
        "standard.conformance.candidate_mismatch"
    )
    audit = _member(failure["terminal_audit"], "runtime-terminal-audit")
    assert audit["refusing_event"]["reason"] == (
        "standard.conformance.candidate_mismatch"
    )
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]
    assert audit["budget_counters"]["event_steps"] == 19

    _reordered_receipt, reordered_trace, _, reordered_metrics = run(
        "candidate_b", reordered=True, selected_rank=7, invocation="9"
    )
    reordered = reordered_trace["events"][0]
    assert reordered["outcome"] == {"id": "selected", "kind": "success"}
    assert reordered["rng_draws"][0]["index"] == success["rng_draws"][0]["index"]
    assert (
        reordered["rng_draws"][0]["candidate_hex"]
        == success["rng_draws"][0]["candidate_hex"]
    )
    reordered_output = next(
        row for row in reordered["facts"] if row["name"] == "selection_result"
    )
    assert reordered_output["value"]["value"]["rank"] == 7
    assert reordered_metrics["samples"][0]["value"] == 7


def test_public_structured_assignment_reports_the_exact_nominal_value_failure(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_structured_experiment(
        tmp_path, run_cli
    )
    specification["scenarios"][0]["assignments"][0]["value"]["value"]["candidates"][0][
        "kind"
    ] = "unknown"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.structured_value_unknown_enum"
    assert diagnostic["primary"]["pointer"] == (
        "/scenarios/0/assignments/0/value/value/candidates/0/kind"
    )


def test_public_structured_empty_selection_uses_the_guarded_outcome(tmp_path, run_cli):
    specification_path, specification = _write_built_structured_experiment(
        tmp_path, run_cli
    )
    initial_state = specification["scenarios"][0]["assignments"][0]["value"]["value"]
    initial_state["candidates"] = []
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(specification_path)]
    )
    assert (check_exit, check_stderr) == (0, ""), (
        check_stdout,
        check_stderr,
    )

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "empty-selection.json"),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    trace = _member(receipt, "event-trace")
    event = trace["events"][0]
    assert event["outcome"] == {
        "id": "candidate-mismatch",
        "kind": "gameplay-alternative",
    }
    assert event["rng_draws"] == []
    assert event["state_after"] == event["state_before"]
    assert not any(row["name"] == "selection_result" for row in event["facts"])
    snapshots = _member(receipt, "snapshot-series")
    assert (
        snapshots["snapshots"][1]["continuation"]["resource_ledger"]["event_steps"] == 5
    )
    assert _member(receipt, "metric-dataset")["samples"][0]["value"] == 9
    assert not any(
        row["logical_name"] == "runtime-terminal-audit"
        for row in receipt["member_locators"]
    )


def test_guard_body_refusal_terminal_audit_uses_expanded_instruction_order(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_structured_experiment(
        tmp_path, run_cli
    )
    initial_state = specification["scenarios"][0]["assignments"][0]["value"]["value"]
    initial_state["candidates"] = []
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "standard.conformance.structured.select-v1"
    )
    guard = next(row for row in operation["body"] if row["node"] == "guard-block")
    guard["body"][0]["expected"] = False
    checked = replace(checked, rir=rir)

    outcome = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    audit = values["runtime-terminal-audit"]
    assert audit["refusing_event"]["reason"] == (
        "standard.conformance.candidate_mismatch"
    )
    assert audit["refusing_event"]["instruction_index"] == 4
    assert audit["budget_counters"]["event_steps"] == 5
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)


def test_structured_terminal_audit_preserves_a_committed_event_prefix(
    tmp_path, run_cli
):
    specification_path, specification = _write_built_structured_experiment(
        tmp_path, run_cli
    )
    scenario = specification["scenarios"][0]
    scenario["event_plan"] = [
        {
            **deepcopy(scenario["event_plan"][0]),
            "root_event_ref": "accepted-selection",
            "entrypoint": "structured.select-candidate-a",
        },
        {
            **deepcopy(scenario["event_plan"][0]),
            "root_event_ref": "refused-selection",
            "logical_time": 1,
            "entrypoint": "structured.select-candidate-b",
        },
    ]
    scenario["terminal_condition"]["maximum"] = 2
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "structured-terminal-audit"),
            "--invocation-key",
            "b" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, ""), (stdout, stderr)
    audit = _member(
        json.loads(stdout)["error"]["terminal_audit"],
        "runtime-terminal-audit",
    )
    assert len(audit["committed_trace_prefix"]) == 1
    assert any(
        fact["kind"] == "structured"
        for fact in audit["committed_trace_prefix"][0]["facts"]
    )


def test_public_experiment_orders_same_time_root_events_and_commits_between_them(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    scenario["event_plan"] = [
        {
            "kind": "transition-invocation",
            "root_event_ref": "low-priority-cast",
            "logical_time": 0,
            "priority": 0,
            "entrypoint": "combat.cast",
            "payload": [],
        },
        {
            "kind": "transition-invocation",
            "root_event_ref": "high-priority-cast",
            "logical_time": 0,
            "priority": 10,
            "entrypoint": "combat.cast",
            "payload": [],
        },
    ]
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 2}
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "terminal_health",
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
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "same-time-root-events"),
            "--invocation-key",
            "5" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    events = _member(receipt, "event-trace")["events"]
    assert [
        (
            event["root_event_ref"],
            event["ordering_key"]["logical_time"],
            event["ordering_key"]["phase"],
            event["ordering_key"]["priority"],
            event["ordering_key"]["enqueue_sequence"],
        )
        for event in events
        if "root_event_ref" in event
    ] == [
        ("high-priority-cast", 0, "transition", 10, 1),
        ("low-priority-cast", 0, "transition", 0, 0),
    ]
    assert len({event["event_id"] for event in events}) == 3
    assert events[1]["state_before"] == events[0]["state_after"]
    assert len(_member(receipt, "snapshot-series")["snapshots"]) == 4


def test_event_count_terminates_only_after_same_time_transitions_drain(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    scenario["event_plan"] = [
        {
            "kind": "transition-invocation",
            "root_event_ref": root_event_ref,
            "logical_time": 0,
            "priority": priority,
            "entrypoint": "combat.cast",
            "payload": [],
        }
        for root_event_ref, priority in (
            ("low-priority-cast", 0),
            ("high-priority-cast", 10),
        )
    ]
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 1}
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "terminal_health",
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
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "same-time-terminal-boundary"),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    trace = _member(receipt, "event-trace")
    events = trace["events"]
    runtime_events = [event for event in events if event["observation"] is None]
    assert [event["root_event_ref"] for event in runtime_events] == [
        "high-priority-cast",
        "low-priority-cast",
    ]
    assert events[-1]["observation"]["metric"] == "terminal_health"
    assert trace["terminal_statuses"][0]["event_count"] == 2
    assert trace["terminal_statuses"][0]["condition"]["maximum"] == 1
    snapshots = _member(receipt, "snapshot-series")["snapshots"]
    assert snapshots[-2]["continuation"]["pending_event_count"] == 0


def _write_scheduled_experiment(tmp_path, run_cli) -> Path:
    source_value = _rpg_model_source()
    source_path = tmp_path / "scheduled-combat-model.json"
    source_path.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source_path),
            "--out",
            str(tmp_path / "scheduled-combat-model"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), (build_stdout, build_stderr)
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=12,
    )
    specification["scenarios"][0]["event_plan"] = [
        {
            "kind": "transition-invocation",
            "root_event_ref": "plan-casts",
            "logical_time": 0,
            "priority": 0,
            "entrypoint": "combat.plan-casts",
            "payload": [],
        }
    ]
    specification["scenarios"][0]["terminal_condition"] = {
        "kind": "event-count",
        "maximum": 2,
    }
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "terminal_health",
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
    requirements, _named_streams = (
        experiment_admission_module.derive_scenario_program_requirements(
            _member(build_receipt, "rir-semantic-payload"),
            entrypoint_id="combat.plan-casts",
            runtime_profile=specification["runtime"]["profile"],
            rng_algorithm=specification["seed"]["algorithm"],
        )
    )
    specification["runtime"]["required_evaluator"] = requirements
    specification_path = tmp_path / "scheduled-combat-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    return specification_path


def test_public_experiment_schedules_a_child_and_cancels_a_pending_child(
    tmp_path, run_cli, monkeypatch
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    evaluate_programs = experiment_runtime_module._evaluate_initialization_programs
    event_frames: list[str] = []

    def record_formula_frame(*args, **kwargs):
        result = evaluate_programs(*args, **kwargs)
        if (
            kwargs.get("phase") == "event"
            and kwargs["frame_identity"] not in event_frames
        ):
            event_frames.append(kwargs["frame_identity"])
        return result

    monkeypatch.setattr(
        experiment_runtime_module,
        "_evaluate_initialization_programs",
        record_formula_frame,
    )

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "scheduled-combat-run"),
            "--invocation-key",
            "7" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    trace = _member(receipt, "event-trace")
    events = trace["events"]
    assert [event["operation"] for event in events] == [
        "game.combat.plan-casts-v1",
        "game.combat.cast-v1",
        None,
    ]
    schedules = events[0]["schedules"]
    assert len(schedules) == 2
    assert schedules[0]["event_id"] == events[1]["event_id"]
    assert events[1]["parent_event_id"] == events[0]["event_id"]
    assert events[0]["cancellations"] == [
        {
            "call_site_identity": events[0]["cancellations"][0]["call_site_identity"],
            "event_id": schedules[1]["event_id"],
            "outcome": "canceled",
        }
    ]
    assert schedules[1]["event_id"] not in {event["event_id"] for event in events}
    root_map = [
        {
            "scenario": "one-cast",
            "root_event_ref": "plan-casts",
            "event_id": events[0]["event_id"],
        }
    ]
    assert trace["root_event_map"] == root_map
    snapshots = _member(receipt, "snapshot-series")["snapshots"]
    assert event_frames == [
        snapshots[0]["snapshot_identity"],
        snapshots[1]["snapshot_identity"],
    ]
    assert all(
        snapshot["snapshot_identity"].startswith("sha256:") for snapshot in snapshots
    )
    assert [
        (event["snapshot_before_identity"], event["snapshot_after_identity"])
        for event in events
    ] == [
        (snapshots[0]["snapshot_identity"], snapshots[1]["snapshot_identity"]),
        (snapshots[1]["snapshot_identity"], snapshots[2]["snapshot_identity"]),
        (snapshots[2]["snapshot_identity"], snapshots[3]["snapshot_identity"]),
    ]
    terminal_status = {
        "scenario": "one-cast",
        "condition": {"kind": "event-count", "maximum": 2},
        "reason": "event-count-reached",
        "event_count": 2,
        "terminal_event_id": events[-2]["event_id"],
        "terminal_snapshot_identity": snapshots[-2]["snapshot_identity"],
        "observation_event_ids": [events[-1]["event_id"]],
        "final_snapshot_identity": snapshots[-1]["snapshot_identity"],
        "logical_time": 1,
    }
    assert trace["terminal_statuses"] == [terminal_status]
    evaluation_run = _member(receipt, "evaluation-run")
    assert evaluation_run["root_event_map"] == root_map
    assert evaluation_run["terminal_statuses"] == [terminal_status]
    sample = _member(receipt, "metric-dataset")["samples"][0]
    assert sample["event_id"] == events[-1]["event_id"]
    assert sample["snapshot_identity"] == snapshots[-1]["snapshot_identity"]
    assert sample["logical_time"] == events[-1]["ordering_key"]["logical_time"]


def test_scheduled_events_resolve_state_from_the_latest_committed_snapshot(
    tmp_path, run_cli
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    next(
        row for row in scenario["assignments"] if row["target"]["name"] == "actor_mana"
    )["value"] = 60
    next(
        row for row in scenario["assignments"] if row["target"]["name"] == "action_cost"
    )["value"] = 30
    next(row for row in scenario["assignments"] if row["target"]["name"] == "accuracy")[
        "value"
    ] = 1000
    scenario["event_plan"].append(
        {
            "kind": "transition-invocation",
            "root_event_ref": "intervening-cast",
            "logical_time": 1,
            "priority": 10,
            "entrypoint": "combat.cast",
            "payload": [],
        }
    )
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 4}
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    plan = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.plan-casts-v1"
    )
    plan["body"] = [row for row in plan["body"] if row["node"] != "cancel"]
    checked_value = deepcopy(checked.value)
    requirements, _named_streams = (
        experiment_admission_module.derive_scenario_program_requirements(
            rir,
            entrypoint_id="combat.plan-casts",
            runtime_profile=checked_value["runtime"]["profile"],
            rng_algorithm=checked_value["seed"]["algorithm"],
        )
    )
    checked_value["runtime"]["required_evaluator"] = requirements

    artifacts = experiment_runtime_module.evaluate_experiment(
        replace(checked, value=checked_value, rir=rir)
    )

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    runtime_events = [
        event
        for event in artifacts.members["event-trace"].value["events"]
        if event["operation"] is not None
    ]
    assert [event["outcome"]["id"] for event in runtime_events] == [
        "planned",
        "cast-resolved",
        "cast-resolved",
        "insufficient-resource",
    ]
    assert runtime_events[-1]["state_before"] == runtime_events[-1]["state_after"]
    assert (
        next(
            row["value"]
            for row in runtime_events[-1]["state_after"]
            if row["name"] == "actor_mana"
        )
        == 0
    )


def test_event_payload_overlays_formula_dependencies_before_formula_evaluation(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    entrypoint = next(
        row for row in checked.rir["entrypoints"] if row["id"] == "combat.cast"
    )
    assert {
        row["target"]["name"]
        for row in entrypoint["event_local_payload_contract"]["targets"]
    } >= {"accuracy"}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    next(row for row in scenario["assignments"] if row["target"]["name"] == "accuracy")[
        "value"
    ] = 0
    scenario["event_plan"][0]["payload"] = [
        {
            "target": {
                "model": "example.rpg-combat-cast",
                "module": "combat",
                "name": "accuracy",
            },
            "value": 1000,
        }
    ]
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "payload-formula-run"),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), stdout
    event = _member(json.loads(stdout), "event-trace")["events"][0]
    assert event["outcome"]["id"] == "cast-resolved"
    assert (
        next(
            row["integer"]
            for row in event["facts"]
            if row["name"] == "effective_accuracy"
        )
        == 1000
    )


def test_snapshots_bind_the_complete_runtime_continuation(tmp_path, run_cli):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    snapshot_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "snapshot_identity"
    ]
    assert snapshot_contract["projection"] == [
        "experiment_identity",
        "scenario_id",
        "index",
        "logical_time",
        "event_id",
        "values",
        "continuation",
    ]
    assert snapshot_contract["runtime_configuration_projection"] == {
        "lifecycle_state": "continuation.lifecycle_state",
        "step_boundary": "continuation.step_boundary",
        "scenario_cursor": "continuation.scenario_cursor",
        "event_catalog": "continuation.event_catalog",
        "pending_event_count": "continuation.pending_event_count",
        "committed_trace": "continuation.committed_trace",
        "current_snapshot": "continuation.current_snapshot",
        "state": "values",
        "rng": "continuation.rng",
        "resource_ledger": "continuation.resource_ledger",
        "next_enqueue_sequence": "continuation.next_enqueue_sequence",
        "root_event_map_identity": "continuation.root_event_map_identity",
        "resolved_runtime_profile_identity": (
            "continuation.resolved_runtime_profile_identity"
        ),
    }
    snapshots = artifacts.members["snapshot-series"].value["snapshots"]
    events = artifacts.members["event-trace"].value["events"]
    runtime_members = {
        "lifecycle_state",
        "step_boundary",
        "scenario_cursor",
        "event_catalog",
        "pending_event_count",
        "committed_trace",
        "current_snapshot",
        "rng",
        "resource_ledger",
        "next_enqueue_sequence",
        "root_event_map_identity",
        "resolved_runtime_profile_identity",
    }
    snapshot_wire_schema = next(
        row["schema"]
        for row in checked.language_bundle["language"]["artifact_wire_schemas"]
        if row["artifact_kind"] == "snapshot-series"
    )
    continuation_schema = snapshot_wire_schema["properties"]["snapshots"]["items"][
        "properties"
    ]["continuation"]
    assert set(continuation_schema["properties"]) == runtime_members
    assert set(continuation_schema["required"]) == runtime_members
    assert all(
        set(snapshot["continuation"]) == runtime_members for snapshot in snapshots
    )
    snapshot_series = artifacts.members["snapshot-series"].value
    assert (
        snapshot_series["event_trace_identity"]
        == artifacts.members["event-trace"].content_identity
    )
    catalog_ids = [row["event_id"] for row in snapshot_series["event_catalog"]]
    event_spec_domain = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["event_spec"]["domain"]
    assert all(
        row["event_id"] == row["event_spec"]["event_id"]
        and row["kind"] == row["event_spec"]["kind"]
        and row["ordering_key"] == row["event_spec"]["ordering_key"]
        and row["event_spec_identity"]
        == content_identity(event_spec_domain, row["event_spec"])
        for row in snapshot_series["event_catalog"]
    )
    assert all(
        experiment_evidence_module._event_catalog_record_is_valid(checked, row)
        for row in snapshot_series["event_catalog"]
    )
    assert experiment_evidence_module._event_catalog_records_are_authoritative(
        checked,
        snapshot_series["event_catalog"],
        events,
    )
    coordinated_root_drift = deepcopy(snapshot_series["event_catalog"])
    coordinated_root_drift[0]["event_spec"]["entrypoint"] = "combat.cast"
    coordinated_root_drift[0]["event_spec_identity"] = content_identity(
        event_spec_domain,
        coordinated_root_drift[0]["event_spec"],
    )
    assert not experiment_evidence_module._event_catalog_records_are_authoritative(
        checked,
        coordinated_root_drift,
        events,
    )
    coordinated_schedule_drift = deepcopy(snapshot_series["event_catalog"])
    scheduled_record = next(
        row
        for row in coordinated_schedule_drift
        if row["kind"] == "scheduled-transition"
    )
    scheduled_record["event_spec"]["arguments"][0]["value"] += 1
    scheduled_record["event_spec_identity"] = content_identity(
        event_spec_domain,
        scheduled_record["event_spec"],
    )
    assert not experiment_evidence_module._event_catalog_records_are_authoritative(
        checked,
        coordinated_schedule_drift,
        events,
    )
    drifted_catalog_record = deepcopy(snapshot_series["event_catalog"][0])
    drifted_catalog_record["event_spec"]["zero_time_depth"] += 1
    assert not experiment_evidence_module._event_catalog_record_is_valid(
        checked,
        drifted_catalog_record,
    )
    event_spec_members = {
        row["kind"]: set(row["event_spec"]) for row in snapshot_series["event_catalog"]
    }
    assert event_spec_members["transition-invocation"] == {
        "event_id",
        "ordering_key",
        "zero_time_depth",
        "kind",
        "root_event_ref",
        "entrypoint",
        "payload",
    }
    assert event_spec_members["scheduled-transition"] == {
        "event_id",
        "ordering_key",
        "zero_time_depth",
        "kind",
        "parent_event_id",
        "call_site_identity",
        "schedule_sequence",
        "operation",
        "arguments",
        "state_references",
    }
    assert event_spec_members["observation"] == {
        "event_id",
        "ordering_key",
        "kind",
        "metric_definition_identity",
    }
    assert len(catalog_ids) == len(set(catalog_ids))
    assert set(catalog_ids) == {
        events[0]["event_id"],
        events[1]["event_id"],
        events[0]["schedules"][1]["event_id"],
        events[2]["event_id"],
    }
    assert snapshots[0]["continuation"]["event_catalog"]["count"] == 1
    assert snapshots[0]["continuation"]["pending_event_count"] == 1
    assert snapshots[0]["continuation"]["committed_trace"]["count"] == 0
    assert snapshots[1]["continuation"]["event_catalog"]["count"] == 3
    assert snapshots[1]["continuation"]["pending_event_count"] == 1
    assert snapshots[1]["continuation"]["committed_trace"]["count"] == 1
    assert snapshots[2]["continuation"]["committed_trace"]["count"] == 2
    assert snapshots[-1]["continuation"]["committed_trace"]["count"] == 3
    assert all(
        snapshot["continuation"]["resolved_runtime_profile_identity"]
        == artifacts.members["resolved-runtime-profile"].content_identity
        for snapshot in snapshots
    )
    assert [snapshot["continuation"]["lifecycle_state"] for snapshot in snapshots] == [
        "step",
        "step",
        "step",
        "terminated",
    ]
    assert [snapshot["continuation"]["step_boundary"] for snapshot in snapshots] == [
        "initial",
        "logical-boundary",
        "terminal",
        "terminal",
    ]
    altered = deepcopy(snapshots[1]["continuation"])
    altered["committed_trace"]["prefix_identity"] = "sha256:" + ("0" * 64)
    assert (
        experiment_runtime_module._projected_runtime_identity(
            snapshot_contract,
            {
                "experiment_identity": checked.content_identity,
                "scenario_id": snapshots[1]["scenario"],
                "index": snapshots[1]["index"],
                "logical_time": snapshots[1]["logical_time"],
                "event_id": snapshots[1]["event_id"],
                "values": snapshots[1]["values"],
                "continuation": altered,
            },
        )
        != snapshots[1]["snapshot_identity"]
    )


def test_kernel_closes_runtime_configuration_transition_and_public_step():
    kernel, _language_bundle = mutable_authorities()
    runtime_program = kernel["meta_format"]["runtime_program"]

    assert runtime_program["runtime_configuration"] == {
        "lifecycle_roles": {
            "active": "event",
            "ready": "step",
            "terminal": "terminated",
        },
        "lifecycle_states": [
            "instantiated",
            "initializing",
            "step",
            "event",
            "terminated",
        ],
        "members": [
            "lifecycle_state",
            "step_boundary",
            "scenario_cursor",
            "event_catalog",
            "pending_event_count",
            "committed_trace",
            "current_snapshot",
            "state",
            "rng",
            "resource_ledger",
            "next_enqueue_sequence",
            "root_event_map_identity",
            "resolved_runtime_profile_identity",
        ],
        "mutation": "internal-transition-only",
    }
    assert runtime_program["scheduler"]["runtime_journal"] == {
        "event_spec": {
            "domain": "runtime-event-spec-v2",
            "projection": "complete-admitted-event",
        },
        "event_catalog": {
            "domain": "runtime-event-catalog-v2",
            "projection": "append-only-admitted-event-chain",
        },
        "committed_trace": {
            "domain": "runtime-committed-trace-v2",
            "projection": "append-only-committed-event-chain-without-snapshot-after",
        },
        "root_event_map": {
            "domain": "runtime-root-event-map-v2",
            "projection": "complete-root-event-map",
        },
    }
    assert runtime_program["transition"] == {
        "input": "runtime-configuration",
        "dispatch_count": 1,
        "event_selection": "scheduler-order-head",
        "transaction": "event-atomicity",
        "result": ["runtime-configuration", "runtime-refusal"],
    }
    assert runtime_program["step"] == {
        "input": "runtime-configuration",
        "advance": "repeat-transition",
        "boundaries": [
            "initial",
            "observation-boundary",
            "logical-boundary",
            "terminal",
        ],
        "boundary_roles": {
            "initial": "initial",
            "logical": "logical-boundary",
            "observation": "observation-boundary",
            "terminal": "terminal",
        },
        "stop": [
            "observation-boundary",
            "logical-boundary",
            "terminal",
        ],
        "result": "committed-boundary",
    }


def test_runtime_profile_bounds_are_ldb_owned_under_the_kernel_shape():
    kernel, language_bundle = mutable_authorities()
    profile_contract = kernel["meta_format"]["runtime_profile_definition"]
    assert profile_contract["active_runtime"]["resource_bounds"] == {
        "members": [
            "max_event_steps",
            "max_logical_time",
            "max_node_steps",
            "max_queue_events",
            "max_total_events",
            "max_zero_time_depth",
        ],
        "value_contract": "positive-integer",
    }
    profile = next(
        row
        for row in language_bundle["language"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    profile["resource_bounds"]["max_event_steps"] += 1

    assert bootstrap_module._runtime_authority_is_closed(kernel, language_bundle)

    del profile["resource_bounds"]["max_queue_events"]
    assert not bootstrap_module._runtime_authority_is_closed(kernel, language_bundle)


def test_artifact_set_validation_rejects_individually_valid_cross_bind_drift(
    tmp_path, run_cli
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    evaluation = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(evaluation, experiment_runtime_module.EvaluationArtifacts)
    values = {
        name: deepcopy(member.value) for name, member in evaluation.members.items()
    }
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    snapshot_payload = {
        key: value
        for key, value in values["snapshot-series"].items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    snapshot_payload["event_trace_identity"] = "sha256:" + ("0" * 64)
    drifted_snapshots = experiment_runtime_module._artifact(
        checked, "snapshot-series", snapshot_payload
    )
    values["snapshot-series"] = drifted_snapshots.value
    primary_payload = {
        key: value
        for key, value in values["evaluation-run"].items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    primary_payload["snapshot_series_identity"] = drifted_snapshots.content_identity
    values["evaluation-run"] = experiment_runtime_module._artifact(
        checked, "evaluation-run", primary_payload
    ).value

    assert all(
        experiment_evidence_module.validate_experiment_member(checked, name, value)
        for name, value in values.items()
    )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked, values
    )


def test_terminal_audit_validation_rejects_individually_valid_cross_field_drift(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_total_events"] = 2
    checked = replace(checked, rir=rir)
    outcome = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    def drift_refusing_index(audit):
        audit["refusing_event"]["index"] += 1

    def drift_snapshot_binding(audit):
        audit["refusing_event"]["snapshot_before_identity"] = "sha256:" + "0" * 64

    def drift_rollback_state(audit):
        audit["rollback"]["state_after"][0]["value"] += 1

    def drift_reason(audit):
        audit["refusing_event"]["reason"] = "runtime.queue_limit_exceeded"

    def drift_trace_index(audit):
        audit["committed_trace_prefix"][0]["index"] += 1

    for mutate in (
        drift_refusing_index,
        drift_snapshot_binding,
        drift_rollback_state,
        drift_reason,
        drift_trace_index,
    ):
        drifted_values = deepcopy(values)
        audit = drifted_values["runtime-terminal-audit"]
        payload = {
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
        mutate(payload)
        drifted = experiment_runtime_module._artifact(
            checked, "runtime-terminal-audit", payload
        )
        drifted_values["runtime-terminal-audit"] = drifted.value

        assert experiment_evidence_module.validate_experiment_member(
            checked,
            "runtime-terminal-audit",
            drifted.value,
        )
        assert not experiment_evidence_module.validate_experiment_artifact_set(
            checked,
            drifted_values,
        )


def test_terminal_audit_validation_rejects_coordinated_empty_prefix_drift(
    tmp_path, run_cli
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    plan_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.plan-casts-v1"
    )
    next(
        instruction
        for instruction in plan_operation["body"]
        if instruction["node"] == "schedule"
    )["logical_time"] = -1
    checked = replace(checked, rir=rir)
    outcome = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    assert outcome.committed_trace_prefix == ()
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    audit = values["runtime-terminal-audit"]
    assert audit["event_catalog_prefix"]
    assert (
        audit["last_snapshot_record"]["snapshot_identity"]
        == audit["last_snapshot_identity"]
    )
    assert (
        audit["refusing_event"]["event_spec"]["event_id"]
        == audit["refusing_event"]["event_id"]
    )
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    def reidentify(drifted_audit):
        payload = {
            key: value
            for key, value in drifted_audit.items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
        return experiment_runtime_module._artifact(
            checked,
            "runtime-terminal-audit",
            payload,
        ).value

    coordinated_snapshot = deepcopy(audit)
    replacement_snapshot_identity = "sha256:" + "0" * 64
    coordinated_snapshot["last_snapshot_identity"] = replacement_snapshot_identity
    coordinated_snapshot["last_snapshot_record"]["snapshot_identity"] = (
        replacement_snapshot_identity
    )
    coordinated_snapshot["refusing_event"]["snapshot_before_identity"] = (
        replacement_snapshot_identity
    )
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = reidentify(coordinated_snapshot)
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )

    coordinated_event = deepcopy(audit)
    replacement_event_id = "sha256:" + "1" * 64
    coordinated_event["refusing_event"]["event_id"] = replacement_event_id
    coordinated_event["refusing_event"]["event_spec"]["event_id"] = replacement_event_id
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = reidentify(coordinated_event)
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )

    coordinated_budget = deepcopy(audit)
    coordinated_budget["budget_counters"]["total_events"] += 1
    last_snapshot = coordinated_budget["last_snapshot_record"]
    last_snapshot["continuation"]["resource_ledger"]["total_events"] += 1
    snapshot_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "snapshot_identity"
    ]
    replacement_snapshot_identity = (
        experiment_runtime_module._projected_runtime_identity(
            snapshot_contract,
            {
                "experiment_identity": checked.content_identity,
                "scenario_id": last_snapshot["scenario"],
                "index": last_snapshot["index"],
                "logical_time": last_snapshot["logical_time"],
                "event_id": last_snapshot["event_id"],
                "values": last_snapshot["values"],
                "continuation": last_snapshot["continuation"],
            },
        )
    )
    last_snapshot["snapshot_identity"] = replacement_snapshot_identity
    coordinated_budget["last_snapshot_identity"] = replacement_snapshot_identity
    coordinated_budget["refusing_event"]["snapshot_before_identity"] = (
        replacement_snapshot_identity
    )
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = reidentify(coordinated_budget)
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )


def test_terminal_audit_validation_rejects_coordinated_observation_ordering_drift(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_total_events"] = 2
    checked = replace(checked, rir=rir)
    outcome = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    audit = values["runtime-terminal-audit"]
    assert audit["refusing_event"]["event_spec"]["kind"] == "observation"
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    drifted_audit = deepcopy(audit)
    refusing = drifted_audit["refusing_event"]
    ordering_key = refusing["event_spec"]["ordering_key"]
    ordering_key["enqueue_sequence"] += 1
    refusing["ordering_key"] = deepcopy(ordering_key)
    metric_identity = refusing["event_spec"]["metric_definition_identity"]
    replacement_event_id = experiment_runtime_module._observation_event_id(
        checked,
        drifted_audit["scenario"],
        metric_identity,
        logical_time=ordering_key["logical_time"],
        enqueue_sequence=ordering_key["enqueue_sequence"],
    )
    refusing["event_id"] = replacement_event_id
    refusing["event_spec"]["event_id"] = replacement_event_id
    payload = {
        key: value
        for key, value in drifted_audit.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = experiment_runtime_module._artifact(
        checked,
        "runtime-terminal-audit",
        payload,
    ).value

    assert experiment_evidence_module.validate_experiment_member(
        checked,
        "runtime-terminal-audit",
        drifted_values["runtime-terminal-audit"],
    )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )


def test_terminal_audit_validation_rejects_coordinated_active_step_drift(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_event_steps"] = 0
    checked = replace(checked, rir=rir)
    outcome = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    audit = values["runtime-terminal-audit"]
    assert audit["refusing_event"]["reason"] == "runtime.step_limit_exceeded"
    assert audit["budget_counters"]["event_steps"] > 0
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    drifted_audit = deepcopy(audit)
    drifted_audit["budget_counters"]["event_steps"] = 0
    drifted_audit["budget_counters"]["node_steps"] = drifted_audit[
        "last_snapshot_record"
    ]["continuation"]["resource_ledger"]["node_steps"]
    payload = {
        key: value
        for key, value in drifted_audit.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = experiment_runtime_module._artifact(
        checked,
        "runtime-terminal-audit",
        payload,
    ).value

    assert experiment_evidence_module.validate_experiment_member(
        checked,
        "runtime-terminal-audit",
        drifted_values["runtime-terminal-audit"],
    )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )


def test_terminal_audit_validation_rejects_coordinated_nonzero_step_decrement(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    cast_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.cast-v1"
    )
    cast_operation["resource_bounds"]["max_steps"] = 2
    checked = replace(checked, rir=rir)
    outcome = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    audit = values["runtime-terminal-audit"]
    assert audit["refusing_event"]["reason"] == "runtime.step_limit_exceeded"
    assert audit["budget_counters"]["event_steps"] > 1
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    drifted_audit = deepcopy(audit)
    drifted_audit["budget_counters"]["event_steps"] -= 1
    drifted_audit["budget_counters"]["node_steps"] -= 1
    payload = {
        key: value
        for key, value in drifted_audit.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = experiment_runtime_module._artifact(
        checked,
        "runtime-terminal-audit",
        payload,
    ).value

    assert experiment_evidence_module.validate_experiment_member(
        checked,
        "runtime-terminal-audit",
        drifted_values["runtime-terminal-audit"],
    )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )

    coordinated_proof = deepcopy(audit)
    assert coordinated_proof["budget_counters"]["event_steps"] == 8
    assert coordinated_proof["budget_counters"]["node_steps"] == 12
    assert coordinated_proof["refusing_event"]["instruction_index"] == 2
    assert len(coordinated_proof["refusing_event"]["attempted_calls"]) == 2
    coordinated_proof["budget_counters"]["event_steps"] = 4
    coordinated_proof["budget_counters"]["node_steps"] = 8
    coordinated_proof["refusing_event"]["instruction_index"] = 1
    coordinated_proof["refusing_event"]["attempted_calls"] = coordinated_proof[
        "refusing_event"
    ]["attempted_calls"][:1]
    payload = {
        key: value
        for key, value in coordinated_proof.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    drifted_values = deepcopy(values)
    drifted_values["runtime-terminal-audit"] = experiment_runtime_module._artifact(
        checked,
        "runtime-terminal-audit",
        payload,
    ).value

    assert experiment_evidence_module.validate_experiment_member(
        checked,
        "runtime-terminal-audit",
        drifted_values["runtime-terminal-audit"],
    )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked,
        drifted_values,
    )


def test_event_catalog_replay_rejects_coordinated_parent_fact_drift(tmp_path, run_cli):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    artifacts = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    catalog = deepcopy(artifacts.members["snapshot-series"].value["event_catalog"])
    events = deepcopy(artifacts.members["event-trace"].value["events"])
    parent_event = next(
        event for event in events if event["operation"] == "game.combat.plan-casts-v1"
    )
    action_cost = next(
        fact for fact in parent_event["facts"] if fact["name"] == "action_cost"
    )
    action_cost["integer"] += 1
    event_spec_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["event_spec"]
    for schedule in parent_event["schedules"]:
        next(row for row in schedule["arguments"] if row["name"] == "action_cost")[
            "value"
        ] += 1
        scheduled_record = next(
            record for record in catalog if record["event_id"] == schedule["event_id"]
        )
        next(
            row
            for row in scheduled_record["event_spec"]["arguments"]
            if row["name"] == "action_cost"
        )["value"] += 1
        scheduled_record["event_spec_identity"] = content_identity(
            event_spec_contract["domain"],
            scheduled_record["event_spec"],
        )

    assert not experiment_evidence_module._event_catalog_records_are_authoritative(
        checked,
        catalog,
        events,
    )


@pytest.mark.parametrize("schedule_shape", ["local", "nested"])
def test_artifact_revalidation_accepts_nested_and_local_schedule_provenance(
    tmp_path, run_cli, schedule_shape
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    schedule = deepcopy(
        next(
            instruction
            for instruction in operations["game.combat.plan-casts-v1"]["body"]
            if instruction["node"] == "schedule"
        )
    )
    schedule["site"] = f"review-{schedule_shape}-schedule"
    schedule["operation"] = {
        "package": "game.resource",
        "version": "1.0.1",
        "id": "game.resource.spend-v1",
    }
    schedule["result"] = {"kind": "local", "name": "review_scheduled_event"}
    damage_operation = operations["game.combat.damage-v1"]
    if schedule_shape == "local":
        constant_index = next(
            index
            for index, instruction in enumerate(damage_operation["body"])
            if instruction.get("target") == "critical_multiplier"
        )
        schedule["arguments"] = [
            {
                "port": "resource",
                "operand": {"kind": "literal", "literal": 10},
            },
            {
                "port": "cost",
                "operand": {"kind": "local", "local": "critical_multiplier"},
            },
        ]
        damage_operation["body"].insert(constant_index + 1, schedule)
    else:
        schedule["arguments"] = [
            {
                "port": "resource",
                "operand": {"kind": "literal", "literal": 1},
            },
            {
                "port": "cost",
                "operand": {"kind": "literal", "literal": 1},
            },
        ]
        damage_operation["body"].insert(0, schedule)
    damage_operation["resource_bounds"]["max_steps"] = 10_000
    checked = replace(checked, rir=rir)

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    values = {
        name: deepcopy(member.value) for name, member in artifacts.members.items()
    }
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)
    trace_events = values["event-trace"]["events"]
    catalog = values["snapshot-series"]["event_catalog"]
    scheduled_record = next(
        record for record in catalog if record["kind"] == "scheduled-transition"
    )
    parent_event = next(
        event
        for event in trace_events
        if any(
            schedule["event_id"] == scheduled_record["event_id"]
            for schedule in event["schedules"]
        )
    )
    schedule_trace = next(
        schedule
        for schedule in parent_event["schedules"]
        if schedule["event_id"] == scheduled_record["event_id"]
    )
    schedule_trace["arguments"][0]["value"] += 1
    scheduled_record["event_spec"]["arguments"][0]["value"] += 1
    event_spec_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["event_spec"]
    scheduled_record["event_spec_identity"] = content_identity(
        event_spec_contract["domain"],
        scheduled_record["event_spec"],
    )

    assert not experiment_evidence_module._event_catalog_records_are_authoritative(
        checked,
        catalog,
        trace_events,
    )


def test_event_catalog_replay_rejects_rng_derived_schedule_local_drift(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    schedule = deepcopy(
        next(
            instruction
            for instruction in operations["game.combat.plan-casts-v1"]["body"]
            if instruction["node"] == "schedule"
        )
    )
    schedule["site"] = "review-rng-derived-schedule"
    schedule["operation"] = {
        "package": "game.resource",
        "version": "1.0.1",
        "id": "game.resource.spend-v1",
    }
    schedule["arguments"] = [
        {
            "port": "resource",
            "operand": {"kind": "literal", "literal": 100},
        },
        {
            "port": "cost",
            "operand": {"kind": "local", "local": "hit_roll"},
        },
    ]
    schedule["result"] = {"kind": "local", "name": "review_rng_event"}
    hit_operation = operations["game.check.hit-v1"]
    draw_index = next(
        index
        for index, instruction in enumerate(hit_operation["body"])
        if instruction["node"] == "draw"
    )
    hit_operation["body"].insert(draw_index + 1, schedule)
    hit_operation["resource_bounds"]["max_steps"] = 10_000
    checked = replace(checked, rir=rir)

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    values = {
        name: deepcopy(member.value) for name, member in artifacts.members.items()
    }
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)
    events = values["event-trace"]["events"]
    catalog = values["snapshot-series"]["event_catalog"]
    parent_event = next(event for event in events if event["rng_draws"])
    draw = parent_event["rng_draws"][0]
    replacement = draw["value"] + 1 if draw["value"] < draw["maximum"] else 1
    draw["value"] = replacement
    schedule_trace = next(
        row
        for row in parent_event["schedules"]
        if row["parent_operation"] == "game.check.hit-v1"
    )
    next(row for row in schedule_trace["arguments"] if row["name"] == "cost")[
        "value"
    ] = replacement
    scheduled_record = next(
        row for row in catalog if row["event_id"] == schedule_trace["event_id"]
    )
    next(
        row
        for row in scheduled_record["event_spec"]["arguments"]
        if row["name"] == "cost"
    )["value"] = replacement
    event_spec_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["event_spec"]
    scheduled_record["event_spec_identity"] = content_identity(
        event_spec_contract["domain"],
        scheduled_record["event_spec"],
    )

    assert not experiment_evidence_module._event_catalog_records_are_authoritative(
        checked,
        catalog,
        events,
    )


def test_event_budget_and_rng_are_independent_per_scenario(tmp_path, run_cli):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
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
                "target": {"minimum": 0, "maximum": 1000},
            }
        )
    ]
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_total_events"] = 2

    artifacts = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    runtime_events = [
        event
        for event in artifacts.members["event-trace"].value["events"]
        if event["operation"] is not None
    ]
    assert len(runtime_events) == 2
    assert runtime_events[0]["rng_draws"] == runtime_events[1]["rng_draws"]


def test_event_step_budget_resets_for_each_event(tmp_path, run_cli):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    second = deepcopy(scenario["event_plan"][0])
    second["root_event_ref"] = "second-cast"
    second["logical_time"] = 1
    scenario["event_plan"].append(second)
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 2}
    specification["metrics"] = [
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
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    entrypoint = next(row for row in rir["entrypoints"] if row["id"] == "combat.cast")
    operation = operations[entrypoint["operation"]["id"]]
    runtime_nodes = experiment_runtime_module._runtime_nodes(checked)
    per_event_steps = sum(
        runtime_nodes[instruction["node"]]["resource_charge"]["amount"]
        for instruction in experiment_admission_module._expanded_operation_body(
            operation, operations
        )
    )
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_event_steps"] = per_event_steps

    artifacts = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    assert (
        len(
            [
                event
                for event in artifacts.members["event-trace"].value["events"]
                if event["operation"] is not None
            ]
        )
        == 2
    )


def test_observation_formula_runs_once_after_same_time_transition_queue_drains(
    tmp_path, run_cli, monkeypatch
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    transition = scenario["event_plan"][0]
    transition["logical_time"] = 0
    scenario["event_plan"] = [
        {
            "kind": "external-input",
            "root_event_ref": "raise-defense",
            "logical_time": 0,
            "priority": 0,
            "source_identity": "sha256:" + "e" * 64,
            "source_sequence": 0,
            "facts": [
                {
                    "target": {
                        "model": "example.rpg-combat-cast",
                        "module": "combat",
                        "name": "target_defense",
                    },
                    "value": 20,
                }
            ],
        },
        transition,
    ]
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 2}
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    evaluate_programs = experiment_runtime_module._evaluate_initialization_programs
    observation_frames: list[str] = []

    def record_formula_frame(*args, **kwargs):
        result = evaluate_programs(*args, **kwargs)
        if kwargs.get("phase") == "observation":
            observation_frames.append(kwargs["frame_identity"])
        return result

    monkeypatch.setattr(
        experiment_runtime_module,
        "_evaluate_initialization_programs",
        record_formula_frame,
    )

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    events = artifacts.members["event-trace"].value["events"]
    transition_event = next(event for event in events if event["operation"] is not None)
    assert observation_frames == [transition_event["snapshot_after_identity"]]


def test_event_metric_searches_the_complete_committed_scenario_trace(tmp_path, run_cli):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    next(row for row in scenario["assignments"] if row["target"]["name"] == "accuracy")[
        "value"
    ] = 1000
    plan = scenario["event_plan"][0]
    plan["logical_time"] = 0
    scenario["event_plan"] = [
        {
            "kind": "transition-invocation",
            "root_event_ref": "cast-before-plan",
            "logical_time": 0,
            "priority": 10,
            "entrypoint": "combat.cast",
            "payload": [],
        },
        plan,
    ]
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 2}
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "first_cast_damage",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "event",
                    "name": "cast-resolved",
                    "member": "damage_dealt",
                },
                "target": {"minimum": 1, "maximum": 1000},
            }
        )
    ]
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)

    artifacts = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(artifacts, experiment_runtime_module.EvaluationArtifacts)
    sample = artifacts.members["metric-dataset"].value["samples"][0]
    assert sample["metric"] == "first_cast_damage"
    assert sample["value"] > 0


def test_runtime_refuses_backward_child_scheduling_before_committing_the_event(
    tmp_path, run_cli
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    plan_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.plan-casts-v1"
    )
    first_schedule = next(
        instruction
        for instruction in plan_operation["body"]
        if instruction["node"] == "schedule"
    )
    first_schedule["logical_time"] = -1

    result = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(result, experiment_runtime_module.RuntimeRefusalOutcome)
    assert result.report.diagnostics[0].code == "runtime.schedule_backward"
    assert result.committed_trace_prefix == ()
    assert result.state_before == {"actor_mana": 30, "target_health": 100}
    assert result.state_after == result.state_before


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("hidden-input", "runtime.schedule_hidden_input"),
        ("illegal-same-time-priority", "runtime.schedule_illegal_same_time_priority"),
        ("logical-time-limit", "runtime.logical_time_exceeded"),
        ("queue-limit", "runtime.queue_limit_exceeded"),
        ("zero-time-depth", "runtime.zero_time_depth_exceeded"),
        ("event-limit", "runtime.event_limit_exceeded"),
        ("cancel-unknown", "runtime.cancel_unknown"),
    ],
)
def test_scheduler_refusal_variants_preserve_the_pre_event_prefix(
    tmp_path, run_cli, mutation, expected_code
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    plan_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.plan-casts-v1"
    )
    schedules = [
        instruction
        for instruction in plan_operation["body"]
        if instruction["node"] == "schedule"
    ]
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    if mutation == "hidden-input":
        schedules[0]["phase"] = "input"
    elif mutation == "illegal-same-time-priority":
        schedules[0]["logical_time"] = 0
        schedules[0]["priority"] = 1
    elif mutation == "logical-time-limit":
        schedules[0]["logical_time"] = 1 << 63
    elif mutation == "queue-limit":
        runtime_profile["resource_bounds"]["max_queue_events"] = 1
    elif mutation == "zero-time-depth":
        schedules[0]["logical_time"] = 0
        runtime_profile["resource_bounds"]["max_zero_time_depth"] = 0
    elif mutation == "event-limit":
        runtime_profile["resource_bounds"]["max_total_events"] = 1
    else:
        cancel = next(
            instruction
            for instruction in plan_operation["body"]
            if instruction["node"] == "cancel"
        )
        cancel["event"]["local"] = "missing_event"

    result = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(result, experiment_runtime_module.RuntimeRefusalOutcome)
    assert result.report.diagnostics[0].code == expected_code
    assert result.committed_trace_prefix == ()
    assert result.state_after == result.state_before


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("backward", "runtime.schedule_backward"),
        ("hidden-input", "runtime.schedule_hidden_input"),
        (
            "illegal-same-time-priority",
            "runtime.schedule_illegal_same_time_priority",
        ),
        ("logical-time-limit", "runtime.logical_time_exceeded"),
        ("zero-time-depth", "runtime.zero_time_depth_exceeded"),
        ("event-limit", "runtime.event_limit_exceeded"),
    ],
)
def test_periodic_scheduler_refusals_publish_through_the_public_run_command(
    tmp_path, run_cli, monkeypatch, mutation, expected_code
):
    specification, _build_receipt = _write_built_periodic_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    apply_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.effect.apply-snapshot-periodic-v1"
    )
    first_schedule = next(
        instruction
        for instruction in apply_operation["body"]
        if instruction["node"] == "schedule"
    )
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    if mutation == "backward":
        first_schedule["logical_time"] = -1
    elif mutation == "hidden-input":
        first_schedule["phase"] = "input"
    elif mutation == "illegal-same-time-priority":
        first_schedule["logical_time"] = 0
        first_schedule["priority"] = 1
    elif mutation == "logical-time-limit":
        first_schedule["logical_time"] = 1 << 63
    elif mutation == "zero-time-depth":
        first_schedule["logical_time"] = 0
        runtime_profile["resource_bounds"]["max_zero_time_depth"] = 0
    else:
        runtime_profile["resource_bounds"]["max_total_events"] = 1

    # These refusals originate in selected Package/Runtime semantics rather than
    # authored Experiment fields. Inject the checked semantic candidate at the
    # public handler seam, then drive the real dispatch, refusal envelope,
    # rollback audit, and publication path end to end.
    monkeypatch.setattr(
        experiment_run_application_module,
        "check_experiment",
        lambda _path: replace(checked, rir=rir),
    )
    out = tmp_path / f"periodic-{mutation}-refusal"

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(out),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    assert [row["code"] for row in error["diagnostics"]] == [expected_code]
    audit = _member(error["terminal_audit"], "runtime-terminal-audit")
    assert audit["refusing_event"]["operation"] == (
        "game.effect.apply-snapshot-periodic-v1"
    )
    assert audit["refusing_event"]["reason"] == expected_code
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]


def test_fault_after_provisional_schedules_rolls_back_scheduler_state(
    tmp_path, run_cli
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    plan_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.plan-casts-v1"
    )
    cancel = next(
        instruction
        for instruction in plan_operation["body"]
        if instruction["node"] == "cancel"
    )
    cancel["event"]["local"] = "missing_event"

    result = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(result, experiment_runtime_module.RuntimeRefusalOutcome)
    assert result.report.diagnostics[0].code == "runtime.cancel_unknown"
    assert result.committed_trace_prefix == ()
    assert result.budget_counters["total_events"] == 1
    assert result.budget_counters["queue_events"] == 0


def test_total_event_budget_counts_derived_observation_events(tmp_path, run_cli):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_total_events"] = 2

    result = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(result, experiment_runtime_module.RuntimeRefusalOutcome)
    assert result.report.diagnostics[0].code == "runtime.event_limit_exceeded"
    assert [
        cast(dict[str, Any], event["ordering_key"])["phase"]
        for event in result.committed_trace_prefix
    ] == ["transition", "observation"]
    assert result.budget_counters["total_events"] == 2
    assert result.refusing_operation == "observation"
    assert result.refusing_event_index == 2
    assert result.state_after == result.state_before


@pytest.mark.parametrize(
    ("bound", "expected_code"),
    [
        ("max_queue_events", "runtime.queue_limit_exceeded"),
        ("max_total_events", "runtime.event_limit_exceeded"),
        ("max_logical_time", "runtime.logical_time_exceeded"),
    ],
)
def test_authored_roots_are_admitted_against_runtime_bounds_before_dispatch(
    tmp_path, run_cli, bound, expected_code
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    second = deepcopy(scenario["event_plan"][0])
    second["root_event_ref"] = "second-cast"
    second["logical_time"] = 1
    scenario["event_plan"].append(second)
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 2}
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"][bound] = 0 if bound == "max_logical_time" else 1

    result = experiment_runtime_module.evaluate_experiment(replace(checked, rir=rir))

    assert isinstance(result, experiment_runtime_module.Schema2RefusalReport)
    assert result.stage == "runtime"
    assert result.diagnostics[0].code == expected_code


def test_complete_root_map_is_allocated_before_the_first_scenario_dispatch(
    tmp_path, run_cli
):
    specification_path = _write_scheduled_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    value = deepcopy(checked.value)
    second = deepcopy(value["scenarios"][0])
    second["id"] = "second-scenario"
    second["event_plan"][0]["root_event_ref"] = "second-plan"
    value["scenarios"].append(second)
    rir = deepcopy(checked.rir)
    plan_operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.plan-casts-v1"
    )
    first_schedule = next(
        instruction
        for instruction in plan_operation["body"]
        if instruction["node"] == "schedule"
    )
    first_schedule["logical_time"] = -1
    checked = replace(
        checked,
        value=value,
        content_identity=experiment_admission_module.experiment_input_identity(value),
        rir=rir,
    )

    result = experiment_runtime_module.evaluate_experiment(checked)

    assert isinstance(result, experiment_runtime_module.RuntimeRefusalOutcome)
    assert result.scenario_id == value["scenarios"][0]["id"]
    assert [row["scenario"] for row in result.root_event_map] == [
        value["scenarios"][0]["id"],
        "second-scenario",
    ]


@pytest.mark.parametrize(
    "external_roots",
    [
        [("a", 0, 0, 0), ("a", 0, 0, 0)],
        [("a", 1, 0, 0), ("a", 0, 0, 0)],
        [("a", 0, 0, 0), ("a", 2, 0, 0)],
        [("a", 0, 1, 0), ("a", 1, 0, 0)],
        [("a", 0, 0, 0), ("a", 1, 0, 10)],
    ],
    ids=[
        "duplicate",
        "decreasing",
        "continuity-gap",
        "logical-order",
        "priority-order",
    ],
)
def test_external_input_sources_require_canonical_contiguous_sequences(
    tmp_path, run_cli, external_roots
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    transition = deepcopy(scenario["event_plan"][0])
    transition["logical_time"] = 1
    target = scenario["assignments"][5]["target"]
    scenario["event_plan"] = [
        *[
            {
                "kind": "external-input",
                "root_event_ref": f"input-{index}",
                "logical_time": logical_time,
                "priority": priority,
                "source_identity": "sha256:" + source * 64,
                "source_sequence": sequence,
                "facts": [{"target": target, "value": 6 + index}],
            }
            for index, (source, sequence, logical_time, priority) in enumerate(
                external_roots
            )
        ],
        transition,
    ]
    scenario["terminal_condition"] = {"kind": "queue-drained"}
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    result = experiment_admission_module.check_experiment(str(specification_path))

    assert isinstance(result, experiment_runtime_module.Schema2RefusalReport)
    assert result.stage == "static"
    assert result.diagnostics[0].code == "language.source_contract_mismatch"


def test_external_facts_must_target_the_compiler_projected_reachable_contract(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    module = source_value["modules"][0]
    ambient = deepcopy(
        next(row for row in module["symbols"] if row["symbol"] == "target_defense")
    )
    ambient["symbol"] = "ambient_temperature"
    module["symbols"].append(ambient)
    source_path = tmp_path / "external-fact-contract-model.json"
    source_path.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source_path),
            "--out",
            str(tmp_path / "external-fact-contract-model"),
            "--invocation-key",
            "b" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    receipt = json.loads(build_stdout)
    build = _member(receipt, "build-receipt")
    rir = _member(receipt, "rir-semantic-payload")
    entrypoint = next(row for row in rir["entrypoints"] if row["id"] == "combat.cast")
    assert {
        row["target"]["name"] for row in entrypoint["external_fact_contract"]["targets"]
    } == {"target_defense"}

    specification = _experiment(
        kernel_identity=build["kernel_identity"],
        language_bundle_identity=build["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=receipt,
        base_damage=24,
    )
    scenario = specification["scenarios"][0]
    scenario["event_plan"] = [
        {
            "kind": "external-input",
            "root_event_ref": "ambient-input",
            "logical_time": 0,
            "priority": 0,
            "source_identity": "sha256:" + "d" * 64,
            "source_sequence": 0,
            "facts": [
                {
                    "target": {
                        "model": "example.rpg-combat-cast",
                        "module": "combat",
                        "name": "ambient_temperature",
                    },
                    "value": 10,
                }
            ],
        },
        {**scenario["event_plan"][0], "logical_time": 1},
    ]
    scenario["terminal_condition"] = {"kind": "queue-drained"}
    specification_path = tmp_path / "external-fact-contract-experiment.json"
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    result = experiment_admission_module.check_experiment(str(specification_path))

    assert isinstance(result, experiment_runtime_module.Schema2RefusalReport)
    assert result.stage == "static"
    assert result.diagnostics[0].code == "language.source_contract_mismatch"
    primary = result.diagnostics[0].primary
    assert isinstance(primary, ArtifactLocation)
    assert primary.pointer.endswith("/facts/0/target")


def test_public_experiment_admits_external_input_before_transition_until_queue_drains(
    tmp_path, run_cli
):
    specification_path = _write_built_experiment(tmp_path, run_cli)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    scenario = specification["scenarios"][0]
    scenario["event_plan"] = [
        {
            "kind": "external-input",
            "root_event_ref": "raise-defense",
            "logical_time": 0,
            "priority": 0,
            "source_identity": "sha256:" + ("8" * 64),
            "source_sequence": 0,
            "facts": [
                {
                    "target": {
                        "model": "example.rpg-combat-cast",
                        "module": "combat",
                        "name": "target_defense",
                    },
                    "value": 200,
                }
            ],
        },
        {
            "kind": "transition-invocation",
            "root_event_ref": "cast-after-input",
            "logical_time": 1,
            "priority": 0,
            "entrypoint": "combat.cast",
            "payload": [],
        },
    ]
    scenario["terminal_condition"] = {"kind": "queue-drained"}
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "terminal_health",
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
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification_path),
            "--out",
            str(tmp_path / "external-input-run"),
            "--invocation-key",
            "8" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)
    receipt = json.loads(stdout)
    events = _member(receipt, "event-trace")["events"]
    assert [
        (event["root_event_ref"], event["ordering_key"]["phase"])
        for event in events
        if "root_event_ref" in event
    ] == [
        ("raise-defense", "input"),
        ("cast-after-input", "transition"),
    ]
    assert events[0]["operation"] is None
    assert events[0]["outcome"] == {"id": "input-admitted", "kind": "success"}
    reproduction = _member(receipt, "reproduction-receipt")
    kernel, _language_bundle = mutable_authorities()
    input_contract = kernel["meta_format"]["runtime_program"]["scheduler"][
        "external_input_identity"
    ]
    input_identity = content_identity(
        input_contract["domain"],
        {
            "experiment_identity": reproduction["experiment_identity"],
            "scenario_id": "one-cast",
            "root_event_ref": "raise-defense",
            "source_identity": "sha256:" + ("8" * 64),
            "source_sequence": 0,
            "facts": scenario["event_plan"][0]["facts"],
        },
    )
    assert events[0]["external_input_identity"] == input_identity
    assert reproduction["external_input_identities"] == [
        {
            "scenario": "one-cast",
            "root_event_ref": "raise-defense",
            "source_identity": "sha256:" + ("8" * 64),
            "source_sequence": 0,
            "input_identity": input_identity,
        }
    ]
    assert (
        next(
            fact["integer"]
            for fact in events[1]["facts"]
            if fact["name"] == "target_defense"
        )
        == 200
    )
    assert events[1]["state_after"] == [
        {"name": "actor_mana", "value": 30},
        {"name": "target_health", "value": 100},
    ]
    observation = events[-1]
    assert observation["ordering_key"]["phase"] == "observation"
    assert observation["operation"] is None
    assert observation["entrypoint"] is None
    assert observation["outcome"] == {
        "id": "observation-emitted",
        "kind": "success",
    }
    assert observation["observation"]["metric"] == "terminal_health"
    assert observation["state_before"] == observation["state_after"]
    assert len(_member(receipt, "snapshot-series")["snapshots"]) == 4


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
                "expression": "let identity = identity(base);\nidentity",
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
                "expression": (
                    "let inner = combat.`derived-damage-inner`(base = base);\ninner"
                ),
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

    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    selected_entrypoints = [checked.rir["entrypoints"][0]]
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
        selected_entrypoints=selected_entrypoints,
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
            selected_entrypoints=selected_entrypoints,
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
            selected_entrypoints=selected_entrypoints,
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
            selected_entrypoints=selected_entrypoints,
        )
        == exact_charge
    )
    assert without_cache[derived_identity] == 32

    cyclic_rir = deepcopy(checked.rir)
    template_program = next(
        program
        for program in cyclic_rir["initialization_programs"]
        if program["site"]["context"]["phase"] == "initialization"
    )
    cycle_a = {
        "model": "example.rpg-combat-cast",
        "module": "combat",
        "name": "cycle_a",
    }
    cycle_b = {
        "model": "example.rpg-combat-cast",
        "module": "combat",
        "name": "cycle_b",
    }

    def cyclic_program(target: dict[str, str], dependency: dict[str, str]) -> dict:
        program = deepcopy(template_program)
        program["target"] = target
        program["inputs"] = [
            {
                "name": "base",
                "operand": {
                    "kind": "symbol",
                    "resolved_symbol": dependency,
                },
            }
        ]
        return program

    cyclic_rir["initialization_programs"] = [
        cyclic_program(cycle_a, cycle_b),
        cyclic_program(cycle_b, cycle_a),
    ]
    cyclic_entrypoint = deepcopy(selected_entrypoints[0])
    next(
        binding
        for binding in cyclic_entrypoint["arguments"]
        if binding["operand"]["kind"] == "symbol"
    )["operand"]["symbol"] = cycle_a
    cyclic_checked = replace(checked, rir=cyclic_rir)

    with pytest.raises(
        ValueError,
        match="admitted initialization program graph is cyclic",
    ):
        experiment_runtime_module._evaluate_initialization_programs(
            cyclic_checked,
            {},
            consumed_steps=0,
            runtime_limit=exact_charge,
            cache=None,
            selected_entrypoints=[cyclic_entrypoint],
        )

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
    formula["expression"] = (
        "let `fully-mitigated` = damage_before_defense < mitigation;\n"
        "let `bounded-damage` = if `fully-mitigated` then mitigation else "
        "damage_before_defense;\n"
        "`bounded-damage`"
    )
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
    formula["expression"] = "let underflow = base - 1;\nunderflow"
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
    rir = _member(build_receipt, "rir-semantic-payload")
    expected_evaluation_site = next(
        row["evaluation_site_identity"]
        for program in rir["initialization_programs"]
        if program["target"]["name"] == "effective_accuracy"
        and program["site"]["context"]["phase"] == "initialization"
        for row in program["body"]
        if row["instruction"]["node"] == "subtract"
    )
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
    payload = json.loads(stdout)
    jsonschema.validate(
        payload,
        schema2_error_envelope_schema(experiment_command_module.EXPERIMENT_RUN),
    )
    error = payload["error"]
    assert error["stage"] == "runtime"
    assert error["diagnostics"][0]["code"] == "runtime.numeric_overflow"
    diagnostic = error["diagnostics"][0]
    assert diagnostic["primary"] == {
        "kind": "runtime",
        "subject": "formula-evaluation-site",
        "identity": expected_evaluation_site,
    }
    assert diagnostic["primary"]["identity"].startswith("sha256:")
    assert diagnostic["related"] == [
        {
            "kind": "runtime",
            "subject": "initialization-frame",
            "identity": diagnostic["related"][0]["identity"],
        },
        {
            "kind": "artifact",
            "content_identity": content_identity(
                "experiment-specification-v2", specification
            ),
            "pointer": "/scenarios/0/assignments",
        },
    ]
    assert diagnostic["related"][0]["identity"].startswith("sha256:")
    message = diagnostic["message"]
    assert "refused before Snapshot 0" in message
    assert "evaluation site sha256:" in message
    assert "immutable frame sha256:" in message
    assert f"evaluation site {expected_evaluation_site}" in message
    assert f"immutable frame {diagnostic['related'][0]['identity']}" in message
    assert "terminal_audit" not in error
    assert not out.exists()

    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    evaluation = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(evaluation, experiment_runtime_module.Schema2RefusalReport)
    assert evaluation.variant == "pre-event"
    assert evaluation.diagnostics[0].model_dump(mode="json") == diagnostic


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
    checked = experiment_admission_module.check_experiment(str(spec_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
    observation_input_snapshots = [
        snapshot for snapshot in snapshots if ":event:" in snapshot["name"]
    ]
    assert observation_frames == [
        snapshot["snapshot_identity"] for snapshot in observation_input_snapshots
    ]
    assert len(set(observation_frames)) == 2
    assert observation_cache_growth == [1, 1]
    runtime_events = [event for event in events if event["operation"] is not None]
    for event in runtime_events:
        facts = {row["name"]: row["integer"] for row in event["facts"]}
        assert facts["target_health"] == 82
        assert facts["effective_accuracy"] == 100
    for event in events:
        if event["operation"] is not None:
            continue
        facts = {row["name"]: row["integer"] for row in event["facts"]}
        assert facts["target_health"] == 82
        assert facts["effective_accuracy"] == facts["target_health"]
    positive_evidence = _observation_evidence(
        site="runtime.lifecycle-observation.positive",
        cache_entries=observation_cache_growth[0],
        events=runtime_events[:1],
        outcome="admitted",
        post_state_committed=(
            observation_input_snapshots[0]["values"] == runtime_events[0]["state_after"]
        ),
        snapshot_identities=cast(list[str], observation_frames[:1]),
        snapshot_indices=[observation_input_snapshots[0]["index"]],
    )
    boundary_evidence = _observation_evidence(
        site="runtime.lifecycle-observation.boundary",
        cache_entries=sum(observation_cache_growth),
        events=runtime_events,
        outcome="admitted",
        post_state_committed=(
            observation_input_snapshots[-1]["values"]
            == runtime_events[-1]["state_after"]
        ),
        snapshot_identities=cast(list[str], observation_frames),
        snapshot_indices=[
            snapshot["index"] for snapshot in observation_input_snapshots
        ],
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
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
    assert tuple(
        {
            "index": event["index"],
            "operation": event["operation"],
            "outcome": event["outcome"],
        }
        for event in outcome.committed_trace_prefix
    ) == (
        {
            "index": 0,
            "operation": "game.combat.cast-v1",
            "outcome": {"id": "cast-resolved", "kind": "success"},
        },
        {
            "index": 1,
            "operation": None,
            "outcome": {"id": "observation-emitted", "kind": "success"},
        },
        {
            "index": 2,
            "operation": None,
            "outcome": {"id": "observation-emitted", "kind": "success"},
        },
        {
            "index": 3,
            "operation": "game.combat.cast-v1",
            "outcome": {"id": "cast-resolved", "kind": "success"},
        },
    )
    assert outcome.refusing_event_index == 4
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
        snapshot_indices=[1, 5],
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
    formula["expression"] = "combat.formula_bonus"
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
        experiment_admission_module.derive_scenario_program_requirements(
            _member(build_receipt, "rir-semantic-payload"),
            entrypoint_id=specification["scenarios"][0]["event_plan"][0]["entrypoint"],
            runtime_profile=specification["runtime"]["profile"],
            rng_algorithm=specification["seed"]["algorithm"],
        )
    )
    specification["runtime"]["required_evaluator"] = requirements
    spec_path = tmp_path / "event-symbol-formula-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    checked = experiment_admission_module.check_experiment(str(spec_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)

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
                "version": "2.1.0",
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
            "event_plan": [
                {
                    "kind": "transition-invocation",
                    "root_event_ref": "cast",
                    "logical_time": 0,
                    "priority": 0,
                    "entrypoint": "combat.cast",
                    "payload": [],
                }
            ],
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
    root_event = value["scenarios"][0]["event_plan"][0]
    root_event.pop("entrypoint")
    root_event["operation"] = "game.combat.cast-v1"
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    pointer = error["diagnostics"][0]["primary"]["pointer"]
    assert pointer in {
        "/scenarios/0/event_plan/0/entrypoint",
        "/scenarios/0/event_plan/0/operation",
    }


@pytest.mark.parametrize(
    ("target_name", "accepted"),
    (("base_damage", True), ("actor_mana", False)),
)
def test_transition_payload_must_exactly_match_its_event_local_contract(
    tmp_path, run_cli, target_name, accepted
):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    transition = next(
        event
        for event in value["scenarios"][0]["event_plan"]
        if event["kind"] == "transition-invocation"
    )
    transition["payload"] = [
        {
            "target": {
                "model": "example.rpg-combat-cast",
                "module": "combat",
                "name": target_name,
            },
            "value": 50,
        }
    ]
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert stderr == ""
    assert exit_code == (0 if accepted else 2)
    if not accepted:
        error = json.loads(stdout)["error"]
        assert error["stage"] == "static"
        assert error["diagnostics"][0]["primary"]["pointer"] == (
            "/scenarios/0/event_plan/0/payload"
        )


def test_transition_payload_rejects_duplicate_targets(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    transition = next(
        event
        for event in value["scenarios"][0]["event_plan"]
        if event["kind"] == "transition-invocation"
    )
    payload = {
        "target": {
            "model": "example.rpg-combat-cast",
            "module": "combat",
            "name": "base_damage",
        },
        "value": 50,
    }
    transition["payload"] = [payload, deepcopy(payload)]
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["experiment", "check", str(specification)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/scenarios/0/event_plan/0/payload"
    )


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

        checked = experiment_admission_module.check_experiment(str(path))
        assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model"),
            "--invocation-key",
            "1" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, ""), build_stdout
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")

    baseline = json.loads(
        (_EXAMPLE_DIR / "experiment.json").read_text(encoding="utf-8")
    )
    assert baseline["kernel_identity"] == build_record["kernel_identity"]
    assert (
        baseline["language_bundle_identity"] == build_record["language_bundle_identity"]
    )
    assert baseline["model"] == {
        "source_identity": content_identity("model-source-package-v2", source_value),
        "build_receipt_identity": build_record["content_identity"],
        "resolved_model_identity": build_record["resolved_model_identity"],
        "package_lock_identity": build_record["package_lock_identity"],
        "rir_identity": build_record["rir_identity"],
    }

    def run(specification: dict[str, Any], name: str, key: str):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(specification), encoding="utf-8")
        check_exit, check_stdout, check_stderr = run_cli(
            ["experiment", "check", str(path)]
        )
        assert (check_exit, check_stderr) == (0, ""), check_stdout
        exit_code, stdout, stderr = run_cli(
            [
                "experiment",
                "run",
                str(path),
                "--out",
                str(tmp_path / name),
                "--invocation-key",
                key,
            ]
        )
        assert (exit_code, stderr) == (0, ""), stdout
        receipt = json.loads(stdout)
        return (
            _member(receipt, "event-trace"),
            _member(receipt, "metric-dataset"),
        )

    baseline_trace, baseline_metrics = run(baseline, "baseline", "2" * 64)
    tuned = deepcopy(baseline)
    tuned["id"] = "example.rpg-combat-cast.player-damage-tuned"
    next(
        assignment
        for assignment in tuned["scenarios"][0]["assignments"]
        if assignment["target"]["name"] == "player_base_damage"
    )["value"] = 55
    tuned_trace, tuned_metrics = run(tuned, "tuned", "3" * 64)

    assert tuned["kernel_identity"] == baseline["kernel_identity"]
    assert tuned["language_bundle_identity"] == baseline["language_bundle_identity"]
    assert tuned["model"] == baseline["model"]
    assert tuned["runtime"] == baseline["runtime"]
    assert tuned_trace["content_identity"] != baseline_trace["content_identity"]

    baseline_values = {
        sample["metric"]: sample["value"] for sample in baseline_metrics["samples"]
    }
    tuned_values = {
        sample["metric"]: sample["value"] for sample in tuned_metrics["samples"]
    }
    assert {
        metric: tuned_values[metric]
        for metric in tuned_values
        if tuned_values[metric] != baseline_values[metric]
    } == {
        "enemy_health_remaining": 53,
        "player_damage_dealt": 47,
    }
    assert [
        event["outcome"]
        for event in tuned_trace["events"]
        if event["operation"] is not None
    ] == [
        {"id": "cast-resolved", "kind": "success"},
        {"id": "cast-resolved", "kind": "success"},
    ]


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
    for entrypoint in renamed["entrypoints"]:
        for argument in entrypoint["arguments"]:
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
    assert experiment_admission_module.experiment_input_identity(
        baseline_spec
    ) != experiment_admission_module.experiment_input_identity(renamed_spec)
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
        publication_module.find_published_artifact(
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


def test_package_operation_execution_vectors_preserve_integer_runtime_behavior():
    kernel, ldb = mutable_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    vectors = [
        vector
        for vector in next(
            vector_set["vector_definitions"]
            for vector_set in ldb.package_conformance_vector_sets
            if vector_set["package_id"] == "game.combat"
            and vector_set["package_version"] == "2.1.0"
        )
        if vector.get("kind") == "operation-execution"
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
            state_names={
                row["id"]
                for row in operation["inputs"]
                if row["access"] == "read-write"
            },
        )
        projection = {
            "completion": {"kind": "outcome", "id": event["outcome"]["id"]},
            "result": (
                {"kind": "value", "value": event["result"]}
                if event["outcome"]["kind"] == "success"
                else {"kind": "not-produced"}
            ),
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
            state_names={
                row["id"]
                for row in operation["inputs"]
                if row["access"] == "read-write"
            },
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


def _reference_operation_execution_projection(
    kernel: dict[str, Any],
    ldb: Any,
    operations: dict[str, dict[str, Any]],
    vector: dict[str, Any],
) -> dict[str, Any]:
    operation = operations[vector["operation"]]
    event = _reference_execute_event(
        kernel,
        operation,
        operations,
        {"id": vector["id"], "values": vector["input"]["values"]},
        seed=vector["input"]["seed"],
        state_names={
            row["id"] for row in operation["inputs"] if row["access"] == "read-write"
        },
        language_bundle=ldb,
    )
    state_after = {row["name"]: row["value"] for row in event["state_after"]}
    state_names = [
        row["id"] for row in operation["inputs"] if row["access"] == "read-write"
    ]
    if "refusal" in event:
        return {
            "completion": {
                "kind": "refusal",
                "reason": event["refusal"]["reason"],
            },
            "result": {"kind": "not-produced"},
            "rng_draws": [],
            "state_after": [
                {"name": name, "value": state_after[name]} for name in state_names
            ],
        }
    return {
        "completion": {
            "kind": "outcome",
            "id": event["outcome"]["id"],
        },
        "result": (
            {"kind": "value", "value": event["result"]}
            if event["outcome"]["kind"] == "success"
            else {"kind": "not-produced"}
        ),
        "rng_draws": [
            {
                member: draw[member]
                for member in ("candidate_hex", "index", "stream", "value")
            }
            for draw in event["rng_draws"]
        ],
        "state_after": [
            {"name": name, "value": state_after[name]} for name in state_names
        ],
    }


def _operation_execution_vectors(ldb: Any) -> list[tuple[str, dict[str, Any]]]:
    return [
        (vector_set["package_id"], vector)
        for vector_set in ldb.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector.get("kind") == "operation-execution"
    ]


def test_neutral_structured_operation_vectors_cover_control_paths():
    kernel, ldb = mutable_authorities()
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    vectors = [
        vector
        for package_id, vector in _operation_execution_vectors(ldb)
        if package_id == "standard.conformance.structured"
    ]
    assert {vector["id"] for vector in vectors} == {
        "structured.select.success",
        "structured.select.empty-outcome",
        "structured.select.mismatch-refusal",
    }

    for vector in vectors:
        assert (
            _reference_operation_execution_projection(kernel, ldb, operations, vector)
            == vector["expect"]
        )


def test_generation_operation_vectors_cover_success_fallback_and_refusals():
    _kernel, ldb = mutable_authorities()

    assert {
        vector["id"]
        for package_id, vector in _operation_execution_vectors(ldb)
        if package_id == "game.generation"
    } == {
        "generation.select.success",
        "generation.select.no-reward-outcome",
        "generation.select.empty-refusal",
        "generation.select.invalid-fallback-refusal",
        "generation.select.invalid-option-refusal",
    }


def test_build_operation_vectors_cover_success_alternatives_and_refusal():
    _kernel, ldb = mutable_authorities()

    assert {
        vector["id"]
        for package_id, vector in _operation_execution_vectors(ldb)
        if package_id == "game.build"
    } == {
        "build.replace.success",
        "build.replace.no-reward-outcome",
        "build.replace.conflict-outcome",
        "build.replace.invalid-plan-refusal",
    }


def test_build_operation_guards_no_reward_before_plan_access_without_rng():
    _kernel, ldb = mutable_authorities()
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.build.replace-reward-v1"
    )

    assert operation["body"][:3] == [
        {
            "key": "disposition",
            "node": "lookup",
            "target": "selected_disposition",
            "value": "selected_reward",
        },
        {
            "left": "selected_disposition",
            "node": "equal",
            "right": "expected_no_reward_disposition",
            "target": "no_reward_selected",
        },
        {
            "body": [],
            "condition": "no_reward_selected",
            "node": "guard-block",
            "outcome": "no-reward",
        },
    ]
    assert operation["effects"] == [
        "event.commit",
        "metric.observe",
        "snapshot.commit",
    ]
    assert operation["resource_bounds"] == {"max_steps": 50}


def test_candidate_graph_executes_every_operation_vector_in_two_consumers():
    kernel, ldb = mutable_authorities()
    context = authority_module.admit_authority_context(kernel, ldb)
    assert isinstance(context, authority_module.AdmittedAuthorityContext)
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    vectors = _operation_execution_vectors(ldb)
    assert vectors

    for package_id, vector in vectors:
        production = evaluate_operation_execution_vector(context, vector)
        reference = _reference_operation_execution_projection(
            kernel, ldb, operations, vector
        )
        assert production == reference == vector["expect"], (
            package_id,
            vector["id"],
            production,
            reference,
        )


def test_candidate_graph_gate_identifies_an_operation_vector_divergence():
    kernel, ldb = mutable_authorities()
    context = authority_module.admit_authority_context(kernel, ldb)
    assert isinstance(context, authority_module.AdmittedAuthorityContext)
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    package_id, vector = next(
        (package_id, deepcopy(candidate))
        for package_id, candidate in _operation_execution_vectors(ldb)
        if candidate["id"] == "structured.select.empty-outcome"
    )
    vector["expect"]["completion"]["id"] = "mutated-outcome"

    production = evaluate_operation_execution_vector(context, vector)
    reference = _reference_operation_execution_projection(
        kernel, ldb, operations, vector
    )
    with pytest.raises(AssertionError) as failure:
        assert production == reference == vector["expect"], (
            package_id,
            vector["id"],
            production,
            reference,
        )
    assert package_id in str(failure.value)
    assert vector["id"] in str(failure.value)


def test_package_scheduler_vectors_execute_in_two_consumers_and_detect_mutations():
    kernel, ldb = mutable_authorities()
    vectors = {
        vector["id"]: vector
        for vector in next(
            vector_set["vector_definitions"]
            for vector_set in ldb.package_conformance_vector_sets
            if vector_set["package_id"] == "standard.runtime"
            and vector_set["package_version"] == "1.1.0"
        )
        if vector.get("kind") == "scheduler-scenario"
    }
    mutation_vectors = {
        vector_id: vector["detects_mutation"]
        for vector_id, vector in vectors.items()
        if vector["category"] == "semantic-mutation"
    }
    vector_contract = next(
        kind
        for kind in kernel["meta_format"]["package_vector"]["kinds"]
        if kind["id"] == "scheduler-scenario"
    )
    assert set(mutation_vectors.values()) == set(vector_contract["mutation_detectors"])
    assert set(vectors) == {
        "runtime.scheduler.accept.total-order-visibility-cancellation",
        "runtime.scheduler.refuse.cancel-active",
        "runtime.scheduler.refuse.cancel-completed",
        *mutation_vectors,
    }
    non_semantic_detections = {
        "runtime.scheduler.accept.total-order-visibility-cancellation": {
            "host-assigned-ordering",
            "omitted-key",
            "pre-commit-visibility",
            "scenario-as-timestep",
        },
        "runtime.scheduler.refuse.cancel-active": set(),
        "runtime.scheduler.refuse.cancel-completed": set(),
    }
    assert set(non_semantic_detections) == {
        vector_id
        for vector_id, vector in vectors.items()
        if vector["category"] != "semantic-mutation"
    }
    mutation_inputs = [
        canonical_bytes(vectors[vector_id]["input"]) for vector_id in mutation_vectors
    ]
    assert len(set(mutation_inputs)) == len(mutation_inputs)
    for vector in vectors.values():
        assert (vector["detects_mutation"] is not None) == (
            vector["category"] == "semantic-mutation"
        )
        production = evaluate_runtime_scheduler_vector(kernel, vector)
        reference = _reference_evaluate_scheduler_vector(kernel, vector)
        assert production == reference == vector["expect"]
    for mutation in mutation_vectors.values():
        for candidate_id, candidate in vectors.items():
            production = evaluate_runtime_scheduler_vector(
                kernel,
                candidate,
                mutation=mutation,
            )
            reference = _reference_evaluate_scheduler_vector(
                kernel,
                candidate,
                mutation=mutation,
            )
            production_detected = production != candidate["expect"]
            reference_detected = reference != candidate["expect"]
            expected_detected = (
                candidate["detects_mutation"] == mutation
                if candidate["category"] == "semantic-mutation"
                else mutation in non_semantic_detections[candidate_id]
            )
            assert production_detected is expected_detected, candidate_id
            assert reference_detected is expected_detected, candidate_id


def test_runtime_scheduler_seam_orders_events_from_the_kernel_contract():
    kernel, _ldb = mutable_authorities()
    events = [
        {
            "id": "observation",
            "logical_time": 1,
            "phase": "observation",
            "priority": 1,
            "enqueue_sequence": 0,
        },
        {
            "id": "later-enqueue",
            "logical_time": 1,
            "phase": "transition",
            "priority": 0,
            "enqueue_sequence": 2,
        },
        {
            "id": "higher-priority",
            "logical_time": 1,
            "phase": "transition",
            "priority": 1,
            "enqueue_sequence": 1,
        },
        {
            "id": "earlier-time",
            "logical_time": 0,
            "phase": "transition",
            "priority": 0,
            "enqueue_sequence": 3,
        },
    ]

    ordered = RuntimeScheduler.from_kernel(kernel).ordered_events(events)

    assert [event["id"] for event in ordered] == [
        "earlier-time",
        "higher-priority",
        "later-enqueue",
        "observation",
    ]


def test_runtime_scheduler_seam_refuses_backward_scheduling():
    kernel, ldb = mutable_authorities()
    vector = next(
        vector
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "runtime.scheduler.mutation.backward"
    )
    events = {event["id"]: event for event in vector["input"]["events"]}

    signal = RuntimeScheduler.from_kernel(kernel).schedule_position_signal(
        events["parent"], events["child"]
    )

    assert signal == vector["expect"]["signal"]


def test_runtime_scheduler_seam_refuses_completed_cancellation():
    kernel, ldb = mutable_authorities()
    vector = next(
        vector
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "runtime.scheduler.refuse.cancel-completed"
    )

    signal = RuntimeScheduler.from_kernel(kernel).cancel_target_signal(
        vector["input"]["events"][0]["status"]
    )

    assert signal == vector["expect"]["signal"]


def test_scheduler_conformance_harness_refuses_missing_detector_implementations():
    kernel, _ldb = mutable_authorities()

    with pytest.raises(ValueError, match="missing detector implementations"):
        require_complete_scheduler_detector_bindings(
            kernel,
            {"backward-scheduling": object()},
            consumer="production",
        )


def test_scheduler_conformance_harness_refuses_unexpected_detector_implementations():
    kernel, _ldb = mutable_authorities()
    declared = {
        detector: object()
        for detector in next(
            kind["mutation_detectors"]
            for kind in kernel["meta_format"]["package_vector"]["kinds"]
            if kind["id"] == "scheduler-scenario"
        )
    }

    with pytest.raises(ValueError, match="unexpected detector implementations"):
        require_complete_scheduler_detector_bindings(
            kernel,
            {**declared, "host-invented-mutation": object()},
            consumer="reference",
        )


@pytest.mark.parametrize(
    "detectors",
    [
        (),
        [],
        ["z-last", "a-first"],
        ["duplicate", "duplicate"],
        ["", "valid"],
        [1, "valid"],
    ],
    ids=["not-list", "empty", "unsorted", "duplicate", "empty-name", "non-string"],
)
def test_scheduler_detector_inventory_refuses_a_nonclosed_declaration(detectors):
    kernel, _ldb = mutable_authorities()
    altered_kernel = deepcopy(kernel)
    vector_contract = next(
        kind
        for kind in altered_kernel["meta_format"]["package_vector"]["kinds"]
        if kind["id"] == "scheduler-scenario"
    )
    vector_contract["mutation_detectors"] = detectors

    with pytest.raises(ValueError, match="detector inventory is not closed"):
        scheduler_detector_inventory(altered_kernel)


def test_reference_scheduler_consumer_refuses_an_unimplemented_kernel_detector():
    kernel, ldb = mutable_authorities()
    altered_kernel = deepcopy(kernel)
    vector_contract = next(
        kind
        for kind in altered_kernel["meta_format"]["package_vector"]["kinds"]
        if kind["id"] == "scheduler-scenario"
    )
    vector_contract["mutation_detectors"] = sorted(
        [*vector_contract["mutation_detectors"], "unimplemented-scheduler-law"]
    )
    vector = next(
        vector
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "runtime.scheduler.mutation.omitted-key"
    )

    with pytest.raises(ValueError, match="missing detector implementations"):
        _reference_evaluate_scheduler_vector(altered_kernel, vector)


def test_production_scheduler_consumer_refuses_an_unimplemented_kernel_detector():
    kernel, ldb = mutable_authorities()
    altered_kernel = deepcopy(kernel)
    vector_contract = next(
        kind
        for kind in altered_kernel["meta_format"]["package_vector"]["kinds"]
        if kind["id"] == "scheduler-scenario"
    )
    vector_contract["mutation_detectors"] = sorted(
        [*vector_contract["mutation_detectors"], "unimplemented-scheduler-law"]
    )
    vector = next(
        vector
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "runtime.scheduler.mutation.omitted-key"
    )

    with pytest.raises(ValueError, match="missing detector implementations"):
        evaluate_runtime_scheduler_vector(altered_kernel, vector)


@pytest.mark.parametrize(
    "consumer",
    [evaluate_runtime_scheduler_vector, _reference_evaluate_scheduler_vector],
    ids=["production", "reference"],
)
def test_scheduler_consumers_refuse_unknown_requested_mutations(consumer):
    kernel, ldb = mutable_authorities()
    vector = next(
        vector
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "runtime.scheduler.mutation.omitted-key"
    )

    with pytest.raises(ValueError, match="unsupported scheduler mutation"):
        consumer(kernel, vector, mutation="host-invented-mutation")


def test_package_value_program_vectors_execute_in_two_consumers():
    _kernel, ldb = mutable_authorities()
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
    _kernel, ldb = mutable_authorities()
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


def test_experiment_check_bounds_the_file_read_before_admission(monkeypatch):
    context = authority_module.packaged_authority_context()
    max_bytes = cast(int, context.language_bundle["resources"]["max_source_bytes"])
    calls: list[tuple[str, int]] = []
    oversized_sha256 = "a" * 64

    def reject_oversized(path: str, limit: int) -> BoundedInputObservation:
        calls.append((path, limit))
        return BoundedInputObservation(data=None, sha256=oversized_sha256)

    monkeypatch.setattr(
        experiment_admission_module,
        "read_bounded_input_with_sha256",
        reject_oversized,
        raising=False,
    )

    result = experiment_admission_module.check_experiment(
        "oversized-experiment.json",
        authority_context=context,
    )

    assert isinstance(result, Schema2RefusalReport)
    assert calls == [("oversized-experiment.json", max_bytes)]
    assert result.stage == "ingress"
    assert result.diagnostics[0].code == "language.source_too_large"
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.content_identity == (
        f"sha256:{oversized_sha256}"
    )


def test_hashed_bounded_input_preserves_oversized_content_identity(tmp_path):
    data = b"oversized" * 10
    source = tmp_path / "oversized.bin"
    source.write_bytes(data)

    observation = read_bounded_input_with_sha256(str(source), max_bytes=8)

    assert observation.data is None
    assert observation.sha256 == hashlib.sha256(data).hexdigest()


def test_experiment_refuses_removed_top_level_external_inputs_member(tmp_path, run_cli):
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
    checked = experiment_admission_module.check_experiment(str(specification))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)

    first = experiment_runtime_module._evaluator_manifest(checked)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    assert set(first.value["instruction_nodes"]) == {
        instruction["node"]
        for scenario in checked.value["scenarios"]
        for event in scenario["event_plan"]
        for instruction in experiment_admission_module._expanded_operation_body(
            operations[entrypoints[event["entrypoint"]]["operation"]["id"]],
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


def test_operation_closure_includes_guard_body_nodes_and_invocations():
    operations = {
        "example.root": {
            "id": "example.root",
            "body": [
                {
                    "node": "guard-block",
                    "condition": "enabled",
                    "body": [
                        {"node": "copy", "value": "input", "target": "copied"},
                        {
                            "node": "invoke",
                            "operation": {
                                "package": "example",
                                "version": "1.0.0",
                                "id": "example.child",
                            },
                        },
                    ],
                    "outcome": "complete",
                }
            ],
        },
        "example.child": {
            "id": "example.child",
            "body": [{"node": "constant", "literal": 1, "target": "one"}],
        },
    }

    expanded = experiment_admission_module._expanded_operation_body(
        operations["example.root"], operations
    )

    assert [instruction["node"] for instruction in expanded] == [
        "guard-block",
        "copy",
        "invoke",
        "constant",
    ]


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


def test_metric_dataset_emits_one_replication_for_each_scenario(tmp_path, run_cli):
    specification = _write_built_experiment(tmp_path, run_cli)
    value = json.loads(specification.read_text(encoding="utf-8"))
    second = deepcopy(value["scenarios"][0])
    second["id"] = "second-cast"
    value["scenarios"].append(second)
    value["metrics"] = [
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
    specification.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "scenario-replications.json"),
            "--invocation-key",
            "2" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    dataset = _member(json.loads(stdout), "metric-dataset")
    assert [sample["scenario"] for sample in dataset["samples"]] == [
        "one-cast",
        "second-cast",
    ]
    assert [sample["replication_identity"] for sample in dataset["samples"]] == [
        "one-cast",
        "second-cast",
    ]


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


def _assert_numeric_overflow_rolls_back_the_entire_current_event(
    tmp_path,
    run_cli,
    base_damage_value,
    extend_base_damage_domain,
):
    source_value = _rpg_model_source()
    base_damage = next(
        symbol
        for symbol in source_value["modules"][0]["symbols"]
        if symbol["symbol"] == "base_damage"
    )
    if extend_base_damage_domain:
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
        base_damage=base_damage_value,
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
    kernel, ldb = mutable_authorities()
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


def test_numeric_overflow_rolls_back_the_entire_current_event(tmp_path, run_cli):
    _assert_numeric_overflow_rolls_back_the_entire_current_event(
        tmp_path,
        run_cli,
        1 << 62,
        True,
    )


def test_receiving_resource_domain_overflow_rolls_back_the_entire_current_event(
    tmp_path,
    run_cli,
):
    _assert_numeric_overflow_rolls_back_the_entire_current_event(
        tmp_path,
        run_cli,
        101,
        False,
    )


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
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
    rir["call_sites"] = model_lowering_module._resolved_call_sites(
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
        content_identity=experiment_admission_module.experiment_input_identity(value),
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
        key: item
        for key, item in production_event.items()
        if key not in _REFERENCE_EVENT_RUNTIME_BINDINGS
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
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
    rir["call_sites"] = model_lowering_module._resolved_call_sites(
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
        key: value
        for key, value in production_event.items()
        if key not in _REFERENCE_EVENT_RUNTIME_BINDINGS
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
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
    rir["call_sites"] = model_lowering_module._resolved_call_sites(
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
        key: value
        for key, value in production_event.items()
        if key not in _REFERENCE_EVENT_RUNTIME_BINDINGS
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
    checked = experiment_admission_module.check_experiment(str(specification_path))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
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
        content_identity=experiment_admission_module.experiment_input_identity(value),
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
        key: item
        for key, item in production_event.items()
        if key not in _REFERENCE_EVENT_RUNTIME_BINDINGS
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
    assert (
        len([event for event in trace["events"] if event["operation"] is not None]) == 5
    )
    assert (
        len([event for event in trace["events"] if event["observation"] is not None])
        == 5
    )


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
    prefix = audit["committed_trace_prefix"]
    assert [event["ordering_key"]["phase"] for event in prefix] == [
        "transition",
        "observation",
        "observation",
    ]
    assert prefix[0]["root_event_ref"] == "cast"
    assert prefix[0]["entrypoint"]["id"] == "combat.cast"
    assert prefix[0]["event_id"].startswith("sha256:")
    assert all(
        call["call_site_identity"].startswith("sha256:") for call in prefix[0]["calls"]
    )
    assert prefix[0]["snapshot_before_identity"].startswith("sha256:")
    assert prefix[-1]["snapshot_after_identity"].startswith("sha256:")
    assert prefix[-1]["observation"]["window"] == {
        "kind": "scenario",
        "name": "terminal-event",
    }
    assert (
        audit["last_snapshot_identity"]
        == audit["refusing_event"]["snapshot_before_identity"]
    )
    assert audit["last_snapshot_identity"] != prefix[-1]["snapshot_after_identity"]
    assert audit["terminal_condition"] == {"kind": "event-count", "maximum": 1}
    assert audit["root_event_map"] == [
        {
            "scenario": "one-cast",
            "root_event_ref": "cast",
            "event_id": prefix[0]["event_id"],
        },
        {
            "scenario": "overflowing-cast",
            "root_event_ref": "cast",
            "event_id": audit["refusing_event"]["event_id"],
        },
    ]
    assert audit["refusing_event"]["ordering_key"] == {
        "logical_time": 0,
        "phase": "transition",
        "priority": 0,
        "enqueue_sequence": 0,
    }
    assert (
        audit["refusing_event"]["snapshot_before_identity"]
        == audit["last_snapshot_identity"]
    )
    assert audit["budget_counters"]["logical_time"] == 0
    assert audit["budget_counters"]["queue_events"] == 0
    assert audit["budget_counters"]["total_events"] == 1
    assert audit["budget_counters"]["zero_time_depth"] == 0
    assert audit["budget_counters"]["event_steps"] > 0
    assert audit["budget_counters"]["node_steps"] > 0


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


@pytest.mark.parametrize(
    "fault",
    [
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    ],
)
def test_periodic_effect_publication_fault_recovers_one_complete_lifecycle(
    tmp_path, run_cli, monkeypatch, fault
):
    specification, _build_receipt = _write_built_periodic_experiment(tmp_path, run_cli)
    out = tmp_path / f"periodic-{fault}.json"
    key = "8" * 64
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
            publication_fault=fault
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()
    if fault == "after-commit":

        def evaluator_must_not_run(_checked):
            raise AssertionError("Invocation-key recovery reran the periodic evaluator")

        monkeypatch.setattr(
            experiment_run_application_module,
            "evaluate_experiment",
            evaluator_must_not_run,
        )
    else:
        store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
        descriptor_key = descriptor_identity(
            experiment_command_module.EXPERIMENT_RUN
        ).removeprefix("sha256:")
        assert not (store / "invocations" / descriptor_key / key).exists()
        assert not (store / "anchors" / descriptor_key / f"{key}.json").exists()

    recovered_exit, recovered_stdout, recovered_stderr = run_cli(
        argv,
        registry=(experiment_command_module.EXPERIMENT_RUN,),
    )

    assert (recovered_exit, recovered_stderr) == (0, "")
    recovered = json.loads(recovered_stdout)
    assert recovered["invocation_key"] == key
    trace = _member(recovered, "event-trace")
    lifecycle = [
        event["entrypoint"]["id"]
        if event.get("entrypoint") is not None
        else event["operation"]
        for event in trace["events"]
        if event["ordering_key"]["phase"] == "transition"
        and event["operation"].startswith("game.effect.")
    ]
    assert lifecycle == [
        "effect.apply-snapshot-periodic",
        "game.effect.tick-snapshot-periodic-v1",
        "game.effect.tick-snapshot-periodic-v1",
        "game.effect.expire-periodic-v1",
    ]
    formula_evaluations = [
        evaluation
        for event in trace["events"]
        for evaluation in event["formula_evaluations"]
    ]
    assert [evaluation["result"] for evaluation in formula_evaluations] == [15]
    assert out.exists()


def test_periodic_effect_public_artifacts_replay_in_an_independent_evaluator(
    tmp_path, run_cli
):
    specification, build_receipt = _write_built_periodic_experiment(tmp_path, run_cli)
    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "independent-periodic-evaluation.json"),
            "--invocation-key",
            "9" * 64,
        ]
    )
    assert (exit_code, stderr) == (0, "")

    receipt = json.loads(stdout)
    rir = _member(build_receipt, "rir-semantic-payload")
    trace = _member(receipt, "event-trace")
    snapshots = _member(receipt, "snapshot-series")["snapshots"]
    metrics = _member(receipt, "metric-dataset")["samples"]
    lifecycle = [
        event
        for event in trace["events"]
        if event["ordering_key"]["phase"] == "transition"
        and event["operation"].startswith("game.effect.")
    ]
    assert len(lifecycle) == 4
    apply_event, *children = lifecycle
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    apply_operation = operations[apply_event["operation"]]
    periodic = apply_operation["extensions"]["game.effect.periodic"]
    timing = periodic["timing"]
    independently_derived_tick_times = list(
        range(timing["period"], timing["duration"], timing["period"])
    )
    assert timing["tick_times"] == independently_derived_tick_times == [1, 2]
    assert timing["expiry_time"] == timing["duration"] == 3

    evaluation = apply_event["formula_evaluations"][0]
    binding = next(
        row
        for row in rir["formula_bindings"]
        if row["identity"] == evaluation["binding_identity"]
    )
    formula = next(
        row
        for row in rir["formulas"]
        if row["identity"] == evaluation["formula"]["identity"]
    )
    assert binding["site"] == {
        "kind": "operation-slot",
        "operation": evaluation["operation"],
        "slot": evaluation["slot"],
        "context": evaluation["context"],
        "identity": evaluation["evaluation_site_identity"],
    }
    assert evaluation["frame_identity"] == apply_event["snapshot_before_identity"]
    magnitude = _reference_evaluate_formula_document(formula, evaluation["arguments"])
    assert magnitude == evaluation["result"] == 15

    policy = periodic["magnitude"]["policy"]
    expected_schedule = [
        (logical_time, f"game.effect.tick-{policy}-periodic-v1")
        for logical_time in independently_derived_tick_times
    ] + [(timing["expiry_time"], "game.effect.expire-periodic-v1")]
    assert [
        (row["ordering_key"]["logical_time"], row["operation"]["id"])
        for row in apply_event["schedules"]
    ] == expected_schedule
    for scheduled, child in zip(apply_event["schedules"], children, strict=True):
        assert child["event_id"] == scheduled["event_id"]
        assert child["parent_event_id"] == apply_event["event_id"]
        assert child["schedule_call_site_identity"] == scheduled["call_site_identity"]
        assert child["ordering_key"] == scheduled["ordering_key"]
        assert child["operation"] == scheduled["operation"]["id"]

    reference_state = {row["name"]: row["value"] for row in apply_event["state_before"]}
    instance = apply_event["rng_draws"][0]
    instance_contract = periodic["instance"]
    assert instance["stream"] == instance_contract["stream"]
    assert (
        instance_contract["minimum"]
        <= instance["value"]
        <= instance_contract["maximum"]
    )
    reference_state["effect_active"] = 1
    reference_state["effect_instance_id"] = instance["value"]
    assert apply_event["state_after"] == [
        {"name": name, "value": value}
        for name, value in sorted(reference_state.items())
    ]
    for child in children:
        assert child["state_before"] == [
            {"name": name, "value": value}
            for name, value in sorted(reference_state.items())
        ]
        if child["operation"] == f"game.effect.tick-{policy}-periodic-v1":
            reference_state["target_health"] -= magnitude
        else:
            assert child["operation"] == "game.effect.expire-periodic-v1"
            reference_state["effect_active"] = 0
        assert child["state_after"] == [
            {"name": name, "value": value}
            for name, value in sorted(reference_state.items())
        ]

    assert snapshots[0]["snapshot_identity"] == apply_event["snapshot_before_identity"]
    assert snapshots[0]["values"] == apply_event["state_before"]
    lifecycle_snapshots = {
        row["event_id"]: row for row in snapshots if row["event_id"] is not None
    }
    for event in lifecycle:
        snapshot = lifecycle_snapshots[event["event_id"]]
        assert snapshot["snapshot_identity"] == event["snapshot_after_identity"]
        assert snapshot["values"] == event["state_after"]
    assert {sample["member"]: sample["value"] for sample in metrics} == reference_state


@pytest.mark.parametrize("mutation", ("result", "omission", "arguments"))
def test_periodic_formula_evidence_rejects_coherent_semantic_mutation(
    tmp_path, run_cli, mutation
):
    specification, _build_receipt = _write_built_periodic_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    evaluation = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(evaluation, experiment_runtime_module.EvaluationArtifacts)
    values = {
        name: deepcopy(member.value) for name, member in evaluation.members.items()
    }
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    trace = values["event-trace"]
    snapshots = values["snapshot-series"]
    dataset = values["metric-dataset"]
    events = trace["events"]
    forged_event = next(event for event in events if event["formula_evaluations"])
    forged = forged_event["formula_evaluations"][0]
    if mutation == "result":
        forged["result"] += 1
    elif mutation == "omission":
        forged_event["formula_evaluations"] = []
    else:
        forged["arguments"][0]["value"] -= 1
        formula = next(
            row
            for row in checked.rir["formulas"]
            if row["identity"] == forged["formula"]["identity"]
        )
        forged["result"] = _reference_evaluate_formula_document(
            formula, forged["arguments"]
        )

    journal = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["committed_trace"]
    snapshot_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "snapshot_identity"
    ]
    trace_prefix = experiment_runtime_module._empty_runtime_journal_identity(journal)
    previous_snapshot = snapshots["snapshots"][0]
    snapshot_identity_changes = {}
    for event, snapshot in zip(events, snapshots["snapshots"][1:], strict=True):
        old_identity = snapshot["snapshot_identity"]
        event["snapshot_before_identity"] = previous_snapshot["snapshot_identity"]
        trace_prefix = experiment_runtime_module._extend_runtime_journal_identity(
            journal,
            trace_prefix,
            experiment_runtime_module._committed_event_projection(event),
        )
        snapshot["continuation"]["committed_trace"]["prefix_identity"] = trace_prefix
        snapshot["snapshot_identity"] = (
            experiment_runtime_module._projected_runtime_identity(
                snapshot_contract,
                {
                    "experiment_identity": checked.content_identity,
                    "scenario_id": snapshot["scenario"],
                    "index": snapshot["index"],
                    "logical_time": snapshot["logical_time"],
                    "event_id": snapshot["event_id"],
                    "values": snapshot["values"],
                    "continuation": snapshot["continuation"],
                },
            )
        )
        event["snapshot_after_identity"] = snapshot["snapshot_identity"]
        snapshot_identity_changes[old_identity] = snapshot["snapshot_identity"]
        previous_snapshot = snapshot

    final_snapshot_identity = snapshots["snapshots"][-1]["snapshot_identity"]
    events_by_id = {event["event_id"]: event for event in events}
    for status in trace["terminal_statuses"]:
        status["terminal_snapshot_identity"] = events_by_id[
            status["terminal_event_id"]
        ]["snapshot_after_identity"]
        status["final_snapshot_identity"] = final_snapshot_identity
    for sample in dataset["samples"]:
        sample["snapshot_identity"] = snapshot_identity_changes.get(
            sample["snapshot_identity"], sample["snapshot_identity"]
        )

    def reidentify(kind):
        payload = {
            key: value
            for key, value in values[kind].items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
        values[kind] = experiment_runtime_module._artifact(checked, kind, payload).value

    reidentify("event-trace")
    values["snapshot-series"]["event_trace_identity"] = values["event-trace"][
        "content_identity"
    ]
    reidentify("snapshot-series")
    reidentify("metric-dataset")
    primary = values["evaluation-run"]
    primary["event_trace_identity"] = values["event-trace"]["content_identity"]
    primary["snapshot_series_identity"] = values["snapshot-series"]["content_identity"]
    primary["metric_dataset_identity"] = values["metric-dataset"]["content_identity"]
    primary["terminal_statuses"] = values["event-trace"]["terminal_statuses"]
    reidentify("evaluation-run")

    assert all(
        artifacts_module.verify_artifact(value, checked.language_bundle)
        for value in values.values()
    )
    if mutation == "result":
        assert not experiment_evidence_module.validate_experiment_member(
            checked, "event-trace", values["event-trace"]
        )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked, values
    )


@pytest.mark.parametrize("mutation", ("result", "omission", "arguments"))
def test_periodic_terminal_audit_rejects_coherent_formula_evidence_mutation(
    tmp_path, run_cli, mutation
):
    specification, _build_receipt = _write_built_periodic_experiment(tmp_path, run_cli)
    checked = experiment_admission_module.check_experiment(str(specification))
    assert isinstance(checked, experiment_admission_module.CheckedExperiment)
    rir = deepcopy(checked.rir)
    runtime_profile = next(
        row
        for row in rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    runtime_profile["resource_bounds"]["max_total_events"] = 4
    checked = replace(checked, rir=rir)
    outcome = experiment_runtime_module.evaluate_experiment(checked)
    assert isinstance(outcome, experiment_runtime_module.RuntimeRefusalOutcome)
    assert outcome.report.diagnostics[0].code == "runtime.event_limit_exceeded"
    members = experiment_evidence_module.runtime_terminal_audit_members(
        checked, outcome
    )
    values = {name: deepcopy(member.value) for name, member in members.items()}
    assert experiment_evidence_module.validate_experiment_artifact_set(checked, values)

    audit = values["runtime-terminal-audit"]
    events = audit["committed_trace_prefix"]
    forged_event = next(event for event in events if event["formula_evaluations"])
    forged = forged_event["formula_evaluations"][0]
    if mutation == "result":
        forged["result"] += 1
    elif mutation == "omission":
        forged_event["formula_evaluations"] = []
    else:
        forged["arguments"][0]["value"] -= 1
        formula = next(
            row
            for row in checked.rir["formulas"]
            if row["identity"] == forged["formula"]["identity"]
        )
        forged["result"] = _reference_evaluate_formula_document(
            formula, forged["arguments"]
        )
    for index, event in enumerate(events[:-1]):
        replacement = content_identity(
            "forged-intermediate-snapshot-v1",
            {"event_id": event["event_id"], "index": event["index"]},
        )
        event["snapshot_after_identity"] = replacement
        events[index + 1]["snapshot_before_identity"] = replacement

    journal = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["committed_trace"]
    trace_prefix = experiment_runtime_module._empty_runtime_journal_identity(journal)
    for event in events:
        trace_prefix = experiment_runtime_module._extend_runtime_journal_identity(
            journal,
            trace_prefix,
            experiment_runtime_module._committed_event_projection(event),
        )
    last_snapshot = audit["last_snapshot_record"]
    last_snapshot["continuation"]["committed_trace"]["prefix_identity"] = trace_prefix
    snapshot_contract = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "snapshot_identity"
    ]
    last_snapshot["snapshot_identity"] = (
        experiment_runtime_module._projected_runtime_identity(
            snapshot_contract,
            {
                "experiment_identity": checked.content_identity,
                "scenario_id": last_snapshot["scenario"],
                "index": last_snapshot["index"],
                "logical_time": last_snapshot["logical_time"],
                "event_id": last_snapshot["event_id"],
                "values": last_snapshot["values"],
                "continuation": last_snapshot["continuation"],
            },
        )
    )
    events[-1]["snapshot_after_identity"] = last_snapshot["snapshot_identity"]
    audit["last_snapshot_identity"] = last_snapshot["snapshot_identity"]
    audit["refusing_event"]["snapshot_before_identity"] = last_snapshot[
        "snapshot_identity"
    ]
    payload = {
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
    values["runtime-terminal-audit"] = experiment_runtime_module._artifact(
        checked, "runtime-terminal-audit", payload
    ).value

    assert artifacts_module.verify_artifact(
        values["runtime-terminal-audit"], checked.language_bundle
    )
    if mutation == "result":
        assert not experiment_evidence_module.validate_experiment_member(
            checked,
            "runtime-terminal-audit",
            values["runtime-terminal-audit"],
        )
    assert not experiment_evidence_module.validate_experiment_artifact_set(
        checked, values
    )


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
            if numeric_admissions <= 6:
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
        experiment_run_application_module,
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


def test_committed_recovery_requires_semantic_artifact_set_revalidation(
    tmp_path, run_cli, monkeypatch
):
    specification = _write_built_experiment(tmp_path, run_cli)
    out = tmp_path / "semantic-recovery.json"
    key = "8" * 64
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
    first_exit, first_stdout, first_stderr = run_cli(argv, registry=(faulting,))
    assert (first_exit, first_stdout) == (4, "")
    assert json.loads(first_stderr)["error"]["code"] == "internal_error"
    assert not out.exists()

    monkeypatch.setattr(
        experiment_run_application_module,
        "validate_experiment_artifact_set",
        lambda _checked, _artifacts: False,
    )

    def evaluator_must_not_run(_checked):
        raise AssertionError("semantically invalid recovery reran the evaluator")

    monkeypatch.setattr(
        experiment_run_application_module,
        "evaluate_experiment",
        evaluator_must_not_run,
    )
    recovered_exit, recovered_stdout, recovered_stderr = run_cli(
        argv,
        registry=(experiment_command_module.EXPERIMENT_RUN,),
    )

    assert (recovered_exit, recovered_stdout) == (4, "")
    assert json.loads(recovered_stderr)["error"]["code"] == "internal_error"
    assert not out.exists()


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
        experiment_run_application_module,
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
