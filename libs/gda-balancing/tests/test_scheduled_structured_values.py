"""Public scheduling preserves nominal captures in traces and refusal prefixes."""

from copy import deepcopy
import json

import jsonschema
import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import (
    CheckedExperiment,
    check_experiment_value,
    derive_scenario_program_requirements,
)
from gda_balancing.domain.experiment_artifacts import (
    _event_catalog_records_are_authoritative,
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.model import admit_rir
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root
from test_bounded_fold_public import _specification
from test_current_namespace_public import _PublicCandidate, _members

_OWNER = "standard.conformance.structured"
_LIST = {"package": _OWNER, "id": "IntList4"}
_ENUM = {"package": _OWNER, "id": "CandidateKind"}
_MAX = (1 << 63) - 1


def _authorities():
    kernel, language = mutable_authorities()
    package = next(p for p in language["language"]["packages"] if p["id"] == _OWNER)
    operations = next(
        row["definitions"]
        for row in package["semantic_closure"]
        if row["authority_path"] == "language.operations"
    )
    template = next(row for row in operations if row["id"] == "bounded-fold-v1")
    unit_result = deepcopy(
        next(
            row["result"]
            for row in language["language"]["operations"]
            if row["result"]["type"] == {"package": "kernel", "id": "Unit"}
        )
    )
    quantity = deepcopy(template["inputs"][2])
    quantity["id"] = "selected_count"
    ports = [
        {
            "id": name,
            "access": "read-write",
            "type": typ,
            "value_kind": "nominal-structured",
        }
        for name, typ in (
            ("items", _LIST),
            ("mode", _ENUM),
            ("selected_items", _LIST),
            ("selected_mode", _ENUM),
        )
    ] + [quantity]
    receive_ports = deepcopy(ports)
    for port in receive_ports[:2]:
        port["access"] = "read"
    bodies = {
        "scheduled-capture": [
            {"node": "copy", "target": "captured-items", "value": "items"},
            {"node": "copy", "target": "captured-mode", "value": "mode"},
            {
                "node": "schedule",
                "site": "capture",
                "operation": {"package": _OWNER, "id": "scheduled-receive"},
                "arguments": [
                    {
                        "port": p["id"],
                        "operand": (
                            {"kind": "local", "local": "captured-" + p["id"]}
                            if p["id"] in {"items", "mode"}
                            else {"kind": "port", "port": p["id"]}
                        ),
                    }
                    for p in ports
                ],
                "logical_time": 1,
                "priority": 0,
                "result": {"kind": "local", "name": "child"},
            },
            {
                "node": "constant",
                "target": "empty",
                "literal": {"type": _LIST, "value": []},
            },
            {"node": "write-state", "symbol": "items", "value": "empty"},
            {
                "node": "constant",
                "target": "secondary",
                "literal": {"type": _ENUM, "value": "secondary"},
            },
            {"node": "write-state", "symbol": "mode", "value": "secondary"},
        ],
        "scheduled-receive": [
            {"node": "write-state", "symbol": "selected_items", "value": "items"},
            {"node": "write-state", "symbol": "selected_mode", "value": "mode"},
            {"node": "constant", "target": "one", "literal": 1},
            {"node": "write-state", "symbol": "selected_count", "value": "one"},
        ],
        "scheduled-overflow": [
            {"node": "constant", "target": "maximum", "literal": _MAX},
            {"node": "constant", "target": "one", "literal": 1},
            {"node": "add", "target": "overflow", "left": "maximum", "right": "one"},
        ],
    }
    vectors = next(
        v for v in language.package_conformance_vector_sets if v["package_id"] == _OWNER
    )
    for name, body in bodies.items():
        operation = deepcopy(template)
        operation.update(
            id=name,
            body=body,
            inputs=deepcopy(
                receive_ports
                if name == "scheduled-receive"
                else ports
                if name == "scheduled-capture"
                else []
            ),
            result=deepcopy(unit_result),
            resource_bounds={"max_steps": len(body)},
            vectors=[],
        )
        operation["refusals"] = [
            "runtime.reason.step-limit",
            "runtime.reason.numeric-overflow",
        ]
        if name == "scheduled-capture":
            operation["effects"].append("event.schedule")
            operation["refusals"] += [
                "runtime.reason." + suffix
                for suffix in (
                    "schedule-backward",
                    "schedule-hidden-input",
                    "schedule-illegal-same-time-priority",
                    "queue-limit",
                    "zero-time-depth-limit",
                    "event-limit",
                    "logical-time-limit",
                )
            ]
        for category, path in (
            ("positive", "body"),
            ("effects", "effects"),
            ("resource", "resource_bounds.max_steps"),
        ):
            identity = f"scheduled-values.{name}.{category}"
            expected = operation
            for member in path.split("."):
                expected = expected[member]
            vectors["vector_definitions"].append(
                {
                    "id": identity,
                    "kind": "operation-contract",
                    "operation": name,
                    "probe": {"path": path},
                    "category": category,
                    "expect": deepcopy(expected),
                }
            )
            vectors["vectors"].append(identity)
            operation["vectors"].append(identity)
        operations.append(operation)
        package["exports"]["operations"].append(name)
    _bind_package_vector_set(package, vectors)
    _reidentify_graph_root(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    return kernel, language, context, ports


def _source(ports):
    symbols = [
        {
            "symbol": p["id"],
            "type": p["type"]["id"],
            "role": "state",
            "value_policy": {"mode": "experiment-required"},
        }
        for p in ports[:-1]
    ]
    symbols.append(
        {
            "symbol": "selected_count",
            "type": "quantity",
            "role": "state",
            "representation": "Int",
            "kind": "scalar",
            "unit": "1",
            "domain_kind": "closed-interval",
            "domain": {"minimum": 0, "maximum": 10},
            "numeric_policy": "exact-int64",
            "value_policy": {"mode": "experiment-required"},
        }
    )
    return {
        "schema_version": "2.0.0",
        "manifest": {"id": "example.bounded-fold", "entry_module": "fold"},
        "package_requirements": ["core.quantity", _OWNER],
        "modules": [
            {
                "id": "fold",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "symbol": "Quantity",
                    }
                ]
                + [
                    {"alias": t, "package": _OWNER, "symbol": t}
                    for t in ("IntList4", "CandidateKind")
                ],
                "symbols": symbols,
            }
        ],
        "entrypoints": [
            {
                "id": "capture",
                "operation": {"package": _OWNER, "id": "scheduled-capture"},
                "arguments": [
                    {
                        "port": p["id"],
                        "operand": {
                            "kind": "symbol",
                            "module": "fold",
                            "symbol": p["id"],
                        },
                    }
                    for p in ports
                ],
                "result": {"kind": "discard"},
            },
            {
                "id": "overflow",
                "operation": {"package": _OWNER, "id": "scheduled-overflow"},
                "arguments": [],
                "result": {"kind": "discard"},
            },
        ],
    }


def _experiment(rir, later_refusal):
    specification = _specification(rir, [1, 2], count=1)
    scenario = specification["scenarios"][0]
    scenario["event_plan"][0]["entrypoint"] = "capture"
    if later_refusal:
        event = deepcopy(scenario["event_plan"][0])
        event.update(
            root_event_ref="later-overflow", logical_time=2, entrypoint="overflow"
        )
        scenario["event_plan"].append(event)
    scenario["terminal_condition"] = {"kind": "queue-drained"}
    values = {
        "items": {"type": _LIST, "value": [1, 2]},
        "mode": {"type": _ENUM, "value": "primary"},
        "selected_items": {"type": _LIST, "value": []},
        "selected_mode": {"type": _ENUM, "value": "secondary"},
        "selected_count": 0,
    }
    scenario["assignments"] = [
        {
            "target": {"model": "example.bounded-fold", "module": "fold", "name": name},
            "value": value,
        }
        for name, value in values.items()
    ]
    specification["metrics"] = specification["metrics"][:1]
    requirements = [
        derive_scenario_program_requirements(
            rir, event["entrypoint"], "standard.exact-int64-event-v1", "splitmix64-v1"
        )[0]
        for event in scenario["event_plan"]
    ]
    specification["runtime"]["required_evaluator"] = {
        key: sorted({value for row in requirements for value in row[key]})
        for key in requirements[0]
    }
    return specification


@pytest.mark.parametrize("later_refusal", [False, True], ids=["run", "terminal-audit"])
def test_public_schedule_captures_nominal_values_and_rejects_forgery(
    tmp_path, later_refusal
):
    kernel, language, context, ports = _authorities()
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, language))
    candidate.write_source(_source(ports))
    assert candidate.cli("model", "check", str(candidate.source))["checked"]
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "71" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    rir_path = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = _experiment(rir, later_refusal)
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(specification))
    assert candidate.cli("experiment", "check", str(path), "--rir", rir_path)["checked"]
    result = candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        rir_path,
        "--out",
        str(tmp_path / "run"),
        "--invocation-key",
        "72" * 32,
        success=not later_refusal,
    )
    if later_refusal:
        assert result["error"]["stage"] == "runtime"
        assert result["error"]["diagnostics"][0]["code"] == "runtime.numeric_overflow"
        members = _members(result["error"]["terminal_audit"])
        kind, event_key, catalog_kind, catalog_key = (
            "runtime-terminal-audit",
            "committed_trace_prefix",
            "runtime-terminal-audit",
            "event_catalog_prefix",
        )
    else:
        members = _members(result)
        kind, event_key, catalog_kind, catalog_key = (
            "event-trace",
            "events",
            "snapshot-series",
            "event_catalog",
        )
    checked = check_experiment_value(
        specification,
        admit_rir(rir, authority_context=context),
        authority_context=context,
    )
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, members)
    events = members[kind][event_key]
    parent = next(row for row in events if row["schedules"])
    arguments = {
        row["name"]: row["value"] for row in parent["schedules"][0]["arguments"]
    }
    assert arguments["items"] == {"type": _LIST, "value": [1, 2]}
    assert arguments["mode"] == {"type": _ENUM, "value": "primary"}
    assert {row["name"] for row in parent["schedules"][0]["state_references"]} == {
        "selected_items",
        "selected_mode",
        "selected_count",
    }
    child = next(row for row in events if row["operation"] == "scheduled-receive")
    final = {row["name"]: row["value"] for row in child["state_after"]}
    assert final == {
        "items": {"type": _LIST, "value": []},
        "mode": {"type": _ENUM, "value": "secondary"},
        "selected_items": {"type": _LIST, "value": [1, 2]},
        "selected_mode": {"type": _ENUM, "value": "primary"},
        "selected_count": 1,
    }
    catalog = members[catalog_kind][catalog_key]
    assert _event_catalog_records_are_authoritative(checked, catalog, events)
    for mutation in ("type", "value", "capture"):
        forged = deepcopy(members)
        forged_events = forged[kind][event_key]
        schedule = next(row for row in forged_events if row["schedules"])["schedules"][
            0
        ]
        scheduled = next(
            row["event_spec"]
            for row in forged[catalog_kind][catalog_key]
            if row["event_spec"]["kind"] == "scheduled-transition"
        )
        for rows in (schedule["arguments"], scheduled["arguments"]):
            value = next(
                row["value"]
                for row in rows
                if row["name"] == ("mode" if mutation == "value" else "items")
            )
            if mutation == "type":
                value["type"] = deepcopy(_ENUM)
            elif mutation == "value":
                value["value"] = "not-an-enum-member"
            else:
                value["value"] = [2, 1]
        # Even coordinated trace/catalog changes fail the independent capture
        # replay, before relying on any artifact/journal digest inconsistency.
        assert not _event_catalog_records_are_authoritative(
            checked, forged[catalog_kind][catalog_key], forged_events
        )
        for name in {kind, catalog_kind}:
            contract = checked.output_contracts[name]
            payload = {
                key: value
                for key, value in forged[name].items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
            forged[name] = contract.identify(payload)
            assert validate_experiment_member(checked, name, forged[name])
        assert not validate_experiment_artifact_set(checked, forged)

    for malformed in (
        [1, 2],
        "primary",
        {"type": _LIST, "value": [1, 2], "extra": True},
        {"type": {**_LIST, "extra": True}, "value": [1, 2]},
    ):
        forged_member = deepcopy(members[kind])
        schedule = next(row for row in forged_member[event_key] if row["schedules"])[
            "schedules"
        ][0]
        next(row for row in schedule["arguments"] if row["name"] == "items")[
            "value"
        ] = malformed
        payload = {
            key: value
            for key, value in forged_member.items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
        with pytest.raises(jsonschema.ValidationError):
            checked.output_contracts[kind].identify(payload)
