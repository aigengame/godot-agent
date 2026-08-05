"""Standard Schema artifact identity and schema admission."""

from copy import deepcopy
from typing import Any, cast

import jsonschema

from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.wire_schema import wire_schema_identity_for_kind


def _language(language_bundle: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], language_bundle["language"])


def _artifact_contract(
    language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    matches = [
        item
        for item in cast(
            list[dict[str, Any]], _language(language_bundle)["artifact_contracts"]
        )
        if item["artifact_kind"] == artifact_kind
    ]
    if len(matches) != 1:
        raise ValueError(f"artifact contract is not unique: {artifact_kind}")
    return matches[0]


def _artifact_schema(
    language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    contract = _artifact_contract(language_bundle, artifact_kind)
    matches = [
        item["schema"]
        for item in cast(
            list[dict[str, Any]], _language(language_bundle)["artifact_wire_schemas"]
        )
        if item["artifact_kind"] == contract["schema_kind"]
    ]
    if len(matches) != 1:
        raise ValueError(f"artifact wire schema is not unique: {artifact_kind}")
    return cast(dict[str, Any], matches[0])


def _wire_schema_identity_for_kind(
    language_bundle: dict[str, Any], artifact_kind: str
) -> str:
    return wire_schema_identity_for_kind(language_bundle, artifact_kind)


def _identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    contract = _artifact_contract(language_bundle, artifact_kind)
    body = cast(
        dict[str, JsonValue],
        {
            "artifact_kind": artifact_kind,
            "artifact_version": "2.0.0",
            "wire_schema_identity": _wire_schema_identity_for_kind(
                language_bundle, artifact_kind
            ),
            **payload,
        },
    )
    excluded = set(cast(list[str], contract["identity_excluded_members"]))
    identity_body = {key: value for key, value in body.items() if key not in excluded}
    artifact = {
        **body,
        "content_identity": content_identity(
            cast(str, contract["identity_domain"]), cast(JsonValue, identity_body)
        ),
    }
    jsonschema.Draft202012Validator(
        _artifact_schema(language_bundle, artifact_kind)
    ).validate(artifact)
    return artifact


def _verify_artifact(value: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    artifact_kind = value.get("artifact_kind")
    if not isinstance(artifact_kind, str):
        return False
    try:
        contract = _artifact_contract(language_bundle, artifact_kind)
        schema = _artifact_schema(language_bundle, artifact_kind)
        jsonschema.Draft202012Validator(schema).validate(value)
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError):
        return False
    if value.get("wire_schema_identity") != _wire_schema_identity_for_kind(
        language_bundle, artifact_kind
    ):
        return False
    excluded = set(cast(list[str], contract["identity_excluded_members"]))
    body = {
        key: item
        for key, item in value.items()
        if key != "content_identity" and key not in excluded
    }
    return value.get("content_identity") == content_identity(
        cast(str, contract["identity_domain"]), cast(JsonValue, body)
    )


def identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Construct and schema-admit one LDB-owned content-addressed artifact."""
    return _identified_artifact(language_bundle, artifact_kind, payload)


def verify_artifact(value: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    """Re-admit one content-addressed artifact against the exact LDB."""
    return _verify_artifact(value, language_bundle)


def wire_schema_identity(language_bundle: dict[str, Any], artifact_kind: str) -> str:
    """Derive one artifact's wire-schema identity from the exact LDB."""
    return _wire_schema_identity_for_kind(language_bundle, artifact_kind)


def artifact_wire_schema(
    language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, object]:
    """Return an isolated copy of one exact LDB-owned artifact schema."""
    return cast(
        dict[str, object], deepcopy(_artifact_schema(language_bundle, artifact_kind))
    )
