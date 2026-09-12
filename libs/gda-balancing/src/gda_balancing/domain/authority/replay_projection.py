"""Derive the fixed Replay comparison container from its existing semantic owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    artifact_envelope_contract,
)
from gda_balancing.domain.authority.package_projection import replay_observation_schemas
from gda_balancing.domain.authority.metric_projection import metric_outcome_schema


def _binding(
    language: dict[str, Any], role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    schemas = [
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == role
    ]
    if len(schemas) != 1:
        raise ValueError("Replay protocol role is missing or ambiguous")
    contracts = [
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schemas[0]["artifact_kind"]
    ]
    if len(contracts) != 1:
        raise ValueError("Replay artifact binding is missing or ambiguous")
    return schemas[0], contracts[0]


def replay_comparison_schema(
    kernel: dict[str, Any], language: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    """Keep the outer wire fixed and bind the actual selected outcome artifacts."""
    meta = kernel["meta_format"]
    law = deepcopy(
        meta["language_definitions"]["wire_schema_protocol_roles"][
            "replay_comparison_structure"
        ]
    )
    if set(law) != {"required_members", "field_types"}:
        raise ValueError("Kernel Replay container has unknown or missing members")
    envelope = artifact_envelope_contract(kernel, artifact_kind)
    fields = {
        name: _contract_schema(value) for name, value in envelope["field_types"].items()
    }
    if set(fields) & set(law["field_types"]):
        raise ValueError("Replay container duplicates the Artifact envelope")
    fields.update(
        {name: _contract_schema(value) for name, value in law["field_types"].items()}
    )
    observation, checks, result = replay_observation_schemas(meta)
    outcomes = [
        _binding(language, role) for role in ("evaluation-run", "experiment-verdict")
    ]
    statuses = [
        metric_outcome_schema(kernel, language, role, contract["artifact_kind"])[
            "properties"
        ]["outcome"]["const"]
        for role, (_schema, contract) in zip(
            ("evaluation-run", "experiment-verdict"), outcomes, strict=True
        )
    ]
    if (
        not all(isinstance(status, str) and status for status in statuses)
        or len(set(statuses)) != 2
    ):
        raise ValueError("Replay producing outcomes have no distinct status contracts")
    observation = deepcopy(observation)
    observation["properties"]["evaluation_outcome_status"] = {"enum": statuses}
    derived = {
        "original_observation": observation,
        "replay_observation": deepcopy(observation),
        "checks": checks,
        "result": result,
        "replay_outcome_kind": {
            "enum": [contract["artifact_kind"] for _, contract in outcomes]
        },
    }
    if set(fields) & set(derived):
        raise ValueError("Replay container duplicates an existing semantic owner")
    fields.update(derived)
    required = law["required_members"]
    if (
        not isinstance(required, list)
        or not all(isinstance(member, str) for member in required)
        or len(required) != len(set(required))
        or set(required) != set(fields)
    ):
        raise ValueError("Kernel Replay container membership is incomplete")
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        "type": "object",
        "properties": fields,
        "required": list(required),
        "unevaluatedProperties": False,
    }


def project_replay_comparison_schema(
    kernel: dict[str, Any], language: dict[str, Any]
) -> None:
    """Populate the derived view; the physical LDB cannot override Replay's wire."""
    try:
        schema, contract = _binding(language, "replay-comparison")
        if "schema" in schema:
            raise ValueError("Replay comparison structure cannot be authored by an LDB")
        schema["schema"] = replay_comparison_schema(
            kernel, language, contract["artifact_kind"]
        )
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError(
            "Kernel Replay structure or artifact binding is incomplete"
        ) from error
