"""Independent bootstrap and mutation conformance for the permanent authority.

Consumer B below intentionally imports no production bootstrap or canonical
code.  Agreement is over public artifact bytes and observable inventories,
not shared helper behavior.
"""

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, cast

import jsonschema
import pytest

import gda_balancing.schema2.bootstrap as production_bootstrap
from gda_balancing.schema2.authority import authority_set
from gda_balancing.schema2.authority_graph import (
    LanguageBundleGraph,
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.schema2.bootstrap import admit_authorities

_SUPPORTED_KERNEL_IDENTITY = (
    "sha256:165ff5ccd3fa7aadecde63ba29be9f1907a3a7ec2b88825fd284de63339a5681"
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
    runtime_closure = [
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] in runtime_paths
    ]
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
    "runtime-scenario": {
        "expect_members",
        "id",
        "input_members",
        "required_members",
        "rng_draw_members",
        "state_value_members",
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
        "runtime-scenario": {
            "category",
            "expect",
            "id",
            "input",
            "kind",
            "operation",
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
        and kinds["runtime-scenario"].get("input_members")
        == ["seed", "state_names", "values"]
        and kinds["runtime-scenario"].get("expect_members")
        == ["outcome", "rng_draws", "state_after"]
        and kinds["runtime-scenario"].get("rng_draw_members")
        == ["candidate_hex", "index", "stream", "value"]
        and kinds["runtime-scenario"].get("state_value_members") == ["name", "value"]
    )


def _consumer_b_canonical_equal(left: Any, right: Any) -> bool:
    try:
        return _encoded(left) == _encoded(right)
    except (TypeError, ValueError, UnicodeEncodeError):
        return False


def _consumer_b_signed_int64(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and -(2**63) <= value <= 2**63 - 1
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


def _consumer_b_package_evidence_vectors_are_closed(
    package: dict[str, Any],
    vector_set: dict[str, Any],
    contract: Any,
) -> bool:
    if not _consumer_b_package_vector_contract_is_closed(contract):
        return False
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
        if operation.get("operation_kind") != "event-program":
            return False
        inp = vector.get("input")
        expect = vector.get("expect")
        if (
            not isinstance(inp, dict)
            or set(inp) != set(kind["input_members"])
            or not _consumer_b_signed_int64(inp.get("seed"))
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
            for item in operation.get("inputs", [])
            if isinstance(item, dict)
        ]
        if (
            not all(
                isinstance(item, dict)
                and set(item) == {"name", "value"}
                and isinstance(item.get("name"), str)
                and item["name"]
                and _consumer_b_signed_int64(item.get("value"))
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
                and _consumer_b_signed_int64(item.get("value"))
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
            and len(item["candidate_hex"]) == 16
            and all(
                character in "0123456789abcdef" for character in item["candidate_hex"]
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
        outcomes = operation.get("outcomes")
        if not isinstance(outcomes, list) or expect["outcome"] not in {
            item.get("id") for item in outcomes if isinstance(item, dict)
        }:
            return False

    operation_evidence_ids = {
        vector["id"]
        for vector in vectors
        if isinstance(vector, dict)
        and vector.get("kind") in {"operation-contract", "runtime-scenario"}
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
        != {"domain", "path_inventory_member", "source_member", "path_member"}
        or semantic_projection.get("source_member") != "semantic_closure"
        or semantic_projection.get("path_member") != "authority_path"
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
    runtime_closure = [
        entry for entry in closure if entry["authority_path"] in set(runtime_paths)
    ]
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
        jsonschema.Draft202012Validator.check_schema(value)
    except jsonschema.SchemaError:
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
    if kind in {"closed-object", "closed-int64-interval"} or (
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
        or set(profile) != {"outputs", "collections", "seeds", "edges"}
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
            ],
            "match": "canonical-equality",
            "cardinality": "at-least-one",
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
            ],
            "match": "canonical-equality",
            "cardinality": "at-least-one",
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
    if (
        not isinstance(outputs, list)
        or not isinstance(collections, list)
        or not isinstance(seeds, list)
        or not isinstance(edges, list)
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
        if (
            not isinstance(collection, dict)
            or set(collection) != {"id", "source", "output_member", "output_shape"}
            or not isinstance(collection.get("id"), str)
            or not collection["id"]
            or not isinstance(collection.get("source"), dict)
            or collection.get("output_shape") not in allowed_shapes
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
        expected = {"operator", "collection", "declaration_package_path"}
        expected |= {"declaration_path", "target_path", "same_package"}
        if (
            set(seed) != expected
            or seed.get("collection") not in collection_set
            or not valid_path(seed.get("declaration_package_path"))
            or not isinstance(seed.get("same_package"), bool)
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
        }
        or edge.get("operator") not in edges_allowed
        or edge.get("source_collection") not in collection_set
        or edge.get("target_collection") not in collection_set
        or not valid_path(edge.get("source_path"), True)
        or not valid_path(edge.get("target_path"), True)
        or not isinstance(edge.get("same_package"), bool)
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
        declaration_kind = fact_kind(fact_value(seed["declaration_path"]))
        package_kind = fact_kind(fact_value(seed["declaration_package_path"]))
        target_kind = selected_kind(
            shapes[seed["collection"]],
            seed["target_path"],
        )
        if (
            declaration_kind is None
            or declaration_kind != target_kind
            or package_kind != "string"
        ):
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
        "member_roles",
        "resource_diagnostic",
        "structural_diagnostic",
    }:
        return False
    roles = profile.get("member_roles")
    judgments = profile.get("judgments")
    role_names = {row.get("role") for row in roles or [] if isinstance(row, dict)}
    schema_kinds = {
        row.get("artifact_kind")
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for row in language.get(collection, [])
        if isinstance(row, dict)
    }
    if (
        not isinstance(roles, list)
        or not roles
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
        or profile.get("max_steps_path") != accounting["limit_path"]
        or profile.get("resource_diagnostic") != accounting["exhaustion_diagnostic"]
        or profile.get("resource_diagnostic") not in diagnostics
        or profile.get("structural_diagnostic") not in diagnostics
    ):
        return False
    found, limit = _consumer_b_exact_path(ldb, profile["max_steps_path"])
    if not found or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return False

    judgment_ids: set[str] = set()
    used_operations: set[str] = set()
    used_primitives: set[str] = set()
    role_operations: set[tuple[str, str]] = set()
    produced: set[str] = set()
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
        chain = lowering.get("rule_chain")
        equalities = lowering.get("output_equalities")
        profile_id = lowering.get("resolution_profile")
        initial_kind = lowering.get("initial_fact_kind")
        if not isinstance(profile_id, str) or not isinstance(initial_kind, str):
            return False
        profile = profiles_by_id.get(profile_id)
        initial_fields = fact_schemas.get(initial_kind)
        if (
            not isinstance(chain, list)
            or not chain
            or not isinstance(equalities, list)
            or not all(isinstance(item, dict) for item in equalities)
            or not isinstance(profile, dict)
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
        if not isinstance(fields, dict) or not _consumer_b_runtime_projection_is_closed(
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
                    left_kind in {"array", "object"} and left_contract != right_contract
                )
            ):
                return False
            pairs.append((tuple(left), tuple(right)))
        if len(pairs) != len(set(pairs)):
            return False
        if not any(left == (profile["symbol_fact_member"],) for left, _ in pairs):
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
                )
            )
            or (binding_kind == "internal" and (accesses or result is not False))
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
        "source_kinds": ["integer"],
        "match_members": [
            "type",
            "representation",
            "kind",
            "unit",
            "domain",
            "numeric_policy",
        ],
        "range_members": {"maximum": "maximum", "minimum": "minimum"},
        "ownership": "profile-owner-must-own-exact-type-export",
        "formal_closure": "at-least-one-exact-operation-value-contract",
        "overlap_policy": "refuse-overlapping-ranges-per-source-and-match-contract",
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
    for profile in profiles:
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
    for index, left in enumerate(cast(list[dict[str, Any]], profiles)):
        for right in cast(list[dict[str, Any]], profiles)[index + 1 :]:
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


def _consumer_b_runtime_authority_is_closed(
    kernel: dict[str, Any], ldb: dict[str, Any]
) -> bool:
    runtime = kernel.get("meta_format", {}).get("runtime_program")
    if (
        not isinstance(runtime, dict)
        or set(runtime)
        != {
            "closed",
            "version",
            "evaluation_order",
            "fixed_value_contracts",
            "expression_nodes",
            "effect_nodes",
            "control_nodes",
            "nodes",
            "numeric",
            "named_rng",
            "event_atomicity",
            "outcome_contract",
            "invocation_contract",
            "vectors",
        }
        or runtime.get("closed") is not True
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
                        in {"same-as-references", "literal-profile"}
                        and (
                            not isinstance(
                                node["result"]["typing"].get("members"), list
                            )
                            or not node["result"]["typing"]["members"]
                        )
                    )
                    or node["result"]["typing"].get("kind")
                    not in {"fixed", "same-as-references", "literal-profile"}
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
        if profile.get("evaluation") == runtime.get("version") and (
            profile.get("runtime_program_version") != runtime.get("version")
            or profile.get("numeric_law") != runtime["numeric"]["id"]
            or profile.get("rng", {}).get("algorithm") != rng["algorithm"]
            or profile.get("budget_scopes")
            != {
                "operation_max_steps": "per-event",
                "runtime_max_steps": "per-run",
            }
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
    nodes_by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}

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
        for instruction in body:
            if not isinstance(instruction, dict):
                return None
            node = nodes_by_id.get(instruction.get("node"))
            if not isinstance(node, dict) or set(instruction) != set(
                node["required_members"]
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
                formal_ports = [
                    row.get("id")
                    for row in invoked.get("inputs", [])
                    if isinstance(row, dict)
                ]
                arguments = instruction.get("arguments")
                if (
                    not isinstance(arguments, list)
                    or [row.get("port") for row in arguments] != formal_ports
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

        return actual.get("type") == formal.get("type") and all(
            canonically_equal(actual.get(member), formal.get(member))
            for member in (
                "representation",
                "kind",
                "unit",
                "domain",
                "numeric_policy",
            )
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

        for instruction_index, instruction in enumerate(body):
            if not isinstance(instruction, dict):
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
                node = node_definitions.get(instruction.get("node"))
                if not isinstance(node, dict):
                    found.add(subject(coordinate, str(instruction_index), "node"))
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
                    if kind == "same-value-contract" and not shared_contracts(resolved):
                        found.add(subject(coordinate, str(instruction_index), "typing"))
                        return None
                    if kind == "fixed-value-contract":
                        expected = fixed_value_contracts.get(constraint.get("contract"))
                        if not isinstance(expected, dict) or any(
                            sum(
                                value_contract_matches(candidate, expected)
                                for candidate in candidates
                            )
                            != 1
                            for candidates in resolved
                        ):
                            found.add(
                                subject(coordinate, str(instruction_index), "typing")
                            )
                            return None
                    if kind == "runtime-numeric" and any(
                        sum(
                            candidate.get("numeric_policy") in runtime_numeric_policies
                            for candidate in candidates
                        )
                        != 1
                        for candidates in resolved
                    ):
                        found.add(subject(coordinate, str(instruction_index), "typing"))
                        return None
                    if kind == "writable-port" and any(
                        not isinstance(instruction.get(member), str)
                        or instruction[member] not in parent_ports
                        or parent_ports[instruction[member]].get("access")
                        not in {"read-write", "write"}
                        for member in members
                    ):
                        found.add(subject(coordinate, str(instruction_index), "typing"))
                        return None
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
                    if kind == "fixed":
                        contract = fixed_value_contracts.get(typing.get("contract"))
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
    meta = kernel.get("meta_format")
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
    composition_subjects = _consumer_b_operation_composition_subjects(kernel, ldb)
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
                    diagnostic_catalog_matches_vectors
                    and not _consumer_b_package_evidence_vectors_are_closed(
                        package, vector_set, package_vector_contract
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
    if not _consumer_b_language_definitions_are_closed(ldb, meta):
        refuse("kernel.vector_mismatch", "static", "language.definitions")
    if not _consumer_b_assignment_policy_is_total(ldb):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.definitions.assignment-policy",
        )
    if not _consumer_b_literal_typing_profiles_are_closed(kernel, ldb):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.literal-typing-profiles",
        )
    for composition_subject in composition_subjects:
        refuse("kernel.vector_mismatch", "static", composition_subject)
    if not _consumer_b_runtime_authority_is_closed(kernel, ldb):
        refuse("kernel.vector_mismatch", "static", "language.runtime")
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


def _consumer_a(kernel: dict[str, Any], ldb: dict[str, Any]) -> dict[str, Any]:
    result = admit_authorities(kernel, ldb)
    return {
        "admitted": result.admitted,
        "kernel_identity": result.kernel_identity,
        "language_bundle_identity": result.language_bundle_identity,
        "law_ids": list(result.law_ids),
        "law_projections": list(result.law_projections),
        "rule_ids": list(result.rule_ids),
        "rule_projections": list(result.rule_projections),
        "diagnostic_projections": list(result.diagnostic_projections),
        "diagnostics": [
            (item.stage, item.code, item.subject) for item in result.diagnostics
        ],
        "truncated": result.truncated,
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


def _refresh_package_closure_and_reidentify(ldb: LanguageBundleIndex) -> None:
    kernel = authority_set()["kernel"]
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]

    def path_values(root: Any, dotted: str) -> list[Any]:
        values = [root]
        for segment in dotted.split("."):
            selected: list[Any] = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    continue
                child = value[segment]
                selected.extend(child if isinstance(child, list) else [child])
            values = selected
        return values

    for package in ldb["language"]["packages"]:
        for entry, projection in zip(
            package["semantic_closure"], projections, strict=True
        ):
            definitions = path_values(ldb, entry["authority_path"])
            owners = path_values(package, projection["owners_path"])
            key_member = projection["key_member"]
            entry["definitions"] = deepcopy(
                [
                    definition
                    for definition in definitions
                    if (
                        definition.get(key_member)
                        if key_member is not None and isinstance(definition, dict)
                        else definition
                    )
                    in owners
                ]
            )
        _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)


def _reidentify_graph_root(ldb: LanguageBundleIndex) -> None:
    graph_root = getattr(ldb, "root", None)
    if isinstance(graph_root, dict):
        packages = deepcopy(ldb["language"]["packages"])
        vector_sets_by_coordinate = {
            (vector_set["package_id"], vector_set["package_version"]): deepcopy(
                vector_set
            )
            for vector_set in ldb.package_conformance_vector_sets
        }
        vector_sets = []
        for package in packages:
            coordinate = (package["id"], package["version"])
            vector_set = vector_sets_by_coordinate.get(coordinate)
            if vector_set is None:
                vector_set = {
                    "artifact_kind": "package-conformance-vector-set",
                    "content_identity": "",
                    "package_id": package["id"],
                    "package_version": package["version"],
                    "vector_definitions": [],
                    "vectors": [],
                }
                _bind_package_vector_set(package, vector_set)
            vector_sets.append(vector_set)
        members = sorted(
            zip(packages, vector_sets, strict=True),
            key=lambda member: _encoded([member[0]["id"], member[0]["version"]]),
        )
        packages = [package for package, _vector_set in members]
        vector_sets = [vector_set for _package, vector_set in members]
        package_sizes = [len(_encoded(package)) for package in packages]
        vector_set_sizes = [len(_encoded(vector_set)) for vector_set in vector_sets]
        graph_root["resources"] = deepcopy(ldb["resources"])
        graph_root["package_descriptors"] = [
            {
                "artifact_kind": package["artifact_kind"],
                "byte_size": size,
                "content_identity": package["content_identity"],
                "id": package["id"],
                "version": package["version"],
            }
            for package, size in zip(packages, package_sizes, strict=True)
        ]
        graph_root["content_identity"] = _identity(
            "language-definition-bundle-v2", graph_root
        )
        ldb.root = deepcopy(graph_root)
        ldb.package_releases = packages
        ldb.package_conformance_vector_sets = vector_sets
        ldb.root_byte_size = len(_encoded(graph_root))
        ldb.package_byte_sizes = tuple(package_sizes)
        ldb.vector_set_byte_sizes = tuple(vector_set_sizes)
        rebuilt = derive_language_index(
            graph_root,
            packages,
            vector_sets,
            authority_set()["kernel"]["admission"]["required_language_members"],
            root_byte_size=ldb.root_byte_size,
            package_byte_sizes=package_sizes,
            vector_set_byte_sizes=vector_set_sizes,
            descriptor_order=authority_set()["kernel"]["meta_format"][
                "language_bundle"
            ]["package_descriptor"]["canonical_order"],
        )
        ldb.root = deepcopy(rebuilt.root)
        ldb.package_releases = deepcopy(rebuilt.package_releases)
        ldb.package_conformance_vector_sets = deepcopy(
            rebuilt.package_conformance_vector_sets
        )
        ldb.root_byte_size = rebuilt.root_byte_size
        ldb.package_byte_sizes = rebuilt.package_byte_sizes
        ldb.vector_set_byte_sizes = rebuilt.vector_set_byte_sizes
        ldb.clear()
        ldb.update(dict(rebuilt))
        return
    ldb["content_identity"] = _identity("language-definition-bundle-v2", ldb)


def test_two_independent_consumers_admit_the_exact_authority_and_inventories():
    authority = authority_set()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is True
    assert first["law_ids"]
    assert first["rule_ids"] == ["quantity.declare", "quantity.lower"]
    assert ldb["language"]["model_source_schema_versions"] == ["2.0.0"]


@pytest.mark.parametrize(
    "mutation",
    (
        "identity-only",
        "reidentified-specification",
        "artifact-schema",
    ),
)
def test_two_consumers_refuse_unilateral_embedded_artifact_binding_drift(mutation):
    authority = authority_set()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    schemas = {
        entry["artifact_kind"]: entry["schema"]
        for entry in ldb["language"]["artifact_wire_schemas"]
    }
    refusal_schema = schemas["migration-refusal-report"]
    properties = refusal_schema["properties"]
    if mutation == "identity-only":
        properties["converter_identity"]["const"] = "sha256:" + "0" * 64
    elif mutation == "reidentified-specification":
        specification = properties["converter_specification"]["const"]
        specification["mapping_rules"][0]["report_mapping"] = "unilateral drift"
        specification["content_identity"] = _identity(
            "source-converter-specification-v1", specification
        )
        properties["converter_identity"]["const"] = specification["content_identity"]
    else:
        schemas["source-converter-specification"]["properties"]["mapping_rules"][
            "minItems"
        ] = 5
    _reidentify(kernel, ldb)

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "ingress",
        "kernel.identity_mismatch",
        "language-bundle.admitted-index",
    ) in first["diagnostics"]


def test_two_consumers_admit_reidentified_nested_integer_literal():
    authority = authority_set()
    ldb = authority["language_bundle"]
    cast_operation = next(
        operation
        for operation in ldb["language"]["operations"]
        if operation["id"] == "game.combat.cast-v1"
    )
    spend_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "spend-resource"
    )
    cost = next(
        argument for argument in spend_call["arguments"] if argument["port"] == "cost"
    )
    cost["operand"] = {"kind": "literal", "literal": 8}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


@pytest.mark.parametrize(
    "mutation",
    (
        "relation-missing-path",
        "relation-wrong-result-type",
        "projection-missing-path",
        "projection-wrong-result-type",
        "scalar-routing-drift",
    ),
)
def test_two_consumers_refuse_reidentified_authority_paths_without_typed_closure(
    mutation,
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    profile = ldb["language"]["resolution_profiles"][0]
    lowering = ldb["language"]["model_lowerings"][0]
    if mutation.startswith("relation"):
        recipe = next(
            item for item in profile["relation_recipes"] if item["id"] == "imports"
        )
        alias = next(item for item in recipe["fields"] if item["name"] == "alias")
        alias["term"]["path"] = (
            ["missing_member"] if mutation == "relation-missing-path" else []
        )
    elif mutation.startswith("projection"):
        seed = next(
            item
            for item in lowering["runtime_projection"]["seeds"]
            if item["collection"] == "units"
        )
        seed["target_path"] = (
            ["missing_member"] if mutation == "projection-missing-path" else []
        )
    else:
        profile["modules_member"] = "host_drift"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        stage == "static" and code == "kernel.vector_mismatch"
        for stage, code, _subject in first["diagnostics"]
    )
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "initialization_source",
    ("named-random-stream", "resolved-model"),
)
def test_two_consumers_refuse_assignment_modes_without_an_operand_value_producer(
    initialization_source,
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    policy = ldb["language"]["model_lowerings"][0]["assignment_policy"]
    parameter = next(row for row in policy["roles"] if row["role"] == "parameter")
    mode = next(row for row in parameter["modes"] if row["id"] == "experiment-required")
    mode.update(
        {
            "initialization_source": initialization_source,
            "value_member": "forbidden",
            "experiment_cardinality": "forbidden",
            "override": False,
        }
    )
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions.assignment-policy",
    ) in first["diagnostics"]


def test_literal_typing_is_an_independent_package_owned_authority():
    authority = authority_set()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    policy = language["model_lowerings"][0]["assignment_policy"]
    profiles = language["literal_typing_profiles"]
    owner = next(
        package for package in language["packages"] if package["id"] == "core.quantity"
    )

    assert "literal_profiles" not in policy
    assert "literal_selection" not in policy
    assert [profile["id"] for profile in profiles] == ["quantity.dimensionless-int64"]
    assert owner["exports"]["literal_typing_profiles"] == [
        "quantity.dimensionless-int64"
    ]
    assert "language.literal_typing_profiles" in owner["runtime_semantic_paths"]


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-type",
        "missing-numeric-policy",
        "overlapping-profile",
    ),
)
def test_two_consumers_refuse_unclosed_or_ambiguous_literal_typing_profiles(
    mutation,
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    profiles = ldb["language"]["literal_typing_profiles"]
    profile = profiles[0]
    if mutation == "missing-type":
        profile["type"]["id"] = "MissingQuantity"
    elif mutation == "missing-numeric-policy":
        profile["numeric_policy"] = "missing-numeric-policy"
    else:
        overlapping = deepcopy(profile)
        overlapping["id"] = "quantity.dimensionless-int64-overlap"
        profiles.append(overlapping)
        owner = next(
            package
            for package in ldb["language"]["packages"]
            if package["id"] == "core.quantity"
        )
        owner["exports"]["literal_typing_profiles"].append(overlapping["id"])
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.literal-typing-profiles",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    ("mutation", "expected_subject"),
    (
        (
            "effect",
            (
                "language.operations.game.combat@1.0.0."
                "game.combat.cast-v1.body.hit-check.effects"
            ),
        ),
        (
            "refusal",
            (
                "language.operations.game.combat@1.0.0."
                "game.combat.cast-v1.body.hit-check.refusals"
            ),
        ),
        (
            "resource",
            (
                "language.operations.game.combat@1.0.0."
                "game.combat.cast-v1.resource_bounds"
            ),
        ),
        (
            "cycle",
            (
                "language.operations.game.check@1.0.0."
                "game.check.hit-v1.body.cycle.operation"
            ),
        ),
        (
            "argument-contract",
            (
                "language.operations.game.combat@1.0.0."
                "game.combat.cast-v1.body.hit-check.arguments"
            ),
        ),
        (
            "literal-contract",
            (
                "language.operations.game.combat@1.0.0."
                "game.combat.cast-v1.body.apply-damage.arguments"
            ),
        ),
    ),
)
def test_two_consumers_refuse_every_reidentified_operation_composition_violation(
    mutation,
    expected_subject,
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    operations = {
        operation["id"]: operation for operation in ldb["language"]["operations"]
    }
    hit = operations["game.check.hit-v1"]
    cast_operation = operations["game.combat.cast-v1"]
    if mutation == "effect":
        hit["effects"].append("hidden.child-effect")
    elif mutation == "refusal":
        hit["refusals"].append("hidden.child-refusal")
    elif mutation == "resource":
        cast_operation["resource_bounds"]["max_steps"] = 1
    elif mutation == "argument-contract":
        defense = next(port for port in hit["inputs"] if port["id"] == "defense")
        defense["numeric_policy"] = "exact-bool"
    elif mutation == "literal-contract":
        damage_call = next(
            instruction
            for instruction in cast_operation["body"]
            if instruction.get("site") == "apply-damage"
        )
        critical = next(
            argument
            for argument in damage_call["arguments"]
            if argument["port"] == "critical"
        )
        critical["operand"] = {"kind": "literal", "literal": 1}
    else:
        hit["body"] = [
            {
                "arguments": [
                    {
                        "operand": {"kind": "port", "port": "accuracy"},
                        "port": "accuracy",
                    },
                    {
                        "operand": {"kind": "port", "port": "defense"},
                        "port": "defense",
                    },
                ],
                "node": "invoke",
                "operation": {
                    "id": "game.check.hit-v1",
                    "package": "game.check",
                    "version": "1.0.0",
                },
                "outcomes": [
                    {
                        "action": {"kind": "continue"},
                        "outcome": "hit",
                    },
                    {
                        "action": {"kind": "continue"},
                        "outcome": "miss",
                    },
                ],
                "result": {"kind": "discard"},
                "site": "self",
            }
        ]
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        expected_subject,
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "projection-output-shape",
        "output-equality-type",
    ),
)
def test_two_consumers_refuse_reidentified_authority_type_mismatches(mutation):
    authority = authority_set()
    ldb = authority["language_bundle"]
    lowering = ldb["language"]["model_lowerings"][0]
    if mutation == "projection-output-shape":
        collection = next(
            item
            for item in lowering["runtime_projection"]["collections"]
            if item["id"] == "components"
        )
        collection["output_shape"] = "definition"
    else:
        lowering["output_equalities"][0]["right"] = ["domain"]
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions",
    ) in first["diagnostics"]


def test_two_consumers_type_empty_semantic_collections_from_kernel_contracts():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    ldb["language"]["conversions"] = []
    package["exports"]["conversions"] = []
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


def test_kernel_meta_format_and_ldb_rules_are_structured_for_independent_execution():
    authority = authority_set()
    meta_format = authority["kernel"]["meta_format"]

    assert set(meta_format) == {
        "admitted_language_index",
        "fact",
        "term",
        "rule",
        "rule_selection",
        "binding_substitution",
        "diagnostic_reason",
        "language_bundle",
        "language_definitions",
        "literal_typing",
        "model_program_vector",
        "package_dependency_constraint",
        "package_conformance_vector_set",
        "package_release",
        "package_vector",
        "resolution_judgment",
        "runtime_program",
        "runtime_projection",
        "template_admission",
    }
    resolution = meta_format["resolution_judgment"]
    assert _consumer_b_package_vector_contract_is_closed(meta_format["package_vector"])
    assert production_bootstrap._package_vector_contract_is_closed(
        meta_format["package_vector"]
    )
    assert resolution["closed"] is True
    assert resolution["stage_order"] == ["static", "resolution"]
    assert [item["id"] for item in resolution["operations"]] == [
        item["id"]
        for stage in resolution["stage_order"]
        for item in resolution["operations"]
        if item["stage"] == stage
    ]
    assert _consumer_b_resolution_contract_is_closed(resolution)
    assert all(
        set(item)
        == {
            "effects",
            "id",
            "input",
            "law",
            "refusals",
            "resources",
            "result",
            "stage",
        }
        for item in resolution["operations"]
    )
    assert all(
        item["input"] == {"fact_kind": "resolution-state"}
        and item["result"] == {"fact_kind": "resolution-state"}
        and item["effects"] == []
        and item["refusals"] == ["reason-bound-diagnostic"]
        and item["resources"]
        for item in resolution["operations"]
    )
    template_admission = meta_format["template_admission"]
    profile = authority["language_bundle"]["language"]["template_admission_profiles"][0]
    assert template_admission["closed"] is True
    assert template_admission["role_contract"] == {
        "identifier": "non-empty-string",
        "cardinalities": ["exactly-one", "one-or-more"],
    }
    assert _consumer_b_template_admission_is_closed(
        meta_format, authority["language_bundle"]
    )
    assert {item["operation"] for item in profile["judgments"]} == {
        item["id"] for item in template_admission["operations"]
    }
    assert all(
        set(item)
        == {
            "effects",
            "id",
            "input",
            "law",
            "refusals",
            "resources",
            "result",
        }
        and item["input"] == {"fact_kind": "template-graph"}
        and item["result"] == {"fact_kind": "template-graph"}
        and item["effects"] == []
        and item["refusals"] == ["reason-bound-diagnostic"]
        and item["resources"]
        and item["law"]["operator"] == item["id"]
        and item["law"]["primitive"]
        in {
            primitive["id"]
            for primitive in template_admission["primitive_spec"]["primitives"]
        }
        for item in template_admission["operations"]
    )
    assert {item["law"]["primitive"] for item in template_admission["operations"]} == {
        primitive["id"]
        for primitive in template_admission["primitive_spec"]["primitives"]
    }
    assert {item["role"] for item in profile["member_roles"]} == {
        "source",
        "experiment",
        "dependencies",
        "defaults",
        "compatibility",
        "documentation",
        "coverage",
        "golden",
        "negative-vector",
        "boundary-vector",
    }
    assert {item["tag"] for item in meta_format["term"]["constructors"]} == {
        "literal",
        "variable",
    }
    for rule in authority["language_bundle"]["language"]["rules"]:
        assert set(rule) == {"id", "phase", "judgment", "premises", "conclusion"}
        assert rule["phase"] in meta_format["rule"]["phases"]
        assert rule["premises"]
        assert set(rule["conclusion"]) == {"fact_kind", "fields"}


@pytest.mark.parametrize("member", ("member_roles", "judgments"))
def test_two_consumers_refuse_an_incomplete_template_admission_profile(member):
    authority = authority_set()
    ldb = authority["language_bundle"]
    ldb["language"]["template_admission_profiles"][0][member].pop()
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_runtime_program_contract_is_independently_executable_and_profile_bound():
    authority = authority_set()
    runtime = authority["kernel"]["meta_format"]["runtime_program"]

    assert set(runtime) == {
        "closed",
        "version",
        "evaluation_order",
        "fixed_value_contracts",
        "expression_nodes",
        "effect_nodes",
        "control_nodes",
        "nodes",
        "numeric",
        "named_rng",
        "event_atomicity",
        "outcome_contract",
        "invocation_contract",
        "vectors",
    }
    nodes = {item["id"]: item for item in runtime["nodes"]}
    assert set(nodes) == {
        *runtime["expression_nodes"],
        *runtime["effect_nodes"],
        *runtime["control_nodes"],
    }
    assert len(nodes) == len(runtime["nodes"])
    for node_id, node in nodes.items():
        assert set(node) == {
            "family",
            "id",
            "operand_constraints",
            "refusals",
            "required_members",
            "resource_charge",
            "result",
            "semantics",
        }
        assert node["family"] in {"expression", "effect", "control"}
        assert node_id in runtime[f"{node['family']}_nodes"]
        assert node["required_members"][0] == "node"
        assert node["resource_charge"] == {
            "amount": 1,
            "counter": "event-steps",
        }
        assert isinstance(node["semantics"]["operator"], str)
        assert node["semantics"]["operator"]
        assert isinstance(node["result"]["kind"], str)
        assert node["result"]["kind"]
        if node["result"]["kind"] in {"local", "draw"}:
            assert node["result"]["typing"]["kind"] in {
                "fixed",
                "same-as-references",
                "literal-profile",
            }
        assert isinstance(node["operand_constraints"], list)

    assert set(runtime["fixed_value_contracts"]) == {
        "kernel-boolean",
        "kernel-unit",
    }
    assert runtime["numeric"] == {
        "compatible_value_numeric_policies": ["exact-int64"],
        "id": "signed-int64-v1",
        "minimum": -(1 << 63),
        "maximum": (1 << 63) - 1,
        "overflow": "runtime-refusal",
        "overflow_signal": "numeric-overflow",
    }
    assert runtime["named_rng"] == {
        "algorithm": "splitmix64-v1",
        "word_bits": 64,
        "seed_encoding": "unsigned-modulo-2^64",
        "stream_name_encoding": "utf-8",
        "stream_derivation": {
            "hash": "sha256",
            "digest_slice": {"offset": 0, "length": 8},
            "byte_order": "big",
            "combine": "unsigned-add-modulo-2^64",
        },
        "state_transition": {
            "increment_hex": "9e3779b97f4a7c15",
            "mix_steps": [
                {"xor_shift_right": 30, "multiply_hex": "bf58476d1ce4e5b9"},
                {"xor_shift_right": 27, "multiply_hex": "94d049bb133111eb"},
                {"xor_shift_right": 31},
            ],
        },
        "interval_sampling": {
            "bounds": "inclusive",
            "mapping": "unsigned-modulo-width",
            "bias_policy": "accepted-modulo-bias-v1",
            "candidates_per_draw": 1,
        },
        "trace_members": [
            "stream",
            "index",
            "candidate_hex",
            "accepted",
            "minimum",
            "maximum",
            "value",
        ],
    }
    assert runtime["event_atomicity"] == {
        "state_writes": "buffered",
        "rng_draws": "buffered",
        "success": "commit-entire-current-event",
        "runtime_refusal": "rollback-entire-current-event",
    }
    assert runtime["outcome_contract"] == {
        "kinds": ["success", "gameplay-alternative"],
        "state_policies": ["commit", "rollback"],
        "operation_members": ["outcomes", "default_outcome"],
    }
    assert runtime["invocation_contract"]["scope"] == "lexical-call-frame"
    assert runtime["invocation_contract"]["ambient_capture"] == "forbidden"
    assert runtime["invocation_contract"]["outcome_mapping"] == (
        "exactly-once-and-exhaustive"
    )
    node_vectors = {
        item["node"]: item for item in runtime["vectors"] if item["kind"] == "node"
    }
    assert set(node_vectors) == set(nodes)
    for node_id, node in nodes.items():
        assert (
            node_vectors[node_id]["expect"]["operand_constraints"]
            == node["operand_constraints"]
        )
        assert node_vectors[node_id]["expect"].get("result_typing") == node[
            "result"
        ].get("typing")
    assert {item["id"] for item in runtime["vectors"] if item["kind"] == "rng"} == {
        "rng.first-draw",
        "rng.multi-draw",
        "rng.cross-stream",
        "rng.interval-boundary",
    }
    invocation_vectors = {
        item["id"]: item
        for item in runtime["vectors"]
        if item["kind"] == "invocation-result-contract"
    }
    assert invocation_vectors["runtime.invocation.result-contract-compatible"][
        "expect"
    ] == {"admitted": True}
    assert invocation_vectors["runtime.invocation.result-contract-incompatible"][
        "expect"
    ] == {"admitted": False}

    profile = next(
        item
        for item in authority["language_bundle"]["language"]["runtime_profiles"]
        if item["id"] == "standard.exact-int64-event-v1"
    )
    assert profile["runtime_program_version"] == runtime["version"]
    assert profile["numeric_law"] == runtime["numeric"]["id"]
    assert profile["rng"] == {
        "algorithm": runtime["named_rng"]["algorithm"],
        "interval_sampling": runtime["named_rng"]["interval_sampling"]["mapping"],
        "bias_policy": runtime["named_rng"]["interval_sampling"]["bias_policy"],
    }
    assert profile["budget_scopes"] == {
        "operation_max_steps": "per-event",
        "runtime_max_steps": "per-run",
    }


def test_rpg_operation_declares_its_complete_gameplay_outcome_algebra():
    authority = authority_set()
    operation = next(
        item
        for item in authority["language_bundle"]["language"]["operations"]
        if item["id"] == "game.combat.cast-v1"
    )

    assert operation["default_outcome"] == "cast-resolved"
    assert operation["outcomes"] == [
        {"id": "cast-resolved", "kind": "success", "state_policy": "commit"},
        {
            "id": "insufficient-resource",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        },
        {
            "id": "miss",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        },
    ]
    declared = {item["id"] for item in operation["outcomes"]}
    operations = {
        item["id"]: item
        for item in authority["language_bundle"]["language"]["operations"]
    }
    referenced = {
        mapping["action"]["outcome"]
        for invocation in operation["body"]
        for mapping in invocation["outcomes"]
        if mapping["action"]["kind"] == "propagate"
    }
    assert referenced == declared - {operation["default_outcome"]}
    assert {invocation["operation"]["id"] for invocation in operation["body"]} <= set(
        operations
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-evaluation-field",
        "unknown-argument-type",
        "missing-charge",
        "unknown-operation-primitive",
        "semantic-value",
        "wrong-result-effect",
        "wrong-failure",
        "wrong-charge-law",
        "argument-type-law",
    ),
)
def test_two_consumers_refuse_an_incomplete_template_primitive_spec(
    mutation, monkeypatch
):
    authority = authority_set()
    kernel = authority["kernel"]
    primitive_spec = kernel["meta_format"]["template_admission"]["primitive_spec"]
    if mutation == "missing-evaluation-field":
        primitive_spec["primitives"][0]["evaluation"].pop("canonical_encoding")
    elif mutation == "unknown-argument-type":
        primitive_spec["primitives"][0]["argument_types"]["selector"] = "host-object"
    elif mutation == "missing-charge":
        primitive_spec["primitives"][0]["charges"].remove("judgment")
    elif mutation == "unknown-operation-primitive":
        kernel["meta_format"]["template_admission"]["operations"][0]["law"][
            "primitive"
        ] = "host-only"
    elif mutation == "semantic-value":
        primitive_spec["primitives"][0]["evaluation"]["canonical_encoding"] = "host.foo"
    elif mutation == "wrong-result-effect":
        primitive_spec["primitives"][0]["result_effect"] = "preserve-graph"
    elif mutation == "wrong-failure":
        primitive_spec["primitives"][0]["failure"]["short_circuit"] = False
    elif mutation == "wrong-charge-law":
        primitive_spec["primitives"][0]["charges"] = ["judgment"]
    else:
        primitive_spec["argument_types"][4]["empty"] = True
    _reidentify(kernel, authority["language_bundle"])
    kernel_identity = kernel["content_identity"]
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )
    monkeypatch.setitem(globals(), "_SUPPORTED_KERNEL_IDENTITY", kernel_identity)

    first = _consumer_a(kernel, authority["language_bundle"])
    second = _consumer_b(kernel, authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert not _consumer_b_template_admission_is_closed(
        kernel["meta_format"], authority["language_bundle"]
    )


@pytest.mark.parametrize(
    "mutation",
    ("empty-non-empty-string", "selector-root-list", "binding-source-list"),
)
def test_two_consumers_execute_template_primitive_argument_types(mutation):
    authority = authority_set()
    ldb = authority["language_bundle"]
    judgments = ldb["language"]["template_admission_profiles"][0]["judgments"]
    if mutation == "empty-non-empty-string":
        judgment = next(
            row for row in judgments if row["id"] == "template.metric-target-interval"
        )
        judgment["arguments"]["minimum_member"] = ""
    elif mutation == "selector-root-list":
        judgment = next(
            row for row in judgments if row["id"] == "template.derive-source-identity"
        )
        judgment["arguments"]["selector"]["root"] = []
    else:
        judgment = next(
            row for row in judgments if row["id"] == "template.admit-source"
        )
        judgment["arguments"]["fact_bindings"][0]["source"] = []
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-selector-root",
        "unknown-model-fact",
        "duplicate-derived-result",
        "derived-use-before-production",
        "invalid-resource-limit",
    ),
)
def test_two_consumers_refuse_malformed_template_graph_programs(mutation):
    authority = authority_set()
    ldb = authority["language_bundle"]
    profile = ldb["language"]["template_admission_profiles"][0]
    if mutation == "unknown-selector-root":
        profile["judgments"][0]["arguments"]["selector"]["root"] = "host"
    elif mutation == "unknown-model-fact":
        profile["judgments"][2]["arguments"]["fact_bindings"][0]["source"] = "host"
    elif mutation == "duplicate-derived-result":
        profile["judgments"][1]["arguments"]["result"] = "source_identity"
    elif mutation == "derived-use-before-production":
        profile["judgments"].append(profile["judgments"].pop(0))
    else:
        ldb["resources"]["max_template_admission_steps"] = 0
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    expected = (
        ("ingress", "kernel.member_set_mismatch")
        if mutation == "invalid-resource-limit"
        else ("static", "kernel.vector_mismatch")
    )
    assert any(
        (stage, code) == expected for stage, code, _subject in first["diagnostics"]
    )


def test_template_role_names_are_ldb_owned_without_a_kernel_change():
    authority = authority_set()
    ldb = authority["language_bundle"]
    documentation = next(
        row
        for row in ldb["language"]["template_admission_profiles"][0]["member_roles"]
        if row["role"] == "documentation"
    )
    documentation["role"] = "genre-extension"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


def test_resolution_profile_symbol_mapping_must_name_the_declared_semantic_fact():
    authority = authority_set()
    ldb = authority["language_bundle"]
    ldb["language"]["resolution_profiles"][0]["symbol_fact_member"] = "role"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-diagnostic",
        "invalid-resource-recipe",
        "missing-diagnostic-pointer",
        "missing-relation",
    ),
)
def test_reidentified_model_program_vector_contract_mutations_are_refused(
    mutation,
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    if mutation == "unknown-diagnostic":
        vector = _owned_vector(
            ldb,
            "model.compile.negative-duplicate",
        )
        vector["expect"]["diagnostics"][0]["code"] = "host.unknown"
    elif mutation == "invalid-resource-recipe":
        vector = _owned_vector(
            ldb,
            "model.compile.boundary-max-symbols-plus-one",
        )
        vector["source_fixture"]["count_offset"] = 2
    elif mutation == "missing-diagnostic-pointer":
        vector = _owned_vector(
            ldb,
            "model.compile.negative-duplicate",
        )
        vector["expect"]["diagnostics"][0].pop("pointer")
    else:
        vector = _owned_vector(
            ldb,
            "model.compile.mutation-role-change",
        )
        vector["expect"]["relation"]["reference"] = "host.missing"

    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_kernel_publishes_the_complete_canonical_identity_recipe():
    encoding = authority_set()["kernel"]["canonical_encoding"]

    assert encoding["identity_algorithm"] == "sha256"
    assert encoding["identity_domain_prefix"] == "gda-balancing:"
    assert encoding["identity_domain_suffix"] == ":"
    assert encoding["identity_excluded_members"] == ["content_identity"]
    assert encoding["identity_output_prefix"] == "sha256:"
    assert encoding["digest_hex_case"] == "lowercase"
    assert encoding["document_terminator"] == "LF"
    assert encoding["array_order"] == "preserve"
    assert encoding["whitespace"] == "none"
    assert encoding["item_separator"] == ","
    assert encoding["key_separator"] == ":"
    assert encoding["non_ascii_strings"] == "literal-utf8"
    assert encoding["escape_solidus"] is False
    assert encoding["printable_ascii_escaping"] == (
        "only-quotation-mark-and-reverse-solidus"
    )
    assert encoding["control_character_escaping"] == {
        "backspace": "\\b",
        "form-feed": "\\f",
        "line-feed": "\\n",
        "other-u0000-u001f": "lowercase-u00xx",
        "carriage-return": "\\r",
        "tab": "\\t",
    }
    assert encoding["delete_character_escaping"] == "literal-byte-7f"
    assert encoding["lone_surrogate"] == "refuse"
    assert encoding["number_kinds"] == ["signed-int64"]
    assert encoding["duplicate_object_keys"] == "refuse-at-decoding"
    assert {item["id"] for item in encoding["vectors"]} == {
        "canonical.boundary-integers",
        "canonical.control-character-escaping",
        "canonical.order-array-unicode-escaping",
        "canonical.reject-duplicate-key",
        "canonical.reject-float",
        "canonical.reject-lone-surrogate",
    }


def test_every_kernel_law_publishes_a_complete_machine_contract():
    kernel = authority_set()["kernel"]

    for law in kernel["admission"]["laws"]:
        assert set(law) == {
            "arguments",
            "effects",
            "id",
            "input",
            "operation",
            "refusals",
            "resources",
            "result",
        }
        assert isinstance(law["arguments"], dict)
        assert law["input"] == {"fact_kind": "authority-pair"}
        assert law["result"] == {"fact_kind": "admission-verdict"}
        assert law["effects"] == []
        assert law["refusals"]
        assert isinstance(law["resources"], list)


def test_quantity_package_is_complete_content_addressed_and_uses_canonical_terms():
    ldb = authority_set()["language_bundle"]
    package = ldb["language"]["packages"][0]

    assert set(package) == {
        "artifact_kind",
        "capabilities",
        "conformance_vectors",
        "content_identity",
        "dependencies",
        "exports",
        "id",
        "profiles",
        "runtime_semantic_paths",
        "semantic_closure",
        "semantic_identity",
        "version",
    }
    assert package["artifact_kind"] == "domain-package-release"
    assert package["content_identity"] == _identity(
        "domain-package-release-v2", package
    )
    expected_package = deepcopy(package)
    _reidentify_package_release(expected_package)
    assert package["semantic_identity"] == expected_package["semantic_identity"]
    assert package["dependencies"] == {
        "optional": [],
        "required": [{"id": "standard.compiler", "version": "1.0.0"}],
    }
    assert package["capabilities"]["required"] == []
    assert package["exports"]["components"] == ["quantity.symbol"]
    assert package["exports"]["conversions"] == ["quantity.identity"]
    assert package["exports"]["operations"] == ["quantity.identity"]
    assert package["profiles"]["runtime"] == []
    assert package["exports"]["types"]
    vector_set = _package_vector_set(ldb, package)
    assert vector_set["vectors"]
    assert [item["id"] for item in vector_set["vector_definitions"]] == vector_set[
        "vectors"
    ]
    assert ldb["language"]["quantity"]["representations"] == ["Int"]
    assert "random" in ldb["language"]["quantity"]["symbol_roles"]
    assert "random-variable" not in ldb["language"]["quantity"]["symbol_roles"]
    duplicate = next(
        item
        for item in ldb["diagnostics"]
        if item["code"] == "language.duplicate_symbol"
    )
    assert duplicate["stage"] == "static"


def test_reidentified_ldb_cannot_hide_a_tampered_package_release():
    authority = authority_set()
    package = authority["language_bundle"]["language"]["packages"][0]
    package["version"] = "2.0.1"
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )


def test_package_release_identity_binds_normative_vector_definitions():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    vector_set = _package_vector_set(ldb, package)
    old_release_identity = package["content_identity"]
    old_semantic_identity = package["semantic_identity"]
    old_vector_identity = vector_set["content_identity"]
    vector = _owned_vector(ldb, "model.compile.positive")
    vector["expect"]["debug_map_identity"] = "sha256:" + "f" * 64

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" and subject.endswith(".conformance_vectors")
        for _, code, subject in first["diagnostics"]
    ), first["diagnostics"]

    _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)

    package = ldb["language"]["packages"][0]
    vector_set = _package_vector_set(ldb, package)
    assert vector_set["content_identity"] != old_vector_identity
    assert package["content_identity"] != old_release_identity
    assert package["semantic_identity"] == old_semantic_identity
    assert _consumer_a(authority["kernel"], ldb)["admitted"] is True


def test_kernel_identity_law_owns_every_authority_artifact_domain():
    kernel = authority_set()["kernel"]
    law = next(
        item
        for item in kernel["admission"]["laws"]
        if item["id"] == "kernel.identity.verify"
    )

    assert {
        target.get("artifact") or target.get("collection"): target["domain"]
        for target in law["arguments"]["targets"]
    } == {
        "kernel": "schema-major-kernel-v2",
        "language-bundle": "language-definition-bundle-v2",
        "language_bundle.language.packages": "domain-package-release-v2",
        "language_bundle.package_conformance_vector_sets": (
            "package-conformance-vector-set-v2"
        ),
    }


def test_two_consumers_project_kernel_package_coordinate_patterns():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = next(
        item for item in ldb["language"]["packages"] if item["id"] == "game.combat"
    )
    vector_set = _package_vector_set(ldb, package)
    package["id"] = "game/combat"
    vector_set["package_id"] = package["id"]
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert {code for _stage, code, _subject in first["diagnostics"]} >= {
        "kernel.binding_mismatch",
        "kernel.member_set_mismatch",
    }


def test_two_consumers_follow_an_expanded_kernel_coordinate_pattern(monkeypatch):
    authority = authority_set()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    kernel["meta_format"]["package_conformance_vector_set"]["field_types"][
        "package_id"
    ]["pattern"] = r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$"
    _reidentify(kernel, ldb)
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
    )
    monkeypatch.setitem(
        globals(), "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
    )

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is True
    assert first["diagnostics"] == []


@pytest.mark.parametrize(
    "mutation",
    ("contract-expectation", "runtime-operation", "unknown-kind"),
)
def test_reidentified_package_evidence_vector_mutations_refuse_in_both_consumers(
    mutation,
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    if mutation == "contract-expectation":
        package = next(
            item
            for item in ldb["language"]["packages"]
            if item["id"] == "game.resource"
        )
        vector = _owned_vector(ldb, "game.resource.spend.effects")
        vector["expect"] = ["event.commit"]
    else:
        package = next(
            item for item in ldb["language"]["packages"] if item["id"] == "game.combat"
        )
        vector = _owned_vector(ldb, "game.combat.cast.positive")
        if mutation == "runtime-operation":
            vector["operation"] = "game.combat.damage-v1"
        else:
            vector["kind"] = "host-runtime-scenario"
    _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" and subject.endswith(".vectors")
        for _, code, subject in first["diagnostics"]
    ), first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    ("category", "kind-members", "probe-root"),
)
def test_reidentified_package_vector_contract_mutations_refuse_in_both_consumers(
    mutation, monkeypatch
):
    authority = authority_set()
    contract = authority["kernel"]["meta_format"]["package_vector"]
    if mutation == "category":
        contract["categories"].append("host-category")
    elif mutation == "kind-members":
        contract["kinds"][0]["required_members"].append("host")
    else:
        contract["package_probe_roots"].append("content_identity")
    _reidentify(authority["kernel"], authority["language_bundle"])
    kernel_identity = authority["kernel"]["content_identity"]
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )
    monkeypatch.setitem(globals(), "_SUPPORTED_KERNEL_IDENTITY", kernel_identity)

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "kernel.meta_format.package_vector",
    ) in first["diagnostics"]


def test_authority_admission_requires_one_default_resolution_profile():
    authority = authority_set()
    ldb = authority["language_bundle"]
    profile = ldb["language"]["resolution_profiles"][0]
    profile["default"] = False
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if profile["id"] in candidate["profiles"]["resolution"]
    )
    for entry in package["semantic_closure"]:
        if entry["authority_path"] == "language.resolution_profiles":
            entry["definitions"] = deepcopy(ldb["language"]["resolution_profiles"])
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" and subject == "language.definitions"
        for _, code, subject in first["diagnostics"]
    )


def test_package_identity_binds_the_complete_exported_definition_closure():
    authority = authority_set()
    ldb = authority["language_bundle"]
    ldb["language"]["operations"][0]["resource_bounds"]["max_steps"] = 2
    package = ldb["language"]["packages"][0]
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation_entry["definitions"][0]["resource_bounds"]["max_steps"] = 2
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch"
        and subject == "language-bundle.language.packages.0"
        for _, code, subject in first["diagnostics"]
    )


def test_reidentified_package_cannot_hide_a_tampered_embedded_definition():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation_entry["definitions"][0]["resource_bounds"]["max_steps"] = 2
    package["content_identity"] = _identity("domain-package-release-v2", package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch"
        and subject == "language-bundle.language.packages.0.semantic_identity"
        for _, code, subject in first["diagnostics"]
    )


def test_coherent_package_semantic_change_changes_the_release_identity():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    old_release_identity = package["content_identity"]
    ldb["language"]["operations"][0]["resource_bounds"]["max_steps"] = 2
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation_entry["definitions"][0]["resource_bounds"]["max_steps"] = 2
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True
    assert package["content_identity"] != old_release_identity


def test_semantic_closure_cannot_move_a_definition_to_a_non_owner_package():
    authority = authority_set()
    ldb = authority["language_bundle"]
    quantity_package = ldb["language"]["packages"][0]
    other_package = deepcopy(quantity_package)
    other_package["id"] = "core.other"
    other_package["capabilities"] = {"provided": [], "required": []}
    other_package["dependencies"] = {"optional": [], "required": []}
    other_package["exports"] = {member: [] for member in quantity_package["exports"]}
    other_package["profiles"] = {"numeric": [], "resolution": [], "runtime": []}
    for entry in other_package["semantic_closure"]:
        entry["definitions"] = []

    quantity_components = next(
        entry
        for entry in quantity_package["semantic_closure"]
        if entry["authority_path"] == "language.components"
    )
    other_components = next(
        entry
        for entry in other_package["semantic_closure"]
        if entry["authority_path"] == "language.components"
    )
    other_components["definitions"] = quantity_components["definitions"]
    quantity_components["definitions"] = []

    for package in (quantity_package, other_package):
        _reidentify_package_release(package)
    ldb["language"]["packages"].append(other_package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" and subject.endswith(".semantic_identity")
        for _, code, subject in first["diagnostics"]
    )


def test_model_lowering_invocation_must_match_the_referenced_rule_contract():
    authority = authority_set()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    language["model_lowerings"][0]["rule_chain"][0]["judgment"] = (
        "host-invented-judgment"
    )
    package = language["packages"][0]
    lowering_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.model_lowerings"
    )
    lowering_entry["definitions"] = deepcopy(language["model_lowerings"])
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.packages",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    [
        "ldb-artifact-kind",
        "ldb-schema-major",
        "diagnostic-extra-member",
        "package-id-type",
        "package-version-type",
        "package-exported-type-empty-id",
    ],
)
def test_reidentified_ldb_and_package_shapes_remain_closed(mutation):
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]

    if mutation == "ldb-artifact-kind":
        ldb["artifact_kind"] = "not-a-bundle"
        ldb.root["artifact_kind"] = "not-a-bundle"
    elif mutation == "ldb-schema-major":
        ldb["schema_major"] = 3
        ldb.root["schema_major"] = 3
    elif mutation == "diagnostic-extra-member":
        ldb["diagnostics"][0]["host_semantics"] = True
        diagnostic_code = ldb["diagnostics"][0]["code"]
        package = next(
            candidate
            for candidate in ldb["language"]["packages"]
            if diagnostic_code in candidate["exports"]["diagnostics"]
        )
        diagnostic_entry = next(
            entry
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "diagnostics"
        )
        next(
            row
            for row in diagnostic_entry["definitions"]
            if row["code"] == diagnostic_code
        )["host_semantics"] = True
        _reidentify_package_release(package)
    elif mutation == "package-id-type":
        package["id"] = 7
    elif mutation == "package-version-type":
        package["version"] = False
    else:
        package["exports"]["types"][0]["id"] = ""

    if mutation.startswith("package-"):
        package["content_identity"] = _identity("domain-package-release-v2", package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_reidentified_package_cannot_reference_an_unowned_vector():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    vector_set = _package_vector_set(ldb, package)
    vector_set["vectors"][0] = "host.missing"
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch"
        and subject == "language-bundle.language.packages.0.vectors"
        for _, code, subject in first["diagnostics"]
    ), first["diagnostics"]


def test_bootstrap_executes_every_rule_vector_into_a_stable_projection():
    authority = authority_set()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    assert admission.admitted is True
    assert dict(admission.rule_projections).keys() == {
        "quantity.declare.valid",
        "quantity.lower.valid",
    }
    assert all(
        identity.startswith("sha256:") for _, identity in admission.rule_projections
    )


def test_bootstrap_projects_every_kernel_law_without_a_host_fallback_table():
    authority = authority_set()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    law_ids = {item["id"] for item in authority["kernel"]["admission"]["laws"]}
    assert {law_id for law_id, _ in admission.law_projections} == law_ids
    assert all(
        identity.startswith("sha256:") for _, identity in admission.law_projections
    )


def test_bootstrap_behavior_covers_every_ldb_diagnostic_reason():
    authority = authority_set()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    catalog_codes = {
        item["code"] for item in authority["language_bundle"]["diagnostics"]
    }
    projection_codes = {code for _, code, _ in admission.diagnostic_projections}
    assert admission.admitted is True
    assert projection_codes == catalog_codes
    assert all(
        identity.startswith("sha256:")
        for _, _, identity in admission.diagnostic_projections
    )


def test_reidentified_deletion_of_every_law_and_rule_is_refused_by_both_consumers():
    baseline = authority_set()
    kernel_laws = baseline["kernel"]["admission"]["laws"]
    ldb_rules = baseline["language_bundle"]["language"]["rules"]

    for index in range(len(kernel_laws)):
        authority = deepcopy(baseline)
        del authority["kernel"]["admission"]["laws"][index]
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
        assert any(
            code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
        )

    for index in range(len(ldb_rules)):
        authority = deepcopy(baseline)
        del authority["language_bundle"]["language"]["rules"][index]
        _refresh_package_closure_and_reidentify(authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
        assert any(
            code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
        ), first["diagnostics"]


def test_reidentified_duplicate_diagnostic_is_not_hidden_by_set_projection():
    authority = authority_set()
    ldb = authority["language_bundle"]
    diagnostic = deepcopy(ldb["diagnostics"][0])
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if diagnostic["code"] in candidate["exports"]["diagnostics"]
    )
    package["exports"]["diagnostics"].append(diagnostic["code"])
    diagnostic_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    diagnostic_entry["definitions"].append(diagnostic)
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "ingress",
        "kernel.member_set_mismatch",
        "language-bundle.language.packages.0",
    ) in first["diagnostics"]


def test_reidentified_duplicate_vector_id_is_refused_by_both_consumers():
    authority = authority_set()
    ldb = authority["language_bundle"]
    duplicate = deepcopy(ldb["vectors"][0])
    duplicate["rule"] = "quantity.lower"
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if duplicate["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    vector_set["vectors"].append(duplicate["id"])
    vector_set["vector_definitions"].append(duplicate)
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert any(
        code == "kernel.vector_mismatch" and subject.endswith(".vectors")
        for _, code, subject in first["diagnostics"]
    )


def test_reidentified_open_fact_shape_is_refused_by_both_consumers():
    authority = authority_set()
    ldb = authority["language_bundle"]
    vector_id = next(
        item["id"]
        for item in ldb["vectors"]
        if isinstance(item.get("input"), dict) and "facts" in item["input"]
    )
    vector = _owned_vector(ldb, vector_id)
    vector["input"]["facts"][0]["host_semantics"] = "invented"
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if vector["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_open_reason_shape_is_refused_by_both_consumers():
    authority = authority_set()
    authority["language_bundle"]["language"]["reasons"][0]["host_predicate"] = (
        "invented"
    )
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
    ), first["diagnostics"]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("exports", "operations"), ["host.invented"]),
        (("exports", "components"), ["host.invented"]),
        (("exports", "conversions"), ["host.invented"]),
        (("profiles", "runtime"), ["host.invented"]),
        (("capabilities", "provided"), ["host.invented"]),
        (("capabilities", "required"), ["host.invented"]),
        (
            ("dependencies", "required"),
            [{"id": "host.invented", "version": "1.0.0"}],
        ),
        (
            ("dependencies", "optional"),
            [{"id": "host.invented", "version": "1.0.0"}],
        ),
    ],
)
def test_reidentified_package_cannot_hide_an_unowned_reference(path, replacement):
    authority = authority_set()
    package = authority["language_bundle"]["language"]["packages"][0]
    target = package
    for member in path[:-1]:
        target = target[member]
    target[path[-1]] = replacement
    package["content_identity"] = _identity("domain-package-release-v2", package)
    _reidentify_graph_root(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    semantic_owner_paths = {
        ("exports", "operations"),
        ("exports", "components"),
        ("exports", "conversions"),
        ("profiles", "runtime"),
        ("capabilities", "provided"),
    }
    expected_code = (
        "kernel.identity_mismatch"
        if path in semantic_owner_paths
        else (
            "kernel.binding_mismatch"
            if path[0] == "dependencies"
            else "kernel.vector_mismatch"
        )
    )
    assert any(code == expected_code for _, code, _ in first["diagnostics"])


def test_reidentified_rule_phase_mutation_is_refused_by_both_consumers():
    authority = authority_set()
    authority["language_bundle"]["language"]["rules"][0]["phase"] = "host"
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_capability_definition_cannot_omit_its_rule_reference():
    authority = authority_set()
    del authority["language_bundle"]["language"]["capabilities"][0]["rule"]
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_package_cannot_export_an_open_host_operation_definition():
    authority = authority_set()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    language["operations"].append({"host_semantics": "invented", "id": "host.op"})
    package = language["packages"][0]
    package["exports"]["operations"].append("host.op")
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation_entry["definitions"].append(deepcopy(language["operations"][-1]))
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_operation_result_source_cannot_invent_host_semantics():
    authority = authority_set()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    operation["result"]["source"] = {"kind": "host-callback", "name": "execute"}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@1.0.0.game.combat.damage-v1.result.source",
    ) in first["diagnostics"]


def test_reidentified_operation_result_source_requires_its_exact_call_producer():
    authority = authority_set()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.cast-v1"
    )
    operation["result"]["source"] = {
        "kind": "operation-result",
        "site": "apply-damage",
    }
    damage_call = next(
        instruction
        for instruction in operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    damage_call["result"] = {"kind": "local", "name": "damage"}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@1.0.0.game.combat.cast-v1.result.source",
    ) in first["diagnostics"]


def test_reidentified_local_result_source_requires_a_compatible_node_producer():
    authority = authority_set()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    operation["body"].insert(
        -1,
        {
            "node": "less-than",
            "target": "bad_result",
            "left": "base_damage",
            "right": "mitigation",
        },
    )
    operation["resource_bounds"]["max_steps"] += 1
    operation["result"]["source"] = {"kind": "local", "name": "bad_result"}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@1.0.0.game.combat.damage-v1.result.source",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "port-shadow",
        "forward-reference",
        "unused-incompatible-node",
        "unused-non-numeric-node",
    ),
)
def test_operation_body_typing_uses_the_complete_sequential_lexical_scope(mutation):
    authority = authority_set()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    if mutation == "port-shadow":
        operation["body"].insert(
            -1,
            {
                "node": "less-than",
                "target": "base_damage",
                "left": "base_damage",
                "right": "mitigation",
            },
        )
        operation["result"]["source"] = {"kind": "local", "name": "base_damage"}
        operation["resource_bounds"]["max_steps"] += 1
    elif mutation == "forward-reference":
        producer_index = next(
            index
            for index, instruction in enumerate(operation["body"])
            if instruction.get("target") == "damage"
        )
        operation["body"].insert(0, operation["body"].pop(producer_index))
    elif mutation == "unused-incompatible-node":
        operation["body"].insert(
            -1,
            {
                "node": "add",
                "target": "unused_bad",
                "left": "critical",
                "right": "base_damage",
            },
        )
        operation["resource_bounds"]["max_steps"] += 1
    else:
        operation["body"].insert(
            -1,
            {
                "node": "add",
                "target": "unused_bad",
                "left": "critical",
                "right": "critical",
            },
        )
        operation["resource_bounds"]["max_steps"] += 1
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_local_result_source_must_exist_before_every_successful_exit_path():
    authority = authority_set()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    operation["outcomes"].append(
        {
            "id": "early-applied",
            "kind": "success",
            "state_policy": "commit",
        }
    )
    operation["body"].insert(
        0,
        {
            "node": "precondition-greater-than-or-equal",
            "left": "base_damage",
            "right": "mitigation",
            "outcome": "early-applied",
        },
    )
    operation["resource_bounds"]["max_steps"] += 1
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@1.0.0.game.combat.damage-v1.result.source",
    ) in first["diagnostics"]


def test_operation_result_source_refuses_a_non_successful_producer_path():
    authority = authority_set()
    ldb = authority["language_bundle"]
    operations = {
        row["id"]: row
        for row in ldb["language"]["operations"]
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    damage = operations["game.combat.damage-v1"]
    damage["outcomes"].append(
        {
            "id": "no-damage",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        }
    )
    damage["body"].insert(
        0,
        {
            "node": "precondition-greater-than-or-equal",
            "left": "base_damage",
            "right": "mitigation",
            "outcome": "no-damage",
        },
    )
    damage["resource_bounds"]["max_steps"] += 1
    cast_operation = operations["game.combat.cast-v1"]
    damage_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    damage_call["outcomes"].append(
        {"outcome": "no-damage", "action": {"kind": "continue"}}
    )
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@1.0.0.game.combat.cast-v1.result.source",
    ) in first["diagnostics"]


def test_malformed_quantity_inventory_returns_a_typed_refusal_from_both_consumers():
    authority = authority_set()
    authority["language_bundle"]["language"]["quantity"] = []
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert first["diagnostics"]


def test_reidentified_fact_enum_drift_is_refused_by_both_consumers():
    authority = authority_set()
    ldb = authority["language_bundle"]
    vector_id = next(
        item["id"]
        for item in ldb["vectors"]
        if isinstance(item.get("input"), dict) and "facts" in item["input"]
    )
    vector = _owned_vector(ldb, vector_id)
    input_fact = vector["input"]["facts"][0]
    expected_fact = vector["expect"]
    input_fact["fields"]["role"] = "host-role"
    expected_fact["fields"]["role"] = "host-role"
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if vector["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_non_string_variable_term_returns_a_typed_refusal():
    authority = authority_set()
    authority["language_bundle"]["language"]["rules"][0]["conclusion"]["fields"][
        "role"
    ]["name"] = {"host": "role"}
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_operand_type_drift_is_refused_by_both_consumers():
    authority = authority_set()
    authority["language_bundle"]["language"]["reasons"][1]["predicate"][
        "member_field"
    ] = 42
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_cannot_change_its_inventory_semantics():
    authority = authority_set()
    authority["language_bundle"]["language"]["reasons"][0]["predicate"][
        "inventory_path"
    ] = "language.quantity.symbol_roles"
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_cannot_change_its_limit_semantics():
    authority = authority_set()
    authority["language_bundle"]["language"]["reasons"][3]["predicate"][
        "limit_path"
    ] = "resources.max_diagnostics"
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_vector_with_non_boolean_outcome_is_a_total_refusal():
    authority = authority_set()
    ldb = authority["language_bundle"]
    reason_vector_id = next(item["id"] for item in ldb["vectors"] if "reason" in item)
    reason_vector = _owned_vector(ldb, reason_vector_id)
    reason_vector["matched"] = {"host": True}
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if reason_vector["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize(
    ("member", "replacement"),
    [("reason", []), ("diagnostic", {}), ("stage", ["static"])],
)
def test_reidentified_reason_vector_header_type_drift_is_a_total_refusal(
    member, replacement
):
    authority = authority_set()
    reason_vector = next(
        item for item in authority["language_bundle"]["vectors"] if "reason" in item
    )
    reason_vector[member] = replacement
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    ("member", "replacement"),
    [("rule", []), ("rule", {}), ("id", None), ("id", False), ("id", 42)],
)
def test_reidentified_rule_vector_header_type_drift_is_a_total_refusal(
    member, replacement
):
    authority = authority_set()
    rule_vector = next(
        item for item in authority["language_bundle"]["vectors"] if "rule" in item
    )
    rule_vector[member] = replacement
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "rule-id-none",
        "premises-none",
        "bind-list",
        "conclusion-none",
        "conclusion-fields-false",
        "reason-id-none",
        "conclusion-fact-kind-list",
        "premise-fact-kind-list",
        "premise-fact-kind-object",
        "conclusion-term-tag-list",
        "conclusion-term-tag-object",
    ],
)
def test_reidentified_rule_and_reason_shape_drift_is_a_total_refusal(mutation):
    authority = authority_set()
    ldb = authority["language_bundle"]
    rule = ldb["language"]["rules"][0]
    if mutation == "rule-id-none":
        rule["id"] = None
    elif mutation == "premises-none":
        rule["premises"] = None
    elif mutation == "bind-list":
        rule["premises"][0]["bind"] = []
    elif mutation == "conclusion-none":
        rule["conclusion"] = None
    elif mutation == "conclusion-fields-false":
        rule["conclusion"]["fields"] = False
    elif mutation == "reason-id-none":
        ldb["language"]["reasons"][0]["id"] = None
    elif mutation == "conclusion-fact-kind-list":
        rule["conclusion"]["fact_kind"] = []
    elif mutation == "premise-fact-kind-list":
        rule["premises"][0]["fact_kind"] = []
    elif mutation == "premise-fact-kind-object":
        rule["premises"][0]["fact_kind"] = {}
    elif mutation == "conclusion-term-tag-list":
        next(iter(rule["conclusion"]["fields"].values()))["tag"] = []
    else:
        next(iter(rule["conclusion"]["fields"].values()))["tag"] = {}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize("replacement", [None, False, 0, "language", []])
def test_reidentified_non_object_language_is_a_total_refusal(replacement):
    authority = authority_set()
    ldb = authority["language_bundle"]
    ldb["language"] = replacement

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_token_drift_is_refused_by_both_consumers():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    package["exports"]["symbol_roles"][-1] = "host-random"
    symbol_roles = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.quantity.symbol_roles"
    )
    symbol_roles["definitions"][-1] = "host-random"
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
    ), first["diagnostics"]


@pytest.mark.parametrize("replacement", [None, False, 0, [], {}])
def test_reidentified_model_source_schema_version_drift_is_refused(replacement):
    authority = authority_set()
    ldb = authority["language_bundle"]
    ldb["language"]["wire_schemas"][0]["schema"]["properties"]["schema_version"][
        "const"
    ] = replacement
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    ("reason_index", "member", "replacement"),
    [
        (0, "inventory_path", "artifact_kind"),
        (1, "member_field", "host"),
        (3, "limit_path", "artifact_kind"),
    ],
)
def test_reidentified_reason_path_shape_drift_is_a_total_refusal(
    reason_index, member, replacement
):
    authority = authority_set()
    ldb = authority["language_bundle"]
    reason_id = ldb["language"]["reasons"][reason_index]["id"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if reason_id in candidate["exports"]["reasons"]
    )
    reasons = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.reasons"
    )
    reason = next(
        definition
        for definition in reasons["definitions"]
        if definition["id"] == reason_id
    )
    reason["predicate"][member] = replacement
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize("collection", ["constructors", "wire_schemas"])
def test_reidentified_language_definition_envelopes_are_closed(collection):
    authority = authority_set()
    authority["language_bundle"]["language"][collection][0]["host_semantics"] = (
        "invented"
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_carry_an_unknown_host_keyword():
    authority = authority_set()
    wire_schema = authority["language_bundle"]["language"]["wire_schemas"][0]
    wire_schema["schema"]["host_semantics"] = "invented"
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_must_be_valid_under_its_declared_dialect():
    authority = authority_set()
    symbol_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]
    symbol_schema["type"] = 42
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_bypass_object_closure_with_type_array():
    authority = authority_set()
    domain_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]["properties"][
        "domain"
    ]
    domain_schema["type"] = ["object"]
    del domain_schema["unevaluatedProperties"]
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_object_keywords_require_explicit_closed_type():
    authority = authority_set()
    domain_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]["properties"][
        "domain"
    ]
    del domain_schema["type"]
    del domain_schema["unevaluatedProperties"]
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_add_an_open_combinator_branch():
    authority = authority_set()
    domain_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]["properties"][
        "domain"
    ]
    replacement = {"anyOf": [deepcopy(domain_schema), {}]}
    authority["language_bundle"]["language"]["wire_schemas"][0]["schema"]["properties"][
        "modules"
    ]["items"]["properties"]["symbols"]["items"]["properties"]["domain"] = replacement
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_reference_a_missing_local_definition():
    authority = authority_set()
    authority["language_bundle"]["language"]["wire_schemas"][0]["schema"]["$ref"] = (
        "#/$defs/missing"
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_collide_with_reserved_projection_kind():
    authority = authority_set()
    authority["language_bundle"]["language"]["wire_schemas"][0]["artifact_kind"] = (
        "schema-major-kernel"
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_numeric_policy_cannot_invent_overflow_semantics():
    authority = authority_set()
    policy = authority["language_bundle"]["language"]["quantity"]["numeric_policies"][0]
    policy["overflow"] = "wrap"
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_current_slice_refuses_not_yet_delivered_operation_definitions():
    authority = authority_set()
    authority["language_bundle"]["language"]["operations"].append(
        {
            "body": {},
            "effects": [],
            "id": "host.op",
            "inputs": {},
            "numeric_profiles": [],
            "refusals": [],
            "resource_bounds": {},
            "result": {},
            "runtime_profiles": [],
            "vectors": [],
        }
    )
    package = authority["language_bundle"]["language"]["packages"][0]
    package["exports"]["operations"].append("host.op")
    package["content_identity"] = _identity("domain-package-release-v2", package)
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_operation_rule_must_match_every_declared_operation_vector():
    authority = authority_set()
    ldb = authority["language_bundle"]
    operation_id = ldb["language"]["operations"][0]["id"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if operation_id in candidate["exports"]["operations"]
    )
    operations = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation = next(
        definition
        for definition in operations["definitions"]
        if definition["id"] == operation_id
    )
    operation["rule"] = "quantity.declare"
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_conflicting_duplicate_binding_refuses_in_both_consumers():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if "quantity.declare" in candidate["exports"]["language_rules"]
    )
    rules = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.rules"
    )
    rule = next(
        definition
        for definition in rules["definitions"]
        if definition["id"] == "quantity.declare"
    )
    rule["premises"].append(deepcopy(rule["premises"][0]))
    vector = _owned_vector(ldb, "quantity.declare.valid")
    conflicting_fact = deepcopy(vector["input"]["facts"][0])
    conflicting_fact["fields"]["role"] = "input"
    vector["input"]["facts"].append(conflicting_fact)
    vector["expect"]["fields"]["role"] = "input"
    _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_reidentified_duplicate_reason_uses_type_sensitive_scalar_equality():
    authority = authority_set()
    duplicate_vector = next(
        item
        for item in authority["language_bundle"]["vectors"]
        if item["id"] == "quantity.refuse.duplicate"
    )
    duplicate_vector["input"]["values"] = [False, 0]
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_old_identity_tamper_and_reidentified_behavior_or_token_mutations_refuse():
    baseline = authority_set()

    old_identity = deepcopy(baseline)
    old_identity["language_bundle"]["language"]["rules"][0]["conclusion"][
        "fact_kind"
    ] = "changed"
    first = _consumer_a(old_identity["kernel"], old_identity["language_bundle"])
    second = _consumer_b(old_identity["kernel"], old_identity["language_bundle"])
    assert first == second
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )

    for index in range(len(baseline["kernel"]["admission"]["laws"])):
        authority = deepcopy(baseline)
        authority["kernel"]["admission"]["laws"][index]["operation"] += ".renamed"
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert any(
            code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
        )

    for index in range(len(baseline["language_bundle"]["language"]["rules"])):
        authority = deepcopy(baseline)
        ldb = authority["language_bundle"]
        rule_id = ldb["language"]["rules"][index]["id"]
        package = next(
            candidate
            for candidate in ldb["language"]["packages"]
            if rule_id in candidate["exports"]["language_rules"]
        )
        rules = next(
            entry
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "language.rules"
        )
        rule = next(
            definition
            for definition in rules["definitions"]
            if definition["id"] == rule_id
        )
        rule["conclusion"]["fact_kind"] += ".changed"
        _reidentify_package_release(package)
        _reidentify_graph_root(ldb)
        first = _consumer_a(authority["kernel"], ldb)
        second = _consumer_b(authority["kernel"], ldb)
        assert first == second
        assert any(
            code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
        )

    for owner, path in (
        ("kernel", ("admission", "laws")),
        ("language_bundle", ("language", "rules")),
    ):
        authority = deepcopy(baseline)
        collection = authority[owner]
        for part in path:
            collection = collection[part]
        if owner == "kernel":
            collection[0]["id"] += ".renamed"
            _reidentify(authority["kernel"], authority["language_bundle"])
        else:
            ldb = authority["language_bundle"]
            rule_id = collection[0]["id"]
            package = next(
                candidate
                for candidate in ldb["language"]["packages"]
                if rule_id in candidate["exports"]["language_rules"]
            )
            rules = next(
                entry
                for entry in package["semantic_closure"]
                if entry["authority_path"] == "language.rules"
            )
            rule = next(
                definition
                for definition in rules["definitions"]
                if definition["id"] == rule_id
            )
            renamed = f"{rule_id}.renamed"
            package["exports"]["language_rules"][
                package["exports"]["language_rules"].index(rule_id)
            ] = renamed
            rule["id"] = renamed
            _reidentify_package_release(package)
            _reidentify_graph_root(ldb)
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        expected_code = (
            "kernel.identity_mismatch"
            if owner == "kernel"
            else "kernel.vector_mismatch"
        )
        assert any(code == expected_code for _, code, _ in first["diagnostics"])


def test_reidentified_kernel_law_operand_mutation_is_refused_by_both_consumers():
    authority = authority_set()
    binding_law = next(
        law
        for law in authority["kernel"]["admission"]["laws"]
        if law["id"] == "kernel.binding.exact"
    )
    binding_law["arguments"]["left"] = "language_bundle.host_invented_binding"
    _reidentify(authority["kernel"], authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )


def test_diagnostic_catalog_missing_extra_and_stage_drift_are_refused():
    mutations = []

    missing = authority_set()
    missing_ldb = missing["language_bundle"]
    missing_code = missing_ldb["diagnostics"][-1]["code"]
    missing_package = next(
        package
        for package in missing_ldb["language"]["packages"]
        if missing_code in package["exports"]["diagnostics"]
    )
    missing_definitions = next(
        entry["definitions"]
        for entry in missing_package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    missing_package["exports"]["diagnostics"].remove(missing_code)
    missing_definitions[:] = [
        definition
        for definition in missing_definitions
        if definition["code"] != missing_code
    ]
    _reidentify_package_release(missing_package)
    _reidentify_graph_root(missing_ldb)
    mutations.append(missing)

    extra = authority_set()
    extra_ldb = extra["language_bundle"]
    extra_package = extra_ldb["language"]["packages"][0]
    extra_package["exports"]["diagnostics"].append("language.unreachable")
    extra_definitions = next(
        entry["definitions"]
        for entry in extra_package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    extra_definitions.append({"code": "language.unreachable", "stage": "static"})
    _reidentify_package_release(extra_package)
    _reidentify_graph_root(extra_ldb)
    mutations.append(extra)

    drift = authority_set()
    drift_ldb = drift["language_bundle"]
    drift_code = drift_ldb["diagnostics"][0]["code"]
    drift_package = next(
        package
        for package in drift_ldb["language"]["packages"]
        if drift_code in package["exports"]["diagnostics"]
    )
    drift_definitions = next(
        entry["definitions"]
        for entry in drift_package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    next(
        definition
        for definition in drift_definitions
        if definition["code"] == drift_code
    )["stage"] = "resolution"
    _reidentify_package_release(drift_package)
    _reidentify_graph_root(drift_ldb)
    mutations.append(drift)

    for authority in mutations:
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert (
            "static",
            "kernel.diagnostic_closure",
            "language-bundle.diagnostics",
        ) in first["diagnostics"]


def test_reidentified_deletion_and_behavior_mutation_of_every_reason_refuse():
    baseline = authority_set()
    reasons = baseline["language_bundle"]["language"]["reasons"]

    for index in range(len(reasons)):
        for mutation in ("delete", "operation"):
            authority = deepcopy(baseline)
            ldb = authority["language_bundle"]
            reason_id = reasons[index]["id"]
            package = next(
                candidate
                for candidate in ldb["language"]["packages"]
                if reason_id in candidate["exports"]["reasons"]
            )
            target = next(
                entry["definitions"]
                for entry in package["semantic_closure"]
                if entry["authority_path"] == "language.reasons"
            )
            reason = next(
                definition for definition in target if definition["id"] == reason_id
            )
            if mutation == "delete":
                package["exports"]["reasons"].remove(reason_id)
                target.remove(reason)
            else:
                reason["predicate"]["operation"] += ".changed"
            _reidentify_package_release(package)
            _reidentify_graph_root(ldb)
            first = _consumer_a(authority["kernel"], ldb)
            second = _consumer_b(authority["kernel"], ldb)
            assert first == second
            assert first["admitted"] is False
            assert any(
                code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
            ), first["diagnostics"]


def test_reidentified_extra_members_cannot_extend_kernel_ldb_or_rule_shapes():
    baseline = authority_set()
    mutations = []

    kernel_extra = deepcopy(baseline)
    kernel_extra["kernel"]["host_extension"] = True
    _reidentify(kernel_extra["kernel"], kernel_extra["language_bundle"])
    mutations.append(kernel_extra)

    ldb_extra = deepcopy(baseline)
    ldb_extra["language_bundle"]["host_extension"] = True
    ldb_extra["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", ldb_extra["language_bundle"]
    )
    mutations.append(ldb_extra)

    rule_extra = deepcopy(baseline)
    rule_extra["language_bundle"]["language"]["rules"][0]["host_hook"] = "run"
    rule_extra["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", rule_extra["language_bundle"]
    )
    mutations.append(rule_extra)

    for authority in mutations:
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False


def test_two_consumers_agree_on_report_all_cap_and_truncation():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if "quantity.declare" in candidate["exports"]["language_rules"]
    )
    diagnostic_cap = authority["kernel"]["resources"]["max_diagnostics"]
    vector_set = _package_vector_set(ldb, package)
    for index in range(diagnostic_cap + 2):
        vector_id = f"mutant.{index}"
        vector_set["vectors"].append(vector_id)
        vector_set["vector_definitions"].append(
            {
                "expect": {},
                "id": vector_id,
                "input": {"facts": [], "judgment": "missing"},
                "rule": "quantity.declare",
            }
        )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["truncated"] is True
    assert len(first["diagnostics"]) == diagnostic_cap


def test_two_consumers_refuse_the_same_nesting_resource_exhaustion():
    authority = authority_set()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    nested: object = "leaf"
    for _ in range(authority["kernel"]["resources"]["max_nesting_depth"] + 1):
        nested = [nested]
    vector_set = _package_vector_set(ldb, package)
    vector_set["vector_definitions"][0]["unused_host_payload"] = nested
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["diagnostics"] == [
        ("ingress", "kernel.resource_exhausted", "language-bundle.package-vectors.0")
    ]


def test_two_consumers_refuse_the_same_noncanonical_integer():
    authority = authority_set()
    ldb = authority["language_bundle"]
    ldb.root["resources"]["max_source_bytes"] = 2**63

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert {code for _, code, _ in first["diagnostics"]} == {
        "kernel.identity_mismatch",
        "kernel.resource_exhausted",
    }


def test_two_consumers_refuse_a_closed_dependency_cycle():
    authority = authority_set()
    ldb = authority["language_bundle"]
    check = next(
        package
        for package in ldb["language"]["packages"]
        if package["id"] == "game.check"
    )
    check["dependencies"]["required"].append({"id": "game.combat", "version": "1.0.0"})
    _reidentify_package_release(check)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "ingress",
        "kernel.binding_mismatch",
        "language-bundle.package-dependencies",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "kernel.member_set_mismatch"),
        ("extra", "kernel.member_set_mismatch"),
        ("duplicate", "kernel.duplicate_identifier"),
        ("substituted", "kernel.binding_mismatch"),
        ("digest-mismatch", "kernel.binding_mismatch"),
        ("size-mismatch", "kernel.binding_mismatch"),
        ("coordinate-mismatch", "kernel.binding_mismatch"),
        ("unresolved-dependency", "kernel.binding_mismatch"),
        ("wrong-dependency-version", "kernel.binding_mismatch"),
        ("same-coordinate-different-content", "kernel.duplicate_identifier"),
    ),
)
def test_two_consumers_refuse_adversarial_graph_membership_and_binding(
    mutation, expected_code
):
    authority = authority_set()
    ldb = authority["language_bundle"]

    if mutation == "missing":
        ldb.package_releases.pop()
        ldb.package_conformance_vector_sets.pop()
        ldb.package_byte_sizes = ldb.package_byte_sizes[:-1]
        ldb.vector_set_byte_sizes = ldb.vector_set_byte_sizes[:-1]
    elif mutation == "extra":
        ldb.package_releases.append(deepcopy(ldb.package_releases[-1]))
        ldb.package_conformance_vector_sets.append(
            deepcopy(ldb.package_conformance_vector_sets[-1])
        )
        ldb.package_byte_sizes += (ldb.package_byte_sizes[-1],)
        ldb.vector_set_byte_sizes += (ldb.vector_set_byte_sizes[-1],)
    elif mutation in {"duplicate", "same-coordinate-different-content"}:
        duplicate = deepcopy(ldb.package_releases[-1])
        if mutation == "same-coordinate-different-content":
            duplicate["dependencies"]["optional"].append(
                {"id": "game.check", "version": "1.0.0"}
            )
            _reidentify_package_release(duplicate)
        ldb["language"]["packages"].append(duplicate)
        _reidentify_graph_root(ldb)
    elif mutation == "substituted":
        ldb.package_releases[0] = deepcopy(ldb.package_releases[-1])
    elif mutation == "digest-mismatch":
        ldb.root["package_descriptors"][0]["content_identity"] = "sha256:" + "0" * 64
    elif mutation == "size-mismatch":
        ldb.package_byte_sizes = (ldb.package_byte_sizes[0] + 1,) + tuple(
            ldb.package_byte_sizes[1:]
        )
    elif mutation == "coordinate-mismatch":
        ldb.root["package_descriptors"][0]["id"] = "core.substituted"
    else:
        package = ldb["language"]["packages"][0]
        if mutation == "wrong-dependency-version":
            package["dependencies"]["required"][0]["version"] = "9.0.0"
        else:
            package["dependencies"]["required"].append(
                {"id": "host.missing", "version": "1.0.0"}
            )
        _reidentify_package_release(package)
        _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == expected_code for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "kernel.member_set_mismatch"),
        ("extra", "kernel.member_set_mismatch"),
        ("substituted", "kernel.binding_mismatch"),
        ("digest-mismatch", "kernel.binding_mismatch"),
        ("size-mismatch", "kernel.binding_mismatch"),
        ("coordinate-mismatch", "kernel.binding_mismatch"),
        ("malformed", "kernel.identity_mismatch"),
    ),
)
def test_two_consumers_refuse_adversarial_package_vector_children(
    mutation, expected_code
):
    authority = authority_set()
    ldb = authority["language_bundle"]

    if mutation == "missing":
        ldb.package_conformance_vector_sets.pop()
        ldb.vector_set_byte_sizes = ldb.vector_set_byte_sizes[:-1]
    elif mutation == "extra":
        ldb.package_conformance_vector_sets.append(
            deepcopy(ldb.package_conformance_vector_sets[-1])
        )
        ldb.vector_set_byte_sizes += (ldb.vector_set_byte_sizes[-1],)
    elif mutation == "substituted":
        ldb.package_conformance_vector_sets[0] = deepcopy(
            ldb.package_conformance_vector_sets[-1]
        )
    elif mutation == "digest-mismatch":
        ldb.package_conformance_vector_sets[0]["content_identity"] = (
            "sha256:" + "0" * 64
        )
    elif mutation == "size-mismatch":
        ldb.vector_set_byte_sizes = (ldb.vector_set_byte_sizes[0] + 1,) + tuple(
            ldb.vector_set_byte_sizes[1:]
        )
    elif mutation == "coordinate-mismatch":
        ldb.package_conformance_vector_sets[0]["package_id"] = "core.substituted"
    else:
        ldb.package_conformance_vector_sets[0].pop("vectors")

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == expected_code for _, code, _ in first["diagnostics"])


def test_descriptor_transport_order_does_not_change_the_canonical_graph():
    authority = authority_set()
    baseline = authority["language_bundle"]
    reordered_root = deepcopy(baseline.root)
    reordered_root["package_descriptors"].reverse()
    reordered = LanguageBundleGraph(
        root=reordered_root,
        package_releases=list(reversed(baseline.package_releases)),
        package_conformance_vector_sets=list(
            reversed(baseline.package_conformance_vector_sets)
        ),
        root_byte_size=baseline.root_byte_size,
        package_byte_sizes=list(reversed(baseline.package_byte_sizes)),
        vector_set_byte_sizes=list(reversed(baseline.vector_set_byte_sizes)),
    )

    first = _consumer_a(authority["kernel"], reordered)
    second = _consumer_b(authority["kernel"], reordered)

    assert first == second
    assert first["admitted"] is True
    assert reordered.root["package_descriptors"] == list(
        reversed(baseline.root["package_descriptors"])
    )
    assert first["language_bundle_identity"] == baseline["content_identity"]


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


@pytest.mark.parametrize(
    "limit_name",
    (
        "max_ldb_root_bytes",
        "max_ldb_child_bytes",
        "max_ldb_package_bytes",
        "max_ldb_total_bytes",
        "max_ldb_package_count",
        "max_ldb_package_member_count",
        "max_ldb_dependency_depth",
        "max_ldb_dependency_steps",
        "max_ldb_admission_work",
    ),
)
def test_two_consumers_agree_at_and_above_each_graph_resource_boundary(
    monkeypatch, limit_name
):
    baseline = authority_set()
    observed = _graph_metrics(baseline["language_bundle"])[limit_name]

    for limit, admitted in ((observed, True), (observed - 1, False)):
        authority = deepcopy(baseline)
        authority["kernel"]["resources"][limit_name] = limit
        _reidentify(authority["kernel"], authority["language_bundle"])
        kernel_identity = authority["kernel"]["content_identity"]
        monkeypatch.setattr(
            production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
        )
        monkeypatch.setitem(globals(), "_SUPPORTED_KERNEL_IDENTITY", kernel_identity)

        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])

        assert first == second
        assert first["admitted"] is admitted
        if not admitted:
            assert (
                "ingress",
                "kernel.resource_exhausted",
                "language-bundle",
            ) in first["diagnostics"]


@pytest.mark.parametrize(
    ("limit_name", "shape_index"),
    (("max_nesting_depth", 0), ("max_members", 1)),
)
def test_two_consumers_agree_at_and_above_each_authority_shape_boundary(
    monkeypatch, limit_name, shape_index
):
    baseline = authority_set()
    ldb = baseline["language_bundle"]
    artifacts = [
        baseline["kernel"],
        ldb.root,
        *ldb.package_releases,
        *ldb.package_conformance_vector_sets,
    ]
    observed = max(_shape(artifact)[shape_index] for artifact in artifacts)

    for limit, admitted in ((observed, True), (observed - 1, False)):
        authority = deepcopy(baseline)
        authority["kernel"]["resources"][limit_name] = limit
        _reidentify(authority["kernel"], authority["language_bundle"])
        kernel_identity = authority["kernel"]["content_identity"]
        monkeypatch.setattr(
            production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
        )
        monkeypatch.setitem(globals(), "_SUPPORTED_KERNEL_IDENTITY", kernel_identity)

        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])

        assert first == second
        assert first["admitted"] is admitted
        if not admitted:
            assert any(
                code == "kernel.resource_exhausted"
                for _stage, code, _subject in first["diagnostics"]
            )
