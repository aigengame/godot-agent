"""Standard Schema artifact identity and schema admission."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.wire_schema import (
    wire_schema_identity_for_kind,
    wire_schema_definition_for_role,
    _wire_schema_definition,
)


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


def artifact_contract_for_role(
    language_bundle: dict[str, Any], protocol_role: str
) -> dict[str, Any]:
    schema_kind = wire_schema_definition_for_role(language_bundle, protocol_role)[
        "artifact_kind"
    ]
    matches = [
        row
        for row in _language(language_bundle)["artifact_contracts"]
        if row["schema_kind"] == schema_kind
    ]
    if len(matches) != 1:
        raise ValueError(f"artifact protocol role is not unique: {protocol_role}")
    return matches[0]


def select_protocol_artifact_contract(
    language_bundle: dict[str, Any], protocol_role: str
) -> "ArtifactContract":
    return select_artifact_contract(
        language_bundle,
        artifact_contract_for_role(language_bundle, protocol_role)["artifact_kind"],
    )


def artifact_protocol_role(language_bundle: dict[str, Any], artifact_kind: str) -> str:
    """Read a core artifact's role from its admitted Wire Schema Definition."""
    contract = _artifact_contract(language_bundle, artifact_kind)
    role = _wire_schema_definition(language_bundle, contract["schema_kind"]).get(
        "protocol_role"
    )
    if not isinstance(role, str):
        raise ValueError(f"artifact has no core protocol role: {artifact_kind}")
    return role


def artifacts_by_protocol_role(
    language_bundle: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Index core semantic members independently of publication labels."""
    result = {}
    for value in artifacts.values():
        role = artifact_protocol_role(language_bundle, value["artifact_kind"])
        if role in result:
            raise ValueError(f"duplicate artifact protocol role: {role}")
        result[role] = value
    return result


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


@dataclass(frozen=True)
class ArtifactContract:
    """One selected artifact's immutable encoding and admission contract.

    Selection requires an admitted authority input. The snapshot contains only
    this kind's contract and complete schema; it is not an authority admission
    mechanism and cannot make an untrusted schema authoritative.
    """

    definition: dict[str, Any]
    schema: dict[str, Any]
    wire_schema_identity: str

    def __post_init__(self) -> None:
        from gda_balancing.domain.authority.context import _deep_freeze

        object.__setattr__(self, "definition", _deep_freeze(self.definition))
        object.__setattr__(self, "schema", _deep_freeze(self.schema))

    def identify(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Construct and admit an artifact without consulting a language catalog."""
        body = cast(
            dict[str, JsonValue],
            {
                "artifact_kind": self.definition["artifact_kind"],
                "artifact_version": "2.0.0",
                "wire_schema_identity": self.wire_schema_identity,
                **payload,
            },
        )
        excluded = set(cast(list[str], self.definition["identity_excluded_members"]))
        identity_body = {
            key: value for key, value in body.items() if key not in excluded
        }
        artifact = {
            **body,
            "content_identity": content_identity(
                cast(str, self.definition["identity_domain"]),
                cast(JsonValue, identity_body),
            ),
        }
        jsonschema.Draft202012Validator(self.schema).validate(artifact)
        return artifact

    def verify(self, value: dict[str, Any]) -> bool:
        """Check exact bytes and their interpretation under this selected kind."""
        if value.get("artifact_kind") != self.definition["artifact_kind"]:
            return False
        try:
            jsonschema.Draft202012Validator(self.schema).validate(value)
        except (KeyError, TypeError, ValueError, jsonschema.ValidationError):
            return False
        if value.get("wire_schema_identity") != self.wire_schema_identity:
            return False
        excluded = set(cast(list[str], self.definition["identity_excluded_members"]))
        body = {
            key: item
            for key, item in value.items()
            if key != "content_identity" and key not in excluded
        }
        return value.get("content_identity") == content_identity(
            cast(str, self.definition["identity_domain"]), cast(JsonValue, body)
        )


def select_artifact_contract(
    language_bundle: dict[str, Any], artifact_kind: str
) -> ArtifactContract:
    """Detach one complete contract from an admitted language authority."""
    return ArtifactContract(
        definition=_artifact_contract(language_bundle, artifact_kind),
        schema=_artifact_schema(language_bundle, artifact_kind),
        wire_schema_identity=_wire_schema_identity_for_kind(
            language_bundle, artifact_kind
        ),
    )


def _identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return select_protocol_artifact_contract(language_bundle, artifact_kind).identify(
        payload
    )


def _verify_artifact(value: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    artifact_kind = value.get("artifact_kind")
    if not isinstance(artifact_kind, str):
        return False
    try:
        contract = select_artifact_contract(language_bundle, artifact_kind)
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError):
        return False
    return contract.verify(value)


def identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Construct and schema-admit one LDB-owned content-addressed artifact."""
    return select_artifact_contract(language_bundle, artifact_kind).identify(payload)


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
