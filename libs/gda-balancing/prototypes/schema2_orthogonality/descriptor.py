"""Sole command-envelope, outcome, and artifact-membership authority."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from canonical import artifact, identity


BASE_MEMBERS = {
    "authoring-ast": {"min": 1, "max": 1},
    "build-receipt": {"min": 1, "max": 1},
    "capability-manifest": {"min": 1, "max": 1},
    "command-descriptor": {"min": 1, "max": 1},
    "debug-map": {"min": 1, "max": 1},
    "domain-package-release": {"min": 1, "max": 16},
    "generated-diagnostic-catalog": {"min": 1, "max": 1},
    "generated-operation-registry": {"min": 1, "max": 1},
    "generated-package-documentation": {"min": 1, "max": 1},
    "generated-runtime-programs": {"min": 1, "max": 1},
    "generated-structural-schema": {"min": 1, "max": 1},
    "generated-vector-catalog": {"min": 1, "max": 1},
    "kernel-specification": {"min": 1, "max": 1},
    "language-definition-bundle": {"min": 1, "max": 1},
    "model-source-package": {"min": 1, "max": 1},
    "package-lock": {"min": 1, "max": 1},
    "prototype-diagnostic-authority": {"min": 1, "max": 1},
    "resolution-receipt": {"min": 1, "max": 1},
    "resolved-model": {"min": 1, "max": 1},
    "surface-manifest": {"min": 1, "max": 1},
    "typed-hir": {"min": 1, "max": 1},
}


def _members(extra: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {**BASE_MEMBERS, **extra}


RUN_DESCRIPTOR = artifact(
    "command-descriptor",
    {
        "command": "probe run",
        "handler": "orthogonality.run.v2",
        "request_envelope": {
            "fields": {
                "command": {"type": "literal", "value": "probe run", "canonical": True},
                "invocation_key": {
                    "type": "string",
                    "pattern": "[0-9a-f]{64}",
                    "canonical": False,
                },
                "params": {"type": "params", "canonical": True},
                "store": {"type": "string", "canonical": False},
            },
            "required": ["command", "invocation_key", "params", "store"],
            "closed": True,
        },
        "parameters": {
            "extra_attribute": {"type": "bool", "default": False},
            "fault": {
                "type": "enum",
                "values": ["none", "before_commit"],
                "default": "none",
            },
            "max_event_writes": {"type": "int", "minimum": 0, "default": 32},
            "scenario": {
                "type": "enum",
                "values": [
                    "success",
                    "insufficient",
                    "interrupted",
                    "effect_lifecycle",
                ],
                "default": "success",
            },
        },
        "outcomes": {
            "completed": {
                "public_outcome": "completed",
                "exit": 0,
                "channel": "stdout",
                "handler_envelope": {
                    "outcome": {"type": "literal", "value": "completed"},
                    "semantic_authority_gate": {
                        "type": "literal",
                        "value": "unvalidated",
                    },
                    "normative_replay_or_evidence_issued": {"type": "bool"},
                },
                "public_envelope": {
                    "outcome": {"type": "literal", "value": "completed"},
                    "semantic_authority_gate": {
                        "type": "literal",
                        "value": "unvalidated",
                    },
                    "normative_replay_or_evidence_issued": {"type": "bool"},
                    "artifact_set": {
                        "type": "literal",
                        "value": "evaluation-artifact-set",
                    },
                    "publication_receipt": {
                        "type": "identity",
                        "domain": "publication-receipt",
                    },
                    "idempotent_replay": {"type": "bool"},
                },
                "artifact_set": {
                    "kind": "evaluation-artifact-set",
                    "members": _members(
                        {
                            "evaluation-run": {"min": 1, "max": 1},
                            "experiment-final-binding-receipt": {"min": 1, "max": 1},
                            "experiment-specification": {"min": 1, "max": 1},
                            "metric-dataset": {"min": 1, "max": 1},
                            "resolved-runtime-profile": {"min": 1, "max": 1},
                            "runtime-run": {"min": 1, "max": 1},
                            "runtime-snapshot": {"min": 1, "max": 33},
                        }
                    ),
                    "forbidden_kinds": ["evidence", "replay", "terminal-audit"],
                    "identity_relations": [
                        {
                            "source_kind": "package-lock",
                            "source_list": "selected",
                            "identity_field": "release_identity",
                            "member_kind": "domain-package-release",
                        }
                    ],
                },
            },
            "runtime_refused": {
                "public_outcome": "refused",
                "exit": 2,
                "channel": "stdout",
                "handler_envelope": {
                    "outcome": {"type": "literal", "value": "refused"},
                    "phase": {"type": "literal", "value": "post-dispatch"},
                    "diagnostic": {"type": "runtime-diagnostic"},
                    "terminal_audit": {"type": "identity", "domain": "terminal-audit"},
                },
                "public_envelope": {
                    "outcome": {"type": "literal", "value": "refused"},
                    "phase": {"type": "literal", "value": "post-dispatch"},
                    "diagnostic": {"type": "runtime-diagnostic"},
                    "terminal_audit": {"type": "identity", "domain": "terminal-audit"},
                    "artifact_set": {
                        "type": "literal",
                        "value": "terminal-audit-artifact-set",
                    },
                    "publication_receipt": {
                        "type": "identity",
                        "domain": "publication-receipt",
                    },
                    "idempotent_replay": {"type": "bool"},
                },
                "artifact_set": {
                    "kind": "terminal-audit-artifact-set",
                    "members": _members(
                        {
                            "experiment-final-binding-receipt": {"min": 1, "max": 1},
                            "experiment-specification": {"min": 1, "max": 1},
                            "resolved-runtime-profile": {"min": 1, "max": 1},
                            "runtime-snapshot": {"min": 1, "max": 33},
                            "terminal-audit": {"min": 1, "max": 1},
                        }
                    ),
                    "forbidden_kinds": [
                        "evaluation-run",
                        "evidence",
                        "metric-dataset",
                        "replay",
                        "runtime-run",
                    ],
                    "identity_relations": [
                        {
                            "source_kind": "package-lock",
                            "source_list": "selected",
                            "identity_field": "release_identity",
                            "member_kind": "domain-package-release",
                        }
                    ],
                },
            },
            "predispatch_refused": {
                "public_outcome": "refused",
                "exit": 2,
                "channel": "stdout",
                "handler_envelope": {
                    "outcome": {"type": "literal", "value": "refused"},
                    "phase": {"type": "literal", "value": "pre-dispatch"},
                    "diagnostic": {"type": "stage-diagnostic"},
                    "terminal_audit": {"type": "null"},
                },
                "public_envelope": {
                    "outcome": {"type": "literal", "value": "refused"},
                    "phase": {"type": "literal", "value": "pre-dispatch"},
                    "diagnostic": {"type": "stage-diagnostic"},
                    "terminal_audit": {"type": "null"},
                },
                "artifact_set": None,
            },
            "usage_error": {
                "public_outcome": "usage_error",
                "exit": 3,
                "channel": "stderr",
                "handler_envelope": {
                    "outcome": {"type": "literal", "value": "usage_error"},
                    "code": {"type": "string"},
                    "field": {"type": "string"},
                },
                "public_envelope": {
                    "outcome": {"type": "literal", "value": "usage_error"},
                    "code": {"type": "string"},
                    "field": {"type": "string"},
                },
                "artifact_set": None,
            },
            "internal_error": {
                "public_outcome": "internal_error",
                "exit": 4,
                "channel": "stderr",
                "handler_envelope": {
                    "outcome": {"type": "literal", "value": "internal_error"},
                    "code": {"type": "string"},
                },
                "public_envelope": {
                    "outcome": {"type": "literal", "value": "internal_error"},
                    "code": {"type": "string"},
                },
                "artifact_set": None,
            },
        },
    },
)

SURFACE_MANIFEST = artifact(
    "surface-manifest",
    {
        "schema_profile": "probe-json-schema-2020-12-closed-v2",
        "commands": [RUN_DESCRIPTOR],
    },
)


class BindingError(Exception):
    def __init__(self, code: str, field: str) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


class DescriptorViolation(Exception):
    pass


def bind(request: Any, descriptor: dict[str, Any] = RUN_DESCRIPTOR) -> dict[str, Any]:
    envelope = descriptor["request_envelope"]
    if not isinstance(request, dict):
        raise BindingError("invocation.not-object", "$")
    fields = envelope["fields"]
    if envelope["closed"]:
        unknown = sorted(set(request) - set(fields))
        if unknown:
            raise BindingError("invocation.field-unknown", unknown[0])
    missing = [name for name in envelope["required"] if name not in request]
    if missing:
        raise BindingError("invocation.field-missing", missing[0])
    for name, schema in fields.items():
        value = request.get(name)
        if schema["type"] == "literal" and value != schema["value"]:
            raise BindingError("invocation.command-unknown", name)
        if schema["type"] == "string":
            if not isinstance(value, str):
                raise BindingError("invocation.field-invalid", name)
            if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
                raise BindingError("invocation.key-invalid", name)
    supplied = request["params"]
    if not isinstance(supplied, dict):
        raise BindingError("invocation.params-invalid", "params")
    parameter_schemas = descriptor["parameters"]
    unknown_params = sorted(set(supplied) - set(parameter_schemas))
    if unknown_params:
        raise BindingError("invocation.parameter-unknown", unknown_params[0])
    params: dict[str, Any] = {}
    for name, schema in parameter_schemas.items():
        value = supplied.get(name, schema["default"])
        if schema["type"] == "bool" and type(value) is not bool:
            raise BindingError("invocation.parameter-invalid", name)
        if schema["type"] == "int" and (
            type(value) is not int or value < schema.get("minimum", value)
        ):
            raise BindingError("invocation.parameter-invalid", name)
        if schema["type"] == "enum" and value not in schema["values"]:
            raise BindingError("invocation.parameter-invalid", name)
        params[name] = value
    canonical_fields: dict[str, Any] = {}
    for name, schema in fields.items():
        if schema["canonical"]:
            canonical_fields[name] = (
                params if schema["type"] == "params" else request[name]
            )
    return {
        "descriptor": descriptor,
        "descriptor_identity": descriptor["identity"],
        "invocation_key": request["invocation_key"],
        "canonical_input_identity": identity(
            "command-input",
            {"descriptor": descriptor["identity"], **canonical_fields},
        ),
        "params": params,
        "store": request["store"],
    }


def reverse_conform_handlers(
    handlers: dict[str, Any], descriptor: dict[str, Any] = RUN_DESCRIPTOR
) -> None:
    expected = {descriptor["handler"]}
    if set(handlers) != expected:
        raise DescriptorViolation("descriptor.handler-inventory-mismatch")


def _validate_envelope_field(value: Any, schema: dict[str, Any], field: str) -> None:
    field_type = schema["type"]
    if field_type == "literal" and value != schema["value"]:
        raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
    if field_type == "string" and not isinstance(value, str):
        raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
    if field_type == "bool" and type(value) is not bool:
        raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
    if field_type == "null" and value is not None:
        raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
    if field_type == "identity" and (
        not isinstance(value, str)
        or re.fullmatch(f"sha256:{schema['domain']}:[0-9a-f]{{64}}", value) is None
    ):
        raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
    if field_type == "stage-diagnostic":
        if not isinstance(value, dict) or set(value) != {"stage", "code", "location"}:
            raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
        if not all(isinstance(item, str) for item in value.values()):
            raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
    if field_type == "runtime-diagnostic":
        if not isinstance(value, dict) or set(value) != {
            "code",
            "message",
            "primary_location",
            "related_locations",
        }:
            raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
        location = value.get("primary_location")
        related = value.get("related_locations")
        if (
            not isinstance(value.get("code"), str)
            or not isinstance(value.get("message"), str)
            or not isinstance(location, dict)
            or set(location) != {"kind", "sequence", "use_site", "path"}
            or location.get("kind") != "runtime-event"
            or type(location.get("sequence")) is not int
            or location["sequence"] < 1
            or not isinstance(location.get("use_site"), str)
            or not isinstance(location.get("path"), str)
            or not isinstance(related, list)
        ):
            raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")
        for related_location in related:
            if (
                not isinstance(related_location, dict)
                or set(related_location) != {"kind", "sequence", "use_site", "path"}
                or related_location.get("kind") != "runtime-event"
                or type(related_location.get("sequence")) is not int
                or related_location["sequence"] < 1
                or not isinstance(related_location.get("use_site"), str)
                or not isinstance(related_location.get("path"), str)
            ):
                raise DescriptorViolation(f"descriptor.envelope-field-invalid:{field}")


def validate_envelope(
    outcome_name: str,
    envelope: Any,
    surface: str,
    descriptor: dict[str, Any] = RUN_DESCRIPTOR,
) -> None:
    outcome = descriptor["outcomes"].get(outcome_name)
    if outcome is None or surface not in {"handler", "public"}:
        raise DescriptorViolation("descriptor.envelope-model-unknown")
    model = outcome[f"{surface}_envelope"]
    if not isinstance(envelope, dict) or set(envelope) != set(model):
        raise DescriptorViolation("descriptor.envelope-shape-invalid")
    for field, schema in model.items():
        _validate_envelope_field(envelope[field], schema, field)


def validate_public_envelope(
    outcome_name: str,
    envelope: Any,
    descriptor: dict[str, Any] = RUN_DESCRIPTOR,
) -> None:
    validate_envelope(outcome_name, envelope, "public", descriptor)


def validate_artifact_set(
    outcome_name: str,
    members: list[dict[str, Any]],
    descriptor: dict[str, Any] = RUN_DESCRIPTOR,
) -> str:
    outcome = descriptor["outcomes"].get(outcome_name)
    if outcome is None or outcome["artifact_set"] is None:
        raise DescriptorViolation("descriptor.artifact-set-unreachable")
    contract = outcome["artifact_set"]
    counts = Counter(member.get("kind") for member in members)
    if any(kind in counts for kind in contract["forbidden_kinds"]):
        raise DescriptorViolation("descriptor.artifact-kind-forbidden")
    if set(counts) - set(contract["members"]):
        raise DescriptorViolation("descriptor.artifact-kind-extra")
    for kind, multiplicity in contract["members"].items():
        if not multiplicity["min"] <= counts.get(kind, 0) <= multiplicity["max"]:
            raise DescriptorViolation(f"descriptor.artifact-multiplicity:{kind}")
    for relation in contract["identity_relations"]:
        sources = [
            member
            for member in members
            if member.get("kind") == relation["source_kind"]
        ]
        if len(sources) != 1:
            raise DescriptorViolation("descriptor.artifact-relation-source-invalid")
        expected_identities = {
            item[relation["identity_field"]]
            for item in sources[0][relation["source_list"]]
        }
        actual_identities = {
            member["identity"]
            for member in members
            if member.get("kind") == relation["member_kind"]
        }
        if actual_identities != expected_identities:
            raise DescriptorViolation("descriptor.artifact-relation-mismatch")
    return contract["kind"]


def outcome_transport(
    outcome_name: str, descriptor: dict[str, Any] = RUN_DESCRIPTOR
) -> tuple[int, str]:
    outcome = descriptor["outcomes"].get(outcome_name)
    if outcome is None:
        raise DescriptorViolation("descriptor.outcome-unknown")
    return outcome["exit"], outcome["channel"]


def validate_handler_result(
    result: Any, descriptor: dict[str, Any] = RUN_DESCRIPTOR
) -> None:
    if not isinstance(result, dict) or set(result) != {
        "outcome_name",
        "envelope",
        "members",
    }:
        raise DescriptorViolation("descriptor.handler-result-shape-invalid")
    outcome = descriptor["outcomes"].get(result["outcome_name"])
    if outcome is None:
        raise DescriptorViolation("descriptor.handler-outcome-unknown")
    validate_envelope(result["outcome_name"], result["envelope"], "handler", descriptor)
    if not isinstance(result["members"], list):
        raise DescriptorViolation("descriptor.handler-members-invalid")
    if outcome["artifact_set"] is None:
        if result["members"]:
            raise DescriptorViolation("descriptor.handler-unexpected-artifacts")
    else:
        validate_artifact_set(result["outcome_name"], result["members"], descriptor)
