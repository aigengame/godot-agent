"""Authority-owned Wire-Schema identity projections."""

from typing import Any, cast

from gda_balancing.schema2.canonical import JsonValue, content_identity


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
    artifact_kind: str,
) -> str:
    """Select the one admitted identity-domain authority for a Wire Schema."""
    language = cast(dict[str, Any], language_bundle["language"])
    definition = _wire_schema_definition(language_bundle, artifact_kind)
    inline_domain = definition.get("wire_schema_identity_domain")
    contracts = [
        item
        for item in cast(list[dict[str, Any]], language["artifact_contracts"])
        if item.get("artifact_kind") == artifact_kind
    ]
    if len(contracts) > 1:
        raise ValueError(f"artifact contract is not unique: {artifact_kind}")
    contract_domain = (
        contracts[0].get("wire_schema_identity_domain") if contracts else None
    )
    if inline_domain is None and contract_domain is None:
        raise ValueError(
            f"exact wire-schema identity domain is unavailable for {artifact_kind}"
        )
    if inline_domain is not None and contract_domain is not None:
        raise ValueError(
            f"wire-schema identity-domain authority is ambiguous for {artifact_kind}"
        )
    domain = inline_domain if inline_domain is not None else contract_domain
    if not isinstance(domain, str) or not domain:
        raise ValueError(
            f"exact wire-schema identity domain is unavailable for {artifact_kind}"
        )
    return domain


def wire_schema_identity(
    language_bundle: dict[str, Any],
    artifact_kind: str,
) -> str:
    """Identify one exact Wire Schema under its owning authority's domain."""
    definition = _wire_schema_definition(language_bundle, artifact_kind)
    schema = cast(dict[str, Any], definition["schema"])
    body = {key: value for key, value in schema.items() if key != "$id"}
    return content_identity(
        wire_schema_identity_domain(language_bundle, artifact_kind),
        cast(JsonValue, body),
    )
