"""The sole command input, routing, outcome, and artifact-set authority."""

from __future__ import annotations

import re
from typing import Any

from canonical import identity


def _outcomes(
    success_sets: list[str] | None, refusal_stages: dict[str, list[str]]
) -> dict[str, Any]:
    outcomes: dict[str, Any] = {
        "refusals": [
            {
                "outcome": "refused",
                "stage": stage,
                "exit": 2,
                "channel": "stdout",
                "artifact_set_kinds": set_kinds,
            }
            for stage, set_kinds in sorted(refusal_stages.items())
        ],
        "usage": {"outcome": "usage_error", "exit": 3, "channel": "stderr"},
        "internal": {"outcome": "internal_error", "exit": 4, "channel": "stderr"},
    }
    if success_sets is not None:
        outcomes["success"] = {
            "outcome": "completed",
            "exit": 0,
            "channel": "stdout",
            "artifact_set_kinds": success_sets,
        }
    return outcomes


def _command(name: str, content: dict[str, Any]) -> dict[str, Any]:
    descriptor = {"kind": "command-descriptor", "command": name, **content}
    descriptor["identity"] = identity("command-descriptor", descriptor)
    return descriptor


COMMANDS: dict[str, dict[str, Any]] = {
    "build": _command(
        "build",
        {
            "handler": "build.v1",
            "artifact_producing": True,
            "parameters": {
                "compiler": {"type": "enum", "values": ["a", "b"], "default": "a"},
                "source_variant": {
                    "type": "enum",
                    "values": ["a", "b"],
                    "default": "a",
                },
                "base_damage": {"type": "int", "minimum": 0, "default": 4},
                "bundle_fixture": {
                    "type": "enum",
                    "values": ["valid", "identity-mismatch", "malformed-rule"],
                    "default": "valid",
                },
                "fault": {
                    "type": "enum",
                    "values": ["none", "before_commit", "after_commit"],
                    "default": "none",
                },
            },
            "outcomes": _outcomes(
                ["build-artifact-set"], {"ingress": [], "static": []}
            ),
        },
    ),
    "run": _command(
        "run",
        {
            "handler": "run.v1",
            "artifact_producing": True,
            "parameters": {
                "compiler": {"type": "enum", "values": ["a", "b"], "default": "a"},
                "evaluator": {"type": "enum", "values": ["a", "b"], "default": "a"},
                "source_variant": {
                    "type": "enum",
                    "values": ["a", "b"],
                    "default": "a",
                },
                "scenario": {
                    "type": "enum",
                    "values": ["success", "insufficient"],
                    "default": "success",
                },
                "base_damage": {"type": "int", "minimum": 0, "default": 4},
                "max_steps": {"type": "int", "minimum": 0, "default": 512},
                "max_draws": {"type": "int", "minimum": 0, "default": 8},
                "fault": {
                    "type": "enum",
                    "values": ["none", "before_commit", "after_commit"],
                    "default": "none",
                },
            },
            "outcomes": _outcomes(
                ["evaluation-artifact-set"],
                {
                    "ingress": [],
                    "runtime": ["terminal-audit-artifact-set"],
                    "static": [],
                },
            ),
        },
    ),
    "compare": _command(
        "compare",
        {
            "handler": "compare.v1",
            "artifact_producing": False,
            "execution_marking": "gate-only-authority-conflict",
            "parameters": {},
            "outcomes": _outcomes(None, {"evaluation": []}),
        },
    ),
    "inspect": _command(
        "inspect",
        {
            "handler": "inspect.v1",
            "artifact_producing": False,
            "parameters": {
                "target_command": {
                    "type": "enum",
                    "values": ["build", "compare", "run"],
                }
            },
            "outcomes": _outcomes([], {"ingress": []}),
        },
    ),
}


COMMAND_DESCRIPTOR: dict[str, Any] = {
    "kind": "command-descriptor-registry",
    "profile": "schema2-probe-command-descriptor-v2",
    "commands": COMMANDS,
}
COMMAND_DESCRIPTOR["identity"] = identity(
    "command-descriptor-registry", COMMAND_DESCRIPTOR
)


class BindingRefusal(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def bind(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise BindingRefusal("invocation.request-not-object", "$")
    allowed_envelope = {"command", "invocation_key", "params", "store"}
    unknown_envelope = sorted(set(request) - allowed_envelope)
    if unknown_envelope:
        raise BindingRefusal("invocation.unknown-field", unknown_envelope[0])
    for required in ("command", "invocation_key", "store"):
        if not isinstance(request.get(required), str):
            raise BindingRefusal("invocation.field-invalid", required)
    invocation_key = request["invocation_key"]
    if re.fullmatch(r"[0-9a-f]{64}", invocation_key) is None:
        raise BindingRefusal("invocation.key-invalid", "invocation_key")
    command = request["command"]
    command_spec = COMMANDS.get(command)
    if command_spec is None:
        raise BindingRefusal("invocation.command-unknown", command)
    supplied = request.get("params", {})
    if not isinstance(supplied, dict):
        raise BindingRefusal("invocation.params-not-object", "params")
    schemas = command_spec["parameters"]
    unknown = sorted(set(supplied) - set(schemas))
    if unknown:
        raise BindingRefusal("invocation.parameter-unknown", unknown[0])
    parameters: dict[str, Any] = {}
    for name, schema in schemas.items():
        if name in supplied:
            value = supplied[name]
        elif "default" in schema:
            value = schema["default"]
        else:
            raise BindingRefusal("invocation.parameter-missing", name)
        if schema["type"] == "enum":
            if value not in schema["values"]:
                raise BindingRefusal("invocation.parameter-invalid", name)
        elif schema["type"] == "int":
            if type(value) is not int or value < schema.get("minimum", value):
                raise BindingRefusal("invocation.parameter-invalid", name)
        else:
            raise BindingRefusal("descriptor.schema-unknown", schema["type"])
        parameters[name] = value
    canonical_input = {
        "descriptor": command_spec["identity"],
        "command": command,
        "params": parameters,
    }
    return {
        "command": command,
        "descriptor": command_spec,
        "descriptor_identity": command_spec["identity"],
        "canonical_input_identity": identity("command-input", canonical_input),
        "invocation_key": invocation_key,
        "params": parameters,
        "store": request["store"],
    }
