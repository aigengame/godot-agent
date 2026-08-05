"""Authority-owned Wire-Schema identity projections."""

from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, content_identity


def _wire_schema_definition(
    language_bundle: dict[str, Any],
    artifact_kind: str,
) -> dict[str, Any]:
    language = cast(dict[str, Any], language_bundle["language"])
    matches = [
        item
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for item in cast(list[dict[str, Any]], language[collection])
        if item.get("artifact_kind") == artifact_kind
    ]
    if len(matches) != 1:
        raise ValueError(f"wire schema is not unique: {artifact_kind}")
    return matches[0]


def wire_schema_identity_domain(
    language_bundle: dict[str, Any],
    schema_kind: str,
) -> str:
    """Select the one admitted identity-domain authority for a Wire Schema."""
    language = cast(dict[str, Any], language_bundle["language"])
    definition = _wire_schema_definition(language_bundle, schema_kind)
    inline_domain = definition.get("wire_schema_identity_domain")
    contracts = [
        item
        for item in cast(list[dict[str, Any]], language["artifact_contracts"])
        if item.get("schema_kind") == schema_kind
    ]
    if len(contracts) > 1:
        raise ValueError(f"artifact schema contract is not unique: {schema_kind}")
    contract_domain = (
        contracts[0].get("wire_schema_identity_domain") if contracts else None
    )
    if inline_domain is None and contract_domain is None:
        raise ValueError(
            f"exact wire-schema identity domain is unavailable for {schema_kind}"
        )
    if inline_domain is not None and contract_domain is not None:
        raise ValueError(
            f"wire-schema identity-domain authority is ambiguous for {schema_kind}"
        )
    domain = inline_domain if inline_domain is not None else contract_domain
    if not isinstance(domain, str) or not domain:
        raise ValueError(
            f"exact wire-schema identity domain is unavailable for {schema_kind}"
        )
    return domain


def wire_schema_identity(
    language_bundle: dict[str, Any],
    schema_kind: str,
) -> str:
    """Identify one exact Wire Schema under its owning authority's domain."""
    definition = _wire_schema_definition(language_bundle, schema_kind)
    schema = cast(dict[str, Any], definition["schema"])
    body = {key: value for key, value in schema.items() if key != "$id"}
    return content_identity(
        wire_schema_identity_domain(language_bundle, schema_kind),
        cast(JsonValue, body),
    )


def artifact_wire_schema_identity(
    language_bundle: dict[str, Any],
    artifact_kind: str,
) -> str:
    """Identify an artifact's schema through its exact Artifact Contract."""
    contract_schema_kind = _artifact_contract_schema_kind(
        language_bundle,
        artifact_kind,
    )
    resolved_schema_kind = wire_schema_kind_for_kind(language_bundle, artifact_kind)
    if resolved_schema_kind != contract_schema_kind:
        raise ValueError(f"artifact schema kind is inconsistent: {artifact_kind}")
    return wire_schema_identity(
        language_bundle,
        resolved_schema_kind,
    )


def _artifact_contract_schema_kind(
    language_bundle: dict[str, Any],
    artifact_kind: str,
) -> str:
    language = cast(dict[str, Any], language_bundle["language"])
    contracts = [
        item
        for item in cast(list[dict[str, Any]], language["artifact_contracts"])
        if item.get("artifact_kind") == artifact_kind
    ]
    if len(contracts) != 1:
        raise ValueError(f"artifact contract is not unique: {artifact_kind}")
    schema_kind = contracts[0].get("schema_kind")
    if not isinstance(schema_kind, str) or not schema_kind:
        raise ValueError(f"artifact schema kind is unavailable for {artifact_kind}")
    return schema_kind


def wire_schema_kind_for_kind(
    language_bundle: dict[str, Any],
    kind: str,
) -> str:
    """Resolve an artifact kind to its schema kind, or retain a standalone kind."""
    language = cast(dict[str, Any], language_bundle["language"])
    contracts = [
        item
        for item in cast(list[dict[str, Any]], language["artifact_contracts"])
        if item.get("artifact_kind") == kind
    ]
    standalone_definitions = [
        item
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for item in cast(list[dict[str, Any]], language[collection])
        if item.get("artifact_kind") == kind and "wire_schema_identity_domain" in item
    ]
    if contracts and standalone_definitions:
        raise ValueError(f"wire-schema kind authority is ambiguous: {kind}")
    if len(contracts) > 1:
        raise ValueError(f"artifact contract is not unique: {kind}")
    if contracts:
        return _artifact_contract_schema_kind(language_bundle, kind)
    return kind


def wire_schema_for_kind(
    language_bundle: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    """Resolve one artifact or standalone kind to its exact admitted Wire Schema."""
    schema_kind = wire_schema_kind_for_kind(language_bundle, kind)
    definition = _wire_schema_definition(language_bundle, schema_kind)
    schema = definition.get("schema")
    if not isinstance(schema, dict):
        raise ValueError(f"wire schema body is unavailable for {schema_kind}")
    return schema


def wire_schema_identity_for_kind(
    language_bundle: dict[str, Any],
    kind: str,
) -> str:
    """Identify an artifact kind or a standalone non-artifact schema kind."""
    return wire_schema_identity(
        language_bundle,
        wire_schema_kind_for_kind(language_bundle, kind),
    )
