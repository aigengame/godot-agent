"""Compose the standalone Experiment wire from existing semantic owners."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.contract_projection import (
    _contract_schema,
    ordered_protocol_schema,
)
from gda_balancing.domain.authority.trace_projection import trace_protocol_contracts


def experiment_judgment_contracts(kernel: dict[str, Any]) -> dict[str, Any]:
    """The two finite language judgments supply selected execution dependencies."""
    collections = kernel["meta_format"]["language_definitions"]["collections"]
    result = {}
    for role, operators in (
        ("metric", ["single-event-integer", "single-terminal-integer"]),
        ("acceptance", ["all-metrics-within-target"]),
    ):
        contract = deepcopy(collections[f"experiment_{role}_judgments"])
        if contract["field_types"]["operator"] != {"enum": operators}:
            raise ValueError("Experiment judgment operator vocabulary is unsupported")
        result[role] = {"type": "closed-object", "closed": True, **contract}
    return result


def selected_experiment_judgments_contract(kernel: dict[str, Any]) -> dict[str, Any]:
    definitions = experiment_judgment_contracts(kernel)
    return _record(
        {
            "metrics": {
                "type": "list-of",
                "items": _record(
                    {
                        "metric": {"type": "non-empty-string"},
                        "judgment": definitions["metric"],
                    }
                ),
                "minItems": 1,
            },
            "acceptance": definitions["acceptance"],
        }
    )


def _record(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "closed-object",
        "closed": True,
        "required_members": list(fields),
        "field_types": fields,
    }


def experiment_input_schema(kernel: dict[str, Any]) -> dict[str, Any]:
    """Reuse values, root Events, terminal and Metric records before wire conversion."""
    meta = kernel["meta_format"]
    protocols = meta["language_definitions"]["wire_schema_protocol_roles"]
    law = deepcopy(protocols["experiment_input_structure"])
    if (
        set(law)
        != {
            "identity",
            "input",
            "scenario",
            "metric",
            "external_facts_minimum",
        }
        or law["identity"]["projection"] != "complete-input"
    ):
        raise ValueError("Experiment input composition is incomplete")
    if law["external_facts_minimum"] != 1:
        raise ValueError("Experiment external facts must be nonempty")
    trace = trace_protocol_contracts(kernel)
    events = trace["event"]["field_types"]
    ordering = events["ordering_key"]["field_types"]
    target = events["schedules"]["items"]["field_types"]["state_references"]["items"][
        "field_types"
    ]["target"]
    value = events["state_after"]["items"]["field_types"]["value"]
    assignment = {
        "type": "list-of",
        "items": _record({"target": target, "value": value}),
    }

    def supply(record: dict[str, Any], fields: dict[str, Any]) -> None:
        if record["field_types"].keys() & fields.keys():
            raise ValueError("Experiment composition duplicates a semantic owner")
        record["field_types"].update(deepcopy(fields))

    roots = []
    for name, member in (("external_input", "facts"), ("root_transition", "payload")):
        root = deepcopy(protocols["runtime_evidence_structure"]["event_spec"][name])
        inputs = deepcopy(assignment)
        if member == "facts":
            inputs["minItems"] = law["external_facts_minimum"]
        supply(
            root,
            {
                member: inputs,
                "logical_time": ordering["logical_time"],
                "priority": ordering["priority"],
            },
        )
        root["required_members"] += ["logical_time", "priority"]
        roots.append(root)
    scenario = law["scenario"]
    supply(
        scenario,
        {
            "assignments": assignment,
            "event_plan": {
                "type": "list-of",
                "minItems": 1,
                "items": {"type": "one-of", "alternatives": roots},
            },
            "terminal_condition": trace["terminal"]["field_types"]["condition"],
        },
    )
    selector = experiment_judgment_contracts(kernel)["metric"]["field_types"][
        "selector"
    ]
    metric = law["metric"]
    metric_fields = deepcopy(selector["field_types"])
    sample = protocols["metric_outcome_structure"]["sample"]["field_types"]
    observation = next(
        part
        for part in events["observation"]["alternatives"]
        if part.get("type") == "closed-object"
    )["field_types"]
    # The discriminator fields are language labels. Their interpretation is selected
    # during Experiment admission, independently of this closed input container.
    metric_fields["window"] = _record(
        {
            **metric_fields["window"]["field_types"],
            "name": observation["window"]["field_types"]["name"],
        }
    )
    metric_fields["observation"] = _record(
        {
            **metric_fields["observation"]["field_types"],
            "name": sample["provenance"]["field_types"]["observation_name"],
            "member": sample["member"],
        }
    )
    integer = events["facts"]["items"]["field_types"]["integer"]
    metric_fields.update(
        id=observation["metric"],
        unit=sample["unit"],
        dimensions=sample["dimensions"],
        target=_record({"minimum": integer, "maximum": integer}),
    )
    supply(metric, metric_fields)
    text = {"type": "non-empty-string"}
    digest = protocols["rir_structure"]["containers"]["envelope"]["field_types"][
        "semantic_identity"
    ]
    result = law["input"]
    supply(
        result,
        {
            "model": _record({"rir_semantic_identity": digest}),
            "runtime": _record({"profile": text}),
            "seed": _record(
                {
                    "algorithm": {
                        "enum": [meta["runtime_program"]["named_rng"]["algorithm"]]
                    },
                    "value": integer,
                }
            ),
            "scenarios": {"type": "list-of", "minItems": 1, "items": scenario},
            "metrics": {"type": "list-of", "minItems": 1, "items": metric},
            "acceptance": _record({"policy": text}),
        },
    )
    return ordered_protocol_schema(
        kernel,
        {
            "$schema": meta["language_definitions"]["collections"][
                "artifact_wire_schemas"
            ]["field_types"]["schema"]["dialect"],
            **_contract_schema(result),
        },
    )


def project_experiment_input(kernel: dict[str, Any], language: dict[str, Any]) -> None:
    """Reject raw overrides and incomplete result bindings before public admission."""
    schemas = [
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == "experiment-specification"
    ]
    if len(schemas) != 1 or "schema" in schemas[0]:
        raise ValueError("Experiment input has an absent, ambiguous or authored Schema")
    schemas[0]["schema"] = experiment_input_schema(kernel)
