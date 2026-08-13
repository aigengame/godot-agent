"""Runtime component and operation-contract admission."""

from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    StructuredValueIndex,
    admit_typed_value,
    nominal_type_key,
)


_SUPPORTED_RUNTIME_COMPONENT_CONTRACT_IDENTITY = (
    "sha256:5884a044e531d0a94c93e203a9644ea6d9d845154592ff714636a6032c8a7798"
)


def operation_value_contract_matches(
    actual: dict[str, Any], formal: dict[str, Any]
) -> bool:
    """Apply the shared closed Operation value-contract relation."""
    if actual.get("type") != formal.get("type"):
        return False
    if "value_kind" in actual or "value_kind" in formal:
        return actual.get("value_kind") == formal.get("value_kind")
    return all(
        actual.get(member) == formal.get(member)
        for member in (
            "representation",
            "kind",
            "unit",
            "domain",
            "numeric_policy",
        )
    )


def literal_operation_contracts(
    value: Any,
    literal_profiles: Any,
    typed_envelope_contract: Any,
    fixed_value_contracts: Any,
) -> tuple[dict[str, Any], ...]:
    """Project the admitted Operation contracts for one literal value."""
    if not isinstance(literal_profiles, list):
        return ()
    if value is None:
        unit = (
            fixed_value_contracts.get("kernel-unit")
            if isinstance(fixed_value_contracts, dict)
            else None
        )
        return (unit,) if isinstance(unit, dict) else ()
    if isinstance(value, bool):
        boolean = (
            fixed_value_contracts.get("kernel-boolean")
            if isinstance(fixed_value_contracts, dict)
            else None
        )
        return (boolean,) if isinstance(boolean, dict) else ()
    admission = (
        typed_envelope_contract.get("admission")
        if isinstance(typed_envelope_contract, dict)
        else None
    )
    envelope_members = (
        admission.get("envelope_members") if isinstance(admission, dict) else None
    )
    type_member = (
        typed_envelope_contract.get("type_member")
        if isinstance(typed_envelope_contract, dict)
        else None
    )
    value_member = (
        typed_envelope_contract.get("value_member")
        if isinstance(typed_envelope_contract, dict)
        else None
    )
    if (
        isinstance(value, dict)
        and isinstance(envelope_members, list)
        and isinstance(type_member, str)
        and isinstance(value_member, str)
        and set(envelope_members) == {type_member, value_member}
        and set(value) == set(envelope_members)
    ):
        type_expression = value[type_member]
        typed_profiles = [
            profile
            for profile in literal_profiles
            if isinstance(profile, dict)
            and profile.get("source_kind") == "typed-envelope"
            and profile.get("value_kind") == "nominal-structured"
        ]
        if (
            len(typed_profiles) == 1
            and isinstance(admission, dict)
            and (coordinate := nominal_type_key(type_expression, admission)) is not None
        ):
            package, version, type_id = coordinate
            return (
                {
                    "type": {"id": type_id, "package": package, "version": version},
                    "value_kind": "nominal-structured",
                },
            )
        return ()
    if not isinstance(value, int) or isinstance(value, bool):
        return ()
    return tuple(
        profile
        for profile in literal_profiles
        if isinstance(profile, dict)
        and profile.get("source_kind") == "integer"
        and isinstance(profile.get("minimum"), int)
        and not isinstance(profile["minimum"], bool)
        and isinstance(profile.get("maximum"), int)
        and not isinstance(profile["maximum"], bool)
        and profile["minimum"] <= value <= profile["maximum"]
    )


def operation_value_is_admitted(
    value: Any,
    formal: dict[str, Any],
    *,
    literal_profiles: Any,
    typed_envelope_contract: Any,
    fixed_value_contracts: Any,
    structured_authority: StructuredValueIndex,
    resource_limit: int,
) -> bool:
    """Validate one execution-vector value against an Operation port."""
    matches = [
        contract
        for contract in literal_operation_contracts(
            value,
            literal_profiles,
            typed_envelope_contract,
            fixed_value_contracts,
        )
        if operation_value_contract_matches(contract, formal)
    ]
    if len(matches) != 1:
        return False
    if not isinstance(value, dict):
        return True
    try:
        admit_typed_value(
            value,
            authority=structured_authority,
            resource_limit=resource_limit,
        )
    except (StructuredValueFault, ValueError):
        return False
    return True


def _operation_result_source_shape_is_closed(
    operation: dict[str, Any],
    result_source_shapes: dict[str, Any],
) -> bool:
    result = operation.get("result")
    source = result.get("source") if isinstance(result, dict) else None
    if not isinstance(source, dict):
        return False
    kind = source.get("kind")
    required_members = result_source_shapes.get(kind) if isinstance(kind, str) else None
    if (
        not isinstance(required_members, list)
        or not all(isinstance(member, str) for member in required_members)
        or set(source) != set(required_members)
    ):
        return False
    if kind in {"local", "port"}:
        return isinstance(source.get("name"), str) and bool(source["name"])
    if kind == "operation-result":
        return isinstance(source.get("site"), str) and bool(source["site"])
    return kind == "unit"


def _runtime_contract_path(runtime: dict[str, Any], path: str) -> Any:
    value: Any = runtime
    for member in path.split("."):
        if not isinstance(value, dict) or member not in value:
            return None
        value = value[member]
    return value


def _active_runtime_profile_matches_contract(
    profile: dict[str, Any],
    contract: dict[str, Any],
    runtime: dict[str, Any],
) -> bool:
    active = contract.get("active_runtime")
    if not isinstance(active, dict) or set(active) != {
        "required_members",
        "optional_members",
        "runtime_member_bindings",
        "rng_member_bindings",
        "budget_scopes",
        "resource_bounds",
    }:
        return False
    required = active.get("required_members")
    optional = active.get("optional_members")
    runtime_bindings = active.get("runtime_member_bindings")
    rng_bindings = active.get("rng_member_bindings")
    budget_scopes = active.get("budget_scopes")
    resource_contract = active.get("resource_bounds")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(member, str) and member for member in required)
        or len(required) != len(set(required))
        or not isinstance(optional, list)
        or not all(isinstance(member, str) and member for member in optional)
        or len(optional) != len(set(optional))
        or set(required) & set(optional)
        or set(profile) - set(optional) != set(required)
        or not isinstance(runtime_bindings, dict)
        or not runtime_bindings
        or not set(runtime_bindings) <= set(required)
        or not all(isinstance(path, str) and path for path in runtime_bindings.values())
        or not isinstance(rng_bindings, dict)
        or not rng_bindings
        or "rng" not in required
        or not isinstance(profile.get("rng"), dict)
        or set(profile["rng"]) != set(rng_bindings)
        or not all(isinstance(path, str) and path for path in rng_bindings.values())
        or "budget_scopes" not in required
        or not isinstance(budget_scopes, dict)
        or not budget_scopes
        or not all(
            isinstance(member, str) and member and isinstance(scope, str) and scope
            for member, scope in budget_scopes.items()
        )
        or profile.get("budget_scopes") != budget_scopes
        or "resource_bounds" not in required
        or not isinstance(resource_contract, dict)
        or set(resource_contract) != {"members", "value_contract"}
        or resource_contract.get("value_contract") != "positive-integer"
    ):
        return False
    resource_members = resource_contract.get("members")
    resource_bounds = profile.get("resource_bounds")
    if (
        not isinstance(resource_members, list)
        or not resource_members
        or not all(isinstance(member, str) and member for member in resource_members)
        or len(resource_members) != len(set(resource_members))
        or not isinstance(resource_bounds, dict)
        or set(resource_bounds) != set(resource_members)
        or not all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in resource_bounds.values()
        )
    ):
        return False
    return all(
        profile.get(member) == _runtime_contract_path(runtime, cast(str, path))
        for member, path in runtime_bindings.items()
    ) and all(
        cast(dict[str, Any], profile["rng"]).get(member)
        == _runtime_contract_path(runtime, cast(str, path))
        for member, path in rng_bindings.items()
    )


def _runtime_component_value_has_type(value: Any, expected: Any) -> bool:
    if expected == "ordering-list":
        return (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(row, dict)
                and set(row)
                in ({"direction", "member"}, {"direction", "member", "rank"})
                and row.get("direction") in {"ascending", "descending"}
                and isinstance(row.get("member"), str)
                and bool(row["member"])
                and (
                    "rank" not in row
                    or (
                        isinstance(row["rank"], list)
                        and bool(row["rank"])
                        and all(isinstance(item, str) and item for item in row["rank"])
                        and len(row["rank"]) == len(set(row["rank"]))
                    )
                )
                for row in value
            )
            and len({row["member"] for row in value}) == len(value)
        )
    return (
        (expected == "object" and isinstance(value, dict))
        or (expected == "array" and isinstance(value, list))
        or (expected == "string" and isinstance(value, str) and bool(value))
        or (
            expected == "integer"
            and isinstance(value, int)
            and not isinstance(value, bool)
        )
        or (
            expected == "string-list"
            and isinstance(value, list)
            and all(isinstance(item, str) and item for item in value)
            and len(value) == len(set(value))
        )
    )


def _runtime_component_contract_is_closed(runtime: dict[str, Any]) -> bool:
    required_object_roles = {
        "runtime-configuration": {"lifecycle-roles", "root"},
        "scheduler": {
            "budget-members",
            "call-site-identities",
            "cancel-call-site-identity",
            "cancel-policy",
            "cancel-refusal-signals",
            "committed-trace-journal",
            "event-catalog-journal",
            "event-identity",
            "event-identity-variants",
            "event-spec-journal",
            "external-input-admission",
            "external-input-identity",
            "observation-policy",
            "root",
            "root-admission-map",
            "root-event-map-journal",
            "root-phase-map",
            "runtime-configuration-projection",
            "runtime-journal",
            "schedule-call-site-identity",
            "schedule-policy",
            "schedule-refusal-signals",
            "snapshot-identity",
            "terminal-status",
        },
        "step": {"boundary-roles", "root"},
        "transition": {"root"},
    }
    required_relation_roles = {
        "lifecycle-states",
        "observation-phase",
        "root-phases",
        "scheduled-child-phase",
        "step-boundaries",
        "step-stops",
    }
    contract = runtime.get("component_contract")
    if (
        not isinstance(contract, dict)
        or set(contract)
        != {
            "components",
            "content_identity",
            "relations",
            "version",
        }
        or contract.get("version") != "runtime-component-meta-contract-v1"
        or contract.get("content_identity")
        != _SUPPORTED_RUNTIME_COMPONENT_CONTRACT_IDENTITY
    ):
        return False
    try:
        observed_contract_identity = content_identity(
            cast(str, contract["version"]),
            cast(
                JsonValue,
                {
                    member: value
                    for member, value in contract.items()
                    if member != "content_identity"
                },
            ),
        )
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    if observed_contract_identity != contract["content_identity"]:
        return False
    components = contract.get("components")
    relations = contract.get("relations")
    if (
        not isinstance(components, dict)
        or not components
        or not isinstance(relations, list)
    ):
        return False
    component_roles: dict[str, str] = {}
    for component_name, component_contract in components.items():
        component = runtime.get(component_name)
        objects = (
            component_contract.get("objects")
            if isinstance(component_contract, dict)
            else None
        )
        if (
            not isinstance(component_name, str)
            or not component_name
            or not isinstance(component, dict)
            or not isinstance(component_contract, dict)
            or set(component_contract) != {"objects", "role"}
            or not isinstance(objects, dict)
            or "" not in objects
            or not isinstance(component_contract.get("role"), str)
            or not component_contract["role"]
            or component_contract["role"] in component_roles
        ):
            return False
        component_role = cast(str, component_contract["role"])
        component_roles[component_role] = component_name
        object_roles: set[str] = set()
        for path, object_contract in objects.items():
            value = component if path == "" else _runtime_contract_path(component, path)
            member_types = (
                object_contract.get("member_types")
                if isinstance(object_contract, dict)
                else None
            )
            object_role = (
                object_contract.get("role")
                if isinstance(object_contract, dict)
                else None
            )
            if (
                not isinstance(path, str)
                or not isinstance(object_contract, dict)
                or set(object_contract) != {"member_types", "role"}
                or not isinstance(object_role, str)
                or not object_role
                or object_role in object_roles
                or not isinstance(value, dict)
                or not isinstance(member_types, dict)
                or set(value) != set(member_types)
                or not all(
                    isinstance(member, str)
                    and member
                    and _runtime_component_value_has_type(value[member], expected)
                    for member, expected in member_types.items()
                )
            ):
                return False
            object_roles.add(object_role)
        if object_roles != required_object_roles.get(component_role):
            return False
    if set(component_roles) != set(required_object_roles):
        return False
    relation_roles: set[str] = set()
    for relation in relations:
        if not isinstance(relation, dict):
            return False
        component_name = cast(str, relation.get("component"))
        component = components.get(component_name)
        runtime_component = runtime.get(component_name)
        if not isinstance(component, dict) or not isinstance(runtime_component, dict):
            return False
        relation_role = relation.get("role")
        if (
            not isinstance(relation_role, str)
            or not relation_role
            or relation_role in relation_roles
        ):
            return False
        relation_roles.add(relation_role)
        kind = relation.get("kind")
        if kind == "mapping-values-in-list":
            if set(relation) != {
                "component",
                "excluded_keys",
                "kind",
                "list_path",
                "mapping_path",
                "role",
            }:
                return False
            mapping = _runtime_contract_path(
                runtime_component, relation["mapping_path"]
            )
            values = _runtime_contract_path(runtime_component, relation["list_path"])
            excluded = relation.get("excluded_keys")
            if (
                not isinstance(mapping, dict)
                or not isinstance(values, list)
                or not isinstance(excluded, list)
                or not all(isinstance(key, str) for key in excluded)
                or not set(excluded) <= set(mapping)
                or any(
                    value not in values
                    for key, value in mapping.items()
                    if key not in excluded
                )
            ):
                return False
            continue
        if kind == "list-values-in-list":
            if set(relation) != {
                "component",
                "kind",
                "list_path",
                "role",
                "values_path",
            }:
                return False
            source = _runtime_contract_path(
                runtime_component, cast(str, relation.get("list_path"))
            )
            values = _runtime_contract_path(
                runtime_component, cast(str, relation.get("values_path"))
            )
            if (
                not isinstance(source, list)
                or not isinstance(values, list)
                or not set(source) <= set(values)
            ):
                return False
            continue
        if kind in {
            "mapping-values-in-ranked-ordering",
            "value-in-ranked-ordering",
        }:
            expected_members = {
                "component",
                "kind",
                "ordering_member",
                "ordering_path",
                "role",
                (
                    "mapping_path"
                    if kind == "mapping-values-in-ranked-ordering"
                    else "value_path"
                ),
            }
            ordering = _runtime_contract_path(
                runtime_component, cast(str, relation.get("ordering_path"))
            )
            rank_row = (
                next(
                    (
                        row
                        for row in ordering
                        if isinstance(row, dict)
                        and row.get("member") == relation.get("ordering_member")
                    ),
                    None,
                )
                if isinstance(ordering, list)
                else None
            )
            rank = rank_row.get("rank") if isinstance(rank_row, dict) else None
            if set(relation) != expected_members or not isinstance(rank, list):
                return False
            if kind == "mapping-values-in-ranked-ordering":
                mapping = _runtime_contract_path(
                    runtime_component, cast(str, relation.get("mapping_path"))
                )
                if not isinstance(mapping, dict) or any(
                    value not in rank for value in mapping.values()
                ):
                    return False
            elif (
                _runtime_contract_path(
                    runtime_component, cast(str, relation.get("value_path"))
                )
                not in rank
            ):
                return False
            continue
        return False
    return relation_roles == required_relation_roles


def _runtime_authority_is_closed(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    meta = kernel.get("meta_format")
    runtime = meta.get("runtime_program") if isinstance(meta, dict) else None
    profile_identity = (
        meta.get("runtime_profile_definition") if isinstance(meta, dict) else None
    )
    if (
        not isinstance(runtime, dict)
        or not isinstance(profile_identity, dict)
        or set(profile_identity) != {"domain", "projection", "active_runtime"}
        or not isinstance(profile_identity.get("domain"), str)
        or not profile_identity["domain"]
        or profile_identity.get("projection") != "complete-definition"
        or set(runtime)
        != {
            "closed",
            "version",
            "fixed_value_contracts",
            "expression_nodes",
            "effect_nodes",
            "control_nodes",
            "nodes",
            "numeric",
            "named_rng",
            "scheduler",
            "event_atomicity",
            "component_contract",
            "runtime_configuration",
            "transition",
            "step",
            "outcome_contract",
            "invocation_contract",
            "vectors",
        }
        or runtime.get("closed") is not True
        or not isinstance(runtime.get("version"), str)
        or not runtime["version"]
        or not isinstance(runtime.get("scheduler"), dict)
        or not isinstance(runtime.get("runtime_configuration"), dict)
        or not isinstance(runtime.get("transition"), dict)
        or not isinstance(runtime.get("step"), dict)
        or not _runtime_component_contract_is_closed(runtime)
    ):
        return False
    family_members = {
        "expression": "expression_nodes",
        "effect": "effect_nodes",
        "control": "control_nodes",
    }
    raw_nodes = runtime.get("nodes")
    fixed_value_contracts = runtime.get("fixed_value_contracts")
    fixed_contract_members = {
        "domain",
        "kind",
        "numeric_policy",
        "representation",
        "type",
        "unit",
    }
    if (
        not isinstance(fixed_value_contracts, dict)
        or not fixed_value_contracts
        or any(
            not isinstance(contract_id, str)
            or not contract_id
            or not isinstance(contract, dict)
            or set(contract) != fixed_contract_members
            or not isinstance(contract.get("type"), dict)
            or set(contract["type"]) != {"id", "package", "version"}
            or not all(
                isinstance(contract["type"].get(member), str)
                and contract["type"][member]
                for member in ("id", "package", "version")
            )
            or not all(
                isinstance(contract.get(member), str) and contract[member]
                for member in ("kind", "numeric_policy", "representation", "unit")
            )
            or not isinstance(contract.get("domain"), dict)
            or set(contract["domain"]) != {"kind"}
            or not isinstance(contract["domain"].get("kind"), str)
            or not contract["domain"]["kind"]
            for contract_id, contract in fixed_value_contracts.items()
        )
    ):
        return False
    if not isinstance(raw_nodes, list):
        return False
    nodes: dict[str, dict[str, Any]] = {}
    for node in raw_nodes:
        if (
            not isinstance(node, dict)
            or set(node)
            != {
                "family",
                "id",
                "operand_constraints",
                "refusals",
                "required_members",
                "resource_charge",
                "result",
                "semantics",
            }
            or node.get("family") not in family_members
            or not isinstance(node.get("id"), str)
            or not node["id"]
            or not isinstance(node.get("required_members"), list)
            or not node["required_members"]
            or node["required_members"][0] != "node"
            or len(node["required_members"]) != len(set(node["required_members"]))
            or not isinstance(node.get("semantics"), dict)
            or not isinstance(node["semantics"].get("operator"), str)
            or not node["semantics"]["operator"]
            or not isinstance(node.get("result"), dict)
            or not isinstance(node["result"].get("kind"), str)
            or not isinstance(node.get("operand_constraints"), list)
            or not isinstance(node.get("refusals"), list)
            or node.get("resource_charge") != {"counter": "event-steps", "amount": 1}
            or node["id"] in nodes
        ):
            return False
        result = cast(dict[str, Any], node["result"])
        typing = result.get("typing")
        if result["kind"] in {"local", "draw"}:
            if not isinstance(typing, dict) or set(result) != {"kind", "typing"}:
                return False
            typing_kind = typing.get("kind")
            if typing_kind == "fixed":
                if (
                    set(typing) != {"kind", "contract"}
                    or typing.get("contract") not in fixed_value_contracts
                ):
                    return False
            elif typing_kind in {
                "declared-result",
                "same-as-references",
                "literal-profile",
            }:
                members = typing.get("members")
                if (
                    set(typing) != {"kind", "members"}
                    or not isinstance(members, list)
                    or not members
                    or not all(
                        isinstance(member, str)
                        and member in node["required_members"]
                        and member not in {"node", "target"}
                        for member in members
                    )
                ):
                    return False
            else:
                return False
        elif set(result) != {"kind"}:
            return False
        for constraint in cast(
            list[Any],
            node["operand_constraints"],
        ):
            if not isinstance(constraint, dict):
                return False
            constraint_kind = constraint.get("kind")
            members = constraint.get("members")
            if (
                constraint_kind
                not in {
                    "fixed-value-contract",
                    "runtime-numeric",
                    "same-value-contract",
                    "writable-port",
                }
                or not isinstance(members, list)
                or not members
                or len(members) != len(set(members))
                or not all(
                    isinstance(member, str)
                    and member in node["required_members"]
                    and member not in {"node", "target"}
                    for member in members
                )
            ):
                return False
            if constraint_kind == "fixed-value-contract":
                if (
                    set(constraint) != {"contract", "kind", "members"}
                    or constraint.get("contract") not in fixed_value_contracts
                ):
                    return False
            elif set(constraint) != {"kind", "members"}:
                return False
        nodes[node["id"]] = node
    cancel_semantics = nodes.get("cancel", {}).get("semantics")
    cancel_target = (
        cancel_semantics.get("target_reference")
        if isinstance(cancel_semantics, dict)
        else None
    )
    cancel_variants = (
        cancel_target.get("variants") if isinstance(cancel_target, dict) else None
    )
    if (
        not isinstance(cancel_target, dict)
        or set(cancel_target) != {"instruction_member", "variants"}
        or not isinstance(cancel_target.get("instruction_member"), str)
        or not cancel_target["instruction_member"]
        or not isinstance(cancel_variants, list)
        or len(cancel_variants) != 2
        or {variant.get("kind") for variant in cancel_variants} != {"local", "port"}
        or any(
            not isinstance(variant, dict)
            or set(variant)
            != (
                {"kind", "value_member", "producer_result_kind"}
                if variant.get("kind") == "local"
                else {"kind", "value_member", "value_contract"}
            )
            or not isinstance(variant.get("value_member"), str)
            or not variant["value_member"]
            or (
                variant.get("kind") == "local"
                and not any(
                    node["result"]["kind"] == variant.get("producer_result_kind")
                    for node in nodes.values()
                )
            )
            or (
                variant.get("kind") == "port"
                and variant.get("value_contract") not in fixed_value_contracts
            )
            for variant in cancel_variants
        )
        or cancel_target["instruction_member"]
        not in nodes["cancel"]["required_members"]
    ):
        return False
    for family, member in family_members.items():
        inventory = runtime.get(member)
        if not isinstance(inventory, list) or inventory != [
            node["id"] for node in raw_nodes if node["family"] == family
        ]:
            return False
    if set(nodes) != {
        *runtime["expression_nodes"],
        *runtime["effect_nodes"],
        *runtime["control_nodes"],
    }:
        return False
    numeric = runtime.get("numeric")
    rng = runtime.get("named_rng")
    event = runtime.get("event_atomicity")
    outcomes = runtime.get("outcome_contract")
    invocation = runtime.get("invocation_contract")
    if (
        not isinstance(numeric, dict)
        or numeric
        != {
            "compatible_value_numeric_policies": ["exact-int64"],
            "id": "signed-int64-v1",
            "minimum": -(1 << 63),
            "maximum": (1 << 63) - 1,
            "overflow": "runtime-refusal",
            "overflow_signal": "numeric-overflow",
        }
        or not isinstance(rng, dict)
        or set(rng)
        != {
            "algorithm",
            "candidate_encoding",
            "word_bits",
            "seed_encoding",
            "stream_name_encoding",
            "stream_derivation",
            "state_transition",
            "interval_sampling",
            "trace_members",
        }
        or rng.get("algorithm") != "splitmix64-v1"
        or rng.get("candidate_encoding")
        != {
            "alphabet": "0123456789abcdef",
            "case": "lowercase",
            "radix": 16,
            "width_bits": 64,
            "zero_pad": True,
        }
        or rng.get("word_bits") != 64
        or rng.get("seed_encoding") != "unsigned-modulo-2^64"
        or rng.get("stream_name_encoding") != "utf-8"
        or not isinstance(rng.get("interval_sampling"), dict)
        or event
        != {
            "state_writes": "buffered",
            "rng_draws": "buffered",
            "child_events": "buffered",
            "cancellations": "buffered",
            "success": "commit-entire-current-event",
            "runtime_refusal": "rollback-entire-current-event",
        }
        or not isinstance(outcomes, dict)
        or outcomes
        != {
            "kinds": ["success", "gameplay-alternative"],
            "state_policies": ["commit", "rollback"],
            "operation_members": ["outcomes", "default_outcome"],
        }
        or invocation
        != {
            "closed": True,
            "version": "resolved-operation-binding-v1",
            "identity_domains": {
                "actual_operand": "actual-operation-operand-v2",
                "call_site": "operation-call-site-v2",
                "entrypoint": "model-entrypoint-v2",
                "formal_port": "operation-formal-port-v2",
                "outcome": "operation-outcome-v2",
                "result": "operation-result-v2",
            },
            "argument_evaluation_order": "formal-port-declaration-order",
            "operand_kinds": ["port", "local", "literal", "expression"],
            "result_binding_kinds": ["local", "operation-result", "discard"],
            "result_source_shapes": {
                "local": ["kind", "name"],
                "operation-result": ["kind", "site"],
                "port": ["kind", "name"],
                "unit": ["kind"],
            },
            "result_producer_cardinality": (
                "exactly-one-compatible-producer-on-every-success-path"
            ),
            "outcome_actions": ["continue", "propagate"],
            "outcome_mapping": "exactly-once-and-exhaustive",
            "scope": "lexical-call-frame",
            "ambient_capture": "forbidden",
            "resource_charge": "invoke-plus-transitive-callee-steps",
            "runtime_refusal": "propagate-with-call-site",
        }
    ):
        return False
    assert isinstance(invocation, dict)
    vectors = runtime.get("vectors")
    node_vectors = (
        {
            item.get("node"): item
            for item in vectors
            if isinstance(item, dict) and item.get("kind") == "node"
        }
        if isinstance(vectors, list)
        else {}
    )
    invocation_vectors = (
        {
            item.get("id"): item
            for item in vectors
            if isinstance(item, dict)
            and item.get("kind") == "invocation-result-contract"
        }
        if isinstance(vectors, list)
        else {}
    )
    if (
        not isinstance(vectors, list)
        or set(node_vectors) != set(nodes)
        or {item.get("id") for item in vectors if item.get("kind") == "rng"}
        != {
            "rng.first-draw",
            "rng.multi-draw",
            "rng.cross-stream",
            "rng.interval-boundary",
        }
        or set(invocation_vectors)
        != {
            "runtime.invocation.result-contract-compatible",
            "runtime.invocation.result-contract-incompatible",
        }
    ):
        return False
    for node_id, node in nodes.items():
        expected = {
            "charge": 1,
            "operand_constraints": node["operand_constraints"],
            "operator": node["semantics"]["operator"],
            "result_kind": node["result"]["kind"],
        }
        if "typing" in node["result"]:
            expected["result_typing"] = node["result"]["typing"]
        vector = node_vectors[node_id]
        if (
            set(vector) != {"expect", "id", "input", "kind", "node"}
            or vector.get("id") != f"runtime.node.{node_id}"
            or vector.get("input") != {"contract-probe": node["required_members"]}
            or vector.get("expect") != expected
        ):
            return False
    for vector in invocation_vectors.values():
        inp = vector.get("input")
        expect = vector.get("expect")
        if (
            set(vector) != {"expect", "id", "input", "kind"}
            or not isinstance(inp, dict)
            or set(inp) != {"producer_contract", "result_contract"}
            or not isinstance(expect, dict)
            or set(expect) != {"admitted"}
            or not isinstance(expect.get("admitted"), bool)
        ):
            return False
        producer_contract = fixed_value_contracts.get(inp["producer_contract"])
        result_contract = fixed_value_contracts.get(inp["result_contract"])
        if (
            not isinstance(producer_contract, dict)
            or not isinstance(result_contract, dict)
            or expect["admitted"]
            is not operation_value_contract_matches(
                producer_contract,
                result_contract,
            )
        ):
            return False
    referenced_fixed_contracts = (
        {
            cast(str, typing["contract"])
            for node in nodes.values()
            if isinstance((result := node.get("result")), dict)
            and isinstance((typing := result.get("typing")), dict)
            and typing.get("kind") == "fixed"
        }
        | {
            cast(str, constraint["contract"])
            for node in nodes.values()
            for constraint in cast(list[dict[str, Any]], node["operand_constraints"])
            if constraint.get("kind") == "fixed-value-contract"
        }
        | {
            cast(str, variant["value_contract"])
            for variant in cast(list[dict[str, Any]], cancel_variants)
            if variant.get("kind") == "port"
        }
        | {
            cast(str, contract_id)
            for vector in invocation_vectors.values()
            for contract_id in cast(dict[str, Any], vector["input"]).values()
        }
    )
    if set(fixed_value_contracts) != referenced_fixed_contracts:
        return False
    language = language_bundle.get("language")
    if not isinstance(language, dict):
        return False
    profiles = language.get("runtime_profiles")
    operations = language.get("operations")
    if not isinstance(profiles, list) or not isinstance(operations, list):
        return False
    for profile in profiles:
        if not isinstance(profile, dict):
            return False
        if profile.get("evaluation") == runtime["version"] and not (
            _active_runtime_profile_matches_contract(
                profile,
                profile_identity,
                runtime,
            )
        ):
            return False
    kinds = set(outcomes["kinds"])
    policies = set(outcomes["state_policies"])
    operations_by_id = {
        operation.get("id"): operation
        for operation in operations
        if isinstance(operation, dict) and isinstance(operation.get("id"), str)
    }

    def operation_outcomes(
        operation: dict[str, Any], visiting: set[str]
    ) -> set[str] | None:
        operation_id = str(operation.get("id", ""))
        if operation_id in visiting:
            return None
        visiting.add(operation_id)
        referenced: set[str] = set()
        local_result_kinds: dict[str, str] = {}
        formal_ports = {
            port.get("id"): port
            for port in operation.get("inputs", [])
            if isinstance(port, dict) and isinstance(port.get("id"), str)
        }
        body = operation.get("body")
        if not isinstance(body, list):
            visiting.remove(operation_id)
            return None
        for instruction in body:
            if not isinstance(instruction, dict):
                visiting.remove(operation_id)
                return None
            node = nodes.get(str(instruction.get("node", "")))
            if node is None or set(instruction) != set(node["required_members"]):
                visiting.remove(operation_id)
                return None
            if node["semantics"]["operator"] == "cancel-event":
                target_contract = node["semantics"]["target_reference"]
                target = instruction.get(target_contract["instruction_member"])
                variants = {
                    variant["kind"]: variant for variant in target_contract["variants"]
                }
                target_variant = (
                    variants.get(target.get("kind"))
                    if isinstance(target, dict)
                    else None
                )
                target_value = (
                    target.get(target_variant["value_member"])
                    if isinstance(target, dict) and isinstance(target_variant, dict)
                    else None
                )
                if (
                    not isinstance(target, dict)
                    or not isinstance(target_variant, dict)
                    or set(target) != {"kind", target_variant["value_member"]}
                    or not isinstance(target_value, str)
                    or not target_value
                    or (
                        target_variant["kind"] == "local"
                        and local_result_kinds.get(target_value)
                        != target_variant["producer_result_kind"]
                    )
                    or (
                        target_variant["kind"] == "port"
                        and (
                            target_value not in formal_ports
                            or not operation_value_contract_matches(
                                formal_ports[target_value],
                                fixed_value_contracts[target_variant["value_contract"]],
                            )
                        )
                    )
                ):
                    visiting.remove(operation_id)
                    return None
            if "outcome" in instruction:
                referenced.add(str(instruction["outcome"]))
            if node["semantics"]["operator"] == "invoke-operation":
                operation_ref = instruction.get("operation")
                if (
                    not isinstance(operation_ref, dict)
                    or set(operation_ref) != {"package", "version", "id"}
                    or not all(
                        isinstance(operation_ref.get(member), str)
                        and operation_ref[member]
                        for member in ("package", "version", "id")
                    )
                ):
                    visiting.remove(operation_id)
                    return None
                invoked = operations_by_id.get(operation_ref["id"])
                if not isinstance(invoked, dict):
                    visiting.remove(operation_id)
                    return None
                nested = operation_outcomes(invoked, visiting)
                if nested is None:
                    visiting.remove(operation_id)
                    return None
                arguments = instruction.get("arguments")
                invoked_formal_ports = invoked.get("inputs")
                result_binding = instruction.get("result")
                mappings = instruction.get("outcomes")
                callee_outcomes = invoked.get("outcomes")
                if (
                    not isinstance(arguments, list)
                    or not isinstance(invoked_formal_ports, list)
                    or not all(
                        isinstance(argument, dict)
                        and set(argument) == {"port", "operand"}
                        and isinstance(argument.get("port"), str)
                        and isinstance(argument.get("operand"), dict)
                        and argument["operand"].get("kind")
                        in set(invocation["operand_kinds"])
                        for argument in arguments
                    )
                    or [argument["port"] for argument in arguments]
                    != [port.get("id") for port in invoked_formal_ports]
                    or not isinstance(result_binding, dict)
                    or result_binding.get("kind")
                    not in set(invocation["result_binding_kinds"])
                    or not isinstance(mappings, list)
                    or not isinstance(callee_outcomes, list)
                    or [mapping.get("outcome") for mapping in mappings]
                    != [outcome.get("id") for outcome in callee_outcomes]
                ):
                    visiting.remove(operation_id)
                    return None
                if result_binding["kind"] == "discard" and not invoked.get(
                    "result", {}
                ).get("discardable"):
                    visiting.remove(operation_id)
                    return None
                for mapping in mappings:
                    action = mapping.get("action")
                    if (
                        not isinstance(mapping, dict)
                        or set(mapping) != {"outcome", "action"}
                        or not isinstance(action, dict)
                        or action.get("kind") not in set(invocation["outcome_actions"])
                        or (action["kind"] == "continue" and set(action) != {"kind"})
                        or (
                            action["kind"] == "propagate"
                            and (
                                set(action) != {"kind", "outcome"}
                                or not isinstance(action.get("outcome"), str)
                            )
                        )
                    ):
                        visiting.remove(operation_id)
                        return None
                    if action["kind"] == "propagate":
                        referenced.add(action["outcome"])
            result_binding = instruction.get("result")
            if (
                isinstance(result_binding, dict)
                and result_binding.get("kind") == "local"
            ):
                local_name = result_binding.get("name")
                if (
                    not isinstance(local_name, str)
                    or not local_name
                    or local_name in local_result_kinds
                ):
                    visiting.remove(operation_id)
                    return None
                local_result_kinds[local_name] = node["result"]["kind"]
        visiting.remove(operation_id)
        return referenced

    for operation in operations:
        if not isinstance(operation, dict):
            return False
        operation_kind = operation.get("operation_kind")
        if operation_kind not in {"event-program", "event-fragment"}:
            continue
        inputs = operation.get("inputs")
        result = operation.get("result")
        numeric_input_members = {
            "id",
            "type",
            "representation",
            "kind",
            "unit",
            "domain",
            "numeric_policy",
            "access",
        }
        structured_input_members = {"id", "type", "value_kind", "access"}
        numeric_result_members = numeric_input_members | {"discardable", "source"}
        structured_result_members = structured_input_members | {
            "discardable",
            "source",
        }
        if (
            not isinstance(inputs, list)
            or len({item.get("id") for item in inputs if isinstance(item, dict)})
            != len(inputs)
            or any(
                not isinstance(item, dict)
                or set(item) not in (numeric_input_members, structured_input_members)
                or (
                    set(item) == structured_input_members
                    and item.get("value_kind") != "nominal-structured"
                )
                or not isinstance(item.get("id"), str)
                or item.get("access") not in {"read", "read-write", "write"}
                for item in inputs
            )
            or not isinstance(result, dict)
            or set(result) not in (numeric_result_members, structured_result_members)
            or (
                set(result) == structured_result_members
                and result.get("value_kind") != "nominal-structured"
            )
            or result.get("access") != "read"
            or not isinstance(result.get("discardable"), bool)
            or not _operation_result_source_shape_is_closed(
                operation, invocation["result_source_shapes"]
            )
        ):
            return False
        referenced = operation_outcomes(operation, set())
        if referenced is None:
            return False
        declared = operation.get("outcomes")
        default = operation.get("default_outcome")
        if (
            not isinstance(declared, list)
            or not declared
            or not isinstance(default, str)
            or len({row.get("id") for row in declared}) != len(declared)
            or any(
                not isinstance(row, dict)
                or set(row) != {"id", "kind", "state_policy"}
                or not isinstance(row.get("id"), str)
                or row.get("kind") not in kinds
                or row.get("state_policy") not in policies
                for row in declared
            )
        ):
            return False
        by_id = {row["id"]: row for row in declared}
        if (
            default not in by_id
            or by_id[default]["kind"] != "success"
            or referenced != set(by_id) - {default}
        ):
            return False
    return True
