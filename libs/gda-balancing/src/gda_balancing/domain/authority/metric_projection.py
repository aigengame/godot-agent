"""Derive Metric samples and primary outcome wire from their protocol owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
    ordered_protocol_schema,
)
from gda_balancing.domain.authority.trace_projection import trace_protocol_schema


def _metric_binding(language: dict[str, Any], role: str):
    schemas = [
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == role
    ]
    if len(schemas) != 1:
        raise ValueError("Metric protocol role is missing or ambiguous")
    contracts = [
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schemas[0]["artifact_kind"]
    ]
    if len(contracts) != 1:
        raise ValueError("Metric protocol artifact binding is missing or ambiguous")
    return schemas[0], contracts[0]


def metric_outcome_schema(
    kernel: dict[str, Any], language: dict[str, Any], role: str, artifact_kind: str
) -> dict[str, Any]:
    """Project fixed containers; actual Metric values remain authored and checked."""
    meta = kernel["meta_format"]
    protocols = meta["language_definitions"]["wire_schema_protocol_roles"]
    law = deepcopy(protocols["metric_outcome_structure"])
    if set(law) != {"bindings", "dataset", "sample", "primary", "outcomes"} or set(
        law["outcomes"]
    ) != {"evaluation-run", "experiment-verdict"}:
        raise ValueError("Kernel Metric containers are incomplete")
    _, trace_contract = _metric_binding(language, "event-trace")
    trace = trace_protocol_schema(kernel, trace_contract["artifact_kind"])["properties"]
    event = trace["events"]["items"]["properties"]
    observations = [
        row for row in event["observation"]["oneOf"] if row.get("type") == "object"
    ]
    if len(observations) != 1:
        raise ValueError("Trace Metric observation owner is ambiguous")
    observation = observations[0]["properties"]

    def fields(contract, *groups):
        result = {
            name: _contract_schema(value)
            for name, value in contract["field_types"].items()
        }
        for derived in groups:
            if result.keys() & derived.keys():
                raise ValueError(
                    "Metric container duplicates a selected semantic owner"
                )
            result.update(deepcopy(derived))
        return result

    def closed(contract, properties):
        required = contract["required_members"]
        if (
            contract.get("type") != "closed-object"
            or contract.get("closed") is not True
            or len(required) != len(set(required))
            or set(required) != set(properties)
        ):
            raise ValueError("Metric container membership is incomplete")
        return {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "unevaluatedProperties": False,
        }

    common = artifact_envelope_contract(kernel, artifact_kind)
    bindings = {
        name: _contract_schema(value) for name, value in law["bindings"].items()
    }
    if role == "metric-dataset":
        sample = closed(
            law["sample"],
            fields(
                law["sample"],
                {
                    "metric": observation["metric"],
                    "metric_definition_identity": observation[
                        "metric_definition_identity"
                    ],
                    "window": observation["window"]["properties"]["name"],
                    "value": event["facts"]["items"]["properties"]["integer"],
                    "logical_time": event["ordering_key"]["properties"]["logical_time"],
                },
            ),
        )
        payload = law["dataset"]
        properties = fields(
            payload,
            bindings,
            {
                "samples": {"type": "array", "minItems": 1, "items": sample},
                "metric_definition_identities": {
                    "type": "array",
                    "minItems": 1,
                    "items": deepcopy(observation["metric_definition_identity"]),
                },
            },
        )
    elif role in law["outcomes"]:
        payload = law["primary"]
        variant = law["outcomes"][role]
        if set(variant) != (
            {"outcome"} if role == "evaluation-run" else {"outcome", "failed_metrics"}
        ):
            raise ValueError("Primary Metric outcome members are incomplete")
        payload["required_members"].extend(variant)
        properties = fields(
            payload,
            bindings,
            {
                "root_event_map": trace["root_event_map"],
                "terminal_statuses": trace["terminal_statuses"],
            },
            {name: _contract_schema(value) for name, value in variant.items()},
        )
    else:
        raise ValueError("Unknown Metric protocol role")
    closed(payload, properties)
    if properties.keys() & common["field_types"].keys():
        raise ValueError("Metric payload duplicates the Artifact envelope")
    properties.update(fields(common, {}))
    required = payload["required_members"] + common["required_members"]
    return ordered_protocol_schema(
        kernel,
        {
            "$schema": meta["language_definitions"]["collections"][
                "artifact_wire_schemas"
            ]["field_types"]["schema"]["dialect"],
            "type": "object",
            "properties": properties,
            "required": required,
            "unevaluatedProperties": False,
        },
    )


def project_metric_outcome_schemas(
    kernel: dict[str, Any], language: dict[str, Any]
) -> None:
    """Populate the derived view without permitting authored protocol overrides."""
    for role in ("metric-dataset", "evaluation-run", "experiment-verdict"):
        schema, contract = _metric_binding(language, role)
        if "schema" in schema:
            raise ValueError("Metric outcome structure cannot be authored by an LDB")
        schema["schema"] = metric_outcome_schema(
            kernel, language, role, contract["artifact_kind"]
        )
