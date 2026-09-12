"""Derive Snapshot and terminal evidence from the existing Runtime owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _candidate_hex_pattern,
    _contract_schema,
    artifact_envelope_contract,
    ordered_protocol_schema,
)
from gda_balancing.domain.authority.trace_projection import trace_protocol_contracts


def runtime_evidence_protocol_schema(
    kernel: dict[str, Any], role: str, artifact_kind: str
) -> dict[str, Any]:
    """One journal grammar serves complete series and genuine refusal prefixes."""
    meta = kernel["meta_format"]
    law = deepcopy(
        meta["language_definitions"]["wire_schema_protocol_roles"][
            "runtime_evidence_structure"
        ]
    )
    if set(law) != {
        "snapshot_series",
        "terminal_audit",
        "snapshot",
        "continuation",
        "journal_prefix",
        "rng_state",
        "event_catalog_record",
        "event_spec",
    }:
        raise ValueError("Kernel Runtime evidence containers are incomplete")
    runtime = meta["runtime_program"]
    scheduler = runtime["scheduler"]
    trace = trace_protocol_contracts(kernel)
    event = trace["event"]
    event_fields = event["field_types"]
    order = event_fields["ordering_key"]
    values = event_fields["state_after"]
    schedule = event_fields["schedules"]["items"]["field_types"]
    target = schedule["state_references"]["items"]["field_types"]["target"]
    value = values["items"]["field_types"]["value"]

    def supply(record: dict[str, Any], fields: dict[str, Any]) -> None:
        if set(record["field_types"]) & set(fields):
            raise ValueError("Runtime evidence duplicates an existing semantic owner")
        record["field_types"].update(deepcopy(fields))

    def record(names: list[str], fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "closed-object",
            "closed": True,
            "required_members": names,
            "field_types": fields,
        }

    def array(item: dict[str, Any]) -> dict[str, Any]:
        return {"type": "list-of", "items": item}

    specs = law["event_spec"]
    if set(specs) != {
        "common",
        "external_input",
        "root_transition",
        "scheduled_transition",
        "observation",
    }:
        raise ValueError("Kernel admitted Event variants are incomplete")
    supply(specs["common"], {"ordering_key": order})
    assignment = array(record(["target", "value"], {"target": target, "value": value}))
    supply(specs["external_input"], {"facts": assignment})
    supply(specs["root_transition"], {"payload": assignment})
    supply(
        specs["scheduled_transition"],
        {
            name: schedule[name]
            for name in ("operation", "arguments", "state_references")
        },
    )
    supply(specs["observation"], {"ordering_key": order})
    variants = []
    for name in ("external_input", "root_transition", "scheduled_transition"):
        variant = specs[name]
        common = specs["common"]
        if set(common["required_members"]) & set(variant["required_members"]):
            raise ValueError("Admitted Event restates its common frame")
        supply(variant, common["field_types"])
        variant["required_members"] += common["required_members"]
        variants.append(variant)
    variants.append(specs["observation"])
    event_spec = {"type": "one-of", "alternatives": variants}
    catalog = law["event_catalog_record"]
    supply(
        catalog,
        {
            "ordering_key": order,
            "kind": {"enum": [v["field_types"]["kind"]["const"] for v in variants]},
            "event_spec": event_spec,
        },
    )
    continuation = law["continuation"]
    if "required_members" in continuation:
        raise ValueError("Continuation duplicates Runtime configuration membership")
    projection = scheduler["snapshot_identity"]["runtime_configuration_projection"]
    continuation["required_members"] = []
    for path in projection.values():
        parts = path.split(".")
        if len(parts) == 2 and parts[0] == "continuation":
            continuation["required_members"].append(parts[1])
        elif path != "values":
            raise ValueError("Snapshot projection has an unsupported container address")
    rng = law["rng_state"]
    encoding = {
        **runtime["named_rng"]["candidate_encoding"],
        "width_bits": runtime["named_rng"]["word_bits"],
    }
    supply(
        rng,
        {"state_hex": {"type": "string", "pattern": _candidate_hex_pattern(encoding)}},
    )
    supply(
        continuation,
        {
            "lifecycle_state": {
                "enum": runtime["runtime_configuration"]["lifecycle_states"]
            },
            "step_boundary": {
                "type": "one-of",
                "alternatives": [
                    {"enum": runtime["step"]["boundaries"]},
                    {"type": "null"},
                ],
            },
            "event_catalog": law["journal_prefix"],
            "committed_trace": law["journal_prefix"],
            "rng": array(rng),
        },
    )
    snapshot = law["snapshot"]
    supply(snapshot, {"continuation": continuation, "values": values})
    shared = {"root_event_map": trace["envelope"]["field_types"]["root_event_map"]}
    if role == "snapshot-series":
        payload = law["snapshot_series"]
        if "items" in payload["field_types"]["snapshots"]:
            raise ValueError("Snapshot Series duplicates its Snapshot record owner")
        payload["field_types"]["snapshots"]["items"] = snapshot
        supply(payload, {**shared, "event_catalog": array(catalog)})
    elif role == "runtime-terminal-audit":
        payload = law["terminal_audit"]
        refusing = payload["field_types"]["refusing_event"]
        entrypoints = [
            part
            for part in event_fields["entrypoint"]["alternatives"]
            if part.get("type") != "null"
        ]
        if len(entrypoints) != 1:
            raise ValueError("Trace has no unique actual dispatch reference")
        supply(
            refusing,
            {
                "event_spec": event_spec,
                "ordering_key": order,
                "attempted_calls": event_fields["calls"],
                "entrypoint": entrypoints[0],
            },
        )
        supply(
            payload["field_types"]["rollback"],
            {
                "state_before": event_fields["state_before"],
                "state_after": values,
            },
        )
        budgets = list(scheduler["budget_members"])
        supply(
            payload,
            {
                **shared,
                "committed_trace_prefix": array(event),
                "last_snapshot": values,
                "last_snapshot_record": snapshot,
                "event_catalog_prefix": array(catalog),
                "terminal_condition": trace["terminal"]["field_types"]["condition"],
                "budget_counters": record(
                    budgets, {name: {"type": "integer"} for name in budgets}
                ),
            },
        )
    else:
        raise ValueError("Unknown Runtime evidence protocol role")
    common = artifact_envelope_contract(kernel, artifact_kind)
    if set(common["required_members"]) & set(payload["required_members"]):
        raise ValueError("Runtime evidence duplicates the Artifact envelope")
    supply(payload, common["field_types"])
    payload["required_members"] += common["required_members"]
    return ordered_protocol_schema(
        kernel,
        {
            "$schema": meta["language_definitions"]["collections"][
                "artifact_wire_schemas"
            ]["field_types"]["schema"]["dialect"],
            **_contract_schema(payload),
        },
    )


def project_runtime_evidence_schemas(
    kernel: dict[str, Any], language: dict[str, Any]
) -> None:
    """Resolve actual LDB kind bindings; refuse authored overrides or missing roles."""
    for role in ("snapshot-series", "runtime-terminal-audit"):
        definitions = [
            row
            for row in language["artifact_wire_schemas"]
            if row.get("protocol_role") == role
        ]
        if len(definitions) != 1:
            raise ValueError("Runtime evidence protocol role is missing or ambiguous")
        definition = definitions[0]
        if "schema" in definition:
            raise ValueError("Runtime evidence structure cannot be authored by an LDB")
        contracts = [
            row
            for row in language["artifact_contracts"]
            if row["schema_kind"] == definition["artifact_kind"]
        ]
        if len(contracts) != 1:
            raise ValueError(
                "Runtime evidence artifact binding is missing or ambiguous"
            )
        definition["schema"] = runtime_evidence_protocol_schema(
            kernel, role, contracts[0]["artifact_kind"]
        )
