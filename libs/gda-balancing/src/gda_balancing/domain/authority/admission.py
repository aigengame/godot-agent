"""Domain admission for the Schema 2.0 Kernel/LDB pair.

The consumer implements the Kernel's small, closed meta-operation set.  It
does not contain Quantity rule dispatch: LDB rules are checked through their
declared generic inputs/result and normative vectors.
"""

import json
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.authority.graph import (
    LanguageBundleGraph,
    LanguageBundleIndex,
    canonical_graph_members,
    derive_language_index,
)
from gda_balancing.domain.authority.package_validation import (
    _diagnostic_catalog_matches_vectors,
    _package_conformance_vector_set_is_closed,
    _package_evidence_vectors_are_closed,
    _package_is_closed,
    _package_semantic_closure_is_closed,
    _package_semantic_projections_are_exact,
)
from gda_balancing.domain.authority.runtime_validation import (
    _operation_result_source_shape_is_closed,
    _runtime_authority_is_closed,
    derive_operation_value_contracts,
)
from gda_balancing.domain.authority.template_validation import (
    _template_admission_profiles_are_closed,
)
from gda_balancing.domain.authority.contract_validation import (
    _meta_validate_json_schema,
    _path_is_declared,
    _path_values,
    _value_matches_contract,
)
from gda_balancing.domain.authority.vector_validation import (
    _execute_reason_vector,
    _execute_rule_vector,
    _fact_schemas,
    _package_vector_contract_is_closed,
    _reason_is_closed,
    _reason_vectors_cover_operands,
    _rule_is_closed,
    _vector_header_is_closed,
)
from gda_balancing.domain.operation_program import project_operation_program

SCHEMA2_REFUSAL_STAGES = (
    "ingress",
    "parse",
    "static",
    "resolution",
    "runtime",
    "evaluation",
    "migration",
    "approval",
)
BOOTSTRAP_REFUSAL_CATALOG = (
    ("kernel.binding_mismatch", "ingress"),
    ("kernel.diagnostic_closure", "static"),
    ("kernel.duplicate_identifier", "static"),
    ("kernel.identity_mismatch", "ingress"),
    ("kernel.member_set_mismatch", "ingress"),
    ("kernel.resource_exhausted", "ingress"),
    ("kernel.unknown_operation", "static"),
    ("kernel.vector_mismatch", "static"),
)
_SUPPORTED_KERNEL_IDENTITY = (
    "sha256:12e6497c361d7f86e417963ab7ee402822025aae34eb63cf672bcf8cc494fb26"
)
_SUPPORTED_CANONICAL_PROFILE: dict[str, Any] = {
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
_KERNEL_MEMBERS = frozenset(
    {
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
)
_KNOWN_OPERATIONS = frozenset(
    {
        "verify-content-identity",
        "require-equal",
        "require-exact-members",
        "require-unique-identifiers",
        "require-known-operations",
        "require-vector-closure",
        "require-diagnostic-closure",
        "enforce-resource-limits",
    }
)


@dataclass(frozen=True)
class AdmissionDiagnostic:
    code: str
    stage: str
    subject: str


@dataclass(frozen=True)
class BootstrapAdmission:
    admitted: bool
    kernel_identity: str | None
    language_bundle_identity: str | None
    law_ids: tuple[str, ...]
    law_projections: tuple[tuple[str, str], ...]
    rule_ids: tuple[str, ...]
    rule_projections: tuple[tuple[str, str], ...]
    diagnostic_projections: tuple[tuple[str, str, str], ...]
    diagnostics: tuple[AdmissionDiagnostic, ...]
    truncated: bool


def _artifact_identity(domain: str, artifact: dict[str, Any]) -> str:
    body = {key: value for key, value in artifact.items() if key != "content_identity"}
    return content_identity(domain, cast(JsonValue, body))


def _strict_json_value(text: str) -> JsonValue:
    def reject_number(_value: str) -> Any:
        raise ValueError("non-integer number is outside canonical JSON")

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key is outside canonical JSON")
            result[key] = value
        return result

    return cast(
        JsonValue,
        json.loads(
            text,
            object_pairs_hook=closed_object,
            parse_float=reject_number,
            parse_constant=reject_number,
        ),
    )


def _canonical_contract_is_supported(canonical_encoding: Any) -> bool:
    if not isinstance(canonical_encoding, dict):
        return False
    vectors = canonical_encoding.get("vectors")
    profile = {
        key: value for key, value in canonical_encoding.items() if key != "vectors"
    }
    if profile != _SUPPORTED_CANONICAL_PROFILE or not isinstance(vectors, list):
        return False
    expected_ids = {
        "canonical.boundary-integers",
        "canonical.control-character-escaping",
        "canonical.order-array-unicode-escaping",
        "canonical.reject-duplicate-key",
        "canonical.reject-float",
        "canonical.reject-lone-surrogate",
    }
    if {item.get("id") for item in vectors if isinstance(item, dict)} != expected_ids:
        return False
    for vector in vectors:
        if not isinstance(vector, dict):
            return False
        if "value" in vector:
            if set(vector) != {
                "canonical_utf8_hex",
                "domain",
                "id",
                "identity",
                "value",
            }:
                return False
            value = cast(JsonValue, vector["value"])
            domain = vector.get("domain")
            if (
                not isinstance(domain, str)
                or canonical_bytes(value).hex() != vector.get("canonical_utf8_hex")
                or content_identity(domain, value) != vector.get("identity")
            ):
                return False
        else:
            if set(vector) != {"id", "input_lexeme", "refusal"} or not isinstance(
                vector.get("input_lexeme"), str
            ):
                return False
            try:
                canonical_bytes(_strict_json_value(vector["input_lexeme"]))
            except (TypeError, ValueError, UnicodeEncodeError):
                continue
            return False
    return True


def _safe_artifact_identity(
    domain: Any,
    artifact: dict[str, Any],
    canonical_encoding: Any,
) -> str | None:
    if not isinstance(domain, str) or not domain:
        return None
    try:
        supported = _canonical_contract_is_supported(canonical_encoding)
    except (TypeError, ValueError, UnicodeEncodeError):
        supported = False
    if not supported:
        return None
    try:
        return _artifact_identity(domain, artifact)
    except (TypeError, ValueError):
        return None


def _declared_identity_domain(
    kernel: dict[str, Any],
    *,
    artifact: str | None = None,
    collection: str | None = None,
) -> str | None:
    if (artifact is None) == (collection is None):
        return None
    laws = kernel.get("admission", {}).get("laws")
    if not isinstance(laws, list):
        return None
    identity_laws = [
        law
        for law in laws
        if isinstance(law, dict) and law.get("id") == "kernel.identity.verify"
    ]
    if len(identity_laws) != 1:
        return None
    targets = identity_laws[0].get("arguments", {}).get("targets")
    if not isinstance(targets, list):
        return None
    selector = "artifact" if artifact is not None else "collection"
    expected = artifact if artifact is not None else collection
    matches = [
        target
        for target in targets
        if isinstance(target, dict) and target.get(selector) == expected
    ]
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


def _resource_shape(value: Any) -> tuple[int, int]:
    """Return maximum nesting depth and largest single collection iteratively."""
    maximum_depth = 0
    maximum_members = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        maximum_depth = max(maximum_depth, depth)
        if isinstance(current, dict):
            maximum_members = max(maximum_members, len(current))
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            maximum_members = max(maximum_members, len(current))
            stack.extend((item, depth + 1) for item in current)
    return maximum_depth, maximum_members


def _resource_work(value: Any) -> int:
    """Count deterministic observation work as visited canonical JSON nodes."""
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


def _language_bundle_is_closed(
    language_bundle: dict[str, Any], contract: Any, refusal_stages: Any
) -> bool:
    if not isinstance(contract, dict) or contract.get("closed") is not True:
        return False
    required = contract.get("required_members")
    member_types = contract.get("member_types")
    diagnostics_contract = contract.get("diagnostic")
    resources_contract = contract.get("resources")
    if (
        not isinstance(required, list)
        or set(language_bundle) != set(required)
        or not isinstance(member_types, dict)
        or set(member_types) != set(required)
        or not isinstance(refusal_stages, list)
        or tuple(refusal_stages) != SCHEMA2_REFUSAL_STAGES
    ):
        return False
    for name, value_contract in member_types.items():
        if name == "diagnostics":
            if not isinstance(language_bundle[name], list):
                return False
        elif not _value_matches_contract(
            language_bundle[name], value_contract, language_bundle
        ):
            return False
    if not isinstance(diagnostics_contract, dict):
        return False
    diagnostic_members = diagnostics_contract.get("required_members")
    diagnostic_types = diagnostics_contract.get("field_types")
    diagnostics = language_bundle["diagnostics"]
    if (
        not isinstance(diagnostic_members, list)
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
    resources = language_bundle["resources"]
    return (
        isinstance(resources, dict)
        and isinstance(resource_members, list)
        and set(resources) == set(resource_members)
        and isinstance(resource_types, dict)
        and set(resource_types) == set(resource_members)
        and all(
            _value_matches_contract(
                resources[name], resource_types[name], language_bundle
            )
            for name in resource_members
        )
    )


def _embedded_artifact_bindings_are_closed(
    language_bundle: dict[str, Any],
) -> bool:
    """Close schema-embedded artifacts over their identity and LDB-owned contract."""
    language = language_bundle.get("language")
    if not isinstance(language, dict):
        return False
    contracts = language.get("artifact_contracts")
    schema_entries = language.get("artifact_wire_schemas")
    if not isinstance(contracts, list) or not isinstance(schema_entries, list):
        return False
    if not all(isinstance(item, dict) for item in contracts + schema_entries):
        return False
    contracts_by_kind = {
        item.get("artifact_kind"): item
        for item in contracts
        if isinstance(item.get("artifact_kind"), str)
    }
    schemas_by_kind = {
        item.get("artifact_kind"): item.get("schema")
        for item in schema_entries
        if isinstance(item.get("artifact_kind"), str)
        and isinstance(item.get("schema"), dict)
    }
    if len(contracts_by_kind) != len(contracts) or len(schemas_by_kind) != len(
        schema_entries
    ):
        return False

    canonical_binding_by_kind: dict[str, bytes] = {}
    for owner in schema_entries:
        owner_schema = owner.get("schema")
        properties = (
            owner_schema.get("properties") if isinstance(owner_schema, dict) else None
        )
        if not isinstance(properties, dict):
            continue
        for member_schema in properties.values():
            if not isinstance(member_schema, dict):
                continue
            embedded = member_schema.get("const")
            if not isinstance(embedded, dict) or "artifact_kind" not in embedded:
                continue
            artifact_kind = embedded.get("artifact_kind")
            content_id = embedded.get("content_identity")
            wire_schema_id = embedded.get("wire_schema_identity")
            if (
                not isinstance(artifact_kind, str)
                or not artifact_kind
                or not isinstance(content_id, str)
                or not content_id
                or not isinstance(wire_schema_id, str)
                or not wire_schema_id
            ):
                return False
            identity_bindings = [
                candidate.get("const")
                for candidate in properties.values()
                if isinstance(candidate, dict)
                and isinstance(candidate.get("const"), str)
                and candidate.get("const") == content_id
            ]
            if len(identity_bindings) != 1:
                return False

            contract = contracts_by_kind.get(artifact_kind)
            if not isinstance(contract, dict):
                return False
            schema_kind = contract.get("schema_kind")
            identity_domain = contract.get("identity_domain")
            wire_identity_domain = contract.get("wire_schema_identity_domain")
            excluded = contract.get("identity_excluded_members")
            artifact_schema = schemas_by_kind.get(schema_kind)
            if (
                not isinstance(schema_kind, str)
                or not isinstance(identity_domain, str)
                or not isinstance(wire_identity_domain, str)
                or not isinstance(excluded, list)
                or not all(isinstance(member, str) for member in excluded)
                or not isinstance(artifact_schema, dict)
            ):
                return False
            try:
                jsonschema.Draft202012Validator(artifact_schema).validate(embedded)
                schema_body = {
                    key: value for key, value in artifact_schema.items() if key != "$id"
                }
                expected_wire_schema_id = content_identity(
                    wire_identity_domain, cast(JsonValue, schema_body)
                )
                identity_body = {
                    key: value
                    for key, value in embedded.items()
                    if key != "content_identity" and key not in excluded
                }
                expected_content_id = content_identity(
                    identity_domain, cast(JsonValue, identity_body)
                )
                canonical_binding = canonical_bytes(cast(JsonValue, embedded))
            except (
                TypeError,
                ValueError,
                UnicodeEncodeError,
                jsonschema.ValidationError,
            ):
                return False
            if (
                wire_schema_id != expected_wire_schema_id
                or content_id != expected_content_id
            ):
                return False
            previous = canonical_binding_by_kind.setdefault(
                artifact_kind, canonical_binding
            )
            if previous != canonical_binding:
                return False
    return True


def _wire_schema_identity_domains_are_closed(
    language_bundle: dict[str, Any],
) -> bool:
    language = language_bundle.get("language")
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


def _profiled_equality_values(
    authorities: dict[str, Any], contract: dict[str, Any]
) -> list[Any] | None:
    profile_contract = contract.get("profile")
    template = contract.get("right_template")
    if (
        not isinstance(profile_contract, dict)
        or set(profile_contract)
        != {
            "owner_profile_member",
            "owners",
            "profile_key_member",
            "profiles",
        }
        or not isinstance(template, list)
        or not template
        or not all(
            (isinstance(segment, str) and bool(segment))
            or (
                isinstance(segment, dict)
                and set(segment) == {"profile_member"}
                and isinstance(segment["profile_member"], str)
                and bool(segment["profile_member"])
            )
            for segment in template
        )
    ):
        return None
    owners_path = profile_contract.get("owners")
    profiles_path = profile_contract.get("profiles")
    owner_profile_member = profile_contract.get("owner_profile_member")
    profile_key_member = profile_contract.get("profile_key_member")
    if (
        not isinstance(owners_path, str)
        or not _path_is_declared(authorities, owners_path)
        or not isinstance(profiles_path, str)
        or not _path_is_declared(authorities, profiles_path)
        or not isinstance(owner_profile_member, str)
        or not owner_profile_member
        or not isinstance(profile_key_member, str)
        or not profile_key_member
    ):
        return None
    owners = _path_values(authorities, owners_path)
    profiles = _path_values(authorities, profiles_path)
    if not owners or not profiles:
        return None
    profile_rows = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile_key_member in profile
    ]
    profile_keys = [profile[profile_key_member] for profile in profile_rows]
    if len(profile_rows) != len(profiles) or len(profile_keys) != len(
        set(profile_keys)
    ):
        return None
    profiles_by_key = dict(zip(profile_keys, profile_rows, strict=True))
    selected_profiles: list[dict[str, Any]] = []
    for owner in owners:
        if (
            not isinstance(owner, dict)
            or owner_profile_member not in owner
            or owner[owner_profile_member] not in profiles_by_key
        ):
            return None
        profile = profiles_by_key[owner[owner_profile_member]]
        if profile not in selected_profiles:
            selected_profiles.append(profile)

    values: list[Any] = []
    for profile in selected_profiles:
        segments: list[str] = []
        for segment in template:
            if isinstance(segment, str):
                segments.append(segment)
                continue
            profile_value = profile.get(segment["profile_member"])
            if not isinstance(profile_value, str) or not profile_value:
                return None
            segments.append(profile_value)
        selected: list[Any] = [authorities]
        for segment in segments:
            expanded: list[Any] = []
            for value in selected:
                candidates = value if isinstance(value, list) else [value]
                for candidate in candidates:
                    if not isinstance(candidate, dict) or segment not in candidate:
                        continue
                    child = candidate[segment]
                    expanded.extend(child if isinstance(child, list) else [child])
            if not expanded:
                return None
            selected = expanded
        values.extend(selected)
    return values


def _reference_contracts_close(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> bool:
    laws = kernel.get("admission", {}).get("laws", [])
    vector_law = next(
        (
            law
            for law in laws
            if isinstance(law, dict) and law.get("id") == "kernel.vectors.closed"
        ),
        None,
    )
    if not isinstance(vector_law, dict):
        return False
    references = vector_law.get("arguments", {}).get("references")
    equalities = vector_law.get("arguments", {}).get("equalities")
    correlations = vector_law.get("arguments", {}).get("correlations")
    if (
        not isinstance(references, list)
        or not isinstance(equalities, list)
        or not isinstance(correlations, list)
    ):
        return False
    authorities = {"kernel": kernel, "language_bundle": language_bundle}
    for contract in correlations:
        if not isinstance(contract, dict):
            return False
        collection_contract = {
            "owners",
            "owner_value_member",
            "references_member",
            "targets",
            "target_key_member",
            "target_value_member",
        }
        alternative_contract = {
            "alternatives",
            "owners",
            "references_member",
            "targets",
            "target_key_member",
        }
        invocation_contract = {
            "equal_members",
            "owner_key_member",
            "owners",
            "target_key_member",
            "targets",
        }
        if set(contract) == invocation_contract:
            owners = _path_values(authorities, contract["owners"])
            targets = _path_values(authorities, contract["targets"])
            equal_members = contract["equal_members"]
            owner_key_member = contract["owner_key_member"]
            target_key_member = contract["target_key_member"]
            if (
                not _path_is_declared(authorities, contract["owners"])
                or not _path_is_declared(authorities, contract["targets"])
                or not isinstance(equal_members, list)
                or not equal_members
                or not all(
                    isinstance(member, str) and member for member in equal_members
                )
                or not isinstance(owner_key_member, str)
                or not isinstance(target_key_member, str)
            ):
                return False
            target_rows = [
                target
                for target in targets
                if isinstance(target, dict) and target_key_member in target
            ]
            target_keys = [target[target_key_member] for target in target_rows]
            if len(target_keys) != len(set(target_keys)):
                return False
            targets_by_key = dict(zip(target_keys, target_rows, strict=True))
            if any(
                not isinstance(owner, dict)
                or owner_key_member not in owner
                or owner[owner_key_member] not in targets_by_key
                or any(
                    owner.get(member)
                    != targets_by_key[owner[owner_key_member]].get(member)
                    for member in equal_members
                )
                for owner in owners
            ):
                return False
            continue
        if set(contract) == alternative_contract:
            owners = _path_values(authorities, contract["owners"])
            targets = _path_values(authorities, contract["targets"])
            alternatives = contract["alternatives"]
            references_member = contract["references_member"]
            target_key_member = contract["target_key_member"]
            if (
                not _path_is_declared(authorities, contract["owners"])
                or not _path_is_declared(authorities, contract["targets"])
                or not isinstance(alternatives, list)
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
                or not isinstance(references_member, str)
                or not references_member
                or not isinstance(target_key_member, str)
                or not target_key_member
            ):
                return False
            target_rows = [
                target
                for target in targets
                if isinstance(target, dict) and target_key_member in target
            ]
            target_keys = [target[target_key_member] for target in target_rows]
            if len(target_keys) != len(set(target_keys)):
                return False
            targets_by_key = dict(zip(target_keys, target_rows, strict=True))
            if any(
                not isinstance(owner, dict)
                or not isinstance(owner.get(references_member), list)
                or any(
                    reference not in targets_by_key
                    or not any(
                        alternative["owner_member"] in owner
                        and alternative["target_member"] in targets_by_key[reference]
                        and owner[alternative["owner_member"]]
                        == targets_by_key[reference][alternative["target_member"]]
                        for alternative in alternatives
                    )
                    for reference in owner[references_member]
                )
                for owner in owners
            ):
                return False
            continue
        if set(contract) != collection_contract:
            return False
        owners = _path_values(authorities, contract["owners"])
        targets = _path_values(authorities, contract["targets"])
        owner_value_member = contract["owner_value_member"]
        references_member = contract["references_member"]
        target_key_member = contract["target_key_member"]
        target_value_member = contract["target_value_member"]
        if (
            not _path_is_declared(authorities, contract["owners"])
            or not _path_is_declared(authorities, contract["targets"])
            or not all(
                isinstance(name, str) and name
                for name in (
                    owner_value_member,
                    references_member,
                    target_key_member,
                    target_value_member,
                )
            )
        ):
            return False
        target_values = {
            target[target_key_member]: target.get(target_value_member)
            for target in targets
            if isinstance(target, dict) and target_key_member in target
        }
        for owner in owners:
            if (
                not isinstance(owner, dict)
                or owner_value_member not in owner
                or not isinstance(owner.get(references_member), list)
                or any(
                    reference not in target_values
                    or target_values[reference] != owner[owner_value_member]
                    for reference in owner[references_member]
                )
            ):
                return False
    for contract in equalities:
        if not isinstance(contract, dict) or contract.get("mode") != "set":
            return False
        if set(contract) == {"left", "mode", "right"}:
            if not _path_is_declared(
                authorities, contract.get("left")
            ) or not _path_is_declared(authorities, contract.get("right")):
                return False
            right_values = _path_values(authorities, contract["right"])
        elif set(contract) == {
            "left",
            "mode",
            "profile",
            "right_template",
        }:
            if not _path_is_declared(authorities, contract.get("left")):
                return False
            right_values = _profiled_equality_values(authorities, contract)
            if right_values is None:
                return False
        else:
            return False
        try:
            if set(_path_values(authorities, contract["left"])) != set(right_values):
                return False
        except TypeError:
            return False
    for contract in references:
        if not isinstance(contract, dict):
            return False
        owners = _path_values(authorities, contract.get("owners"))
        targets = contract.get("targets")
        if not _path_is_declared(authorities, contract.get("owners")) or not isinstance(
            targets, dict
        ):
            return False
        # Reference contracts quantify the rows that exist. A declared empty
        # owner collection is closed by construction; optional language
        # collections such as Conversions must not require a fabricated row.
        for owner in owners:
            if not isinstance(owner, dict):
                return False
            for source_path, target_path in targets.items():
                if not _path_is_declared(owner, source_path) or not _path_is_declared(
                    authorities, target_path
                ):
                    return False
                source_values = _path_values(owner, source_path)
                target_values = _path_values(authorities, target_path)
                if any(value not in target_values for value in source_values):
                    return False
    return True


def _duplicate_identifier_subjects(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> set[str]:
    laws = kernel.get("admission", {}).get("laws", [])
    uniqueness_law = next(
        (
            law
            for law in laws
            if isinstance(law, dict) and law.get("id") == "kernel.identifiers.unique"
        ),
        None,
    )
    if not isinstance(uniqueness_law, dict):
        return {"kernel.admission.laws"}
    collections = uniqueness_law.get("arguments", {}).get("collections")
    if not isinstance(collections, list):
        return {"kernel.admission.laws"}
    authorities = {"kernel": kernel, "language_bundle": language_bundle}
    duplicates: set[str] = set()
    for contract in collections:
        if not isinstance(contract, dict):
            duplicates.add("kernel.admission.laws")
            continue
        keys = contract.get("keys")
        path = contract.get("path")
        subject = contract.get("subject")
        items = _path_values(authorities, path)
        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(key, str) and key for key in keys)
            or not isinstance(subject, str)
            or not subject
        ):
            duplicates.add(str(subject or path or "kernel.admission.laws"))
            continue
        identities: list[tuple[Any, ...]] = []
        for item in items:
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


def _definition_is_closed(
    value: Any,
    contract: Any,
    language_bundle: dict[str, Any],
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
            _value_matches_contract(value[name], field_types[name], language_bundle)
            for name in value
        )
    )


def _fact_contract_at_path(fields: dict[str, Any], path: Any) -> dict[str, Any] | None:
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


def _fact_contract_path_is_declared(fields: dict[str, Any], path: Any) -> bool:
    return _fact_contract_at_path(fields, path) is not None


def _resolution_judgment_is_closed(contract: Any) -> bool:
    if (
        not isinstance(contract, dict)
        or set(contract)
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
        or contract.get("closed") is not True
    ):
        return False
    stages = contract.get("stage_order")
    relations = contract.get("relation_schemas")
    operations = contract.get("operations")
    law_format = contract.get("law_format")
    recipe_format = contract.get("relation_recipe_format")
    routing_equivalences = contract.get("routing_equivalences")
    resource_accounting = contract.get("resource_accounting")
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
            or not isinstance(relation.get("fields"), list)
            or not relation["fields"]
            or not all(isinstance(field, str) and field for field in relation["fields"])
            or len(relation["fields"]) != len(set(relation["fields"]))
            or not isinstance(relation.get("pointer_fields"), list)
            or not all(
                isinstance(field, str) and field for field in relation["pointer_fields"]
            )
            or not set(relation["pointer_fields"]) <= set(relation["fields"])
            or relation["id"] in relation_fields
        ):
            return False
        relation_fields[relation["id"]] = set(relation["fields"])
    law_specs = {
        item["id"]: item
        for item in law_format["operators"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(law_specs) != len(law_format["operators"]):
        return False
    for spec in law_specs.values():
        required = spec.get("required_members")
        optional = spec.get("optional_members")
        if (
            set(spec)
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
    operation_ids: set[str] = set()
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
            or operation["id"] in operation_ids
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
        operation_ids.add(operation["id"])
        law = operation["law"]
        spec = law_specs.get(law.get("operator"))
        if not isinstance(spec, dict):
            return False
        required_members = set(spec["required_members"])
        optional_members = set(spec["optional_members"])
        if not required_members <= set(law) or not set(law) <= (
            required_members | optional_members
        ):
            return False
        operator = law["operator"]
        if operator == "require-match":
            subject_fields = relation_fields.get(law.get("subject_relation"))
            target_fields = relation_fields.get(law.get("target_relation"))
            matches = law.get("match")
            cardinalities = spec.get("cardinalities")
            if (
                subject_fields is None
                or target_fields is None
                or not isinstance(matches, list)
                or not matches
                or not isinstance(cardinalities, list)
                or law.get("cardinality") not in cardinalities
                or law.get("pointer_field") not in subject_fields
                or any(
                    not isinstance(match, dict)
                    or set(match) != {"subject", "target"}
                    or match.get("subject") not in subject_fields
                    or match.get("target") not in target_fields
                    for match in matches
                )
            ):
                return False
            guard = law.get("guard")
            if guard is not None:
                guard_relation = (
                    guard.get("target_relation") if isinstance(guard, dict) else None
                )
                guard_fields = (
                    relation_fields.get(guard_relation)
                    if isinstance(guard_relation, str)
                    else None
                )
                if (
                    not isinstance(guard, dict)
                    or set(guard) != {"target_relation", "match", "cardinality"}
                    or guard_fields is None
                    or guard.get("cardinality") not in cardinalities
                    or not isinstance(guard.get("match"), list)
                    or not guard["match"]
                    or any(
                        not isinstance(match, dict)
                        or set(match) != {"subject", "target"}
                        or match.get("subject") not in subject_fields
                        or match.get("target") not in guard_fields
                        for match in guard["match"]
                    )
                ):
                    return False
        elif operator in {"require-unique", "require-single-value"}:
            fields = relation_fields.get(law.get("relation"))
            list_members = (
                ("scope", "key")
                if operator == "require-unique"
                else ("scope", "group", "value")
            )
            if (
                fields is None
                or law.get("pointer_field") not in fields
                or any(
                    not isinstance(law.get(member), list)
                    or not all(field in fields for field in law[member])
                    for member in list_members
                )
                or (
                    operator == "require-unique" and not cast(list[Any], law.get("key"))
                )
                or (
                    operator == "require-single-value"
                    and (
                        not cast(list[Any], law.get("group"))
                        or not cast(list[Any], law.get("value"))
                    )
                )
            ):
                return False
        else:
            return False
    flattened = [
        operation["id"]
        for stage in stages
        for operation in operations
        if operation["stage"] == stage
    ]
    return flattened == [operation["id"] for operation in operations]


def _json_schema_path(schema: Any, path: list[str]) -> dict[str, Any] | None:
    current = schema
    for segment in path:
        if (
            not isinstance(current, dict)
            or current.get("type") != "object"
            or not isinstance(current.get("properties"), dict)
            or segment not in current["properties"]
        ):
            return None
        current = current["properties"][segment]
    return current if isinstance(current, dict) else None


def _schema_value_kind(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    value_type = schema.get("type")
    if isinstance(value_type, str):
        return value_type
    if "const" in schema:
        value = schema["const"]
        if isinstance(value, str):
            return "string"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        kinds = {_canonical_value_kind(value) for value in schema["enum"]}
        if len(kinds) == 1:
            return kinds.pop()
    return None


def _canonical_value_kind(value: Any) -> str | None:
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


def _package_release_path_contract(
    contract: dict[str, Any], path: list[str]
) -> dict[str, Any] | None:
    if not path:
        return contract
    if len(path) == 1:
        field_types = contract.get("field_types")
        selected = field_types.get(path[0]) if isinstance(field_types, dict) else None
        return selected if isinstance(selected, dict) else None
    if len(path) != 2:
        return None
    nested = contract.get("nested_field_types")
    group = nested.get(path[0]) if isinstance(nested, dict) else None
    selected = group.get(path[1]) if isinstance(group, dict) else None
    if not isinstance(selected, dict):
        return None
    if path == ["exports", "types"]:
        item = contract.get("type_export")
        if not isinstance(item, dict):
            return None
        return {**selected, "items": item}
    return selected


def _contract_value_kind(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    value_type = contract.get("type")
    if value_type in {"inventory-member", "non-empty-string", "string"}:
        return "string"
    if value_type in {"list", "list-of", "string-list"}:
        return "array"
    if value_type in {
        "closed-discriminated-object",
        "closed-int64-interval",
        "closed-object",
    } or ("required_members" in contract and "field_types" in contract):
        return "object"
    if value_type in {"positive-signed-int64", "signed-int64"}:
        return "integer"
    if value_type == "boolean":
        return "boolean"
    if "const" in contract:
        return _canonical_value_kind(contract["const"])
    return None


def _relation_recipe_paths_are_typed(
    profile: dict[str, Any],
    language_bundle: dict[str, Any],
    resolution_contract: dict[str, Any],
    package_release_contract: dict[str, Any],
) -> bool:
    language = language_bundle.get("language")
    wire_schemas = language.get("wire_schemas") if isinstance(language, dict) else None
    if not isinstance(language, dict) or not isinstance(wire_schemas, list):
        return False
    source_schemas = [
        item.get("schema")
        for item in wire_schemas
        if isinstance(item, dict)
        and item.get("artifact_kind") == "model-source-package"
    ]
    if len(source_schemas) != 1 or not isinstance(source_schemas[0], dict):
        return False
    source_schema = source_schemas[0]
    recipes = profile["relation_recipes"]
    recipe_by_id = {recipe["id"]: recipe for recipe in recipes}

    # A shape is (representation, schema-or-values, source-origin).
    def term_shape(
        term: dict[str, Any],
        bindings: dict[str, tuple[str, Any, str]],
    ) -> tuple[str, Any, str] | None:
        root = term["root"]
        if root == "source":
            shape: tuple[str, Any, str] = ("schema", source_schema, "source")
        elif root == "language":
            if term["path"] != ["packages"]:
                return None
            return ("contract-list", package_release_contract, "language")
        elif root == "selected-packages":
            if term["path"]:
                return None
            return ("contract-list", package_release_contract, "language")
        elif root == "binding" and term.get("binding") in bindings:
            shape = bindings[term["binding"]]
        else:
            return None
        representation, payload, origin = shape
        path = term["path"]
        if representation == "schema":
            selected = _json_schema_path(payload, path)
            return ("schema", selected, origin) if selected is not None else None
        if representation == "contract":
            selected = _package_release_path_contract(payload, path)
            return ("contract", selected, origin) if selected is not None else None
        values = payload
        for segment in path:
            if not isinstance(values, list):
                return None
            selected_values = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    return None
                selected_values.append(value[segment])
            values = selected_values
        return ("values", values, origin)

    def result_kind(shape: tuple[str, Any, str]) -> str | None:
        representation, payload, _origin = shape
        if representation == "schema":
            return _schema_value_kind(payload)
        if representation in {"contract", "contract-list"}:
            return (
                "array"
                if representation == "contract-list"
                else _contract_value_kind(payload)
            )
        if not isinstance(payload, list) or not payload:
            return None
        kinds = {_canonical_value_kind(value) for value in payload}
        return kinds.pop() if len(kinds) == 1 else None

    for recipe in recipes:
        bindings: dict[str, tuple[str, Any, str]] = {}
        for binding in recipe["bindings"]:
            shape = term_shape(binding["source"], bindings)
            if shape is None:
                return False
            representation, payload, origin = shape
            if representation == "schema":
                if (
                    not isinstance(payload, dict)
                    or payload.get("type") != "array"
                    or not isinstance(payload.get("items"), dict)
                ):
                    return False
                bindings[binding["name"]] = ("schema", payload["items"], origin)
            elif representation in {"contract", "contract-list"}:
                if representation == "contract-list":
                    item_contract = payload
                elif payload.get("type") == "string-list":
                    item_contract = {"type": "non-empty-string"}
                else:
                    item_contract = payload.get("items")
                if not isinstance(item_contract, dict):
                    return False
                bindings[binding["name"]] = ("contract", item_contract, origin)
            else:
                if (
                    not isinstance(payload, list)
                    or not payload
                    or not all(isinstance(value, list) for value in payload)
                ):
                    return False
                bindings[binding["name"]] = (
                    "values",
                    [item for value in payload for item in value],
                    origin,
                )
        for predicate in recipe["predicates"]:
            left = term_shape(predicate["left"], bindings)
            right = term_shape(predicate["right"], bindings)
            if (
                left is None
                or right is None
                or result_kind(left) is None
                or result_kind(left) != result_kind(right)
            ):
                return False
        for field in recipe["fields"]:
            shape = term_shape(field["term"], bindings)
            if (
                shape is None
                or result_kind(shape) != "string"
                or (field["pointer"] and shape[2] != "source")
            ):
                return False

    for equivalence in resolution_contract["routing_equivalences"]:
        recipe = recipe_by_id.get(equivalence["recipe"])
        if recipe is None:
            return False
        if equivalence["subject_kind"] == "binding-source":
            matches = [
                binding["source"]
                for binding in recipe["bindings"]
                if binding["name"] == equivalence["subject"]
            ]
        else:
            matches = [
                field["term"]
                for field in recipe["fields"]
                if field["name"] == equivalence["subject"]
            ]
        if len(matches) != 1 or not matches[0]["path"]:
            return False
        expected = (
            ".".join(matches[0]["path"])
            if equivalence["projection"] == "dot-path"
            else matches[0]["path"][-1]
        )
        if profile.get(equivalence["profile_member"]) != expected:
            return False
    return True


def _relation_recipes_are_closed(
    profile: dict[str, Any],
    resolution_contract: dict[str, Any],
    language_bundle: dict[str, Any],
    package_release_contract: dict[str, Any],
) -> bool:
    recipes = profile.get("relation_recipes")
    schemas = resolution_contract.get("relation_schemas")
    recipe_format = resolution_contract.get("relation_recipe_format")
    if (
        not isinstance(recipes, list)
        or not isinstance(schemas, list)
        or not isinstance(recipe_format, dict)
        or [item.get("id") for item in recipes if isinstance(item, dict)]
        != [item.get("id") for item in schemas if isinstance(item, dict)]
    ):
        return False
    allowed_sources = set(
        cast(list[str], recipe_format.get("binding_source_roots", []))
    )
    allowed_terms = set(cast(list[str], recipe_format.get("term_roots", [])))
    allowed_predicates = set(
        cast(list[str], recipe_format.get("predicate_operators", []))
    )

    def term_is_closed(
        term: Any,
        bindings: set[str],
        *,
        allowed_roots: set[str],
    ) -> bool:
        if not isinstance(term, dict) or not isinstance(term.get("root"), str):
            return False
        root = term["root"]
        expected = (
            {"root", "path", "binding"}
            if root == "binding"
            else {
                "root",
                "path",
            }
        )
        return (
            root in allowed_roots
            and set(term) == expected
            and isinstance(term.get("path"), list)
            and all(isinstance(segment, str) and segment for segment in term["path"])
            and (
                root != "binding"
                or (
                    isinstance(term.get("binding"), str) and term["binding"] in bindings
                )
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
        bindings: set[str] = set()
        for binding in recipe["bindings"]:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"name", "source"}
                or not isinstance(binding.get("name"), str)
                or not binding["name"]
                or binding["name"] in bindings
                or not term_is_closed(
                    binding.get("source"),
                    bindings,
                    allowed_roots=allowed_sources,
                )
            ):
                return False
            bindings.add(binding["name"])
        for predicate in recipe["predicates"]:
            if (
                not isinstance(predicate, dict)
                or set(predicate) != {"operator", "left", "right"}
                or predicate.get("operator") not in allowed_predicates
                or not term_is_closed(
                    predicate.get("left"),
                    bindings,
                    allowed_roots=allowed_terms,
                )
                or not term_is_closed(
                    predicate.get("right"),
                    bindings,
                    allowed_roots=allowed_terms,
                )
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
                or not term_is_closed(
                    field.get("term"),
                    bindings,
                    allowed_roots=allowed_terms,
                )
                for field in recipe["fields"]
            )
        ):
            return False
    return _relation_recipe_paths_are_typed(
        profile,
        language_bundle,
        resolution_contract,
        package_release_contract,
    )


def _semantic_element_contract(
    authority_path: str, language_definitions: dict[str, Any]
) -> dict[str, Any] | None:
    parts = authority_path.split(".")
    if len(parts) == 2 and parts[0] == "language":
        collections = language_definitions.get("collections")
        contract = collections.get(parts[1]) if isinstance(collections, dict) else None
    elif len(parts) == 3 and parts[:2] == ["language", "quantity"]:
        quantity = language_definitions.get("quantity")
        collections = (
            quantity.get("collections") if isinstance(quantity, dict) else None
        )
        contract = collections.get(parts[2]) if isinstance(collections, dict) else None
    else:
        return None
    if not isinstance(contract, dict):
        return None
    item_type = contract.get("item_type")
    return {"type": item_type} if isinstance(item_type, str) else contract


def _definition_contract_at_path(
    contract: dict[str, Any], path: list[str]
) -> dict[str, Any] | None:
    selected = contract
    for segment in path:
        if selected.get("type") == "closed-discriminated-object":
            variants = selected.get("variants")
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
            kinds = {_contract_value_kind(child) for child in children}
            if not children or len(kinds) != 1 or None in kinds:
                return None
            if all(child == children[0] for child in children[1:]):
                selected = children[0]
            else:
                selected = {
                    "type": {
                        "array": "list",
                        "boolean": "boolean",
                        "integer": "signed-int64",
                        "object": "object",
                        "string": "non-empty-string",
                    }[cast(str, next(iter(kinds)))]
                }
            continue
        field_types = selected.get("field_types")
        if not isinstance(field_types, dict):
            return None
        child = field_types.get(segment)
        if not isinstance(child, dict):
            return None
        selected = child
    return selected


def _contract_assignable_to_schema(contract: dict[str, Any], schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if "const" in contract:
        value = contract["const"]
        if "const" in schema and schema["const"] != value:
            return False
        if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
            return False
        expected = _canonical_value_kind(value)
        actual = schema.get("type")
        return actual is None or actual == expected
    if isinstance(contract.get("enum"), list) and contract["enum"]:
        values = contract["enum"]
        kinds = {_canonical_value_kind(value) for value in values}
        return (
            len(kinds) == 1
            and schema.get("type") in {None, next(iter(kinds))}
            and (
                not isinstance(schema.get("enum"), list)
                or set(values) <= set(schema["enum"])
            )
        )
    value_type = contract.get("type")
    if value_type in {"inventory-member", "non-empty-string", "string"}:
        return schema.get("type") == "string"
    if value_type in {"positive-signed-int64", "signed-int64"}:
        return schema.get("type") == "integer"
    if value_type == "boolean":
        return schema.get("type") == "boolean"
    if value_type == "string-list":
        return (
            schema.get("type") == "array"
            and isinstance(schema.get("items"), dict)
            and schema["items"].get("type") == "string"
        )
    if value_type == "canonical-value":
        # The closed wire schema remains the structural authority for the
        # canonical value. The Kernel contract establishes only that the
        # language definition is canonically encodable.
        return True
    if value_type == "closed-discriminated-object":
        return schema == {}
    if value_type == "list-of":
        item = contract.get("items")
        return (
            schema.get("type") == "array"
            and isinstance(item, dict)
            and _contract_assignable_to_schema(item, schema.get("items"))
        )
    is_object = value_type == "closed-object" or (
        value_type is None
        and isinstance(contract.get("required_members"), list)
        and isinstance(contract.get("field_types"), dict)
    )
    if is_object:
        required = contract.get("required_members")
        optional = contract.get("optional_members", [])
        fields = contract.get("field_types")
        properties = schema.get("properties")
        schema_required = schema.get("required")
        return (
            schema.get("type") == "object"
            and isinstance(required, list)
            and isinstance(optional, list)
            and isinstance(fields, dict)
            and isinstance(properties, dict)
            and isinstance(schema_required, list)
            and not set(required) & set(optional)
            and set(required) | set(optional) == set(fields)
            and set(fields) == set(properties)
            and set(schema_required) == set(required)
            and schema.get("unevaluatedProperties") is False
            and all(
                _contract_assignable_to_schema(fields[name], properties[name])
                for name in fields
            )
        )
    return False


def _schema_items_match(source: Any, target: Any) -> bool:
    return isinstance(source, dict) and isinstance(target, dict) and source == target


def _runtime_projection_is_closed(
    profile: Any,
    contract: Any,
    language_bundle: dict[str, Any],
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
    source_kinds = set(cast(list[Any], contract.get("collection_source_kinds", [])))
    output_shapes = set(cast(list[Any], contract.get("output_shapes", [])))
    seed_operators = set(cast(list[Any], contract.get("seed_operators", [])))
    edge_operators = set(cast(list[Any], contract.get("edge_operators", [])))
    output_kinds = set(cast(list[Any], contract.get("output_kinds", [])))
    if (
        source_kinds != {"lock-member", "semantic-closure"}
        or output_shapes
        != {"as-is", "package-definition", "definition", "closure-only"}
        or seed_operators != {"declaration-field"}
        or edge_operators != {"equal"}
        or output_kinds
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

    def path_is_closed(path: Any, *, empty: bool = False) -> bool:
        return (
            isinstance(path, list)
            and (empty or bool(path))
            and all(isinstance(segment, str) and segment for segment in path)
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
    output_members: list[str] = []
    for output in outputs:
        if not isinstance(output, dict) or output.get("kind") not in output_kinds:
            return False
        kind = output["kind"]
        expected = {
            "kind",
            "source_member",
            "output_member",
            "package_member",
        }
        if kind == "selected-packages":
            expected.add("members")
        elif kind == "selected-semantic-closures":
            expected.update(
                {
                    "entries_member",
                    "authority_path_member",
                    "definitions_member",
                }
            )
        if (
            set(output) != expected
            or any(
                not isinstance(output.get(member), str) or not output[member]
                for member in expected - {"kind", "members"}
            )
            or (
                "members" in output
                and (
                    not isinstance(output["members"], list)
                    or not output["members"]
                    or not all(
                        isinstance(member, str) and member
                        for member in output["members"]
                    )
                    or len(output["members"]) != len(set(output["members"]))
                )
            )
        ):
            return False
        output_members.append(output["output_member"])

    collection_ids: list[str] = []
    authority_paths: set[str] = set()
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
            or collection.get("output_shape") not in output_shapes
            or (
                collection["output_shape"] == "closure-only"
                and collection.get("output_member") is not None
            )
            or (
                collection["output_shape"] != "closure-only"
                and (
                    not isinstance(collection.get("output_member"), str)
                    or not collection["output_member"]
                )
            )
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
        source = collection["source"]
        if source.get("kind") == "lock-member":
            if (
                set(source) != {"kind", "member", "package_path"}
                or not isinstance(source.get("member"), str)
                or not source["member"]
                or not path_is_closed(source.get("package_path"))
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
        collection_ids.append(collection["id"])
        if collection["output_member"] is not None:
            output_members.append(collection["output_member"])
    if len(collection_ids) != len(set(collection_ids)):
        return False
    collection_names = set(collection_ids)

    for seed in seeds:
        if not isinstance(seed, dict) or seed.get("operator") not in seed_operators:
            return False
        expected = {
            "operator",
            "collection",
            "declaration_path",
            "declaration_package_path",
            "target_path",
            "same_package",
            "missing_declaration_path",
            "applicability_member",
        }
        if "missing_target" in seed:
            expected.add("missing_target")
        if (
            set(seed) != expected
            or seed.get("collection") not in collection_names
            or not path_is_closed(seed.get("declaration_package_path"))
            or not path_is_closed(seed.get("declaration_path"))
            or not path_is_closed(seed.get("target_path"), empty=True)
            or not isinstance(seed.get("same_package"), bool)
            or seed.get("missing_declaration_path") != "not-applicable"
            or not isinstance(seed.get("applicability_member"), str)
            or not seed["applicability_member"]
            or seed.get("missing_target", "refuse") not in {"not-applicable", "refuse"}
        ):
            return False
    for edge in edges:
        if (
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
            or edge.get("operator") not in edge_operators
            or edge.get("source_collection") not in collection_names
            or edge.get("target_collection") not in collection_names
            or not path_is_closed(edge.get("source_path"), empty=True)
            or not path_is_closed(edge.get("target_path"), empty=True)
            or not isinstance(edge.get("same_package"), bool)
            or edge.get("missing_target") not in {"not-applicable", "refuse"}
        ):
            return False
    if len(output_members) != len(set(output_members)):
        return False
    language = language_bundle.get("language")
    wire_schemas = (
        language.get("artifact_wire_schemas") if isinstance(language, dict) else None
    )
    if not isinstance(wire_schemas, list):
        return False
    rir_schemas = [
        item.get("schema")
        for item in wire_schemas
        if isinstance(item, dict)
        and item.get("artifact_kind") == "rir-semantic-payload"
    ]
    if len(rir_schemas) != 1 or not isinstance(rir_schemas[0], dict):
        return False
    selected_schema = (
        rir_schemas[0].get("properties", {}).get("selected_semantics")
        if isinstance(rir_schemas[0].get("properties"), dict)
        else None
    )
    required_outputs = (
        selected_schema.get("required") if isinstance(selected_schema, dict) else None
    )
    selected_properties = (
        selected_schema.get("properties") if isinstance(selected_schema, dict) else None
    )
    packages = language.get("packages") if isinstance(language, dict) else None
    lock_schemas = [
        item.get("schema")
        for item in wire_schemas
        if isinstance(item, dict) and item.get("artifact_kind") == "package-lock"
    ]
    if not (
        isinstance(required_outputs, list)
        and set(output_members) == set(required_outputs)
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
        and len(lock_schemas) == 1
        and isinstance(lock_schemas[0], dict)
        and isinstance(lock_schemas[0].get("properties"), dict)
    ):
        return False
    lock_properties = lock_schemas[0]["properties"]

    def fact_contract(path: list[str]) -> dict[str, Any] | None:
        if not path or path[0] not in declaration_fields:
            return None
        selected = declaration_fields[path[0]]
        for segment in path[1:]:
            if (
                not isinstance(selected, dict)
                or selected.get("type") != "closed-object"
                or not isinstance(selected.get("field_types"), dict)
                or segment not in selected["field_types"]
            ):
                return None
            selected = selected["field_types"][segment]
        return selected if isinstance(selected, dict) else None

    def contract_kind(value: dict[str, Any] | None) -> str | None:
        if value is None:
            return None
        kind = value.get("type")
        if kind in {"non-empty-string", "inventory-member"}:
            return "string"
        if kind in {"closed-object", "closed-int64-interval"}:
            return "object"
        if kind in {"signed-int64", "positive-signed-int64"}:
            return "integer"
        if kind == "boolean":
            return "boolean"
        return None

    collection_shapes: dict[str, tuple[str, Any]] = {}
    for collection in collections:
        source = collection["source"]
        if source["kind"] == "lock-member":
            member_schema = lock_properties.get(source["member"])
            if (
                not isinstance(member_schema, dict)
                or member_schema.get("type") != "array"
                or not isinstance(member_schema.get("items"), dict)
                or _schema_value_kind(
                    _json_schema_path(
                        member_schema["items"],
                        source["package_path"],
                    )
                )
                != "string"
            ):
                return False
            collection_shapes[collection["id"]] = (
                "schema",
                member_schema["items"],
            )
        else:
            element_contract = _semantic_element_contract(
                source["authority_path"], language_definitions
            )
            if element_contract is None:
                return False
            collection_shapes[collection["id"]] = ("contract", element_contract)

    def projected_kind(shape: tuple[str, Any], path: list[str]) -> str | None:
        representation, payload = shape
        if representation == "schema":
            selected = _json_schema_path(payload, path)
            return _schema_value_kind(selected)
        selected = _definition_contract_at_path(payload, path)
        return _contract_value_kind(selected)

    for seed in seeds:
        if seed["applicability_member"] not in declaration_fields:
            continue
        declaration_kind = contract_kind(fact_contract(seed["declaration_path"]))
        package_kind = contract_kind(fact_contract(seed["declaration_package_path"]))
        if declaration_kind is None:
            if seed["missing_declaration_path"] != "not-applicable":
                return False
            continue
        target_kind = projected_kind(
            collection_shapes[seed["collection"]],
            seed["target_path"],
        )
        if declaration_kind != target_kind or package_kind != "string":
            return False
    for edge in edges:
        source_kind = projected_kind(
            collection_shapes[edge["source_collection"]],
            edge["source_path"],
        )
        target_kind = projected_kind(
            collection_shapes[edge["target_collection"]],
            edge["target_path"],
        )
        if source_kind is None or source_kind != target_kind:
            return False
    for collection in collections:
        output_member = collection["output_member"]
        if output_member is None:
            continue
        target = selected_properties.get(output_member)
        if (
            not isinstance(target, dict)
            or target.get("type") != "array"
            or not isinstance(target.get("items"), dict)
        ):
            return False
        representation, payload = collection_shapes[collection["id"]]
        shape = collection["output_shape"]
        if representation == "schema":
            if shape != "as-is" or not _schema_items_match(payload, target["items"]):
                return False
        elif shape == "definition":
            if not _contract_assignable_to_schema(payload, target["items"]):
                return False
        elif shape == "package-definition":
            target_item = target["items"]
            properties = target_item.get("properties")
            if not (
                target_item.get("type") == "object"
                and isinstance(properties, dict)
                and set(properties) == {"package", "definition"}
                and set(target_item.get("required", [])) == {"package", "definition"}
                and target_item.get("unevaluatedProperties") is False
                and properties["package"].get("type") == "string"
                and _contract_assignable_to_schema(payload, properties["definition"])
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
            or _schema_value_kind(
                _json_schema_path(
                    source_schema["items"],
                    [output["package_member"]],
                )
            )
            != "string"
        ):
            return False
        if output["kind"] == "selected-packages" and any(
            _json_schema_path(source_schema["items"], [member]) is None
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
            entries = _json_schema_path(
                source_schema["items"],
                [output["entries_member"]],
            )
            if (
                not isinstance(entries, dict)
                or entries.get("type") != "array"
                or not isinstance(entries.get("items"), dict)
                or _schema_value_kind(
                    _json_schema_path(
                        entries["items"],
                        [output["authority_path_member"]],
                    )
                )
                != "string"
                or _json_schema_path(
                    entries["items"],
                    [output["definitions_member"]],
                )
                is None
            ):
                return False
            source_item = source_schema["items"]
            source_properties = source_item.get("properties")
            target_item = target_schema["items"]
            target_properties = target_item.get("properties")
            projected = {output["package_member"], output["entries_member"]}
            if not (
                isinstance(source_properties, dict)
                and isinstance(target_properties, dict)
                and set(target_properties) == projected
                and set(target_item.get("required", [])) == projected
                and target_item.get("unevaluatedProperties") is False
                and all(
                    source_properties[member] == target_properties[member]
                    for member in projected
                )
            ):
                return False
    return True


def _language_definitions_are_closed(
    language_bundle: dict[str, Any], meta_format: dict[str, Any]
) -> bool:
    language = language_bundle.get("language")
    authority = meta_format.get("language_definitions")
    if not isinstance(language, dict) or not isinstance(authority, dict):
        return False
    collections = authority.get("collections")
    if not isinstance(collections, dict):
        return False
    for name, contract in collections.items():
        values = language.get(name)
        if not isinstance(values, list) or not isinstance(contract, dict):
            return False
        max_items = contract.get("max_items")
        if max_items is not None:
            if not isinstance(max_items, int) or len(values) > max_items:
                return False
            continue
        item_type = contract.get("item_type")
        if item_type is not None:
            item_contract = {"type": item_type}
            if not all(
                _value_matches_contract(value, item_contract, language_bundle)
                for value in values
            ):
                return False
            continue
        if not all(
            _definition_is_closed(value, contract, language_bundle) for value in values
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
        item_type = contract.get("item_type")
        if item_type is not None:
            item_contract = {"type": item_type}
            if not all(
                _value_matches_contract(value, item_contract, language_bundle)
                for value in values
            ):
                return False
        elif not all(
            _definition_is_closed(value, contract, language_bundle) for value in values
        ):
            return False
    if not _template_admission_profiles_are_closed(language_bundle, meta_format):
        return False
    fact_schemas = _fact_schemas(meta_format)
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
    resolution_contract = meta_format.get("resolution_judgment")
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
        for item in cast(list[dict[str, Any]], language.get("reasons", []))
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
        for item in cast(list[dict[str, Any]], language.get("reasons", []))
        if isinstance(exhaustion_reason, dict)
        and item.get("stage") == exhaustion_reason.get("stage")
        and isinstance(item.get("predicate"), dict)
        and item["predicate"].get("operation") == exhaustion_reason.get("operation")
        and item["predicate"].get("limit_path") == exhaustion_reason.get("limit_path")
    ]
    runtime_projection_contract = meta_format.get("runtime_projection")
    runtime_accounting = (
        runtime_projection_contract.get("resource_accounting")
        if isinstance(runtime_projection_contract, dict)
        else None
    )
    runtime_exhaustion_reason = (
        runtime_accounting.get("exhaustion_reason")
        if isinstance(runtime_accounting, dict)
        else None
    )
    runtime_resource_reasons = [
        item
        for item in cast(list[dict[str, Any]], language.get("reasons", []))
        if isinstance(runtime_exhaustion_reason, dict)
        and item.get("stage") == runtime_exhaustion_reason.get("stage")
        and isinstance(item.get("predicate"), dict)
        and item["predicate"].get("operation")
        == runtime_exhaustion_reason.get("operation")
        and item["predicate"].get("limit_path")
        == runtime_exhaustion_reason.get("limit_path")
    ]
    if (
        len(profiles_by_id) != len(profiles)
        or not isinstance(resolution_contract, dict)
        or not _resolution_judgment_is_closed(resolution_contract)
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
            or not _relation_recipes_are_closed(
                profile,
                resolution_contract,
                language_bundle,
                cast(dict[str, Any], meta_format["package_release"]),
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
            if not isinstance(fields, dict) or not _runtime_projection_is_closed(
                lowering.get("runtime_projection"),
                runtime_projection_contract,
                language_bundle,
                fields,
                cast(dict[str, Any], meta_format["language_definitions"]),
            ):
                return False
            for equality in equalities:
                left = equality.get("left")
                right = equality.get("right")
                if (
                    not _fact_contract_path_is_declared(fields, left)
                    or not _fact_contract_path_is_declared(fields, right)
                    or left == right
                ):
                    return False
                left_contract = _fact_contract_at_path(fields, left)
                right_contract = _fact_contract_at_path(fields, right)
                left_kind = _contract_value_kind(left_contract)
                right_kind = _contract_value_kind(right_contract)
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


def _artifact_semantic_identity_projections_are_closed(
    language_bundle: dict[str, Any],
) -> bool:
    language = language_bundle.get("language")
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


def _assignment_mode_contract_is_coherent(mode: dict[str, Any]) -> bool:
    source = mode.get("initialization_source")
    value_member = mode.get("value_member")
    cardinality = mode.get("experiment_cardinality")
    event_cardinality = mode.get("event_payload_cardinality")
    external_fact_cardinality = mode.get("external_fact_cardinality")
    override = mode.get("override")
    initialization_is_coherent = (
        (
            source == "model"
            and value_member == "required"
            and cardinality == "forbidden"
            and override is False
        )
        or (
            source == "experiment"
            and value_member == "forbidden"
            and cardinality == "required"
            and override is False
        )
        or (
            source == "model-with-experiment-override"
            and value_member == "required"
            and cardinality == "optional"
            and override is True
        )
        or (
            source in {"execution", "named-random-stream", "resolved-model"}
            and value_member == "forbidden"
            and cardinality == "forbidden"
            and override is False
        )
    )
    return (
        initialization_is_coherent
        and event_cardinality in {"forbidden", "optional", "required"}
        and external_fact_cardinality in {"forbidden", "optional", "required"}
    )


def _assignment_role_contract_is_total(row: dict[str, Any]) -> bool:
    modes = row.get("modes")
    accesses = row.get("entrypoint_operand_access")
    result = row.get("entrypoint_result")
    binding_kind = row.get("binding_kind")
    if (
        not isinstance(modes, list)
        or not modes
        or not isinstance(accesses, list)
        or not isinstance(result, bool)
    ):
        return False
    if binding_kind == "operand":
        return (
            bool(accesses)
            and result is False
            and all(
                mode["experiment_cardinality"] != "forbidden"
                or mode["initialization_source"]
                in {"model", "model-with-experiment-override"}
                or (
                    row.get("role") == "derived"
                    and mode["initialization_source"] == "resolved-model"
                )
                for mode in modes
            )
            and all(
                mode["event_payload_cardinality"] == "forbidden"
                or (
                    accesses == ["read"]
                    and mode["initialization_source"]
                    in {"experiment", "model-with-experiment-override"}
                )
                for mode in modes
            )
            and all(
                mode["external_fact_cardinality"] == "forbidden"
                or (
                    accesses == ["read"]
                    and mode["initialization_source"] == "experiment"
                )
                for mode in modes
            )
        )
    if binding_kind == "result":
        return (
            not accesses
            and result is True
            and all(mode["initialization_source"] == "execution" for mode in modes)
            and all(mode["event_payload_cardinality"] == "forbidden" for mode in modes)
            and all(mode["external_fact_cardinality"] == "forbidden" for mode in modes)
        )
    return (
        binding_kind == "internal"
        and not accesses
        and result is False
        and all(mode["event_payload_cardinality"] == "forbidden" for mode in modes)
        and all(mode["external_fact_cardinality"] == "forbidden" for mode in modes)
    )


def _assignment_policy_is_total(language_bundle: dict[str, Any]) -> bool:
    language = language_bundle.get("language")
    if not isinstance(language, dict):
        return False
    lowerings = language.get("model_lowerings")
    quantity = language.get("quantity")
    wire_schemas = language.get("wire_schemas")
    resolution_profiles = language.get("resolution_profiles")
    if (
        not isinstance(lowerings, list)
        or len(lowerings) != 1
        or not isinstance(quantity, dict)
        or not isinstance(quantity.get("symbol_roles"), list)
        or not isinstance(wire_schemas, list)
        or not isinstance(resolution_profiles, list)
    ):
        return False
    selected_profile = lowerings[0].get("resolution_profile")
    profiles = [
        profile
        for profile in resolution_profiles
        if isinstance(profile, dict) and profile.get("id") == selected_profile
    ]
    if len(profiles) != 1:
        return False
    modules_member = profiles[0].get("modules_member")
    symbols_member = profiles[0].get("symbols_member")
    if not isinstance(modules_member, str) or not isinstance(symbols_member, str):
        return False
    policy = lowerings[0].get("assignment_policy")
    if not isinstance(policy, dict) or not isinstance(policy.get("roles"), list):
        return False
    rows = cast(list[dict[str, Any]], policy["roles"])
    by_role = {
        row.get("role"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("role"), str)
    }
    if len(by_role) != len(rows) or set(by_role) != set(quantity["symbol_roles"]):
        return False
    declared_mode_ids: set[str] = set()
    for row in rows:
        modes = row.get("modes")
        accesses = row.get("entrypoint_operand_access")
        if (
            not isinstance(modes, list)
            or not modes
            or not isinstance(accesses, list)
            or any(
                not isinstance(mode, dict)
                or not isinstance(mode.get("id"), str)
                or not mode["id"]
                or not _assignment_mode_contract_is_coherent(mode)
                for mode in modes
            )
            or len({mode["id"] for mode in modes}) != len(modes)
            or any(access not in {"read", "read-write", "write"} for access in accesses)
            or not _assignment_role_contract_is_total(row)
        ):
            return False
        declared_mode_ids.update(cast(str, mode["id"]) for mode in modes)
    model_source_schemas = [
        item["schema"]
        for item in wire_schemas
        if isinstance(item, dict)
        and item.get("artifact_kind") == "model-source-package"
        and isinstance(item.get("schema"), dict)
    ]
    if len(model_source_schemas) != 1:
        return False
    try:
        schema_modes = set(
            model_source_schemas[0]["properties"][modules_member]["items"][
                "properties"
            ][symbols_member]["items"]["properties"]["value_policy"]["properties"][
                "mode"
            ]["enum"]
        )
    except (KeyError, TypeError):
        return False
    return schema_modes == declared_mode_ids


def _literal_typing_profiles_are_closed(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> bool:
    meta = kernel.get("meta_format")
    contract = meta.get("literal_typing") if isinstance(meta, dict) else None
    expected_contract = {
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
        "range_members": {
            "maximum": "maximum",
            "minimum": "minimum",
        },
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
    language = language_bundle.get("language")
    if not isinstance(language, dict) or contract != expected_contract:
        return False
    literal_contract = cast(dict[str, Any], contract)
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
    representations = set(cast(list[Any], quantity.get("representations", [])))
    kinds = set(cast(list[Any], quantity.get("kinds", [])))
    units = {
        row.get("id")
        for row in cast(list[Any], quantity.get("units", []))
        if isinstance(row, dict)
    }
    numeric_policies = {
        row.get("id")
        for row in cast(list[Any], quantity.get("numeric_policies", []))
        if isinstance(row, dict)
    }
    owners: dict[str, list[dict[str, Any]]] = {}
    for package in packages:
        exports = package.get("exports") if isinstance(package, dict) else None
        profile_ids = (
            exports.get("literal_typing_profiles")
            if isinstance(exports, dict)
            else None
        )
        if not isinstance(profile_ids, list):
            return False
        for profile_id in profile_ids:
            if not isinstance(profile_id, str):
                return False
            owners.setdefault(profile_id, []).append(package)
    formals = [
        formal
        for operation in operations
        if isinstance(operation, dict)
        for formal in (
            [item for item in operation.get("inputs", []) if isinstance(item, dict)]
            + (
                [operation["result"]]
                if isinstance(operation.get("result"), dict)
                else []
            )
        )
    ]
    match_members = cast(list[str], literal_contract["match_members"])
    typed_profile_contract = cast(
        dict[str, Any], literal_contract["typed_envelope_profile"]
    )
    numeric_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = profile.get("id") if isinstance(profile, dict) else None
        profile_owners = (
            owners.get(profile_id, []) if isinstance(profile_id, str) else []
        )
        if not isinstance(profile, dict) or not isinstance(profile_id, str):
            return False
        if profile.get("source_kind") == "typed-envelope":
            owner = profile_owners[0] if len(profile_owners) == 1 else None
            owner_exports = owner.get("exports") if isinstance(owner, dict) else None
            if (
                set(profile) != {"admission", "id", "source_kind", "value_kind"}
                or profile.get("admission") != typed_profile_contract["admission"]
                or profile_id != typed_profile_contract["id"]
                or profile.get("value_kind") != typed_profile_contract["value_kind"]
                or not isinstance(owner_exports, dict)
                or set(cast(list[Any], owner_exports.get("constructors", [])))
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
            or not isinstance(profile_id, str)
            or len(profile_owners) != 1
            or type(profile.get("minimum")) is not int
            or type(profile.get("maximum")) is not int
            or profile["minimum"] > profile["maximum"]
            or profile.get("representation") not in representations
            or profile.get("kind") not in kinds
            or profile.get("unit") not in units
            or profile.get("numeric_policy") not in numeric_policies
            or not isinstance(profile.get("type"), dict)
        ):
            return False
        numeric_profiles.append(profile)
        owner = profile_owners[0]
        owner_exports = cast(dict[str, Any], owner["exports"])
        exported_types = owner_exports.get("types")
        type_ref = cast(dict[str, Any], profile["type"])
        if (
            type_ref.get("package") != owner.get("id")
            or type_ref.get("version") != owner.get("version")
            or not isinstance(exported_types, list)
            or len(
                [
                    row
                    for row in exported_types
                    if isinstance(row, dict) and row.get("id") == type_ref.get("id")
                ]
            )
            != 1
            or not any(
                all(
                    profile.get(member) == formal.get(member)
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
                    left.get(member) == right.get(member) for member in match_members
                )
                and left["minimum"] <= right["maximum"]
                and right["minimum"] <= left["maximum"]
            ):
                return False
    return True


def _operation_alias_policy_is_closed(operation: dict[str, Any]) -> bool:
    inputs = operation.get("inputs")
    policy = operation.get("alias_policy")
    if not isinstance(inputs, list) or not isinstance(policy, dict):
        return False
    ports = {
        item.get("id"): item
        for item in inputs
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    groups = policy.get("writable_groups")
    if (
        policy.get("read_only") != "share"
        or not isinstance(groups, list)
        or len(ports) != len(inputs)
    ):
        return False
    seen: set[frozenset[str]] = set()
    for group in groups:
        group_ports = group.get("ports") if isinstance(group, dict) else None
        if (
            not isinstance(group_ports, list)
            or len(group_ports) < 2
            or len(group_ports) != len(set(group_ports))
            or not set(group_ports) <= set(ports)
            or group.get("semantics") != "operation-body-order"
            or all(ports[port].get("access") == "read" for port in group_ports)
            or frozenset(group_ports) in seen
        ):
            return False
        seen.add(frozenset(group_ports))
    return True


def _operation_aliases_are_admitted(
    operation: dict[str, Any],
    aliases: dict[str, list[tuple[str, str]]],
) -> bool:
    groups = {
        frozenset(group["ports"])
        for group in cast(
            list[dict[str, Any]], operation["alias_policy"]["writable_groups"]
        )
    }
    return all(
        len(uses) < 2
        or all(access == "read" for _port, access in uses)
        or frozenset(port for port, _access in uses) in groups
        for uses in aliases.values()
    )


def _operation_composition_diagnostic_subjects(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> tuple[str, ...]:
    language = language_bundle.get("language")
    if not isinstance(language, dict) or not isinstance(language.get("packages"), list):
        return ("language.operations",)
    invocation_contract = (
        kernel.get("meta_format", {})
        .get("runtime_program", {})
        .get("invocation_contract")
    )
    runtime_program = kernel.get("meta_format", {}).get("runtime_program")
    runtime_nodes = (
        runtime_program.get("nodes") if isinstance(runtime_program, dict) else None
    )
    value_contracts = derive_operation_value_contracts(kernel, language_bundle)
    result_source_shapes = (
        invocation_contract.get("result_source_shapes")
        if isinstance(invocation_contract, dict)
        else None
    )
    if (
        not isinstance(result_source_shapes, dict)
        or not isinstance(runtime_nodes, list)
        or value_contracts is None
    ):
        return ("language.literal-typing-profiles",)
    fixed_value_contracts = value_contracts.fixed_value_contracts
    runtime_numeric_policies = value_contracts.runtime_numeric_policies
    node_definitions = {
        node["id"]: node
        for node in runtime_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    if len(node_definitions) != len(runtime_nodes):
        return ("kernel.meta-format.runtime-program.nodes",)
    reasons_by_signal: dict[str, list[str]] = {}
    for reason in cast(list[dict[str, Any]], language.get("reasons", [])):
        signal = reason.get("signal") if isinstance(reason, dict) else None
        reason_id = reason.get("id") if isinstance(reason, dict) else None
        if isinstance(signal, str) and isinstance(reason_id, str):
            reasons_by_signal.setdefault(signal, []).append(reason_id)
    operations: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
    for package in cast(list[dict[str, Any]], language["packages"]):
        package_id = package.get("id")
        version = package.get("version")
        closure = package.get("semantic_closure")
        if (
            not isinstance(package_id, str)
            or not isinstance(version, str)
            or not isinstance(closure, list)
        ):
            return ("language.operations",)
        for entry in closure:
            if (
                not isinstance(entry, dict)
                or entry.get("authority_path") != "language.operations"
            ):
                continue
            definitions = entry.get("definitions")
            if not isinstance(definitions, list):
                return (f"language.operations.{package_id}@{version}",)
            for operation in definitions:
                if not isinstance(operation, dict) or not isinstance(
                    operation.get("id"), str
                ):
                    return (f"language.operations.{package_id}@{version}",)
                key = (package_id, version, cast(str, operation["id"]))
                if key in operations:
                    return (f"language.operations.{package_id}@{version}",)
                operations[key] = (f"{package_id}@{version}", operation)
    if not all(
        _operation_alias_policy_is_closed(operation)
        for _owner, operation in operations.values()
    ):
        return ("language.operations.alias-policy",)
    operation_node_ids = {
        node_id
        for node_id, node in node_definitions.items()
        if node["semantics"]["operator"] in {"invoke-operation", "schedule-operation"}
    }
    invocation_node_ids = {
        node_id
        for node_id, node in node_definitions.items()
        if node["semantics"]["operator"] == "invoke-operation"
    }
    cache: dict[tuple[str, str, str], tuple[frozenset[str], frozenset[str], int]] = {}
    guard_body_keys: set[tuple[str, str, str]] = set()
    found: set[str] = set()

    def refuse(owner: str, operation: dict[str, Any], site: str, member: str) -> None:
        found.add(f"language.operations.{owner}.{operation['id']}.body.{site}.{member}")

    def close(
        key: tuple[str, str, str],
        stack: tuple[tuple[str, str, str], ...],
    ) -> tuple[frozenset[str], frozenset[str], int] | None:
        if key in stack:
            owner, operation = operations[key]
            refuse(owner, operation, "cycle", "operation")
            return None
        if key in cache:
            return cache[key]
        owner, operation = operations[key]
        if not _operation_result_source_shape_is_closed(
            operation, result_source_shapes
        ):
            found.add(f"language.operations.{owner}.{operation['id']}.result.source")
            return None
        source = cast(dict[str, Any], operation["result"]["source"])
        source_kind = cast(str, source["kind"])
        source_site = (
            cast(str, source["site"]) if source_kind == "operation-result" else None
        )
        parent_ports = {
            item["id"]: item for item in cast(list[dict[str, Any]], operation["inputs"])
        }
        parent_outcome_definitions = {
            item["id"]: item
            for item in cast(list[dict[str, Any]], operation.get("outcomes", []))
        }
        parent_outcomes = set(parent_outcome_definitions)
        parent_successes = {
            outcome_id
            for outcome_id, definition in parent_outcome_definitions.items()
            if definition.get("kind") == "success"
        }
        locals_: dict[str, tuple[dict[str, Any], ...]] = {}
        lexical_environment: dict[str, tuple[dict[str, Any], ...]] = {
            name: (contract,) for name, contract in parent_ports.items()
        }
        local_producers: dict[str, int] = {}
        effects = set(cast(list[str], operation["effects"]))
        refusals = set(cast(list[str], operation["refusals"]))
        seen_sites: set[str] = set()
        operation_result_sites: set[str] = set()
        source_producer_reached = False

        def compatible_candidates(
            candidate_sets: list[tuple[dict[str, Any], ...]],
        ) -> tuple[dict[str, Any], ...]:
            if not candidate_sets:
                return ()
            return tuple(
                candidate
                for candidate in candidate_sets[0]
                if all(
                    any(
                        value_contracts.matches(candidate, other)
                        for other in candidates
                    )
                    for candidates in candidate_sets[1:]
                )
            )

        def referenced_candidates(
            instruction: dict[str, Any],
            members: list[str],
        ) -> list[tuple[dict[str, Any], ...]] | None:
            candidates: list[tuple[dict[str, Any], ...]] = []
            for member in members:
                name = instruction.get(member)
                visible = (
                    lexical_environment.get(name) if isinstance(name, str) else None
                )
                if not visible:
                    return None
                candidates.append(visible)
            return candidates

        def narrow_reference(
            instruction: dict[str, Any],
            member: str,
            candidates: tuple[dict[str, Any], ...],
        ) -> None:
            name = cast(str, instruction[member])
            lexical_environment[name] = candidates
            if name in locals_:
                locals_[name] = candidates

        for instruction_index, instruction in enumerate(
            cast(list[dict[str, Any]], operation["body"])
        ):
            node = node_definitions.get(instruction.get("node"))
            if not isinstance(node, dict) or set(instruction) != set(
                node["required_members"]
            ):
                refuse(owner, operation, str(instruction_index), "members")
                return None
            target = instruction.get("target")
            if instruction.get("node") != "invoke":
                if (
                    source_kind in {"local", "operation-result"}
                    and not source_producer_reached
                    and instruction.get("outcome") in parent_successes
                ):
                    found.add(
                        f"language.operations.{owner}.{operation['id']}.result.source"
                    )
                    return None
                for constraint in cast(
                    list[dict[str, Any]], node["operand_constraints"]
                ):
                    members = cast(list[str], constraint["members"])
                    referenced = referenced_candidates(instruction, members)
                    if referenced is None:
                        refuse(owner, operation, str(instruction_index), "typing")
                        return None
                    constraint_kind = constraint["kind"]
                    if constraint_kind == "same-value-contract":
                        shared = compatible_candidates(referenced)
                        if node["semantics"]["operator"] == "canonical-equal":
                            expected_result_contract = cast(
                                dict[str, Any], node["result"]["typing"]
                            ).get("contract")
                            shared = tuple(
                                candidate
                                for candidate in shared
                                if candidate.get("value_kind")
                                not in {"nominal-structured", "structured"}
                                or (
                                    isinstance(expected_result_contract, str)
                                    and value_contracts.declared_equal_result_contract(
                                        candidate
                                    )
                                    == expected_result_contract
                                )
                            )
                        if not shared:
                            refuse(owner, operation, str(instruction_index), "typing")
                            return None
                        for member, candidates in zip(
                            members,
                            referenced,
                            strict=True,
                        ):
                            narrow_reference(
                                instruction,
                                member,
                                tuple(
                                    candidate
                                    for candidate in candidates
                                    if any(
                                        value_contracts.matches(candidate, common)
                                        for common in shared
                                    )
                                ),
                            )
                    if constraint_kind == "fixed-value-contract":
                        expected = fixed_value_contracts[constraint["contract"]]
                        for member, candidates in zip(
                            members,
                            referenced,
                            strict=True,
                        ):
                            narrowed = tuple(
                                candidate
                                for candidate in candidates
                                if value_contracts.matches(candidate, expected)
                            )
                            if not narrowed:
                                refuse(
                                    owner,
                                    operation,
                                    str(instruction_index),
                                    "typing",
                                )
                                return None
                            narrow_reference(
                                instruction,
                                member,
                                narrowed,
                            )
                    if constraint_kind == "runtime-numeric":
                        for member, candidates in zip(
                            members,
                            referenced,
                            strict=True,
                        ):
                            narrowed = tuple(
                                candidate
                                for candidate in candidates
                                if candidate.get("numeric_policy")
                                in runtime_numeric_policies
                            )
                            if not narrowed:
                                refuse(
                                    owner,
                                    operation,
                                    str(instruction_index),
                                    "typing",
                                )
                                return None
                            narrow_reference(
                                instruction,
                                member,
                                narrowed,
                            )
                    if constraint_kind == "writable-port" and any(
                        not isinstance(instruction.get(member), str)
                        or instruction[member] not in parent_ports
                        or parent_ports[instruction[member]].get("access")
                        not in {"read-write", "write"}
                        for member in members
                    ):
                        refuse(owner, operation, str(instruction_index), "typing")
                        return None
                if node["semantics"]["operator"] == "cancel-event":
                    target_contract = node["semantics"]["target_reference"]
                    target = instruction.get(target_contract["instruction_member"])
                    variants = {
                        variant["kind"]: variant
                        for variant in target_contract["variants"]
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
                        not isinstance(target_variant, dict)
                        or not isinstance(target_value, str)
                        or not target_value
                        or set(cast(dict[str, Any], target))
                        != {"kind", target_variant["value_member"]}
                        or (
                            target_variant["kind"] == "port"
                            and (
                                target_value not in parent_ports
                                or not value_contracts.matches(
                                    parent_ports[target_value],
                                    fixed_value_contracts[
                                        target_variant["value_contract"]
                                    ],
                                )
                            )
                        )
                    ):
                        refuse(owner, operation, str(instruction_index), "event")
                        return None
                operator = node["semantics"]["operator"]
                if operator == "typed-require":
                    refusal_reference = node["semantics"].get("refusal_reference")
                    reason_member = (
                        refusal_reference.get("instruction_member")
                        if isinstance(refusal_reference, dict)
                        else None
                    )
                    reason = (
                        instruction.get(reason_member)
                        if isinstance(reason_member, str)
                        else None
                    )
                    if (
                        not isinstance(instruction.get("expected"), bool)
                        or reason_member not in node["required_members"]
                        or refusal_reference.get("source")
                        != "enclosing-operation.refusals"
                        or not isinstance(reason, str)
                        or reason not in refusals
                    ):
                        refuse(
                            owner,
                            operation,
                            str(instruction_index),
                            "refusals",
                        )
                        return None
                if operator == "guarded-outcome-block":
                    body = instruction.get("body")
                    guarded_outcome = instruction.get("outcome")
                    if (
                        key in guard_body_keys
                        or not isinstance(body, list)
                        or not all(isinstance(item, dict) for item in body)
                        or any(item.get("node") == "guard-block" for item in body)
                        or any(
                            isinstance(body_node, dict)
                            and body_node.get("result", {}).get("kind") == "outcome"
                            for item in body
                            if (body_node := node_definitions.get(item.get("node")))
                        )
                        or guarded_outcome not in parent_outcomes
                    ):
                        refuse(
                            owner,
                            operation,
                            str(instruction_index),
                            "body",
                        )
                        return None
                    guard_key = (
                        key[0],
                        key[1],
                        f"{key[2]}#guard-{instruction_index}",
                    )
                    unit_contract = cast(
                        dict[str, Any], fixed_value_contracts["kernel-unit"]
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
                        for name, candidates in lexical_environment.items()
                        if len(candidates) == 1
                    ]
                    if len(synthetic_inputs) != len(lexical_environment):
                        refuse(
                            owner,
                            operation,
                            str(instruction_index),
                            "typing",
                        )
                        return None
                    synthetic = {
                        "body": body,
                        "default_outcome": guarded_outcome,
                        "effects": list(effects),
                        "id": guard_key[2],
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
                    operations[guard_key] = (owner, synthetic)
                    guard_body_keys.add(guard_key)
                    try:
                        guard_closure = close(guard_key, (*stack, key))
                    finally:
                        guard_body_keys.discard(guard_key)
                        operations.pop(guard_key, None)
                        cache.pop(guard_key, None)
                    if guard_closure is None:
                        return None
                    body_effects, body_refusals, _body_charge = guard_closure
                    if not body_effects <= effects:
                        refuse(
                            owner,
                            operation,
                            str(instruction_index),
                            "effects",
                        )
                        return None
                    if not body_refusals <= refusals:
                        refuse(
                            owner,
                            operation,
                            str(instruction_index),
                            "refusals",
                        )
                        return None
                result_definition = cast(dict[str, Any], node["result"])
                if result_definition["kind"] in {"local", "draw"}:
                    if (
                        not isinstance(target, str)
                        or not target
                        or target in lexical_environment
                    ):
                        refuse(owner, operation, str(instruction_index), "target")
                        return None
                    typing = cast(dict[str, Any], result_definition["typing"])
                    typing_kind = typing["kind"]
                    if typing_kind == "fixed":
                        expected_contract = cast(
                            dict[str, Any],
                            fixed_value_contracts[typing["contract"]],
                        )
                        if operator == "collection-is-empty":
                            value_name = instruction.get("value")
                            value_candidates = (
                                lexical_environment.get(value_name)
                                if isinstance(value_name, str)
                                else None
                            )
                            result_candidates = (
                                (expected_contract,)
                                if value_candidates
                                and all(
                                    value_contracts.declared_is_empty_result_contract(
                                        candidate
                                    )
                                    == typing["contract"]
                                    for candidate in value_candidates
                                )
                                else ()
                            )
                        else:
                            result_candidates = (expected_contract,)
                    elif typing_kind == "same-as-references":
                        referenced = referenced_candidates(
                            instruction,
                            cast(list[str], typing["members"]),
                        )
                        result_candidates = (
                            compatible_candidates(referenced)
                            if referenced is not None
                            else ()
                        )
                    elif typing_kind == "declared-result":
                        value_name = instruction.get("value")
                        value_candidates = (
                            lexical_environment.get(value_name)
                            if isinstance(value_name, str)
                            else None
                        )
                        declared_results = (
                            tuple(
                                result
                                for candidate in value_candidates
                                if (
                                    result := value_contracts.declared_lookup_contract(
                                        candidate,
                                        instruction.get("key"),
                                        locals_.get(cast(str, instruction.get("key")))
                                        if isinstance(instruction.get("key"), str)
                                        else None,
                                    )
                                )
                                is not None
                            )
                            if value_candidates is not None
                            else ()
                        )
                        if any(
                            signal not in cast(list[str], node.get("refusals", []))
                            or len(reasons_by_signal.get(signal, [])) != 1
                            or reasons_by_signal[signal][0] not in refusals
                            for _result, signal in declared_results
                        ):
                            refuse(
                                owner,
                                operation,
                                str(instruction_index),
                                "refusals",
                            )
                            return None
                        result_candidates = tuple(
                            result for result, _signal in declared_results
                        )
                    else:
                        literal_candidates = [
                            value_contracts.literal_contracts(instruction.get(member))
                            for member in cast(list[str], typing["members"])
                        ]
                        result_candidates = compatible_candidates(literal_candidates)
                    if not result_candidates:
                        refuse(owner, operation, str(instruction_index), "typing")
                        return None
                    locals_[target] = result_candidates
                    lexical_environment[target] = result_candidates
                    local_producers[target] = 1
                    if source_kind == "local" and target == source.get("name"):
                        source_producer_reached = True
                continue
            site = instruction.get("site")
            if not isinstance(site, str) or not site or site in seen_sites:
                refuse(owner, operation, str(site), "site")
                return None
            seen_sites.add(site)
            child_ref = instruction.get("operation")
            if not isinstance(child_ref, dict):
                refuse(owner, operation, site, "operation")
                return None
            child_key = (
                child_ref.get("package"),
                child_ref.get("version"),
                child_ref.get("id"),
            )
            if child_key not in operations:
                refuse(owner, operation, site, "operation")
                return None
            _child_owner, child = operations[cast(tuple[str, str, str], child_key)]
            child_ports = cast(list[dict[str, Any]], child["inputs"])
            arguments = instruction.get("arguments")
            if not isinstance(arguments, list) or [
                item.get("port") for item in arguments
            ] != [item["id"] for item in child_ports]:
                refuse(owner, operation, site, "arguments")
                return None
            aliases: dict[str, list[tuple[str, str]]] = {}
            for formal, argument in zip(child_ports, arguments, strict=True):
                operand = argument.get("operand")
                if not isinstance(operand, dict):
                    refuse(owner, operation, site, "arguments")
                    return None
                kind = operand.get("kind")
                if kind == "port":
                    operand_port = operand.get("port")
                    actual = (
                        parent_ports.get(operand_port)
                        if isinstance(operand_port, str)
                        else None
                    )
                    if (
                        actual is None
                        or not value_contracts.matches(actual, formal)
                        or (
                            formal["access"] in {"read-write", "write"}
                            and actual["access"] not in {"read-write", "write"}
                        )
                    ):
                        refuse(owner, operation, site, "arguments")
                        return None
                    alias_key = f"port:{operand['port']}"
                elif kind == "local":
                    operand_local = operand.get("local")
                    actual_candidates = (
                        locals_.get(operand_local)
                        if isinstance(operand_local, str)
                        else None
                    )
                    if (
                        not actual_candidates
                        or formal["access"] != "read"
                        or len(
                            [
                                actual
                                for actual in actual_candidates
                                if value_contracts.matches(actual, formal)
                            ]
                        )
                        != 1
                    ):
                        refuse(owner, operation, site, "arguments")
                        return None
                    alias_key = f"local:{operand['local']}"
                elif kind == "literal":
                    literal = operand.get("literal")
                    if formal[
                        "access"
                    ] != "read" or not value_contracts.literal_matches(literal, formal):
                        refuse(owner, operation, site, "arguments")
                        return None
                    alias_key = f"literal:{operand['literal']}"
                else:
                    refuse(owner, operation, site, "arguments")
                    return None
                aliases.setdefault(alias_key, []).append(
                    (cast(str, formal["id"]), cast(str, formal["access"]))
                )
            if not _operation_aliases_are_admitted(child, aliases):
                refuse(owner, operation, site, "aliases")
                return None
            result = instruction.get("result")
            if not isinstance(result, dict):
                refuse(owner, operation, site, "result")
                return None
            if result.get("kind") == "discard":
                if child["result"].get("discardable") is not True:
                    refuse(owner, operation, site, "result")
                    return None
            elif result.get("kind") == "local":
                name = result.get("name")
                if not isinstance(name, str) or not name or name in lexical_environment:
                    refuse(owner, operation, site, "result")
                    return None
                child_result = cast(dict[str, Any], child["result"])
                locals_[name] = (child_result,)
                lexical_environment[name] = (child_result,)
                local_producers[name] = 1
            elif result.get("kind") == "operation-result":
                if not value_contracts.matches(
                    cast(dict[str, Any], child["result"]),
                    cast(dict[str, Any], operation["result"]),
                ):
                    refuse(owner, operation, site, "result")
                    return None
                operation_result_sites.add(site)
            else:
                refuse(owner, operation, site, "result")
                return None
            outcomes = instruction.get("outcomes")
            child_outcomes = [
                item["id"]
                for item in cast(list[dict[str, Any]], child.get("outcomes", []))
            ]
            if (
                not isinstance(outcomes, list)
                or [item.get("outcome") for item in outcomes] != child_outcomes
                or (
                    key in guard_body_keys
                    and any(
                        item.get("action", {}).get("kind") == "propagate"
                        for item in outcomes
                    )
                )
                or any(
                    item.get("action", {}).get("kind") == "propagate"
                    and item["action"].get("outcome") not in parent_outcomes
                    for item in outcomes
                )
            ):
                refuse(owner, operation, site, "outcomes")
                return None
            child_outcome_definitions = {
                item["id"]: item
                for item in cast(list[dict[str, Any]], child.get("outcomes", []))
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
                    for mapping in cast(list[dict[str, Any]], outcomes)
                )
                exits_success_before_source = (
                    not source_producer_reached
                    and not produces_source
                    and any(
                        mapping["action"].get("kind") == "propagate"
                        and mapping["action"].get("outcome") in parent_successes
                        for mapping in cast(list[dict[str, Any]], outcomes)
                    )
                )
                if (
                    produces_source and reaches_parent_success
                ) or exits_success_before_source:
                    found.add(
                        f"language.operations.{owner}.{operation['id']}.result.source"
                    )
                    return None
                if produces_source:
                    source_producer_reached = True
            child_closure = close(cast(tuple[str, str, str], child_key), (*stack, key))
            if child_closure is None:
                return None
            child_effects, child_refusals, _child_charge = child_closure
            if not child_effects <= set(cast(list[str], operation["effects"])):
                refuse(owner, operation, site, "effects")
                return None
            if not child_refusals <= set(cast(list[str], operation["refusals"])):
                refuse(owner, operation, site, "refusals")
                return None

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
                and value_contracts.matches(
                    cast(dict[str, Any], parent_ports[source["name"]]),
                    result_contract,
                )
            )
            or (
                source_kind == "local"
                and local_producers.get(cast(str, source.get("name"))) == 1
                and source_producer_reached
                and bool(local_result_candidates)
                and len(
                    [
                        candidate
                        for candidate in cast(
                            tuple[dict[str, Any], ...],
                            local_result_candidates,
                        )
                        if value_contracts.matches(
                            candidate,
                            result_contract,
                        )
                    ]
                )
                == 1
            )
            or (
                source_kind == "unit"
                and value_contracts.matches(
                    result_contract,
                    cast(dict[str, Any], fixed_value_contracts["kernel-unit"]),
                )
            )
        )
        if not source_is_compatible:
            found.add(f"language.operations.{owner}.{operation['id']}.result.source")
            return None
        try:
            projection = project_operation_program(
                key,
                {
                    coordinate: definition
                    for coordinate, (
                        _definition_owner,
                        definition,
                    ) in operations.items()
                },
                operation_node_ids=operation_node_ids,
                invocation_node_ids=invocation_node_ids,
            )
        except (KeyError, TypeError, ValueError):
            refuse(owner, operation, "closure", "operation")
            return None
        if projection.resource_charge > operation["resource_bounds"]["max_steps"]:
            found.add(f"language.operations.{owner}.{operation['id']}.resource_bounds")
            return None
        cache[key] = (
            projection.effects,
            projection.refusals,
            projection.resource_charge,
        )
        return cache[key]

    for key in sorted(operations):
        close(key, ())
    return tuple(sorted(found))


def admit_authorities(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> BootstrapAdmission:
    """Admit an authority pair or return all deterministic bootstrap diagnostics."""
    found: set[AdmissionDiagnostic] = set()

    def refuse(code: str, stage: str, subject: str) -> None:
        found.add(AdmissionDiagnostic(code=code, stage=stage, subject=subject))

    kernel_identity = kernel.get("content_identity")
    raw_graph_candidate = isinstance(
        language_bundle, LanguageBundleGraph
    ) and not isinstance(language_bundle, LanguageBundleIndex)
    raw_graph_root = getattr(language_bundle, "root", None)
    raw_graph_releases = getattr(language_bundle, "package_releases", None)
    raw_graph_vector_sets = getattr(
        language_bundle, "package_conformance_vector_sets", None
    )
    raw_graph_root_size = getattr(language_bundle, "root_byte_size", None)
    raw_graph_package_sizes = getattr(language_bundle, "package_byte_sizes", None)
    raw_graph_vector_set_sizes = getattr(language_bundle, "vector_set_byte_sizes", None)
    is_graph = (
        isinstance(raw_graph_root, dict)
        and isinstance(raw_graph_releases, list)
        and isinstance(raw_graph_vector_sets, list)
        and isinstance(raw_graph_root_size, int)
        and isinstance(raw_graph_package_sizes, tuple)
        and isinstance(raw_graph_vector_set_sizes, tuple)
    )
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
    if (
        is_graph
        and isinstance(descriptor_order, list)
        and all(isinstance(item, str) for item in descriptor_order)
    ):
        (
            graph_root,
            graph_releases,
            graph_vector_sets,
            normalized_package_sizes,
            normalized_vector_set_sizes,
        ) = canonical_graph_members(
            graph_root,
            graph_releases,
            graph_vector_sets,
            list(graph_package_sizes),
            list(graph_vector_set_sizes),
            cast(list[str], descriptor_order),
        )
        graph_package_sizes = tuple(normalized_package_sizes)
        graph_vector_set_sizes = tuple(normalized_vector_set_sizes)
    identity_source = graph_root if is_graph else language_bundle
    ldb_identity = identity_source.get("content_identity")
    canonical_encoding = kernel.get("canonical_encoding")
    kernel_domain = _declared_identity_domain(kernel, artifact="kernel")
    ldb_domain = _declared_identity_domain(kernel, artifact="language-bundle")
    package_release_domain = _declared_identity_domain(
        kernel, collection="language_bundle.language.packages"
    )
    package_vector_set_domain = _declared_identity_domain(
        kernel,
        collection="language_bundle.package_conformance_vector_sets",
    )
    computed_kernel_identity = _safe_artifact_identity(
        kernel_domain, kernel, canonical_encoding
    )
    computed_ldb_identity = _safe_artifact_identity(
        ldb_domain, identity_source, canonical_encoding
    )
    if (
        not isinstance(kernel_identity, str)
        or kernel_identity != computed_kernel_identity
        or kernel_identity != _SUPPORTED_KERNEL_IDENTITY
    ):
        refuse("kernel.identity_mismatch", "ingress", "kernel")
    if not isinstance(ldb_identity, str) or ldb_identity != computed_ldb_identity:
        refuse("kernel.identity_mismatch", "ingress", "language-bundle")
    if language_bundle.get("kernel_identity") != kernel_identity:
        refuse(
            "kernel.binding_mismatch",
            "ingress",
            "language-bundle.kernel_identity",
        )
    if is_graph:
        root_members = {
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
        descriptor_members = (
            set(descriptor_required)
            if isinstance(descriptor_required, list)
            and all(isinstance(item, str) for item in descriptor_required)
            else set()
        )
        descriptors = graph_root.get("package_descriptors")
        if (
            set(graph_root) != root_members
            or graph_root.get("artifact_kind") != "language-definition-bundle"
            or graph_root.get("artifact_version") != "2.0.0"
            or graph_root.get("schema_major") != 2
            or not isinstance(descriptors, list)
            or len(descriptors) != len(graph_releases)
            or len(descriptors) != len(graph_vector_sets)
            or len(descriptors) != len(graph_package_sizes)
            or len(descriptors) != len(graph_vector_set_sizes)
        ):
            refuse("kernel.member_set_mismatch", "ingress", "language-bundle")
        else:
            coordinates: list[tuple[str, str]] = []
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
                    or set(descriptor) != descriptor_members
                    or not isinstance(descriptor_field_types, dict)
                    or set(descriptor_field_types) != descriptor_members
                    or not all(
                        _value_matches_contract(
                            descriptor[name],
                            descriptor_field_types[name],
                            language_bundle,
                        )
                        for name in descriptor_members
                    )
                    or not isinstance(release, dict)
                    or descriptor.get("artifact_kind") != release.get("artifact_kind")
                    or descriptor.get("id") != release.get("id")
                    or descriptor.get("version") != release.get("version")
                    or descriptor.get("content_identity")
                    != release.get("content_identity")
                    or descriptor.get("byte_size") != package_byte_size
                ):
                    refuse("kernel.binding_mismatch", "ingress", subject)
                    continue
                if not isinstance(descriptor["id"], str) or not isinstance(
                    descriptor["version"], str
                ):
                    continue
                coordinate = (descriptor["id"], descriptor["version"])
                coordinates.append(coordinate)
                if release.get("content_identity") != _safe_artifact_identity(
                    package_release_domain, release, canonical_encoding
                ):
                    refuse("kernel.identity_mismatch", "ingress", subject)
                vector_descriptor = release.get("conformance_vectors")
                vector_subject = f"{subject}.conformance_vectors"
                if (
                    not isinstance(vector_descriptor, dict)
                    or set(vector_descriptor)
                    != {"artifact_kind", "byte_size", "content_identity"}
                    or not isinstance(vector_set, dict)
                    or vector_descriptor.get("artifact_kind")
                    != vector_set.get("artifact_kind")
                    or vector_descriptor.get("content_identity")
                    != vector_set.get("content_identity")
                    or vector_descriptor.get("byte_size") != vector_set_byte_size
                    or vector_set.get("package_id") != release.get("id")
                    or vector_set.get("package_version") != release.get("version")
                ):
                    refuse("kernel.binding_mismatch", "ingress", vector_subject)
                elif vector_set.get("content_identity") != _safe_artifact_identity(
                    package_vector_set_domain, vector_set, canonical_encoding
                ):
                    refuse("kernel.identity_mismatch", "ingress", vector_subject)
            if coordinates != sorted(coordinates):
                refuse(
                    "kernel.member_set_mismatch",
                    "ingress",
                    "language-bundle.package_descriptors",
                )
            if len(coordinates) != len(set(coordinates)):
                refuse(
                    "kernel.duplicate_identifier",
                    "static",
                    "language-bundle.package_descriptors",
                )
            available = set(coordinates)
            dependency_graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
            for release in graph_releases:
                package_id = str(release.get("id", ""))
                package_version = str(release.get("version", ""))
                dependencies = release.get("dependencies")
                required = (
                    dependencies.get("required")
                    if isinstance(dependencies, dict)
                    else None
                )
                optional = (
                    dependencies.get("optional")
                    if isinstance(dependencies, dict)
                    else None
                )
                if (
                    not isinstance(required, list)
                    or not isinstance(optional, list)
                    or not all(
                        isinstance(item, dict)
                        and set(item) == {"id", "version"}
                        and isinstance(item["id"], str)
                        and bool(item["id"])
                        and isinstance(item["version"], str)
                        and bool(item["version"])
                        for item in [*required, *optional]
                    )
                ):
                    refuse(
                        "kernel.member_set_mismatch",
                        "ingress",
                        f"language-bundle.packages.{package_id}.dependencies",
                    )
                    continue
                required_coordinates = {
                    (item["id"], item["version"]) for item in required
                }
                all_coordinates = {
                    (item["id"], item["version"]) for item in [*required, *optional]
                }
                dependency_graph[(package_id, package_version)] = required_coordinates
                if len(all_coordinates) != len([*required, *optional]) or not (
                    all_coordinates <= available
                ):
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
            graph_resources = kernel.get("resources")
            graph_limit_names = (
                "max_ldb_root_bytes",
                "max_ldb_child_bytes",
                "max_ldb_package_bytes",
                "max_ldb_total_bytes",
                "max_ldb_package_count",
                "max_ldb_package_member_count",
                "max_ldb_dependency_depth",
                "max_ldb_dependency_steps",
                "max_ldb_admission_work",
            )
            graph_limits = (
                {name: graph_resources.get(name) for name in graph_limit_names}
                if isinstance(graph_resources, dict)
                else {}
            )
            if set(graph_limits) != set(graph_limit_names) or not all(
                isinstance(value, int) and value > 0 for value in graph_limits.values()
            ):
                refuse(
                    "kernel.resource_exhausted",
                    "ingress",
                    "kernel.resources",
                )
            else:
                typed_graph_limits = cast(dict[str, int], graph_limits)
                dependency_steps = sum(
                    len(dependencies) for dependencies in dependency_graph.values()
                )
                dependency_depth = 0
                if not has_dependency_cycle:
                    depth_by_package: dict[tuple[str, str], int] = {}

                    def dependency_depth_of(coordinate: tuple[str, str]) -> int:
                        known = depth_by_package.get(coordinate)
                        if known is not None:
                            return known
                        depth = 1 + max(
                            (
                                dependency_depth_of(dependency)
                                for dependency in sorted(
                                    dependency_graph.get(coordinate, set())
                                )
                            ),
                            default=0,
                        )
                        depth_by_package[coordinate] = depth
                        return depth

                    dependency_depth = max(
                        (
                            dependency_depth_of(coordinate)
                            for coordinate in sorted(dependency_graph)
                        ),
                        default=0,
                    )
                graph_work = (
                    _resource_work(graph_root)
                    + sum(_resource_work(release) for release in graph_releases)
                    + sum(
                        _resource_work(vector_set) for vector_set in graph_vector_sets
                    )
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
            required_language_members = kernel.get("admission", {}).get(
                "required_language_members"
            )
            if raw_graph_candidate and found:
                return _result(
                    found,
                    128,
                    kernel_identity if isinstance(kernel_identity, str) else None,
                    ldb_identity if isinstance(ldb_identity, str) else None,
                    (),
                    (),
                    (),
                    (),
                    (),
                )
            if (
                isinstance(required_language_members, list)
                and all(isinstance(item, str) for item in required_language_members)
                and isinstance(descriptor_order, list)
                and all(isinstance(item, str) for item in descriptor_order)
            ):
                try:
                    expected_index = derive_language_index(
                        graph_root,
                        graph_releases,
                        graph_vector_sets,
                        cast(list[str], required_language_members),
                        root_byte_size=graph_root_size,
                        package_byte_sizes=list(graph_package_sizes),
                        vector_set_byte_sizes=list(graph_vector_set_sizes),
                        descriptor_order=cast(list[str], descriptor_order),
                    )
                except ValueError:
                    expected_index = None
                if expected_index is None:
                    refuse(
                        "kernel.identity_mismatch",
                        "ingress",
                        "language-bundle.admitted-index",
                    )
                elif raw_graph_candidate:
                    language_bundle = expected_index
                elif dict(expected_index) != dict(language_bundle):
                    refuse(
                        "kernel.identity_mismatch",
                        "ingress",
                        "language-bundle.admitted-index",
                    )
            else:
                refuse(
                    "kernel.member_set_mismatch",
                    "ingress",
                    "kernel.meta_format.admitted_language_index",
                )
            if raw_graph_candidate and found:
                return _result(
                    found,
                    128,
                    kernel_identity if isinstance(kernel_identity, str) else None,
                    ldb_identity if isinstance(ldb_identity, str) else None,
                    (),
                    (),
                    (),
                    (),
                    (),
                )
    if set(kernel) != _KERNEL_MEMBERS:
        refuse("kernel.member_set_mismatch", "ingress", "kernel")
    if any(item.subject == "kernel" for item in found):
        return _result(
            found,
            128,
            kernel_identity if isinstance(kernel_identity, str) else None,
            ldb_identity if isinstance(ldb_identity, str) else None,
            (),
            (),
            (),
            (),
            (),
        )

    admission = cast(dict[str, Any], kernel.get("admission", {}))
    raw_meta_format = kernel.get("meta_format")
    admitted_index_contract = (
        raw_meta_format.get("admitted_language_index")
        if isinstance(raw_meta_format, dict)
        else None
    )
    expected_members = set(
        cast(
            list[str],
            admitted_index_contract.get("required_members", [])
            if isinstance(admitted_index_contract, dict)
            else [],
        )
    )
    if set(language_bundle) != expected_members:
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")
    raw_language = language_bundle.get("language")
    expected_language_members = set(
        cast(list[str], admission.get("required_language_members", []))
    )
    if (
        not isinstance(raw_language, dict)
        or set(raw_language) != expected_language_members
    ):
        refuse(
            "kernel.member_set_mismatch",
            "ingress",
            "language-bundle.language",
        )
    refusal_stages = admission.get("refusal_stages")
    if not _language_bundle_is_closed(
        language_bundle, admitted_index_contract, refusal_stages
    ):
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")

    resources = cast(dict[str, Any], kernel.get("resources", {}))
    max_bytes = resources.get("max_authority_bytes", 262144)
    if not isinstance(max_bytes, int) or max_bytes < 1:
        max_bytes = 262144
        refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
    max_depth = resources.get("max_nesting_depth", 32)
    max_members = resources.get("max_members", 256)
    if not isinstance(max_depth, int) or max_depth < 1:
        max_depth = 32
        refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
    if not isinstance(max_members, int) or max_members < 1:
        max_members = 256
        refuse("kernel.resource_exhausted", "ingress", "kernel.resources")
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
        resource_artifacts.append(("language-bundle", language_bundle))
    for subject, artifact in resource_artifacts:
        depth, largest_collection = _resource_shape(artifact)
        if depth > max_depth or largest_collection > max_members:
            refuse("kernel.resource_exhausted", "ingress", subject)
        try:
            size = len(canonical_bytes(cast(JsonValue, artifact)))
        except (TypeError, ValueError):
            size = max_bytes + 1
        if size > max_bytes:
            refuse("kernel.resource_exhausted", "ingress", subject)

    packages = raw_language.get("packages") if isinstance(raw_language, dict) else None
    package_contract = (
        raw_meta_format.get("package_release")
        if isinstance(raw_meta_format, dict)
        else None
    )
    package_vector_contract = (
        raw_meta_format.get("package_vector")
        if isinstance(raw_meta_format, dict)
        else None
    )
    package_vector_set_contract = (
        raw_meta_format.get("package_conformance_vector_set")
        if isinstance(raw_meta_format, dict)
        else None
    )
    runtime_program_contract = (
        raw_meta_format.get("runtime_program")
        if isinstance(raw_meta_format, dict)
        else None
    )
    named_rng_contract = (
        runtime_program_contract.get("named_rng")
        if isinstance(runtime_program_contract, dict)
        else None
    )
    candidate_encoding_contract = (
        named_rng_contract.get("candidate_encoding")
        if isinstance(named_rng_contract, dict)
        else None
    )
    definitions_are_closed = _language_definitions_are_closed(
        language_bundle,
        raw_meta_format if isinstance(raw_meta_format, dict) else {},
    )
    artifact_semantic_projections_are_closed = (
        definitions_are_closed
        and _artifact_semantic_identity_projections_are_closed(language_bundle)
    )
    literal_typing_profiles_are_closed = (
        definitions_are_closed
        and _literal_typing_profiles_are_closed(kernel, language_bundle)
    )
    composition_subjects = (
        _operation_composition_diagnostic_subjects(kernel, language_bundle)
        if literal_typing_profiles_are_closed
        else ()
    )
    diagnostic_catalog_matches_vectors = _diagnostic_catalog_matches_vectors(
        language_bundle
    )
    admitted_packages: list[dict[str, Any]] = []
    semantic_projection_mismatch = False
    if not _package_vector_contract_is_closed(package_vector_contract):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "kernel.meta_format.package_vector",
        )
    if not isinstance(packages, list):
        refuse(
            "kernel.member_set_mismatch", "ingress", "language-bundle.language.packages"
        )
    else:
        for index, package in enumerate(packages):
            subject = f"language-bundle.language.packages.{index}"
            if not isinstance(package, dict) or not _package_is_closed(
                package, package_contract, language_bundle
            ):
                refuse("kernel.member_set_mismatch", "ingress", subject)
                continue
            admitted_packages.append(package)
            if package.get("content_identity") != _safe_artifact_identity(
                package_release_domain, package, canonical_encoding
            ):
                refuse("kernel.identity_mismatch", "ingress", subject)
            if not _package_semantic_closure_is_closed(package, package_contract):
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
                or not _package_conformance_vector_set_is_closed(
                    vector_set, package_vector_set_contract
                )
                or vector_set.get("package_id") != package.get("id")
                or vector_set.get("package_version") != package.get("version")
                or (
                    literal_typing_profiles_are_closed
                    and not composition_subjects
                    and diagnostic_catalog_matches_vectors
                    and not _package_evidence_vectors_are_closed(
                        package,
                        vector_set,
                        package_vector_contract,
                        candidate_encoding_contract,
                        runtime_program_contract,
                        kernel,
                        language_bundle,
                    )
                )
            ):
                refuse("kernel.vector_mismatch", "static", f"{subject}.vectors")
        semantic_projection_mismatch = len(admitted_packages) == len(
            packages
        ) and not _package_semantic_projections_are_exact(
            admitted_packages, package_contract, language_bundle
        )

    cap = resources.get("max_diagnostics", 128)
    if not isinstance(cap, int) or cap < 1:
        cap = 128
    if found:
        return _result(
            found,
            cap,
            kernel_identity if isinstance(kernel_identity, str) else None,
            ldb_identity if isinstance(ldb_identity, str) else None,
            (),
            (),
            (),
            (),
            (),
        )

    laws = cast(list[dict[str, Any]], admission.get("laws", []))
    for subject in _duplicate_identifier_subjects(kernel, language_bundle):
        refuse("kernel.duplicate_identifier", "static", subject)
    law_ids = [str(law.get("id", "")) for law in laws]
    if len(law_ids) != len(set(law_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.admission.laws")
    operation_law = next(
        (law for law in laws if law.get("id") == "kernel.operations.closed"), None
    )
    operation_arguments = (
        operation_law.get("arguments", {}) if isinstance(operation_law, dict) else {}
    )
    allowed_operations = operation_arguments.get("admission_operations")
    if not isinstance(allowed_operations, list) or set(allowed_operations) != set(
        _KNOWN_OPERATIONS
    ):
        refuse("kernel.unknown_operation", "static", "kernel.operations.closed")
    for law in laws:
        if law.get("operation") not in set(allowed_operations or []):
            refuse("kernel.unknown_operation", "static", str(law.get("id", "")))
    law_projections = tuple(
        sorted(
            (
                str(law.get("id", "")),
                content_identity("kernel-law-projection-v2", cast(JsonValue, law)),
            )
            for law in laws
        )
    )

    kernel_vectors = cast(list[dict[str, Any]], kernel.get("vectors", []))
    kernel_vector_ids = [str(vector.get("id", "")) for vector in kernel_vectors]
    if len(kernel_vector_ids) != len(set(kernel_vector_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.vectors")
    referenced_laws = {str(vector.get("law", "")) for vector in kernel_vectors}
    if set(law_ids) != referenced_laws:
        refuse("kernel.vector_mismatch", "static", "kernel.vectors")
    kernel_diagnostics = cast(list[dict[str, Any]], kernel.get("diagnostics", []))
    kernel_codes = [str(item.get("code", "")) for item in kernel_diagnostics]
    if len(kernel_codes) != len(set(kernel_codes)):
        refuse("kernel.duplicate_identifier", "static", "kernel.diagnostics")
    kernel_catalog = {
        (str(item.get("code", "")), str(item.get("stage", "")))
        for item in kernel_diagnostics
    }
    if kernel_catalog != set(BOOTSTRAP_REFUSAL_CATALOG):
        refuse("kernel.diagnostic_closure", "static", "kernel.diagnostics")
    kernel_vector_catalog = {
        (str(item["diagnostic"]), str(item.get("stage", "")))
        for item in kernel_vectors
        if "diagnostic" in item
    }
    if kernel_catalog != kernel_vector_catalog:
        refuse("kernel.diagnostic_closure", "static", "kernel.diagnostics")

    language = cast(dict[str, Any], language_bundle.get("language", {}))
    meta_format = cast(dict[str, Any], kernel.get("meta_format", {}))
    if not definitions_are_closed:
        refuse("kernel.vector_mismatch", "static", "language.definitions")
    if definitions_are_closed and not artifact_semantic_projections_are_closed:
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.definitions.artifact-semantic-projections",
        )
    if not _assignment_policy_is_total(language_bundle):
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
    if definitions_are_closed:
        for subject in composition_subjects:
            refuse("kernel.vector_mismatch", "static", subject)
    if not _json_pointer_authority_is_closed(kernel):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "kernel.meta-format.json-pointer",
        )
    if not _authority_wire_schema_projection_is_closed(kernel):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "kernel.meta-format.authority-wire-schema-projection",
        )
    if not _runtime_authority_is_closed(kernel, language_bundle):
        refuse("kernel.vector_mismatch", "static", "language.runtime")
    if not _wire_schema_identity_domains_are_closed(language_bundle):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.wire-schema-identity-domains",
        )
    if not _embedded_artifact_bindings_are_closed(language_bundle):
        refuse(
            "kernel.vector_mismatch",
            "static",
            "language.embedded-artifact-bindings",
        )
    ldb_diagnostics = cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
    ldb_codes = [str(item.get("code", "")) for item in ldb_diagnostics]
    if len(ldb_codes) != len(set(ldb_codes)):
        refuse("kernel.duplicate_identifier", "static", "language-bundle.diagnostics")
    if not diagnostic_catalog_matches_vectors:
        refuse("kernel.diagnostic_closure", "static", "language-bundle.diagnostics")
    raw_ldb_vectors = language_bundle.get("vectors")
    ldb_vectors: list[dict[str, Any]] = []
    if not isinstance(raw_ldb_vectors, list):
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    elif diagnostic_catalog_matches_vectors:
        for vector in raw_ldb_vectors:
            if _vector_header_is_closed(vector, meta_format, language_bundle):
                ldb_vectors.append(vector)
            else:
                subject = str(vector.get("id", "")) if isinstance(vector, dict) else ""
                refuse("kernel.vector_mismatch", "static", subject)
    raw_rules = language.get("rules")
    rules: list[dict[str, Any]] = []
    if not isinstance(raw_rules, list) or not all(
        _rule_is_closed(rule, meta_format, language_bundle) for rule in raw_rules
    ):
        refuse("kernel.vector_mismatch", "static", "language.rules")
    else:
        rules = cast(list[dict[str, Any]], raw_rules)
    raw_reasons = language.get("reasons")
    reasons: list[dict[str, Any]] = []
    if not isinstance(raw_reasons, list) or not all(
        _reason_is_closed(reason, meta_format, language_bundle)
        for reason in raw_reasons
    ):
        refuse("kernel.vector_mismatch", "static", "language.reasons")
    else:
        reasons = cast(list[dict[str, Any]], raw_reasons)
    if found:
        return _result(
            found,
            cap,
            kernel_identity if isinstance(kernel_identity, str) else None,
            ldb_identity if isinstance(ldb_identity, str) else None,
            tuple(sorted(law_ids)),
            law_projections,
            (),
            (),
            (),
        )
    rule_ids = [str(rule.get("id", "")) for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        refuse("kernel.duplicate_identifier", "static", "language.rules")
    ldb_vector_ids = [str(item.get("id", "")) for item in ldb_vectors]
    if len(ldb_vector_ids) != len(set(ldb_vector_ids)):
        refuse(
            "kernel.duplicate_identifier",
            "static",
            "language-bundle.vectors",
        )
    program_vectors = [item for item in ldb_vectors if "source_fixture" in item]
    program_contract = meta_format.get("model_program_vector")
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
    program_by_id = {str(item.get("id", "")): item for item in program_vectors}
    program_vectors_close = (
        isinstance(expected_categories, list)
        and isinstance(category_outcomes, dict)
        and set(expected_categories)
        == {str(item.get("category", "")) for item in program_vectors}
        and all(
            {
                str(item.get("expect", {}).get("outcome", ""))
                for item in program_vectors
                if item.get("category") == category
            }
            == set(category_outcomes.get(category, []))
            for category in expected_categories
        )
    )
    if program_vectors_close:
        for vector in program_vectors:
            relation = cast(dict[str, Any], vector["expect"]["relation"])
            if relation["kind"] == "independent":
                continue
            reference = program_by_id.get(str(relation["reference"]))
            if reference is None:
                program_vectors_close = False
                break
            expected = cast(dict[str, Any], vector["expect"])
            reference_expected = cast(dict[str, Any], reference["expect"])
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
    rule_vectors = [item for item in ldb_vectors if "rule" in item]
    if set(rule_ids) != {str(item["rule"]) for item in rule_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    rule_projections: list[tuple[str, str]] = []
    for vector in rule_vectors:
        output = _execute_rule_vector(rules, vector, meta_format, language_bundle)
        if output is None or output != vector.get("expect"):
            refuse("kernel.vector_mismatch", "static", str(vector.get("id", "")))
            continue
        rule_projections.append(
            (
                str(vector.get("id", "")),
                content_identity("rule-vector-projection-v2", cast(JsonValue, output)),
            )
        )

    reason_ids = [str(item.get("id", "")) for item in reasons]
    if len(reason_ids) != len(set(reason_ids)):
        refuse("kernel.duplicate_identifier", "static", "language.reasons")
    reason_vectors = [item for item in ldb_vectors if "diagnostic" in item]
    if set(reason_ids) != {str(item.get("reason", "")) for item in reason_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.reasons")
    by_reason = {str(item.get("id", "")): item for item in reasons}
    diagnostic_projections: list[tuple[str, str, str]] = []
    for vector in reason_vectors:
        reason = by_reason.get(str(vector.get("reason", "")))
        output = _execute_reason_vector(language_bundle, reason, vector, meta_format)
        expected = {
            "code": vector.get("diagnostic"),
            "matched": vector.get("matched"),
            "stage": vector.get("stage"),
        }
        if output != expected:
            refuse("kernel.vector_mismatch", "static", str(vector.get("id", "")))
            continue
        diagnostic_projections.append(
            (
                str(vector.get("id", "")),
                str(vector.get("diagnostic", "")),
                content_identity(
                    "diagnostic-vector-projection-v2", cast(JsonValue, output)
                ),
            )
        )
    for reason_id, reason in by_reason.items():
        vectors = [
            vector for vector in reason_vectors if vector.get("reason") == reason_id
        ]
        if not _reason_vectors_cover_operands(
            language_bundle, reason, vectors, meta_format
        ):
            refuse("kernel.vector_mismatch", "static", reason_id)

    if isinstance(packages, list):
        package_coordinates = [
            (str(package.get("id", "")), str(package.get("version", "")))
            for package in packages
            if isinstance(package, dict)
        ]
        if len(package_coordinates) != len(set(package_coordinates)):
            refuse("kernel.duplicate_identifier", "static", "language.packages")
        vector_ids = {str(item.get("id", "")) for item in ldb_vectors}
        vectors_by_id = {str(item.get("id", "")): item for item in ldb_vectors}
        constructor_ids = {
            str(item.get("id", ""))
            for item in cast(list[dict[str, Any]], language.get("constructors", []))
        }
        numeric_profiles = {
            str(item.get("id", ""))
            for item in cast(dict[str, Any], language.get("quantity", {})).get(
                "numeric_policies", []
            )
            if isinstance(item, dict)
        }
        vector_sets_by_coordinate = {
            (
                vector_set.get("package_id"),
                vector_set.get("package_version"),
            ): vector_set
            for vector_set in graph_vector_sets
            if isinstance(vector_set, dict)
        }
        for package in packages:
            if not isinstance(package, dict):
                continue
            exports = cast(dict[str, Any], package.get("exports", {}))
            profiles = cast(dict[str, Any], package.get("profiles", {}))
            vector_set = vector_sets_by_coordinate.get(
                (package.get("id"), package.get("version")), {}
            )
            references_close = (
                set(map(str, vector_set.get("vectors", []))) <= vector_ids
                and vector_set.get("vector_definitions")
                == [
                    vectors_by_id[vector_id]
                    for vector_id in vector_set.get("vectors", [])
                    if vector_id in vectors_by_id
                ]
                and set(map(str, exports.get("language_rules", []))) <= set(rule_ids)
                and set(map(str, exports.get("diagnostics", []))) <= set(ldb_codes)
                and set(map(str, profiles.get("numeric", []))) <= numeric_profiles
                and all(
                    str(item.get("constructor", "")) in constructor_ids
                    for item in exports.get("types", [])
                    if isinstance(item, dict)
                )
            )
            if not references_close:
                refuse(
                    "kernel.vector_mismatch",
                    "static",
                    f"language.packages.{package.get('id', '')}",
                )
        if not _reference_contracts_close(kernel, language_bundle):
            refuse("kernel.vector_mismatch", "static", "language.packages")

    if semantic_projection_mismatch and not found:
        for index in range(len(admitted_packages)):
            refuse(
                "kernel.identity_mismatch",
                "ingress",
                f"language-bundle.language.packages.{index}.semantic_identity",
            )

    return _result(
        found,
        cap,
        kernel_identity if isinstance(kernel_identity, str) else None,
        ldb_identity if isinstance(ldb_identity, str) else None,
        tuple(sorted(law_ids)),
        law_projections,
        tuple(sorted(rule_ids)),
        tuple(sorted(rule_projections)),
        tuple(sorted(diagnostic_projections)),
    )


def _json_pointer_authority_is_closed(kernel: dict[str, Any]) -> bool:
    meta = kernel.get("meta_format")
    json_pointer = meta.get("json_pointer") if isinstance(meta, dict) else None
    pointer_schema = (
        json_pointer.get("schema") if isinstance(json_pointer, dict) else None
    )
    pointer_schema_is_valid = False
    try:
        if isinstance(json_pointer, dict) and isinstance(pointer_schema, dict):
            pointer_schema_is_valid = _meta_validate_json_schema(
                canonical_bytes(cast(JsonValue, pointer_schema)),
                canonical_bytes(
                    cast(
                        JsonValue,
                        {
                            key: value
                            for key, value in json_pointer.items()
                            if key != "schema"
                        },
                    )
                ),
            )
    except (TypeError, ValueError, UnicodeEncodeError):
        pointer_schema_is_valid = False
    return (
        isinstance(json_pointer, dict)
        and set(json_pointer) == {"encoding", "schema", "target_policy"}
        and json_pointer.get("encoding") == "RFC6901"
        and json_pointer.get("target_policy") == "existing-target"
        and pointer_schema_is_valid
        and isinstance(pointer_schema, dict)
        and pointer_schema.get("type") == "string"
    )


def _authority_wire_schema_projection_is_closed(kernel: dict[str, Any]) -> bool:
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


def _result(
    found: set[AdmissionDiagnostic],
    cap: int,
    kernel_identity: str | None,
    ldb_identity: str | None,
    law_ids: tuple[str, ...],
    law_projections: tuple[tuple[str, str], ...],
    rule_ids: tuple[str, ...],
    rule_projections: tuple[tuple[str, str], ...],
    diagnostic_projections: tuple[tuple[str, str, str], ...],
) -> BootstrapAdmission:
    ordered = sorted(found, key=lambda item: (item.stage, item.subject, item.code))
    truncated = len(ordered) > cap
    emitted = tuple(ordered[:cap])
    return BootstrapAdmission(
        admitted=not found,
        kernel_identity=kernel_identity,
        language_bundle_identity=ldb_identity,
        law_ids=law_ids,
        law_projections=law_projections,
        rule_ids=rule_ids,
        rule_projections=rule_projections,
        diagnostic_projections=diagnostic_projections,
        diagnostics=emitted,
        truncated=truncated,
    )
