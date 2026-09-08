"""Derive the fixed Event Trace wire structure from its actual Kernel owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import _contract_schema


def _record(members: list[str], fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "closed-object",
        "closed": True,
        "required_members": members,
        "field_types": fields,
    }


def trace_protocol_schema(kernel: dict[str, Any], artifact_kind: str) -> dict[str, Any]:
    """Project one Trace structure; no LDB schema, override, or ambient authority."""
    meta = kernel["meta_format"]
    structure = deepcopy(
        meta["language_definitions"]["wire_schema_protocol_roles"]["trace_structure"]
    )
    if set(structure) != {"envelope", "event", "terminal"}:
        raise ValueError("Kernel Trace containers are incomplete")
    runtime = meta["runtime_program"]
    scheduler = runtime["scheduler"]
    literal = meta["literal_typing"]["typed_envelope_profile"]
    text = {"type": "non-empty-string"}
    integer = {"type": "integer"}
    coordinate_members = literal["admission"]["nominal_type_reference"][
        "coordinate_members"
    ]
    coordinate = _record(
        coordinate_members, {name: text for name in coordinate_members}
    )
    value = _record(
        [literal["type_member"], literal["value_member"]],
        {
            literal["type_member"]: coordinate,
            literal["value_member"]: {"type": "canonical-json"},
        },
    )
    runtime_value = {"type": "one-of", "alternatives": [integer, value]}
    order = scheduler["ordering"]
    ordering_key = _record(
        [row["member"] for row in order],
        {
            row["member"]: {"enum": row["rank"]} if "rank" in row else integer
            for row in order
        },
    )
    outcome = _record(
        ["id", "kind"],
        {"id": text, "kind": {"enum": runtime["outcome_contract"]["kinds"]}},
    )

    def supply(record: dict[str, Any], fields: dict[str, Any]) -> None:
        if set(record["field_types"]) & set(fields):
            raise ValueError("Trace structure duplicates an existing semantic owner")
        record["field_types"].update(fields)

    event = structure["event"]
    supply(event, {"ordering_key": ordering_key, "outcome": outcome})
    fields = event["field_types"]
    supply(fields["facts"]["items"], {"value": value})
    for member in ("state_before", "state_after"):
        supply(fields[member]["items"], {"value": runtime_value})
    for member in ("calls", "schedules"):
        supply(fields[member]["items"], {"operation": coordinate})
    schedules = fields["schedules"]["items"]
    supply(schedules, {"ordering_key": ordering_key})
    supply(schedules["field_types"]["arguments"]["items"], {"value": runtime_value})
    formula_context = fields["formula_evaluations"]["items"]["field_types"]["context"]
    supply(
        formula_context,
        {
            "phase": {
                "const": runtime["runtime_configuration"]["lifecycle_roles"]["active"]
            }
        },
    )
    terminal = structure["terminal"]
    if "required_members" in terminal:
        raise ValueError("Trace structure duplicates scheduler terminal members")
    terminal["required_members"] = scheduler["terminal_status"]["members"]
    supply(terminal, {"reason": {"enum": scheduler["terminal_status"]["reasons"]}})
    root_members = scheduler["root_admission_map"]["members"]
    envelope = structure["envelope"]
    supply(
        envelope,
        {
            "artifact_kind": {"const": artifact_kind},
            "events": {"type": "list-of", "items": event},
            "root_event_map": {
                "type": "list-of",
                "items": _record(root_members, {name: text for name in root_members}),
            },
            "terminal_statuses": {"type": "list-of", "items": terminal},
        },
    )
    schema = _contract_schema(envelope)
    return {
        "$schema": meta["language_definitions"]["collections"]["artifact_wire_schemas"][
            "field_types"
        ]["schema"]["dialect"],
        **schema,
    }


def project_trace_schema(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Populate only a derived index; attached packages never acquire a schema."""
    try:
        for row in language["artifact_wire_schemas"]:
            if row.get("protocol_role") != "event-trace":
                if "schema" not in row:
                    raise ValueError("an authored artifact schema is missing")
                continue
            if "schema" in row:
                raise ValueError("Event Trace structure cannot be authored by an LDB")
            contracts = [
                item
                for item in language["artifact_contracts"]
                if item["schema_kind"] == row["artifact_kind"]
            ]
            if len(contracts) != 1:
                raise ValueError("Trace artifact binding is not unique")
            row["schema"] = trace_protocol_schema(kernel, contracts[0]["artifact_kind"])
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError(
            "Kernel Trace structure or artifact binding is incomplete"
        ) from error
