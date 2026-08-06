"""Package closure, semantic projection, and evidence validation."""

from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)
from gda_balancing.domain.authority.contract_validation import (
    _exact_path_value,
    _path_is_declared,
    _path_values,
    _value_matches_contract,
)
from gda_balancing.domain.authority.vector_validation import (
    _package_vector_contract_is_closed,
    _scheduler_scenario_vector_is_closed,
    _signed_int64,
    _value_program_instruction_is_closed,
)


def _package_is_closed(
    package: dict[str, Any], contract: Any, language_bundle: dict[str, Any]
) -> bool:
    if not isinstance(contract, dict) or contract.get("closed") is not True:
        return False
    required = contract.get("required_members")
    field_types = contract.get("field_types")
    nested_members = contract.get("nested_members")
    nested_types = contract.get("nested_field_types")
    type_export = contract.get("type_export")
    if (
        not isinstance(required, list)
        or set(package) != set(required)
        or not isinstance(field_types, dict)
        or not isinstance(nested_members, dict)
        or not isinstance(nested_types, dict)
        or set(nested_members) != set(nested_types)
        or set(field_types) | set(nested_members) != set(required)
        or set(field_types) & set(nested_members)
        or not all(
            _value_matches_contract(package[name], field_types[name], language_bundle)
            for name in field_types
        )
    ):
        return False
    for name, members in nested_members.items():
        value = package.get(name)
        member_types = nested_types.get(name)
        if (
            not isinstance(value, dict)
            or not isinstance(members, list)
            or set(value) != set(members)
            or not isinstance(member_types, dict)
            or set(member_types) != set(members)
            or not all(
                _value_matches_contract(
                    value[member], member_types[member], language_bundle
                )
                for member in members
            )
        ):
            return False
    exports = package.get("exports")
    exported_types = exports.get("types") if isinstance(exports, dict) else None
    if not isinstance(exported_types, list) or not isinstance(type_export, dict):
        return False
    export_members = type_export.get("required_members")
    export_field_types = type_export.get("field_types")
    return (
        isinstance(export_members, list)
        and isinstance(export_field_types, dict)
        and set(export_field_types) == set(export_members)
        and all(
            isinstance(item, dict)
            and set(item) == set(export_members)
            and all(
                _value_matches_contract(
                    item[member], export_field_types[member], language_bundle
                )
                for member in export_members
            )
            for item in exported_types
        )
    )


def _canonical_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_bytes(cast(JsonValue, left)) == canonical_bytes(
            cast(JsonValue, right)
        )
    except (TypeError, ValueError, UnicodeEncodeError):
        return False


def _operation_relation_is_satisfied(
    operation: dict[str, Any],
    vector: dict[str, Any],
    kind: dict[str, Any],
    roots: list[str],
    runtime_nodes: list[dict[str, Any]],
) -> bool:
    probe = vector.get("probe")
    if not isinstance(probe, dict) or set(probe) != set(kind["probe_members"]):
        return False
    declaration_extension = kind.get("declaration_extension")
    declaration_members = kind.get("declaration_members")
    extensions = operation.get("extensions")
    declarations = (
        extensions.get(declaration_extension)
        if isinstance(extensions, dict) and isinstance(declaration_extension, str)
        else None
    )
    if not isinstance(declaration_members, list) or not isinstance(declarations, list):
        return False
    matches = [
        declaration
        for declaration in declarations
        if isinstance(declaration, dict)
        and set(declaration) == set(declaration_members)
        and declaration.get("id") == vector.get("role")
    ]
    if len(matches) != 1 or not _canonical_equal(probe, matches[0].get("probe")):
        return False
    left_path = probe.get("left_path")
    right_path = probe.get("right_path")
    right_value = probe.get("right_value")
    operator = probe.get("operator")

    def member_path(value: Any) -> list[str] | None:
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(member, str) and member for member in value)
        ):
            return None
        return cast(list[str], value)

    def observed(path: list[str]) -> tuple[bool, Any]:
        current: Any = operation
        for member in path:
            if not isinstance(current, dict) or member not in current:
                return False, None
            current = current[member]
        return True, current

    left_members = member_path(left_path)
    right_members = member_path(right_path) if right_path is not None else None
    if (
        left_members is None
        or left_members[0] not in roots
        or operator not in kind["operators"]
        or (right_members is not None) == (right_value is not None)
    ):
        return False
    declared, left = observed(left_members)
    if not declared:
        return False
    if right_members is not None:
        if right_members[0] not in roots:
            return False
        declared, right = observed(right_members)
        if not declared:
            return False
    else:
        right = right_value
    if operator == "canonical-equal":
        return _canonical_equal(left, right)
    if operator == "schedule-projection-equal":
        projection_members = kind.get("schedule_projection_members")
        schedule_nodes = {
            node.get("id")
            for node in runtime_nodes
            if isinstance(node, dict)
            and isinstance(node.get("semantics"), dict)
            and node["semantics"].get("operator") == "schedule-operation"
        }
        if (
            not isinstance(projection_members, list)
            or not isinstance(left, list)
            or not all(isinstance(instruction, dict) for instruction in left)
        ):
            return False
        projected = [
            {member: instruction[member] for member in projection_members}
            for instruction in left
            if instruction.get("node") in schedule_nodes
            and all(member in instruction for member in projection_members)
        ]
        return _canonical_equal(projected, right)
    if operator == "integer-range-equal":
        range_members = kind.get("integer_range_members")
        if (
            not isinstance(range_members, list)
            or len(range_members) != 3
            or not isinstance(right, dict)
            or set(right) != set(range_members)
            or not isinstance(left, list)
            or not all(_signed_int64(item) for item in left)
        ):
            return False
        range_paths = [member_path(right.get(member)) for member in range_members]
        if any(path is None or path[0] not in roots for path in range_paths):
            return False
        range_values: list[int] = []
        for path in range_paths:
            declared, value = observed(cast(list[str], path))
            if not declared or not _signed_int64(value):
                return False
            range_values.append(cast(int, value))
        start, stop, step = range_values
        if step == 0:
            return False
        expected_length = (
            0
            if (step > 0 and start >= stop) or (step < 0 and start <= stop)
            else (
                (stop - start - 1) // step + 1
                if step > 0
                else (start - stop - 1) // -step + 1
            )
        )
        return len(left) == expected_length and all(
            item == start + index * step for index, item in enumerate(left)
        )
    if not _signed_int64(left) or not _signed_int64(right):
        return False
    return (
        left == right
        if operator == "integer-equal"
        else left > right
        if operator == "integer-greater-than"
        else left <= right
    )


def _package_conformance_vector_set_is_closed(
    vector_set: dict[str, Any],
    contract: Any,
) -> bool:
    expected_members = {
        "artifact_kind",
        "content_identity",
        "package_id",
        "package_version",
        "vector_definitions",
        "vectors",
    }
    fixed_field_types = {
        "artifact_kind": {"const": "package-conformance-vector-set"},
        "content_identity": {"type": "non-empty-string"},
        "vector_definitions": {"type": "list"},
        "vectors": {"type": "string-list"},
    }
    field_types = contract.get("field_types") if isinstance(contract, dict) else None
    coordinate_contracts = (
        [field_types.get("package_id"), field_types.get("package_version")]
        if isinstance(field_types, dict)
        else []
    )
    return (
        isinstance(contract, dict)
        and contract.get("closed") is True
        and contract.get("required_members") == sorted(expected_members)
        and isinstance(field_types, dict)
        and set(field_types) == expected_members
        and all(
            field_types[name] == expected
            for name, expected in fixed_field_types.items()
        )
        and all(
            isinstance(item, dict)
            and item.get("type") == "non-empty-string"
            and isinstance(item.get("pattern"), str)
            and bool(item["pattern"])
            for item in coordinate_contracts
        )
        and set(vector_set) == expected_members
        and vector_set.get("artifact_kind") == "package-conformance-vector-set"
        and all(
            _value_matches_contract(vector_set[name], field_types[name], vector_set)
            for name in expected_members
        )
        and len(vector_set["vectors"]) == len(set(vector_set["vectors"]))
    )


def _package_evidence_vectors_are_closed(
    package: dict[str, Any],
    vector_set: dict[str, Any],
    contract: Any,
    candidate_encoding: Any,
    runtime_program_contract: Any,
) -> bool:
    scheduler_contract = (
        runtime_program_contract.get("scheduler")
        if isinstance(runtime_program_contract, dict)
        else None
    )
    runtime_nodes = (
        runtime_program_contract.get("nodes")
        if isinstance(runtime_program_contract, dict)
        else None
    )
    ordering = (
        scheduler_contract.get("ordering")
        if isinstance(scheduler_contract, dict)
        else None
    )
    phase_rank = (
        next(
            (
                row.get("rank")
                for row in ordering
                if isinstance(row, dict) and row.get("member") == "phase"
            ),
            None,
        )
        if isinstance(ordering, list)
        else None
    )
    if (
        not _package_vector_contract_is_closed(contract)
        or not isinstance(candidate_encoding, dict)
        or candidate_encoding.get("radix") != 16
        or candidate_encoding.get("zero_pad") is not True
        or not isinstance(candidate_encoding.get("width_bits"), int)
        or candidate_encoding["width_bits"] % 4 != 0
        or not isinstance(candidate_encoding.get("alphabet"), str)
        or not candidate_encoding["alphabet"]
        or not isinstance(phase_rank, list)
        or not phase_rank
        or not all(isinstance(phase, str) and phase for phase in phase_rank)
        or not isinstance(runtime_nodes, list)
        or not all(isinstance(node, dict) for node in runtime_nodes)
    ):
        return False
    phase_inventory = set(phase_rank)
    candidate_width = candidate_encoding["width_bits"] // 4
    candidate_alphabet = candidate_encoding["alphabet"]
    vector_ids = vector_set.get("vectors")
    vectors = vector_set.get("vector_definitions")
    if (
        not isinstance(vector_ids, list)
        or not isinstance(vectors, list)
        or vector_ids
        != [vector.get("id") for vector in vectors if isinstance(vector, dict)]
        or len(vector_ids) != len(set(vector_ids))
    ):
        return False
    kinds = {
        item["id"]: item
        for item in contract["kinds"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    categories = set(contract["categories"])
    operations_entry = next(
        (
            item
            for item in cast(list[dict[str, Any]], package.get("semantic_closure"))
            if item.get("authority_path") == "language.operations"
        ),
        None,
    )
    if not isinstance(operations_entry, dict) or not isinstance(
        operations_entry.get("definitions"), list
    ):
        return False
    operations = {
        operation.get("id"): operation
        for operation in operations_entry["definitions"]
        if isinstance(operation, dict) and isinstance(operation.get("id"), str)
    }
    if any(
        not isinstance(operation.get("vectors"), list)
        for operation in operations.values()
    ):
        return False
    evidence_ids: set[str] = set()
    relation_roles_by_operation: dict[str, list[str]] = {}
    for vector in vectors:
        if not isinstance(vector, dict) or "kind" not in vector:
            continue
        kind_id = vector.get("kind")
        kind = kinds.get(kind_id)
        if (
            not isinstance(kind_id, str)
            or not isinstance(kind, dict)
            or set(vector) != set(kind["required_members"])
            or not isinstance(vector.get("id"), str)
            or not vector["id"]
            or vector.get("category") not in categories
        ):
            return False
        evidence_ids.add(vector["id"])
        if kind_id == "package-contract":
            probe = vector.get("probe")
            if (
                not isinstance(probe, dict)
                or set(probe) != set(kind["probe_members"])
                or not isinstance(probe.get("path"), str)
                or probe["path"].split(".", 1)[0] not in contract["package_probe_roots"]
            ):
                return False
            declared, observed = _exact_path_value(package, probe["path"])
            if not declared or not _canonical_equal(observed, vector.get("expect")):
                return False
            continue
        if kind_id == "value-program":
            inp = vector.get("input")
            expect = vector.get("expect")
            allowed_nodes = set(cast(list[str], kind["instruction_nodes"]))
            if (
                not isinstance(inp, dict)
                or set(inp) != set(kind["input_members"])
                or not isinstance(inp.get("cache"), bool)
                or not isinstance(inp.get("evaluations"), int)
                or isinstance(inp["evaluations"], bool)
                or inp["evaluations"] < 1
                or not isinstance(inp.get("instructions"), list)
                or not inp["instructions"]
                or not all(
                    _value_program_instruction_is_closed(row, allowed_nodes)
                    for row in inp["instructions"]
                )
                or not isinstance(inp.get("numeric"), dict)
                or set(inp["numeric"]) != {"maximum", "minimum"}
                or not _signed_int64(inp["numeric"].get("minimum"))
                or not _signed_int64(inp["numeric"].get("maximum"))
                or inp["numeric"]["minimum"] > inp["numeric"]["maximum"]
                or not isinstance(inp.get("operands"), list)
                or not all(
                    isinstance(row, dict)
                    and set(row) == {"name", "value"}
                    and isinstance(row.get("name"), str)
                    and bool(row["name"])
                    and _signed_int64(row.get("value"))
                    for row in inp["operands"]
                )
                or [row["name"] for row in inp["operands"]]
                != sorted({row["name"] for row in inp["operands"]})
                or not isinstance(inp.get("resource_limit"), int)
                or isinstance(inp["resource_limit"], bool)
                or inp["resource_limit"] < 0
                or not isinstance(inp.get("result"), str)
                or not inp["result"]
                or not isinstance(inp.get("site"), str)
                or not inp["site"]
                or not isinstance(expect, dict)
                or set(expect) != set(kind["expect_members"])
                or expect.get("outcome") not in {"admitted", "refused"}
                or not isinstance(expect.get("cache_entries"), int)
                or isinstance(expect["cache_entries"], bool)
                or expect["cache_entries"] < 0
                or not isinstance(expect.get("charge"), int)
                or isinstance(expect["charge"], bool)
                or expect["charge"] < 0
                or not isinstance(expect.get("result_artifact"), bool)
                or not isinstance(expect.get("site"), str)
                or not expect["site"]
                or not (
                    (
                        expect["outcome"] == "admitted"
                        and _signed_int64(expect.get("result"))
                        and expect.get("signal") is None
                        and expect["result_artifact"] is True
                    )
                    or (
                        expect["outcome"] == "refused"
                        and expect.get("result") is None
                        and expect.get("signal") in {"numeric-overflow", "step-limit"}
                        and expect["result_artifact"] is False
                    )
                )
            ):
                return False
            continue
        if kind_id == "scheduler-scenario":
            if not _scheduler_scenario_vector_is_closed(vector, kind, phase_inventory):
                return False
            continue
        operation = operations.get(vector.get("operation"))
        if not isinstance(operation, dict):
            return False
        if kind_id == "operation-contract":
            probe = vector.get("probe")
            if (
                not isinstance(probe, dict)
                or set(probe) != set(kind["probe_members"])
                or not isinstance(probe.get("path"), str)
                or probe["path"].split(".", 1)[0]
                not in contract["operation_probe_roots"]
            ):
                return False
            declared, observed = _exact_path_value(operation, probe["path"])
            if not declared or not _canonical_equal(observed, vector.get("expect")):
                return False
            continue
        if kind_id == "operation-relation":
            if not _operation_relation_is_satisfied(
                operation,
                vector,
                kind,
                cast(list[str], contract["operation_probe_roots"]),
                cast(list[dict[str, Any]], runtime_nodes),
            ):
                return False
            relation_roles_by_operation.setdefault(operation["id"], []).append(
                cast(str, vector["role"])
            )
            continue
        if operation.get("operation_kind") != "event-program":
            return False
        inp = vector.get("input")
        expect = vector.get("expect")
        if (
            not isinstance(inp, dict)
            or set(inp) != set(kind["input_members"])
            or not _signed_int64(inp.get("seed"))
            or not isinstance(inp.get("state_names"), list)
            or inp["state_names"] != sorted(set(inp["state_names"]))
            or not all(isinstance(name, str) and name for name in inp["state_names"])
            or not isinstance(inp.get("values"), list)
            or not isinstance(expect, dict)
            or set(expect) != set(kind["expect_members"])
            or not isinstance(expect.get("outcome"), str)
            or not isinstance(expect.get("state_after"), list)
            or not isinstance(expect.get("rng_draws"), list)
        ):
            return False
        values = inp["values"]
        value_names = [item.get("name") for item in values if isinstance(item, dict)]
        operation_inputs = [
            item.get("id")
            for item in cast(list[dict[str, Any]], operation.get("inputs"))
            if isinstance(item, dict)
        ]
        if (
            not all(
                isinstance(item, dict)
                and set(item) == {"name", "value"}
                and isinstance(item.get("name"), str)
                and item["name"]
                and _signed_int64(item.get("value"))
                for item in values
            )
            or value_names != operation_inputs
            or not set(inp["state_names"]) <= set(value_names)
        ):
            return False
        state_after = expect["state_after"]
        if (
            not all(
                isinstance(item, dict)
                and set(item) == set(kind["state_value_members"])
                and isinstance(item.get("name"), str)
                and _signed_int64(item.get("value"))
                for item in state_after
            )
            or [item["name"] for item in state_after] != inp["state_names"]
        ):
            return False
        draws = expect["rng_draws"]
        if not all(
            isinstance(item, dict)
            and set(item) == set(kind["rng_draw_members"])
            and isinstance(item.get("candidate_hex"), str)
            and len(item["candidate_hex"]) == candidate_width
            and all(
                character in candidate_alphabet for character in item["candidate_hex"]
            )
            and isinstance(item.get("stream"), str)
            and item["stream"]
            and isinstance(item.get("index"), int)
            and not isinstance(item["index"], bool)
            and item["index"] >= 0
            and _signed_int64(item.get("value"))
            for item in draws
        ):
            return False
        outcomes = operation.get("outcomes")
        if not isinstance(outcomes, list) or expect["outcome"] not in {
            item.get("id") for item in outcomes if isinstance(item, dict)
        }:
            return False

    relation_kind = kinds.get("operation-relation")
    declaration_extension = (
        relation_kind.get("declaration_extension")
        if isinstance(relation_kind, dict)
        else None
    )
    declaration_members = (
        relation_kind.get("declaration_members")
        if isinstance(relation_kind, dict)
        else None
    )
    policy_authority_path = (
        relation_kind.get("policy_authority_path")
        if isinstance(relation_kind, dict)
        else None
    )
    policy_contract_members = (
        relation_kind.get("policy_contract_members")
        if isinstance(relation_kind, dict)
        else None
    )
    policy_extension = (
        relation_kind.get("policy_extension")
        if isinstance(relation_kind, dict)
        else None
    )
    policy_members = (
        relation_kind.get("policy_members") if isinstance(relation_kind, dict) else None
    )
    relation_probe_members = (
        relation_kind.get("probe_members") if isinstance(relation_kind, dict) else None
    )
    declared_roles_by_operation: dict[str, list[str]] = {}
    if (
        not isinstance(declaration_extension, str)
        or not isinstance(declaration_members, list)
        or not isinstance(policy_authority_path, str)
        or not isinstance(policy_contract_members, list)
        or not isinstance(policy_extension, str)
        or not isinstance(policy_members, list)
        or not isinstance(relation_probe_members, list)
    ):
        return False
    for operation_id, operation in operations.items():
        extensions = operation.get("extensions")
        declarations = (
            extensions.get(declaration_extension)
            if isinstance(extensions, dict)
            else None
        )
        if declarations is None:
            continue
        if (
            not isinstance(declarations, list)
            or not declarations
            or not all(
                isinstance(declaration, dict)
                and set(declaration) == set(declaration_members)
                and isinstance(declaration.get("id"), str)
                and bool(declaration["id"])
                and isinstance(declaration.get("probe"), dict)
                for declaration in declarations
            )
        ):
            return False
        roles = [cast(str, declaration["id"]) for declaration in declarations]
        if len(roles) != len(set(roles)):
            return False
        declared_roles_by_operation[cast(str, operation_id)] = roles

    policy_entry = next(
        (
            item
            for item in cast(list[dict[str, Any]], package.get("semantic_closure"))
            if item.get("authority_path") == policy_authority_path
        ),
        None,
    )
    policy_definitions = (
        policy_entry.get("definitions") if isinstance(policy_entry, dict) else None
    )
    if not isinstance(policy_definitions, list):
        return False
    policy_roles_by_operation: dict[str, list[str]] = {}
    for definition in policy_definitions:
        extensions = (
            definition.get("extensions") if isinstance(definition, dict) else None
        )
        policies = (
            extensions.get(policy_extension) if isinstance(extensions, dict) else None
        )
        if policies is None:
            continue
        if not isinstance(policies, list) or not policies:
            return False
        for policy in policies:
            if not isinstance(policy, dict) or set(policy) != set(policy_members):
                return False
            operation_id = policy.get("operation")
            operation = operations.get(operation_id)
            contract_probe = policy.get("contract")
            relations = policy.get("relations")
            if (
                not isinstance(operation_id, str)
                or not operation_id
                or operation_id in policy_roles_by_operation
                or not isinstance(operation, dict)
                or not isinstance(contract_probe, dict)
                or set(contract_probe) != set(policy_contract_members)
                or not isinstance(relations, list)
                or not relations
                or not all(
                    isinstance(relation, dict)
                    and set(relation) == set(declaration_members)
                    and isinstance(relation.get("id"), str)
                    and bool(relation["id"])
                    and isinstance(relation.get("probe"), dict)
                    and set(relation["probe"]) == set(relation_probe_members)
                    for relation in relations
                )
            ):
                return False
            policy_roles = [cast(str, relation["id"]) for relation in relations]
            if len(policy_roles) != len(set(policy_roles)):
                return False
            path = contract_probe.get("path")
            if (
                not isinstance(path, list)
                or not path
                or not all(isinstance(member, str) and member for member in path)
                or path[0] not in contract["operation_probe_roots"]
            ):
                return False
            observed: Any = operation
            for member in path:
                if not isinstance(observed, dict) or member not in observed:
                    return False
                observed = observed[member]
            operation_extensions = operation.get("extensions")
            declarations = (
                operation_extensions.get(declaration_extension)
                if isinstance(operation_extensions, dict)
                else None
            )
            if not _canonical_equal(observed, contract_probe.get("expect")) or not (
                _canonical_equal(declarations, relations)
            ):
                return False
            policy_roles_by_operation[operation_id] = policy_roles
    operation_ids = set(relation_roles_by_operation)
    if (
        operation_ids != set(declared_roles_by_operation)
        or operation_ids != set(policy_roles_by_operation)
        or any(
            roles != declared_roles_by_operation[operation_id]
            or roles != policy_roles_by_operation[operation_id]
            for operation_id, roles in relation_roles_by_operation.items()
        )
    ):
        return False

    operation_evidence_ids = {
        vector["id"]
        for vector in vectors
        if isinstance(vector, dict)
        and vector.get("kind")
        in {"operation-contract", "operation-relation", "runtime-scenario"}
    }
    referenced = {
        vector_id
        for operation in operations.values()
        for vector_id in cast(list[str], operation["vectors"])
        if vector_id in evidence_ids
    }
    return referenced == operation_evidence_ids


def _diagnostic_catalog_matches_vectors(language_bundle: dict[str, Any]) -> bool:
    diagnostics = language_bundle.get("diagnostics")
    vectors = language_bundle.get("vectors")
    if not isinstance(diagnostics, list) or not isinstance(vectors, list):
        return False
    catalog = {
        (str(item.get("code", "")), str(item.get("stage", "")))
        for item in diagnostics
        if isinstance(item, dict)
    }
    vector_catalog = {
        (str(item.get("diagnostic", "")), str(item.get("stage", "")))
        for item in vectors
        if isinstance(item, dict) and "diagnostic" in item
    }
    return catalog == vector_catalog


def _package_semantic_closure_is_closed(
    package: dict[str, Any],
    contract: Any,
) -> bool:
    if not isinstance(contract, dict):
        return False
    closure_contract = contract.get("semantic_closure")
    closure = package.get("semantic_closure")
    if not isinstance(closure_contract, dict) or not isinstance(closure, list):
        return False
    domain = closure_contract.get("domain")
    entry_members = closure_contract.get("entry_members")
    projections = closure_contract.get("projections")
    if (
        not isinstance(domain, str)
        or not domain
        or not isinstance(entry_members, list)
        or entry_members != ["authority_path", "definitions"]
        or not isinstance(projections, list)
        or len(closure) != len(projections)
    ):
        return False
    for entry, projection in zip(closure, projections, strict=True):
        key_member = (
            projection.get("key_member") if isinstance(projection, dict) else None
        )
        owners_path = (
            projection.get("owners_path") if isinstance(projection, dict) else None
        )
        if (
            not isinstance(entry, dict)
            or set(entry) != set(entry_members)
            or not isinstance(projection, dict)
            or set(projection) != {"authority_path", "key_member", "owners_path"}
            or entry.get("authority_path") != projection.get("authority_path")
            or not isinstance(entry.get("definitions"), list)
            or not isinstance(projection.get("authority_path"), str)
            or (key_member is not None and not isinstance(key_member, str))
            or not isinstance(owners_path, str)
            or not owners_path
            or not _path_is_declared(package, owners_path)
        ):
            return False
        definitions = entry["definitions"]
        owned_values = _path_values(package, owners_path)

        def definition_key(value: Any) -> bytes | None:
            selected = value
            if key_member is not None:
                if not isinstance(value, dict) or key_member not in value:
                    return None
                selected = value[key_member]
            try:
                return canonical_bytes(cast(JsonValue, selected))
            except (TypeError, ValueError):
                return None

        def owner_key(value: Any) -> bytes | None:
            try:
                return canonical_bytes(cast(JsonValue, value))
            except (TypeError, ValueError):
                return None

        definition_keys = [definition_key(value) for value in definitions]
        owner_keys = [owner_key(value) for value in owned_values]
        if (
            any(key is None for key in definition_keys)
            or any(key is None for key in owner_keys)
            or len(set(definition_keys)) != len(definition_keys)
            or len(set(owner_keys)) != len(owner_keys)
            or set(definition_keys) != set(owner_keys)
        ):
            return False
    semantic_projection = contract.get("semantic_identity_projection")
    if (
        not isinstance(semantic_projection, dict)
        or set(semantic_projection)
        != {
            "domain",
            "extension_inventory_member",
            "path_inventory_member",
            "source_member",
            "path_member",
        }
        or semantic_projection.get("source_member") != "semantic_closure"
        or semantic_projection.get("path_member") != "authority_path"
        or semantic_projection.get("extension_inventory_member")
        != "runtime_semantic_excluded_extensions"
        or not isinstance(semantic_projection.get("domain"), str)
        or not isinstance(semantic_projection.get("path_inventory_member"), str)
    ):
        return False
    runtime_paths = package.get(semantic_projection["path_inventory_member"])
    closure_paths = [entry["authority_path"] for entry in closure]
    if (
        not isinstance(runtime_paths, list)
        or not runtime_paths
        or not all(isinstance(path, str) and path for path in runtime_paths)
        or len(runtime_paths) != len(set(runtime_paths))
        or not set(runtime_paths) <= set(closure_paths)
    ):
        return False
    try:
        runtime_closure = package_runtime_semantic_closure(package, semantic_projection)
        expected = content_identity(
            semantic_projection["domain"], cast(JsonValue, runtime_closure)
        )
    except (TypeError, ValueError):
        return False
    return package.get("semantic_identity") == expected


def _package_semantic_projections_are_exact(
    packages: list[dict[str, Any]],
    contract: Any,
    language_bundle: dict[str, Any],
) -> bool:
    if not isinstance(contract, dict):
        return False
    closure_contract = contract.get("semantic_closure")
    if not isinstance(closure_contract, dict):
        return False
    projections = closure_contract.get("projections")
    if not isinstance(projections, list):
        return False
    for index, projection in enumerate(projections):
        if not isinstance(projection, dict):
            return False
        authority_path = projection.get("authority_path")
        key_member = projection.get("key_member")
        declared, authority_definitions = _exact_path_value(
            language_bundle, authority_path
        )
        if not declared or not isinstance(authority_definitions, list):
            return False
        embedded: list[Any] = []
        for package in packages:
            closure = package.get("semantic_closure")
            if not isinstance(closure, list) or index >= len(closure):
                return False
            entry = closure[index]
            if (
                not isinstance(entry, dict)
                or entry.get("authority_path") != authority_path
                or not isinstance(entry.get("definitions"), list)
            ):
                return False
            embedded.extend(entry["definitions"])

        def definition_key(value: Any) -> tuple[str, bytes] | None:
            if key_member is None:
                try:
                    return ("value", canonical_bytes(cast(JsonValue, value)))
                except (TypeError, ValueError):
                    return None
            if (
                not isinstance(key_member, str)
                or not isinstance(value, dict)
                or key_member not in value
            ):
                return None
            try:
                return (
                    "member",
                    canonical_bytes(cast(JsonValue, value[key_member])),
                )
            except (TypeError, ValueError):
                return None

        embedded_keys = [definition_key(value) for value in embedded]
        authority_keys = [definition_key(value) for value in authority_definitions]
        if (
            any(key is None for key in embedded_keys)
            or any(key is None for key in authority_keys)
            or len(set(embedded_keys)) != len(embedded_keys)
            or len(set(authority_keys)) != len(authority_keys)
        ):
            return False
        embedded_by_key = dict(zip(embedded_keys, embedded, strict=True))
        authority_by_key = dict(zip(authority_keys, authority_definitions, strict=True))
        if embedded_by_key != authority_by_key:
            return False
    return True
