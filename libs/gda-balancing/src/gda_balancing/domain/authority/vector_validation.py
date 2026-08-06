"""Kernel/LDB conformance-vector structure and execution."""

from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.authority.contract_validation import (
    _exact_path_value,
    _value_matches_contract,
)


_PACKAGE_VECTOR_KIND_MEMBERS = {
    "package-contract": {
        "id",
        "probe_members",
        "required_members",
    },
    "operation-contract": {
        "id",
        "probe_members",
        "required_members",
    },
    "operation-relation": {
        "declaration_extension",
        "declaration_members",
        "id",
        "integer_range_members",
        "operators",
        "policy_authority_path",
        "policy_contract_members",
        "policy_extension",
        "policy_members",
        "probe_members",
        "required_members",
        "schedule_projection_members",
    },
    "runtime-scenario": {
        "expect_members",
        "id",
        "input_members",
        "required_members",
        "rng_draw_members",
        "state_value_members",
    },
    "value-program": {
        "expect_members",
        "id",
        "input_members",
        "instruction_nodes",
        "required_members",
    },
    "scheduler-scenario": {
        "event_members",
        "expect_members",
        "id",
        "input_members",
        "mutation_detectors",
        "observation_members",
        "required_members",
        "state_value_members",
        "target_states",
    },
}


_PACKAGE_VECTOR_CATEGORIES = (
    "positive",
    "negative",
    "boundary",
    "semantic-mutation",
    "dependency",
    "outcome",
    "refusal",
    "deterministic-rng",
    "effects",
    "rollback-replay",
    "resource",
)


def _package_vector_contract_is_closed(contract: Any) -> bool:
    if (
        not isinstance(contract, dict)
        or set(contract)
        != {
            "categories",
            "closed",
            "kinds",
            "operation_probe_roots",
            "package_probe_roots",
        }
        or contract.get("closed") is not True
        or contract.get("categories") != list(_PACKAGE_VECTOR_CATEGORIES)
        or contract.get("operation_probe_roots")
        != [
            "body",
            "default_outcome",
            "effects",
            "extensions",
            "outcomes",
            "refusals",
            "resource_bounds",
        ]
        or contract.get("package_probe_roots")
        != ["capabilities", "dependencies", "exports", "profiles"]
        or not isinstance(contract.get("kinds"), list)
    ):
        return False
    kinds: dict[str, dict[str, Any]] = {}
    for item in contract["kinds"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            kinds[cast(str, item["id"])] = item
    if set(kinds) != set(_PACKAGE_VECTOR_KIND_MEMBERS):
        return False
    expected_members = {
        "package-contract": {
            "category",
            "expect",
            "id",
            "kind",
            "probe",
        },
        "operation-contract": {
            "category",
            "expect",
            "id",
            "kind",
            "operation",
            "probe",
        },
        "operation-relation": {
            "category",
            "id",
            "kind",
            "operation",
            "probe",
            "role",
        },
        "runtime-scenario": {
            "category",
            "expect",
            "id",
            "input",
            "kind",
            "operation",
        },
        "value-program": {
            "category",
            "expect",
            "id",
            "input",
            "kind",
        },
        "scheduler-scenario": {
            "category",
            "detects_mutation",
            "expect",
            "id",
            "input",
            "kind",
        },
    }
    for kind_id, kind in kinds.items():
        if set(kind) != _PACKAGE_VECTOR_KIND_MEMBERS[kind_id] or kind.get(
            "required_members"
        ) != sorted(expected_members[kind_id]):
            return False
    return (
        kinds["package-contract"].get("probe_members") == ["path"]
        and kinds["operation-contract"].get("probe_members") == ["path"]
        and kinds["operation-relation"].get("probe_members")
        == ["left_path", "operator", "right_path", "right_value"]
        and kinds["operation-relation"].get("operators")
        == [
            "canonical-equal",
            "integer-equal",
            "integer-greater-than",
            "integer-less-than-or-equal",
            "integer-range-equal",
            "schedule-projection-equal",
        ]
        and kinds["operation-relation"].get("declaration_extension")
        == "standard.operation-relations"
        and kinds["operation-relation"].get("declaration_members") == ["id", "probe"]
        and kinds["operation-relation"].get("integer_range_members")
        == ["start_path", "stop_path", "step_path"]
        and kinds["operation-relation"].get("policy_authority_path")
        == "language.capabilities"
        and kinds["operation-relation"].get("policy_contract_members")
        == ["expect", "path"]
        and kinds["operation-relation"].get("policy_extension")
        == "standard.operation-relation-policy"
        and kinds["operation-relation"].get("policy_members")
        == ["contract", "operation", "relations"]
        and kinds["operation-relation"].get("schedule_projection_members")
        == ["logical_time", "operation"]
        and kinds["runtime-scenario"].get("input_members")
        == ["seed", "state_names", "values"]
        and kinds["runtime-scenario"].get("expect_members")
        == ["outcome", "rng_draws", "state_after"]
        and kinds["runtime-scenario"].get("rng_draw_members")
        == ["candidate_hex", "index", "stream", "value"]
        and kinds["runtime-scenario"].get("state_value_members") == ["name", "value"]
        and kinds["value-program"].get("input_members")
        == [
            "cache",
            "evaluations",
            "instructions",
            "numeric",
            "operands",
            "resource_limit",
            "result",
            "site",
        ]
        and kinds["value-program"].get("expect_members")
        == [
            "cache_entries",
            "charge",
            "outcome",
            "result",
            "result_artifact",
            "signal",
            "site",
        ]
        and kinds["value-program"].get("instruction_nodes")
        == [
            "add",
            "constant",
            "copy",
            "if",
            "maximum",
            "multiply",
            "subtract",
        ]
        and kinds["scheduler-scenario"].get("input_members")
        == ["events", "initial_states", "terminal_condition"]
        and kinds["scheduler-scenario"].get("expect_members")
        == [
            "event_order",
            "observations",
            "outcome",
            "signal",
            "terminal_reason",
            "terminal_states",
        ]
        and kinds["scheduler-scenario"].get("mutation_detectors")
        == [
            "backward-scheduling",
            "host-assigned-ordering",
            "omitted-key",
            "pre-commit-visibility",
            "scenario-as-timestep",
        ]
        and kinds["scheduler-scenario"].get("event_members")
        == [
            "cancel_requested",
            "enqueue_sequence",
            "id",
            "logical_time",
            "parent_id",
            "phase",
            "priority",
            "scenario",
            "state_delta",
            "status",
        ]
        and kinds["scheduler-scenario"].get("observation_members")
        == ["event_id", "scenario", "state_after", "state_before"]
        and kinds["scheduler-scenario"].get("state_value_members")
        == ["scenario", "value"]
        and kinds["scheduler-scenario"].get("target_states")
        == ["active", "canceled", "completed", "pending", "provisional", "unknown"]
    )


def _signed_int64(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and -(2**63) <= value <= 2**63 - 1
    )


def _value_program_instruction_is_closed(
    row: Any,
    allowed_nodes: set[str],
) -> bool:
    if (
        not isinstance(row, dict)
        or set(row) != {"evaluation_site_identity", "instruction"}
        or not isinstance(row.get("evaluation_site_identity"), str)
        or not row["evaluation_site_identity"]
        or not isinstance(row.get("instruction"), dict)
    ):
        return False
    instruction = row["instruction"]
    node = instruction.get("node")
    members = {
        "constant": {"node", "target", "literal"},
        "copy": {"node", "target", "value"},
        "add": {"node", "target", "left", "right"},
        "maximum": {"node", "target", "left", "right"},
        "multiply": {"node", "target", "left", "right"},
        "subtract": {"node", "target", "left", "right"},
        "if": {
            "node",
            "target",
            "condition",
            "when_true",
            "when_false",
        },
    }
    required = members.get(node) if isinstance(node, str) else None
    return (
        isinstance(required, set)
        and node in allowed_nodes
        and set(instruction) == required
        and isinstance(instruction.get("target"), str)
        and bool(instruction["target"])
        and (
            _signed_int64(instruction.get("literal"))
            if node == "constant"
            else all(
                isinstance(instruction.get(member), str) and bool(instruction[member])
                for member in required - {"node", "target"}
            )
        )
    )


def _scheduler_scenario_vector_is_closed(
    vector: dict[str, Any], kind: dict[str, Any], phase_inventory: set[str]
) -> bool:
    inp = vector.get("input")
    expect = vector.get("expect")
    detects_mutation = vector.get("detects_mutation")
    if (
        not isinstance(inp, dict)
        or set(inp) != set(kind["input_members"])
        or not isinstance(expect, dict)
        or set(expect) != set(kind["expect_members"])
        or (
            detects_mutation not in kind["mutation_detectors"]
            if vector.get("category") == "semantic-mutation"
            else detects_mutation is not None
        )
        or inp.get("terminal_condition") not in {"event-count-reached", "queue-drained"}
        or not isinstance(inp.get("initial_states"), list)
        or not inp["initial_states"]
        or not isinstance(inp.get("events"), list)
        or not inp["events"]
    ):
        return False
    initial_states = inp["initial_states"]
    scenarios = [row.get("scenario") for row in initial_states if isinstance(row, dict)]
    if (
        len(scenarios) != len(initial_states)
        or len(scenarios) != len(set(scenarios))
        or not all(
            isinstance(row, dict)
            and set(row) == set(kind["state_value_members"])
            and isinstance(row.get("scenario"), str)
            and bool(row["scenario"])
            and _signed_int64(row.get("value"))
            for row in initial_states
        )
    ):
        return False
    events = inp["events"]
    event_ids = [row.get("id") for row in events if isinstance(row, dict)]
    if (
        len(event_ids) != len(events)
        or len(event_ids) != len(set(event_ids))
        or not all(
            isinstance(row, dict)
            and set(row) == set(kind["event_members"])
            and isinstance(row.get("id"), str)
            and bool(row["id"])
            and row.get("scenario") in scenarios
            and _signed_int64(row.get("logical_time"))
            and isinstance(row.get("phase"), str)
            and row["phase"] in phase_inventory
            and _signed_int64(row.get("priority"))
            and isinstance(row.get("enqueue_sequence"), int)
            and not isinstance(row["enqueue_sequence"], bool)
            and row["enqueue_sequence"] >= 0
            and _signed_int64(row.get("state_delta"))
            and isinstance(row.get("cancel_requested"), bool)
            and row.get("status") in kind["target_states"]
            and (
                row.get("parent_id") is None
                or (
                    isinstance(row["parent_id"], str)
                    and row["parent_id"] in event_ids
                    and row["parent_id"] != row["id"]
                )
            )
            for row in events
        )
    ):
        return False
    observations = expect.get("observations")
    terminal_states = expect.get("terminal_states")
    return (
        expect.get("outcome") in {"admitted", "refused"}
        and (expect.get("signal") is None or isinstance(expect.get("signal"), str))
        and expect.get("terminal_reason")
        in {None, "event-count-reached", "queue-drained"}
        and isinstance(expect.get("event_order"), list)
        and all(event_id in event_ids for event_id in expect["event_order"])
        and isinstance(observations, list)
        and all(
            isinstance(row, dict)
            and set(row) == set(kind["observation_members"])
            and row.get("event_id") in event_ids
            and row.get("scenario") in scenarios
            and _signed_int64(row.get("state_before"))
            and _signed_int64(row.get("state_after"))
            for row in observations
        )
        and isinstance(terminal_states, list)
        and [row.get("scenario") for row in terminal_states] == scenarios
        and all(
            isinstance(row, dict)
            and set(row) == set(kind["state_value_members"])
            and _signed_int64(row.get("value"))
            for row in terminal_states
        )
    )


def _package_evidence_vector_header_is_closed(
    vector: dict[str, Any],
    contract: Any,
) -> bool:
    if not _package_vector_contract_is_closed(contract):
        return False
    kinds = {
        item["id"]: item
        for item in contract["kinds"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    kind = kinds.get(vector.get("kind"))
    return (
        isinstance(kind, dict)
        and set(vector) == set(kind["required_members"])
        and isinstance(vector.get("id"), str)
        and bool(vector["id"])
        and vector.get("category") in contract["categories"]
    )


def _fact_schemas(
    meta_format: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    fact_contract = meta_format.get("fact")
    if not isinstance(fact_contract, dict):
        return {}
    schemas = fact_contract.get("schemas")
    field_contracts = fact_contract.get("field_contracts")
    if not isinstance(schemas, list) or not isinstance(field_contracts, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            return {}
        kind = schema.get("kind")
        contract_name = schema.get("field_contract")
        fields = field_contracts.get(contract_name)
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(contract_name, str)
            or not isinstance(fields, dict)
            or not all(isinstance(field, str) and field for field in fields)
            or kind in result
        ):
            return {}
        result[kind] = fields
    return result


def _fact_is_closed(
    fact: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    fact_contract = meta_format.get("fact")
    schemas = _fact_schemas(meta_format)
    if not isinstance(fact_contract, dict) or not schemas or not isinstance(fact, dict):
        return False
    required = fact_contract.get("required_members")
    kind = fact.get("kind")
    fields = fact.get("fields")
    return (
        fact_contract.get("closed") is True
        and isinstance(required, list)
        and set(fact) == set(required)
        and isinstance(kind, str)
        and kind in schemas
        and isinstance(fields, dict)
        and set(fields) == set(schemas[kind])
        and all(isinstance(name, str) and name for name in fields)
        and all(
            _value_matches_contract(fields[name], schemas[kind][name], language_bundle)
            for name in fields
        )
    )


def _reason_is_closed(
    reason: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    contract = meta_format.get("diagnostic_reason")
    if not isinstance(contract, dict) or not isinstance(reason, dict):
        return False
    required = contract.get("required_members")
    optional = contract.get("optional_members", [])
    member_types = contract.get("member_types")
    schemas = contract.get("predicate_schemas")
    predicate = reason.get("predicate")
    if (
        contract.get("closed") is not True
        or contract.get("scalar_equality") != "type-and-canonical-value"
        or not isinstance(required, list)
        or not isinstance(optional, list)
        or not set(required) <= set(reason)
        or not set(reason) <= set(required) | set(optional)
        or not isinstance(member_types, dict)
        or set(member_types) != (set(required) | set(optional)) - {"predicate"}
        or not all(
            _value_matches_contract(reason[name], member_types[name], language_bundle)
            for name in set(reason) - {"predicate"}
        )
        or not isinstance(predicate, dict)
        or not isinstance(schemas, list)
    ):
        return False
    operation = predicate.get("operation")
    schema = next(
        (
            item
            for item in schemas
            if isinstance(item, dict) and item.get("operation") == operation
        ),
        None,
    )
    if not isinstance(schema, dict):
        return False
    predicate_required = schema.get("required_members")
    optional = schema.get("optional_members")
    predicate_types = schema.get("member_types")
    input_members = schema.get("input_members")
    input_types = schema.get("input_member_types")
    return (
        isinstance(predicate_required, list)
        and isinstance(optional, list)
        and isinstance(predicate_types, dict)
        and isinstance(input_members, list)
        and isinstance(input_types, dict)
        and set(input_types) == set(input_members)
        and set(predicate_required) <= set(predicate)
        and set(predicate) <= set(predicate_required) | set(optional)
        and set(predicate_types) == set(predicate_required) | set(optional)
        and all(
            _value_matches_contract(
                predicate[name], predicate_types[name], language_bundle
            )
            for name in predicate
        )
        and _reason_operands_are_closed(predicate, language_bundle)
    )


def _reason_operands_are_closed(
    predicate: dict[str, Any], language_bundle: dict[str, Any]
) -> bool:
    operation = predicate.get("operation")
    if operation == "not-member":
        declared, inventory = _exact_path_value(
            language_bundle, predicate.get("inventory_path")
        )
        if not declared or not isinstance(inventory, list) or not inventory:
            return False
        member_field = predicate.get("member_field")
        if member_field is None:
            values = inventory
        elif isinstance(member_field, str) and member_field:
            if not all(
                isinstance(item, dict) and member_field in item for item in inventory
            ):
                return False
            values = [item[member_field] for item in inventory]
        else:
            return False
        return all(
            _value_matches_contract(
                value, {"type": "canonical-scalar"}, language_bundle
            )
            for value in values
        )
    if operation == "greater-than":
        declared, limit = _exact_path_value(
            language_bundle, predicate.get("limit_path")
        )
        return declared and _value_matches_contract(
            limit, {"type": "signed-int64"}, language_bundle
        )
    return operation in {"has-duplicate", "invalid-interval", "not-equal"}


def _model_program_vector_is_closed(
    vector: dict[str, Any],
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    contract = meta_format.get("model_program_vector")
    if not isinstance(contract, dict):
        return False
    required = contract.get("required_members")
    categories = contract.get("categories")
    category_outcomes = contract.get("category_outcomes")
    category_relations = contract.get("category_relations")
    fixture_modes = contract.get("fixture_modes")
    expect_members = contract.get("expect_members")
    diagnostic_members = contract.get("diagnostic_members")
    lock_members = contract.get("lock_oracle_members")
    relation_kinds = contract.get("relation_kinds")
    category = vector.get("category")
    fixture = vector.get("source_fixture")
    expect = vector.get("expect")
    if (
        not isinstance(required, list)
        or set(vector) != set(required)
        or not isinstance(vector.get("id"), str)
        or not vector["id"]
        or not isinstance(categories, list)
        or category not in categories
        or not isinstance(category_outcomes, dict)
        or not isinstance(category_relations, dict)
        or not isinstance(fixture_modes, dict)
        or not isinstance(expect_members, list)
        or diagnostic_members != ["code", "stage", "pointer"]
        or not isinstance(lock_members, list)
        or not isinstance(relation_kinds, list)
        or not isinstance(fixture, dict)
        or not isinstance(expect, dict)
        or set(expect) != set(expect_members)
    ):
        return False
    mode = fixture.get("mode")
    mode_contract = fixture_modes.get(mode) if isinstance(mode, str) else None
    if (
        not isinstance(mode_contract, dict)
        or not isinstance(mode_contract.get("required_members"), list)
        or set(fixture) != set(mode_contract["required_members"])
        or not isinstance(fixture.get("source"), dict)
    ):
        return False
    if mode == "indexed-repeat":
        collection_path = fixture.get("collection_path")
        count_path = fixture.get("count_resource_path")
        count_offset = fixture.get("count_offset")
        template = fixture.get("template")
        index_member = fixture.get("index_member")
        index_prefix = fixture.get("index_prefix")
        index_width = fixture.get("index_width")
        if (
            not isinstance(collection_path, list)
            or not collection_path
            or not all(isinstance(item, str) and item for item in collection_path)
            or not isinstance(count_path, str)
            or not count_path
            or count_offset not in (0, 1)
            or not isinstance(template, dict)
            or not isinstance(index_member, str)
            or not index_member
            or index_member not in template
            or not isinstance(index_prefix, str)
            or not index_prefix
            or not isinstance(index_width, int)
            or isinstance(index_width, bool)
            or not 1 <= index_width <= 18
            or fixture.get("index_encoding") != mode_contract.get("index_encoding")
        ):
            return False
        current: Any = fixture["source"]
        for segment in collection_path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            elif (
                isinstance(current, list)
                and segment.isdecimal()
                and int(segment) < len(current)
            ):
                current = current[int(segment)]
            else:
                return False
        declared, count = _exact_path_value(language_bundle, count_path)
        if (
            not isinstance(current, list)
            or current
            or not declared
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
        ):
            return False
    elif mode != "literal":
        return False
    outcome = expect.get("outcome")
    allowed_outcomes = category_outcomes.get(category)
    diagnostics = expect.get("diagnostics")
    semantic_artifacts = expect.get("semantic_artifacts")
    declaration_count = expect.get("declaration_count")
    relation = expect.get("relation")
    if (
        not isinstance(allowed_outcomes, list)
        or outcome not in allowed_outcomes
        or not isinstance(diagnostics, list)
        or not all(
            isinstance(item, dict)
            and set(item) == {"code", "stage", "pointer"}
            and isinstance(item["code"], str)
            and item["code"]
            and isinstance(item["stage"], str)
            and item["stage"]
            and isinstance(item["pointer"], str)
            and (not item["pointer"] or item["pointer"].startswith("/"))
            for item in diagnostics
        )
        or not isinstance(semantic_artifacts, bool)
        or not isinstance(declaration_count, int)
        or isinstance(declaration_count, bool)
        or declaration_count < 0
        or not isinstance(relation, dict)
        or set(relation) != {"kind", "reference"}
        or relation.get("kind") not in relation_kinds
        or relation.get("kind") not in category_relations.get(category, [])
    ):
        return False
    catalog = {
        (item.get("code"), item.get("stage"))
        for item in cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
        if isinstance(item, dict)
    }
    if any((item["code"], item["stage"]) not in catalog for item in diagnostics):
        return False
    reference = relation.get("reference")
    if relation["kind"] == "independent":
        if reference is not None:
            return False
    elif not isinstance(reference, str) or not reference:
        return False
    lock_oracle = expect.get("lock_oracle")
    rir_identity = expect.get("rir_identity")
    debug_map_identity = expect.get("debug_map_identity")
    if outcome == "admitted":
        return (
            semantic_artifacts is True
            and not diagnostics
            and declaration_count > 0
            and isinstance(rir_identity, str)
            and bool(rir_identity)
            and isinstance(debug_map_identity, str)
            and bool(debug_map_identity)
            and isinstance(lock_oracle, dict)
            and set(lock_oracle) == set(lock_members)
        )
    return (
        semantic_artifacts is False
        and bool(diagnostics)
        and declaration_count == 0
        and rir_identity is None
        and debug_map_identity is None
        and lock_oracle is None
    )


def _vector_header_is_closed(
    vector: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    if not isinstance(vector, dict):
        return False
    if "rule" in vector:
        invocation = vector.get("input")
        rule_contract = meta_format.get("rule")
        phases = (
            rule_contract.get("phases") if isinstance(rule_contract, dict) else None
        )
        return (
            set(vector) == {"expect", "id", "input", "rule"}
            and isinstance(vector.get("id"), str)
            and bool(vector["id"])
            and isinstance(vector.get("rule"), str)
            and bool(vector["rule"])
            and isinstance(invocation, dict)
            and set(invocation) == {"facts", "judgment", "phase"}
            and isinstance(invocation.get("judgment"), str)
            and bool(invocation["judgment"])
            and isinstance(phases, list)
            and invocation.get("phase") in phases
            and isinstance(invocation.get("facts"), list)
            and all(
                _fact_is_closed(fact, meta_format, language_bundle)
                for fact in invocation["facts"]
            )
            and _fact_is_closed(vector.get("expect"), meta_format, language_bundle)
        )
    if "diagnostic" in vector:
        contract = meta_format.get("diagnostic_reason")
        if not isinstance(contract, dict):
            return False
        required = contract.get("vector_required_members")
        member_types = contract.get("vector_member_types")
        return (
            isinstance(required, list)
            and set(vector) == set(required)
            and isinstance(member_types, dict)
            and set(member_types) == set(required) - {"input"}
            and all(
                _value_matches_contract(
                    vector[name], member_types[name], language_bundle
                )
                for name in member_types
            )
            and isinstance(vector.get("input"), dict)
        )
    if "kind" in vector:
        return _package_evidence_vector_header_is_closed(
            vector, meta_format.get("package_vector")
        )
    if "category" in vector:
        return _model_program_vector_is_closed(vector, meta_format, language_bundle)
    return False


def _execute_rule_vector(
    rules: list[dict[str, Any]],
    vector: dict[str, Any],
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute the Kernel's closed fact/select/bind/substitute meta-format."""
    if set(vector) != {"expect", "id", "input", "rule"}:
        return None
    invocation = vector.get("input")
    if not isinstance(invocation, dict) or set(invocation) != {
        "facts",
        "judgment",
        "phase",
    }:
        return None
    judgment = invocation.get("judgment")
    phase = invocation.get("phase")
    facts = invocation.get("facts")
    if (
        not isinstance(judgment, str)
        or not isinstance(phase, str)
        or not isinstance(facts, list)
        or not all(
            _fact_is_closed(fact, meta_format, language_bundle) for fact in facts
        )
    ):
        return None

    candidates: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda item: str(item.get("id", ""))):
        premises = rule.get("premises")
        if (
            rule.get("phase") != phase
            or rule.get("judgment") != judgment
            or not isinstance(premises, list)
        ):
            continue
        if len(premises) != len(facts):
            continue
        if all(
            isinstance(premise, dict)
            and isinstance(fact, dict)
            and premise.get("fact_kind") == fact.get("kind")
            for premise, fact in zip(premises, facts, strict=True)
        ):
            candidates.append(rule)
    if len(candidates) != 1 or candidates[0].get("id") != vector.get("rule"):
        return None

    selected = candidates[0]
    bindings: dict[str, Any] = {}
    for premise, fact in zip(selected["premises"], facts, strict=True):
        fields = fact.get("fields")
        bind = premise.get("bind")
        if not isinstance(fields, dict) or not isinstance(bind, dict):
            return None
        for variable, field_name in bind.items():
            if not isinstance(variable, str) or field_name not in fields:
                return None
            value = fields[field_name]
            if variable in bindings and bindings[variable] != value:
                return None
            bindings[variable] = value

    conclusion = selected.get("conclusion")
    if not isinstance(conclusion, dict) or not isinstance(
        conclusion.get("fields"), dict
    ):
        return None
    output_fields: dict[str, Any] = {}
    for name, term in conclusion["fields"].items():
        if not isinstance(name, str) or not isinstance(term, dict):
            return None
        if term.get("tag") == "literal" and set(term) == {"tag", "value"}:
            output_fields[name] = term["value"]
        elif term.get("tag") == "variable" and set(term) == {"tag", "name"}:
            variable = term["name"]
            if not isinstance(variable, str) or variable not in bindings:
                return None
            output_fields[name] = bindings[variable]
        else:
            return None
    output = {"kind": conclusion.get("fact_kind"), "fields": output_fields}
    return output if _fact_is_closed(output, meta_format, language_bundle) else None


def _rule_is_closed(
    rule: Any,
    meta_format: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    contract = meta_format.get("rule")
    term_contract = meta_format.get("term")
    fact_schemas = _fact_schemas(meta_format)
    if (
        not isinstance(contract, dict)
        or not isinstance(rule, dict)
        or contract.get("closed") is not True
        or not isinstance(contract.get("required_members"), list)
        or set(rule) != set(contract["required_members"])
        or rule.get("phase") not in contract.get("phases", [])
        or not isinstance(rule.get("id"), str)
        or not rule.get("id")
        or not isinstance(rule.get("judgment"), str)
        or not rule.get("judgment")
        or not fact_schemas
    ):
        return False
    premises = rule.get("premises")
    conclusion = rule.get("conclusion")
    premise_members = contract.get("premise_required_members")
    conclusion_members = contract.get("conclusion_required_members")
    if not isinstance(premises, list) or not isinstance(premise_members, list):
        return False
    for item in premises:
        if not isinstance(item, dict):
            return False
        fact_kind = item.get("fact_kind")
        bindings = item.get("bind")
        if (
            set(item) != set(premise_members)
            or not isinstance(fact_kind, str)
            or fact_kind not in fact_schemas
            or not isinstance(bindings, dict)
            or not all(
                isinstance(variable, str)
                and variable
                and isinstance(field, str)
                and field in fact_schemas[fact_kind]
                for variable, field in bindings.items()
            )
        ):
            return False
    conclusion_kind = (
        conclusion.get("fact_kind") if isinstance(conclusion, dict) else None
    )
    if (
        not isinstance(conclusion, dict)
        or not isinstance(conclusion_members, list)
        or set(conclusion) != set(conclusion_members)
        or not isinstance(conclusion_kind, str)
        or conclusion_kind not in fact_schemas
    ):
        return False
    fields = conclusion.get("fields")
    if (
        not isinstance(fields, dict)
        or set(fields) != set(fact_schemas[conclusion_kind])
        or not isinstance(term_contract, dict)
        or not isinstance(term_contract.get("constructors"), list)
    ):
        return False
    constructors = {
        str(item.get("tag")): item
        for item in term_contract["constructors"]
        if isinstance(item, dict)
    }
    for term in fields.values():
        if not isinstance(term, dict):
            return False
        tag = term.get("tag")
        constructor = constructors.get(tag) if isinstance(tag, str) else None
        if not isinstance(constructor, dict):
            return False
        required_members = constructor.get("required_members")
        member_types = constructor.get("member_types")
        if (
            not isinstance(required_members, list)
            or set(term) != set(required_members)
            or not isinstance(member_types, dict)
            or set(member_types) != set(required_members)
            or not all(
                _value_matches_contract(term[name], member_types[name], language_bundle)
                for name in term
            )
        ):
            return False
    return True


def _execute_reason_vector(
    language_bundle: dict[str, Any],
    reason: dict[str, Any] | None,
    vector: dict[str, Any],
    meta_format: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute one closed post-admission reason predicate from LDB data."""
    reason_contract = meta_format.get("diagnostic_reason")
    if not isinstance(reason_contract, dict):
        return None
    required = reason_contract.get("vector_required_members")
    member_types = reason_contract.get("vector_member_types")
    if (
        not isinstance(required, list)
        or set(vector) != set(required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required) - {"input"}
        or not all(
            _value_matches_contract(vector[name], member_types[name], language_bundle)
            for name in member_types
        )
        or not _reason_is_closed(reason, meta_format, language_bundle)
        or not isinstance(vector.get("input"), dict)
    ):
        return None
    assert reason is not None
    if (
        vector["reason"] != reason.get("id")
        or vector["diagnostic"] != reason.get("diagnostic")
        or vector["stage"] != reason.get("stage")
    ):
        return None
    predicate = reason.get("predicate")
    if not isinstance(predicate, dict):
        return None
    operation = predicate.get("operation")
    inp = cast(dict[str, Any], vector["input"])
    predicate_schema = next(
        (
            item
            for item in cast(list[dict[str, Any]], reason_contract["predicate_schemas"])
            if item.get("operation") == operation
        ),
        None,
    )
    input_types = (
        predicate_schema.get("input_member_types")
        if isinstance(predicate_schema, dict)
        else None
    )
    if (
        not isinstance(predicate_schema, dict)
        or set(inp) != set(cast(list[str], predicate_schema.get("input_members", [])))
        or not isinstance(input_types, dict)
        or set(inp) != set(input_types)
        or not all(
            _value_matches_contract(inp[name], input_types[name], language_bundle)
            for name in inp
        )
    ):
        return None
    matched = False
    if operation == "not-member":
        inventory = _resolve_path(language_bundle, predicate.get("inventory_path"))
        if not isinstance(inventory, list):
            return None
        member_field = predicate.get("member_field")
        values = [
            item.get(member_field)
            if isinstance(member_field, str) and isinstance(item, dict)
            else item
            for item in inventory
        ]
        matched = _canonical_scalar_key(inp.get("value")) not in {
            _canonical_scalar_key(item) for item in values
        }
    elif operation == "has-duplicate":
        values = inp.get("values")
        if not isinstance(values, list):
            return None
        keys = [_canonical_scalar_key(item) for item in values]
        matched = len(keys) != len(set(keys))
    elif operation == "greater-than":
        limit = _resolve_path(language_bundle, predicate.get("limit_path"))
        value = inp.get("value")
        if not isinstance(limit, int) or not isinstance(value, int):
            return None
        matched = value > limit
    elif operation == "invalid-interval":
        minimum = inp.get("minimum")
        maximum = inp.get("maximum")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
        ):
            return None
        matched = minimum > maximum
    elif operation == "not-equal":
        try:
            matched = canonical_bytes(
                cast(JsonValue, inp.get("actual"))
            ) != canonical_bytes(cast(JsonValue, inp.get("expected")))
        except (TypeError, ValueError):
            return None
    return {
        "code": reason.get("diagnostic"),
        "matched": matched,
        "stage": reason.get("stage"),
    }


def _canonical_scalar_key(value: Any) -> tuple[str, Any]:
    return (
        "null"
        if value is None
        else "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "string",
        value,
    )


def _reason_vectors_cover_operands(
    language_bundle: dict[str, Any],
    reason: dict[str, Any],
    vectors: list[dict[str, Any]],
    meta_format: dict[str, Any],
) -> bool:
    contract = meta_format.get("diagnostic_reason")
    predicate = reason.get("predicate")
    if not isinstance(contract, dict) or not isinstance(predicate, dict):
        return False
    coverage = contract.get("vector_coverage")
    operation = predicate.get("operation")
    if not isinstance(coverage, dict) or not isinstance(operation, str):
        return False
    if not vectors or any(
        not isinstance(vector, dict)
        or not isinstance(vector.get("matched"), bool)
        or not isinstance(vector.get("input"), dict)
        for vector in vectors
    ):
        return False
    outcomes = {vector.get("matched") for vector in vectors}
    if outcomes != {False, True}:
        return False
    if operation == "not-member":
        if coverage.get(operation) != "every-inventory-member-and-one-non-member":
            return False
        inventory = _resolve_path(language_bundle, predicate.get("inventory_path"))
        if not isinstance(inventory, list):
            return False
        member_field = predicate.get("member_field")
        if member_field is None:
            values = inventory
        elif (
            isinstance(member_field, str)
            and member_field
            and all(
                isinstance(item, dict) and member_field in item for item in inventory
            )
        ):
            values = [item[member_field] for item in inventory]
        else:
            return False
        if not all(
            _value_matches_contract(
                value, {"type": "canonical-scalar"}, language_bundle
            )
            for value in values
        ):
            return False
        if not all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get("value"),
                {"type": "canonical-scalar"},
                language_bundle,
            )
            for vector in vectors
        ):
            return False
        nonmatches = {
            _canonical_scalar_key(vector.get("input", {}).get("value"))
            for vector in vectors
            if vector.get("matched") is False and isinstance(vector.get("input"), dict)
        }
        return {_canonical_scalar_key(value) for value in values} <= nonmatches
    if operation == "has-duplicate":
        return coverage.get(operation) == "both-outcomes" and all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get("values"),
                {"type": "scalar-list"},
                language_bundle,
            )
            for vector in vectors
        )
    if operation == "greater-than":
        if coverage.get(operation) != "limit-and-successor":
            return False
        limit = _resolve_path(language_bundle, predicate.get("limit_path"))
        if not isinstance(limit, int) or isinstance(limit, bool) or limit >= 2**63 - 1:
            return False
        if not all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get("value"),
                {"type": "signed-int64"},
                language_bundle,
            )
            for vector in vectors
        ):
            return False
        witnesses = {
            (vector.get("input", {}).get("value"), vector.get("matched"))
            for vector in vectors
            if isinstance(vector.get("input"), dict)
        }
        return {(limit, False), (limit + 1, True)} <= witnesses
    if operation == "invalid-interval":
        if coverage.get(operation) != "both-outcomes":
            return False
        return outcomes == {False, True} and all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get(name),
                {"type": "signed-int64"},
                language_bundle,
            )
            for vector in vectors
            for name in ("minimum", "maximum")
        )
    if operation == "not-equal":
        if coverage.get(operation) != "both-outcomes":
            return False
        return outcomes == {False, True} and all(
            _value_matches_contract(
                cast(dict[str, Any], vector["input"]).get(name),
                {"type": "canonical-value"},
                language_bundle,
            )
            for vector in vectors
            for name in ("actual", "expected")
        )
    return False


def _resolve_path(root: dict[str, Any], dotted: Any) -> Any:
    if not isinstance(dotted, str):
        return None
    value: Any = root
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value
