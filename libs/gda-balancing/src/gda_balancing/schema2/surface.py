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
    "uniqueItems",
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


def schema2_error_envelope_schema(descriptor: CommandDescriptor) -> dict[str, Any]:
    """Return the descriptor's exact closed 2.x Error contract."""
    artifact_location = {
        "type": "object",
        "properties": {
            "kind": {"const": "artifact"},
            "content_identity": {"type": "string"},
            "pointer": {"type": "string", "pattern": "^/"},
        },
        "required": ["kind", "content_identity", "pointer"],
        "unevaluatedProperties": False,
    }
    runtime_location = {
        "type": "object",
        "properties": {
            "kind": {"const": "runtime"},
            "subject": {
                "enum": [
                    "run",
                    "initialization-frame",
                    "formula-evaluation-site",
                    "event",
                    "snapshot-boundary",
                ]
            },
            "identity": {"type": "string"},
        },
        "required": ["kind", "subject", "identity"],
        "unevaluatedProperties": False,
    }
    location = {"oneOf": [artifact_location, runtime_location]}
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
    legacy_variants = deepcopy(ERROR_ENVELOPE_SCHEMA["properties"]["error"]["oneOf"])
    usage = legacy_variants[1]
    usage["properties"]["code"] = {"enum": sorted(descriptor.usage_codes)}
    variants: list[dict[str, Any]] = []
    for stage in descriptor.refusal_stages:
        codes = sorted(
            code
            for code, declared_stage in descriptor.refusal_catalog
            if declared_stage == stage
        )
        stage_diagnostic = deepcopy(diagnostic)
        stage_diagnostic["properties"]["code"] = {"enum": codes}
        declared_variants = [
            variant for variant in descriptor.refusal_variants if variant.stage == stage
        ]
        for declared_variant in declared_variants or [None]:
            forbidden = (
                set(declared_variant.forbidden_details)
                if declared_variant is not None
                else set()
            )
            details = {
                detail.field_name: deepcopy(detail.schema())
                for detail in descriptor.refusal_details
                if detail.stage == stage and detail.field_name not in forbidden
            }
            required_details = {
                detail.field_name
                for detail in descriptor.refusal_details
                if detail.stage == stage and detail.required
            }
            if declared_variant is not None:
                required_details.update(declared_variant.required_details)
            variants.append(
                {
                    "type": "object",
                    "properties": {
                        "category": {"const": "refusal"},
                        "stage": {"const": stage},
                        "diagnostics": {
                            "type": "array",
                            "minItems": 1,
                            "items": stage_diagnostic,
                        },
                        "truncated": {"type": "boolean"},
                        **details,
                    },
                    "required": [
                        "category",
                        "stage",
                        "diagnostics",
                        "truncated",
                        *sorted(required_details),
                    ],
                    "unevaluatedProperties": False,
                }
            )
    if descriptor.usage_codes:
        variants.append(usage)
    internal_properties: dict[str, Any] = {
        "category": {"const": "internal"},
        "code": {"const": "internal_error"},
        "message": {"type": "string"},
        "debug": {"type": "string"},
    }
    if descriptor.stochastic:
        internal_properties["reproduction"] = {
            "type": "object",
            "properties": {
                "seed": {
                    "type": "integer",
                    "minimum": 0,
                    "exclusiveMaximum": 2**32,
                },
                "toolkit_version": {"type": "string"},
            },
            "required": ["seed", "toolkit_version"],
            "unevaluatedProperties": False,
        }
    variants.append(
        {
            "type": "object",
            "properties": internal_properties,
            "required": ["category", "code", "message"],
            "unevaluatedProperties": False,
        }
    )
    return _close_schema_objects(
        {
            "$schema": _DRAFT_2020_12,
            "type": "object",
            "properties": {"error": {"oneOf": variants}},
            "required": ["error"],
            "unevaluatedProperties": False,
        }
    )


def _close_schema_objects(value: Any) -> Any:
    """Apply object closure only at JSON Schema positions.

    Literal data carried by ``const``, ``enum``, or ``default`` may itself
    contain mappings that look like schemas.  Those values are data and must
    remain byte-for-byte exact.
    """
    if not isinstance(value, dict):
        return deepcopy(value)
    closed = deepcopy(value)
    for keyword in ("$defs", "properties"):
        children = value.get(keyword)
        if isinstance(children, dict):
            closed[keyword] = {
                name: _close_schema_objects(schema) for name, schema in children.items()
            }
    for keyword in ("anyOf", "oneOf"):
        children = value.get(keyword)
        if isinstance(children, list):
            closed[keyword] = [_close_schema_objects(schema) for schema in children]
    if isinstance(value.get("items"), dict):
        closed["items"] = _close_schema_objects(value["items"])
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


def _artifact_membership(descriptor: CommandDescriptor) -> dict[str, JsonValue]:
    """Project the descriptor-owned artifact behavior and complete member set."""

    def members(
        artifact_set: tuple[Any, ...],
    ) -> list[dict[str, JsonValue]]:
        return [
            {
                "logical_name": member.logical_name,
                "artifact_kind": member.artifact_kind,
                "role": member.role,
            }
            for member in artifact_set
        ]

    return cast(
        dict[str, JsonValue],
        {
            "artifact_behavior": (
                "atomic-artifact-set"
                if (
                    descriptor.artifact_sink
                    or descriptor.artifact_set
                    or descriptor.verdict_artifact_set
                )
                else "stdout-only"
            ),
            "artifact_set": members(descriptor.artifact_set),
            "verdict_artifact_set": members(descriptor.verdict_artifact_set),
            "refusal_artifact_sets": [
                {
                    "stage": item.stage,
                    **({"variant": item.variant} if item.variant is not None else {}),
                    "members": members(item.members),
                }
                for item in descriptor.refusal_artifact_sets
            ],
        },
    )


def _descriptor_body(descriptor: CommandDescriptor) -> dict[str, JsonValue]:
    profile = command_schema_profile()
    success_schema = (
        descriptor.success_schema()
        if descriptor.success_schema is not None
        else descriptor.output_model.model_json_schema()
    )
    verdict_schema = (
        descriptor.verdict_schema()
        if descriptor.verdict_schema is not None
        else (
            descriptor.verdict_model.model_json_schema()
            if descriptor.verdict_model is not None
            else None
        )
    )
    refusal_details: list[JsonValue] = [
        {
            "stage": detail.stage,
            "field_name": detail.field_name,
            "required": detail.required,
            "schema": _schema_document(
                (
                    f"{descriptor.group or 'meta'}.{descriptor.command}.error."
                    f"{detail.stage}.{detail.field_name}"
                ),
                detail.schema(),
            ),
        }
        for detail in sorted(
            descriptor.refusal_details,
            key=lambda item: (item.stage, item.field_name),
        )
    ]
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
        **(
            {
                "verdict": _schema_document(
                    f"{descriptor.group or 'meta'}.{descriptor.command}.verdict",
                    cast(dict[str, Any], verdict_schema),
                )
            }
            if verdict_schema is not None
            else {}
        ),
        "execution": {
            "stochastic": descriptor.stochastic,
            "structured_params": descriptor.structured_params,
            "json_presentation_field": descriptor.json_presentation_field,
            "refusal_stages": list(descriptor.refusal_stages),
            "refusal_catalog": [
                {"code": code, "stage": stage}
                for code, stage in descriptor.refusal_catalog
            ],
            **(
                {
                    "refusal_variants": [
                        {
                            "id": variant.id,
                            "stage": variant.stage,
                            "required_details": list(variant.required_details),
                            "forbidden_details": list(variant.forbidden_details),
                        }
                        for variant in descriptor.refusal_variants
                    ]
                }
                if descriptor.refusal_variants
                else {}
            ),
            "usage_codes": list(descriptor.usage_codes),
        },
        **({"refusal_details": refusal_details} if refusal_details else {}),
        **_artifact_membership(descriptor),
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
        **({"verdict": body["verdict"]} if "verdict" in body else {}),
        "error": cast(JsonValue, schema2_error_envelope_schema(descriptor)),
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
            "verdict": schema_document,
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
            "refusal_catalog": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "stage": {"type": "string"},
                    },
                    "required": ["code", "stage"],
                    "unevaluatedProperties": False,
                },
            },
            "refusal_variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "stage": {"type": "string"},
                        "required_details": {
                            "type": "array",
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                        "forbidden_details": {
                            "type": "array",
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                    },
                    "required": [
                        "id",
                        "stage",
                        "required_details",
                        "forbidden_details",
                    ],
                    "unevaluatedProperties": False,
                },
            },
            "usage_codes": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "stochastic",
            "structured_params",
            "refusal_stages",
            "refusal_catalog",
            "refusal_variants",
            "usage_codes",
        ],
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
            "artifact_set": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "logical_name": {"type": "string", "minLength": 1},
                        "artifact_kind": {"type": "string", "minLength": 1},
                        "role": {"enum": ["primary", "companion"]},
                    },
                    "required": ["logical_name", "artifact_kind", "role"],
                    "unevaluatedProperties": False,
                },
            },
            "verdict_artifact_set": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "logical_name": {"type": "string", "minLength": 1},
                        "artifact_kind": {"type": "string", "minLength": 1},
                        "role": {"enum": ["primary", "companion"]},
                    },
                    "required": ["logical_name", "artifact_kind", "role"],
                    "unevaluatedProperties": False,
                },
            },
            "refusal_artifact_sets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stage": {"type": "string"},
                        "variant": {"type": "string", "minLength": 1},
                        "members": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "logical_name": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "artifact_kind": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "role": {"enum": ["primary", "companion"]},
                                },
                                "required": [
                                    "logical_name",
                                    "artifact_kind",
                                    "role",
                                ],
                                "unevaluatedProperties": False,
                            },
                        },
                    },
                    "required": ["stage", "members"],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": [
            "group",
            "command",
            "description",
            "descriptor_identity",
            "schema",
            "execution",
            "artifact_behavior",
            "artifact_set",
            "verdict_artifact_set",
            "refusal_artifact_sets",
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
                    "refusal_catalog": [
                        {"code": code, "stage": stage}
                        for code, stage in descriptor.refusal_catalog
                    ],
                    "refusal_variants": [
                        {
                            "id": variant.id,
                            "stage": variant.stage,
                            "required_details": list(variant.required_details),
                            "forbidden_details": list(variant.forbidden_details),
                        }
                        for variant in descriptor.refusal_variants
                    ],
                    "usage_codes": list(descriptor.usage_codes),
                },
                **_artifact_membership(descriptor),
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
