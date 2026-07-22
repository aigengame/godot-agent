"""Descriptor-derived Schema 2.0 command schemas and Surface manifest."""

from typing import Any, cast

from gda_balancing.descriptors import CommandDescriptor
from copy import deepcopy

from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA
from gda_balancing.schema2.canonical import JsonValue, content_identity

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_ADMITTED_KEYWORDS = (
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "anyOf",
    "const",
    "default",
    "description",
    "enum",
    "exclusiveMaximum",
    "items",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "oneOf",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "unevaluatedProperties",
)

_PROFILE_BODY: dict[str, JsonValue] = {
    "artifact_kind": "command-schema-profile",
    "artifact_version": "2.0.0",
    "json_schema_dialect": _DRAFT_2020_12,
    "object_closure_keyword": "unevaluatedProperties",
    "object_closure_value": False,
    "reference_policy": "local-defs-and-exact-content-only",
    "remote_resolution": "forbidden",
    "defaults": "descriptor-owned-binding; JSON-Schema-default-is-annotation",
    "admitted_keywords": list(_ADMITTED_KEYWORDS),
    "admitted_formats": [],
}


def command_schema_profile() -> dict[str, JsonValue]:
    """Return the immutable cross-command JSON Schema profile."""
    return {
        **_PROFILE_BODY,
        "content_identity": content_identity(
            "command-schema-profile-v2", cast(JsonValue, _PROFILE_BODY)
        ),
    }


def schema2_error_envelope_schema() -> dict[str, Any]:
    """Return the shared closed 2.x usage/internal/refusal Error contract."""
    location = {
        "type": "object",
        "properties": {
            "kind": {"const": "artifact"},
            "content_identity": {"type": "string"},
            "pointer": {"type": "string", "pattern": "^/"},
        },
        "required": ["kind", "content_identity", "pointer"],
        "unevaluatedProperties": False,
    }
    diagnostic = {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "primary": location,
            "related": {"type": "array", "items": location},
        },
        "required": ["code", "message", "primary", "related"],
        "unevaluatedProperties": False,
    }
    refusal = {
        "type": "object",
        "properties": {
            "category": {"const": "refusal"},
            "stage": {
                "enum": [
                    "ingress",
                    "parse",
                    "static",
                    "resolution",
                    "runtime",
                    "evaluation",
                    "migration",
                    "approval",
                ]
            },
            "diagnostics": {
                "type": "array",
                "minItems": 1,
                "items": diagnostic,
            },
            "truncated": {"type": "boolean"},
        },
        "required": ["category", "stage", "diagnostics", "truncated"],
        "unevaluatedProperties": False,
    }
    legacy_variants = deepcopy(ERROR_ENVELOPE_SCHEMA["properties"]["error"]["oneOf"])
    return _close_schema_objects(
        {
            "$schema": _DRAFT_2020_12,
            "type": "object",
            "properties": {"error": {"oneOf": [refusal, *legacy_variants[1:]]}},
            "required": ["error"],
            "unevaluatedProperties": False,
        }
    )


def _close_schema_objects(value: Any) -> Any:
    """Apply the profile's one object-closure form recursively."""
    if isinstance(value, list):
        return [_close_schema_objects(item) for item in value]
    if not isinstance(value, dict):
        return value
    closed = {key: _close_schema_objects(item) for key, item in value.items()}
    if closed.get("type") == "object":
        additional = closed.pop("additionalProperties", None)
        if additional not in (None, False):
            raise ValueError("open object schema is outside the Command schema profile")
        closed["unevaluatedProperties"] = False
    return closed


def _schema_document(name: str, raw: dict[str, Any]) -> dict[str, JsonValue]:
    body = cast(dict[str, JsonValue], _close_schema_objects(raw))
    body["$schema"] = _DRAFT_2020_12
    digest = content_identity(f"command-wire-schema:{name}", cast(JsonValue, body))
    return {
        "$id": f"urn:gda-balancing:command-schema:{digest.removeprefix('sha256:')}",
        **body,
    }


def _descriptor_body(descriptor: CommandDescriptor) -> dict[str, JsonValue]:
    profile = command_schema_profile()
    success_schema = (
        descriptor.success_schema()
        if descriptor.success_schema is not None
        else descriptor.output_model.model_json_schema()
    )
    return {
        "group": descriptor.group,
        "command": descriptor.command,
        "description": descriptor.description,
        "schema_major": descriptor.schema_major,
        "profile_identity": cast(str, profile["content_identity"]),
        "input": _schema_document(
            f"{descriptor.group or 'meta'}.{descriptor.command}.input",
            descriptor.input_model.model_json_schema(),
        ),
        "success": _schema_document(
            f"{descriptor.group or 'meta'}.{descriptor.command}.success",
            success_schema,
        ),
        "execution": {
            "stochastic": descriptor.stochastic,
            "structured_params": descriptor.structured_params,
            "refusal_stages": list(descriptor.refusal_stages),
        },
        "artifact_behavior": "atomic-artifact-set"
        if descriptor.artifact_sink
        else "stdout-only",
    }


def descriptor_identity(descriptor: CommandDescriptor) -> str:
    return content_identity(
        "command-descriptor-v2", cast(JsonValue, _descriptor_body(descriptor))
    )


def command_schema_projection(descriptor: CommandDescriptor) -> dict[str, JsonValue]:
    """Return the exact per-command schema object used by manifest and CLI."""
    body = _descriptor_body(descriptor)
    identity = descriptor_identity(descriptor)
    schema_body: dict[str, JsonValue] = {
        "artifact_kind": "command-schema",
        "profile_identity": cast(str, body["profile_identity"]),
        "descriptor_identity": identity,
        "input": body["input"],
        "success": body["success"],
        "error": cast(JsonValue, schema2_error_envelope_schema()),
    }
    return {
        **schema_body,
        "content_identity": content_identity(
            "command-schema-v2", cast(JsonValue, schema_body)
        ),
    }


def surface_manifest_success_schema() -> dict[str, object]:
    """Closed structural contract for the self-referential Surface manifest."""
    identity = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    schema_document = {
        "type": "object",
        "properties": {keyword: {} for keyword in _ADMITTED_KEYWORDS},
        "unevaluatedProperties": False,
    }
    command_schema = {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "command-schema"},
            "content_identity": identity,
            "descriptor_identity": identity,
            "profile_identity": identity,
            "input": schema_document,
            "success": schema_document,
            "error": schema_document,
        },
        "required": [
            "artifact_kind",
            "content_identity",
            "descriptor_identity",
            "profile_identity",
            "input",
            "success",
            "error",
        ],
        "unevaluatedProperties": False,
    }
    execution = {
        "type": "object",
        "properties": {
            "stochastic": {"type": "boolean"},
            "structured_params": {"type": "boolean"},
            "refusal_stages": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["stochastic", "structured_params", "refusal_stages"],
        "unevaluatedProperties": False,
    }
    row = {
        "type": "object",
        "properties": {
            "group": {"type": ["string", "null"]},
            "command": {"type": "string"},
            "description": {"type": "string"},
            "descriptor_identity": identity,
            "schema": command_schema,
            "execution": execution,
            "artifact_behavior": {"enum": ["stdout-only", "atomic-artifact-set"]},
        },
        "required": [
            "group",
            "command",
            "description",
            "descriptor_identity",
            "schema",
            "execution",
            "artifact_behavior",
        ],
        "unevaluatedProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "surface-manifest"},
            "surface_version": {"const": "2.0.0"},
            "command_schema_profile": {"const": command_schema_profile()},
            "commands": {"type": "array", "items": row},
            "content_identity": identity,
        },
        "required": [
            "artifact_kind",
            "surface_version",
            "command_schema_profile",
            "commands",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }


def surface_manifest(
    registry: tuple[CommandDescriptor, ...],
) -> dict[str, JsonValue]:
    """Enumerate the delivered 2.x subset from the live descriptor registry."""
    rows: list[JsonValue] = []
    for descriptor in registry:
        if descriptor.schema_major != 2:
            continue
        rows.append(
            {
                "group": descriptor.group,
                "command": descriptor.command,
                "description": descriptor.description,
                "descriptor_identity": descriptor_identity(descriptor),
                "schema": command_schema_projection(descriptor),
                "execution": {
                    "stochastic": descriptor.stochastic,
                    "structured_params": descriptor.structured_params,
                    "refusal_stages": list(descriptor.refusal_stages),
                },
                "artifact_behavior": (
                    "atomic-artifact-set" if descriptor.artifact_sink else "stdout-only"
                ),
            }
        )
    rows.sort(
        key=lambda raw: (
            cast(dict[str, JsonValue], raw)["group"] or "",
            cast(dict[str, JsonValue], raw)["command"],
        )
    )
    body: dict[str, JsonValue] = {
        "artifact_kind": "surface-manifest",
        "surface_version": "2.0.0",
        "command_schema_profile": command_schema_profile(),
        "commands": rows,
    }
    return {
        **body,
        "content_identity": content_identity(
            "surface-manifest-v2", cast(JsonValue, body)
        ),
    }
