"""Independent bootstrap and mutation conformance for the permanent authority.

Consumer B below intentionally imports no production bootstrap or canonical
code.  Agreement is over public artifact bytes and observable inventories,
not shared helper behavior.
"""

import hashlib


import json


import re


from copy import deepcopy


from functools import cache


from typing import Any, cast


import jsonschema


import pytest


from gda_balancing.domain.authority.graph import (
    LanguageBundleGraph,
    LanguageBundleIndex,
    derive_language_index,
)


_SUPPORTED_KERNEL_IDENTITY = (
    "sha256:53ba784725ff78d51d0dd00b8e0de8b2c7c183c790358e2924fc93fcb207812c"
)
_SUPPORTED_RUNTIME_COMPONENT_CONTRACT_IDENTITY = (
    "sha256:5884a044e531d0a94c93e203a9644ea6d9d845154592ff714636a6032c8a7798"
)


def _identity(domain: str, artifact: dict[str, Any]) -> str:
    graph_root = getattr(artifact, "root", None)
    if domain == "language-definition-bundle-v2" and isinstance(graph_root, dict):
        artifact = graph_root
    body = {key: value for key, value in artifact.items() if key != "content_identity"}
    encoded = _encoded(body)
    return (
        "sha256:"
        + hashlib.sha256(f"gda-balancing:{domain}:".encode() + encoded).hexdigest()
    )


def _reidentify_package_release(package: dict[str, Any]) -> None:
    runtime_paths = set(package["runtime_semantic_paths"])
    excluded = set(package["runtime_semantic_excluded_extensions"])
    runtime_closure = deepcopy(
        [
            entry
            for entry in package["semantic_closure"]
            if entry["authority_path"] in runtime_paths
        ]
    )
    for entry in runtime_closure:
        for definition in entry["definitions"]:
            if not isinstance(definition, dict) or not isinstance(
                definition.get("extensions"), dict
            ):
                continue
            retained = {
                key: value
                for key, value in definition["extensions"].items()
                if key not in excluded
            }
            if retained:
                definition["extensions"] = retained
            else:
                definition.pop("extensions")
    package["semantic_identity"] = (
        "sha256:"
        + hashlib.sha256(
            b"gda-balancing:domain-package-semantic-closure-v2:"
            + _encoded(runtime_closure)
        ).hexdigest()
    )
    package["content_identity"] = _identity("domain-package-release-v2", package)


def _reidentify_package_vector_set(vector_set: dict[str, Any]) -> None:
    vector_set["content_identity"] = _identity(
        "package-conformance-vector-set-v2", vector_set
    )


def _bind_package_vector_set(
    package: dict[str, Any], vector_set: dict[str, Any]
) -> None:
    _reidentify_package_vector_set(vector_set)
    package["conformance_vectors"] = {
        "artifact_kind": vector_set["artifact_kind"],
        "byte_size": len(_encoded(vector_set)),
        "content_identity": vector_set["content_identity"],
    }
    _reidentify_package_release(package)


def _package_vector_set(
    ldb: LanguageBundleIndex, package: dict[str, Any]
) -> dict[str, Any]:
    return next(
        vector_set
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == package["id"]
        and vector_set["package_version"] == package["version"]
    )


def _owned_vector(ldb: LanguageBundleIndex, vector_id: str) -> dict[str, Any]:
    return next(
        vector
        for vector_set in ldb.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector["id"] == vector_id
    )


def _safe_identity(domain: str, artifact: dict[str, Any]) -> str | None:
    try:
        return _identity(domain, artifact)
    except (TypeError, ValueError, UnicodeEncodeError):
        return None


def _identity_from_kernel(
    kernel: dict[str, Any], domain: str, artifact: dict[str, Any]
) -> str | None:
    recipe = kernel.get("canonical_encoding")
    try:
        supported = _consumer_b_canonical_contract_supported(recipe)
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    if not supported:
        return None
    assert isinstance(recipe, dict)
    expected = {
        "array_order": "preserve",
        "character_encoding": "UTF-8",
        "control_character_escaping": {
            "backspace": "\\b",
            "carriage-return": "\\r",
            "form-feed": "\\f",
            "line-feed": "\\n",
            "other-u0000-u001f": "lowercase-u00xx",
            "tab": "\\t",
        },
        "delete_character_escaping": "literal-byte-7f",
        "digest_hex_case": "lowercase",
        "document_terminator": "LF",
        "duplicate_object_keys": "refuse-at-decoding",
        "escape_solidus": False,
        "identity_algorithm": "sha256",
        "identity_domain_prefix": "gda-balancing:",
        "identity_domain_suffix": ":",
        "identity_excluded_members": ["content_identity"],
        "identity_output_prefix": "sha256:",
        "integer_domain": "signed-int64",
        "item_separator": ",",
        "key_separator": ":",
        "lone_surrogate": "refuse",
        "non_ascii_strings": "literal-utf8",
        "number_kinds": ["signed-int64"],
        "object_order": "UTF-8-key-byte-order",
        "optional_members": "omit",
        "printable_ascii_escaping": "only-quotation-mark-and-reverse-solidus",
        "profile": "gda-canonical-json-v1",
        "unicode_normalization": "preserve",
        "whitespace": "none",
    }
    if {key: value for key, value in recipe.items() if key != "vectors"} != expected:
        return None
    excluded = set(recipe["identity_excluded_members"])
    body = {key: value for key, value in artifact.items() if key not in excluded}
    try:
        encoded = _encoded(body)
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    prefix = (
        recipe["identity_domain_prefix"] + domain + recipe["identity_domain_suffix"]
    ).encode(recipe["character_encoding"])
    digest = hashlib.new(recipe["identity_algorithm"], prefix + encoded).hexdigest()
    if recipe["digest_hex_case"] == "lowercase":
        digest = digest.lower()
    return recipe["identity_output_prefix"] + digest


def _declared_identity_domain(
    kernel: dict[str, Any],
    *,
    artifact: str | None = None,
    collection: str | None = None,
) -> str | None:
    if (artifact is None) == (collection is None):
        return None
    laws = kernel.get("admission", {}).get("laws")
    identity_laws = (
        [
            law
            for law in laws
            if isinstance(law, dict) and law.get("id") == "kernel.identity.verify"
        ]
        if isinstance(laws, list)
        else []
    )
    if len(identity_laws) != 1:
        return None
    targets = identity_laws[0].get("arguments", {}).get("targets")
    selector = "artifact" if artifact is not None else "collection"
    expected = artifact if artifact is not None else collection
    matches = (
        [
            target
            for target in targets
            if isinstance(target, dict) and target.get(selector) == expected
        ]
        if isinstance(targets, list)
        else []
    )
    if len(matches) != 1:
        return None
    target = matches[0]
    domain = target.get("domain")
    if (
        target.get("identity_member") != "content_identity"
        or not isinstance(domain, str)
        or not domain
    ):
        return None
    return domain


def _encoded(value: Any) -> bytes:
    _validate_canonical(value)
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _validate_canonical(value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        value.encode("utf-8")
        return
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValueError("integer is outside signed Int64")
        return
    if isinstance(value, list):
        for item in value:
            _validate_canonical(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical object key is not a string")
            _validate_canonical(key)
            _validate_canonical(item)
        return
    raise TypeError("value is outside canonical JSON")


def _consumer_b_canonical_contract_supported(recipe: Any) -> bool:
    if not isinstance(recipe, dict) or not isinstance(recipe.get("vectors"), list):
        return False

    def reject_number(_value: str) -> Any:
        raise ValueError("non-integer number")

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    expected_ids = {
        "canonical.boundary-integers",
        "canonical.control-character-escaping",
        "canonical.order-array-unicode-escaping",
        "canonical.reject-duplicate-key",
        "canonical.reject-float",
        "canonical.reject-lone-surrogate",
    }
    vectors = recipe["vectors"]
    if {item.get("id") for item in vectors if isinstance(item, dict)} != expected_ids:
        return False
    for vector in vectors:
        if not isinstance(vector, dict):
            return False
        if "value" in vector:
            value = vector["value"]
            domain = vector.get("domain")
            if not isinstance(domain, str):
                return False
            encoded = _encoded(value)
            identity = (
                "sha256:"
                + hashlib.sha256(
                    f"gda-balancing:{domain}:".encode() + encoded
                ).hexdigest()
            )
            if encoded.hex() != vector.get(
                "canonical_utf8_hex"
            ) or identity != vector.get("identity"):
                return False
        else:
            lexeme = vector.get("input_lexeme")
            if not isinstance(lexeme, str):
                return False
            try:
                value = json.loads(
                    lexeme,
                    object_pairs_hook=closed_object,
                    parse_float=reject_number,
                    parse_constant=reject_number,
                )
                _encoded(value)
            except (TypeError, ValueError, UnicodeEncodeError):
                continue
            return False
    return True


def _shape(value: Any) -> tuple[int, int]:
    depth = 0
    members = 0
    stack = [(value, 0)]
    while stack:
        current, current_depth = stack.pop()
        depth = max(depth, current_depth)
        if isinstance(current, dict):
            members = max(members, len(current))
            stack.extend((item, current_depth + 1) for item in current.values())
        elif isinstance(current, list):
            members = max(members, len(current))
            stack.extend((item, current_depth + 1) for item in current)
    return depth, members


def _work(value: Any) -> int:
    work = 0
    stack = [value]
    while stack:
        current = stack.pop()
        work += 1
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return work


def _consumer_b_package_is_closed(
    package: dict[str, Any], contract: Any, ldb: dict[str, Any]
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
            _consumer_b_value_matches(package[name], field_types[name], ldb)
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
                _consumer_b_value_matches(value[member], member_types[member], ldb)
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
                _consumer_b_value_matches(item[name], export_field_types[name], ldb)
                for name in export_members
            )
            for item in exported_types
        )
    )


_CONSUMER_B_PACKAGE_VECTOR_CATEGORIES = (
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


_CONSUMER_B_PACKAGE_VECTOR_KIND_MEMBERS = {
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
    "operation-execution": {
        "completion_members",
        "expect_members",
        "id",
        "input_members",
        "required_members",
        "result_members",
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
    "structured-value": {
        "actions",
        "expect_members",
        "id",
        "input_members",
        "required_members",
    },
    "replay-comparison": {
        "check_members",
        "expect_members",
        "id",
        "input_members",
        "observation_members",
        "required_members",
        "results",
    },
}


def _consumer_b_package_vector_contract_is_closed(contract: Any) -> bool:
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
        or contract.get("categories") != list(_CONSUMER_B_PACKAGE_VECTOR_CATEGORIES)
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
        != [
            "capabilities",
            "dependencies",
            "exports",
            "profiles",
            "semantic_closure",
        ]
        or not isinstance(contract.get("kinds"), list)
    ):
        return False
    kinds: dict[str, dict[str, Any]] = {}
    for item in contract["kinds"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            kinds[cast(str, item["id"])] = item
    if set(kinds) != set(_CONSUMER_B_PACKAGE_VECTOR_KIND_MEMBERS):
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
        "operation-execution": {
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
        "structured-value": {
            "category",
            "expect",
            "id",
            "input",
            "kind",
        },
        "replay-comparison": {
            "category",
            "expect",
            "id",
            "input",
            "kind",
            "policy",
        },
    }
    for kind_id, kind in kinds.items():
        if set(kind) != _CONSUMER_B_PACKAGE_VECTOR_KIND_MEMBERS[kind_id] or kind.get(
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
        and kinds["operation-execution"].get("input_members") == ["seed", "values"]
        and kinds["operation-execution"].get("expect_members")
        == ["completion", "result", "rng_draws", "state_after"]
        and kinds["operation-execution"].get("completion_members")
        == ["id", "kind", "reason"]
        and kinds["operation-execution"].get("result_members") == ["kind", "value"]
        and kinds["operation-execution"].get("rng_draw_members")
        == ["candidate_hex", "index", "stream", "value"]
        and kinds["operation-execution"].get("state_value_members") == ["name", "value"]
        and kinds["replay-comparison"].get("input_members") == ["original", "replay"]
        and kinds["replay-comparison"].get("observation_members")
        == [
            "evaluation_outcome_status",
            "event_trace_identity",
            "snapshot_series_identity",
            "metric_dataset_identity",
        ]
        and kinds["replay-comparison"].get("expect_members") == ["checks", "result"]
        and kinds["replay-comparison"].get("check_members")
        == ["key", "match", "original", "replay"]
        and kinds["replay-comparison"].get("results") == ["matched", "mismatched"]
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
        and kinds["structured-value"].get("actions")
        == ["admit", "equal", "is-empty", "lookup"]
        and kinds["structured-value"].get("input_members")
        == ["action", "key", "left", "limit", "right"]
        and kinds["structured-value"].get("expect_members")
        == ["code", "outcome", "pointer", "type", "value"]
    )


def _consumer_b_canonical_equal(left: Any, right: Any) -> bool:
    try:
        return _encoded(left) == _encoded(right)
    except (TypeError, ValueError, UnicodeEncodeError):
        return False


def _consumer_b_replay_comparison_vector_is_closed(
    package: dict[str, Any], vector: dict[str, Any], kind: dict[str, Any]
) -> bool:
    policy_entry = next(
        (
            entry
            for entry in package.get("semantic_closure", [])
            if isinstance(entry, dict)
            and entry.get("authority_path") == "language.replay_comparison_policies"
        ),
        None,
    )
    policies = (
        policy_entry.get("definitions") if isinstance(policy_entry, dict) else None
    )
    policy = (
        next(
            (
                item
                for item in policies
                if isinstance(item, dict) and item.get("id") == vector.get("policy")
            ),
            None,
        )
        if isinstance(policies, list)
        else None
    )
    inp = vector.get("input")
    expect = vector.get("expect")
    if (
        not isinstance(policy, dict)
        or policy.get("comparator") != "canonical-equal"
        or not isinstance(policy.get("checks"), list)
        or not policy["checks"]
        or not isinstance(inp, dict)
        or set(inp) != set(kind["input_members"])
        or not isinstance(expect, dict)
        or set(expect) != set(kind["expect_members"])
        or expect.get("result") not in kind["results"]
        or not isinstance(expect.get("checks"), list)
    ):
        return False
    observation_members = cast(list[str], kind["observation_members"])
    original = inp.get("original")
    replay = inp.get("replay")
    if (
        not isinstance(original, dict)
        or set(original) != set(observation_members)
        or not isinstance(replay, dict)
        or set(replay) != set(observation_members)
    ):
        return False
    observed_checks = [
        {
            "key": member.replace("_", "-"),
            "match": _consumer_b_canonical_equal(original[member], replay[member]),
            "original": original[member],
            "replay": replay[member],
        }
        for member in observation_members
    ]
    matched = all(check["match"] for check in observed_checks)
    return (
        policy["checks"] == [check["key"] for check in observed_checks]
        and _consumer_b_canonical_equal(expect["checks"], observed_checks)
        and expect["result"] == ("matched" if matched else "mismatched")
    )


def _consumer_b_signed_int64(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and -(2**63) <= value <= 2**63 - 1
    )


def _consumer_b_operation_relation_is_satisfied(
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
    if len(matches) != 1 or not _consumer_b_canonical_equal(
        probe, matches[0].get("probe")
    ):
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
        return _consumer_b_canonical_equal(left, right)
    if operator == "schedule-projection-equal":
        projection_members = kind.get("schedule_projection_members")
        schedule_nodes = {
            node.get("id")
            for node in runtime_nodes
            if isinstance(node, dict)
            if isinstance(node.get("semantics"), dict)
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
        return _consumer_b_canonical_equal(projected, right)
    if operator == "integer-range-equal":
        range_members = kind.get("integer_range_members")
        if (
            not isinstance(range_members, list)
            or len(range_members) != 3
            or not isinstance(right, dict)
            or set(right) != set(range_members)
            or not isinstance(left, list)
            or not all(_consumer_b_signed_int64(item) for item in left)
        ):
            return False
        range_paths = [member_path(right.get(member)) for member in range_members]
        if any(path is None or path[0] not in roots for path in range_paths):
            return False
        range_values: list[int] = []
        for path in range_paths:
            declared, value = observed(cast(list[str], path))
            if not declared or not _consumer_b_signed_int64(value):
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
    if not _consumer_b_signed_int64(left) or not _consumer_b_signed_int64(right):
        return False
    return (
        left == right
        if operator == "integer-equal"
        else left > right
        if operator == "integer-greater-than"
        else left <= right
    )


def _consumer_b_value_program_instruction_is_closed(
    row: Any,
    allowed_nodes: set[str],
) -> bool:
    if not isinstance(row, dict) or len(row) != 2:
        return False
    site = row.get("evaluation_site_identity")
    instruction = row.get("instruction")
    if not isinstance(site, str) or not site or not isinstance(instruction, dict):
        return False

    operand_fields = {
        "copy": ("value",),
        "add": ("left", "right"),
        "maximum": ("left", "right"),
        "multiply": ("left", "right"),
        "subtract": ("left", "right"),
        "if": ("condition", "when_true", "when_false"),
    }
    node = instruction.get("node")
    if not isinstance(node, str) or node not in allowed_nodes:
        return False
    fields = ("literal",) if node == "constant" else operand_fields.get(node)
    if fields is None or set(instruction) != {"node", "target", *fields}:
        return False
    target = instruction.get("target")
    if not isinstance(target, str) or not target:
        return False
    if node == "constant":
        return _consumer_b_signed_int64(instruction.get("literal"))
    return all(
        isinstance(value, str) and bool(value)
        for value in (instruction.get(field) for field in fields)
    )


def _consumer_b_scheduler_scenario_vector_is_closed(
    vector: dict[str, Any], kind: dict[str, Any], phases: set[str]
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
            and _consumer_b_signed_int64(row.get("value"))
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
            and _consumer_b_signed_int64(row.get("logical_time"))
            and isinstance(row.get("phase"), str)
            and row["phase"] in phases
            and _consumer_b_signed_int64(row.get("priority"))
            and isinstance(row.get("enqueue_sequence"), int)
            and not isinstance(row["enqueue_sequence"], bool)
            and row["enqueue_sequence"] >= 0
            and _consumer_b_signed_int64(row.get("state_delta"))
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
            and _consumer_b_signed_int64(row.get("state_before"))
            and _consumer_b_signed_int64(row.get("state_after"))
            for row in observations
        )
        and isinstance(terminal_states, list)
        and [row.get("scenario") for row in terminal_states] == scenarios
        and all(
            isinstance(row, dict)
            and set(row) == set(kind["state_value_members"])
            and _consumer_b_signed_int64(row.get("value"))
            for row in terminal_states
        )
    )


def _consumer_b_package_vector_set_is_closed(
    vector_set: dict[str, Any], contract: Any
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
        and all(
            _consumer_b_value_matches(vector_set[name], field_types[name], vector_set)
            for name in expected_members
        )
        and len(vector_set["vectors"]) == len(set(vector_set["vectors"]))
    )


def _consumer_b_operation_value_contract_matches(
    actual: dict[str, Any], formal: dict[str, Any]
) -> bool:
    if not _consumer_b_canonical_equal(actual.get("type"), formal.get("type")):
        return False
    if "value_kind" in actual or "value_kind" in formal:
        return actual.get("value_kind") == formal.get("value_kind")
    return all(
        _consumer_b_canonical_equal(actual.get(member), formal.get(member))
        for member in ("representation", "kind", "unit", "domain", "numeric_policy")
    )


def _consumer_b_operation_value_is_admitted(
    value: Any,
    formal: dict[str, Any],
    *,
    ldb: dict[str, Any],
    kernel: dict[str, Any],
    resource_limit: int,
) -> bool:
    language = ldb.get("language")
    profiles = (
        language.get("literal_typing_profiles") if isinstance(language, dict) else None
    )
    literal_typing = kernel.get("meta_format", {}).get("literal_typing")
    typed_contract = (
        literal_typing.get("typed_envelope_profile")
        if isinstance(literal_typing, dict)
        else None
    )
    runtime = kernel.get("meta_format", {}).get("runtime_program")
    fixed = runtime.get("fixed_value_contracts") if isinstance(runtime, dict) else None
    if (
        not isinstance(profiles, list)
        or not isinstance(typed_contract, dict)
        or not isinstance(fixed, dict)
    ):
        return False
    contracts: list[dict[str, Any]] = []
    if value is None:
        unit = fixed.get("kernel-unit")
        if isinstance(unit, dict):
            contracts.append(unit)
    elif isinstance(value, bool):
        boolean = fixed.get("kernel-boolean")
        if isinstance(boolean, dict):
            contracts.append(boolean)
    elif isinstance(value, int):
        contracts.extend(
            profile
            for profile in profiles
            if isinstance(profile, dict)
            and profile.get("source_kind") == "integer"
            and type(profile.get("minimum")) is int
            and type(profile.get("maximum")) is int
            and profile["minimum"] <= value <= profile["maximum"]
        )
    elif isinstance(value, dict):
        admission = typed_contract.get("admission")
        envelope_members = (
            admission.get("envelope_members") if isinstance(admission, dict) else None
        )
        type_member = typed_contract.get("type_member")
        value_member = typed_contract.get("value_member")
        reference = (
            admission.get("nominal_type_reference")
            if isinstance(admission, dict)
            else None
        )
        coordinate_members = (
            reference.get("coordinate_members") if isinstance(reference, dict) else None
        )
        optional_kind = (
            reference.get("optional_kind_member")
            if isinstance(reference, dict)
            else None
        )
        optional_value = (
            reference.get("optional_kind_value")
            if isinstance(reference, dict)
            else None
        )
        if (
            isinstance(envelope_members, list)
            and isinstance(type_member, str)
            and isinstance(value_member, str)
            and set(value) == set(envelope_members) == {type_member, value_member}
            and coordinate_members == ["package", "version", "id"]
            and isinstance(optional_kind, str)
            and isinstance(optional_value, str)
            and isinstance(value[type_member], dict)
        ):
            type_expression = value[type_member]
            expected_members = {"package", "version", "id"}
            if optional_kind in type_expression:
                expected_members.add(optional_kind)
            coordinate = tuple(
                type_expression.get(member) for member in ("package", "version", "id")
            )
            if (
                set(type_expression) == expected_members
                and all(isinstance(item, str) and item for item in coordinate)
                and (
                    optional_kind not in type_expression
                    or type_expression[optional_kind] == optional_value
                )
                and len(
                    [
                        profile
                        for profile in profiles
                        if isinstance(profile, dict)
                        and profile.get("source_kind") == "typed-envelope"
                        and profile.get("value_kind") == "nominal-structured"
                    ]
                )
                == 1
            ):
                package, version, type_id = cast(tuple[str, str, str], coordinate)
                contracts.append(
                    {
                        "type": {
                            "id": type_id,
                            "package": package,
                            "version": version,
                        },
                        "value_kind": "nominal-structured",
                    }
                )
    matches = [
        contract
        for contract in contracts
        if _consumer_b_operation_value_contract_matches(contract, formal)
    ]
    if len(matches) != 1:
        return False
    if not isinstance(value, dict):
        return True
    packages = language.get("packages") if isinstance(language, dict) else None
    if not isinstance(packages, list):
        return False
    observed = _consumer_b_evaluate_structured_value_vector(
        {
            "input": {
                "action": "admit",
                "key": None,
                "left": value,
                "limit": None,
                "right": None,
            }
        },
        nominal_types=packages,
        kernel=kernel,
        resource_limit=resource_limit,
    )
    return observed.get("outcome") == "admitted"


def _consumer_b_package_evidence_vectors_are_closed(
    package: dict[str, Any],
    vector_set: dict[str, Any],
    contract: Any,
    candidate_encoding: Any,
    runtime_program: Any,
    kernel: dict[str, Any],
    ldb: dict[str, Any],
) -> bool:
    scheduler = (
        runtime_program.get("scheduler") if isinstance(runtime_program, dict) else None
    )
    runtime_nodes = (
        runtime_program.get("nodes") if isinstance(runtime_program, dict) else None
    )
    ordering = scheduler.get("ordering") if isinstance(scheduler, dict) else None
    phase_row = (
        next(
            (
                row
                for row in ordering
                if isinstance(row, dict) and row.get("member") == "phase"
            ),
            None,
        )
        if isinstance(ordering, list)
        else None
    )
    phase_rank = phase_row.get("rank") if isinstance(phase_row, dict) else None
    language = ldb.get("language")
    literal_typing = kernel.get("meta_format", {}).get("literal_typing")
    literal_profiles = (
        language.get("literal_typing_profiles") if isinstance(language, dict) else None
    )
    typed_envelope_contract = (
        literal_typing.get("typed_envelope_profile")
        if isinstance(literal_typing, dict)
        else None
    )
    fixed_value_contracts = (
        runtime_program.get("fixed_value_contracts")
        if isinstance(runtime_program, dict)
        else None
    )
    resource_limit = kernel.get("resources", {}).get("max_ldb_admission_work")
    if (
        not _consumer_b_package_vector_contract_is_closed(contract)
        or not isinstance(candidate_encoding, dict)
        or candidate_encoding.get("radix") != 16
        or candidate_encoding.get("zero_pad") is not True
        or not isinstance(candidate_encoding.get("width_bits"), int)
        or candidate_encoding["width_bits"] % 4 != 0
        or not isinstance(candidate_encoding.get("alphabet"), str)
        or not candidate_encoding["alphabet"]
        or not isinstance(phase_rank, list)
        or not phase_rank
        or any(not isinstance(phase, str) or not phase for phase in phase_rank)
        or not isinstance(runtime_nodes, list)
        or not all(isinstance(node, dict) for node in runtime_nodes)
        or not isinstance(literal_profiles, list)
        or not isinstance(typed_envelope_contract, dict)
        or not isinstance(fixed_value_contracts, dict)
        or not isinstance(resource_limit, int)
        or isinstance(resource_limit, bool)
        or resource_limit < 1
    ):
        return False
    phases = set(phase_rank)
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
            for item in package.get("semantic_closure", [])
            if isinstance(item, dict)
            and item.get("authority_path") == "language.operations"
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
            declared, observed = _consumer_b_exact_path(package, probe["path"])
            if not declared or not _consumer_b_canonical_equal(
                observed, vector.get("expect")
            ):
                return False
            continue
        if kind_id == "replay-comparison":
            if not _consumer_b_replay_comparison_vector_is_closed(
                package, vector, kind
            ):
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
                    _consumer_b_value_program_instruction_is_closed(row, allowed_nodes)
                    for row in inp["instructions"]
                )
                or not isinstance(inp.get("numeric"), dict)
                or set(inp["numeric"]) != {"maximum", "minimum"}
                or not _consumer_b_signed_int64(inp["numeric"].get("minimum"))
                or not _consumer_b_signed_int64(inp["numeric"].get("maximum"))
                or inp["numeric"]["minimum"] > inp["numeric"]["maximum"]
                or not isinstance(inp.get("operands"), list)
                or not all(
                    isinstance(row, dict)
                    and set(row) == {"name", "value"}
                    and isinstance(row.get("name"), str)
                    and bool(row["name"])
                    and _consumer_b_signed_int64(row.get("value"))
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
                        and _consumer_b_signed_int64(expect.get("result"))
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
            if not _consumer_b_scheduler_scenario_vector_is_closed(
                vector, kind, phases
            ):
                return False
            continue
        if kind_id == "structured-value":
            inp = vector.get("input")
            expect = vector.get("expect")
            if (
                not isinstance(inp, dict)
                or set(inp) != set(kind["input_members"])
                or inp.get("action") not in kind["actions"]
                or not (
                    inp.get("limit") is None
                    or (
                        isinstance(inp["limit"], int)
                        and not isinstance(inp["limit"], bool)
                        and inp["limit"] > 0
                    )
                )
                or not isinstance(expect, dict)
                or set(expect) != set(kind["expect_members"])
                or expect.get("outcome") not in {"admitted", "refused"}
                or not (
                    (expect["outcome"] == "admitted" and expect.get("code") is None)
                    or (
                        expect["outcome"] == "refused"
                        and isinstance(expect.get("code"), str)
                        and bool(expect["code"])
                        and isinstance(expect.get("pointer"), str)
                    )
                )
            ):
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
            declared, observed = _consumer_b_exact_path(operation, probe["path"])
            if not declared or not _consumer_b_canonical_equal(
                observed, vector.get("expect")
            ):
                return False
            continue
        if kind_id == "operation-relation":
            if not _consumer_b_operation_relation_is_satisfied(
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
            or not _consumer_b_signed_int64(inp.get("seed"))
            or not isinstance(inp.get("values"), list)
            or not isinstance(expect, dict)
            or set(expect) != set(kind["expect_members"])
            or not isinstance(expect.get("completion"), dict)
            or not isinstance(expect.get("result"), dict)
            or not isinstance(expect.get("state_after"), list)
            or not isinstance(expect.get("rng_draws"), list)
        ):
            return False
        values = inp["values"]
        operation_inputs = [
            item for item in operation.get("inputs", []) if isinstance(item, dict)
        ]
        value_names = [item.get("name") for item in values if isinstance(item, dict)]
        if (
            not all(
                isinstance(item, dict)
                and set(item) == {"name", "value"}
                and isinstance(item.get("name"), str)
                and item["name"]
                and _consumer_b_operation_value_is_admitted(
                    item.get("value"),
                    formal,
                    ldb=ldb,
                    kernel=kernel,
                    resource_limit=resource_limit,
                )
                for item, formal in zip(values, operation_inputs, strict=False)
            )
            or len(values) != len(operation_inputs)
            or value_names != [item.get("id") for item in operation_inputs]
        ):
            return False
        state_inputs = [
            item for item in operation_inputs if item.get("access") == "read-write"
        ]
        state_after = expect["state_after"]
        if (
            not all(
                isinstance(item, dict)
                and set(item) == set(kind["state_value_members"])
                and isinstance(item.get("name"), str)
                and _consumer_b_operation_value_is_admitted(
                    item.get("value"),
                    formal,
                    ldb=ldb,
                    kernel=kernel,
                    resource_limit=resource_limit,
                )
                for item, formal in zip(state_after, state_inputs, strict=False)
            )
            or len(state_after) != len(state_inputs)
            or [item["name"] for item in state_after]
            != [item.get("id") for item in state_inputs]
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
            and _consumer_b_signed_int64(item.get("value"))
            for item in draws
        ):
            return False
        outcomes = {
            item.get("id"): item
            for item in operation.get("outcomes", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        refusals = operation.get("refusals")
        completion = expect["completion"]
        result = expect["result"]
        if completion.get("kind") == "outcome":
            outcome = outcomes.get(completion.get("id"))
            if set(completion) != {"id", "kind"} or not isinstance(outcome, dict):
                return False
            produces_result = outcome.get("kind") == "success"
        elif completion.get("kind") == "refusal":
            if (
                set(completion) != {"kind", "reason"}
                or not isinstance(refusals, list)
                or completion.get("reason") not in refusals
            ):
                return False
            produces_result = False
        else:
            return False
        if produces_result:
            if (
                set(result) != {"kind", "value"}
                or result.get("kind") != "value"
                or not isinstance(operation.get("result"), dict)
                or not _consumer_b_operation_value_is_admitted(
                    result.get("value"),
                    cast(dict[str, Any], operation["result"]),
                    ldb=ldb,
                    kernel=kernel,
                    resource_limit=resource_limit,
                )
            ):
                return False
        elif result != {"kind": "not-produced"}:
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
            for item in package.get("semantic_closure", [])
            if isinstance(item, dict)
            and item.get("authority_path") == policy_authority_path
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
            if not _consumer_b_canonical_equal(
                observed, contract_probe.get("expect")
            ) or not _consumer_b_canonical_equal(declarations, relations):
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
        in {"operation-contract", "operation-relation", "operation-execution"}
    }
    referenced = {
        vector_id
        for operation in operations.values()
        for vector_id in operation["vectors"]
        if vector_id in evidence_ids
    }
    return referenced == operation_evidence_ids


def _consumer_b_package_evidence_vector_header_is_closed(
    vector: dict[str, Any],
    contract: Any,
) -> bool:
    if not _consumer_b_package_vector_contract_is_closed(contract):
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


def _consumer_b_package_semantic_closure_is_closed(
    package: dict[str, Any], contract: Any
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
            or not _consumer_b_path_is_declared(package, owners_path)
        ):
            return False
        definitions = entry["definitions"]
        owned_values = _project(package, owners_path)

        def definition_key(value: Any) -> bytes | None:
            selected = value
            if key_member is not None:
                if not isinstance(value, dict) or key_member not in value:
                    return None
                selected = value[key_member]
            try:
                return _encoded(selected)
            except (TypeError, ValueError, UnicodeEncodeError):
                return None

        def owner_key(value: Any) -> bytes | None:
            try:
                return _encoded(value)
            except (TypeError, ValueError, UnicodeEncodeError):
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
    excluded_extensions = package.get(semantic_projection["extension_inventory_member"])
    if (
        not isinstance(excluded_extensions, list)
        or not all(isinstance(item, str) and item for item in excluded_extensions)
        or len(excluded_extensions) != len(set(excluded_extensions))
    ):
        return False
    runtime_closure = deepcopy(
        [entry for entry in closure if entry["authority_path"] in set(runtime_paths)]
    )
    found_extensions: set[str] = set()
    excluded = set(excluded_extensions)
    for entry in runtime_closure:
        for definition in entry["definitions"]:
            if not isinstance(definition, dict) or not isinstance(
                definition.get("extensions"), dict
            ):
                continue
            found_extensions.update(excluded & set(definition["extensions"]))
            retained = {
                key: value
                for key, value in definition["extensions"].items()
                if key not in excluded
            }
            if retained:
                definition["extensions"] = retained
            else:
                definition.pop("extensions")
    if found_extensions != excluded:
        return False
    try:
        encoded = _encoded(runtime_closure)
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    expected = (
        "sha256:"
        + hashlib.sha256(
            f"gda-balancing:{semantic_projection['domain']}:".encode() + encoded
        ).hexdigest()
    )
    return package.get("semantic_identity") == expected


def _consumer_b_package_semantic_projections_are_exact(
    packages: list[dict[str, Any]], contract: Any, ldb: dict[str, Any]
) -> bool:
    if not isinstance(contract, dict):
        return False
    closure_contract = contract.get("semantic_closure")
    projections = (
        closure_contract.get("projections")
        if isinstance(closure_contract, dict)
        else None
    )
    if not isinstance(projections, list):
        return False
    for index, projection in enumerate(projections):
        if not isinstance(projection, dict):
            return False
        authority_path = projection.get("authority_path")
        key_member = projection.get("key_member")
        declared, authority_definitions = _consumer_b_exact_path(ldb, authority_path)
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
                    return ("value", _encoded(value))
                except (TypeError, ValueError, UnicodeEncodeError):
                    return None
            if (
                not isinstance(key_member, str)
                or not isinstance(value, dict)
                or key_member not in value
            ):
                return None
            try:
                return ("member", _encoded(value[key_member]))
            except (TypeError, ValueError, UnicodeEncodeError):
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
        if dict(zip(embedded_keys, embedded, strict=True)) != dict(
            zip(authority_keys, authority_definitions, strict=True)
        ):
            return False
    return True


def _consumer_b_ldb_is_closed(
    ldb: dict[str, Any], contract: Any, refusal_stages: Any
) -> bool:
    if not isinstance(contract, dict) or contract.get("closed") is not True:
        return False
    required = contract.get("required_members")
    member_types = contract.get("member_types")
    diagnostic_contract = contract.get("diagnostic")
    resources_contract = contract.get("resources")
    if (
        not isinstance(required, list)
        or set(ldb) != set(required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required)
        or not isinstance(refusal_stages, list)
        or refusal_stages
        != [
            "ingress",
            "parse",
            "static",
            "resolution",
            "runtime",
            "evaluation",
            "migration",
            "approval",
        ]
    ):
        return False
    if not all(
        _consumer_b_value_matches(ldb[name], value_contract, ldb)
        for name, value_contract in member_types.items()
    ):
        return False
    if not isinstance(diagnostic_contract, dict):
        return False
    diagnostic_members = diagnostic_contract.get("required_members")
    diagnostic_types = diagnostic_contract.get("field_types")
    diagnostics = ldb.get("diagnostics")
    if (
        not isinstance(diagnostics, list)
        or not isinstance(diagnostic_members, list)
        or not isinstance(diagnostic_types, dict)
        or set(diagnostic_types) != set(diagnostic_members)
        or not all(
            isinstance(item, dict)
            and set(item) == set(diagnostic_members)
            and isinstance(item.get("code"), str)
            and bool(item["code"])
            and item.get("stage") in refusal_stages
            for item in diagnostics
        )
    ):
        return False
    if not isinstance(resources_contract, dict):
        return False
    resource_members = resources_contract.get("required_members")
    resource_types = resources_contract.get("field_types")
    resources = ldb.get("resources")
    return (
        isinstance(resources, dict)
        and isinstance(resource_members, list)
        and set(resources) == set(resource_members)
        and isinstance(resource_types, dict)
        and set(resource_types) == set(resource_members)
        and all(
            _consumer_b_value_matches(resources[name], resource_types[name], ldb)
            for name in resource_members
        )
    )


def _project(root: Any, dotted: Any) -> list[Any]:
    if not isinstance(dotted, str) or not dotted:
        return []
    values = [root]
    for part in dotted.split("."):
        projected: list[Any] = []
        for value in values:
            if not isinstance(value, dict) or part not in value:
                return []
            child = value[part]
            projected.extend(child if isinstance(child, list) else [child])
        values = projected
    return values


def _consumer_b_path_is_declared(root: Any, dotted: Any) -> bool:
    if not isinstance(dotted, str) or not dotted:
        return False

    def walk(value: Any, parts: list[str]) -> bool:
        if not parts:
            return True
        if not isinstance(value, dict) or parts[0] not in value:
            return False
        child = value[parts[0]]
        if isinstance(child, list):
            return all(walk(item, parts[1:]) for item in child)
        return walk(child, parts[1:])

    return walk(root, dotted.split("."))


def _consumer_b_profiled_equality_values(
    authorities: dict[str, Any], contract: dict[str, Any]
) -> list[Any] | None:
    profile_contract = contract.get("profile")
    template = contract.get("right_template")
    expected_profile_members = {
        "owner_profile_member",
        "owners",
        "profile_key_member",
        "profiles",
    }
    if (
        not isinstance(profile_contract, dict)
        or set(profile_contract) != expected_profile_members
        or not isinstance(template, list)
        or not template
    ):
        return None
    owners_path = profile_contract.get("owners")
    profiles_path = profile_contract.get("profiles")
    owner_member = profile_contract.get("owner_profile_member")
    key_member = profile_contract.get("profile_key_member")
    if (
        not _consumer_b_path_is_declared(authorities, owners_path)
        or not _consumer_b_path_is_declared(authorities, profiles_path)
        or not isinstance(owner_member, str)
        or not owner_member
        or not isinstance(key_member, str)
        or not key_member
    ):
        return None
    owners = _project(authorities, owners_path)
    profiles = _project(authorities, profiles_path)
    profile_index: dict[Any, dict[str, Any]] = {}
    for profile in profiles:
        if (
            not isinstance(profile, dict)
            or key_member not in profile
            or profile[key_member] in profile_index
        ):
            return None
        profile_index[profile[key_member]] = profile
    selected: list[dict[str, Any]] = []
    for owner in owners:
        if not isinstance(owner, dict) or owner.get(owner_member) not in profile_index:
            return None
        profile = profile_index[owner[owner_member]]
        if profile not in selected:
            selected.append(profile)
    if not selected:
        return None

    projected: list[Any] = []
    for profile in selected:
        values: list[Any] = [authorities]
        for raw_segment in template:
            if isinstance(raw_segment, str) and raw_segment:
                segment = raw_segment
            elif (
                isinstance(raw_segment, dict)
                and set(raw_segment) == {"profile_member"}
                and isinstance(raw_segment["profile_member"], str)
                and isinstance(profile.get(raw_segment["profile_member"]), str)
                and profile[raw_segment["profile_member"]]
            ):
                segment = profile[raw_segment["profile_member"]]
            else:
                return None
            next_values: list[Any] = []
            for value in values:
                for candidate in value if isinstance(value, list) else [value]:
                    if isinstance(candidate, dict) and segment in candidate:
                        child = candidate[segment]
                        next_values.extend(
                            child if isinstance(child, list) else [child]
                        )
            if not next_values:
                return None
            values = next_values
        projected.extend(values)
    return projected


def _consumer_b_exact_path(root: Any, dotted: Any) -> tuple[bool, Any]:
    if not isinstance(dotted, str) or not dotted:
        return False, None
    value = root
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _consumer_b_closed_json_schema(value: Any, contract: dict[str, Any]) -> bool:
    allowed = contract.get("allowed_keywords")
    closure_keyword = contract.get("object_closure_keyword")
    keyword_type_requirements = contract.get("keyword_type_requirements")
    if (
        not isinstance(value, dict)
        or not isinstance(allowed, list)
        or not all(isinstance(item, str) for item in allowed)
        or not isinstance(keyword_type_requirements, dict)
        or not all(
            isinstance(keyword, str)
            and isinstance(types, list)
            and types
            and all(isinstance(item, str) for item in types)
            for keyword, types in keyword_type_requirements.items()
        )
        or value.get("$schema") != contract.get("dialect")
        or closure_keyword != "unevaluatedProperties"
        or contract.get("object_closure_value") is not False
        or contract.get("references") != "forbidden"
        or contract.get("type_form") != "single-string"
    ):
        return False
    try:
        if not _consumer_b_meta_validate_schema(_encoded(value), _encoded(contract)):
            return False
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    allowed_set = set(allowed)

    def walk(schema: Any) -> bool:
        if not isinstance(schema, dict) or not set(schema) <= allowed_set:
            return False
        schema_type = schema.get("type")
        if schema_type is not None and (
            not isinstance(schema_type, str)
            or schema_type
            not in {
                "array",
                "boolean",
                "integer",
                "null",
                "number",
                "object",
                "string",
            }
        ):
            return False
        if schema_type == "object" and schema.get(closure_keyword) is not False:
            return False
        if any(
            keyword in schema and schema_type not in required_types
            for keyword, required_types in keyword_type_requirements.items()
        ):
            return False
        if "$ref" in schema:
            return False
        required = schema.get("required")
        if required is not None and (
            not isinstance(required, list)
            or not all(isinstance(item, str) and item for item in required)
            or len(required) != len(set(required))
        ):
            return False
        for keyword in ("$defs", "properties"):
            children = schema.get(keyword)
            if children is not None and (
                not isinstance(children, dict)
                or not all(
                    isinstance(name, str) and name and walk(child)
                    for name, child in children.items()
                )
            ):
                return False
        if "items" in schema and not walk(schema["items"]):
            return False
        for keyword in ("anyOf", "oneOf"):
            children = schema.get(keyword)
            if children is not None and (
                not isinstance(children, list)
                or not children
                or not all(walk(child) for child in children)
            ):
                return False
        for keyword in ("const", "default", "enum"):
            if keyword in schema:
                try:
                    _encoded(schema[keyword])
                except (TypeError, ValueError, UnicodeEncodeError):
                    return False
        return True

    return walk(value)


@cache
def _consumer_b_meta_validate_schema(
    canonical_schema_bytes: bytes,
    canonical_profile_bytes: bytes,
) -> bool:
    """Consumer B's independent, content-keyed JSON-Schema meta-validation."""
    del canonical_profile_bytes
    try:
        value = json.loads(canonical_schema_bytes)
        jsonschema.Draft202012Validator.check_schema(value)
    except (json.JSONDecodeError, jsonschema.SchemaError):
        return False
    return True


def _consumer_b_embedded_artifact_bindings_are_closed(ldb: dict[str, Any]) -> bool:
    language = ldb.get("language")
    if not isinstance(language, dict):
        return False
    contracts = language.get("artifact_contracts")
    entries = language.get("artifact_wire_schemas")
    if not isinstance(contracts, list) or not isinstance(entries, list):
        return False
    contract_index = {
        item.get("artifact_kind"): item for item in contracts if isinstance(item, dict)
    }
    schema_index = {
        item.get("artifact_kind"): item.get("schema")
        for item in entries
        if isinstance(item, dict)
    }
    if len(contract_index) != len(contracts) or len(schema_index) != len(entries):
        return False

    observed: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("schema"), dict):
            return False
        properties = entry["schema"].get("properties")
        if not isinstance(properties, dict):
            continue
        for property_schema in properties.values():
            candidate = (
                property_schema.get("const")
                if isinstance(property_schema, dict)
                else None
            )
            if not isinstance(candidate, dict) or "artifact_kind" not in candidate:
                continue
            kind = candidate.get("artifact_kind")
            identity = candidate.get("content_identity")
            wire_identity = candidate.get("wire_schema_identity")
            if (
                not isinstance(kind, str)
                or not isinstance(identity, str)
                or not isinstance(wire_identity, str)
            ):
                return False
            if (
                sum(
                    isinstance(value, dict) and value.get("const") == identity
                    for value in properties.values()
                )
                != 1
            ):
                return False
            contract = contract_index.get(kind)
            if not isinstance(contract, dict):
                return False
            artifact_schema = schema_index.get(contract.get("schema_kind"))
            excluded = contract.get("identity_excluded_members")
            if not isinstance(artifact_schema, dict) or not isinstance(excluded, list):
                return False
            try:
                jsonschema.Draft202012Validator(artifact_schema).validate(candidate)
                schema_body = {
                    key: value for key, value in artifact_schema.items() if key != "$id"
                }
                expected_wire = _identity(
                    contract["wire_schema_identity_domain"], schema_body
                )
                identity_body = {
                    key: value
                    for key, value in candidate.items()
                    if key != "content_identity" and key not in excluded
                }
                expected_identity = _identity(
                    contract["identity_domain"], identity_body
                )
                encoded = _encoded(candidate)
            except (
                KeyError,
                TypeError,
                ValueError,
                UnicodeEncodeError,
                jsonschema.ValidationError,
            ):
                return False
            if wire_identity != expected_wire or identity != expected_identity:
                return False
            if kind in observed and observed[kind] != encoded:
                return False
            observed[kind] = encoded
    return True


def _consumer_b_wire_schema_identity_domains_are_closed(
    ldb: dict[str, Any],
) -> bool:
    language = ldb.get("language")
    if not isinstance(language, dict):
        return False
    raw_contracts = language.get("artifact_contracts")
    if not isinstance(raw_contracts, list):
        return False
    contract_domains = {
        item.get("schema_kind"): item.get("wire_schema_identity_domain")
        for item in raw_contracts
        if isinstance(item, dict)
        and isinstance(item.get("schema_kind"), str)
        and isinstance(item.get("wire_schema_identity_domain"), str)
    }
    artifact_kinds = {
        item.get("artifact_kind")
        for item in raw_contracts
        if isinstance(item, dict)
        and isinstance(item.get("artifact_kind"), str)
        and item["artifact_kind"]
    }
    if len(contract_domains) != len(raw_contracts) or len(artifact_kinds) != len(
        raw_contracts
    ):
        return False
    seen: set[str] = set()
    inline_kinds: set[str] = set()
    for collection in ("wire_schemas", "artifact_wire_schemas"):
        entries = language.get(collection)
        if not isinstance(entries, list):
            return False
        for item in entries:
            if not isinstance(item, dict):
                return False
            kind = item.get("artifact_kind")
            inline_domain = item.get("wire_schema_identity_domain")
            if (
                not isinstance(kind, str)
                or not kind
                or kind in seen
                or (inline_domain is None) == (kind not in contract_domains)
                or (
                    inline_domain is not None
                    and (not isinstance(inline_domain, str) or not inline_domain)
                )
            ):
                return False
            seen.add(kind)
            if inline_domain is not None:
                inline_kinds.add(kind)
    return artifact_kinds.isdisjoint(inline_kinds)


def _consumer_b_value_matches(value: Any, contract: Any, ldb: dict[str, Any]) -> bool:
    if not isinstance(contract, dict):
        return False
    if "const" in contract:
        return value == contract["const"] and type(value) is type(contract["const"])
    if "enum" in contract:
        return isinstance(contract["enum"], list) and value in contract["enum"]
    kind = contract.get("type")
    if kind == "non-empty-string":
        if not isinstance(value, str) or not value:
            return False
        pattern = contract.get("pattern")
        if pattern is None:
            return True
        if not isinstance(pattern, str):
            return False
        try:
            return re.fullmatch(pattern, value) is not None
        except re.error:
            return False
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "positive-signed-int64":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 1 <= value <= 2**63 - 1
        )
    if kind == "signed-int64":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and -(2**63) <= value <= 2**63 - 1
        )
    if kind == "canonical-scalar":
        return (
            value is None
            or isinstance(value, (bool, str))
            or (
                isinstance(value, int)
                and not isinstance(value, bool)
                and -(2**63) <= value <= 2**63 - 1
            )
        )
    if kind == "scalar-list":
        return isinstance(value, list) and all(
            _consumer_b_value_matches(item, {"type": "canonical-scalar"}, ldb)
            for item in value
        )
    if kind == "string-list":
        return (
            isinstance(value, list)
            and all(isinstance(item, str) and item for item in value)
            and len(value) == len(set(value))
        )
    if kind == "path-segments":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item for item in value)
        )
    if kind == "canonical-value":
        try:
            _encoded(value)
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        return True
    if kind == "closed-object":
        required = contract.get("required_members")
        field_types = contract.get("field_types")
        return (
            isinstance(value, dict)
            and isinstance(required, list)
            and isinstance(field_types, dict)
            and set(value) == set(required)
            and set(field_types) == set(required)
            and all(
                _consumer_b_value_matches(value[name], field_types[name], ldb)
                for name in required
            )
        )
    if kind == "closed-discriminated-object":
        discriminator = contract.get("discriminator")
        variants = contract.get("variants")
        if (
            not isinstance(value, dict)
            or not isinstance(discriminator, str)
            or not discriminator
            or not isinstance(variants, dict)
            or not variants
        ):
            return False
        variant = variants.get(value.get(discriminator))
        return isinstance(variant, dict) and _consumer_b_value_matches(
            value, variant, ldb
        )
    if kind == "list-of":
        item_contract = contract.get("items")
        return (
            isinstance(value, list)
            and isinstance(item_contract, dict)
            and all(
                _consumer_b_value_matches(item, item_contract, ldb) for item in value
            )
        )
    if kind == "inventory-member":
        path = contract.get("path")
        return _consumer_b_path_is_declared(ldb, path) and value in _project(ldb, path)
    if kind == "inventory-list-path":
        declared, target = _consumer_b_exact_path(ldb, value)
        return declared and isinstance(target, list) and bool(target)
    if kind == "signed-int64-path":
        declared, target = _consumer_b_exact_path(ldb, value)
        return declared and _consumer_b_value_matches(
            target, {"type": "signed-int64"}, ldb
        )
    if kind == "closed-json-schema":
        return _consumer_b_closed_json_schema(value, contract)
    if kind == "closed-int64-interval":
        if not isinstance(value, dict) or set(value) != {"minimum", "maximum"}:
            return False
        minimum = value["minimum"]
        maximum = value["maximum"]
        return (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and -(2**63) <= minimum <= maximum <= 2**63 - 1
        )
    return False


def _consumer_b_definition_is_closed(
    value: Any, contract: Any, ldb: dict[str, Any]
) -> bool:
    if not isinstance(value, dict) or not isinstance(contract, dict):
        return False
    required = contract.get("required_members")
    optional = contract.get("optional_members", [])
    field_types = contract.get("field_types")
    return (
        isinstance(required, list)
        and isinstance(optional, list)
        and isinstance(field_types, dict)
        and not set(required) & set(optional)
        and set(required) <= set(value)
        and set(value) <= set(required) | set(optional)
        and set(field_types) == set(required) | set(optional)
        and all(
            _consumer_b_value_matches(value[name], field_types[name], ldb)
            for name in value
        )
    )


def _consumer_b_fact_contract_at_path(
    fields: dict[str, Any], path: Any
) -> dict[str, Any] | None:
    if (
        not isinstance(path, list)
        or not path
        or not all(isinstance(segment, str) and segment for segment in path)
        or path[0] not in fields
    ):
        return None
    contract = fields[path[0]]
    for segment in path[1:]:
        if (
            not isinstance(contract, dict)
            or contract.get("type") != "closed-object"
            or not isinstance(contract.get("field_types"), dict)
            or segment not in contract["field_types"]
        ):
            return None
        contract = contract["field_types"][segment]
    return contract if isinstance(contract, dict) else None


def _consumer_b_fact_contract_path_is_declared(
    fields: dict[str, Any], path: Any
) -> bool:
    return _consumer_b_fact_contract_at_path(fields, path) is not None


def _consumer_b_resolution_contract_is_closed(value: Any) -> bool:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "closed",
            "input",
            "operations",
            "result",
            "stage_order",
            "relation_schemas",
            "relation_recipe_format",
            "routing_equivalences",
            "resource_accounting",
            "law_format",
        }
        or value.get("closed") is not True
    ):
        return False
    stages = value.get("stage_order")
    relations = value.get("relation_schemas")
    operations = value.get("operations")
    law_format = value.get("law_format")
    recipe_format = value.get("relation_recipe_format")
    routing_equivalences = value.get("routing_equivalences")
    resource_accounting = value.get("resource_accounting")
    if (
        not isinstance(stages, list)
        or not stages
        or not all(isinstance(stage, str) and stage for stage in stages)
        or len(stages) != len(set(stages))
        or not isinstance(relations, list)
        or not relations
        or not isinstance(operations, list)
        or not operations
        or not isinstance(law_format, dict)
        or set(law_format) != {"closed", "operators"}
        or law_format.get("closed") is not True
        or not isinstance(law_format.get("operators"), list)
        or not isinstance(recipe_format, dict)
        or set(recipe_format)
        != {
            "closed",
            "binding_source_roots",
            "term_roots",
            "predicate_operators",
            "binding",
            "term",
            "predicate",
            "field",
            "root_typing",
        }
        or recipe_format.get("closed") is not True
        or recipe_format.get("binding_source_roots")
        != ["source", "language", "selected-packages", "binding"]
        or recipe_format.get("term_roots") != ["source", "language", "binding"]
        or recipe_format.get("predicate_operators") != ["equal"]
        or recipe_format.get("binding")
        != {
            "required_members": ["name", "source"],
            "source_result": "list",
            "expansion_order": "source-list-order",
        }
        or recipe_format.get("term")
        != {
            "required_members": {
                "source": ["root", "path"],
                "language": ["root", "path"],
                "binding": ["root", "binding", "path"],
            },
            "path_semantics": "closed-object-member-path",
            "empty_path": "identity",
        }
        or recipe_format.get("predicate")
        != {
            "required_members": ["operator", "left", "right"],
            "operand_type": "canonical-value",
        }
        or recipe_format.get("field")
        != {
            "required_members": ["name", "term", "pointer"],
            "result_type": "non-empty-string",
            "pointer_true_origin": "source",
        }
        or recipe_format.get("root_typing")
        != {
            "source": "model-source-wire-schema",
            "language": "kernel-declared-language-contracts",
            "selected-packages": "required-transitive-package-closure",
            "binding": "expanded-binding-item",
        }
        or not isinstance(routing_equivalences, list)
        or not routing_equivalences
        or any(
            not isinstance(item, dict)
            or set(item)
            != {
                "profile_member",
                "recipe",
                "subject_kind",
                "subject",
                "projection",
            }
            or not all(
                isinstance(item.get(member), str) and item[member]
                for member in ("profile_member", "recipe", "subject")
            )
            or item.get("subject_kind") not in {"binding-source", "field-term"}
            or item.get("projection") not in {"dot-path", "last-segment"}
            for item in routing_equivalences
        )
        or len(
            {
                item["profile_member"]
                for item in routing_equivalences
                if isinstance(item, dict) and "profile_member" in item
            }
        )
        != len(routing_equivalences)
        or resource_accounting
        != {
            "limit_member": "max_rule_match_steps",
            "counter_scope": "per-resolution-stage",
            "charged_events": [
                "binding-expansion",
                "predicate-comparison",
                "field-projection",
                "law-subject-evaluation",
                "law-target-comparison",
            ],
            "exhaustion_reason": {
                "stage": "static",
                "operation": "greater-than",
                "limit_path": "resources.max_rule_match_steps",
            },
        }
    ):
        return False
    relation_fields: dict[str, set[str]] = {}
    for relation in relations:
        if (
            not isinstance(relation, dict)
            or set(relation) != {"id", "fields", "pointer_fields"}
            or not isinstance(relation.get("id"), str)
            or relation["id"] in relation_fields
            or not isinstance(relation.get("fields"), list)
            or not relation["fields"]
            or not all(isinstance(field, str) and field for field in relation["fields"])
            or len(relation["fields"]) != len(set(relation["fields"]))
            or not isinstance(relation.get("pointer_fields"), list)
            or not all(
                isinstance(field, str) and field for field in relation["pointer_fields"]
            )
            or not set(relation["pointer_fields"]) <= set(relation["fields"])
        ):
            return False
        relation_fields[relation["id"]] = set(relation["fields"])
    specifications = {
        item["id"]: item
        for item in law_format["operators"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(specifications) != len(law_format["operators"]):
        return False
    for specification in specifications.values():
        required = specification.get("required_members")
        optional = specification.get("optional_members")
        if (
            set(specification)
            not in (
                {"id", "required_members", "optional_members"},
                {"id", "required_members", "optional_members", "cardinalities"},
            )
            or not isinstance(required, list)
            or not isinstance(optional, list)
            or not all(isinstance(member, str) and member for member in required)
            or not all(isinstance(member, str) and member for member in optional)
            or len(required) != len(set(required))
            or len(optional) != len(set(optional))
            or set(required) & set(optional)
        ):
            return False

    def field_list(law: dict[str, Any], member: str, fields: set[str]) -> bool:
        selected = law.get(member)
        return isinstance(selected, list) and all(field in fields for field in selected)

    seen: set[str] = set()
    for operation in operations:
        if (
            not isinstance(operation, dict)
            or set(operation)
            != {
                "id",
                "stage",
                "law",
                "input",
                "result",
                "effects",
                "refusals",
                "resources",
            }
            or not isinstance(operation.get("id"), str)
            or operation["id"] in seen
            or operation.get("stage") not in stages
            or not isinstance(operation.get("law"), dict)
            or operation.get("input") != {"fact_kind": "resolution-state"}
            or operation.get("result") != {"fact_kind": "resolution-state"}
            or operation.get("effects") != []
            or operation.get("refusals") != ["reason-bound-diagnostic"]
            or operation.get("resources")
            != [
                "max_diagnostics",
                "max_rule_match_steps",
                "max_symbols",
            ]
        ):
            return False
        seen.add(operation["id"])
        law = operation["law"]
        specification = specifications.get(law.get("operator"))
        if not isinstance(specification, dict):
            return False
        required = set(specification["required_members"])
        optional = set(specification["optional_members"])
        if not required <= set(law) or not set(law) <= required | optional:
            return False
        operator = law["operator"]
        if operator == "require-match":
            source_fields = relation_fields.get(law.get("subject_relation"))
            target_fields = relation_fields.get(law.get("target_relation"))
            pairs = law.get("match")
            cardinalities = specification.get("cardinalities")
            if (
                source_fields is None
                or target_fields is None
                or not isinstance(pairs, list)
                or not pairs
                or not isinstance(cardinalities, list)
                or law.get("cardinality") not in cardinalities
                or law.get("pointer_field") not in source_fields
                or any(
                    not isinstance(pair, dict)
                    or set(pair) != {"subject", "target"}
                    or pair.get("subject") not in source_fields
                    or pair.get("target") not in target_fields
                    for pair in pairs
                )
            ):
                return False
            guard = law.get("guard")
            if guard is not None:
                guarded_relation = (
                    guard.get("target_relation") if isinstance(guard, dict) else None
                )
                guarded_fields = (
                    relation_fields.get(guarded_relation)
                    if isinstance(guarded_relation, str)
                    else None
                )
                if (
                    not isinstance(guard, dict)
                    or set(guard) != {"target_relation", "match", "cardinality"}
                    or guarded_fields is None
                    or guard.get("cardinality") not in cardinalities
                    or not isinstance(guard.get("match"), list)
                    or not guard["match"]
                    or any(
                        not isinstance(pair, dict)
                        or set(pair) != {"subject", "target"}
                        or pair.get("subject") not in source_fields
                        or pair.get("target") not in guarded_fields
                        for pair in guard["match"]
                    )
                ):
                    return False
        elif operator == "require-unique":
            fields = relation_fields.get(law.get("relation"))
            if (
                fields is None
                or not field_list(law, "scope", fields)
                or not field_list(law, "key", fields)
                or not law["key"]
                or law.get("pointer_field") not in fields
            ):
                return False
        elif operator == "require-single-value":
            fields = relation_fields.get(law.get("relation"))
            if (
                fields is None
                or not field_list(law, "scope", fields)
                or not field_list(law, "group", fields)
                or not field_list(law, "value", fields)
                or not law["group"]
                or not law["value"]
                or law.get("pointer_field") not in fields
            ):
                return False
        else:
            return False
    return [operation["id"] for operation in operations] == [
        operation["id"]
        for stage in stages
        for operation in operations
        if operation["stage"] == stage
    ]


def _consumer_b_schema_path(schema: Any, path: list[str]) -> dict[str, Any] | None:
    selected = schema
    for segment in path:
        if (
            not isinstance(selected, dict)
            or selected.get("type") != "object"
            or not isinstance(selected.get("properties"), dict)
            or segment not in selected["properties"]
        ):
            return None
        selected = selected["properties"][segment]
    return selected if isinstance(selected, dict) else None


def _consumer_b_kind(value: Any, *, schema: bool = False) -> str | None:
    if schema:
        if not isinstance(value, dict):
            return None
        if isinstance(value.get("type"), str):
            return value["type"]
        if "const" in value:
            return _consumer_b_kind(value["const"])
        if isinstance(value.get("enum"), list) and value["enum"]:
            kinds = {_consumer_b_kind(item) for item in value["enum"]}
            return kinds.pop() if len(kinds) == 1 else None
        return None
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return None


def _consumer_b_relation_paths_are_typed(
    profile: dict[str, Any],
    resolution: dict[str, Any],
    ldb: dict[str, Any],
    package_release: dict[str, Any],
) -> bool:
    language = ldb.get("language")
    schemas = language.get("wire_schemas") if isinstance(language, dict) else None
    source = [
        item.get("schema")
        for item in schemas or []
        if isinstance(item, dict)
        and item.get("artifact_kind") == "model-source-package"
    ]
    if (
        not isinstance(language, dict)
        or len(source) != 1
        or not isinstance(source[0], dict)
    ):
        return False
    recipes = profile["relation_recipes"]
    recipes_by_id = {item["id"]: item for item in recipes}

    def select(
        term: dict[str, Any],
        bindings: dict[str, tuple[str, Any, str]],
    ) -> tuple[str, Any, str] | None:
        if term["root"] == "source":
            representation, payload, origin = "schema", source[0], "source"
        elif term["root"] == "language":
            if term["path"] != ["packages"]:
                return None
            return ("package-list", package_release, "language")
        elif term["root"] == "selected-packages":
            if term["path"]:
                return None
            return ("package-list", package_release, "language")
        elif term["root"] == "binding" and term.get("binding") in bindings:
            representation, payload, origin = bindings[term["binding"]]
        else:
            return None
        if representation == "schema":
            selected = _consumer_b_schema_path(payload, term["path"])
            return ("schema", selected, origin) if selected is not None else None
        if representation == "contract":
            if not isinstance(payload, dict):
                return None
            path = term["path"]
            if not path:
                return ("contract", payload, origin)
            direct = payload.get("field_types")
            nested = payload.get("nested_field_types")
            if len(path) == 1 and isinstance(direct, dict):
                selected = direct.get(path[0])
            elif (
                len(path) == 2
                and isinstance(nested, dict)
                and isinstance(nested.get(path[0]), dict)
            ):
                selected = nested[path[0]].get(path[1])
                if path == ["exports", "types"] and isinstance(selected, dict):
                    selected = {**selected, "items": payload.get("type_export")}
            else:
                selected = None
            return (
                ("contract", selected, origin) if isinstance(selected, dict) else None
            )
        if not isinstance(payload, list):
            return None
        values = payload
        for segment in term["path"]:
            next_values = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    return None
                next_values.append(value[segment])
            values = next_values
        return ("values", values, origin)

    def result_kind(shape: tuple[str, Any, str]) -> str | None:
        representation, payload, _origin = shape
        if representation == "schema":
            return _consumer_b_kind(payload, schema=True)
        if representation == "package-list":
            return "array"
        if representation == "contract":
            value_type = payload.get("type")
            if value_type in {"non-empty-string", "string"}:
                return "string"
            if value_type in {"list", "string-list"}:
                return "array"
            if "const" in payload:
                return _consumer_b_kind(payload["const"])
            return None
        if not payload:
            return None
        kinds = {_consumer_b_kind(value) for value in payload}
        return kinds.pop() if len(kinds) == 1 else None

    for recipe in recipes:
        bindings: dict[str, tuple[str, Any, str]] = {}
        for binding in recipe["bindings"]:
            shape = select(binding["source"], bindings)
            if shape is None:
                return False
            representation, payload, origin = shape
            if representation == "schema":
                if payload.get("type") != "array" or not isinstance(
                    payload.get("items"), dict
                ):
                    return False
                bindings[binding["name"]] = ("schema", payload["items"], origin)
            elif representation in {"contract", "package-list"}:
                if representation == "package-list":
                    item = payload
                elif payload.get("type") == "string-list":
                    item = {"type": "non-empty-string"}
                else:
                    item = payload.get("items")
                if not isinstance(item, dict):
                    return False
                bindings[binding["name"]] = ("contract", item, origin)
            else:
                if not payload or not all(isinstance(value, list) for value in payload):
                    return False
                bindings[binding["name"]] = (
                    "values",
                    [item for value in payload for item in value],
                    origin,
                )
        for predicate in recipe["predicates"]:
            left = select(predicate["left"], bindings)
            right = select(predicate["right"], bindings)
            if (
                left is None
                or right is None
                or result_kind(left) is None
                or result_kind(left) != result_kind(right)
            ):
                return False
        for field in recipe["fields"]:
            shape = select(field["term"], bindings)
            if (
                shape is None
                or result_kind(shape) != "string"
                or (field["pointer"] and shape[2] != "source")
            ):
                return False
    for equivalence in resolution["routing_equivalences"]:
        recipe = recipes_by_id.get(equivalence["recipe"])
        if recipe is None:
            return False
        candidates = (
            [
                binding["source"]
                for binding in recipe["bindings"]
                if binding["name"] == equivalence["subject"]
            ]
            if equivalence["subject_kind"] == "binding-source"
            else [
                field["term"]
                for field in recipe["fields"]
                if field["name"] == equivalence["subject"]
            ]
        )
        if len(candidates) != 1 or not candidates[0]["path"]:
            return False
        expected = (
            ".".join(candidates[0]["path"])
            if equivalence["projection"] == "dot-path"
            else candidates[0]["path"][-1]
        )
        if profile.get(equivalence["profile_member"]) != expected:
            return False
    return True


def _consumer_b_relation_recipes_are_closed(
    profile: dict[str, Any],
    resolution: dict[str, Any],
    ldb: dict[str, Any],
    package_release: dict[str, Any],
) -> bool:
    recipes = profile.get("relation_recipes")
    schemas = resolution.get("relation_schemas")
    recipe_format = resolution.get("relation_recipe_format")
    if (
        not isinstance(recipes, list)
        or not isinstance(schemas, list)
        or not isinstance(recipe_format, dict)
        or [item.get("id") for item in recipes if isinstance(item, dict)]
        != [item.get("id") for item in schemas if isinstance(item, dict)]
    ):
        return False
    allowed_sources = set(recipe_format.get("binding_source_roots", []))
    allowed_terms = set(recipe_format.get("term_roots", []))
    allowed_predicates = set(recipe_format.get("predicate_operators", []))

    def valid_term(
        term: Any,
        names: set[str],
        roots: set[str],
    ) -> bool:
        if not isinstance(term, dict):
            return False
        root = term.get("root")
        expected = (
            {"root", "path", "binding"}
            if root == "binding"
            else {
                "root",
                "path",
            }
        )
        return (
            root in roots
            and set(term) == expected
            and isinstance(term.get("path"), list)
            and all(isinstance(segment, str) and segment for segment in term["path"])
            and (
                root != "binding"
                or (isinstance(term.get("binding"), str) and term["binding"] in names)
            )
        )

    for recipe, schema in zip(recipes, schemas, strict=True):
        if (
            not isinstance(recipe, dict)
            or not isinstance(schema, dict)
            or set(recipe) != {"id", "bindings", "predicates", "fields"}
            or recipe.get("id") != schema.get("id")
            or not isinstance(recipe.get("bindings"), list)
            or not isinstance(recipe.get("predicates"), list)
            or not isinstance(recipe.get("fields"), list)
        ):
            return False
        names: set[str] = set()
        for binding in recipe["bindings"]:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"name", "source"}
                or not isinstance(binding.get("name"), str)
                or not binding["name"]
                or binding["name"] in names
                or not valid_term(binding.get("source"), names, allowed_sources)
            ):
                return False
            names.add(binding["name"])
        if any(
            not isinstance(predicate, dict)
            or set(predicate) != {"operator", "left", "right"}
            or predicate.get("operator") not in allowed_predicates
            or not valid_term(predicate.get("left"), names, allowed_terms)
            or not valid_term(predicate.get("right"), names, allowed_terms)
            for predicate in recipe["predicates"]
        ):
            return False
        schema_fields = schema.get("fields")
        pointer_fields = schema.get("pointer_fields")
        if (
            not isinstance(schema_fields, list)
            or not isinstance(pointer_fields, list)
            or [
                field.get("name")
                for field in recipe["fields"]
                if isinstance(field, dict)
            ]
            != schema_fields
            or any(
                not isinstance(field, dict)
                or set(field) != {"name", "term", "pointer"}
                or field.get("pointer") != (field.get("name") in pointer_fields)
                or not valid_term(field.get("term"), names, allowed_terms)
                for field in recipe["fields"]
            )
        ):
            return False
    return _consumer_b_relation_paths_are_typed(
        profile,
        resolution,
        ldb,
        package_release,
    )


def _consumer_b_semantic_item_contract(
    authority_path: str, definitions: dict[str, Any]
) -> dict[str, Any] | None:
    route = authority_path.split(".")
    if route[:1] != ["language"]:
        return None
    if len(route) == 2:
        groups = definitions.get("collections")
        item = groups.get(route[1]) if isinstance(groups, dict) else None
    elif len(route) == 3 and route[1] == "quantity":
        quantity = definitions.get("quantity")
        groups = quantity.get("collections") if isinstance(quantity, dict) else None
        item = groups.get(route[2]) if isinstance(groups, dict) else None
    else:
        return None
    if not isinstance(item, dict):
        return None
    scalar = item.get("item_type")
    return {"type": scalar} if isinstance(scalar, str) else item


def _consumer_b_contract_path(
    contract: dict[str, Any], path: list[str]
) -> dict[str, Any] | None:
    current = contract
    for segment in path:
        if current.get("type") == "closed-discriminated-object":
            variants = current.get("variants")
            children = (
                [
                    child
                    for variant in variants.values()
                    if isinstance(variant, dict)
                    and isinstance(variant.get("field_types"), dict)
                    and isinstance(child := variant["field_types"].get(segment), dict)
                ]
                if isinstance(variants, dict)
                else []
            )
            kinds = {_consumer_b_contract_kind(child) for child in children}
            if not children or len(kinds) != 1 or None in kinds:
                return None
            if all(child == children[0] for child in children[1:]):
                current = children[0]
            else:
                current = {
                    "type": {
                        "array": "list",
                        "boolean": "boolean",
                        "integer": "signed-int64",
                        "object": "object",
                        "string": "non-empty-string",
                    }[cast(str, next(iter(kinds)))]
                }
            continue
        members = current.get("field_types")
        selected = members.get(segment) if isinstance(members, dict) else None
        if not isinstance(selected, dict):
            return None
        current = selected
    return current


def _consumer_b_contract_kind(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    kind = contract.get("type")
    if kind in {"inventory-member", "non-empty-string", "string"}:
        return "string"
    if kind in {"list", "list-of", "string-list"}:
        return "array"
    if kind in {
        "closed-discriminated-object",
        "closed-int64-interval",
        "closed-object",
    } or (
        isinstance(contract.get("required_members"), list)
        and isinstance(contract.get("field_types"), dict)
    ):
        return "object"
    if kind in {"positive-signed-int64", "signed-int64"}:
        return "integer"
    if kind == "boolean":
        return "boolean"
    if "const" in contract:
        return _consumer_b_kind(contract["const"])
    return None


def _consumer_b_contract_fits_schema(contract: dict[str, Any], schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if "const" in contract:
        literal = contract["const"]
        return (
            ("const" not in schema or schema["const"] == literal)
            and (not isinstance(schema.get("enum"), list) or literal in schema["enum"])
            and (
                schema.get("type") is None
                or schema.get("type") == _consumer_b_kind(literal)
            )
        )
    if isinstance(contract.get("enum"), list) and contract["enum"]:
        values = contract["enum"]
        kinds = {_consumer_b_kind(value) for value in values}
        return (
            len(kinds) == 1
            and schema.get("type") in {None, next(iter(kinds))}
            and (
                not isinstance(schema.get("enum"), list)
                or set(values) <= set(schema["enum"])
            )
        )
    kind = contract.get("type")
    if kind in {"inventory-member", "non-empty-string", "string"}:
        return schema.get("type") == "string"
    if kind in {"positive-signed-int64", "signed-int64"}:
        return schema.get("type") == "integer"
    if kind == "boolean":
        return schema.get("type") == "boolean"
    if kind == "string-list":
        items = schema.get("items")
        return (
            schema.get("type") == "array"
            and isinstance(items, dict)
            and items.get("type") == "string"
        )
    if kind == "canonical-value":
        return True
    if kind == "closed-discriminated-object":
        return schema == {}
    if kind == "list-of":
        return (
            schema.get("type") == "array"
            and isinstance(contract.get("items"), dict)
            and _consumer_b_contract_fits_schema(contract["items"], schema.get("items"))
        )
    object_contract = kind == "closed-object" or (
        kind is None
        and isinstance(contract.get("required_members"), list)
        and isinstance(contract.get("field_types"), dict)
    )
    if not object_contract:
        return False
    required = contract.get("required_members")
    optional = contract.get("optional_members", [])
    fields = contract.get("field_types")
    properties = schema.get("properties")
    return (
        schema.get("type") == "object"
        and isinstance(required, list)
        and isinstance(optional, list)
        and isinstance(fields, dict)
        and isinstance(properties, dict)
        and not set(required) & set(optional)
        and set(fields) == set(required) | set(optional)
        and set(properties) == set(fields)
        and set(schema.get("required", [])) == set(required)
        and schema.get("unevaluatedProperties") is False
        and all(
            _consumer_b_contract_fits_schema(fields[name], properties[name])
            for name in fields
        )
    )


def _consumer_b_runtime_projection_is_closed(
    profile: Any,
    contract: Any,
    ldb: dict[str, Any],
    declaration_fields: dict[str, Any],
    language_definitions: dict[str, Any],
) -> bool:
    if (
        not isinstance(profile, dict)
        or set(profile)
        != {"outputs", "collections", "seeds", "edges", "type_reference_closure"}
        or not isinstance(contract, dict)
        or set(contract)
        != {
            "closed",
            "collection_source_kinds",
            "output_shapes",
            "seed_operators",
            "edge_operators",
            "output_kinds",
            "collection",
            "seed",
            "edge",
            "type_reference_closure",
            "path_typing",
            "output_typing",
            "resource_accounting",
        }
        or contract.get("closed") is not True
    ):
        return False
    sources = set(contract.get("collection_source_kinds", []))
    allowed_shapes = set(contract.get("output_shapes", []))
    seeds_allowed = set(contract.get("seed_operators", []))
    edges_allowed = set(contract.get("edge_operators", []))
    outputs_allowed = set(contract.get("output_kinds", []))
    if (
        sources != {"lock-member", "semantic-closure"}
        or allowed_shapes
        != {"as-is", "package-definition", "definition", "closure-only"}
        or seeds_allowed != {"declaration-field"}
        or edges_allowed != {"equal"}
        or outputs_allowed
        != {
            "selected-packages",
            "selected-semantic-closures",
        }
        or contract.get("collection")
        != {
            "required_members": ["id", "source", "output_member", "output_shape"],
            "optional_members": ["excluded_extension_members"],
            "lock_source_members": ["kind", "member", "package_path"],
            "closure_source_members": ["kind", "authority_path"],
        }
        or contract.get("seed")
        != {
            "required_members": [
                "operator",
                "collection",
                "declaration_path",
                "declaration_package_path",
                "target_path",
                "same_package",
                "missing_declaration_path",
                "applicability_member",
            ],
            "match": "canonical-equality",
            "cardinality": "at-least-one",
            "missing_declaration_path": "not-applicable",
            "applicability": "declared-member-present",
            "optional_members": ["missing_target"],
            "missing_target_modes": ["not-applicable", "refuse"],
        }
        or contract.get("edge")
        != {
            "required_members": [
                "operator",
                "source_collection",
                "source_path",
                "target_collection",
                "target_path",
                "same_package",
                "missing_target",
            ],
            "match": "canonical-equality",
            "cardinality": "at-least-one",
            "missing_target_modes": ["not-applicable", "refuse"],
        }
        or contract.get("type_reference_closure")
        != {
            "required_members": [
                "source_collection",
                "source_definition_path",
                "target_type_collection",
                "target_constructor_collection",
                "coordinate_members",
                "structural_kind_member",
                "constructor_kind_path",
            ],
            "coordinate_match": "exact-package-version-type-id",
            "structural_match": "definition-kind-to-constructor-kind",
        }
        or contract.get("path_typing")
        != {
            "declaration": "terminal-fact-contract",
            "lock": "package-lock-wire-schema",
            "semantic_closure": "kernel-language-definition-contract",
            "empty_path": "identity",
        }
        or contract.get("output_typing")
        != {
            "source": "collection-element-contract",
            "target": "rir-selected-semantics-member-schema",
            "shape_transforms": {
                "as-is": "identity",
                "definition": "identity",
                "package-definition": "package-and-definition-object",
                "closure-only": "no-output",
            },
        }
        or contract.get("resource_accounting")
        != {
            "limit_member": "max_runtime_projection_steps",
            "counter_scope": "per-runtime-projection",
            "charged_events": [
                "catalog-row",
                "seed-candidate",
                "edge-source",
                "edge-target",
                "type-reference-term",
                "type-reference-target",
                "constructor-kind-target",
                "collection-output-row",
                "explicit-output-row",
            ],
            "exhaustion_reason": {
                "stage": "static",
                "operation": "greater-than",
                "limit_path": "resources.max_runtime_projection_steps",
            },
        }
    ):
        return False

    def valid_path(value: Any, allow_empty: bool = False) -> bool:
        return (
            isinstance(value, list)
            and (allow_empty or bool(value))
            and all(isinstance(segment, str) and segment for segment in value)
        )

    outputs = profile.get("outputs")
    collections = profile.get("collections")
    seeds = profile.get("seeds")
    edges = profile.get("edges")
    type_reference_closure = profile.get("type_reference_closure")
    if (
        not isinstance(outputs, list)
        or not isinstance(collections, list)
        or not isinstance(seeds, list)
        or not isinstance(edges, list)
        or type_reference_closure
        != {
            "constructor_kind_path": ["value_rule", "definition_kind"],
            "coordinate_members": ["package", "version", "id"],
            "source_collection": "nominal_types",
            "source_definition_path": ["definition"],
            "structural_kind_member": "kind",
            "target_constructor_collection": "constructors",
            "target_type_collection": "types",
        }
    ):
        return False
    projected_members = []
    for output in outputs:
        if not isinstance(output, dict) or output.get("kind") not in outputs_allowed:
            return False
        expected = {"kind", "source_member", "output_member", "package_member"}
        if output["kind"] == "selected-packages":
            expected.add("members")
        elif output["kind"] == "selected-semantic-closures":
            expected |= {
                "entries_member",
                "authority_path_member",
                "definitions_member",
            }
        if set(output) != expected:
            return False
        scalar_members = expected - {"kind", "members"}
        if any(
            not isinstance(output.get(member), str) or not output[member]
            for member in scalar_members
        ):
            return False
        if "members" in output and (
            not isinstance(output["members"], list)
            or not output["members"]
            or not all(
                isinstance(member, str) and member for member in output["members"]
            )
            or len(output["members"]) != len(set(output["members"]))
        ):
            return False
        projected_members.append(output["output_member"])

    collection_names = []
    authority_paths = set()
    for collection in collections:
        if not isinstance(collection, dict):
            return False
        expected_collection_members = {
            "id",
            "source",
            "output_member",
            "output_shape",
        }
        if "excluded_extension_members" in collection:
            expected_collection_members.add("excluded_extension_members")
        if (
            set(collection) != expected_collection_members
            or not isinstance(collection.get("id"), str)
            or not collection["id"]
            or not isinstance(collection.get("source"), dict)
            or collection.get("output_shape") not in allowed_shapes
            or (
                "excluded_extension_members" in collection
                and (
                    not isinstance(collection["excluded_extension_members"], list)
                    or not collection["excluded_extension_members"]
                    or not all(
                        isinstance(member, str) and member
                        for member in collection["excluded_extension_members"]
                    )
                    or len(collection["excluded_extension_members"])
                    != len(set(collection["excluded_extension_members"]))
                )
            )
        ):
            return False
        output_member = collection.get("output_member")
        if (collection["output_shape"] == "closure-only") != (output_member is None):
            return False
        if output_member is not None:
            if not isinstance(output_member, str) or not output_member:
                return False
            projected_members.append(output_member)
        source = collection["source"]
        if source.get("kind") == "lock-member":
            if (
                set(source) != {"kind", "member", "package_path"}
                or not isinstance(source.get("member"), str)
                or not source["member"]
                or not valid_path(source.get("package_path"))
            ):
                return False
        elif source.get("kind") == "semantic-closure":
            if (
                set(source) != {"kind", "authority_path"}
                or not isinstance(source.get("authority_path"), str)
                or not source["authority_path"]
            ):
                return False
            authority_paths.add(source["authority_path"])
        else:
            return False
        collection_names.append(collection["id"])
    if len(collection_names) != len(set(collection_names)):
        return False
    collection_set = set(collection_names)

    for seed in seeds:
        if not isinstance(seed, dict) or seed.get("operator") not in seeds_allowed:
            return False
        expected = {
            "operator",
            "collection",
            "declaration_package_path",
            "missing_declaration_path",
            "applicability_member",
        }
        expected |= {"declaration_path", "target_path", "same_package"}
        if "missing_target" in seed:
            expected.add("missing_target")
        if (
            set(seed) != expected
            or seed.get("collection") not in collection_set
            or not valid_path(seed.get("declaration_package_path"))
            or not isinstance(seed.get("same_package"), bool)
            or seed.get("missing_declaration_path") != "not-applicable"
            or not isinstance(seed.get("applicability_member"), str)
            or not seed["applicability_member"]
            or seed.get("missing_target", "refuse") not in {"not-applicable", "refuse"}
        ):
            return False
        if not valid_path(seed.get("declaration_path")) or not valid_path(
            seed.get("target_path"), True
        ):
            return False
    if any(
        not isinstance(edge, dict)
        or set(edge)
        != {
            "operator",
            "source_collection",
            "source_path",
            "target_collection",
            "target_path",
            "same_package",
            "missing_target",
        }
        or edge.get("operator") not in edges_allowed
        or edge.get("source_collection") not in collection_set
        or edge.get("target_collection") not in collection_set
        or not valid_path(edge.get("source_path"), True)
        or not valid_path(edge.get("target_path"), True)
        or not isinstance(edge.get("same_package"), bool)
        or edge.get("missing_target") not in {"not-applicable", "refuse"}
        for edge in edges
    ):
        return False
    language = ldb.get("language")
    schema_values = (
        language.get("artifact_wire_schemas") if isinstance(language, dict) else None
    )
    schemas = schema_values if isinstance(schema_values, list) else []
    rir = [
        item["schema"]
        for item in schemas
        if isinstance(item, dict)
        and item.get("artifact_kind") == "rir-semantic-payload"
    ]
    if len(rir) != 1:
        return False
    selected = rir[0].get("properties", {}).get("selected_semantics")
    required = selected.get("required") if isinstance(selected, dict) else None
    selected_properties = (
        selected.get("properties") if isinstance(selected, dict) else None
    )
    packages = language.get("packages") if isinstance(language, dict) else None
    locks = [
        item["schema"]
        for item in schemas
        if isinstance(item, dict) and item.get("artifact_kind") == "package-lock"
    ]
    if not (
        len(projected_members) == len(set(projected_members))
        and isinstance(required, list)
        and set(projected_members) == set(required)
        and isinstance(selected_properties, dict)
        and isinstance(packages, list)
        and all(
            authority_paths
            <= {
                entry.get("authority_path")
                for entry in package.get("semantic_closure", [])
                if isinstance(entry, dict)
            }
            for package in packages
            if isinstance(package, dict)
        )
        and len(locks) == 1
        and isinstance(locks[0].get("properties"), dict)
    ):
        return False
    lock_properties = locks[0]["properties"]

    def fact_value(path: list[str]) -> dict[str, Any] | None:
        if not path or path[0] not in declaration_fields:
            return None
        selected_contract = declaration_fields[path[0]]
        for segment in path[1:]:
            if (
                not isinstance(selected_contract, dict)
                or selected_contract.get("type") != "closed-object"
                or not isinstance(selected_contract.get("field_types"), dict)
                or segment not in selected_contract["field_types"]
            ):
                return None
            selected_contract = selected_contract["field_types"][segment]
        return selected_contract

    def fact_kind(value: dict[str, Any] | None) -> str | None:
        kind = value.get("type") if isinstance(value, dict) else None
        if kind in {"non-empty-string", "inventory-member"}:
            return "string"
        if kind in {"closed-object", "closed-int64-interval"}:
            return "object"
        if kind in {"signed-int64", "positive-signed-int64"}:
            return "integer"
        if kind == "boolean":
            return "boolean"
        return None

    shapes: dict[str, tuple[str, Any]] = {}
    for collection in collections:
        source = collection["source"]
        if source["kind"] == "lock-member":
            member = lock_properties.get(source["member"])
            if (
                not isinstance(member, dict)
                or member.get("type") != "array"
                or not isinstance(member.get("items"), dict)
                or _consumer_b_kind(
                    _consumer_b_schema_path(
                        member["items"],
                        source["package_path"],
                    ),
                    schema=True,
                )
                != "string"
            ):
                return False
            shapes[collection["id"]] = ("schema", member["items"])
        else:
            item_contract = _consumer_b_semantic_item_contract(
                source["authority_path"], language_definitions
            )
            if item_contract is None:
                return False
            shapes[collection["id"]] = ("contract", item_contract)

    def selected_kind(shape: tuple[str, Any], path: list[str]) -> str | None:
        representation, payload = shape
        if representation == "schema":
            return _consumer_b_kind(
                _consumer_b_schema_path(payload, path),
                schema=True,
            )
        return _consumer_b_contract_kind(_consumer_b_contract_path(payload, path))

    for seed in seeds:
        if seed["applicability_member"] not in declaration_fields:
            continue
        declaration_kind = fact_kind(fact_value(seed["declaration_path"]))
        package_kind = fact_kind(fact_value(seed["declaration_package_path"]))
        if declaration_kind is None:
            if seed["missing_declaration_path"] != "not-applicable":
                return False
            continue
        target_kind = selected_kind(
            shapes[seed["collection"]],
            seed["target_path"],
        )
        if declaration_kind != target_kind or package_kind != "string":
            return False
    for edge in edges:
        source_kind = selected_kind(
            shapes[edge["source_collection"]],
            edge["source_path"],
        )
        target_kind = selected_kind(
            shapes[edge["target_collection"]],
            edge["target_path"],
        )
        if source_kind is None or source_kind != target_kind:
            return False
    for collection in collections:
        member = collection["output_member"]
        if member is None:
            continue
        target = selected_properties.get(member)
        if (
            not isinstance(target, dict)
            or target.get("type") != "array"
            or not isinstance(target.get("items"), dict)
        ):
            return False
        representation, payload = shapes[collection["id"]]
        shape = collection["output_shape"]
        if representation == "schema":
            if shape != "as-is" or payload != target["items"]:
                return False
        elif shape == "definition":
            if not _consumer_b_contract_fits_schema(payload, target["items"]):
                return False
        elif shape == "package-definition":
            item = target["items"]
            properties = item.get("properties")
            if not (
                item.get("type") == "object"
                and isinstance(properties, dict)
                and set(properties) == {"package", "definition"}
                and set(item.get("required", [])) == {"package", "definition"}
                and item.get("unevaluatedProperties") is False
                and properties["package"].get("type") == "string"
                and _consumer_b_contract_fits_schema(payload, properties["definition"])
            ):
                return False
        else:
            return False
    for output in outputs:
        source_schema = lock_properties.get(output["source_member"])
        target_schema = selected_properties.get(output["output_member"])
        if (
            not isinstance(source_schema, dict)
            or source_schema.get("type") != "array"
            or not isinstance(source_schema.get("items"), dict)
            or not isinstance(target_schema, dict)
            or target_schema.get("type") != "array"
            or not isinstance(target_schema.get("items"), dict)
            or _consumer_b_kind(
                _consumer_b_schema_path(
                    source_schema["items"],
                    [output["package_member"]],
                ),
                schema=True,
            )
            != "string"
        ):
            return False
        if output["kind"] == "selected-packages" and any(
            _consumer_b_schema_path(source_schema["items"], [member]) is None
            for member in output["members"]
        ):
            return False
        if output["kind"] == "selected-packages":
            source_properties = source_schema["items"].get("properties")
            target_item = target_schema["items"]
            target_properties = target_item.get("properties")
            members = set(output["members"])
            if not (
                isinstance(source_properties, dict)
                and isinstance(target_properties, dict)
                and set(target_properties) == members
                and set(target_item.get("required", [])) == members
                and target_item.get("unevaluatedProperties") is False
                and all(
                    source_properties[member] == target_properties[member]
                    for member in members
                )
            ):
                return False
        if output["kind"] == "selected-semantic-closures":
            entries = _consumer_b_schema_path(
                source_schema["items"],
                [output["entries_member"]],
            )
            if (
                not isinstance(entries, dict)
                or entries.get("type") != "array"
                or not isinstance(entries.get("items"), dict)
                or _consumer_b_kind(
                    _consumer_b_schema_path(
                        entries["items"],
                        [output["authority_path_member"]],
                    ),
                    schema=True,
                )
                != "string"
                or _consumer_b_schema_path(
                    entries["items"],
                    [output["definitions_member"]],
                )
                is None
            ):
                return False
            source_properties = source_schema["items"].get("properties")
            target_item = target_schema["items"]
            target_properties = target_item.get("properties")
            members = {output["package_member"], output["entries_member"]}
            if not (
                isinstance(source_properties, dict)
                and isinstance(target_properties, dict)
                and set(target_properties) == members
                and set(target_item.get("required", [])) == members
                and target_item.get("unevaluatedProperties") is False
                and all(
                    source_properties[member] == target_properties[member]
                    for member in members
                )
            ):
                return False
    return True


def _consumer_b_template_admission_is_closed(
    meta: dict[str, Any],
    ldb: dict[str, Any],
) -> bool:
    """Independently close the Kernel/LDB Template program surface."""
    contract = meta.get("template_admission")
    language = ldb.get("language")
    if not isinstance(contract, dict) or not isinstance(language, dict):
        return False
    selector = contract.get("selector")
    accounting = contract.get("resource_accounting")
    operation_rows = contract.get("operations")
    primitive_spec = contract.get("primitive_spec")
    role_contract = contract.get("role_contract")
    if (
        set(contract)
        != {
            "closed",
            "operations",
            "primitive_spec",
            "resource_accounting",
            "role_contract",
            "selector",
        }
        or contract.get("closed") is not True
        or not isinstance(selector, dict)
        or selector
        != {
            "roots": [
                "kernel",
                "language-bundle",
                "release",
                "role",
                "derived",
            ],
            "wildcard_segment": "*",
            "path_semantics": "ordered-flatten",
        }
        or not isinstance(accounting, dict)
        or accounting
        != {
            "limit_path": "resources.max_template_admission_steps",
            "counter_scope": "per-template-release-admission",
            "charge_rules": [
                {"amount": "one-per-member", "event": "member-role"},
                {"amount": "one-per-judgment", "event": "judgment"},
                {
                    "amount": "one-per-projected-value",
                    "event": "selected-value",
                },
                {"amount": "one-per-input-row", "event": "scoped-row"},
                {"amount": "one-per-vector", "event": "vector-execution"},
            ],
            "exhaustion_diagnostic": "language.resource_exhausted",
        }
        or role_contract
        != {
            "identifier": "non-empty-string",
            "cardinalities": ["exactly-one", "one-or-more"],
        }
        or not isinstance(operation_rows, list)
        or not operation_rows
        or not isinstance(primitive_spec, dict)
        or set(primitive_spec)
        != {
            "argument_types",
            "canonical_equality",
            "closed",
            "evaluation_order",
            "primitives",
            "version",
        }
        or primitive_spec.get("closed") is not True
        or primitive_spec.get("version") != "template-graph-primitives-v1"
        or primitive_spec.get("evaluation_order") != "profile-order-first-failure"
        or primitive_spec.get("canonical_equality") != "kernel-canonical-bytes"
        or not isinstance(primitive_spec.get("argument_types"), list)
        or not isinstance(primitive_spec.get("primitives"), list)
    ):
        return False
    assert isinstance(role_contract, dict)
    role_cardinalities = role_contract["cardinalities"]
    expected_argument_types = [
        {"id": "selector", "kind": "selector"},
        {"id": "selector-list", "item": "selector", "kind": "non-empty-list"},
        {"id": "role", "kind": "role-name"},
        {"empty": True, "id": "path", "kind": "string-list"},
        {"empty": False, "id": "non-empty-string", "kind": "string"},
        {"fresh": True, "id": "fresh-derived-name", "kind": "derived-name"},
        {
            "cardinality": "one-or-more",
            "id": "fact-bindings",
            "kind": "model-fact-bindings",
        },
        {"id": "relation", "kind": "enum", "values": ["equal", "subset"]},
        {"id": "outcome", "kind": "enum", "values": ["admitted", "refused"]},
        {"id": "json-value", "kind": "canonical-json"},
    ]
    if primitive_spec["argument_types"] != expected_argument_types:
        return False
    argument_types = {
        row.get("id"): row
        for row in primitive_spec["argument_types"]
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if len(argument_types) != len(primitive_spec["argument_types"]) or any(
        set(row) < {"id", "kind"}
        or row.get("kind")
        not in {
            "canonical-json",
            "derived-name",
            "enum",
            "model-fact-bindings",
            "non-empty-list",
            "role-name",
            "selector",
            "string",
            "string-list",
        }
        for row in argument_types.values()
    ):
        return False
    charge_events = {row["event"] for row in accounting["charge_rules"]}
    expected_evaluations = {
        "content-identity": {
            "kind": "content-identity",
            "selector": "selector",
            "selection_cardinality": "exactly-one",
            "domain": "identity_domain",
            "result": "result",
            "canonical_encoding": "kernel.canonical_encoding",
        },
        "concatenate-selections": {
            "kind": "concatenate-selections",
            "selectors": "selectors",
            "order": "selector-order-then-member-order",
            "result": "result",
        },
        "model-source-admission": {
            "kind": "model-source-admission",
            "role": "role",
            "role_cardinality": "exactly-one",
            "authority": "exact-caller-pair",
            "bindings": "fact_bindings",
        },
        "canonical-unique": {
            "kind": "canonical-unique",
            "selector": "selector",
            "selection_cardinality": "one-or-more",
            "equality": "kernel-canonical-bytes",
        },
        "canonical-inventory": {
            "kind": "canonical-inventory",
            "selector": "selector",
            "selection_cardinality": "one-or-more",
            "inventory": "inventory",
            "relation": "subset",
            "equality": "kernel-canonical-bytes",
        },
        "canonical-set-relation": {
            "kind": "canonical-set-relation",
            "left": "left",
            "right": "right",
            "relation": "relation",
            "relations": ["equal", "subset"],
            "equality": "kernel-canonical-bytes",
        },
        "canonical-scoped-relation": {
            "kind": "canonical-scoped-relation",
            "source": "source",
            "source_scope_path": "source_scope_path",
            "source_values_path": "source_values_path",
            "target": "target",
            "target_scope_path": "target_scope_path",
            "target_values_path": "target_values_path",
            "row_scope_cardinality": "exactly-one",
            "row_values_cardinality": "one-or-more",
            "relation": "relation",
            "relations": ["equal", "subset"],
            "equality": "kernel-canonical-bytes",
        },
        "canonical-scoped-unique": {
            "kind": "canonical-scoped-unique",
            "selector": "selector",
            "scope_path": "scope_path",
            "values_path": "values_path",
            "row_scope_cardinality": "exactly-one",
            "row_values_cardinality": "one-or-more",
            "equality": "kernel-canonical-bytes",
        },
        "closed-int64-interval": {
            "kind": "closed-int64-interval",
            "selector": "selector",
            "selection_cardinality": "one-or-more",
            "minimum_member": "minimum_member",
            "maximum_member": "maximum_member",
            "integer_domain": "signed-int64-excluding-boolean",
        },
        "closed-int64-interval-join": {
            "kind": "closed-int64-interval-join",
            "source": "source",
            "source_key_path": "source_key_path",
            "source_value_path": "source_value_path",
            "target": "target",
            "target_key_path": "target_key_path",
            "target_interval_path": "target_interval_path",
            "target_key_cardinality": "exactly-one",
            "target_interval_cardinality": "exactly-one",
            "source_key_cardinality": "exactly-one",
            "source_value_cardinality": "exactly-one",
            "minimum_member": "minimum_member",
            "maximum_member": "maximum_member",
            "integer_domain": "signed-int64-excluding-boolean",
            "key_equality": "kernel-canonical-bytes",
        },
        "model-source-vector": {
            "kind": "model-source-vector",
            "role": "role",
            "pointer_path": "pointer_path",
            "value_path": "value_path",
            "outcome": "outcome",
            "diagnostic_path": "diagnostic_path",
            "expected_path": "expected_path",
            "expected_value": "expected_value",
            "pointer_encoding": "RFC6901-existing-target",
            "mutation": "deep-copy-single-replacement",
            "admission": "exact-caller-pair",
            "refused_diagnostic_cardinality": "exactly-one",
        },
    }
    expected_effects = {
        "content-identity": "bind-derived",
        "concatenate-selections": "bind-derived",
        "model-source-admission": "bind-model-facts",
        "canonical-unique": "preserve-graph",
        "canonical-inventory": "preserve-graph",
        "canonical-set-relation": "preserve-graph",
        "canonical-scoped-relation": "preserve-graph",
        "canonical-scoped-unique": "preserve-graph",
        "closed-int64-interval": "preserve-graph",
        "closed-int64-interval-join": "preserve-graph",
        "model-source-vector": "preserve-graph",
    }
    expected_charges = {
        "content-identity": ["judgment", "selected-value"],
        "concatenate-selections": ["judgment", "selected-value"],
        "model-source-admission": ["judgment"],
        "canonical-unique": ["judgment", "selected-value"],
        "canonical-inventory": ["judgment", "selected-value"],
        "canonical-set-relation": ["judgment", "selected-value"],
        "canonical-scoped-relation": ["judgment", "selected-value", "scoped-row"],
        "canonical-scoped-unique": ["judgment", "selected-value", "scoped-row"],
        "closed-int64-interval": ["judgment", "selected-value"],
        "closed-int64-interval-join": ["judgment", "selected-value"],
        "model-source-vector": ["judgment", "selected-value", "vector-execution"],
    }
    primitives: dict[str, dict[str, Any]] = {}
    found_kinds: set[str] = set()
    for primitive in primitive_spec["primitives"]:
        if not isinstance(primitive, dict):
            return False
        primitive_id = primitive.get("id")
        evaluation = primitive.get("evaluation")
        base_members = {
            "argument_members",
            "argument_types",
            "charges",
            "evaluation",
            "failure",
            "id",
            "result_effect",
        }
        if (
            not isinstance(primitive_id, str)
            or primitive_id in primitives
            or set(primitive) not in (base_members, base_members | {"result_members"})
            or not isinstance(evaluation, dict)
            or evaluation.get("kind") not in expected_evaluations
            or evaluation != expected_evaluations[evaluation["kind"]]
            or evaluation["kind"] in found_kinds
            or not isinstance(primitive.get("argument_members"), list)
            or not primitive["argument_members"]
            or len(primitive["argument_members"])
            != len(set(primitive["argument_members"]))
            or not isinstance(primitive.get("argument_types"), dict)
            or set(primitive["argument_types"]) != set(primitive["argument_members"])
            or not set(primitive["argument_types"].values()) <= set(argument_types)
            or primitive.get("failure")
            != {"mode": "judgment-diagnostic", "short_circuit": True}
            or not isinstance(primitive.get("charges"), list)
            or "judgment" not in primitive["charges"]
            or not set(primitive["charges"]) <= charge_events
            or primitive.get("result_effect") != expected_effects[evaluation["kind"]]
            or primitive["charges"] != expected_charges[evaluation["kind"]]
            or (
                evaluation["kind"] == "model-source-admission"
                and primitive.get("result_members")
                != ["root_requirements", "resolved_packages", "source_symbols"]
            )
        ):
            return False
        primitives[primitive_id] = primitive
        found_kinds.add(evaluation["kind"])
    if found_kinds != set(expected_evaluations):
        return False
    operations: dict[str, dict[str, Any]] = {}
    for row in operation_rows:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "effects",
                "id",
                "input",
                "law",
                "refusals",
                "resources",
                "result",
            }
            or not isinstance(row.get("id"), str)
            or row["id"] in operations
            or row.get("input") != {"fact_kind": "template-graph"}
            or row.get("result") != {"fact_kind": "template-graph"}
            or row.get("effects") != []
            or row.get("refusals") != ["reason-bound-diagnostic"]
            or not isinstance(row.get("resources"), list)
            or "max_template_admission_steps" not in row["resources"]
        ):
            return False
        law = row.get("law")
        if (
            not isinstance(law, dict)
            or set(law) != {"operator", "primitive"}
            or law.get("operator") != row["id"]
            or law.get("primitive") not in primitives
        ):
            return False
        operations[row["id"]] = row

    profiles = language.get("template_admission_profiles")
    diagnostics = {
        row.get("code") for row in ldb.get("diagnostics", []) if isinstance(row, dict)
    }
    if not isinstance(profiles, list) or len(profiles) != 1:
        return False
    profile = profiles[0]
    if not isinstance(profile, dict) or set(profile) != {
        "id",
        "judgments",
        "max_steps_path",
        "member_identity_domain",
        "member_roles",
        "resource_diagnostic",
        "structural_diagnostic",
    }:
        return False
    roles = profile.get("member_roles")
    judgments = profile.get("judgments")
    role_names = {row.get("role") for row in roles or [] if isinstance(row, dict)}
    standalone_schema_kinds = {
        row.get("artifact_kind")
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for row in language.get(collection, [])
        if isinstance(row, dict) and "wire_schema_identity_domain" in row
    }
    artifact_schema_kinds = {
        row.get("artifact_kind")
        for row in language.get("artifact_contracts", [])
        if isinstance(row, dict)
    }
    schema_kinds = standalone_schema_kinds | artifact_schema_kinds
    if (
        not isinstance(roles, list)
        or not roles
        or not standalone_schema_kinds.isdisjoint(artifact_schema_kinds)
        or len(roles) != len(role_names)
        or any(
            not isinstance(row, dict)
            or set(row) != {"cardinality", "member_kind", "required_operations", "role"}
            or row.get("cardinality") not in role_cardinalities
            or not isinstance(row.get("role"), str)
            or not row["role"]
            or not isinstance(row.get("member_kind"), str)
            or row["member_kind"] not in schema_kinds
            or not isinstance(row.get("required_operations"), list)
            or any(
                operation not in operations
                for operation in row.get("required_operations", [])
            )
            or len(row.get("required_operations", []))
            != len(set(row.get("required_operations", [])))
            for row in roles
        )
        or len({row.get("member_kind") for row in roles if isinstance(row, dict)})
        != len(roles)
        or not isinstance(judgments, list)
        or not judgments
        or not isinstance(profile.get("member_identity_domain"), str)
        or not profile["member_identity_domain"]
        or profile.get("max_steps_path") != accounting["limit_path"]
        or profile.get("resource_diagnostic") != accounting["exhaustion_diagnostic"]
        or profile.get("resource_diagnostic") not in diagnostics
        or profile.get("structural_diagnostic") not in diagnostics
    ):
        return False
    model_source_roles = {
        row["role"]
        for row in roles
        if isinstance(row, dict)
        and row.get("member_kind") == "model-source-package"
        and isinstance(row.get("role"), str)
    }
    resolution_profiles = language.get("resolution_profiles")
    default_source_domains = (
        {
            row.get("source_identity_domain")
            for row in resolution_profiles
            if isinstance(row, dict)
            and row.get("default") is True
            and isinstance(row.get("source_identity_domain"), str)
            and row["source_identity_domain"]
        }
        if isinstance(resolution_profiles, list)
        else set()
    )
    if len(model_source_roles) != 1 or len(default_source_domains) != 1:
        return False
    found, limit = _consumer_b_exact_path(ldb, profile["max_steps_path"])
    if not found or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return False

    judgment_ids: set[str] = set()
    used_operations: set[str] = set()
    used_primitives: set[str] = set()
    role_operations: set[tuple[str, str]] = set()
    produced: set[str] = set()
    model_source_identity_domains: set[str] = set()
    selector_members = {"inventory", "left", "right", "selector", "source", "target"}
    roots = set(selector["roots"])

    def argument_is_typed(
        value: Any,
        contract: dict[str, Any],
        *,
        result_members: set[str],
    ) -> bool:
        kind = contract["kind"]
        if kind == "selector":
            return (
                isinstance(value, dict)
                and set(value) == {"name", "path", "root"}
                and isinstance(value.get("root"), str)
                and value["root"] in roots
                and isinstance(value.get("name"), str)
                and isinstance(value.get("path"), list)
                and all(isinstance(part, str) and part for part in value["path"])
                and (value["root"] != "role" or value["name"] in role_names)
            )
        if kind == "non-empty-list":
            item_contract = argument_types.get(contract.get("item"))
            return (
                isinstance(value, list)
                and bool(value)
                and item_contract is not None
                and all(
                    argument_is_typed(
                        item, item_contract, result_members=result_members
                    )
                    for item in value
                )
            )
        if kind == "role-name":
            return isinstance(value, str) and value in role_names
        if kind == "string-list":
            return (
                isinstance(value, list)
                and (contract.get("empty") is True or bool(value))
                and all(isinstance(part, str) and part for part in value)
            )
        if kind == "string":
            return isinstance(value, str) and (
                contract.get("empty") is True or bool(value)
            )
        if kind == "derived-name":
            return (
                isinstance(value, str)
                and bool(value)
                and (contract.get("fresh") is not True or value not in produced)
            )
        if kind == "model-fact-bindings":
            return (
                isinstance(value, list)
                and (contract.get("cardinality") != "one-or-more" or bool(value))
                and all(
                    isinstance(binding, dict)
                    and set(binding) == {"result", "source"}
                    and isinstance(binding.get("source"), str)
                    and binding["source"] in result_members
                    and isinstance(binding.get("result"), str)
                    and bool(binding["result"])
                    and binding["result"] not in produced
                    for binding in value
                )
                and len({binding["source"] for binding in value}) == len(value)
                and len({binding["result"] for binding in value}) == len(value)
            )
        if kind == "enum":
            return value in contract.get("values", [])
        if kind == "canonical-json":
            try:
                _encoded(value)
            except (TypeError, ValueError, UnicodeEncodeError):
                return False
            return True
        return False

    for judgment in judgments:
        if (
            not isinstance(judgment, dict)
            or set(judgment) != {"arguments", "diagnostic", "id", "operation"}
            or not isinstance(judgment.get("id"), str)
            or judgment["id"] in judgment_ids
            or judgment.get("diagnostic") not in diagnostics
            or judgment.get("operation") not in operations
            or not isinstance(judgment.get("arguments"), dict)
        ):
            return False
        arguments = judgment["arguments"]
        law = operations[judgment["operation"]]["law"]
        primitive = primitives[law["primitive"]]
        if set(arguments) != set(primitive["argument_members"]) or any(
            not argument_is_typed(
                arguments[name],
                argument_types[type_id],
                result_members=set(primitive.get("result_members", [])),
            )
            for name, type_id in primitive["argument_types"].items()
        ):
            return False
        if primitive["evaluation"]["kind"] == "content-identity":
            source_selector = arguments.get("selector")
            if (
                isinstance(source_selector, dict)
                and source_selector.get("root") == "role"
                and source_selector.get("name") in model_source_roles
                and isinstance(arguments.get("identity_domain"), str)
            ):
                model_source_identity_domains.add(arguments["identity_domain"])
        selected: list[dict[str, Any]] = []
        for name, value in arguments.items():
            if name in selector_members:
                if (
                    not isinstance(value, dict)
                    or set(value) != {"name", "path", "root"}
                    or value.get("root") not in roots
                    or not isinstance(value.get("name"), str)
                    or not isinstance(value.get("path"), list)
                    or not all(isinstance(part, str) and part for part in value["path"])
                    or (value["root"] == "role" and value["name"] not in role_names)
                ):
                    return False
                selected.append(value)
            if name == "selectors":
                if not isinstance(value, list) or not value:
                    return False
                for item in value:
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"name", "path", "root"}
                        or item.get("root") not in roots
                        or not isinstance(item.get("name"), str)
                        or not isinstance(item.get("path"), list)
                        or not all(
                            isinstance(part, str) and part for part in item["path"]
                        )
                        or (item["root"] == "role" and item["name"] not in role_names)
                    ):
                        return False
                    selected.append(item)
            if name.endswith("_path") and (
                not isinstance(value, list)
                or not all(isinstance(part, str) and part for part in value)
            ):
                return False
        for selected_value in selected:
            if selected_value["root"] == "role":
                role_operations.add((selected_value["name"], judgment["operation"]))
            if (
                selected_value["root"] == "derived"
                and selected_value["name"] not in produced
            ):
                return False
        if arguments.get("relation") not in {None, "equal", "subset"}:
            return False
        if arguments.get("outcome") not in {None, "admitted", "refused"}:
            return False
        role = arguments.get("role")
        if role is not None:
            if not isinstance(role, str) or role not in role_names:
                return False
            role_operations.add((role, judgment["operation"]))
        kind = primitive["evaluation"]["kind"]
        if kind == "model-source-admission":
            bindings = arguments.get("fact_bindings")
            result_members = primitive.get("result_members")
            if (
                not isinstance(bindings, list)
                or not bindings
                or not isinstance(result_members, list)
                or any(
                    not isinstance(binding, dict)
                    or set(binding) != {"result", "source"}
                    or binding.get("source") not in result_members
                    or not isinstance(binding.get("result"), str)
                    or binding["result"] in produced
                    for binding in bindings
                )
                or len({binding["source"] for binding in bindings}) != len(bindings)
                or len({binding["result"] for binding in bindings}) != len(bindings)
            ):
                return False
            produced.update(binding["result"] for binding in bindings)
        if kind in {"concatenate-selections", "content-identity"}:
            result = arguments.get("result")
            if (
                not isinstance(result, str)
                or not result
                or result in produced
                or (
                    kind == "content-identity"
                    and (
                        not isinstance(arguments.get("identity_domain"), str)
                        or not arguments["identity_domain"]
                    )
                )
            ):
                return False
            produced.add(result)
        judgment_ids.add(judgment["id"])
        used_operations.add(judgment["operation"])
        used_primitives.add(law["primitive"])
    required_pairs = {
        (row["role"], operation)
        for row in roles
        if isinstance(row, dict)
        for operation in row["required_operations"]
    }
    return (
        used_operations == set(operations)
        and used_primitives == set(primitives)
        and required_pairs <= role_operations
        and model_source_identity_domains == default_source_domains
    )


def _consumer_b_language_definitions_are_closed(
    ldb: dict[str, Any], meta: dict[str, Any]
) -> bool:
    language = ldb.get("language")
    authority = meta.get("language_definitions")
    if not isinstance(language, dict) or not isinstance(authority, dict):
        return False
    collections = authority.get("collections")
    if not isinstance(collections, dict):
        return False
    for name, contract in collections.items():
        values = language.get(name)
        if not isinstance(values, list) or not isinstance(contract, dict):
            return False
        if "max_items" in contract:
            max_items = contract["max_items"]
            if not isinstance(max_items, int) or len(values) > max_items:
                return False
            continue
        if "item_type" in contract:
            if not all(
                _consumer_b_value_matches(value, {"type": contract["item_type"]}, ldb)
                for value in values
            ):
                return False
            continue
        if not all(
            _consumer_b_definition_is_closed(value, contract, ldb) for value in values
        ):
            return False
    quantity = language.get("quantity")
    quantity_contract = authority.get("quantity")
    if not isinstance(quantity, dict) or not isinstance(quantity_contract, dict):
        return False
    required = quantity_contract.get("required_members")
    quantity_collections = quantity_contract.get("collections")
    if (
        not isinstance(required, list)
        or set(quantity) != set(required)
        or not isinstance(quantity_collections, dict)
        or set(quantity_collections) != set(required)
    ):
        return False
    for name, contract in quantity_collections.items():
        values = quantity.get(name)
        if not isinstance(values, list) or not isinstance(contract, dict):
            return False
        if "item_type" in contract:
            if not all(
                _consumer_b_value_matches(value, {"type": contract["item_type"]}, ldb)
                for value in values
            ):
                return False
        elif not all(
            _consumer_b_definition_is_closed(value, contract, ldb) for value in values
        ):
            return False
    if not _consumer_b_template_admission_is_closed(meta, ldb):
        return False
    fact_schemas = _consumer_b_fact_schemas(meta)
    rules = language.get("rules")
    lowerings = language.get("model_lowerings")
    profiles = language.get("resolution_profiles")
    if (
        not fact_schemas
        or not isinstance(rules, list)
        or not isinstance(lowerings, list)
        or not isinstance(profiles, list)
    ):
        return False
    rules_by_id = {
        rule["id"]: rule
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str)
    }
    profiles_by_id = {
        profile["id"]: profile
        for profile in profiles
        if isinstance(profile, dict) and isinstance(profile.get("id"), str)
    }
    resolution_contract = meta.get("resolution_judgment")
    operation_specs = (
        resolution_contract.get("operations")
        if isinstance(resolution_contract, dict)
        else None
    )
    operation_order = [
        item["id"] for item in operation_specs or [] if isinstance(item, dict)
    ]
    operations_by_id = {
        item["id"]: item
        for item in operation_specs or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    reason_stages = {
        item["id"]: item["stage"]
        for item in language.get("reasons", [])
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("stage"), str)
    }
    accounting = (
        resolution_contract.get("resource_accounting")
        if isinstance(resolution_contract, dict)
        else None
    )
    exhaustion_reason = (
        accounting.get("exhaustion_reason") if isinstance(accounting, dict) else None
    )
    resource_reasons = [
        item
        for item in language.get("reasons", [])
        if isinstance(exhaustion_reason, dict)
        and isinstance(item, dict)
        and item.get("stage") == exhaustion_reason.get("stage")
        and isinstance(item.get("predicate"), dict)
        and item["predicate"].get("operation") == exhaustion_reason.get("operation")
        and item["predicate"].get("limit_path") == exhaustion_reason.get("limit_path")
    ]
    runtime_projection_contract = meta.get("runtime_projection")
    runtime_accounting = (
        runtime_projection_contract.get("resource_accounting")
        if isinstance(runtime_projection_contract, dict)
        else None
    )
    runtime_exhaustion = (
        runtime_accounting.get("exhaustion_reason")
        if isinstance(runtime_accounting, dict)
        else None
    )
    runtime_resource_reasons = [
        item
        for item in language.get("reasons", [])
        if isinstance(runtime_exhaustion, dict)
        and isinstance(item, dict)
        and item.get("stage") == runtime_exhaustion.get("stage")
        and isinstance(item.get("predicate"), dict)
        and item["predicate"].get("operation") == runtime_exhaustion.get("operation")
        and item["predicate"].get("limit_path") == runtime_exhaustion.get("limit_path")
    ]
    if (
        len(profiles_by_id) != len(profiles)
        or not isinstance(resolution_contract, dict)
        or not _consumer_b_resolution_contract_is_closed(resolution_contract)
        or not isinstance(operation_specs, list)
        or not operation_specs
        or len(operations_by_id) != len(operation_specs)
        or len(resource_reasons) != 1
        or len(runtime_resource_reasons) != 1
        or len([profile for profile in profiles if profile.get("default") is True]) != 1
    ):
        return False
    for profile in profiles:
        chain = profile.get("judgment_chain")
        if (
            not isinstance(chain, list)
            or not _consumer_b_relation_recipes_are_closed(
                profile,
                resolution_contract,
                ldb,
                meta["package_release"],
            )
            or [item.get("operation") for item in chain if isinstance(item, dict)]
            != operation_order
            or any(
                not isinstance(item, dict)
                or item.get("operation") not in operations_by_id
                or reason_stages.get(item.get("reason"))
                != operations_by_id[item["operation"]].get("stage")
                for item in chain
            )
        ):
            return False
    for lowering in lowerings:
        if not isinstance(lowering, dict):
            return False
        equalities = lowering.get("output_equalities")
        profile_id = lowering.get("resolution_profile")
        paths = [
            (lowering.get("rule_chain"), lowering.get("initial_fact_kind")),
            (
                lowering.get("structured_rule_chain"),
                lowering.get("structured_initial_fact_kind"),
            ),
        ]
        if not isinstance(profile_id, str):
            return False
        profile = profiles_by_id.get(profile_id)
        if (
            not isinstance(equalities, list)
            or not all(isinstance(item, dict) for item in equalities)
            or not isinstance(profile, dict)
        ):
            return False
        for chain, initial_kind in paths:
            initial_fields = (
                fact_schemas.get(initial_kind)
                if isinstance(initial_kind, str)
                else None
            )
            if (
                not isinstance(chain, list)
                or not chain
                or not isinstance(initial_fields, dict)
                or profile.get("symbol_fact_member") not in initial_fields
            ):
                return False
            terminal = chain[-1]
            rule = (
                rules_by_id.get(terminal.get("rule"))
                if isinstance(terminal, dict)
                else None
            )
            conclusion = rule.get("conclusion") if isinstance(rule, dict) else None
            kind = conclusion.get("fact_kind") if isinstance(conclusion, dict) else None
            fields = fact_schemas.get(kind) if isinstance(kind, str) else None
            pairs: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
            if not isinstance(
                fields, dict
            ) or not _consumer_b_runtime_projection_is_closed(
                lowering.get("runtime_projection"),
                runtime_projection_contract,
                ldb,
                fields,
                meta["language_definitions"],
            ):
                return False
            for equality in equalities:
                left = equality.get("left")
                right = equality.get("right")
                if (
                    not _consumer_b_fact_contract_path_is_declared(fields, left)
                    or not _consumer_b_fact_contract_path_is_declared(fields, right)
                    or left == right
                ):
                    return False
                left_contract = _consumer_b_fact_contract_at_path(fields, left)
                right_contract = _consumer_b_fact_contract_at_path(fields, right)
                left_kind = _consumer_b_contract_kind(left_contract)
                right_kind = _consumer_b_contract_kind(right_contract)
                if (
                    left_kind is None
                    or left_kind != right_kind
                    or (
                        left_kind in {"array", "object"}
                        and left_contract != right_contract
                    )
                ):
                    return False
                pairs.append((tuple(left), tuple(right)))
            if len(pairs) != len(set(pairs)):
                return False
            if not any(left == (profile["symbol_fact_member"],) for left, _ in pairs):
                return False
    return True


def _consumer_b_evidence_claim_kinds_are_closed(
    ldb: dict[str, Any], meta: dict[str, Any]
) -> bool:
    language = ldb.get("language")
    definitions = meta.get("language_definitions")
    collections = (
        definitions.get("collections") if isinstance(definitions, dict) else None
    )
    contract = (
        collections.get("evidence_claim_kinds")
        if isinstance(collections, dict)
        else None
    )
    if not isinstance(contract, dict):
        return False
    try:
        graph_states = set(
            contract["field_types"]["vectors"]["items"]["field_types"]["input"][
                "field_types"
            ]["graph"]["enum"]
        )
    except (KeyError, TypeError):
        return False
    claim_kinds = (
        language.get("evidence_claim_kinds") if isinstance(language, dict) else None
    )
    if not isinstance(claim_kinds, list) or graph_states <= {"exact"}:
        return False
    claim_ids: set[str] = set()
    for claim_kind in claim_kinds:
        if not isinstance(claim_kind, dict):
            return False
        claim_id = claim_kind.get("id")
        roles = claim_kind.get("subject_roles")
        edges = claim_kind.get("prerequisite_edges")
        eligibility = claim_kind.get("eligibility")
        vectors = claim_kind.get("vectors")
        if (
            not isinstance(claim_id, str)
            or claim_id in claim_ids
            or not isinstance(roles, list)
            or not roles
            or not all(isinstance(role, str) and role for role in roles)
            or len(roles) != len(set(roles))
            or not isinstance(edges, list)
            or not isinstance(eligibility, dict)
            or not isinstance(vectors, list)
            or not vectors
        ):
            return False
        claim_ids.add(claim_id)
        role_set = set(roles)
        edge_pairs = [
            (edge.get("subject"), edge.get("prerequisite"))
            for edge in edges
            if isinstance(edge, dict)
        ]
        if (
            len(edge_pairs) != len(edges)
            or len(edge_pairs) != len(set(edge_pairs))
            or any(
                subject not in role_set
                or prerequisite not in role_set
                or subject == prerequisite
                for subject, prerequisite in edge_pairs
            )
        ):
            return False
        pending = set(role_set)
        while pending:
            ready = {
                role
                for role in pending
                if all(
                    prerequisite not in pending
                    for subject, prerequisite in edge_pairs
                    if subject == role
                )
            }
            if not ready:
                return False
            pending -= ready
        producing_outcomes = eligibility.get("producing_outcomes")
        required_variant = eligibility.get("runtime_refusal_variant")
        if (
            eligibility.get("runtime_dispatch") != "required"
            or eligibility.get("claim_state") != "candidate"
            or not isinstance(producing_outcomes, list)
            or not producing_outcomes
            or not all(
                isinstance(outcome, str) and outcome for outcome in producing_outcomes
            )
            or len(producing_outcomes) != len(set(producing_outcomes))
            or not isinstance(required_variant, str)
        ):
            return False
        vector_ids: set[str] = set()
        positive_outcomes: set[str] = set()
        negative_graphs: set[str] = set()
        has_pre_dispatch = False
        for vector in vectors:
            if not isinstance(vector, dict):
                return False
            vector_input = vector.get("input")
            vector_id = vector.get("id")
            if (
                not isinstance(vector_input, dict)
                or not isinstance(vector_id, str)
                or vector_id in vector_ids
            ):
                return False
            vector_ids.add(vector_id)
            graph = vector_input.get("graph")
            outcome = vector_input.get("producing_outcome")
            dispatch = vector_input.get("runtime_dispatch")
            refusal_variant = vector_input.get("runtime_refusal_variant")
            eligible = (
                graph == "exact"
                and dispatch == "reached"
                and outcome in producing_outcomes
                and (
                    (
                        outcome == "runtime-refusal"
                        and refusal_variant == required_variant
                    )
                    or (
                        outcome != "runtime-refusal"
                        and refusal_variant == "not-applicable"
                    )
                )
            )
            expected = "candidate" if eligible else "refusal"
            expected_kind = "positive" if eligible else "negative"
            if vector.get("expect") != expected or vector.get("kind") != expected_kind:
                return False
            if eligible and isinstance(outcome, str):
                positive_outcomes.add(outcome)
            if not eligible and isinstance(graph, str) and graph != "exact":
                negative_graphs.add(graph)
            if not eligible and dispatch == "not-reached":
                has_pre_dispatch = True
        if (
            positive_outcomes != set(producing_outcomes)
            or negative_graphs != graph_states - {"exact"}
            or not has_pre_dispatch
        ):
            return False
    return True


def _consumer_b_artifact_semantic_projections_are_closed(
    ldb: dict[str, Any],
) -> bool:
    language = ldb.get("language")
    if not isinstance(language, dict):
        return False
    contracts = language.get("artifact_contracts")
    schemas = language.get("artifact_wire_schemas")
    if not isinstance(contracts, list) or not isinstance(schemas, list):
        return False
    schemas_by_kind = {
        row.get("artifact_kind"): row.get("schema")
        for row in schemas
        if isinstance(row, dict)
        and isinstance(row.get("artifact_kind"), str)
        and isinstance(row.get("schema"), dict)
    }
    for contract in contracts:
        if not isinstance(contract, dict):
            return False
        projection = contract.get("semantic_identity_projection")
        if projection is None:
            continue
        schema = schemas_by_kind.get(contract.get("schema_kind"))
        root_exclusions = (
            projection.get("excluded_root_members")
            if isinstance(projection, dict)
            else None
        )
        collection_exclusions = (
            projection.get("collection_member_exclusions")
            if isinstance(projection, dict)
            else None
        )
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if (
            not isinstance(contract.get("semantic_identity_domain"), str)
            or not isinstance(properties, dict)
            or not isinstance(root_exclusions, list)
            or not set(root_exclusions) <= set(properties)
            or not {"content_identity", "semantic_identity"} <= set(root_exclusions)
            or not isinstance(collection_exclusions, list)
            or len(
                {
                    row.get("collection_member")
                    for row in collection_exclusions
                    if isinstance(row, dict)
                }
            )
            != len(collection_exclusions)
        ):
            return False
        for row in collection_exclusions:
            collection_member = (
                row.get("collection_member") if isinstance(row, dict) else None
            )
            excluded_members = (
                row.get("excluded_members") if isinstance(row, dict) else None
            )
            collection_schema = properties.get(collection_member)
            item_schema = (
                collection_schema.get("items")
                if isinstance(collection_schema, dict)
                else None
            )
            item_properties = (
                item_schema.get("properties") if isinstance(item_schema, dict) else None
            )
            if (
                not isinstance(collection_member, str)
                or not isinstance(excluded_members, list)
                or not isinstance(item_properties, dict)
                or not set(excluded_members) <= set(item_properties)
            ):
                return False
    return True


def _consumer_b_assignment_policy_is_total(ldb: dict[str, Any]) -> bool:
    language = ldb.get("language")
    if not isinstance(language, dict):
        return False
    lowerings = language.get("model_lowerings")
    profiles = language.get("resolution_profiles")
    quantity = language.get("quantity")
    schemas = language.get("wire_schemas")
    if (
        not isinstance(lowerings, list)
        or len(lowerings) != 1
        or not isinstance(profiles, list)
        or not isinstance(quantity, dict)
        or not isinstance(quantity.get("symbol_roles"), list)
        or not isinstance(schemas, list)
    ):
        return False
    lowering = lowerings[0]
    if not isinstance(lowering, dict):
        return False
    selected_profiles = [
        profile
        for profile in profiles
        if isinstance(profile, dict)
        and profile.get("id") == lowering.get("resolution_profile")
    ]
    if len(selected_profiles) != 1:
        return False
    modules_member = selected_profiles[0].get("modules_member")
    symbols_member = selected_profiles[0].get("symbols_member")
    policy = lowering.get("assignment_policy")
    if (
        not isinstance(modules_member, str)
        or not isinstance(symbols_member, str)
        or not isinstance(policy, dict)
        or not isinstance(policy.get("roles"), list)
    ):
        return False
    role_rows = policy["roles"]
    roles = {
        row.get("role")
        for row in role_rows
        if isinstance(row, dict) and isinstance(row.get("role"), str)
    }
    if len(roles) != len(role_rows) or roles != set(quantity["symbol_roles"]):
        return False
    coherent_modes = {
        ("model", "required", "forbidden", False),
        ("experiment", "forbidden", "required", False),
        ("model-with-experiment-override", "required", "optional", True),
        ("execution", "forbidden", "forbidden", False),
        ("named-random-stream", "forbidden", "forbidden", False),
        ("resolved-model", "forbidden", "forbidden", False),
    }
    declared_modes: set[str] = set()
    for row in role_rows:
        modes = row.get("modes")
        accesses = row.get("entrypoint_operand_access")
        result = row.get("entrypoint_result")
        binding_kind = row.get("binding_kind")
        if (
            not isinstance(modes, list)
            or not modes
            or not isinstance(accesses, list)
            or not isinstance(result, bool)
            or any(
                not isinstance(mode, dict)
                or not isinstance(mode.get("id"), str)
                or not mode["id"]
                or (
                    mode.get("initialization_source"),
                    mode.get("value_member"),
                    mode.get("experiment_cardinality"),
                    mode.get("override"),
                )
                not in coherent_modes
                or mode.get("event_payload_cardinality")
                not in {"forbidden", "optional", "required"}
                or mode.get("external_fact_cardinality")
                not in {"forbidden", "optional", "required"}
                for mode in modes
            )
            or len({mode["id"] for mode in modes}) != len(modes)
            or any(access not in {"read", "read-write", "write"} for access in accesses)
            or (
                binding_kind == "operand"
                and (
                    not accesses
                    or result is not False
                    or any(
                        mode["experiment_cardinality"] == "forbidden"
                        and mode["initialization_source"]
                        not in {"model", "model-with-experiment-override"}
                        and not (
                            row.get("role") == "derived"
                            and mode["initialization_source"] == "resolved-model"
                        )
                        for mode in modes
                    )
                    or any(
                        mode["event_payload_cardinality"] != "forbidden"
                        and not (
                            accesses == ["read"]
                            and mode["initialization_source"]
                            in {"experiment", "model-with-experiment-override"}
                        )
                        for mode in modes
                    )
                    or any(
                        mode["external_fact_cardinality"] != "forbidden"
                        and not (
                            accesses == ["read"]
                            and mode["initialization_source"] == "experiment"
                        )
                        for mode in modes
                    )
                )
            )
            or (
                binding_kind == "result"
                and (
                    accesses
                    or result is not True
                    or any(
                        mode["initialization_source"] != "execution" for mode in modes
                    )
                    or any(
                        mode["event_payload_cardinality"] != "forbidden"
                        for mode in modes
                    )
                    or any(
                        mode["external_fact_cardinality"] != "forbidden"
                        for mode in modes
                    )
                )
            )
            or (
                binding_kind == "internal"
                and (
                    accesses
                    or result is not False
                    or any(
                        mode["event_payload_cardinality"] != "forbidden"
                        for mode in modes
                    )
                    or any(
                        mode["external_fact_cardinality"] != "forbidden"
                        for mode in modes
                    )
                )
            )
            or binding_kind not in {"operand", "result", "internal"}
        ):
            return False
        declared_modes.update(mode["id"] for mode in modes)
    model_schemas = [
        row["schema"]
        for row in schemas
        if isinstance(row, dict)
        and row.get("artifact_kind") == "model-source-package"
        and isinstance(row.get("schema"), dict)
    ]
    if len(model_schemas) != 1:
        return False
    try:
        schema_modes = set(
            model_schemas[0]["properties"][modules_member]["items"]["properties"][
                symbols_member
            ]["items"]["properties"]["value_policy"]["properties"]["mode"]["enum"]
        )
    except (KeyError, TypeError):
        return False
    return schema_modes == declared_modes


def _consumer_b_literal_typing_profiles_are_closed(
    kernel: dict[str, Any],
    ldb: dict[str, Any],
) -> bool:
    contract = kernel.get("meta_format", {}).get("literal_typing")
    expected = {
        "closed": True,
        "collection": "language.literal_typing_profiles",
        "selection": "unique-formal-match",
        "source_kinds": ["integer", "typed-envelope"],
        "match_members": [
            "type",
            "representation",
            "kind",
            "unit",
            "domain",
            "numeric_policy",
        ],
        "range_members": {"maximum": "maximum", "minimum": "minimum"},
        "ownership": {
            "integer": "profile-owner-must-own-exact-type-export",
            "typed-envelope": "profile-owner-must-own-structured-constructors",
        },
        "formal_closure": "at-least-one-exact-operation-value-contract",
        "overlap_policy": "refuse-overlapping-ranges-per-source-and-match-contract",
        "typed_envelope_profile": {
            "admission": {
                "envelope_members": ["type", "value"],
                "nominal_type_reference": {
                    "coordinate_members": ["package", "version", "id"],
                    "optional_kind_member": "kind",
                    "optional_kind_value": "nominal",
                },
                "operator": "recursive-typed-envelope",
                "resource_charge_per_node": 1,
                "type_relation": "exact-selected-type",
            },
            "id": "standard.schema.nominal-structured",
            "required_constructors": [
                "standard.schema.enum",
                "standard.schema.list",
                "standard.schema.record",
                "standard.schema.ref",
            ],
            "selection": "exact-envelope-type",
            "type_member": "type",
            "value_kind": "nominal-structured",
            "value_member": "value",
        },
    }
    language = ldb.get("language")
    if contract != expected or not isinstance(language, dict):
        return False
    profiles = language.get("literal_typing_profiles")
    packages = language.get("packages")
    operations = language.get("operations")
    quantity = language.get("quantity")
    if (
        not isinstance(profiles, list)
        or not profiles
        or not isinstance(packages, list)
        or not isinstance(operations, list)
        or not isinstance(quantity, dict)
    ):
        return False
    inventories = {
        "representation": set(quantity.get("representations", [])),
        "kind": set(quantity.get("kinds", [])),
        "unit": {
            row.get("id") for row in quantity.get("units", []) if isinstance(row, dict)
        },
        "numeric_policy": {
            row.get("id")
            for row in quantity.get("numeric_policies", [])
            if isinstance(row, dict)
        },
    }
    owners: dict[str, list[dict[str, Any]]] = {}
    for package in packages:
        exports = package.get("exports") if isinstance(package, dict) else None
        exported_profiles = (
            exports.get("literal_typing_profiles")
            if isinstance(exports, dict)
            else None
        )
        if not isinstance(exported_profiles, list):
            return False
        for profile_id in exported_profiles:
            if not isinstance(profile_id, str):
                return False
            owners.setdefault(profile_id, []).append(package)
    formals: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            return False
        inputs = operation.get("inputs")
        result = operation.get("result")
        if not isinstance(inputs, list) or not isinstance(result, dict):
            return False
        formals.extend(item for item in inputs if isinstance(item, dict))
        formals.append(result)
    match_members = cast(list[str], expected["match_members"])
    typed_profile_contract = cast(dict[str, Any], expected["typed_envelope_profile"])
    numeric_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            return False
        if profile.get("source_kind") == "typed-envelope":
            profile_id = profile.get("id")
            owner_rows = owners.get(cast(str, profile_id), [])
            owner = owner_rows[0] if len(owner_rows) == 1 else None
            owner_exports = owner.get("exports") if isinstance(owner, dict) else None
            if (
                set(profile) != {"admission", "id", "source_kind", "value_kind"}
                or profile.get("admission") != typed_profile_contract["admission"]
                or profile_id != typed_profile_contract["id"]
                or profile.get("value_kind") != typed_profile_contract["value_kind"]
                or not isinstance(owner_exports, dict)
                or set(owner_exports.get("constructors", []))
                != set(typed_profile_contract["required_constructors"])
                or not any(
                    formal.get("value_kind") == typed_profile_contract["value_kind"]
                    and isinstance(formal.get("type"), dict)
                    for formal in formals
                )
            ):
                return False
            continue
        if (
            not isinstance(profile, dict)
            or profile.get("source_kind") != "integer"
            or not isinstance(profile.get("id"), str)
            or len(owners.get(cast(str, profile.get("id")), [])) != 1
            or type(profile.get("minimum")) is not int
            or type(profile.get("maximum")) is not int
            or profile["minimum"] > profile["maximum"]
            or any(
                profile.get(member) not in values
                for member, values in inventories.items()
            )
            or not isinstance(profile.get("type"), dict)
        ):
            return False
        numeric_profiles.append(profile)
        owner = owners[cast(str, profile["id"])][0]
        type_ref = cast(dict[str, Any], profile["type"])
        exported_types = cast(dict[str, Any], owner["exports"]).get("types")
        if (
            type_ref.get("package") != owner.get("id")
            or type_ref.get("version") != owner.get("version")
            or not isinstance(exported_types, list)
            or sum(
                1
                for exported in exported_types
                if isinstance(exported, dict)
                and exported.get("id") == type_ref.get("id")
            )
            != 1
            or not any(
                all(
                    _encoded(profile.get(member)) == _encoded(formal.get(member))
                    for member in match_members
                )
                for formal in formals
            )
        ):
            return False
    for index, left in enumerate(numeric_profiles):
        for right in numeric_profiles[index + 1 :]:
            if (
                left["source_kind"] == right["source_kind"]
                and all(
                    _encoded(left.get(member)) == _encoded(right.get(member))
                    for member in match_members
                )
                and left["minimum"] <= right["maximum"]
                and right["minimum"] <= left["maximum"]
            ):
                return False
    return True


def _consumer_b_fact_schemas(
    meta: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    schemas = meta.get("fact", {}).get("schemas")
    field_contracts = meta.get("fact", {}).get("field_contracts")
    if not isinstance(schemas, list) or not isinstance(field_contracts, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in schemas:
        if not isinstance(item, dict):
            return {}
        kind = item.get("kind")
        contract_name = item.get("field_contract")
        fields = field_contracts.get(contract_name)
        if (
            not isinstance(kind, str)
            or not isinstance(contract_name, str)
            or not isinstance(fields, dict)
            or not all(isinstance(field, str) and field for field in fields)
            or kind in result
        ):
            return {}
        result[kind] = fields
    return result


def _consumer_b_fact_is_closed(
    fact: Any, meta: dict[str, Any], ldb: dict[str, Any]
) -> bool:
    contract = meta.get("fact")
    schemas = _consumer_b_fact_schemas(meta)
    if not isinstance(contract, dict) or not isinstance(fact, dict):
        return False
    kind = fact.get("kind")
    fields = fact.get("fields")
    return (
        contract.get("closed") is True
        and isinstance(contract.get("required_members"), list)
        and set(fact) == set(contract["required_members"])
        and isinstance(kind, str)
        and kind in schemas
        and isinstance(fields, dict)
        and set(fields) == set(schemas[kind])
        and all(isinstance(field, str) and field for field in fields)
        and all(
            _consumer_b_value_matches(fields[name], schemas[kind][name], ldb)
            for name in fields
        )
    )


def _consumer_b_reason_is_closed(
    reason: Any, meta: dict[str, Any], ldb: dict[str, Any]
) -> bool:
    contract = meta.get("diagnostic_reason")
    if not isinstance(contract, dict) or not isinstance(reason, dict):
        return False
    predicate = reason.get("predicate")
    required_reason = contract.get("required_members")
    optional_reason = contract.get("optional_members", [])
    member_types_reason = contract.get("member_types")
    if (
        contract.get("closed") is not True
        or contract.get("scalar_equality") != "type-and-canonical-value"
        or not isinstance(required_reason, list)
        or not isinstance(optional_reason, list)
        or not set(required_reason) <= set(reason)
        or not set(reason) <= set(required_reason) | set(optional_reason)
        or not isinstance(member_types_reason, dict)
        or set(member_types_reason)
        != (set(required_reason) | set(optional_reason)) - {"predicate"}
        or not all(
            _consumer_b_value_matches(reason[name], member_types_reason[name], ldb)
            for name in set(reason) - {"predicate"}
        )
        or not isinstance(predicate, dict)
        or not isinstance(contract.get("predicate_schemas"), list)
    ):
        return False
    schema = next(
        (
            item
            for item in contract["predicate_schemas"]
            if isinstance(item, dict)
            and item.get("operation") == predicate.get("operation")
        ),
        None,
    )
    if not isinstance(schema, dict):
        return False
    required = schema.get("required_members")
    optional = schema.get("optional_members")
    member_types = schema.get("member_types")
    input_members = schema.get("input_members")
    input_types = schema.get("input_member_types")
    return (
        isinstance(required, list)
        and isinstance(optional, list)
        and isinstance(member_types, dict)
        and isinstance(input_members, list)
        and isinstance(input_types, dict)
        and set(input_types) == set(input_members)
        and set(required) <= set(predicate)
        and set(predicate) <= set(required) | set(optional)
        and set(member_types) == set(required) | set(optional)
        and all(
            _consumer_b_value_matches(predicate[name], member_types[name], ldb)
            for name in predicate
        )
        and _consumer_b_reason_operands_close(predicate, ldb)
    )


def _consumer_b_reason_operands_close(
    predicate: dict[str, Any], ldb: dict[str, Any]
) -> bool:
    operation = predicate.get("operation")
    if operation == "not-member":
        declared, inventory = _consumer_b_exact_path(
            ldb, predicate.get("inventory_path")
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
            _consumer_b_value_matches(value, {"type": "canonical-scalar"}, ldb)
            for value in values
        )
    if operation == "greater-than":
        declared, limit = _consumer_b_exact_path(ldb, predicate.get("limit_path"))
        return declared and _consumer_b_value_matches(
            limit, {"type": "signed-int64"}, ldb
        )
    return operation in {"has-duplicate", "invalid-interval", "not-equal"}


def _consumer_b_scalar_key(value: Any) -> tuple[str, Any]:
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


def _consumer_b_reason_vectors_cover(
    ldb: dict[str, Any],
    reason: dict[str, Any],
    vectors: list[dict[str, Any]],
    meta: dict[str, Any],
) -> bool:
    contract = meta.get("diagnostic_reason")
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
    if {vector.get("matched") for vector in vectors} != {False, True}:
        return False
    if operation == "not-member":
        if coverage.get(operation) != "every-inventory-member-and-one-non-member":
            return False
        declared, inventory = _consumer_b_exact_path(
            ldb, predicate.get("inventory_path")
        )
        if not declared or not isinstance(inventory, list):
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
            _consumer_b_value_matches(value, {"type": "canonical-scalar"}, ldb)
            for value in values
        ):
            return False
        if not all(
            _consumer_b_value_matches(
                vector["input"].get("value"), {"type": "canonical-scalar"}, ldb
            )
            for vector in vectors
        ):
            return False
        nonmatches = {
            _consumer_b_scalar_key(vector.get("input", {}).get("value"))
            for vector in vectors
            if vector.get("matched") is False and isinstance(vector.get("input"), dict)
        }
        return {_consumer_b_scalar_key(value) for value in values} <= nonmatches
    if operation == "has-duplicate":
        return coverage.get(operation) == "both-outcomes" and all(
            _consumer_b_value_matches(
                vector["input"].get("values"), {"type": "scalar-list"}, ldb
            )
            for vector in vectors
        )
    if operation == "greater-than":
        if coverage.get(operation) != "limit-and-successor":
            return False
        declared, limit = _consumer_b_exact_path(ldb, predicate.get("limit_path"))
        if (
            not declared
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit >= 2**63 - 1
        ):
            return False
        if not all(
            _consumer_b_value_matches(
                vector["input"].get("value"), {"type": "signed-int64"}, ldb
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
        return coverage.get(operation) == "both-outcomes" and all(
            _consumer_b_value_matches(
                vector["input"].get(name), {"type": "signed-int64"}, ldb
            )
            for vector in vectors
            for name in ("minimum", "maximum")
        )
    if operation == "not-equal":
        return coverage.get(operation) == "both-outcomes" and all(
            _consumer_b_value_matches(
                vector["input"].get(name), {"type": "canonical-value"}, ldb
            )
            for vector in vectors
            for name in ("actual", "expected")
        )
    return False


def _consumer_b_rule_is_closed(
    rule: Any, meta: dict[str, Any], ldb: dict[str, Any]
) -> bool:
    contract = meta.get("rule")
    term_contract = meta.get("term")
    schemas = _consumer_b_fact_schemas(meta)
    if (
        not isinstance(contract, dict)
        or not isinstance(term_contract, dict)
        or not isinstance(rule, dict)
        or contract.get("closed") is not True
        or not isinstance(contract.get("required_members"), list)
        or set(rule) != set(contract["required_members"])
        or rule.get("phase") not in contract.get("phases", [])
        or not isinstance(rule.get("id"), str)
        or not rule.get("id")
        or not isinstance(rule.get("judgment"), str)
        or not rule.get("judgment")
        or not schemas
    ):
        return False
    premises = rule.get("premises")
    premise_members = contract.get("premise_required_members")
    conclusion = rule.get("conclusion")
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
            or fact_kind not in schemas
            or not isinstance(bindings, dict)
            or not all(
                isinstance(variable, str)
                and variable
                and isinstance(field, str)
                and field in schemas[fact_kind]
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
        or conclusion_kind not in schemas
        or not isinstance(conclusion.get("fields"), dict)
        or set(conclusion["fields"]) != set(schemas[conclusion_kind])
        or not isinstance(term_contract.get("constructors"), list)
    ):
        return False
    constructors = {
        str(item.get("tag")): item
        for item in term_contract["constructors"]
        if isinstance(item, dict)
    }
    for term in conclusion["fields"].values():
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
                _consumer_b_value_matches(term[name], member_types[name], ldb)
                for name in term
            )
        ):
            return False
    return True


def _consumer_b_duplicate_subjects(
    kernel: dict[str, Any], ldb: dict[str, Any]
) -> set[str]:
    law = next(
        item
        for item in kernel["admission"]["laws"]
        if item["id"] == "kernel.identifiers.unique"
    )
    authorities = {"kernel": kernel, "language_bundle": ldb}
    duplicates: set[str] = set()
    for contract in law["arguments"]["collections"]:
        keys = contract["keys"]
        subject = contract["subject"]
        identities: list[tuple[Any, ...]] = []
        for item in _project(authorities, contract["path"]):
            if not isinstance(item, dict) or any(key not in item for key in keys):
                duplicates.add(subject)
                break
            identities.append(tuple(item[key] for key in keys))
        try:
            if len(identities) != len(set(identities)):
                duplicates.add(subject)
        except TypeError:
            duplicates.add(subject)
    return duplicates


def _consumer_b_model_program_vector_is_closed(
    vector: dict[str, Any],
    meta: dict[str, Any],
    ldb: dict[str, Any],
) -> bool:
    contract = meta.get("model_program_vector")
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
        declared, count = _consumer_b_exact_path(ldb, count_path)
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
        for item in ldb.get("diagnostics", [])
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


def _consumer_b_vector_header_is_closed(
    vector: Any, meta: dict[str, Any], ldb: dict[str, Any]
) -> bool:
    if not isinstance(vector, dict):
        return False
    if "rule" in vector:
        invocation = vector.get("input")
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
            and invocation.get("phase") in meta.get("rule", {}).get("phases", [])
            and isinstance(invocation.get("facts"), list)
            and all(
                _consumer_b_fact_is_closed(fact, meta, ldb)
                for fact in invocation["facts"]
            )
            and _consumer_b_fact_is_closed(vector.get("expect"), meta, ldb)
        )
    if "diagnostic" in vector:
        contract = meta.get("diagnostic_reason")
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
                _consumer_b_value_matches(vector[name], member_types[name], ldb)
                for name in member_types
            )
            and isinstance(vector.get("input"), dict)
        )
    if "kind" in vector:
        return _consumer_b_package_evidence_vector_header_is_closed(
            vector, meta.get("package_vector")
        )
    if "category" in vector:
        return _consumer_b_model_program_vector_is_closed(vector, meta, ldb)
    return False


def _consumer_b_json_pointer_authority_is_closed(kernel: dict[str, Any]) -> bool:
    meta = kernel.get("meta_format")
    json_pointer = meta.get("json_pointer") if isinstance(meta, dict) else None
    pointer_schema = (
        json_pointer.get("schema") if isinstance(json_pointer, dict) else None
    )
    try:
        if isinstance(pointer_schema, dict):
            jsonschema.Draft202012Validator.check_schema(pointer_schema)
    except jsonschema.SchemaError:
        return False
    return (
        isinstance(json_pointer, dict)
        and set(json_pointer) == {"encoding", "schema", "target_policy"}
        and json_pointer.get("encoding") == "RFC6901"
        and json_pointer.get("target_policy") == "existing-target"
        and isinstance(pointer_schema, dict)
        and pointer_schema.get("type") == "string"
    )


def _consumer_b_authority_wire_schema_projection_is_closed(
    kernel: dict[str, Any],
) -> bool:
    meta = kernel.get("meta_format")
    contract = (
        meta.get("authority_wire_schema_projection") if isinstance(meta, dict) else None
    )
    return contract == {
        "identity_domains": {
            "language-definition-bundle": "language-definition-bundle-wire-schema-v2",
            "schema-major-kernel": "schema-major-kernel-wire-schema-v2",
        },
        "projection": "complete-authority-const-schema",
    }


def _consumer_b_path(source: dict[str, Any], coordinate: str) -> Any:
    current: Any = source
    for component in coordinate.split("."):
        if not isinstance(current, dict) or component not in current:
            return None
        current = current[component]
    return current


def _consumer_b_active_profile_is_closed(
    profile: dict[str, Any],
    definition_contract: dict[str, Any],
    runtime: dict[str, Any],
) -> bool:
    active = definition_contract.get("active_runtime")
    if not isinstance(active, dict):
        return False
    required = active.get("required_members")
    optional = active.get("optional_members")
    bindings = active.get("runtime_member_bindings")
    rng_bindings = active.get("rng_member_bindings")
    scopes = active.get("budget_scopes")
    bounds_contract = active.get("resource_bounds")
    if (
        set(active)
        != {
            "required_members",
            "optional_members",
            "runtime_member_bindings",
            "rng_member_bindings",
            "budget_scopes",
            "resource_bounds",
        }
        or not isinstance(required, list)
        or not required
        or not all(isinstance(item, str) and item for item in required)
        or len(required) != len(set(required))
        or not isinstance(optional, list)
        or not all(isinstance(item, str) and item for item in optional)
        or len(optional) != len(set(optional))
        or set(required) & set(optional)
        or set(profile) - set(optional) != set(required)
        or not isinstance(bindings, dict)
        or not bindings
        or not set(bindings) <= set(required)
        or not all(isinstance(path, str) and path for path in bindings.values())
        or not isinstance(rng_bindings, dict)
        or not rng_bindings
        or not all(isinstance(path, str) and path for path in rng_bindings.values())
        or set(profile.get("rng", {})) != set(rng_bindings)
        or not isinstance(scopes, dict)
        or not scopes
        or profile.get("budget_scopes") != scopes
        or not isinstance(bounds_contract, dict)
        or set(bounds_contract) != {"members", "value_contract"}
        or bounds_contract.get("value_contract") != "positive-integer"
    ):
        return False
    bound_names = bounds_contract.get("members")
    bounds = profile.get("resource_bounds")
    if (
        not isinstance(bound_names, list)
        or not bound_names
        or not all(isinstance(item, str) and item for item in bound_names)
        or len(bound_names) != len(set(bound_names))
        or not isinstance(bounds, dict)
        or set(bounds) != set(bound_names)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in bounds.values()
        )
    ):
        return False
    return all(
        profile.get(member) == _consumer_b_path(runtime, path)
        for member, path in bindings.items()
    ) and all(
        profile["rng"].get(member) == _consumer_b_path(runtime, path)
        for member, path in rng_bindings.items()
    )


def _consumer_b_component_shape_matches(value: Any, declared_type: Any) -> bool:
    if declared_type == "ordering-list":
        if not isinstance(value, list) or not value:
            return False
        members: list[str] = []
        for item in value:
            if (
                not isinstance(item, dict)
                or set(item)
                not in ({"direction", "member"}, {"direction", "member", "rank"})
                or item.get("direction") not in {"ascending", "descending"}
                or not isinstance(item.get("member"), str)
                or not item["member"]
            ):
                return False
            members.append(item["member"])
            rank = item.get("rank")
            if "rank" in item and (
                not isinstance(rank, list)
                or not rank
                or any(not isinstance(entry, str) or not entry for entry in rank)
                or len(rank) != len(set(rank))
            ):
                return False
        return len(members) == len(set(members))
    checks = {
        "object": lambda candidate: isinstance(candidate, dict),
        "array": lambda candidate: isinstance(candidate, list),
        "string": lambda candidate: isinstance(candidate, str) and bool(candidate),
        "integer": lambda candidate: (
            isinstance(candidate, int) and not isinstance(candidate, bool)
        ),
        "string-list": lambda candidate: (
            isinstance(candidate, list)
            and all(isinstance(item, str) and item for item in candidate)
            and len(candidate) == len(set(candidate))
        ),
    }
    predicate = checks.get(declared_type)
    return predicate(value) if predicate is not None else False


def _consumer_b_component_contract_matches(runtime: dict[str, Any]) -> bool:
    expected_object_roles = {
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
    expected_relation_roles = {
        "lifecycle-states",
        "observation-phase",
        "root-phases",
        "scheduled-child-phase",
        "step-boundaries",
        "step-stops",
    }
    declaration = runtime.get("component_contract")
    if (
        not isinstance(declaration, dict)
        or set(declaration)
        != {"components", "content_identity", "relations", "version"}
        or declaration.get("version") != "runtime-component-meta-contract-v1"
        or declaration.get("content_identity")
        != _SUPPORTED_RUNTIME_COMPONENT_CONTRACT_IDENTITY
        or _safe_identity(declaration["version"], declaration)
        != declaration["content_identity"]
    ):
        return False
    component_specs = declaration.get("components")
    relation_specs = declaration.get("relations")
    if not isinstance(component_specs, dict) or not isinstance(relation_specs, list):
        return False
    resolved_components: dict[str, dict[str, Any]] = {}
    observed_component_roles: set[str] = set()
    for name, spec in component_specs.items():
        candidate = runtime.get(name)
        object_specs = spec.get("objects") if isinstance(spec, dict) else None
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(candidate, dict)
            or not isinstance(spec, dict)
            or set(spec) != {"objects", "role"}
            or not isinstance(object_specs, dict)
            or "" not in object_specs
            or not isinstance(spec.get("role"), str)
            or not spec["role"]
            or spec["role"] in observed_component_roles
        ):
            return False
        component_role = spec["role"]
        observed_component_roles.add(component_role)
        resolved_components[name] = candidate
        observed_object_roles: set[str] = set()
        for coordinate, object_spec in object_specs.items():
            fields = (
                object_spec.get("member_types")
                if isinstance(object_spec, dict)
                else None
            )
            object_role = (
                object_spec.get("role") if isinstance(object_spec, dict) else None
            )
            observed = (
                candidate
                if coordinate == ""
                else _consumer_b_path(candidate, coordinate)
            )
            if (
                not isinstance(coordinate, str)
                or not isinstance(object_spec, dict)
                or set(object_spec) != {"member_types", "role"}
                or not isinstance(object_role, str)
                or not object_role
                or object_role in observed_object_roles
                or not isinstance(fields, dict)
                or not isinstance(observed, dict)
                or set(observed) != set(fields)
                or any(
                    not isinstance(field, str)
                    or not field
                    or not _consumer_b_component_shape_matches(
                        observed[field], declared_type
                    )
                    for field, declared_type in fields.items()
                )
            ):
                return False
            observed_object_roles.add(object_role)
        if observed_object_roles != expected_object_roles.get(component_role):
            return False
    if observed_component_roles != set(expected_object_roles):
        return False
    observed_relation_roles: set[str] = set()
    for relation in relation_specs:
        if not isinstance(relation, dict):
            return False
        component = resolved_components.get(cast(str, relation.get("component")))
        if component is None:
            return False
        relation_role = relation.get("role")
        if (
            not isinstance(relation_role, str)
            or not relation_role
            or relation_role in observed_relation_roles
        ):
            return False
        observed_relation_roles.add(relation_role)
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
            source = _consumer_b_path(
                component, cast(str, relation.get("mapping_path"))
            )
            destination = _consumer_b_path(
                component, cast(str, relation.get("list_path"))
            )
            excluded = relation.get("excluded_keys")
            if (
                not isinstance(source, dict)
                or not isinstance(destination, list)
                or not isinstance(excluded, list)
                or any(not isinstance(item, str) for item in excluded)
                or not set(excluded) <= set(source)
                or not set(source[key] for key in source if key not in excluded)
                <= set(destination)
            ):
                return False
        elif kind == "list-values-in-list":
            if set(relation) != {
                "component",
                "kind",
                "list_path",
                "role",
                "values_path",
            }:
                return False
            source = _consumer_b_path(component, cast(str, relation.get("list_path")))
            values = _consumer_b_path(component, cast(str, relation.get("values_path")))
            if (
                not isinstance(source, list)
                or not isinstance(values, list)
                or not set(source) <= set(values)
            ):
                return False
        elif kind in {
            "mapping-values-in-ranked-ordering",
            "value-in-ranked-ordering",
        }:
            coordinate_member = (
                "mapping_path"
                if kind == "mapping-values-in-ranked-ordering"
                else "value_path"
            )
            if set(relation) != {
                "component",
                "kind",
                "ordering_member",
                "ordering_path",
                "role",
                coordinate_member,
            }:
                return False
            ordering = _consumer_b_path(
                component, cast(str, relation.get("ordering_path"))
            )
            ranked = (
                next(
                    (
                        row.get("rank")
                        for row in ordering
                        if isinstance(row, dict)
                        and row.get("member") == relation.get("ordering_member")
                    ),
                    None,
                )
                if isinstance(ordering, list)
                else None
            )
            source = _consumer_b_path(
                component, cast(str, relation.get(coordinate_member))
            )
            if (
                not isinstance(ranked, list)
                or (
                    kind == "mapping-values-in-ranked-ordering"
                    and (
                        not isinstance(source, dict)
                        or not set(source.values()) <= set(ranked)
                    )
                )
                or (kind == "value-in-ranked-ordering" and source not in ranked)
            ):
                return False
        else:
            return False
    return observed_relation_roles == expected_relation_roles


def _consumer_b_runtime_authority_is_closed(
    kernel: dict[str, Any], ldb: dict[str, Any]
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
        or profile_identity.get("domain") != "runtime-profile-definition-v1"
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
        or not isinstance(runtime.get("scheduler"), dict)
        or not isinstance(runtime.get("runtime_configuration"), dict)
        or not isinstance(runtime.get("transition"), dict)
        or not isinstance(runtime.get("step"), dict)
        or not _consumer_b_component_contract_matches(runtime)
    ):
        return False
    nodes = runtime.get("nodes")
    fixed_value_contracts = runtime.get("fixed_value_contracts")
    if not isinstance(nodes, list) or fixed_value_contracts != {
        "kernel-boolean": {
            "type": {"package": "kernel", "version": "2.0.0", "id": "Boolean"},
            "representation": "Bool",
            "kind": "boolean",
            "unit": "1",
            "domain": {"kind": "boolean"},
            "numeric_policy": "exact-bool",
        },
        "kernel-unit": {
            "type": {"package": "kernel", "version": "2.0.0", "id": "Unit"},
            "representation": "Unit",
            "kind": "unit",
            "unit": "1",
            "domain": {"kind": "unit"},
            "numeric_policy": "exact-unit",
        },
        "kernel-event-reference": {
            "type": {
                "package": "kernel",
                "version": "2.0.0",
                "id": "EventReference",
            },
            "representation": "EventRef",
            "kind": "event-reference",
            "unit": "1",
            "domain": {"kind": "runtime-event"},
            "numeric_policy": "exact-reference",
        },
    }:
        return False
    assert isinstance(fixed_value_contracts, dict)
    families = {
        "expression": "expression_nodes",
        "effect": "effect_nodes",
        "control": "control_nodes",
    }
    for family, member in families.items():
        if runtime.get(member) != [
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and node.get("family") == family
        ]:
            return False
    if len({node.get("id") for node in nodes if isinstance(node, dict)}) != len(
        nodes
    ) or any(
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
        or node.get("family") not in families
        or not isinstance(node.get("required_members"), list)
        or not node["required_members"]
        or node["required_members"][0] != "node"
        or node.get("resource_charge") != {"counter": "event-steps", "amount": 1}
        or not isinstance(node.get("operand_constraints"), list)
        or not isinstance(node.get("semantics"), dict)
        or not isinstance(node["semantics"].get("operator"), str)
        or not isinstance(node.get("result"), dict)
        or (
            (
                node["result"].get("kind") in {"local", "draw"}
                and (
                    set(node["result"]) != {"kind", "typing"}
                    or not isinstance(node["result"].get("typing"), dict)
                    or (
                        node["result"]["typing"].get("kind") == "fixed"
                        and node["result"]["typing"].get("contract")
                        not in fixed_value_contracts
                    )
                    or (
                        node["result"]["typing"].get("kind")
                        in {
                            "declared-result",
                            "same-as-references",
                            "literal-profile",
                        }
                        and (
                            not isinstance(
                                node["result"]["typing"].get("members"), list
                            )
                            or not node["result"]["typing"]["members"]
                        )
                    )
                    or node["result"]["typing"].get("kind")
                    not in {
                        "declared-result",
                        "fixed",
                        "same-as-references",
                        "literal-profile",
                    }
                )
            )
            or (
                node["result"].get("kind") not in {"local", "draw"}
                and set(node["result"]) != {"kind"}
            )
        )
        for node in nodes
    ):
        return False
    for node in cast(list[dict[str, Any]], nodes):
        for constraint in node["operand_constraints"]:
            if not isinstance(constraint, dict):
                return False
            kind = constraint.get("kind")
            members = constraint.get("members")
            if (
                kind
                not in {
                    "fixed-value-contract",
                    "runtime-numeric",
                    "same-value-contract",
                    "writable-port",
                }
                or not isinstance(members, list)
                or not members
                or len(members) != len(set(members))
                or any(
                    not isinstance(member, str)
                    or member not in node["required_members"]
                    or member in {"node", "target"}
                    for member in members
                )
                or (
                    kind == "fixed-value-contract"
                    and (
                        set(constraint) != {"contract", "kind", "members"}
                        or constraint.get("contract") not in fixed_value_contracts
                    )
                )
                or (
                    kind != "fixed-value-contract"
                    and set(constraint) != {"kind", "members"}
                )
            ):
                return False
    nodes_by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    cancel_semantics = nodes_by_id.get("cancel", {}).get("semantics")
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
                    for node in nodes_by_id.values()
                )
            )
            or (
                variant.get("kind") == "port"
                and variant.get("value_contract") not in fixed_value_contracts
            )
            for variant in cancel_variants
        )
        or cancel_target["instruction_member"]
        not in nodes_by_id["cancel"]["required_members"]
    ):
        return False
    rng = runtime.get("named_rng")
    if (
        runtime.get("numeric")
        != {
            "compatible_value_numeric_policies": ["exact-int64"],
            "id": "signed-int64-v1",
            "minimum": -(1 << 63),
            "maximum": (1 << 63) - 1,
            "overflow": "runtime-refusal",
            "overflow_signal": "numeric-overflow",
        }
        or not isinstance(rng, dict)
        or rng.get("algorithm") != "splitmix64-v1"
        or rng.get("candidate_encoding")
        != {
            "alphabet": "0123456789abcdef",
            "case": "lowercase",
            "radix": 16,
            "width_bits": 64,
            "zero_pad": True,
        }
        or rng.get("interval_sampling", {}).get("bias_policy")
        != "accepted-modulo-bias-v1"
        or runtime.get("outcome_contract")
        != {
            "kinds": ["success", "gameplay-alternative"],
            "state_policies": ["commit", "rollback"],
            "operation_members": ["outcomes", "default_outcome"],
        }
    ):
        return False
    invocation_contract = runtime.get("invocation_contract")
    if (
        not isinstance(invocation_contract, dict)
        or invocation_contract.get("closed") is not True
        or invocation_contract.get("version") != "resolved-operation-binding-v1"
        or invocation_contract.get("scope") != "lexical-call-frame"
        or invocation_contract.get("ambient_capture") != "forbidden"
        or invocation_contract.get("argument_evaluation_order")
        != "formal-port-declaration-order"
        or invocation_contract.get("outcome_mapping") != "exactly-once-and-exhaustive"
        or invocation_contract.get("resource_charge")
        != "invoke-plus-transitive-callee-steps"
        or set(invocation_contract.get("operand_kinds", []))
        != {"port", "local", "literal", "expression"}
        or set(invocation_contract.get("result_binding_kinds", []))
        != {"local", "operation-result", "discard"}
        or invocation_contract.get("result_source_shapes")
        != {
            "local": ["kind", "name"],
            "operation-result": ["kind", "site"],
            "port": ["kind", "name"],
            "unit": ["kind"],
        }
        or invocation_contract.get("result_producer_cardinality")
        != "exactly-one-compatible-producer-on-every-success-path"
        or set(invocation_contract.get("outcome_actions", []))
        != {"continue", "propagate"}
    ):
        return False
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
        or set(node_vectors) != {node["id"] for node in nodes}
        or set(invocation_vectors)
        != {
            "runtime.invocation.result-contract-compatible",
            "runtime.invocation.result-contract-incompatible",
        }
    ):
        return False
    for node in nodes:
        expected = {
            "charge": 1,
            "operand_constraints": node["operand_constraints"],
            "operator": node["semantics"]["operator"],
            "result_kind": node["result"]["kind"],
        }
        if "typing" in node["result"]:
            expected["result_typing"] = node["result"]["typing"]
        vector = node_vectors[node["id"]]
        if (
            vector.get("id") != f"runtime.node.{node['id']}"
            or vector.get("input") != {"contract-probe": node["required_members"]}
            or vector.get("expect") != expected
        ):
            return False
    for vector in invocation_vectors.values():
        inp = vector.get("input")
        expect = vector.get("expect")
        if not isinstance(inp, dict) or not isinstance(expect, dict):
            return False
        producer_contract = fixed_value_contracts.get(inp.get("producer_contract"))
        result_contract = fixed_value_contracts.get(inp.get("result_contract"))
        if (
            not isinstance(producer_contract, dict)
            or not isinstance(result_contract, dict)
            or expect.get("admitted")
            is not (_encoded(producer_contract) == _encoded(result_contract))
        ):
            return False
    for profile in ldb.get("language", {}).get("runtime_profiles", []):
        if profile.get("evaluation") == runtime.get("version") and not (
            isinstance(profile, dict)
            and _consumer_b_active_profile_is_closed(
                profile,
                profile_identity,
                runtime,
            )
        ):
            return False
    kinds = set(runtime["outcome_contract"]["kinds"])
    policies = set(runtime["outcome_contract"]["state_policies"])
    operations = ldb.get("language", {}).get("operations", [])
    if not isinstance(operations, list):
        return False
    operations_by_id = {
        operation.get("id"): operation
        for operation in operations
        if isinstance(operation, dict) and isinstance(operation.get("id"), str)
    }

    def referenced_outcomes(
        operation: dict[str, Any], stack: set[str]
    ) -> set[str] | None:
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or operation_id in stack:
            return None
        body = operation.get("body")
        if not isinstance(body, list):
            return None
        nested_stack = {*stack, operation_id}
        referenced: set[str] = set()
        produced_locals: dict[str, str] = {}
        formal_ports = {
            port.get("id"): port
            for port in operation.get("inputs", [])
            if isinstance(port, dict) and isinstance(port.get("id"), str)
        }
        for instruction in body:
            if not isinstance(instruction, dict):
                return None
            node = nodes_by_id.get(instruction.get("node"))
            if not isinstance(node, dict) or set(instruction) != set(
                node["required_members"]
            ):
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
                        and produced_locals.get(target_value)
                        != target_variant["producer_result_kind"]
                    )
                    or (
                        target_variant["kind"] == "port"
                        and (
                            target_value not in formal_ports
                            or formal_ports[target_value].get("type")
                            != fixed_value_contracts[
                                target_variant["value_contract"]
                            ].get("type")
                            or any(
                                formal_ports[target_value].get(member)
                                != fixed_value_contracts[
                                    target_variant["value_contract"]
                                ].get(member)
                                for member in (
                                    "representation",
                                    "kind",
                                    "unit",
                                    "domain",
                                    "numeric_policy",
                                )
                            )
                        )
                    )
                ):
                    return None
            outcome = instruction.get("outcome")
            if isinstance(outcome, str):
                referenced.add(outcome)
            if node["semantics"]["operator"] == "invoke-operation":
                operation_ref = instruction.get("operation")
                if not isinstance(operation_ref, dict) or set(operation_ref) != {
                    "package",
                    "version",
                    "id",
                }:
                    return None
                invoked = operations_by_id.get(operation_ref["id"])
                if not isinstance(invoked, dict):
                    return None
                invoked_formal_ports = [
                    row.get("id")
                    for row in invoked.get("inputs", [])
                    if isinstance(row, dict)
                ]
                arguments = instruction.get("arguments")
                if (
                    not isinstance(arguments, list)
                    or [row.get("port") for row in arguments] != invoked_formal_ports
                    or any(
                        not isinstance(row, dict)
                        or set(row) != {"port", "operand"}
                        or not isinstance(row["operand"], dict)
                        or row["operand"].get("kind")
                        not in set(invocation_contract["operand_kinds"])
                        for row in arguments
                    )
                ):
                    return None
                child_outcomes = {
                    row.get("id")
                    for row in invoked.get("outcomes", [])
                    if isinstance(row, dict)
                }
                mappings = instruction.get("outcomes")
                if (
                    not isinstance(mappings, list)
                    or {row.get("outcome") for row in mappings} != child_outcomes
                    or len(mappings) != len(child_outcomes)
                ):
                    return None
                for mapping in mappings:
                    action = mapping.get("action")
                    if not isinstance(action, dict) or action.get("kind") not in set(
                        invocation_contract["outcome_actions"]
                    ):
                        return None
                    if action["kind"] == "propagate":
                        propagated = action.get("outcome")
                        if not isinstance(propagated, str):
                            return None
                        referenced.add(propagated)
                result_binding = instruction.get("result")
                if (
                    not isinstance(result_binding, dict)
                    or result_binding.get("kind")
                    not in set(invocation_contract["result_binding_kinds"])
                    or (
                        result_binding["kind"] == "discard"
                        and invoked.get("result", {}).get("discardable") is not True
                    )
                ):
                    return None
                nested = referenced_outcomes(invoked, nested_stack)
                if nested is None:
                    return None
            binding = instruction.get("result")
            if isinstance(binding, dict) and binding.get("kind") == "local":
                name = binding.get("name")
                if not isinstance(name, str) or not name or name in produced_locals:
                    return None
                produced_locals[name] = node["result"]["kind"]
        return referenced

    for operation in operations:
        if not isinstance(operation, dict):
            return False
        operation_kind = operation.get("operation_kind")
        if operation_kind not in {"event-program", "event-fragment"}:
            continue
        result = operation.get("result")
        source = result.get("source") if isinstance(result, dict) else None
        source_kind = source.get("kind") if isinstance(source, dict) else None
        source_members = invocation_contract["result_source_shapes"].get(source_kind)
        source_value = (
            source.get("site")
            if source_kind == "operation-result" and isinstance(source, dict)
            else source.get("name")
            if source_kind in {"local", "port"} and isinstance(source, dict)
            else None
        )
        if (
            not isinstance(source, dict)
            or not isinstance(source_members, list)
            or set(source) != set(source_members)
            or (
                source_kind in {"local", "port", "operation-result"}
                and (not isinstance(source_value, str) or not source_value)
            )
            or source_kind not in {"local", "port", "operation-result", "unit"}
        ):
            return False
        referenced = referenced_outcomes(operation, set())
        if referenced is None:
            return False
        outcomes = operation.get("outcomes")
        if not isinstance(outcomes, list) or any(
            set(item) != {"id", "kind", "state_policy"}
            or item["kind"] not in kinds
            or item["state_policy"] not in policies
            for item in outcomes
        ):
            return False
        declared = {item["id"]: item for item in outcomes}
        default = operation.get("default_outcome")
        if (
            default not in declared
            or declared[default]["kind"] != "success"
            or referenced != set(declared) - {default}
        ):
            return False
    return True


def _consumer_b_operation_composition_subjects(
    kernel: dict[str, Any],
    ldb: dict[str, Any],
) -> tuple[str, ...]:
    """Independently close exact nested calls without using production admission."""
    language = ldb.get("language")
    if not isinstance(language, dict):
        return ()
    packages = language.get("packages")
    operations = language.get("operations")
    if not isinstance(packages, list) or not isinstance(operations, list):
        return ()
    literal_profiles = language.get("literal_typing_profiles")
    literal_contract = kernel.get("meta_format", {}).get("literal_typing")
    invocation_contract = (
        kernel.get("meta_format", {})
        .get("runtime_program", {})
        .get("invocation_contract")
    )
    runtime_program = kernel.get("meta_format", {}).get("runtime_program")
    runtime_nodes = (
        runtime_program.get("nodes") if isinstance(runtime_program, dict) else None
    )
    fixed_value_contracts = (
        runtime_program.get("fixed_value_contracts")
        if isinstance(runtime_program, dict)
        else None
    )
    runtime_numeric_policies = (
        runtime_program.get("numeric", {}).get("compatible_value_numeric_policies")
        if isinstance(runtime_program, dict)
        and isinstance(runtime_program.get("numeric"), dict)
        else None
    )
    result_source_shapes = (
        invocation_contract.get("result_source_shapes")
        if isinstance(invocation_contract, dict)
        else None
    )
    if (
        not isinstance(literal_contract, dict)
        or literal_contract.get("selection") != "unique-formal-match"
        or not isinstance(literal_profiles, list)
        or not isinstance(result_source_shapes, dict)
        or not isinstance(runtime_nodes, list)
        or not isinstance(fixed_value_contracts, dict)
        or not isinstance(runtime_numeric_policies, list)
        or not runtime_numeric_policies
        or not all(isinstance(policy, str) for policy in runtime_numeric_policies)
    ):
        return ("language.literal-typing-profiles",)
    node_definitions = {
        node["id"]: node
        for node in runtime_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    if len(node_definitions) != len(runtime_nodes):
        return ("kernel.meta-format.runtime-program.nodes",)
    constructors = {
        constructor["id"]: constructor
        for constructor in cast(list[dict[str, Any]], language.get("constructors", []))
        if isinstance(constructor, dict) and isinstance(constructor.get("id"), str)
    }
    structured_operations = [
        operation
        for operation in cast(
            list[dict[str, Any]], language.get("structured_operations", [])
        )
        if isinstance(operation, dict)
    ]
    typed_profiles = [
        profile
        for profile in literal_profiles
        if isinstance(profile, dict)
        and profile.get("source_kind") == "typed-envelope"
        and profile.get("value_kind") == "nominal-structured"
        and isinstance(profile.get("admission"), dict)
    ]
    if len(typed_profiles) != 1:
        return ("language.literal-typing-profiles",)
    reasons_by_signal: dict[str, list[str]] = {}
    for reason in cast(list[dict[str, Any]], language.get("reasons", [])):
        signal = reason.get("signal") if isinstance(reason, dict) else None
        reason_id = reason.get("id") if isinstance(reason, dict) else None
        if isinstance(signal, str) and isinstance(reason_id, str):
            reasons_by_signal.setdefault(signal, []).append(reason_id)
    nominal_type_definitions = {
        (
            cast(str, definition["package"]),
            cast(str, definition["version"]),
            cast(str, definition["id"]),
        ): definition
        for definition in cast(list[dict[str, Any]], language.get("nominal_types", []))
        if isinstance(definition, dict)
        and all(
            isinstance(definition.get(member), str)
            for member in ("package", "version", "id")
        )
    }
    owners: dict[str, tuple[str, str]] = {}
    for package in packages:
        if not isinstance(package, dict):
            continue
        package_id = package.get("id")
        package_version = package.get("version")
        if not isinstance(package_id, str) or not isinstance(package_version, str):
            continue
        exports = package.get("exports")
        exported = exports.get("operations") if isinstance(exports, dict) else None
        if not isinstance(exported, list):
            continue
        for operation_id in exported:
            if isinstance(operation_id, str):
                owners[operation_id] = (package_id, package_version)
    by_coordinate = {
        (*owners[operation["id"]], operation["id"]): operation
        for operation in operations
        if isinstance(operation, dict)
        and isinstance(operation.get("id"), str)
        and operation["id"] in owners
    }
    found: set[str] = set()
    closed: dict[tuple[str, str, str], tuple[set[str], set[str], int]] = {}
    guard_body_coordinates: set[tuple[str, str, str]] = set()

    def subject(
        coordinate: tuple[str, str, str],
        site: str | None,
        member: str,
    ) -> str:
        package, version, operation_id = coordinate
        base = f"language.operations.{package}@{version}.{operation_id}"
        return (
            f"{base}.body.{site}.{member}" if site is not None else f"{base}.{member}"
        )

    def value_contract_matches(actual: dict[str, Any], formal: dict[str, Any]) -> bool:
        def canonically_equal(left: Any, right: Any) -> bool:
            try:
                return _encoded(left) == _encoded(right)
            except (TypeError, ValueError, UnicodeEncodeError):
                return False

        if actual.get("type") != formal.get("type"):
            return False
        if "value_kind" in actual or "value_kind" in formal:
            return actual.get("value_kind") == formal.get("value_kind")
        return all(
            canonically_equal(actual.get(member), formal.get(member))
            for member in (
                "representation",
                "kind",
                "unit",
                "domain",
                "numeric_policy",
            )
        )

    def type_key(type_expression: Any) -> tuple[str, str, str] | None:
        if not isinstance(type_expression, dict):
            return None
        contract = typed_profiles[0]["admission"].get("nominal_type_reference")
        if not isinstance(contract, dict):
            return None
        coordinate_members = contract.get("coordinate_members")
        kind_member = contract.get("optional_kind_member")
        kind_value = contract.get("optional_kind_value")
        if (
            not isinstance(coordinate_members, list)
            or coordinate_members != ["package", "version", "id"]
            or not isinstance(kind_member, str)
            or not isinstance(kind_value, str)
        ):
            return None
        expected = set(coordinate_members)
        if kind_member in type_expression:
            expected.add(kind_member)
            if type_expression[kind_member] != kind_value:
                return None
        values = tuple(type_expression.get(member) for member in coordinate_members)
        return (
            cast(tuple[str, str, str], values)
            if set(type_expression) == expected
            and all(isinstance(value, str) and value for value in values)
            else None
        )

    def structural_contract(
        type_expression: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        constructor = None
        coordinate = type_key(type_expression)
        if coordinate is not None:
            nominal = nominal_type_definitions.get(coordinate)
            constructor = (
                constructors.get(nominal.get("constructor"))
                if isinstance(nominal, dict)
                else None
            )
            if (
                not isinstance(nominal, dict)
                or constructor is None
                or "definition" not in nominal
            ):
                return None
            type_expression = nominal["definition"]
        if not isinstance(type_expression, dict):
            return None
        if constructor is None:
            matches = [
                candidate
                for candidate in constructors.values()
                if candidate.get("value_rule", {}).get("definition_kind")
                == type_expression.get("kind")
            ]
            if len(matches) != 1:
                return None
            constructor = matches[0]
        rule = constructor.get("value_rule")
        return (type_expression, constructor, rule) if isinstance(rule, dict) else None

    def operation_law(
        constructor: dict[str, Any], operator: str
    ) -> dict[str, Any] | None:
        matches = [
            operation
            for operation in structured_operations
            if operation.get("owner_constructor") == constructor.get("id")
            and isinstance(operation.get("law"), dict)
            and operation["law"].get("operator") == operator
        ]
        nodes = [
            node
            for node in node_definitions.values()
            if node.get("semantics", {}).get("operator") == operator
        ]
        charge = (
            nodes[0].get("resource_charge", {}).get("amount")
            if len(nodes) == 1
            else None
        )
        bound = (
            matches[0].get("resource_bounds", {}).get("max_steps")
            if len(matches) == 1
            else None
        )
        if (
            len(matches) != 1
            or len(nodes) != 1
            or not isinstance(charge, int)
            or isinstance(charge, bool)
            or not isinstance(bound, int)
            or isinstance(bound, bool)
            or charge > bound
        ):
            return None
        return cast(dict[str, Any], matches[0]["law"])

    def structured_contract(type_expression: Any) -> dict[str, Any] | None:
        if not isinstance(type_expression, dict):
            return None
        coordinate = type_key(type_expression)
        if coordinate is not None:
            package, version, type_id = coordinate
            exact_type = {"id": type_id, "package": package, "version": version}
            scalar_profiles = [
                profile
                for profile in literal_profiles
                if isinstance(profile, dict)
                and profile.get("source_kind") == "integer"
                and profile.get("type") == exact_type
            ]
            if len(scalar_profiles) == 1:
                profile = scalar_profiles[0]
                return {
                    member: profile[member]
                    for member in (
                        "domain",
                        "kind",
                        "numeric_policy",
                        "representation",
                        "unit",
                    )
                } | {
                    "type": exact_type,
                }
            return {"type": exact_type, "value_kind": "nominal-structured"}
        if type_expression.get("kind") in {"list", "ref"}:
            return {"type": type_expression, "value_kind": "nominal-structured"}
        return None

    def lookup_contract(
        value_contract: dict[str, Any],
        key: Any,
        key_candidates: tuple[dict[str, Any], ...] | None,
    ) -> tuple[dict[str, Any], str] | None:
        type_expression = value_contract.get("type")
        resolved = structural_contract(type_expression)
        if resolved is None:
            return None
        type_expression, constructor, rule = resolved
        law = operation_law(constructor, "bounded-lookup")
        if not isinstance(law, dict):
            return None
        refusal_signal = law.get("refusal_signal")
        if not isinstance(refusal_signal, str) or not refusal_signal:
            return None
        if (
            law.get("selector") == "static-field"
            and law.get("result_projection") == "record-field-type"
            and rule.get("operator") == "closed-record"
            and isinstance(key, str)
        ):
            fields_member = rule.get("fields_member")
            name_member = rule.get("field_name_member")
            type_member = rule.get("field_type_member")
            fields = (
                type_expression.get(fields_member)
                if isinstance(fields_member, str)
                else None
            )
            matches = (
                [
                    field
                    for field in fields
                    if isinstance(field, dict) and field.get(name_member) == key
                ]
                if isinstance(fields, list)
                else []
            )
            result = (
                structured_contract(matches[0].get(type_member))
                if len(matches) == 1 and isinstance(type_member, str)
                else None
            )
            return (result, refusal_signal) if result is not None else None
        if (
            law.get("selector") == "local-index"
            and law.get("result_projection") == "list-element-type"
            and rule.get("operator") == "bounded-list"
        ):
            integer_profiles = [
                profile
                for profile in literal_profiles
                if isinstance(profile, dict)
                and profile.get("source_kind") == "integer"
                and profile.get("numeric_policy") in runtime_numeric_policies
            ]
            if not key_candidates or any(
                not any(
                    value_contract_matches(candidate, profile)
                    for profile in integer_profiles
                )
                for candidate in key_candidates
            ):
                return None
            element_member = rule.get("element_member")
            result = (
                structured_contract(type_expression.get(element_member))
                if isinstance(element_member, str)
                else None
            )
            return (result, refusal_signal) if result is not None else None
        return None

    def equal_contract(value_contract: dict[str, Any]) -> str | None:
        resolved = structural_contract(value_contract.get("type"))
        if resolved is None:
            return None
        _definition, constructor, _rule = resolved
        law = operation_law(constructor, "canonical-equal")
        result_contract = law.get("result_contract") if isinstance(law, dict) else None
        return result_contract if isinstance(result_contract, str) else None

    def empty_contract(value_contract: dict[str, Any]) -> str | None:
        resolved = structural_contract(value_contract.get("type"))
        if resolved is None:
            return None
        _definition, constructor, rule = resolved
        law = operation_law(constructor, "collection-is-empty")
        result_contract = law.get("result_contract") if isinstance(law, dict) else None
        return (
            result_contract
            if rule.get("operator") == "bounded-list"
            and isinstance(result_contract, str)
            else None
        )

    def aliases_are_admitted(
        operation: dict[str, Any],
        aliases: dict[str, list[tuple[str, str]]],
    ) -> bool:
        policy = operation.get("alias_policy")
        if not isinstance(policy, dict):
            return False
        groups = policy.get("writable_groups")
        if not isinstance(groups, list):
            return False
        writable = {
            frozenset(group.get("ports", []))
            for group in groups
            if isinstance(group, dict)
            and group.get("semantics")
            in {"operation-body-order", "commutative-reducer"}
        }
        for uses in aliases.values():
            if len(uses) < 2 or all(access == "read" for _port, access in uses):
                continue
            if frozenset(port for port, _access in uses) not in writable:
                return False
        return True

    def literal_matches(value: Any, formal: dict[str, Any]) -> bool:
        matches = [
            profile
            for profile in literal_contracts(value)
            if value_contract_matches(profile, formal)
        ]
        return len(matches) == 1

    def literal_contracts(value: Any) -> tuple[dict[str, Any], ...]:
        if isinstance(value, dict) and set(value) == {"type", "value"}:
            type_expression = value["type"]
            typed_profiles = [
                profile
                for profile in literal_profiles
                if isinstance(profile, dict)
                and profile.get("source_kind") == "typed-envelope"
                and profile.get("value_kind") == "nominal-structured"
            ]
            if (
                len(typed_profiles) == 1
                and (coordinate := type_key(type_expression)) is not None
            ):
                package, version, type_id = coordinate
                return (
                    {
                        "type": {
                            "id": type_id,
                            "package": package,
                            "version": version,
                        },
                        "value_kind": "nominal-structured",
                    },
                )
            return ()
        if type(value) is not int:
            return ()
        return tuple(
            profile
            for profile in literal_profiles
            if isinstance(profile, dict)
            and profile.get("source_kind") == "integer"
            and type(profile.get("minimum")) is int
            and type(profile.get("maximum")) is int
            and profile["minimum"] <= value <= profile["maximum"]
        )

    def close(
        coordinate: tuple[str, str, str],
        stack: tuple[tuple[str, str, str], ...],
    ) -> tuple[set[str], set[str], int] | None:
        if coordinate in closed:
            return closed[coordinate]
        operation = by_coordinate.get(coordinate)
        if not isinstance(operation, dict):
            return None
        result = operation.get("result")
        source = result.get("source") if isinstance(result, dict) else None
        source_kind = source.get("kind") if isinstance(source, dict) else None
        source_members = (
            result_source_shapes.get(source_kind)
            if isinstance(source_kind, str)
            else None
        )
        source_value = (
            source.get("site")
            if source_kind == "operation-result" and isinstance(source, dict)
            else source.get("name")
            if source_kind in {"local", "port"} and isinstance(source, dict)
            else None
        )
        if (
            not isinstance(source, dict)
            or not isinstance(source_members, list)
            or set(source) != set(source_members)
            or (
                source_kind in {"local", "port", "operation-result"}
                and (not isinstance(source_value, str) or not source_value)
            )
            or source_kind not in {"local", "port", "operation-result", "unit"}
        ):
            found.add(subject(coordinate, None, "result.source"))
            return None
        source_site = (
            cast(str, source["site"]) if source_kind == "operation-result" else None
        )
        parent_ports = {
            port["id"]: port
            for port in operation.get("inputs", [])
            if isinstance(port, dict) and isinstance(port.get("id"), str)
        }
        parent_outcome_definitions = {
            row["id"]: row
            for row in operation.get("outcomes", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        parent_outcomes = set(parent_outcome_definitions)
        parent_successes = {
            outcome_id
            for outcome_id, definition in parent_outcome_definitions.items()
            if definition.get("kind") == "success"
        }
        locals_: dict[str, tuple[dict[str, Any], ...]] = {}
        scope: dict[str, tuple[dict[str, Any], ...]] = {
            name: (contract,) for name, contract in parent_ports.items()
        }
        local_producers: dict[str, int] = {}
        effects = set(cast(list[str], operation.get("effects", [])))
        refusals = set(cast(list[str], operation.get("refusals", [])))
        body = operation.get("body")
        if not isinstance(body, list):
            return None
        charge = len(body)
        operation_result_sites: set[str] = set()
        source_producer_reached = False

        def shared_contracts(
            groups: list[tuple[dict[str, Any], ...]],
        ) -> tuple[dict[str, Any], ...]:
            if not groups:
                return ()
            return tuple(
                candidate
                for candidate in groups[0]
                if all(
                    any(value_contract_matches(candidate, other) for other in group)
                    for group in groups[1:]
                )
            )

        def references(
            instruction: dict[str, Any],
            members: list[str],
        ) -> list[tuple[dict[str, Any], ...]] | None:
            resolved: list[tuple[dict[str, Any], ...]] = []
            for member in members:
                name = instruction.get(member)
                candidates = scope.get(name) if isinstance(name, str) else None
                if not candidates:
                    return None
                resolved.append(candidates)
            return resolved

        def narrow_reference(
            instruction: dict[str, Any],
            member: str,
            candidates: tuple[dict[str, Any], ...],
        ) -> None:
            name = cast(str, instruction[member])
            scope[name] = candidates
            if name in locals_:
                locals_[name] = candidates

        for instruction_index, instruction in enumerate(body):
            if not isinstance(instruction, dict):
                return None
            node = node_definitions.get(instruction.get("node"))
            if not isinstance(node, dict) or set(instruction) != set(
                node["required_members"]
            ):
                found.add(subject(coordinate, str(instruction_index), "members"))
                return None
            target = instruction.get("target")
            if instruction.get("node") != "invoke":
                if (
                    source_kind in {"local", "operation-result"}
                    and not source_producer_reached
                    and instruction.get("outcome") in parent_successes
                ):
                    found.add(subject(coordinate, None, "result.source"))
                    return None
                for constraint in node.get("operand_constraints", []):
                    if not isinstance(constraint, dict):
                        return None
                    members = constraint.get("members")
                    if not isinstance(members, list):
                        return None
                    resolved = references(instruction, members)
                    if resolved is None:
                        found.add(subject(coordinate, str(instruction_index), "typing"))
                        return None
                    kind = constraint.get("kind")
                    if kind == "same-value-contract":
                        shared = shared_contracts(resolved)
                        if (
                            node.get("semantics", {}).get("operator")
                            == "canonical-equal"
                        ):
                            expected_result_contract = (
                                node.get("result", {}).get("typing", {}).get("contract")
                            )
                            shared = tuple(
                                candidate
                                for candidate in shared
                                if candidate.get("value_kind")
                                not in {"nominal-structured", "structured"}
                                or equal_contract(candidate) == expected_result_contract
                            )
                        if not shared:
                            found.add(
                                subject(coordinate, str(instruction_index), "typing")
                            )
                            return None
                        for member, candidates in zip(
                            members,
                            resolved,
                            strict=True,
                        ):
                            narrow_reference(
                                instruction,
                                member,
                                tuple(
                                    candidate
                                    for candidate in candidates
                                    if any(
                                        value_contract_matches(candidate, common)
                                        for common in shared
                                    )
                                ),
                            )
                    if kind == "fixed-value-contract":
                        expected = fixed_value_contracts.get(constraint.get("contract"))
                        if not isinstance(expected, dict):
                            return None
                        for member, candidates in zip(
                            members,
                            resolved,
                            strict=True,
                        ):
                            narrowed = tuple(
                                candidate
                                for candidate in candidates
                                if value_contract_matches(candidate, expected)
                            )
                            if not narrowed:
                                found.add(
                                    subject(
                                        coordinate,
                                        str(instruction_index),
                                        "typing",
                                    )
                                )
                                return None
                            narrow_reference(
                                instruction,
                                member,
                                narrowed,
                            )
                    if kind == "runtime-numeric":
                        for member, candidates in zip(
                            members,
                            resolved,
                            strict=True,
                        ):
                            narrowed = tuple(
                                candidate
                                for candidate in candidates
                                if candidate.get("numeric_policy")
                                in runtime_numeric_policies
                            )
                            if not narrowed:
                                found.add(
                                    subject(
                                        coordinate,
                                        str(instruction_index),
                                        "typing",
                                    )
                                )
                                return None
                            narrow_reference(
                                instruction,
                                member,
                                narrowed,
                            )
                    if kind == "writable-port" and any(
                        not isinstance(instruction.get(member), str)
                        or instruction[member] not in parent_ports
                        or parent_ports[instruction[member]].get("access")
                        not in {"read-write", "write"}
                        for member in members
                    ):
                        found.add(subject(coordinate, str(instruction_index), "typing"))
                        return None
                operator = node.get("semantics", {}).get("operator")
                if operator == "typed-require":
                    refusal_reference = node.get("semantics", {}).get(
                        "refusal_reference"
                    )
                    reason_member = (
                        refusal_reference.get("instruction_member")
                        if isinstance(refusal_reference, dict)
                        else None
                    )
                    if (
                        not isinstance(instruction.get("expected"), bool)
                        or reason_member not in node.get("required_members", [])
                        or refusal_reference.get("source")
                        != "enclosing-operation.refusals"
                        or instruction.get(reason_member) not in refusals
                    ):
                        found.add(
                            subject(
                                coordinate,
                                str(instruction_index),
                                "refusals",
                            )
                        )
                        return None
                if operator == "guarded-outcome-block":
                    guard_body = instruction.get("body")
                    guarded_outcome = instruction.get("outcome")
                    if (
                        coordinate in guard_body_coordinates
                        or not isinstance(guard_body, list)
                        or not all(isinstance(row, dict) for row in guard_body)
                        or any(row.get("node") == "guard-block" for row in guard_body)
                        or any(
                            isinstance(body_node, dict)
                            and body_node.get("result", {}).get("kind") == "outcome"
                            for row in guard_body
                            if (body_node := node_definitions.get(row.get("node")))
                        )
                        or guarded_outcome not in parent_outcomes
                    ):
                        found.add(subject(coordinate, str(instruction_index), "body"))
                        return None
                    guard_coordinate = (
                        coordinate[0],
                        coordinate[1],
                        f"{coordinate[2]}#guard-{instruction_index}",
                    )
                    synthetic_inputs = [
                        {
                            **candidates[0],
                            "access": (
                                parent_ports[name]["access"]
                                if name in parent_ports
                                else "read"
                            ),
                            "id": name,
                        }
                        for name, candidates in scope.items()
                        if len(candidates) == 1
                    ]
                    if len(synthetic_inputs) != len(scope):
                        found.add(
                            subject(
                                coordinate,
                                str(instruction_index),
                                "typing",
                            )
                        )
                        return None
                    unit_contract = cast(
                        dict[str, Any], fixed_value_contracts["kernel-unit"]
                    )
                    synthetic = {
                        "body": guard_body,
                        "default_outcome": guarded_outcome,
                        "effects": list(effects),
                        "id": guard_coordinate[2],
                        "inputs": synthetic_inputs,
                        "outcomes": list(parent_outcome_definitions.values()),
                        "refusals": list(refusals),
                        "resource_bounds": {
                            "max_steps": operation["resource_bounds"]["max_steps"]
                        },
                        "result": {
                            **unit_contract,
                            "access": "read",
                            "discardable": True,
                            "id": "result",
                            "source": {"kind": "unit"},
                        },
                    }
                    by_coordinate[guard_coordinate] = synthetic
                    guard_body_coordinates.add(guard_coordinate)
                    try:
                        guard_closure = close(guard_coordinate, (*stack, coordinate))
                    finally:
                        guard_body_coordinates.discard(guard_coordinate)
                        by_coordinate.pop(guard_coordinate, None)
                        closed.pop(guard_coordinate, None)
                    if guard_closure is None:
                        return None
                    body_effects, body_refusals, body_charge = guard_closure
                    if not body_effects <= effects:
                        found.add(
                            subject(
                                coordinate,
                                str(instruction_index),
                                "effects",
                            )
                        )
                        return None
                    if not body_refusals <= refusals:
                        found.add(
                            subject(
                                coordinate,
                                str(instruction_index),
                                "refusals",
                            )
                        )
                        return None
                    charge += body_charge
                result_definition = node.get("result")
                if isinstance(result_definition, dict) and result_definition.get(
                    "kind"
                ) in {"local", "draw"}:
                    if not isinstance(target, str) or not target or target in scope:
                        found.add(subject(coordinate, str(instruction_index), "target"))
                        return None
                    typing = result_definition.get("typing")
                    if not isinstance(typing, dict):
                        return None
                    kind = typing.get("kind")
                    produced: tuple[dict[str, Any], ...]
                    if kind == "fixed":
                        contract = fixed_value_contracts.get(typing.get("contract"))
                        if operator == "collection-is-empty":
                            value_name = instruction.get("value")
                            candidates = (
                                scope.get(value_name)
                                if isinstance(value_name, str)
                                else None
                            )
                            produced = (
                                (contract,)
                                if isinstance(contract, dict)
                                and candidates
                                and all(
                                    empty_contract(candidate) == typing.get("contract")
                                    for candidate in candidates
                                )
                                else ()
                            )
                        else:
                            produced = (contract,) if isinstance(contract, dict) else ()
                    elif kind == "same-as-references":
                        members = typing.get("members")
                        resolved = (
                            references(instruction, members)
                            if isinstance(members, list)
                            else None
                        )
                        produced = (
                            shared_contracts(resolved) if resolved is not None else ()
                        )
                    elif kind == "declared-result":
                        value_name = instruction.get("value")
                        value_candidates = (
                            scope.get(value_name)
                            if isinstance(value_name, str)
                            else None
                        )
                        declared_results: tuple[tuple[dict[str, Any], str], ...]
                        if value_candidates is None:
                            declared_results = ()
                        else:
                            declared_results = tuple(
                                result
                                for candidate in value_candidates
                                if (
                                    result := lookup_contract(
                                        candidate,
                                        instruction.get("key"),
                                        locals_.get(cast(str, instruction.get("key")))
                                        if isinstance(instruction.get("key"), str)
                                        else None,
                                    )
                                )
                                is not None
                            )
                        if any(
                            signal not in node.get("refusals", [])
                            or len(reasons_by_signal.get(signal, [])) != 1
                            or reasons_by_signal[signal][0] not in refusals
                            for _result, signal in declared_results
                        ):
                            found.add(
                                subject(
                                    coordinate,
                                    str(instruction_index),
                                    "refusals",
                                )
                            )
                            return None
                        produced = tuple(result for result, _signal in declared_results)
                    else:
                        members = typing.get("members")
                        produced = (
                            shared_contracts(
                                [
                                    literal_contracts(instruction.get(member))
                                    for member in members
                                ]
                            )
                            if isinstance(members, list)
                            else ()
                        )
                    if not produced:
                        found.add(subject(coordinate, str(instruction_index), "typing"))
                        return None
                    locals_[target] = produced
                    scope[target] = produced
                    local_producers[target] = 1
                    if source_kind == "local" and target == source.get("name"):
                        source_producer_reached = True
                continue
            site = instruction.get("site")
            operation_ref = instruction.get("operation")
            if (
                not isinstance(site, str)
                or not isinstance(operation_ref, dict)
                or not all(
                    isinstance(operation_ref.get(member), str)
                    for member in ("package", "version", "id")
                )
            ):
                found.add(subject(coordinate, cast(str | None, site), "operation"))
                return None
            child_coordinate = (
                operation_ref["package"],
                operation_ref["version"],
                operation_ref["id"],
            )
            if child_coordinate in stack or child_coordinate == coordinate:
                found.add(subject(coordinate, "cycle", "operation"))
                return None
            child = by_coordinate.get(child_coordinate)
            if not isinstance(child, dict):
                found.add(subject(coordinate, site, "operation"))
                return None
            child_ports = cast(list[dict[str, Any]], child.get("inputs", []))
            arguments = instruction.get("arguments")
            if not isinstance(arguments, list) or [
                row.get("port") for row in arguments
            ] != [row.get("id") for row in child_ports]:
                found.add(subject(coordinate, site, "arguments"))
                return None
            aliases: dict[str, list[tuple[str, str]]] = {}
            for formal, argument in zip(child_ports, arguments, strict=True):
                operand = argument.get("operand")
                if not isinstance(operand, dict):
                    found.add(subject(coordinate, site, "arguments"))
                    return None
                kind = operand.get("kind")
                if kind == "port":
                    actual = parent_ports.get(operand.get("port"))
                    if (
                        not isinstance(actual, dict)
                        or not value_contract_matches(actual, formal)
                        or (
                            formal.get("access") in {"read-write", "write"}
                            and actual.get("access") not in {"read-write", "write"}
                        )
                    ):
                        found.add(subject(coordinate, site, "arguments"))
                        return None
                    alias_key = f"port:{operand['port']}"
                elif kind == "local":
                    local_name = operand.get("local")
                    if not isinstance(local_name, str):
                        found.add(subject(coordinate, site, "arguments"))
                        return None
                    actual_candidates = locals_.get(local_name)
                    if (
                        not actual_candidates
                        or formal.get("access") != "read"
                        or sum(
                            value_contract_matches(actual, formal)
                            for actual in actual_candidates
                        )
                        != 1
                    ):
                        found.add(subject(coordinate, site, "arguments"))
                        return None
                    alias_key = f"local:{local_name}"
                elif kind == "literal":
                    literal = operand.get("literal")
                    if formal.get("access") != "read" or not literal_matches(
                        literal, formal
                    ):
                        found.add(subject(coordinate, site, "arguments"))
                        return None
                    alias_key = f"literal:{literal}"
                else:
                    found.add(subject(coordinate, site, "arguments"))
                    return None
                aliases.setdefault(alias_key, []).append(
                    (cast(str, formal["id"]), cast(str, formal["access"]))
                )
            if not aliases_are_admitted(child, aliases):
                found.add(subject(coordinate, site, "aliases"))
                return None
            result = instruction.get("result")
            if not isinstance(result, dict):
                found.add(subject(coordinate, site, "result"))
                return None
            if result.get("kind") == "discard":
                if child.get("result", {}).get("discardable") is not True:
                    found.add(subject(coordinate, site, "result"))
                    return None
            elif result.get("kind") == "local":
                local = result.get("name")
                if not isinstance(local, str) or not local or local in scope:
                    found.add(subject(coordinate, site, "result"))
                    return None
                child_result = cast(dict[str, Any], child["result"])
                locals_[local] = (child_result,)
                scope[local] = (child_result,)
                local_producers[local] = 1
            elif result.get("kind") == "operation-result":
                if not value_contract_matches(
                    cast(dict[str, Any], child["result"]),
                    cast(dict[str, Any], operation["result"]),
                ):
                    found.add(subject(coordinate, site, "result"))
                    return None
                operation_result_sites.add(site)
            else:
                found.add(subject(coordinate, site, "result"))
                return None
            child_outcomes = [
                row.get("id")
                for row in child.get("outcomes", [])
                if isinstance(row, dict)
            ]
            mappings = instruction.get("outcomes")
            if (
                not isinstance(mappings, list)
                or [row.get("outcome") for row in mappings] != child_outcomes
                or (
                    coordinate in guard_body_coordinates
                    and any(
                        row.get("action", {}).get("kind") == "propagate"
                        for row in mappings
                    )
                )
                or any(
                    row.get("action", {}).get("kind") == "propagate"
                    and row["action"].get("outcome") not in parent_outcomes
                    for row in mappings
                )
            ):
                found.add(subject(coordinate, site, "outcomes"))
                return None
            child_outcome_definitions = {
                row["id"]: row
                for row in child.get("outcomes", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            produces_source = (
                source_kind == "operation-result" and site == source_site
            ) or (
                source_kind == "local"
                and result.get("kind") == "local"
                and result.get("name") == source.get("name")
            )
            if source_kind in {"local", "operation-result"}:
                reaches_parent_success = any(
                    (
                        mapping["action"].get("kind") == "continue"
                        or (
                            mapping["action"].get("kind") == "propagate"
                            and mapping["action"].get("outcome") in parent_successes
                        )
                    )
                    and child_outcome_definitions[mapping["outcome"]].get("kind")
                    != "success"
                    for mapping in cast(list[dict[str, Any]], mappings)
                )
                exits_success_before_source = (
                    not source_producer_reached
                    and not produces_source
                    and any(
                        mapping["action"].get("kind") == "propagate"
                        and mapping["action"].get("outcome") in parent_successes
                        for mapping in cast(list[dict[str, Any]], mappings)
                    )
                )
                if (
                    produces_source and reaches_parent_success
                ) or exits_success_before_source:
                    found.add(subject(coordinate, None, "result.source"))
                    return None
                if produces_source:
                    source_producer_reached = True
            child_closure = close(child_coordinate, (*stack, coordinate))
            if child_closure is None:
                return None
            child_effects, child_refusals, child_charge = child_closure
            if not child_effects <= set(cast(list[str], operation["effects"])):
                found.add(subject(coordinate, site, "effects"))
                return None
            if not child_refusals <= set(cast(list[str], operation["refusals"])):
                found.add(subject(coordinate, site, "refusals"))
                return None
            effects.update(child_effects)
            refusals.update(child_refusals)
            charge += child_charge

        result_contract = cast(dict[str, Any], operation["result"])
        local_result_candidates = (
            locals_.get(cast(str, source.get("name")))
            if source_kind == "local"
            else None
        )
        source_is_compatible = (
            (
                source_kind == "operation-result"
                and source_site in operation_result_sites
                and source_producer_reached
            )
            or (
                source_kind == "port"
                and isinstance(parent_ports.get(source.get("name")), dict)
                and value_contract_matches(
                    cast(dict[str, Any], parent_ports[source["name"]]),
                    result_contract,
                )
            )
            or (
                source_kind == "local"
                and local_producers.get(cast(str, source.get("name"))) == 1
                and source_producer_reached
                and bool(local_result_candidates)
                and sum(
                    value_contract_matches(candidate, result_contract)
                    for candidate in cast(
                        tuple[dict[str, Any], ...],
                        local_result_candidates,
                    )
                )
                == 1
            )
            or (
                source_kind == "unit"
                and result_contract.get("type")
                == {"package": "kernel", "version": "2.0.0", "id": "Unit"}
                and result_contract.get("representation") == "Unit"
                and result_contract.get("kind") == "unit"
                and result_contract.get("unit") == "1"
                and result_contract.get("domain") == {"kind": "unit"}
                and result_contract.get("numeric_policy") == "exact-unit"
            )
        )
        if not source_is_compatible:
            found.add(subject(coordinate, None, "result.source"))
            return None
        if charge > operation.get("resource_bounds", {}).get("max_steps", -1):
            found.add(subject(coordinate, None, "resource_bounds"))
            return None
        closed[coordinate] = (effects, refusals, charge)
        return closed[coordinate]

    for coordinate in sorted(by_coordinate):
        close(coordinate, ())
    return tuple(sorted(found))


def _consumer_b(kernel: dict[str, Any], ldb: dict[str, Any]) -> dict[str, Any]:
    """A separate, deliberately compact Kernel interpreter for cross-checking."""
    diagnostics: set[tuple[str, str, str]] = set()
    cap = kernel.get("resources", {}).get("max_diagnostics", 128)
    if not isinstance(cap, int) or cap < 1:
        cap = 128

    def refuse(code: str, stage: str, subject: str) -> None:
        diagnostics.add((stage, code, subject))

    kernel_domain = _declared_identity_domain(kernel, artifact="kernel")
    ldb_domain = _declared_identity_domain(kernel, artifact="language-bundle")
    package_release_domain = _declared_identity_domain(
        kernel, collection="language_bundle.language.packages"
    )
    package_vector_set_domain = _declared_identity_domain(
        kernel,
        collection="language_bundle.package_conformance_vector_sets",
    )
    if (
        kernel.get("content_identity")
        != _identity_from_kernel(kernel, kernel_domain or "", kernel)
        or kernel.get("content_identity") != _SUPPORTED_KERNEL_IDENTITY
    ):
        refuse("kernel.identity_mismatch", "ingress", "kernel")
    raw_graph_root = getattr(ldb, "root", None)
    raw_graph_releases = getattr(ldb, "package_releases", None)
    raw_graph_vector_sets = getattr(ldb, "package_conformance_vector_sets", None)
    raw_graph_root_size = getattr(ldb, "root_byte_size", None)
    raw_graph_package_sizes = getattr(ldb, "package_byte_sizes", None)
    raw_graph_vector_set_sizes = getattr(ldb, "vector_set_byte_sizes", None)
    is_graph = (
        isinstance(raw_graph_root, dict)
        and isinstance(raw_graph_releases, list)
        and isinstance(raw_graph_vector_sets, list)
        and isinstance(raw_graph_root_size, int)
        and isinstance(raw_graph_package_sizes, tuple)
        and isinstance(raw_graph_vector_set_sizes, tuple)
    )
    raw_graph_candidate = is_graph and not isinstance(ldb, LanguageBundleIndex)
    graph_root = cast(dict[str, Any], raw_graph_root) if is_graph else {}
    graph_releases = cast(list[dict[str, Any]], raw_graph_releases) if is_graph else []
    graph_vector_sets = (
        cast(list[dict[str, Any]], raw_graph_vector_sets) if is_graph else []
    )
    graph_root_size = cast(int, raw_graph_root_size) if is_graph else 0
    graph_package_sizes = (
        cast(tuple[int, ...], raw_graph_package_sizes) if is_graph else ()
    )
    graph_vector_set_sizes = (
        cast(tuple[int, ...], raw_graph_vector_set_sizes) if is_graph else ()
    )
    descriptor_contract = (
        kernel.get("meta_format", {})
        .get("language_bundle", {})
        .get("package_descriptor")
    )
    descriptor_order = (
        descriptor_contract.get("canonical_order")
        if isinstance(descriptor_contract, dict)
        else None
    )
    if is_graph and isinstance(descriptor_order, list) and descriptor_order:
        descriptors = graph_root.get("package_descriptors")
        if (
            isinstance(descriptors, list)
            and len(descriptors) == len(graph_releases)
            and len(descriptors) == len(graph_vector_sets)
            and len(descriptors) == len(graph_package_sizes)
            and len(descriptors) == len(graph_vector_set_sizes)
            and all(
                isinstance(descriptor, dict)
                and all(
                    isinstance(descriptor.get(name), str) for name in descriptor_order
                )
                for descriptor in descriptors
            )
        ):
            members = sorted(
                zip(
                    descriptors,
                    graph_releases,
                    graph_vector_sets,
                    graph_package_sizes,
                    graph_vector_set_sizes,
                    strict=True,
                ),
                key=lambda member: tuple(
                    cast(dict[str, Any], member[0])[name] for name in descriptor_order
                ),
            )
            graph_root = deepcopy(graph_root)
            graph_root["package_descriptors"] = [
                deepcopy(descriptor)
                for descriptor, _release, _vectors, _package_size, _vector_size in members
            ]
            graph_releases = [
                deepcopy(release)
                for _descriptor, release, _vectors, _package_size, _vector_size in members
            ]
            graph_vector_sets = [
                deepcopy(vectors)
                for _descriptor, _release, vectors, _package_size, _vector_size in members
            ]
            graph_package_sizes = tuple(
                size for _descriptor, _release, _vectors, size, _vector_size in members
            )
            graph_vector_set_sizes = tuple(
                size for _descriptor, _release, _vectors, _package_size, size in members
            )
    identity_source = graph_root if is_graph else ldb
    if ldb.get("content_identity") != _identity_from_kernel(
        kernel, ldb_domain or "", identity_source
    ):
        refuse("kernel.identity_mismatch", "ingress", "language-bundle")
    if ldb.get("kernel_identity") != kernel.get("content_identity"):
        refuse("kernel.binding_mismatch", "ingress", "language-bundle.kernel_identity")
    if is_graph:
        descriptors = graph_root.get("package_descriptors")
        expected_root_members = {
            "artifact_kind",
            "artifact_version",
            "content_identity",
            "kernel_identity",
            "package_descriptors",
            "resources",
            "schema_major",
        }
        descriptor_required = (
            descriptor_contract.get("required_members")
            if isinstance(descriptor_contract, dict)
            else None
        )
        descriptor_field_types = (
            descriptor_contract.get("field_types")
            if isinstance(descriptor_contract, dict)
            else None
        )
        expected_descriptor_members = (
            set(descriptor_required)
            if isinstance(descriptor_required, list)
            and all(isinstance(item, str) for item in descriptor_required)
            else set()
        )
        if (
            set(graph_root) != expected_root_members
            or not isinstance(descriptors, list)
            or len(descriptors) != len(graph_releases)
            or len(descriptors) != len(graph_vector_sets)
            or len(descriptors) != len(graph_package_sizes)
            or len(descriptors) != len(graph_vector_set_sizes)
        ):
            refuse("kernel.member_set_mismatch", "ingress", "language-bundle")
        else:
            coordinates = []
            coordinates_are_strings = True
            for index, (
                descriptor,
                release,
                vector_set,
                package_byte_size,
                vector_set_byte_size,
            ) in enumerate(
                zip(
                    descriptors,
                    graph_releases,
                    graph_vector_sets,
                    graph_package_sizes,
                    graph_vector_set_sizes,
                    strict=True,
                )
            ):
                subject = f"language-bundle.package_descriptors.{index}"
                if (
                    not isinstance(descriptor, dict)
                    or set(descriptor) != expected_descriptor_members
                    or not isinstance(descriptor_field_types, dict)
                    or set(descriptor_field_types) != expected_descriptor_members
                    or not all(
                        _consumer_b_value_matches(
                            descriptor[name], descriptor_field_types[name], ldb
                        )
                        for name in expected_descriptor_members
                    )
                    or descriptor.get("artifact_kind") != release.get("artifact_kind")
                    or descriptor.get("id") != release.get("id")
                    or descriptor.get("version") != release.get("version")
                    or descriptor.get("content_identity")
                    != release.get("content_identity")
                    or descriptor.get("byte_size") != package_byte_size
                ):
                    refuse("kernel.binding_mismatch", "ingress", subject)
                    continue
                if isinstance(descriptor["id"], str) and isinstance(
                    descriptor["version"], str
                ):
                    coordinates.append((descriptor["id"], descriptor["version"]))
                else:
                    coordinates_are_strings = False
                if release.get("content_identity") != _identity_from_kernel(
                    kernel, package_release_domain or "", release
                ):
                    refuse("kernel.identity_mismatch", "ingress", subject)
                vector_descriptor = release.get("conformance_vectors")
                vector_subject = f"{subject}.conformance_vectors"
                if (
                    not isinstance(vector_descriptor, dict)
                    or set(vector_descriptor)
                    != {"artifact_kind", "byte_size", "content_identity"}
                    or vector_descriptor.get("artifact_kind")
                    != vector_set.get("artifact_kind")
                    or vector_descriptor.get("content_identity")
                    != vector_set.get("content_identity")
                    or vector_descriptor.get("byte_size") != vector_set_byte_size
                    or vector_set.get("package_id") != release.get("id")
                    or vector_set.get("package_version") != release.get("version")
                ):
                    refuse("kernel.binding_mismatch", "ingress", vector_subject)
                elif vector_set.get("content_identity") != _identity_from_kernel(
                    kernel, package_vector_set_domain or "", vector_set
                ):
                    refuse("kernel.identity_mismatch", "ingress", vector_subject)
            if coordinates_are_strings and coordinates != sorted(coordinates):
                refuse(
                    "kernel.member_set_mismatch",
                    "ingress",
                    "language-bundle.package_descriptors",
                )
            if coordinates_are_strings and len(coordinates) != len(set(coordinates)):
                refuse(
                    "kernel.duplicate_identifier",
                    "static",
                    "language-bundle.package_descriptors",
                )
            package_coordinates = set(coordinates)
            dependency_graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
            for release in graph_releases:
                dependencies = release.get("dependencies")
                package_id = release.get("id")
                package_version = release.get("version")
                if (
                    not isinstance(dependencies, dict)
                    or not isinstance(package_id, str)
                    or not isinstance(package_version, str)
                ):
                    continue
                required = dependencies.get("required")
                optional = dependencies.get("optional")
                if not isinstance(required, list) or not isinstance(optional, list):
                    continue
                if all(
                    isinstance(dependency, dict)
                    and set(dependency) == {"id", "version"}
                    and isinstance(dependency["id"], str)
                    and bool(dependency["id"])
                    and isinstance(dependency["version"], str)
                    and bool(dependency["version"])
                    for dependency in [*required, *optional]
                ):
                    dependency_graph[(package_id, package_version)] = {
                        (dependency["id"], dependency["version"])
                        for dependency in required
                    }
                if any(
                    not isinstance(dependency, dict)
                    or set(dependency) != {"id", "version"}
                    or (dependency.get("id"), dependency.get("version"))
                    not in package_coordinates
                    for dependency in [*required, *optional]
                ) or len(
                    {
                        (dependency["id"], dependency["version"])
                        for dependency in [*required, *optional]
                        if isinstance(dependency, dict)
                        and set(dependency) == {"id", "version"}
                    }
                ) != len([*required, *optional]):
                    refuse(
                        "kernel.binding_mismatch",
                        "ingress",
                        f"language-bundle.packages.{package_id}.dependencies",
                    )

            visiting: set[tuple[str, str]] = set()
            visited: set[tuple[str, str]] = set()

            def cyclic(coordinate: tuple[str, str]) -> bool:
                if coordinate in visiting:
                    return True
                if coordinate in visited:
                    return False
                visiting.add(coordinate)
                has_cycle = any(
                    cyclic(dependency)
                    for dependency in sorted(dependency_graph.get(coordinate, set()))
                    if dependency in dependency_graph
                )
                visiting.remove(coordinate)
                visited.add(coordinate)
                return has_cycle

            has_dependency_cycle = any(
                cyclic(coordinate) for coordinate in sorted(dependency_graph)
            )
            if has_dependency_cycle:
                refuse(
                    "kernel.binding_mismatch",
                    "ingress",
                    "language-bundle.package-dependencies",
                )

            graph_limit_names = {
                "max_ldb_root_bytes",
                "max_ldb_child_bytes",
                "max_ldb_package_bytes",
                "max_ldb_total_bytes",
                "max_ldb_package_count",
                "max_ldb_package_member_count",
                "max_ldb_dependency_depth",
                "max_ldb_dependency_steps",
                "max_ldb_admission_work",
            }
            graph_resources = kernel.get("resources")
            graph_limits = (
                {name: graph_resources.get(name) for name in graph_limit_names}
                if isinstance(graph_resources, dict)
                else {}
            )
            if set(graph_limits) != graph_limit_names or not all(
                isinstance(value, int) and value > 0 for value in graph_limits.values()
            ):
                refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
            else:
                typed_graph_limits = cast(dict[str, int], graph_limits)
                dependency_steps = sum(
                    len(dependencies) for dependencies in dependency_graph.values()
                )
                dependency_depth = 0
                if not has_dependency_cycle:
                    depths: dict[tuple[str, str], int] = {}

                    def depth_of(coordinate: tuple[str, str]) -> int:
                        known = depths.get(coordinate)
                        if known is not None:
                            return known
                        depth = 1 + max(
                            (
                                depth_of(dependency)
                                for dependency in sorted(
                                    dependency_graph.get(coordinate, set())
                                )
                            ),
                            default=0,
                        )
                        depths[coordinate] = depth
                        return depth

                    dependency_depth = max(
                        (depth_of(coordinate) for coordinate in dependency_graph),
                        default=0,
                    )
                graph_work = (
                    _work(graph_root)
                    + sum(_work(release) for release in graph_releases)
                    + sum(_work(vector_set) for vector_set in graph_vector_sets)
                )
                if (
                    graph_root_size > typed_graph_limits["max_ldb_root_bytes"]
                    or any(
                        size > typed_graph_limits["max_ldb_child_bytes"]
                        for size in (*graph_package_sizes, *graph_vector_set_sizes)
                    )
                    or any(
                        package_size + vector_size
                        > typed_graph_limits["max_ldb_package_bytes"]
                        for package_size, vector_size in zip(
                            graph_package_sizes,
                            graph_vector_set_sizes,
                            strict=True,
                        )
                    )
                    or typed_graph_limits["max_ldb_package_member_count"] != 2
                    or graph_root_size
                    + sum(graph_package_sizes)
                    + sum(graph_vector_set_sizes)
                    > typed_graph_limits["max_ldb_total_bytes"]
                    or len(graph_releases) > typed_graph_limits["max_ldb_package_count"]
                    or dependency_depth > typed_graph_limits["max_ldb_dependency_depth"]
                    or dependency_steps > typed_graph_limits["max_ldb_dependency_steps"]
                    or graph_work > typed_graph_limits["max_ldb_admission_work"]
                ):
                    refuse(
                        "kernel.resource_exhausted",
                        "ingress",
                        "language-bundle",
                    )
            language: dict[str, Any] = {
                member: {} if member == "quantity" else []
                for member in kernel["admission"]["required_language_members"]
            }
            derived_diagnostics: list[Any] = []
            derived_vectors: list[Any] = []
            for release, vector_set in zip(
                graph_releases, graph_vector_sets, strict=True
            ):
                for entry in release.get("semantic_closure", []):
                    authority_path = entry.get("authority_path")
                    definitions = entry.get("definitions")
                    if not isinstance(authority_path, str) or not isinstance(
                        definitions, list
                    ):
                        continue
                    if authority_path == "diagnostics":
                        derived_diagnostics.extend(deepcopy(definitions))
                        continue
                    if not authority_path.startswith("language."):
                        continue
                    segments = authority_path.split(".")[1:]
                    target = language
                    for segment in segments[:-1]:
                        target = target.setdefault(segment, {})
                    target.setdefault(segments[-1], []).extend(deepcopy(definitions))
                derived_vectors.extend(
                    deepcopy(vector_set.get("vector_definitions", []))
                )
            language["packages"] = deepcopy(graph_releases)
            expected_index = {
                "artifact_kind": graph_root.get("artifact_kind"),
                "artifact_version": graph_root.get("artifact_version"),
                "content_identity": graph_root.get("content_identity"),
                "diagnostics": derived_diagnostics,
                "kernel_identity": graph_root.get("kernel_identity"),
                "language": language,
                "resources": deepcopy(graph_root.get("resources")),
                "schema_major": graph_root.get("schema_major"),
                "vectors": derived_vectors,
            }
            if raw_graph_candidate and diagnostics:
                ordered = sorted(
                    diagnostics, key=lambda item: (item[0], item[2], item[1])
                )
                return {
                    "admitted": False,
                    "kernel_identity": kernel.get("content_identity"),
                    "language_bundle_identity": ldb.get("content_identity"),
                    "law_ids": [],
                    "law_projections": [],
                    "rule_ids": [],
                    "rule_projections": [],
                    "diagnostic_projections": [],
                    "diagnostics": ordered[:cap],
                    "truncated": len(ordered) > cap,
                }
            if raw_graph_candidate:
                ldb = expected_index
            elif expected_index != dict(ldb):
                refuse(
                    "kernel.identity_mismatch",
                    "ingress",
                    "language-bundle.admitted-index",
                )

    kernel_members = {
        "admission",
        "artifact_kind",
        "artifact_version",
        "canonical_encoding",
        "content_identity",
        "diagnostics",
        "meta_format",
        "resources",
        "schema_major",
        "vectors",
    }
    if set(kernel) != kernel_members:
        refuse("kernel.member_set_mismatch", "ingress", "kernel")

    if any(subject == "kernel" for _, _, subject in diagnostics):
        ordered = sorted(diagnostics, key=lambda item: (item[0], item[2], item[1]))
        return {
            "admitted": False,
            "kernel_identity": kernel.get("content_identity"),
            "language_bundle_identity": ldb.get("content_identity"),
            "law_ids": [],
            "law_projections": [],
            "rule_ids": [],
            "rule_projections": [],
            "diagnostic_projections": [],
            "diagnostics": ordered[:cap],
            "truncated": len(ordered) > cap,
        }

    expected_members = set(
        kernel["meta_format"]["admitted_language_index"]["required_members"]
    )
    if set(ldb) != expected_members:
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")
    expected_language_members = set(kernel["admission"]["required_language_members"])
    if (
        not isinstance(ldb.get("language"), dict)
        or set(ldb["language"]) != expected_language_members
    ):
        refuse(
            "kernel.member_set_mismatch",
            "ingress",
            "language-bundle.language",
        )
    meta = cast(dict[str, Any], kernel.get("meta_format", {}))
    ldb_contract = (
        meta.get("admitted_language_index") if isinstance(meta, dict) else None
    )
    if not _consumer_b_ldb_is_closed(
        ldb, ldb_contract, kernel["admission"].get("refusal_stages")
    ):
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")

    limits = kernel["resources"]
    resource_artifacts = [("kernel", kernel)]
    if is_graph:
        resource_artifacts.append(("language-bundle", graph_root))
        resource_artifacts.extend(
            (f"language-bundle.packages.{index}", package)
            for index, package in enumerate(graph_releases)
        )
        resource_artifacts.extend(
            (f"language-bundle.package-vectors.{index}", vector_set)
            for index, vector_set in enumerate(graph_vector_sets)
        )
    else:
        resource_artifacts.append(("language-bundle", ldb))
    for subject, artifact in resource_artifacts:
        depth, members = _shape(artifact)
        try:
            encoded_size = len(_encoded(artifact))
        except (TypeError, ValueError, UnicodeEncodeError):
            encoded_size = limits["max_authority_bytes"] + 1
        if (
            depth > limits["max_nesting_depth"]
            or members > limits["max_members"]
            or encoded_size > limits["max_authority_bytes"]
        ):
            refuse("kernel.resource_exhausted", "ingress", subject)

    raw_language = ldb.get("language")
    raw_packages = (
        raw_language.get("packages") if isinstance(raw_language, dict) else None
    )
    packages: list[dict[str, Any]] = []
    semantic_projection_mismatch = False
    package_contract = meta.get("package_release") if isinstance(meta, dict) else None
    package_vector_contract = (
        meta.get("package_vector") if isinstance(meta, dict) else None
    )
    package_vector_set_contract = (
        meta.get("package_conformance_vector_set") if isinstance(meta, dict) else None
    )
    definitions_are_closed = _consumer_b_language_definitions_are_closed(ldb, meta)
    evidence_claim_kinds_are_closed = (
        definitions_are_closed
        and _consumer_b_evidence_claim_kinds_are_closed(ldb, meta)
    )
    artifact_semantic_projections_are_closed = (
        definitions_are_closed
        and _consumer_b_artifact_semantic_projections_are_closed(ldb)
    )
    literal_typing_profiles_are_closed = (
        definitions_are_closed
        and _consumer_b_literal_typing_profiles_are_closed(kernel, ldb)
    )
    composition_subjects = (
        _consumer_b_operation_composition_subjects(kernel, ldb)
        if literal_typing_profiles_are_closed
        else ()
    )
    raw_diagnostics = ldb.get("diagnostics")
    raw_vectors = ldb.get("vectors")
    early_diagnostic_catalog = (
        {
            (str(item.get("code", "")), str(item.get("stage", "")))
            for item in raw_diagnostics
            if isinstance(item, dict)
        }
        if isinstance(raw_diagnostics, list)
        else set()
    )
    early_vector_catalog = (
        {
            (str(item.get("diagnostic", "")), str(item.get("stage", "")))
            for item in raw_vectors
            if isinstance(item, dict) and "diagnostic" in item
        }
        if isinstance(raw_vectors, list)
        else set()
    )
    diagnostic_catalog_matches_vectors = (
        isinstance(raw_diagnostics, list)
        and early_diagnostic_catalog == early_vector_catalog
    )
    if not _consumer_b_package_vector_contract_is_closed(package_vector_contract):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "kernel.meta_format.package_vector",
        )
    if not isinstance(raw_packages, list):
        refuse(
            "kernel.member_set_mismatch",
            "ingress",
            "language-bundle.language.packages",
        )
    else:
        for index, package in enumerate(raw_packages):
            subject = f"language-bundle.language.packages.{index}"
            if not isinstance(package, dict) or not _consumer_b_package_is_closed(
                package, package_contract, ldb
            ):
                refuse("kernel.member_set_mismatch", "ingress", subject)
                continue
            packages.append(package)
            if package.get("content_identity") != _identity_from_kernel(
                kernel, package_release_domain or "", package
            ):
                refuse("kernel.identity_mismatch", "ingress", subject)
            if not _consumer_b_package_semantic_closure_is_closed(
                package, package_contract
            ):
                refuse(
                    "kernel.identity_mismatch",
                    "ingress",
                    f"{subject}.semantic_identity",
                )
            vector_set = (
                graph_vector_sets[index] if index < len(graph_vector_sets) else None
            )
            if (
                not isinstance(vector_set, dict)
                or not _consumer_b_package_vector_set_is_closed(
                    vector_set, package_vector_set_contract
                )
                or vector_set.get("package_id") != package.get("id")
                or vector_set.get("package_version") != package.get("version")
                or (
                    literal_typing_profiles_are_closed
                    and not composition_subjects
                    and diagnostic_catalog_matches_vectors
                    and not _consumer_b_package_evidence_vectors_are_closed(
                        package,
                        vector_set,
                        package_vector_contract,
                        meta.get("runtime_program", {})
                        .get("named_rng", {})
                        .get("candidate_encoding"),
                        meta.get("runtime_program"),
                        kernel,
                        ldb,
                    )
                )
            ):
                refuse("kernel.vector_mismatch", "static", f"{subject}.vectors")
        semantic_projection_mismatch = len(packages) == len(
            raw_packages
        ) and not _consumer_b_package_semantic_projections_are_exact(
            packages, package_contract, ldb
        )

    if diagnostics:
        ordered = sorted(diagnostics, key=lambda item: (item[0], item[2], item[1]))
        truncated = len(ordered) > cap
        return {
            "admitted": False,
            "kernel_identity": kernel.get("content_identity"),
            "language_bundle_identity": ldb.get("content_identity"),
            "law_ids": [],
            "law_projections": [],
            "rule_ids": [],
            "rule_projections": [],
            "diagnostic_projections": [],
            "diagnostics": ordered[:cap],
            "truncated": truncated,
        }

    laws = kernel["admission"]["laws"]
    for subject in _consumer_b_duplicate_subjects(kernel, ldb):
        refuse("kernel.duplicate_identifier", "static", subject)
    operation_law = next(law for law in laws if law["id"] == "kernel.operations.closed")
    allowed_operations = set(operation_law["arguments"]["admission_operations"])
    law_ids = [law["id"] for law in laws]
    if len(law_ids) != len(set(law_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.admission.laws")
    for law in laws:
        if law["operation"] not in allowed_operations:
            refuse("kernel.unknown_operation", "static", law["id"])
    law_projections = sorted(
        (law["id"], _identity("kernel-law-projection-v2", law)) for law in laws
    )

    kernel_vectors = kernel["vectors"]
    kernel_vector_ids = [vector["id"] for vector in kernel_vectors]
    if len(kernel_vector_ids) != len(set(kernel_vector_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.vectors")
    referenced_laws = {vector["law"] for vector in kernel_vectors}
    if set(law_ids) != referenced_laws:
        refuse("kernel.vector_mismatch", "static", "kernel.vectors")
    kernel_codes = [item["code"] for item in kernel["diagnostics"]]
    if len(kernel_codes) != len(set(kernel_codes)):
        refuse("kernel.duplicate_identifier", "static", "kernel.diagnostics")
    kernel_catalog = {(item["code"], item["stage"]) for item in kernel["diagnostics"]}
    kernel_vector_catalog = {
        (item["diagnostic"], item["stage"])
        for item in kernel_vectors
        if "diagnostic" in item
    }
    if kernel_catalog != kernel_vector_catalog:
        refuse("kernel.diagnostic_closure", "static", "kernel.diagnostics")

    meta = kernel["meta_format"]
    if not definitions_are_closed:
        refuse("kernel.vector_mismatch", "static", "language.definitions")
    if definitions_are_closed and not evidence_claim_kinds_are_closed:
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.evidence-claim-kinds",
        )
    if definitions_are_closed and not artifact_semantic_projections_are_closed:
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.definitions.artifact-semantic-projections",
        )
    if not _consumer_b_assignment_policy_is_total(ldb):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.definitions.assignment-policy",
        )
    if definitions_are_closed and not literal_typing_profiles_are_closed:
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.literal-typing-profiles",
        )
    for composition_subject in composition_subjects:
        refuse("kernel.vector_mismatch", "static", composition_subject)
    if not _consumer_b_json_pointer_authority_is_closed(kernel):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "kernel.meta-format.json-pointer",
        )
    if not _consumer_b_authority_wire_schema_projection_is_closed(kernel):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "kernel.meta-format.authority-wire-schema-projection",
        )
    if not _consumer_b_runtime_authority_is_closed(kernel, ldb):
        refuse("kernel.vector_mismatch", "static", "language.runtime")
    if not _consumer_b_wire_schema_identity_domains_are_closed(ldb):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.wire-schema-identity-domains",
        )
    if not _consumer_b_embedded_artifact_bindings_are_closed(ldb):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.embedded-artifact-bindings",
        )
    ldb_codes = [item["code"] for item in ldb["diagnostics"]]
    if len(ldb_codes) != len(set(ldb_codes)):
        refuse("kernel.duplicate_identifier", "static", "language-bundle.diagnostics")
    if not diagnostic_catalog_matches_vectors:
        refuse("kernel.diagnostic_closure", "static", "language-bundle.diagnostics")
    raw_vectors = ldb.get("vectors")
    valid_vectors: list[dict[str, Any]] = []
    if not isinstance(raw_vectors, list):
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    elif diagnostic_catalog_matches_vectors:
        for vector in raw_vectors:
            if _consumer_b_vector_header_is_closed(vector, meta, ldb):
                valid_vectors.append(vector)
            else:
                subject = str(vector.get("id", "")) if isinstance(vector, dict) else ""
                refuse("kernel.vector_mismatch", "static", subject)
    raw_rules = ldb.get("language", {}).get("rules")
    rules: list[dict[str, Any]] = []
    if not isinstance(raw_rules, list) or not all(
        _consumer_b_rule_is_closed(rule, meta, ldb) for rule in raw_rules
    ):
        refuse("kernel.vector_mismatch", "static", "language.rules")
    else:
        rules = raw_rules
    raw_reasons = ldb.get("language", {}).get("reasons")
    reasons_list: list[dict[str, Any]] = []
    if not isinstance(raw_reasons, list) or not all(
        _consumer_b_reason_is_closed(reason, meta, ldb) for reason in raw_reasons
    ):
        refuse("kernel.vector_mismatch", "static", "language.reasons")
    else:
        reasons_list = raw_reasons
    if diagnostics:
        ordered = sorted(diagnostics, key=lambda item: (item[0], item[2], item[1]))
        return {
            "admitted": False,
            "kernel_identity": kernel.get("content_identity"),
            "language_bundle_identity": ldb.get("content_identity"),
            "law_ids": sorted(law_ids),
            "law_projections": law_projections,
            "rule_ids": [],
            "rule_projections": [],
            "diagnostic_projections": [],
            "diagnostics": ordered[:cap],
            "truncated": len(ordered) > cap,
        }
    rule_ids = [rule["id"] for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        refuse("kernel.duplicate_identifier", "static", "language.rules")
    ldb_vector_ids = [item["id"] for item in valid_vectors]
    if len(ldb_vector_ids) != len(set(ldb_vector_ids)):
        refuse(
            "kernel.duplicate_identifier",
            "static",
            "language-bundle.vectors",
        )
    program_vectors = [item for item in valid_vectors if "source_fixture" in item]
    program_contract = meta.get("model_program_vector")
    expected_categories = (
        program_contract.get("categories")
        if isinstance(program_contract, dict)
        else None
    )
    category_outcomes = (
        program_contract.get("category_outcomes")
        if isinstance(program_contract, dict)
        else None
    )
    program_by_id = {item["id"]: item for item in program_vectors}
    program_vectors_close = (
        isinstance(expected_categories, list)
        and isinstance(category_outcomes, dict)
        and set(expected_categories)
        == {item.get("category") for item in program_vectors}
        and all(
            {
                item.get("expect", {}).get("outcome")
                for item in program_vectors
                if item.get("category") == category
            }
            == set(category_outcomes.get(category, []))
            for category in expected_categories
        )
    )
    if program_vectors_close:
        for vector in program_vectors:
            relation = vector["expect"]["relation"]
            if relation["kind"] == "independent":
                continue
            reference = program_by_id.get(relation["reference"])
            if reference is None:
                program_vectors_close = False
                break
            expected = vector["expect"]
            reference_expected = reference["expect"]
            if (
                expected["lock_oracle"] != reference_expected["lock_oracle"]
                or (
                    relation["kind"] == "semantic-equivalent"
                    and (
                        expected["rir_identity"] != reference_expected["rir_identity"]
                        or expected["debug_map_identity"]
                        == reference_expected["debug_map_identity"]
                    )
                )
                or (
                    relation["kind"] == "semantic-change"
                    and expected["rir_identity"] == reference_expected["rir_identity"]
                )
            ):
                program_vectors_close = False
                break
    if not program_vectors_close:
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language-bundle.model-program-vectors",
        )
    rule_vectors = [item for item in valid_vectors if "rule" in item]
    if set(rule_ids) != {item["rule"] for item in rule_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    projections = []
    for vector in rule_vectors:
        invocation = vector.get("input")
        if (
            set(vector) != {"expect", "id", "input", "rule"}
            or not isinstance(invocation, dict)
            or set(invocation) != {"facts", "judgment", "phase"}
            or not isinstance(invocation.get("facts"), list)
            or not all(
                _consumer_b_fact_is_closed(fact, meta, ldb)
                for fact in invocation.get("facts", [])
            )
        ):
            refuse("kernel.vector_mismatch", "static", str(vector.get("id", "")))
            continue
        facts = invocation["facts"]
        candidates = [
            rule
            for rule in sorted(rules, key=lambda item: item["id"])
            if rule["phase"] == invocation["phase"]
            and rule["judgment"] == invocation["judgment"]
            and len(rule["premises"]) == len(facts)
            and all(
                premise["fact_kind"] == fact["kind"]
                for premise, fact in zip(rule["premises"], facts, strict=True)
            )
        ]
        output = None
        if len(candidates) == 1 and candidates[0]["id"] == vector["rule"]:
            selected = candidates[0]
            bindings = {}
            valid = True
            for premise, fact in zip(selected["premises"], facts, strict=True):
                for variable, field_name in premise["bind"].items():
                    if field_name not in fact["fields"]:
                        valid = False
                        break
                    value = fact["fields"][field_name]
                    if variable in bindings and bindings[variable] != value:
                        valid = False
                        break
                    bindings[variable] = value
            fields = {}
            for name, term in selected["conclusion"]["fields"].items():
                if term["tag"] == "literal" and set(term) == {"tag", "value"}:
                    fields[name] = term["value"]
                elif (
                    term["tag"] == "variable"
                    and isinstance(term.get("name"), str)
                    and term["name"] in bindings
                ):
                    fields[name] = bindings[term["name"]]
                else:
                    valid = False
            if valid:
                output = {"kind": selected["conclusion"]["fact_kind"], "fields": fields}
                if not _consumer_b_fact_is_closed(output, meta, ldb):
                    output = None
        if output != vector["expect"]:
            refuse("kernel.vector_mismatch", "static", vector["id"])
        else:
            assert isinstance(output, dict)
            projections.append(
                (vector["id"], _identity("rule-vector-projection-v2", output))
            )

    def resolve(path: str) -> Any:
        value: Any = ldb
        for part in path.split("."):
            value = value[part]
        return value

    reasons = {item["id"]: item for item in reasons_list}
    diagnostic_projections = []
    diagnostic_vectors = [item for item in valid_vectors if "diagnostic" in item]
    if set(reasons) != {item.get("reason") for item in diagnostic_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.reasons")
    reason_contract = meta.get("diagnostic_reason")
    vector_required = (
        reason_contract.get("vector_required_members")
        if isinstance(reason_contract, dict)
        else None
    )
    vector_types = (
        reason_contract.get("vector_member_types")
        if isinstance(reason_contract, dict)
        else None
    )
    for vector in diagnostic_vectors:
        reason = reasons.get(vector.get("reason"))
        matched = False
        if (
            not isinstance(vector_required, list)
            or set(vector) != set(vector_required)
            or not isinstance(vector_types, dict)
            or set(vector_types) != set(vector_required) - {"input"}
            or not all(
                _consumer_b_value_matches(vector[name], vector_types[name], ldb)
                for name in vector_types
            )
            or not _consumer_b_reason_is_closed(reason, meta, ldb)
            or not isinstance(vector.get("input"), dict)
        ):
            refuse("kernel.vector_mismatch", "static", str(vector.get("id", "")))
            continue
        if reason is not None:
            if (
                vector["reason"] != reason["id"]
                or vector["diagnostic"] != reason["diagnostic"]
                or vector["stage"] != reason["stage"]
            ):
                refuse("kernel.vector_mismatch", "static", vector["id"])
                continue
            predicate = reason["predicate"]
            operation = predicate["operation"]
            predicate_schema = next(
                item
                for item in meta["diagnostic_reason"]["predicate_schemas"]
                if item["operation"] == operation
            )
            input_types = predicate_schema.get("input_member_types")
            if (
                set(vector["input"]) != set(predicate_schema["input_members"])
                or not isinstance(input_types, dict)
                or set(vector["input"]) != set(input_types)
                or not all(
                    _consumer_b_value_matches(
                        vector["input"][name], input_types[name], ldb
                    )
                    for name in vector["input"]
                )
            ):
                refuse(
                    "kernel.vector_mismatch",
                    "static",
                    str(vector.get("id", "")),
                )
                continue
            if operation == "not-member":
                inventory = resolve(predicate["inventory_path"])
                if "member_field" in predicate:
                    inventory = [item[predicate["member_field"]] for item in inventory]
                matched = _consumer_b_scalar_key(vector["input"]["value"]) not in {
                    _consumer_b_scalar_key(item) for item in inventory
                }
            elif operation == "has-duplicate":
                values = vector["input"]["values"]
                keys = [_consumer_b_scalar_key(item) for item in values]
                matched = len(keys) != len(set(keys))
            elif operation == "greater-than":
                matched = vector["input"]["value"] > resolve(predicate["limit_path"])
            elif operation == "invalid-interval":
                matched = vector["input"]["minimum"] > vector["input"]["maximum"]
            elif operation == "not-equal":
                matched = _encoded(vector["input"]["actual"]) != _encoded(
                    vector["input"]["expected"]
                )
        output = (
            {
                "code": reason["diagnostic"],
                "matched": matched,
                "stage": reason["stage"],
            }
            if reason is not None
            else None
        )
        expected = {
            "code": vector["diagnostic"],
            "matched": vector["matched"],
            "stage": vector["stage"],
        }
        if output != expected:
            refuse("kernel.vector_mismatch", "static", vector["id"])
        else:
            assert isinstance(output, dict)
            diagnostic_projections.append(
                (
                    vector["id"],
                    vector["diagnostic"],
                    _identity("diagnostic-vector-projection-v2", output),
                )
            )
    for reason_id, reason in reasons.items():
        vectors = [
            vector for vector in diagnostic_vectors if vector.get("reason") == reason_id
        ]
        if not _consumer_b_reason_vectors_cover(ldb, reason, vectors, meta):
            refuse("kernel.vector_mismatch", "static", reason_id)

    package_coordinates = [(item["id"], item["version"]) for item in packages]
    if len(package_coordinates) != len(set(package_coordinates)):
        refuse("kernel.duplicate_identifier", "static", "language.packages")
    vector_ids = {item["id"] for item in valid_vectors}
    vectors_by_id = {item["id"]: item for item in valid_vectors}
    constructor_ids = {item["id"] for item in ldb["language"]["constructors"]}
    numeric_profiles = {
        item["id"] for item in ldb["language"]["quantity"]["numeric_policies"]
    }
    vector_sets_by_coordinate = {
        (vector_set["package_id"], vector_set["package_version"]): vector_set
        for vector_set in graph_vector_sets
    }
    for package in packages:
        exports = package["exports"]
        profiles = package["profiles"]
        vector_set = vector_sets_by_coordinate.get(
            (package["id"], package["version"]), {}
        )
        references_close = (
            set(vector_set.get("vectors", [])) <= vector_ids
            and vector_set.get("vector_definitions")
            == [vectors_by_id[vector_id] for vector_id in vector_set.get("vectors", [])]
            and set(exports["language_rules"]) <= set(rule_ids)
            and set(exports["diagnostics"]) <= set(ldb_codes)
            and set(profiles["numeric"]) <= numeric_profiles
            and all(item["constructor"] in constructor_ids for item in exports["types"])
        )
        if not references_close:
            refuse(
                "kernel.vector_mismatch",
                "static",
                f"language.packages.{package['id']}",
            )

    vector_law = next(law for law in laws if law["id"] == "kernel.vectors.closed")
    authorities = {"kernel": kernel, "language_bundle": ldb}
    reference_contracts_close = True
    for contract in vector_law["arguments"]["correlations"]:
        owners = _project(authorities, contract["owners"])
        targets = _project(authorities, contract["targets"])
        if set(contract) == {
            "equal_members",
            "owner_key_member",
            "owners",
            "target_key_member",
            "targets",
        }:
            target_rows = {
                target[contract["target_key_member"]]: target
                for target in targets
                if isinstance(target, dict) and contract["target_key_member"] in target
            }
            if len(target_rows) != len(targets) or any(
                not isinstance(owner, dict)
                or owner.get(contract["owner_key_member"]) not in target_rows
                or any(
                    owner.get(member)
                    != target_rows[owner[contract["owner_key_member"]]].get(member)
                    for member in contract["equal_members"]
                )
                for owner in owners
            ):
                reference_contracts_close = False
                break
            continue
        if set(contract) == {
            "alternatives",
            "owners",
            "references_member",
            "target_key_member",
            "targets",
        }:
            alternatives = contract["alternatives"]
            target_rows = {
                target[contract["target_key_member"]]: target
                for target in targets
                if isinstance(target, dict) and contract["target_key_member"] in target
            }
            if (
                not isinstance(alternatives, list)
                or not alternatives
                or not all(
                    isinstance(item, dict)
                    and set(item) == {"owner_member", "target_member"}
                    and all(
                        isinstance(item.get(member), str) and item[member]
                        for member in ("owner_member", "target_member")
                    )
                    for item in alternatives
                )
                or len(target_rows) != len(targets)
                or any(
                    not isinstance(owner, dict)
                    or not isinstance(owner.get(contract["references_member"]), list)
                    or any(
                        reference not in target_rows
                        or not any(
                            alternative["owner_member"] in owner
                            and alternative["target_member"] in target_rows[reference]
                            and owner[alternative["owner_member"]]
                            == target_rows[reference][alternative["target_member"]]
                            for alternative in alternatives
                        )
                        for reference in owner[contract["references_member"]]
                    )
                    for owner in owners
                )
            ):
                reference_contracts_close = False
                break
            continue
        target_values = {
            target[contract["target_key_member"]]: target.get(
                contract["target_value_member"]
            )
            for target in targets
            if isinstance(target, dict) and contract["target_key_member"] in target
        }
        for owner in owners:
            if not isinstance(owner, dict) or any(
                target_values.get(reference)
                != owner.get(contract["owner_value_member"])
                for reference in owner.get(contract["references_member"], [])
            ):
                reference_contracts_close = False
                break
    for contract in vector_law["arguments"]["equalities"]:
        if (
            not isinstance(contract, dict)
            or contract.get("mode") != "set"
            or not _consumer_b_path_is_declared(authorities, contract.get("left"))
        ):
            reference_contracts_close = False
            break
        if set(contract) == {"left", "mode", "right"}:
            if not _consumer_b_path_is_declared(authorities, contract["right"]):
                reference_contracts_close = False
                break
            right_values = _project(authorities, contract["right"])
        elif set(contract) == {
            "left",
            "mode",
            "profile",
            "right_template",
        }:
            right_values = _consumer_b_profiled_equality_values(authorities, contract)
            if right_values is None:
                reference_contracts_close = False
                break
        else:
            reference_contracts_close = False
            break
        try:
            if set(_project(authorities, contract["left"])) != set(right_values):
                reference_contracts_close = False
                break
        except TypeError:
            reference_contracts_close = False
            break
    for contract in vector_law["arguments"]["references"]:
        owners = _project(authorities, contract["owners"])
        if not _consumer_b_path_is_declared(authorities, contract["owners"]):
            reference_contracts_close = False
            break
        for owner in owners:
            if not isinstance(owner, dict):
                reference_contracts_close = False
                break
            for source, target in contract["targets"].items():
                if not _consumer_b_path_is_declared(
                    owner, source
                ) or not _consumer_b_path_is_declared(authorities, target):
                    reference_contracts_close = False
                    break
                target_values = _project(authorities, target)
                if any(value not in target_values for value in _project(owner, source)):
                    reference_contracts_close = False
                    break
    if not reference_contracts_close:
        refuse("kernel.vector_mismatch", "static", "language.packages")
    if semantic_projection_mismatch and not diagnostics:
        for index in range(len(packages)):
            refuse(
                "kernel.identity_mismatch",
                "ingress",
                f"language-bundle.language.packages.{index}.semantic_identity",
            )

    ordered = sorted(diagnostics, key=lambda item: (item[0], item[2], item[1]))
    truncated = len(ordered) > cap
    return {
        "admitted": not ordered,
        "kernel_identity": kernel.get("content_identity"),
        "language_bundle_identity": ldb.get("content_identity"),
        "law_ids": sorted(law_ids),
        "law_projections": law_projections,
        "rule_ids": sorted(rule_ids),
        "rule_projections": sorted(projections),
        "diagnostic_projections": sorted(diagnostic_projections),
        "diagnostics": ordered[:cap],
        "truncated": truncated,
    }


def _reidentify(kernel: dict[str, Any], ldb: dict[str, Any]) -> None:
    kernel["content_identity"] = _identity("schema-major-kernel-v2", kernel)
    graph_root = getattr(ldb, "root", None)
    if isinstance(ldb, LanguageBundleIndex) and isinstance(graph_root, dict):
        graph_root["kernel_identity"] = kernel["content_identity"]
        graph_root["content_identity"] = _identity(
            "language-definition-bundle-v2", graph_root
        )
        ldb.root_byte_size = len(_encoded(graph_root))
        ldb["kernel_identity"] = graph_root["kernel_identity"]
        ldb["content_identity"] = graph_root["content_identity"]
        return
    ldb["kernel_identity"] = kernel["content_identity"]
    ldb["content_identity"] = _identity("language-definition-bundle-v2", ldb)


def _graph_metrics(ldb: LanguageBundleIndex) -> dict[str, int]:
    dependencies = {
        (package["id"], package["version"]): {
            (dependency["id"], dependency["version"])
            for dependency in package["dependencies"]["required"]
        }
        for package in ldb.package_releases
    }
    depths: dict[tuple[str, str], int] = {}

    def depth_of(coordinate: tuple[str, str]) -> int:
        known = depths.get(coordinate)
        if known is not None:
            return known
        depth = 1 + max(
            (depth_of(dependency) for dependency in dependencies[coordinate]),
            default=0,
        )
        depths[coordinate] = depth
        return depth

    return {
        "max_ldb_root_bytes": ldb.root_byte_size,
        "max_ldb_child_bytes": max(*ldb.package_byte_sizes, *ldb.vector_set_byte_sizes),
        "max_ldb_package_bytes": max(
            package_size + vector_size
            for package_size, vector_size in zip(
                ldb.package_byte_sizes,
                ldb.vector_set_byte_sizes,
                strict=True,
            )
        ),
        "max_ldb_total_bytes": ldb.root_byte_size
        + sum(ldb.package_byte_sizes)
        + sum(ldb.vector_set_byte_sizes),
        "max_ldb_package_count": len(ldb.package_releases),
        "max_ldb_package_member_count": 2,
        "max_ldb_dependency_depth": max(map(depth_of, dependencies)),
        "max_ldb_dependency_steps": sum(map(len, dependencies.values())),
        "max_ldb_admission_work": _work(ldb.root)
        + sum(_work(package) for package in ldb.package_releases)
        + sum(_work(vector_set) for vector_set in ldb.package_conformance_vector_sets),
    }


def _consumer_b_evaluate_structured_value_vector(
    vector: dict[str, Any],
    *,
    nominal_types: list[dict[str, Any]],
    kernel: dict[str, Any],
    resource_limit: int,
) -> dict[str, Any]:
    """Execute a structured-value vector without production value helpers."""
    constructors = {
        constructor["id"]: constructor
        for package in nominal_types
        for entry in package.get("semantic_closure", [])
        if entry.get("authority_path") == "language.constructors"
        for constructor in entry.get("definitions", [])
    }
    definitions = {
        (package["id"], package["version"], exported["id"]): {
            **exported,
            "package": package["id"],
            "version": package["version"],
        }
        for package in nominal_types
        for exported in package.get("exports", {}).get("types", [])
    }
    for package in nominal_types:
        for entry in package.get("semantic_closure", []):
            if entry.get("authority_path") != "language.nominal_types":
                continue
            for definition in entry.get("definitions", []):
                key = (
                    definition["package"],
                    definition["version"],
                    definition["id"],
                )
                if key not in definitions:
                    raise AssertionError("nominal definition has no exported type")
                definitions[key] = definition
    structured_operations = {
        operation["id"]: operation
        for package in nominal_types
        for entry in package.get("semantic_closure", [])
        if entry.get("authority_path") == "language.structured_operations"
        for operation in entry.get("definitions", [])
    }
    typed_profiles = [
        profile
        for package in nominal_types
        for entry in package.get("semantic_closure", [])
        if entry.get("authority_path") == "language.literal_typing_profiles"
        for profile in entry.get("definitions", [])
        if profile.get("source_kind") == "typed-envelope"
        and profile.get("value_kind") == "nominal-structured"
    ]
    runtime = kernel["meta_format"]["runtime_program"]
    typed_contract = kernel["meta_format"]["literal_typing"]["typed_envelope_profile"]
    if len(typed_profiles) != 1 or typed_profiles[0] != {
        "admission": typed_contract["admission"],
        "id": typed_contract["id"],
        "source_kind": "typed-envelope",
        "value_kind": typed_contract["value_kind"],
    }:
        raise AssertionError("typed-envelope authority is incomplete")
    type_member = typed_contract["type_member"]
    value_member = typed_contract["value_member"]
    envelope_members = set(typed_contract["admission"]["envelope_members"])
    value_nodes = {
        node["semantics"]["operator"]: node
        for node in runtime["nodes"]
        if node["semantics"]["operator"]
        in {"bounded-lookup", "canonical-equal", "collection-is-empty"}
    }
    inp = vector["input"]
    requested = inp.get("limit")
    remaining = [
        min(resource_limit, requested)
        if isinstance(requested, int)
        and not isinstance(requested, bool)
        and requested > 0
        else resource_limit
    ]

    class Refusal(Exception):
        def __init__(self, code: str, pointer: str):
            self.code = code
            self.pointer = pointer

    def type_key(type_expression: Any) -> tuple[str, str, str] | None:
        if not isinstance(type_expression, dict):
            return None
        contract = typed_profiles[0]["admission"]["nominal_type_reference"]
        coordinate_members = contract["coordinate_members"]
        kind_member = contract["optional_kind_member"]
        expected = set(coordinate_members)
        if kind_member in type_expression:
            expected.add(kind_member)
            if type_expression[kind_member] != contract["optional_kind_value"]:
                return None
        values = tuple(type_expression.get(name) for name in coordinate_members)
        if set(type_expression) == expected and all(
            isinstance(value, str) and value for value in values
        ):
            return cast(tuple[str, str, str], values)
        return None

    def child(pointer, member):
        encoded = str(member).replace("~", "~0").replace("/", "~1")
        return f"{pointer}/{encoded}"

    def canonical_type(type_expression):
        nominal = type_key(type_expression)
        if nominal is not None:
            package, version, type_id = nominal
            return {"id": type_id, "package": package, "version": version}
        if not isinstance(type_expression, dict):
            if isinstance(type_expression, list):
                return [canonical_type(item) for item in type_expression]
            return type_expression
        return {
            member: canonical_type(value) for member, value in type_expression.items()
        }

    def structural_contract(type_expression, pointer):
        constructor = None
        nominal = type_key(type_expression)
        if nominal is not None:
            definition = definitions.get(nominal)
            constructor = (
                constructors.get(definition.get("constructor"))
                if isinstance(definition, dict)
                else None
            )
            if (
                not isinstance(definition, dict)
                or constructor is None
                or "definition" not in definition
            ):
                raise Refusal("language.structured_value_type_mismatch", pointer)
            type_expression = definition["definition"]
        if not isinstance(type_expression, dict):
            raise Refusal("language.structured_value_type_mismatch", pointer)
        if constructor is None:
            matches = [
                candidate
                for candidate in constructors.values()
                if candidate.get("value_rule", {}).get("definition_kind")
                == type_expression.get("kind")
            ]
            if len(matches) != 1:
                raise Refusal("language.structured_value_type_mismatch", pointer)
            constructor = matches[0]
        return type_expression, constructor, constructor["value_rule"]

    def operation_law(constructor, operator, pointer):
        matches = [
            operation
            for operation in structured_operations.values()
            if operation.get("owner_constructor") == constructor.get("id")
            and operation.get("law", {}).get("operator") == operator
        ]
        node = value_nodes.get(operator)
        charge = (
            node.get("resource_charge", {}).get("amount")
            if isinstance(node, dict)
            else None
        )
        bound = (
            matches[0].get("resource_bounds", {}).get("max_steps")
            if len(matches) == 1
            else None
        )
        if (
            len(matches) != 1
            or not isinstance(node, dict)
            or not isinstance(charge, int)
            or isinstance(charge, bool)
            or not isinstance(bound, int)
            or isinstance(bound, bool)
            or charge > bound
        ):
            raise Refusal("language.structured_value_type_mismatch", pointer)
        return matches[0]["law"]

    def validate(type_expression, value, pointer):
        charge = typed_profiles[0]["admission"]["resource_charge_per_node"]
        for _ in range(charge):
            if remaining[0] < 1:
                raise Refusal("language.structured_value_resource_exhausted", pointer)
            remaining[0] -= 1
        nominal = type_key(type_expression)
        if nominal is not None:
            definition = definitions.get(nominal)
            if definition is None:
                raise Refusal("language.structured_value_type_mismatch", pointer)
            constructor = constructors.get(definition.get("constructor"))
            if constructor is None:
                raise Refusal("language.structured_value_type_mismatch", pointer)
            if "definition" in definition:
                return validate(definition["definition"], value, pointer)
            value_rule = constructor.get("value_rule", {})
            if (
                value_rule.get("operator") != "exact-integer"
                or not isinstance(value, int)
                or isinstance(value, bool)
                or not value_rule["minimum"] <= value <= value_rule["maximum"]
            ):
                raise Refusal("language.structured_value_type_mismatch", pointer)
            return value
        if not isinstance(type_expression, dict):
            raise Refusal("language.structured_value_type_mismatch", pointer)
        kind = type_expression.get("kind")
        rules = [
            constructor["value_rule"]
            for constructor in constructors.values()
            if constructor.get("value_rule", {}).get("definition_kind") == kind
        ]
        if len(rules) != 1:
            raise Refusal("language.structured_value_type_mismatch", pointer)
        rule = rules[0]
        operator = rule.get("operator")
        if operator == "enum-member":
            if not isinstance(value, str) or value not in type_expression.get(
                rule["members_member"], []
            ):
                raise Refusal("language.structured_value_unknown_enum", pointer)
            return value
        if operator == "closed-record":
            fields = type_expression.get(rule["fields_member"])
            if not isinstance(fields, list) or not isinstance(value, dict):
                raise Refusal("language.structured_value_type_mismatch", pointer)
            name_member = rule["field_name_member"]
            type_member = rule["field_type_member"]
            names = [
                field.get(name_member) for field in fields if isinstance(field, dict)
            ]
            missing = [name for name in names if name not in value]
            extra = sorted(
                (name for name in value if name not in names),
                key=lambda name: str(name).encode("utf-8"),
            )
            if missing or extra:
                raise Refusal(
                    "language.structured_value_record_member_mismatch",
                    child(pointer, (missing or extra)[0]),
                )
            return {
                field[name_member]: validate(
                    field[type_member],
                    value[field[name_member]],
                    child(pointer, field[name_member]),
                )
                for field in fields
            }
        if operator == "bounded-list":
            maximum = type_expression.get(rule["maximum_length_member"])
            if (
                not isinstance(value, list)
                or not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or len(value) > maximum
            ):
                raise Refusal("language.structured_value_type_mismatch", pointer)
            return [
                validate(
                    type_expression.get(rule["element_member"]),
                    item,
                    child(pointer, index),
                )
                for index, item in enumerate(value)
            ]
        if operator == "canonical-ref-key":
            target_member = rule["target_member"]
            pattern_member = rule["key_pattern_member"]
            value_members = rule["value_members"]
            if (
                type_key(type_expression.get(target_member)) is None
                or not isinstance(type_expression.get(pattern_member), str)
                or not type_expression[pattern_member]
                or not isinstance(value, dict)
                or set(value) != set(value_members)
                or len(value_members) != 1
                or not isinstance(value.get(value_members[0]), str)
            ):
                raise Refusal("language.structured_value_type_mismatch", pointer)
            try:
                key_matches = (
                    re.fullmatch(
                        type_expression[pattern_member], value[value_members[0]]
                    )
                    is not None
                )
            except re.error as error:
                raise AssertionError("admitted Ref key pattern is invalid") from error
            if not key_matches:
                raise Refusal("language.structured_value_type_mismatch", pointer)
            return {value_members[0]: value[value_members[0]]}
        raise Refusal("language.structured_value_type_mismatch", pointer)

    def admit(envelope):
        if not isinstance(envelope, dict) or set(envelope) != envelope_members:
            raise Refusal("language.structured_value_type_mismatch", "")
        return {
            type_member: canonical_type(envelope[type_member]),
            value_member: validate(
                envelope[type_member], envelope[value_member], f"/{value_member}"
            ),
        }

    try:
        left = admit(inp["left"])
        if inp["action"] == "admit":
            result = left
        elif inp["action"] == "equal":
            right = admit(inp["right"])
            if _encoded(left[type_member]) != _encoded(right[type_member]):
                raise Refusal("language.structured_value_type_mismatch", "/right/type")
            _definition, constructor, _rule = structural_contract(
                left[type_member], "/left/type"
            )
            result_contract = value_nodes["canonical-equal"]["result"]["typing"][
                "contract"
            ]
            if (
                operation_law(constructor, "canonical-equal", "/left/type").get(
                    "result_contract"
                )
                != result_contract
            ):
                raise Refusal("language.structured_value_type_mismatch", "/left/type")
            result = {
                type_member: runtime["fixed_value_contracts"][result_contract]["type"],
                value_member: _encoded(left[value_member])
                == _encoded(right[value_member]),
            }
        elif inp["action"] == "lookup":
            type_expression, constructor, lookup_rule = structural_contract(
                left[type_member], "/type"
            )
            law = operation_law(constructor, "bounded-lookup", "/type")
            if law.get("refusal_signal") != "structured-lookup-out-of-range":
                raise Refusal("language.structured_value_type_mismatch", "/type")
            if law.get("selector") == "static-field" and isinstance(inp["key"], str):
                fields = type_expression[lookup_rule["fields_member"]]
                name_member = lookup_rule["field_name_member"]
                field_type_member = lookup_rule["field_type_member"]
                field = next(
                    (field for field in fields if field[name_member] == inp["key"]),
                    None,
                )
                if field is None:
                    raise Refusal("runtime.structured_lookup_out_of_range", "/key")
                result = {
                    type_member: canonical_type(field[field_type_member]),
                    value_member: left[value_member][inp["key"]],
                }
            elif law.get("selector") == "local-index" and isinstance(inp["key"], int):
                if not 0 <= inp["key"] < len(left[value_member]):
                    raise Refusal("runtime.structured_lookup_out_of_range", "/key")
                result = {
                    type_member: canonical_type(
                        type_expression[lookup_rule["element_member"]]
                    ),
                    value_member: left[value_member][inp["key"]],
                }
            else:
                raise Refusal("language.structured_value_type_mismatch", "/key")
        elif inp["action"] == "is-empty":
            type_expression, constructor, list_rule = structural_contract(
                left[type_member], "/type"
            )
            result_contract = value_nodes["collection-is-empty"]["result"]["typing"][
                "contract"
            ]
            law = operation_law(constructor, "collection-is-empty", "/type")
            if (
                list_rule.get("operator") != "bounded-list"
                or law.get("result_contract") != result_contract
                or not isinstance(left[value_member], list)
            ):
                raise Refusal("language.structured_value_type_mismatch", "/type")
            result = {
                type_member: runtime["fixed_value_contracts"][result_contract]["type"],
                value_member: not left[value_member],
            }
        else:
            raise AssertionError("unknown structured vector action")
    except Refusal as refusal:
        return {
            "code": refusal.code,
            "outcome": "refused",
            "pointer": refusal.pointer,
            "type": None,
            "value": None,
        }
    return {
        "code": None,
        "outcome": "admitted",
        "pointer": "",
        "type": result[type_member],
        "value": result[value_member],
    }


__all__ = [
    "_consumer_b_meta_validate_schema",
    "Any",
    "LanguageBundleGraph",
    "LanguageBundleIndex",
    "_CONSUMER_B_PACKAGE_VECTOR_CATEGORIES",
    "_CONSUMER_B_PACKAGE_VECTOR_KIND_MEMBERS",
    "_SUPPORTED_KERNEL_IDENTITY",
    "_bind_package_vector_set",
    "_consumer_b",
    "_consumer_b_assignment_policy_is_total",
    "_consumer_b_canonical_contract_supported",
    "_consumer_b_canonical_equal",
    "_consumer_b_closed_json_schema",
    "_consumer_b_contract_fits_schema",
    "_consumer_b_contract_kind",
    "_consumer_b_contract_path",
    "_consumer_b_definition_is_closed",
    "_consumer_b_duplicate_subjects",
    "_consumer_b_embedded_artifact_bindings_are_closed",
    "_consumer_b_evaluate_structured_value_vector",
    "_consumer_b_exact_path",
    "_consumer_b_fact_contract_at_path",
    "_consumer_b_fact_contract_path_is_declared",
    "_consumer_b_fact_is_closed",
    "_consumer_b_fact_schemas",
    "_consumer_b_kind",
    "_consumer_b_language_definitions_are_closed",
    "_consumer_b_ldb_is_closed",
    "_consumer_b_literal_typing_profiles_are_closed",
    "_consumer_b_model_program_vector_is_closed",
    "_consumer_b_operation_composition_subjects",
    "_consumer_b_package_evidence_vector_header_is_closed",
    "_consumer_b_package_evidence_vectors_are_closed",
    "_consumer_b_package_is_closed",
    "_consumer_b_package_semantic_closure_is_closed",
    "_consumer_b_package_semantic_projections_are_exact",
    "_consumer_b_package_vector_contract_is_closed",
    "_consumer_b_package_vector_set_is_closed",
    "_consumer_b_path_is_declared",
    "_consumer_b_profiled_equality_values",
    "_consumer_b_reason_is_closed",
    "_consumer_b_reason_operands_close",
    "_consumer_b_reason_vectors_cover",
    "_consumer_b_relation_paths_are_typed",
    "_consumer_b_relation_recipes_are_closed",
    "_consumer_b_resolution_contract_is_closed",
    "_consumer_b_rule_is_closed",
    "_consumer_b_runtime_authority_is_closed",
    "_consumer_b_runtime_projection_is_closed",
    "_consumer_b_scalar_key",
    "_consumer_b_schema_path",
    "_consumer_b_semantic_item_contract",
    "_consumer_b_signed_int64",
    "_consumer_b_template_admission_is_closed",
    "_consumer_b_value_matches",
    "_consumer_b_vector_header_is_closed",
    "_declared_identity_domain",
    "_encoded",
    "_graph_metrics",
    "_identity",
    "_identity_from_kernel",
    "_owned_vector",
    "_package_vector_set",
    "_project",
    "_reidentify",
    "_reidentify_package_release",
    "_reidentify_package_vector_set",
    "_safe_identity",
    "_shape",
    "_validate_canonical",
    "_work",
    "cast",
    "deepcopy",
    "derive_language_index",
    "hashlib",
    "json",
    "jsonschema",
    "pytest",
    "re",
]
