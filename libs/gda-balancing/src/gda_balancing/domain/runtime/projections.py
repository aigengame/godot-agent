"""Authority-derived Runtime contracts, identities, and evidence projections."""

import hashlib
import json
import platform
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import (
    CheckedExperiment,
    _ordered_root_events_under,
    _scenario_root_events,
)
from gda_balancing.domain.operation_program import (
    OperationCoordinate,
    selected_operation_index,
)
from gda_balancing.domain.program_reachability import (
    project_reachable_program_structure,
)
from gda_balancing.domain.publication import PublicationMember
from gda_balancing.domain.runtime.scheduler import RuntimeScheduler
from gda_balancing.domain.structured_values import (
    StructuredValueIndex,
    typed_envelope_members,
)
from gda_balancing.infrastructure.package_resources import (
    list_package_resources,
    read_package_resource,
)


EVALUATOR_IMPLEMENTATION = "gda-balancing.deterministic-event-evaluator-v1"

SUPPORTED_RUNTIME_OPERATORS = frozenset(
    {
        "copy-value",
        "cancel-event",
        "canonical-equal",
        "bounded-lookup",
        "bounded-list-append",
        "bounded-pure-fold",
        "collection-is-empty",
        "gameplay-precondition",
        "guarded-outcome-block",
        "integer-add",
        "integer-compare",
        "integer-floor-divide",
        "typed-literal",
        "integer-multiply",
        "integer-subtract",
        "invoke-operation",
        "named-integer-draw",
        "select-value",
        "schedule-operation",
        "state-integer-subtract",
        "state-write",
        "typed-require",
    }
)


@dataclass(frozen=True)
class RuntimeRefusalOutcome:
    """Runtime-to-Evidence handoff for one terminal refusal."""

    report: Schema2RefusalReport
    scenario_id: str
    scenario_index: int
    committed_trace_prefix: tuple[dict[str, JsonValue], ...]
    event_catalog_prefix: tuple[dict[str, JsonValue], ...]
    root_event_map: tuple[dict[str, JsonValue], ...]
    terminal_condition: dict[str, JsonValue]
    last_snapshot_identity: str
    last_snapshot_record: dict[str, JsonValue]
    budget_counters: dict[str, int]
    last_state: dict[str, Any]
    refusing_event_index: int
    refusing_event_id: str
    refusing_event_spec: dict[str, JsonValue]
    refusing_attempted_calls: tuple[dict[str, JsonValue], ...]
    refusing_ordering_key: dict[str, JsonValue]
    refusing_snapshot_before_identity: str
    refusing_entrypoint_id: str
    refusing_entrypoint_identity: str
    refusing_operation: str
    refusing_call_path: str
    refusing_call_site_identity: str | None
    refusing_evaluation_site_identity: str | None
    refusing_instruction_index: int | None
    state_before: dict[str, Any]
    state_after: dict[str, Any]


def artifact(
    checked: CheckedExperiment,
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> PublicationMember:
    """Create one Runtime artifact under the request's selected output contract."""
    contract = checked.output_contracts[artifact_kind]
    value = contract.identify(payload)
    return PublicationMember(
        value=value,
        artifact_kind=artifact_kind,
        wire_schema_identity=contract.wire_schema_identity,
        content_identity=cast(str, value["content_identity"]),
    )


def runtime_contract(checked: CheckedExperiment) -> dict[str, Any]:
    """Return the selected execution laws carried by the admitted program."""
    return cast(
        dict[str, Any],
        checked.rir["selected_semantics"]["execution_laws"]["runtime_program"],
    )


def runtime_execution_contract(checked: CheckedExperiment) -> dict[str, Any]:
    """Project the Runtime lifecycle, transition, and step contracts."""
    runtime = runtime_contract(checked)
    return {
        member: cast(dict[str, Any], runtime[member])
        for member in ("runtime_configuration", "transition", "step")
    }


def execution_path_segment(checked: CheckedExperiment, segment: str) -> str:
    """Encode one authored segment under the selected invocation path law."""
    encoding = runtime_contract(checked)["invocation_contract"]["execution_path"][
        "segment_encoding"
    ]
    # Escape the escape character first; the encoded slash must not be escaped twice.
    return segment.replace("~", encoding["~"]).replace("/", encoding["/"])


def runtime_lifecycle_roles(checked: CheckedExperiment) -> dict[str, str]:
    configuration = runtime_execution_contract(checked)["runtime_configuration"]
    return cast(dict[str, str], configuration["lifecycle_roles"])


def runtime_boundary_roles(checked: CheckedExperiment) -> dict[str, str]:
    step = runtime_execution_contract(checked)["step"]
    return cast(dict[str, str], step["boundary_roles"])


def runtime_nodes(checked: CheckedExperiment) -> dict[str, dict[str, Any]]:
    """Index exact Kernel Runtime nodes by id."""
    return {
        row["id"]: row
        for row in cast(list[dict[str, Any]], runtime_contract(checked)["nodes"])
    }


def operation_formula_slot(
    operation: dict[str, Any], slot_id: str
) -> dict[str, Any] | None:
    extensions = operation.get("extensions")
    slots = (
        extensions.get("standard.formula-slots")
        if isinstance(extensions, dict)
        else None
    )
    matches = (
        [row for row in slots if isinstance(row, dict) and row.get("id") == slot_id]
        if isinstance(slots, list)
        else []
    )
    return cast(dict[str, Any], matches[0]) if len(matches) == 1 else None


def operation_formula_evaluation_record(
    operation: dict[str, Any],
    binding: dict[str, Any],
    variables: dict[str, Any],
    *,
    evaluation_site_identity: str,
    frame_identity: JsonValue,
    call_path: tuple[str, ...],
) -> dict[str, JsonValue] | None:
    """Build the canonical Formula-evaluation record shape."""
    binding_site = cast(dict[str, Any], binding["site"])
    slot = operation_formula_slot(operation, cast(str, binding_site["slot"]))
    if slot is None:
        return None
    formula_parameter_by_slot_parameter = {
        cast(str, argument["operand"]["parameter"]): cast(str, argument["parameter"])
        for argument in cast(list[dict[str, Any]], binding["arguments"])
    }
    evaluated_arguments: list[dict[str, JsonValue]] = []
    for parameter in cast(list[dict[str, Any]], slot["parameters"]):
        source = cast(dict[str, Any], parameter["source"])
        source_name = source.get("name")
        parameter_id = parameter.get("id")
        if (
            source.get("kind") not in {"port", "local"}
            or not isinstance(source_name, str)
            or source_name not in variables
            or not isinstance(parameter_id, str)
            or parameter_id not in formula_parameter_by_slot_parameter
        ):
            return None
        evaluated_arguments.append(
            {
                "parameter": formula_parameter_by_slot_parameter[parameter_id],
                "value": cast(JsonValue, variables[source_name]),
            }
        )
    target = slot.get("target")
    if not isinstance(target, str) or target not in variables:
        return None
    return {
        "evaluation_site_identity": evaluation_site_identity,
        "binding_identity": cast(JsonValue, binding["identity"]),
        "formula": cast(JsonValue, binding["formula"]),
        "operation": cast(JsonValue, binding_site["operation"]),
        "slot": cast(JsonValue, binding_site["slot"]),
        "context": cast(JsonValue, binding_site["context"]),
        "arguments": cast(
            JsonValue,
            sorted(evaluated_arguments, key=lambda row: cast(str, row["parameter"])),
        ),
        "result": cast(JsonValue, variables[target]),
        "frame_identity": frame_identity,
        "call_path": "/".join(call_path),
    }


def scheduler_contract(checked: CheckedExperiment) -> Mapping[str, Any]:
    """Return the exact Kernel scheduler contract."""
    return RuntimeScheduler(runtime_contract(checked)["scheduler"]).contract


def scenario_transition_events(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in _scenario_root_events(scenario)
        if event["kind"] == "transition-invocation"
    ]


def _resolved_symbol_from_identity(identity: bytes) -> dict[str, JsonValue]:
    resolved = json.loads(identity)
    if (
        not isinstance(resolved, dict)
        or set(resolved) != {"model", "module", "name"}
        or not all(isinstance(value, str) and value for value in resolved.values())
    ):
        raise ValueError("Runtime state reference is not a Resolved Symbol")
    return cast(dict[str, JsonValue], resolved)


def pending_event_projection(event: dict[str, Any]) -> dict[str, JsonValue]:
    """Project one admitted pending Event to its public journal shape."""
    ordering_key = cast(
        dict[str, JsonValue],
        {
            "logical_time": event["logical_time"],
            "phase": event["phase"],
            "priority": event["priority"],
            "enqueue_sequence": event["enqueue_sequence"],
        },
    )
    common = {
        "event_id": cast(str, event["event_id"]),
        "ordering_key": ordering_key,
        "zero_time_depth": cast(int, event.get("zero_time_depth", 0)),
    }
    if event.get("kind") == "external-input":
        return {
            **common,
            "kind": "external-input",
            "root_event_ref": cast(str, event["root_event_ref"]),
            "source_identity": cast(str, event["source_identity"]),
            "source_sequence": cast(int, event["source_sequence"]),
            "facts": cast(JsonValue, event["facts"]),
        }
    if "entrypoint" in event:
        projected = cast(
            dict[str, JsonValue],
            {
                **common,
                "kind": "transition-invocation",
                "root_event_ref": cast(str, event["root_event_ref"]),
                "entrypoint": cast(str, event["entrypoint"]),
                "payload": cast(JsonValue, event["payload"]),
            },
        )
        if event.get("event_references"):
            projected["event_references"] = cast(JsonValue, event["event_references"])
        return projected
    return {
        **common,
        "kind": "scheduled-transition",
        "parent_event_id": cast(str, event["parent_event_id"]),
        "call_site_identity": cast(str, event["call_site_identity"]),
        "schedule_sequence": cast(int, event["schedule_sequence"]),
        "operation": cast(JsonValue, event["operation_ref"]),
        "arguments": cast(
            JsonValue,
            [
                {"name": name, "value": value}
                for name, value in sorted(
                    cast(dict[str, JsonValue], event["arguments"]).items()
                )
            ],
        ),
        "state_references": cast(
            JsonValue,
            [
                {"name": name, "target": _resolved_symbol_from_identity(identity)}
                for name, identity in sorted(
                    cast(dict[str, bytes], event["state_references"]).items()
                )
            ],
        ),
    }


def runtime_journal_contract(checked: CheckedExperiment) -> dict[str, Any]:
    journal = scheduler_contract(checked).get("runtime_journal")
    if not isinstance(journal, dict):
        raise ValueError("Kernel Runtime journal contract is absent")
    return cast(dict[str, Any], journal)


def empty_runtime_journal_identity(contract: dict[str, Any]) -> str:
    return content_identity(cast(str, contract["domain"]), [])


def extend_runtime_journal_identity(
    contract: dict[str, Any],
    previous_identity: str,
    record: dict[str, JsonValue],
) -> str:
    return content_identity(
        cast(str, contract["domain"]),
        cast(JsonValue, {"previous_identity": previous_identity, "record": record}),
    )


def committed_event_projection(
    event: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        member: value
        for member, value in event.items()
        if member != "snapshot_after_identity"
    }


def event_catalog_record(
    checked: CheckedExperiment,
    scenario_id: str,
    event: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    contract = runtime_journal_contract(checked)["event_spec"]
    event_spec = cast(dict[str, JsonValue], deepcopy(event))
    return cast(
        dict[str, JsonValue],
        {
            "scenario": scenario_id,
            "event_id": event["event_id"],
            "kind": event["kind"],
            "ordering_key": event["ordering_key"],
            "event_spec": event_spec,
            "event_spec_identity": content_identity(
                cast(str, contract["domain"]), cast(JsonValue, event_spec)
            ),
        },
    )


def ordered_root_events(
    checked: CheckedExperiment, scenario: dict[str, Any]
) -> list[dict[str, Any]]:
    return _ordered_root_events_under(scheduler_contract(checked), scenario)


def root_event_id(
    checked: CheckedExperiment, scenario_id: str, event: dict[str, Any]
) -> str:
    identity = cast(dict[str, Any], scheduler_contract(checked)["event_identity"])
    body = {
        "experiment_identity": checked.content_identity,
        "scenario_id": scenario_id,
        "root_event_ref": event["root_event_ref"],
        "logical_time": event["logical_time"],
        "phase": event["phase"],
        "priority": event["priority"],
        "enqueue_sequence": event["enqueue_sequence"],
    }
    return content_identity(cast(str, identity["domain"]), cast(JsonValue, body))


def scheduled_event_id(
    checked: CheckedExperiment, scenario_id: str, event: dict[str, Any]
) -> str:
    identity = cast(dict[str, Any], scheduler_contract(checked)["event_identity"])
    body = {
        "experiment_identity": checked.content_identity,
        "scenario_id": scenario_id,
        "parent_event_id": event["parent_event_id"],
        "call_site_identity": event["call_site_identity"],
        "schedule_sequence": event["schedule_sequence"],
        "logical_time": event["logical_time"],
        "phase": event["phase"],
        "priority": event["priority"],
        "enqueue_sequence": event["enqueue_sequence"],
    }
    return content_identity(cast(str, identity["domain"]), cast(JsonValue, body))


def projected_runtime_identity(
    contract: dict[str, Any], values: dict[str, JsonValue]
) -> str:
    projection = contract.get("projection")
    domain = contract.get("domain")
    if (
        not isinstance(projection, list)
        or not projection
        or not all(isinstance(member, str) for member in projection)
        or set(values) != set(projection)
        or not isinstance(domain, str)
        or not domain
    ):
        raise ValueError("Kernel runtime identity projection is incomplete")
    body = {member: values[member] for member in projection}
    return content_identity(domain, cast(JsonValue, body))


def observation_event_id(
    checked: CheckedExperiment,
    scenario_id: str,
    metric_definition_identity: str,
    *,
    logical_time: int,
    enqueue_sequence: int,
) -> str:
    scheduler = scheduler_contract(checked)
    identity = cast(dict[str, Any], scheduler["event_identity"])
    observation = cast(dict[str, Any], scheduler["observation"])
    return projected_runtime_identity(
        {
            "domain": identity["domain"],
            "projection": identity["variants"]["observation"],
        },
        {
            "experiment_identity": checked.content_identity,
            "scenario_id": scenario_id,
            "metric_definition_identity": metric_definition_identity,
            "logical_time": logical_time,
            "phase": observation["phase"],
            "priority": observation["priority"],
            "enqueue_sequence": enqueue_sequence,
        },
    )


def external_input_identity(
    checked: CheckedExperiment, scenario_id: str, event: dict[str, Any]
) -> str:
    return projected_runtime_identity(
        cast(dict[str, Any], scheduler_contract(checked)["external_input_identity"]),
        {
            "experiment_identity": checked.content_identity,
            "scenario_id": scenario_id,
            "root_event_ref": event["root_event_ref"],
            "source_identity": event["source_identity"],
            "source_sequence": event["source_sequence"],
            "facts": cast(JsonValue, event["facts"]),
        },
    )


def value_rows(
    values: dict[str, Any], structured_authority: StructuredValueIndex
) -> list[dict[str, JsonValue]]:
    envelope_members = (
        set(typed_envelope_members(structured_authority))
        if structured_authority.typed_envelope_profile is not None
        else None
    )
    rows: list[dict[str, JsonValue]] = []
    for name in sorted(values):
        value = values[name]
        if isinstance(value, bool):
            rows.append({"name": name, "kind": "boolean", "boolean": value})
        elif isinstance(value, int):
            rows.append({"name": name, "kind": "integer", "integer": value})
        elif isinstance(value, str):
            rows.append({"name": name, "kind": "string", "string": value})
        elif (
            isinstance(value, dict)
            and envelope_members is not None
            and set(value) == envelope_members
        ):
            rows.append(
                {"name": name, "kind": "structured", "value": cast(JsonValue, value)}
            )
        else:
            raise TypeError("runtime fact is not canonically representable")
    return rows


def named_value_rows(values: dict[str, Any]) -> list[dict[str, JsonValue]]:
    return [
        {"name": name, "value": cast(JsonValue, values[name])}
        for name in sorted(values)
    ]


def resolved_display_names(
    declarations: dict[bytes, dict[str, Any]],
) -> dict[bytes, str]:
    counts: dict[str, int] = {}
    for declaration in declarations.values():
        name = cast(str, declaration["symbol"])
        counts[name] = counts.get(name, 0) + 1
    result: dict[bytes, str] = {}
    for identity, declaration in declarations.items():
        symbol = cast(dict[str, str], declaration["resolved_symbol"])
        name = cast(str, declaration["symbol"])
        result[identity] = (
            name
            if counts[name] == 1
            else f"{symbol['model']}:{symbol['module']}:{symbol['name']}"
        )
    return result


def resolved_state_rows(
    values: dict[bytes, Any], display_names: dict[bytes, str]
) -> list[dict[str, JsonValue]]:
    return [
        {"name": display_names[key], "value": cast(JsonValue, values[key])}
        for key in sorted(values, key=lambda item: display_names[item])
    ]


def resolved_value_rows(
    values: dict[bytes, Any],
    display_names: dict[bytes, str],
    structured_authority: StructuredValueIndex,
) -> list[dict[str, JsonValue]]:
    projected = {display_names[key]: value for key, value in values.items()}
    return value_rows(projected, structured_authority)


def metric_definition_identity(metric: dict[str, Any]) -> str:
    return content_identity(
        "metric-definition-v2",
        cast(
            JsonValue,
            {
                name: metric[name]
                for name in (
                    "id",
                    "kind",
                    "unit",
                    "dimensions",
                    "window",
                    "aggregation",
                    "replication",
                    "missing",
                    "censoring",
                    "observation",
                )
            },
        ),
    )


def runtime_profile_definition_identity(
    checked: CheckedExperiment, definition: dict[str, Any]
) -> str:
    contract = checked.runtime_profile_identity_contract
    if (
        not isinstance(contract, dict)
        or set(contract) != {"domain", "projection", "active_runtime"}
        or not isinstance(contract.get("domain"), str)
        or not contract["domain"]
        or contract.get("projection") != "complete-definition"
    ):
        raise ValueError("Kernel Runtime-profile-definition identity is incomplete")
    return content_identity(cast(str, contract["domain"]), cast(JsonValue, definition))


def canonical_metric_dataset(
    samples: Sequence[Mapping[str, JsonValue]],
) -> tuple[list[str], list[dict[str, JsonValue]]]:
    """Apply the Metric Dataset's declared identity and replication ordering."""

    def sample_key(sample: Mapping[str, JsonValue]) -> tuple[bytes, bytes]:
        return (
            cast(str, sample["metric_definition_identity"]).encode("utf-8"),
            cast(str, sample["replication_identity"]).encode("utf-8"),
        )

    ordered = [dict(sample) for sample in sorted(samples, key=sample_key)]
    identities = sorted(
        {cast(str, sample["metric_definition_identity"]) for sample in ordered},
        key=lambda identity: identity.encode("utf-8"),
    )
    return identities, ordered


@cache
def evaluator_build_identity() -> str:
    """Bind evaluator provenance to the installed Python source build."""
    source_names = sorted(
        name
        for name in list_package_resources("gda_balancing")
        if name.startswith("domain/") and name.endswith(".py")
    )
    source_bytes = [
        (
            name.removeprefix("domain/"),
            read_package_resource("gda_balancing", name),
        )
        for name in source_names
    ]
    sources: list[JsonValue] = [
        {
            "path": path,
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        }
        for path, data in source_bytes
    ]
    if not sources:
        raise RuntimeError("evaluator build contains no Python source")
    return content_identity("evaluator-build-v1", sources)


def evaluator_manifest(checked: CheckedExperiment) -> PublicationMember:
    """Project the evaluator's authority-derived capability manifest."""
    runtime = runtime_contract(checked)
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    reachable_nodes: set[str] = set()
    reachable_operations: set[OperationCoordinate] = set()
    for scenario in checked.value["scenarios"]:
        selected_entrypoints = [
            entrypoints[event["entrypoint"]]
            for event in scenario_transition_events(scenario)
        ]
        reachable = project_reachable_program_structure(
            checked.rir,
            selected_entrypoints,
        )
        reachable_nodes.update(reachable.runtime_node_ids)
        reachable_operations.update(reachable.operation_coordinates)
    nodes = sorted(
        row["id"]
        for row in runtime["nodes"]
        if row["id"] in reachable_nodes
        and row["semantics"]["operator"] in SUPPORTED_RUNTIME_OPERATORS
    )
    operations = selected_operation_index(checked.rir["selected_semantics"])
    # Effect IDs label the admitted Operation closure. Instruction support is
    # checked separately before dispatch; these labels add no host behavior.
    effects = sorted(
        {
            effect
            for coordinate in reachable_operations
            for effect in operations[coordinate]["effects"]
        }
    )
    supported_profiles = sorted(
        row["id"]
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if (
            row.get("evaluation") == runtime["version"]
            and row.get("runtime_program_version") == runtime["version"]
            and row.get("numeric_policy") == "exact-int64"
            and row.get("numeric_law") == runtime["numeric"]["id"]
            and row.get("rng")
            == {
                "algorithm": runtime["named_rng"]["algorithm"],
                "interval_sampling": runtime["named_rng"]["interval_sampling"][
                    "mapping"
                ],
                "bias_policy": runtime["named_rng"]["interval_sampling"]["bias_policy"],
            }
            and row.get("budget_scopes")
            == {
                "event_steps": "per-event-transaction",
                "logical_time": "per-event",
                "node_steps": "per-run",
                "operation_steps": "per-operation-invocation",
                "queue_events": "pending-and-provisional",
                "total_events": "per-scenario",
                "zero_time_depth": "per-descendant-chain",
            }
        )
    )
    build_identity = evaluator_build_identity()
    return artifact(
        checked,
        "evaluator-capability-manifest",
        {
            "evaluator_build_identity": build_identity,
            "implementation": EVALUATOR_IMPLEMENTATION,
            "platform": {
                "implementation": platform.python_implementation(),
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine() or "unknown",
            },
            "operation_kinds": ["event-fragment", "event-program", "pure-expression"],
            "instruction_nodes": nodes,
            "effects": effects,
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": [runtime["named_rng"]["algorithm"]],
            "runtime_profiles": supported_profiles,
        },
    )


def unsupported_evaluator_requirement(
    checked: CheckedExperiment, available: Mapping[str, Any]
) -> str | None:
    """Return the first required capability absent from a producer declaration."""
    required = checked.value["runtime"]["required_evaluator"]
    for member in (
        "operation_kinds",
        "instruction_nodes",
        "effects",
        "numeric_policies",
        "rng_algorithms",
        "runtime_profiles",
    ):
        if not set(required[member]) <= set(available[member]):
            return member
    return None


def resolved_runtime_profile(checked: CheckedExperiment) -> PublicationMember:
    """Identify the complete selected execution inputs without producer provenance."""
    profile_id = checked.value["runtime"]["profile"]
    definition = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == profile_id
    )
    return artifact(
        checked,
        "resolved-runtime-profile",
        {
            "experiment_identity": checked.content_identity,
            "rir_semantic_identity": checked.rir["semantic_identity"],
            "runtime_profile_definition_identity": runtime_profile_definition_identity(
                checked, definition
            ),
            "runtime_profile": deepcopy(definition),
        },
    )
