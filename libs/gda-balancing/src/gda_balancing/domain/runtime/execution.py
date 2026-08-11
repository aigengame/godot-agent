"""Deterministic Runtime execution and produced evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast
from gda_balancing.domain.authority.context import (
    packaged_authority_context,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
)
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    RuntimeLocation,
    Schema2RefusalReport,
)
from gda_balancing.domain.artifacts import (
    identified_artifact,
    wire_schema_identity,
)
from gda_balancing.domain.publication import PublicationMember
from gda_balancing.domain.runtime.scheduler import RuntimeScheduler
from gda_balancing.domain.experiment import (
    CheckedExperiment,
    _expanded_operation_body,
    _ordered_root_events_under,
    _refusal,
    _scenario_root_events,
)


_EVALUATOR_IMPLEMENTATION = "gda-balancing.deterministic-event-evaluator-v1"


_SUPPORTED_RUNTIME_OPERATORS = frozenset(
    {
        "copy-value",
        "cancel-event",
        "gameplay-precondition",
        "integer-add",
        "integer-compare",
        "integer-literal",
        "integer-maximum",
        "integer-multiply",
        "integer-subtract",
        "invoke-operation",
        "named-integer-draw",
        "select-value",
        "schedule-operation",
        "state-integer-subtract",
        "state-write",
    }
)


@dataclass(frozen=True)
class EvaluationArtifacts:
    members: dict[str, PublicationMember]
    accepted: bool
    failed_metrics: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeRefusalOutcome:
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
    last_state: dict[str, int]
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
    state_before: dict[str, int]
    state_after: dict[str, int]


class _RuntimeExecutionFault(Exception):
    def __init__(
        self,
        *,
        signal: str,
        operation: str,
        call_path: tuple[str, ...],
        call_site_identity: str | None,
        evaluation_site_identity: str | None,
        instruction_index: int | None,
    ) -> None:
        super().__init__(signal)
        self.signal = signal
        self.operation = operation
        self.call_path = call_path
        self.call_site_identity = call_site_identity
        self.evaluation_site_identity = evaluation_site_identity
        self.instruction_index = instruction_index


class _InitializationProgramFault(Exception):
    def __init__(
        self,
        *,
        signal: str,
        program: str,
        evaluation_site_identity: str,
        frame_identity: str,
    ) -> None:
        super().__init__(signal)
        self.signal = signal
        self.program = program
        self.evaluation_site_identity = evaluation_site_identity
        self.frame_identity = frame_identity


def _artifact(
    checked: CheckedExperiment,
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> PublicationMember:
    value = identified_artifact(
        checked.language_bundle,
        artifact_kind,
        payload,
    )
    return PublicationMember(
        value=value,
        artifact_kind=artifact_kind,
        wire_schema_identity=wire_schema_identity(
            checked.language_bundle, artifact_kind
        ),
        content_identity=cast(str, value["content_identity"]),
    )


def _runtime_contract(checked: CheckedExperiment) -> dict[str, Any]:
    return cast(dict[str, Any], checked.kernel["meta_format"]["runtime_program"])


def _runtime_execution_contract(checked: CheckedExperiment) -> dict[str, Any]:
    runtime = _runtime_contract(checked)
    return {
        member: cast(dict[str, Any], runtime[member])
        for member in ("runtime_configuration", "transition", "step")
    }


def _runtime_lifecycle_roles(checked: CheckedExperiment) -> dict[str, str]:
    configuration = _runtime_execution_contract(checked)["runtime_configuration"]
    return cast(dict[str, str], configuration["lifecycle_roles"])


def _runtime_boundary_roles(checked: CheckedExperiment) -> dict[str, str]:
    step = _runtime_execution_contract(checked)["step"]
    return cast(dict[str, str], step["boundary_roles"])


def _runtime_nodes(checked: CheckedExperiment) -> dict[str, dict[str, Any]]:
    return {
        row["id"]: row
        for row in cast(list[dict[str, Any]], _runtime_contract(checked)["nodes"])
    }


def _instruction_evaluation_sites(
    operation: dict[str, Any],
) -> dict[int, str]:
    extensions = operation.get("extensions")
    if not isinstance(extensions, dict):
        return {}
    provenance = extensions.get("standard.instruction-provenance")
    if (
        not isinstance(provenance, dict)
        or provenance.get("kind") != "instruction-evaluation-sites"
        or not isinstance(provenance.get("sites"), list)
    ):
        return {}
    return {
        cast(int, row["instruction_index"]): cast(str, row["evaluation_site_identity"])
        for row in cast(list[dict[str, Any]], provenance["sites"])
    }


def _operation_formula_slot(
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


def _operation_formula_evaluation_record(
    operation: dict[str, Any],
    binding: dict[str, Any],
    variables: dict[str, Any],
    *,
    evaluation_site_identity: str,
    frame_identity: JsonValue,
    call_path: tuple[str, ...],
) -> dict[str, JsonValue] | None:
    """Build the one canonical Formula-evaluation record shape."""
    binding_site = cast(dict[str, Any], binding["site"])
    slot = _operation_formula_slot(operation, cast(str, binding_site["slot"]))
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
            sorted(
                evaluated_arguments,
                key=lambda row: cast(str, row["parameter"]),
            ),
        ),
        "result": cast(JsonValue, variables[target]),
        "frame_identity": frame_identity,
        "call_path": "/".join(call_path),
    }


def _scheduler_contract(checked: CheckedExperiment) -> Mapping[str, Any]:
    return RuntimeScheduler.from_kernel(checked.kernel).contract


def _scenario_transition_events(scenario: dict[str, Any]) -> list[dict[str, Any]]:
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


def _pending_event_projection(event: dict[str, Any]) -> dict[str, JsonValue]:
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
                {
                    "name": name,
                    "target": _resolved_symbol_from_identity(identity),
                }
                for name, identity in sorted(
                    cast(dict[str, bytes], event["state_references"]).items()
                )
            ],
        ),
    }


def _runtime_journal_contract(checked: CheckedExperiment) -> dict[str, Any]:
    journal = _scheduler_contract(checked).get("runtime_journal")
    if not isinstance(journal, dict):
        raise ValueError("Kernel Runtime journal contract is absent")
    return cast(dict[str, Any], journal)


def _empty_runtime_journal_identity(contract: dict[str, Any]) -> str:
    return content_identity(cast(str, contract["domain"]), [])


def _extend_runtime_journal_identity(
    contract: dict[str, Any],
    previous_identity: str,
    record: dict[str, JsonValue],
) -> str:
    return content_identity(
        cast(str, contract["domain"]),
        cast(
            JsonValue,
            {
                "previous_identity": previous_identity,
                "record": record,
            },
        ),
    )


def _committed_event_projection(event: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        member: value
        for member, value in event.items()
        if member != "snapshot_after_identity"
    }


def _event_catalog_record(
    checked: CheckedExperiment,
    scenario_id: str,
    event: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    contract = _runtime_journal_contract(checked)["event_spec"]
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
                cast(str, contract["domain"]),
                cast(JsonValue, event_spec),
            ),
        },
    )


def _runtime_continuation(
    checked: CheckedExperiment,
    *,
    lifecycle_state: str,
    step_boundary: str | None,
    scenario_cursor: int,
    event_catalog_count: int,
    event_catalog_identity: str,
    pending_event_count: int,
    committed_event_count: int,
    committed_trace_identity: str,
    snapshot_index: int,
    event_id: str | None,
    logical_time: int | None,
    rng: _NamedRng,
    event_steps: int,
    node_steps: int,
    admitted_event_count: int,
    next_enqueue_sequence: int,
    root_event_map_identity: str,
    resolved_runtime_profile_identity: str,
) -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        {
            "lifecycle_state": lifecycle_state,
            "step_boundary": step_boundary,
            "scenario_cursor": scenario_cursor,
            "event_catalog": {
                "count": event_catalog_count,
                "prefix_identity": event_catalog_identity,
            },
            "pending_event_count": pending_event_count,
            "committed_trace": {
                "count": committed_event_count,
                "prefix_identity": committed_trace_identity,
            },
            "current_snapshot": {
                "index": snapshot_index,
                "event_id": event_id,
                "logical_time": logical_time,
            },
            "rng": rng.continuation(),
            "resource_ledger": {
                "event_steps": event_steps,
                "node_steps": node_steps,
                "queue_events": pending_event_count,
                "total_events": admitted_event_count,
            },
            "next_enqueue_sequence": next_enqueue_sequence,
            "root_event_map_identity": root_event_map_identity,
            "resolved_runtime_profile_identity": resolved_runtime_profile_identity,
        },
    )


def _runtime_step_boundary(
    checked: CheckedExperiment,
    *,
    active_logical_time: int,
    pending_events: list[dict[str, Any]],
    event_position: int,
    terminal_maximum: int | None,
) -> str | None:
    contract = _runtime_execution_contract(checked)["step"]
    stops = cast(list[str], contract["stop"])
    boundary_roles = _runtime_boundary_roles(checked)
    if not pending_events:
        terminal = boundary_roles["terminal"]
        return terminal if terminal in stops else None
    scheduler = RuntimeScheduler(_scheduler_contract(checked))
    next_event = min(
        pending_events,
        key=scheduler.ordering_key,
    )
    at_step_boundary = next_event["logical_time"] != active_logical_time
    if (
        terminal_maximum is not None
        and event_position >= terminal_maximum
        and at_step_boundary
    ):
        terminal = boundary_roles["terminal"]
        return terminal if terminal in stops else None
    if next_event["logical_time"] != active_logical_time:
        logical = boundary_roles["logical"]
        return logical if logical in stops else None
    return None


def _ordered_root_events(
    checked: CheckedExperiment,
    scenario: dict[str, Any],
) -> list[dict[str, Any]]:
    return _ordered_root_events_under(_scheduler_contract(checked), scenario)


def _root_event_id(
    checked: CheckedExperiment,
    scenario_id: str,
    event: dict[str, Any],
) -> str:
    scheduler = _scheduler_contract(checked)
    identity = cast(dict[str, Any], scheduler["event_identity"])
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


def _scheduled_event_id(
    checked: CheckedExperiment,
    scenario_id: str,
    event: dict[str, Any],
) -> str:
    scheduler = _scheduler_contract(checked)
    identity = cast(dict[str, Any], scheduler["event_identity"])
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


def _observation_event_id(
    checked: CheckedExperiment,
    scenario_id: str,
    metric_definition_identity: str,
    *,
    logical_time: int,
    enqueue_sequence: int,
) -> str:
    scheduler = _scheduler_contract(checked)
    identity = cast(dict[str, Any], scheduler["event_identity"])
    observation = cast(dict[str, Any], scheduler["observation"])
    return _projected_runtime_identity(
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


def _projected_runtime_identity(
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


def _external_input_identity(
    checked: CheckedExperiment,
    scenario_id: str,
    event: dict[str, Any],
) -> str:
    return _projected_runtime_identity(
        _scheduler_contract(checked)["external_input_identity"],
        {
            "experiment_identity": checked.content_identity,
            "scenario_id": scenario_id,
            "root_event_ref": event["root_event_ref"],
            "source_identity": event["source_identity"],
            "source_sequence": event["source_sequence"],
            "facts": cast(JsonValue, event["facts"]),
        },
    )


def _diagnostic_for_signal(checked: CheckedExperiment, signal: str, stage: str) -> str:
    matches = [
        reason["diagnostic"]
        for reason in checked.language_bundle["language"]["reasons"]
        if reason.get("signal") == signal and reason.get("stage") == stage
    ]
    if len(matches) != 1:
        raise ValueError(f"admitted Diagnostic signal is not unique: {signal}")
    return cast(str, matches[0])


def _admit_numeric(value: int, numeric: dict[str, Any]) -> int:
    if value < numeric["minimum"] or value > numeric["maximum"]:
        raise OverflowError("exact-int64 arithmetic overflow")
    return value


def _admit_declared_numeric(
    value: int,
    numeric: dict[str, Any],
    declaration: dict[str, Any],
) -> int:
    admitted = _admit_numeric(value, numeric)
    if declaration["domain_kind"] == "closed-interval":
        domain = cast(dict[str, int], declaration["domain"])
        if not domain["minimum"] <= admitted <= domain["maximum"]:
            raise OverflowError("value is outside its declared numeric domain")
    return admitted


def _integer_compare(comparison: str, left: int, right: int) -> bool:
    if comparison == "greater-than-or-equal":
        return left >= right
    if comparison == "less-than":
        return left < right
    if comparison == "less-than-or-equal":
        return left <= right
    raise ValueError("unsupported admitted integer comparison")


class _NamedRng:
    def __init__(self, seed: int, contract: dict[str, Any]) -> None:
        if (
            contract["algorithm"] != "splitmix64-v1"
            or contract["word_bits"] != 64
            or contract["seed_encoding"] != "unsigned-modulo-2^64"
            or contract["candidate_encoding"]
            != {
                "alphabet": "0123456789abcdef",
                "case": "lowercase",
                "radix": 16,
                "width_bits": 64,
                "zero_pad": True,
            }
        ):
            raise ValueError("unsupported admitted Named-stream RNG contract")
        self._contract = contract
        self._mask = (1 << contract["word_bits"]) - 1
        self._seed = seed & self._mask
        self._states: dict[str, int] = {}
        self._indices: dict[str, int] = {}

    def snapshot(self) -> tuple[dict[str, int], dict[str, int]]:
        return dict(self._states), dict(self._indices)

    def restore(self, snapshot: tuple[dict[str, int], dict[str, int]]) -> None:
        states, indices = snapshot
        self._states = dict(states)
        self._indices = dict(indices)

    def continuation(self) -> list[dict[str, JsonValue]]:
        width = self._contract["word_bits"] // 4
        return [
            {
                "stream": stream,
                "state_hex": f"{self._states[stream]:0{width}x}",
                "next_index": self._indices[stream],
            }
            for stream in sorted(self._states)
        ]

    def encode_candidate(self, candidate: int) -> str:
        width = self._contract["candidate_encoding"]["width_bits"] // 4
        return f"{candidate:0{width}x}"

    def draw(
        self, stream: str, minimum: int, maximum: int
    ) -> tuple[int, int, int, bool]:
        if minimum > maximum:
            raise ValueError("invalid deterministic draw interval")
        if stream not in self._states:
            derivation = self._contract["stream_derivation"]
            if (
                derivation["hash"] != "sha256"
                or self._contract["stream_name_encoding"] != "utf-8"
                or derivation["combine"] != "unsigned-add-modulo-2^64"
            ):
                raise ValueError("unsupported admitted Named-stream derivation")
            digest = hashlib.sha256(stream.encode("utf-8")).digest()
            digest_slice = derivation["digest_slice"]
            start = digest_slice["offset"]
            end = start + digest_slice["length"]
            self._states[stream] = (
                self._seed
                + int.from_bytes(
                    digest[start:end],
                    derivation["byte_order"],
                )
            ) & self._mask
            self._indices[stream] = 0
        transition = self._contract["state_transition"]
        state = (
            self._states[stream] + int(transition["increment_hex"], 16)
        ) & self._mask
        self._states[stream] = state
        mixed = state
        for step in transition["mix_steps"]:
            mixed ^= mixed >> step["xor_shift_right"]
            if "multiply_hex" in step:
                mixed = (mixed * int(step["multiply_hex"], 16)) & self._mask
        index = self._indices[stream]
        self._indices[stream] = index + 1
        sampling = self._contract["interval_sampling"]
        if (
            sampling["bounds"] != "inclusive"
            or sampling["mapping"] != "unsigned-modulo-width"
            or sampling["bias_policy"] != "accepted-modulo-bias-v1"
            or sampling["candidates_per_draw"] != 1
        ):
            raise ValueError("unsupported admitted interval-sampling law")
        return minimum + mixed % (maximum - minimum + 1), index, mixed, True


def _value_rows(values: dict[str, Any]) -> list[dict[str, JsonValue]]:
    rows: list[dict[str, JsonValue]] = []
    for name in sorted(values):
        value = values[name]
        if isinstance(value, bool):
            rows.append({"name": name, "kind": "boolean", "boolean": value})
        elif isinstance(value, int):
            rows.append({"name": name, "kind": "integer", "integer": value})
        elif isinstance(value, str):
            rows.append({"name": name, "kind": "string", "string": value})
        else:
            raise TypeError("runtime fact is not canonically representable")
    return rows


def _int_rows(values: dict[str, int]) -> list[dict[str, JsonValue]]:
    return [{"name": name, "value": values[name]} for name in sorted(values)]


def _resolved_display_names(
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


def _resolved_int_rows(
    values: dict[bytes, int],
    display_names: dict[bytes, str],
) -> list[dict[str, JsonValue]]:
    projected = {display_names[key]: value for key, value in values.items()}
    return _int_rows(projected)


def _resolved_value_rows(
    values: dict[bytes, Any],
    display_names: dict[bytes, str],
) -> list[dict[str, JsonValue]]:
    projected = {display_names[key]: value for key, value in values.items()}
    return _value_rows(projected)


def _metric_definition_identity(metric: dict[str, Any]) -> str:
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


def _runtime_profile_definition_identity(
    checked: CheckedExperiment,
    definition: dict[str, Any],
) -> str:
    contract = checked.kernel["meta_format"].get("runtime_profile_definition")
    if (
        not isinstance(contract, dict)
        or set(contract) != {"domain", "projection", "active_runtime"}
        or not isinstance(contract.get("domain"), str)
        or not contract["domain"]
        or contract.get("projection") != "complete-definition"
    ):
        raise ValueError("Kernel Runtime-profile-definition identity is incomplete")
    return content_identity(
        cast(str, contract["domain"]),
        cast(JsonValue, definition),
    )


def _canonical_metric_dataset(
    samples: Sequence[Mapping[str, JsonValue]],
) -> tuple[list[str], list[dict[str, JsonValue]]]:
    """Apply the Metric Dataset's declared identity/replication ordering."""

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
def _evaluator_build_identity(root: Path | None = None) -> str:
    """Bind evaluator provenance to the installed Python source build."""
    package_root = root or Path(__file__).parents[1]
    sources: list[JsonValue] = []
    for source in sorted(package_root.rglob("*.py")):
        sources.append(
            {
                "path": source.relative_to(package_root).as_posix(),
                "sha256": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    if not sources:
        raise RuntimeError("evaluator build contains no Python source")
    return content_identity("evaluator-build-v1", sources)


def _evaluator_manifest(checked: CheckedExperiment) -> PublicationMember:
    runtime_contract = _runtime_contract(checked)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    reachable_nodes = {
        instruction["node"]
        for scenario in checked.value["scenarios"]
        for event in _scenario_transition_events(scenario)
        for instruction in _expanded_operation_body(
            operations[entrypoints[event["entrypoint"]]["operation"]["id"]],
            operations,
        )
    }
    nodes = sorted(
        row["id"]
        for row in runtime_contract["nodes"]
        if row["id"] in reachable_nodes
        and row["semantics"]["operator"] in _SUPPORTED_RUNTIME_OPERATORS
    )
    supported_profiles = sorted(
        row["id"]
        for row in checked.language_bundle["language"]["runtime_profiles"]
        if (
            row.get("evaluation") == runtime_contract["version"]
            and row.get("runtime_program_version") == runtime_contract["version"]
            and row.get("numeric_policy") == "exact-int64"
            and row.get("numeric_law") == runtime_contract["numeric"]["id"]
            and row.get("rng")
            == {
                "algorithm": runtime_contract["named_rng"]["algorithm"],
                "interval_sampling": runtime_contract["named_rng"]["interval_sampling"][
                    "mapping"
                ],
                "bias_policy": runtime_contract["named_rng"]["interval_sampling"][
                    "bias_policy"
                ],
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
            and set(row["effects"])
            <= {
                "event.cancel",
                "event.commit",
                "event.schedule",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            }
        )
    )
    build_identity = _evaluator_build_identity()
    implementation_identity = content_identity(
        "evaluator-implementation-v1",
        {
            "implementation": _EVALUATOR_IMPLEMENTATION,
            "evaluator_build_identity": build_identity,
            "runtime_program_version": runtime_contract["version"],
            "operation_kinds": ["event-fragment", "event-program"],
            "instruction_nodes": nodes,
            "effects": [
                "event.cancel",
                "event.commit",
                "event.schedule",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            ],
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": [runtime_contract["named_rng"]["algorithm"]],
            "runtime_profiles": supported_profiles,
        },
    )
    return _artifact(
        checked,
        "evaluator-capability-manifest",
        {
            "evaluator_build_identity": build_identity,
            "implementation_identity": implementation_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "operation_kinds": ["event-fragment", "event-program"],
            "instruction_nodes": nodes,
            "effects": [
                "event.cancel",
                "event.commit",
                "event.schedule",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            ],
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": [runtime_contract["named_rng"]["algorithm"]],
            "runtime_profiles": supported_profiles,
        },
    )


def _resolved_runtime_profile(
    checked: CheckedExperiment, evaluator: PublicationMember
) -> PublicationMember:
    profile_id = checked.value["runtime"]["profile"]
    definition = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == profile_id
    )
    definition_identity = _runtime_profile_definition_identity(checked, definition)
    return _artifact(
        checked,
        "resolved-runtime-profile",
        {
            "experiment_identity": checked.content_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": checked.package_lock["content_identity"],
            "resolved_model_identity": checked.resolved_model["content_identity"],
            "rir_identity": checked.rir["content_identity"],
            "evaluator_manifest_identity": evaluator.content_identity,
            "runtime_profile_definition_identity": definition_identity,
            "runtime_profile": {
                "id": definition["id"],
                "version": definition["version"],
                "evaluation": definition["evaluation"],
                "numeric_policy": definition["numeric_policy"],
                "runtime_program_version": definition["runtime_program_version"],
                "numeric_law": definition["numeric_law"],
                "rng": definition["rng"],
                "budget_scopes": definition["budget_scopes"],
                "effects": definition["effects"],
                "resource_bounds": definition["resource_bounds"],
            },
            "rng_algorithm": checked.value["seed"]["algorithm"],
            "platform": {
                "implementation": platform.python_implementation(),
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine() or "unknown",
            },
        },
    )


def _formula_snapshot_identity_domain(checked: CheckedExperiment) -> str:
    profile_id = checked.value["runtime"]["profile"]
    definition = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == profile_id
    )
    extensions = definition.get("extensions")
    formula = (
        extensions.get("standard.formula") if isinstance(extensions, dict) else None
    )
    domain = (
        formula.get("snapshot_identity_domain") if isinstance(formula, dict) else None
    )
    if not isinstance(domain, str) or not domain:
        raise ValueError("Runtime profile declares no Formula Snapshot identity domain")
    if domain != _scheduler_contract(checked)["snapshot_identity"]["domain"]:
        raise ValueError("Runtime profile and Kernel disagree on Snapshot identity")
    return domain


def _check_evaluator_requirements(
    checked: CheckedExperiment, evaluator: PublicationMember
) -> Schema2RefusalReport | None:
    required = checked.value["runtime"]["required_evaluator"]
    available = evaluator.value
    for member in (
        "operation_kinds",
        "instruction_nodes",
        "effects",
        "numeric_policies",
        "rng_algorithms",
        "runtime_profiles",
    ):
        if not set(required[member]) <= set(available[member]):
            return _refusal(
                stage="resolution",
                code=_diagnostic_for_signal(
                    checked, "capability-unsupported", "resolution"
                ),
                identity=checked.content_identity,
                pointer=f"/runtime/required_evaluator/{member}",
                message=f"Evaluator does not provide every required {member}",
            )
    return None


def _reproduction_receipt(
    checked: CheckedExperiment,
    evaluator: PublicationMember,
    resolved_runtime: PublicationMember,
) -> PublicationMember:
    external_input_identities = [
        {
            "scenario": scenario["id"],
            "root_event_ref": event["root_event_ref"],
            "source_identity": event["source_identity"],
            "source_sequence": event["source_sequence"],
            "input_identity": _external_input_identity(checked, scenario["id"], event),
        }
        for scenario in checked.value["scenarios"]
        for event in _scenario_root_events(scenario)
        if event["kind"] == "external-input"
    ]
    return _artifact(
        checked,
        "reproduction-receipt",
        {
            "experiment_identity": checked.content_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": checked.package_lock["content_identity"],
            "resolved_model_identity": checked.resolved_model["content_identity"],
            "rir_identity": checked.rir["content_identity"],
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "evaluator_manifest_identity": evaluator.content_identity,
            "seed_algorithm": checked.value["seed"]["algorithm"],
            "seed_value": checked.value["seed"]["value"],
            "external_input_identities": cast(JsonValue, external_input_identities),
        },
    )


def _scenario_state(
    scenario: dict[str, Any],
    declarations: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return {
        row["name"]: row["value"]
        for row in scenario["values"]
        if declarations[row["name"]]["role"] == "state"
    }


def _execute_value_instruction(
    instruction: dict[str, Any],
    variables: dict[str, Any],
    numeric: dict[str, Any],
    node_contract: dict[str, Any],
) -> None:
    """Execute one value instruction through its Kernel-owned operator law."""
    semantics = cast(dict[str, Any], node_contract["semantics"])
    operator = cast(str, semantics["operator"])
    if operator == "integer-literal":
        value = cast(int, instruction["literal"])
    elif operator == "copy-value":
        value = variables[cast(str, instruction["value"])]
    elif operator in {
        "integer-add",
        "integer-subtract",
        "integer-multiply",
        "integer-maximum",
    }:
        left = variables[cast(str, instruction["left"])]
        right = variables[cast(str, instruction["right"])]
        value = (
            left + right
            if operator == "integer-add"
            else left - right
            if operator == "integer-subtract"
            else left * right
            if operator == "integer-multiply"
            else max(left, right)
        )
    elif operator == "integer-compare":
        variables[cast(str, instruction["target"])] = _integer_compare(
            cast(str, semantics["comparison"]),
            variables[cast(str, instruction["left"])],
            variables[cast(str, instruction["right"])],
        )
        return
    elif operator == "select-value":
        value = variables[
            cast(
                str,
                instruction[
                    "when_true"
                    if variables[cast(str, instruction["condition"])]
                    else "when_false"
                ],
            )
        ]
    else:
        raise ValueError(f"Kernel operator is not a value instruction: {operator}")
    variables[cast(str, instruction["target"])] = _admit_numeric(value, numeric)


def _evaluate_value_program_vector(
    vector: dict[str, Any],
) -> dict[str, JsonValue]:
    """Execute one package-owned generic value-program conformance vector."""
    inp = cast(dict[str, Any], vector["input"])
    numeric = cast(dict[str, Any], inp["numeric"])
    instructions = cast(list[dict[str, Any]], inp["instructions"])
    operands = {
        cast(str, row["name"]): cast(int, row["value"])
        for row in cast(list[dict[str, Any]], inp["operands"])
    }
    cache: dict[bytes, int] = {}
    runtime_nodes = {
        cast(str, row["id"]): row
        for row in cast(
            list[dict[str, Any]],
            packaged_authority_context().kernel["meta_format"]["runtime_program"][
                "nodes"
            ],
        )
    }
    charge = 0
    result_value: int | None = None
    signal: str | None = None
    refusing_site = cast(str, inp["site"])
    for _evaluation in range(cast(int, inp["evaluations"])):
        charge += len(instructions)
        if charge > cast(int, inp["resource_limit"]):
            signal = "step-limit"
            result_value = None
            break
        cache_key = canonical_bytes(
            cast(
                JsonValue,
                {
                    "instructions": instructions,
                    "numeric": numeric,
                    "operands": [
                        {"name": name, "value": value}
                        for name, value in sorted(operands.items())
                    ],
                    "result": inp["result"],
                    "site": inp["site"],
                },
            )
        )
        if cast(bool, inp["cache"]) and cache_key in cache:
            result_value = cache[cache_key]
            continue
        values = dict(operands)
        for row in instructions:
            try:
                _execute_value_instruction(
                    cast(dict[str, Any], row["instruction"]),
                    values,
                    numeric,
                    runtime_nodes[cast(str, row["instruction"]["node"])],
                )
            except OverflowError:
                signal = "numeric-overflow"
                refusing_site = cast(str, row["evaluation_site_identity"])
                result_value = None
                break
        if signal is not None:
            break
        result_value = values[cast(str, inp["result"])]
        if cast(bool, inp["cache"]):
            cache[cache_key] = result_value
    admitted = signal is None
    return {
        "cache_entries": len(cache),
        "charge": charge,
        "outcome": "admitted" if admitted else "refused",
        "result": result_value,
        "result_artifact": admitted,
        "signal": signal,
        "site": cast(str, inp["site"]) if admitted else refusing_site,
    }


def _formula_programs_reachable_from_entrypoints(
    checked: CheckedExperiment,
    selected_entrypoints: Sequence[dict[str, Any]],
    *,
    phase: str,
) -> list[dict[str, Any]]:
    """Project one lifecycle phase to the sites selected by a Scenario."""
    programs = [
        program
        for program in cast(
            list[dict[str, Any]], checked.rir["initialization_programs"]
        )
        if cast(dict[str, Any], program["site"])["context"]["phase"] == phase
    ]
    reachable_targets = {
        canonical_bytes(cast(JsonValue, operand["symbol"]))
        for entrypoint in selected_entrypoints
        for binding in cast(list[dict[str, Any]], entrypoint["arguments"])
        if (operand := cast(dict[str, Any], binding["operand"]))["kind"] == "symbol"
    }
    while True:
        previous_targets = len(reachable_targets)
        for program in programs:
            target = canonical_bytes(cast(JsonValue, program["target"]))
            if target not in reachable_targets:
                continue
            reachable_targets.update(
                canonical_bytes(cast(JsonValue, operand["resolved_symbol"]))
                for row in cast(list[dict[str, Any]], program["inputs"])
                if (operand := cast(dict[str, Any], row["operand"]))["kind"]
                != "literal"
            )
        if len(reachable_targets) == previous_targets:
            break
    return [
        program
        for program in programs
        if canonical_bytes(cast(JsonValue, program["target"])) in reachable_targets
    ]


def _evaluate_initialization_programs(
    checked: CheckedExperiment,
    actual_values: dict[bytes, int],
    *,
    consumed_steps: int,
    runtime_limit: int,
    cache: dict[bytes, int] | None,
    selected_entrypoints: Sequence[dict[str, Any]],
    frame_token: JsonValue | None = None,
    frame_identity: str | None = None,
    phase: str = "initialization",
) -> int:
    """Evaluate closed generic programs in one authority-owned lifecycle frame."""
    programs = _formula_programs_reachable_from_entrypoints(
        checked,
        selected_entrypoints,
        phase=phase,
    )
    if not programs:
        return consumed_steps
    # A selected site can still depend on an explicit input absent from this
    # Scenario. Remove that open branch and every dependent branch, but keep a
    # closed cycle intact so the evaluator's invariant guard can reject it.
    available_identities = set(actual_values)
    while programs:
        program_targets = {
            canonical_bytes(cast(JsonValue, program["target"])) for program in programs
        }
        closed_programs = [
            program
            for program in programs
            if {
                canonical_bytes(cast(JsonValue, operand["resolved_symbol"]))
                for row in cast(list[dict[str, Any]], program["inputs"])
                if (operand := cast(dict[str, Any], row["operand"]))["kind"]
                != "literal"
            }
            <= available_identities | program_targets
        ]
        if len(closed_programs) == len(programs):
            break
        programs = closed_programs
    if not programs:
        return consumed_steps
    program_targets = {
        canonical_bytes(cast(JsonValue, program["target"])) for program in programs
    }
    numeric = cast(dict[str, Any], _runtime_contract(checked)["numeric"])
    runtime_nodes = _runtime_nodes(checked)
    if frame_identity is None:
        if phase != "initialization":
            raise ValueError(
                "observation requires an exact committed Snapshot identity"
            )
        frame_identity = content_identity(
            "initialization-frame-v2",
            cast(
                JsonValue,
                {
                    "token": frame_token,
                    "values": [
                        {
                            "symbol": identity.decode("utf-8").rstrip("\n"),
                            "value": value,
                        }
                        for identity, value in sorted(actual_values.items())
                        if identity not in program_targets
                    ],
                },
            ),
        )
    pending = list(programs)
    while pending:
        progressed = False
        for program in list(pending):
            input_values: dict[str, int] = {}
            ready = True
            for row in cast(list[dict[str, Any]], program["inputs"]):
                operand = cast(dict[str, Any], row["operand"])
                if operand["kind"] == "literal":
                    value = cast(int, operand["value"])
                else:
                    identity = canonical_bytes(
                        cast(JsonValue, operand["resolved_symbol"])
                    )
                    if identity not in actual_values:
                        ready = False
                        break
                    value = actual_values[identity]
                input_values[cast(str, row["name"])] = value
            if not ready:
                continue
            charge = cast(
                int,
                cast(dict[str, Any], program["resource_bounds"])["max_steps"],
            )
            consumed_steps += charge
            if consumed_steps > runtime_limit:
                raise _InitializationProgramFault(
                    signal="step-limit",
                    program=cast(str, program["identity"]),
                    evaluation_site_identity=cast(
                        str, cast(dict[str, Any], program["site"])["identity"]
                    ),
                    frame_identity=frame_identity,
                )
            cache_key = canonical_bytes(
                cast(
                    JsonValue,
                    {
                        "program": program["identity"],
                        "site": cast(dict[str, Any], program["site"])["identity"],
                        "frame": frame_identity,
                        "operands": [
                            {"name": name, "value": value}
                            for name, value in sorted(input_values.items())
                        ],
                        "numeric": numeric,
                    },
                )
            )
            if cache is not None and cache_key in cache:
                result_value = cache[cache_key]
            else:
                variables = dict(input_values)
                for row in cast(list[dict[str, Any]], program["body"]):
                    try:
                        _execute_value_instruction(
                            cast(dict[str, Any], row["instruction"]),
                            variables,
                            numeric,
                            runtime_nodes[cast(str, row["instruction"]["node"])],
                        )
                    except OverflowError as error:
                        raise _InitializationProgramFault(
                            signal="numeric-overflow",
                            program=cast(str, program["identity"]),
                            evaluation_site_identity=cast(
                                str, row["evaluation_site_identity"]
                            ),
                            frame_identity=frame_identity,
                        ) from error
                result = cast(dict[str, Any], program["result"])
                result_value = _admit_numeric(
                    variables[cast(str, result["name"])],
                    numeric,
                )
                if cache is not None:
                    cache[cache_key] = result_value
            target = canonical_bytes(cast(JsonValue, program["target"]))
            actual_values[target] = result_value
            pending.remove(program)
            progressed = True
        if not progressed:
            raise ValueError("admitted initialization program graph is cyclic")
    return consumed_steps


def _runtime_refusal_outcome(
    checked: CheckedExperiment,
    *,
    scenario_id: str,
    scenario_index: int,
    code: str,
    message: str,
    events: list[dict[str, JsonValue]],
    event_catalog: list[dict[str, JsonValue]],
    root_event_map: list[dict[str, JsonValue]],
    terminal_condition: dict[str, JsonValue],
    last_snapshot_identity: str,
    last_snapshot_record: dict[str, JsonValue],
    budget_counters: dict[str, int],
    entrypoint_id: str,
    entrypoint_identity: str,
    operation: str,
    call_path: tuple[str, ...],
    call_site_identity: str | None,
    evaluation_site_identity: str | None,
    instruction_index: int | None,
    refusing_event_id: str,
    refusing_event_spec: dict[str, JsonValue],
    refusing_attempted_calls: list[dict[str, JsonValue]],
    refusing_ordering_key: dict[str, JsonValue],
    refusing_snapshot_before_identity: str,
    state_before: dict[str, int],
) -> RuntimeRefusalOutcome:
    report = _refusal(
        stage="runtime",
        variant="post-dispatch",
        code=code,
        identity=checked.content_identity,
        pointer=f"/scenarios/{scenario_index}/entrypoint",
        message=message,
    )
    return RuntimeRefusalOutcome(
        report=report,
        scenario_id=scenario_id,
        scenario_index=scenario_index,
        committed_trace_prefix=tuple(dict(event) for event in events),
        event_catalog_prefix=tuple(deepcopy(record) for record in event_catalog),
        root_event_map=tuple(dict(row) for row in root_event_map),
        terminal_condition=dict(terminal_condition),
        last_snapshot_identity=last_snapshot_identity,
        last_snapshot_record=deepcopy(last_snapshot_record),
        budget_counters=dict(budget_counters),
        last_state=dict(state_before),
        refusing_event_index=len(events),
        refusing_event_id=refusing_event_id,
        refusing_event_spec=deepcopy(refusing_event_spec),
        refusing_attempted_calls=tuple(
            deepcopy(call) for call in refusing_attempted_calls
        ),
        refusing_ordering_key=dict(refusing_ordering_key),
        refusing_snapshot_before_identity=refusing_snapshot_before_identity,
        refusing_entrypoint_id=entrypoint_id,
        refusing_entrypoint_identity=entrypoint_identity,
        refusing_operation=operation,
        refusing_call_path="/".join(call_path),
        refusing_call_site_identity=call_site_identity,
        refusing_evaluation_site_identity=evaluation_site_identity,
        refusing_instruction_index=instruction_index,
        state_before=dict(state_before),
        state_after=dict(state_before),
    )


def evaluate_experiment(
    checked: CheckedExperiment,
) -> EvaluationArtifacts | RuntimeRefusalOutcome | Schema2RefusalReport:
    """Evaluate one checked deterministic-event Experiment without publishing."""
    evaluator = _evaluator_manifest(checked)
    capability_refusal = _check_evaluator_requirements(checked, evaluator)
    if capability_refusal is not None:
        return capability_refusal
    resolved_runtime = _resolved_runtime_profile(checked, evaluator)
    runtime_profile = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == checked.value["runtime"]["profile"]
    )
    runtime_bounds = cast(dict[str, int], runtime_profile["resource_bounds"])
    _runtime_execution_contract(checked)
    _formula_snapshot_identity_domain(checked)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    declarations = {
        canonical_bytes(cast(JsonValue, row["resolved_symbol"])): row
        for row in checked.rir["declarations"]
    }
    display_names = _resolved_display_names(declarations)
    call_sites = {
        (
            cast(dict[str, str], row["parent_operation"])["id"],
            row["site"],
        ): row
        for row in checked.rir["call_sites"]
    }
    formula_bindings_by_site = {
        cast(str, cast(dict[str, Any], binding["site"])["identity"]): binding
        for binding in cast(list[dict[str, Any]], checked.rir["formula_bindings"])
        if cast(dict[str, Any], binding["site"])["kind"] == "operation-slot"
    }
    runtime_contract = _runtime_contract(checked)
    numeric = cast(dict[str, Any], runtime_contract["numeric"])
    node_contracts = _runtime_nodes(checked)
    events: list[dict[str, JsonValue]] = []
    snapshots: list[dict[str, JsonValue]] = []
    event_catalog: list[dict[str, JsonValue]] = []
    root_event_map: list[dict[str, JsonValue]] = []
    terminal_statuses: list[dict[str, JsonValue]] = []
    scenario_observation_evidence: dict[tuple[str, str], tuple[str, str, int]] = {}
    scenario_event_outputs: dict[
        str, list[tuple[dict[str, Any], dict[str, int], str]]
    ] = {}
    scenario_terminal_states: dict[str, dict[str, int]] = {}
    total_steps = 0
    runtime_limit = runtime_bounds["max_node_steps"]
    initialization_cache: dict[bytes, int] = {}
    scheduler = _scheduler_contract(checked)
    runtime_scheduler = RuntimeScheduler(scheduler)
    root_events_by_scenario: dict[str, list[dict[str, Any]]] = {}
    root_event_ids_by_scenario: dict[str, dict[str, str]] = {}
    for scenario in checked.value["scenarios"]:
        ordered_events = _ordered_root_events(checked, scenario)
        for root_event in ordered_events:
            root_event["event_id"] = _root_event_id(checked, scenario["id"], root_event)
        root_events_by_scenario[scenario["id"]] = ordered_events
        root_event_ids_by_scenario[scenario["id"]] = {
            cast(str, root_event["root_event_ref"]): cast(str, root_event["event_id"])
            for root_event in ordered_events
        }
        root_event_map.extend(
            {
                "scenario": scenario["id"],
                "root_event_ref": root_event["root_event_ref"],
                "event_id": root_event["event_id"],
            }
            for root_event in sorted(
                ordered_events, key=lambda event: event["enqueue_sequence"]
            )
        )
    journal_contract = _runtime_journal_contract(checked)
    root_event_map_identity = content_identity(
        cast(str, journal_contract["root_event_map"]["domain"]),
        cast(JsonValue, root_event_map),
    )
    for scenario_index, scenario in enumerate(checked.value["scenarios"]):
        ordered_events = root_events_by_scenario[scenario["id"]]
        if len(ordered_events) > runtime_bounds["max_queue_events"]:
            return _refusal(
                stage="runtime",
                variant="pre-event",
                code=_diagnostic_for_signal(checked, "queue-limit", "runtime"),
                identity=checked.content_identity,
                pointer=f"/scenarios/{scenario_index}/event_plan",
                message="Authored root Events exceed the Runtime queue bound",
            )
        if any(
            event["logical_time"] > runtime_bounds["max_logical_time"]
            for event in ordered_events
        ):
            return _refusal(
                stage="runtime",
                variant="pre-event",
                code=_diagnostic_for_signal(checked, "logical-time-limit", "runtime"),
                identity=checked.content_identity,
                pointer=f"/scenarios/{scenario_index}/event_plan",
                message="Authored root Event exceeds the Runtime logical-time bound",
            )
        if len(ordered_events) > runtime_bounds["max_total_events"]:
            return _refusal(
                stage="runtime",
                variant="pre-event",
                code=_diagnostic_for_signal(checked, "event-limit", "runtime"),
                identity=checked.content_identity,
                pointer=f"/scenarios/{scenario_index}/event_plan",
                message="Authored root Events exceed the Runtime total-Event bound",
            )
    for scenario_index, scenario in enumerate(checked.value["scenarios"]):
        ordered_events = root_events_by_scenario[scenario["id"]]
        rng = _NamedRng(
            checked.value["seed"]["value"],
            cast(dict[str, Any], runtime_contract["named_rng"]),
        )
        admitted_event_count = len(ordered_events)
        next_enqueue_sequence = len(ordered_events)
        scenario_event_catalog = [
            _event_catalog_record(
                checked,
                scenario["id"],
                _pending_event_projection(root_event),
            )
            for root_event in ordered_events
        ]
        event_catalog.extend(scenario_event_catalog)
        event_catalog_identity = _empty_runtime_journal_identity(
            journal_contract["event_catalog"]
        )
        for record in scenario_event_catalog:
            event_catalog_identity = _extend_runtime_journal_identity(
                journal_contract["event_catalog"],
                event_catalog_identity,
                record,
            )
        committed_event_count = 0
        committed_trace_identity = _empty_runtime_journal_identity(
            journal_contract["committed_trace"]
        )
        event_steps = 0
        root_step_limit = runtime_bounds["max_event_steps"]
        scenario_entrypoints = [
            entrypoints[event["entrypoint"]]
            for event in ordered_events
            if event["kind"] == "transition-invocation"
        ]
        actual_values: dict[bytes, Any] = {}
        for selected_entrypoint in scenario_entrypoints:
            scenario_input_contract = cast(
                dict[str, Any], selected_entrypoint["scenario_input_contract"]
            )
            for initializer in cast(
                list[dict[str, Any]], scenario_input_contract["initializers"]
            ):
                identity = canonical_bytes(cast(JsonValue, initializer["target"]))
                previous = actual_values.get(identity, initializer["value"])
                if previous != initializer["value"]:
                    raise ValueError(
                        "admitted Scenario Input Contracts disagree on an initializer"
                    )
                actual_values[identity] = initializer["value"]
        for assignment in scenario["assignments"]:
            identity = canonical_bytes(cast(JsonValue, assignment["target"]))
            actual_values[identity] = assignment["value"]
        try:
            total_steps = _evaluate_initialization_programs(
                checked,
                actual_values,
                consumed_steps=total_steps,
                runtime_limit=runtime_limit,
                cache=initialization_cache,
                selected_entrypoints=scenario_entrypoints,
                frame_token={
                    "scenario": scenario["id"],
                    "snapshot_index": len(snapshots),
                },
                phase="initialization",
            )
        except _InitializationProgramFault as fault:
            code = _diagnostic_for_signal(checked, fault.signal, "runtime")
            return _refusal(
                stage="runtime",
                variant="pre-event",
                code=code,
                identity=checked.content_identity,
                pointer=f"/scenarios/{scenario_index}/assignments",
                message=(
                    f"Initialization program {fault.program} refused before "
                    f"Snapshot 0 at evaluation site "
                    f"{fault.evaluation_site_identity} in immutable frame "
                    f"{fault.frame_identity}"
                ),
                primary=RuntimeLocation(
                    subject="formula-evaluation-site",
                    identity=fault.evaluation_site_identity,
                ),
                related=(
                    RuntimeLocation(
                        subject="initialization-frame",
                        identity=fault.frame_identity,
                    ),
                    ArtifactLocation(
                        content_identity=checked.content_identity,
                        pointer=f"/scenarios/{scenario_index}/assignments",
                    ),
                ),
            )
        state: dict[bytes, int] = {
            identity: cast(int, actual_values[identity])
            for identity, declaration in declarations.items()
            if declaration["role"] == "state" and identity in actual_values
        }
        initial_values = _resolved_int_rows(state, display_names)
        initial_snapshot = cast(
            dict[str, JsonValue],
            {
                "index": len(snapshots),
                "name": f"{scenario['id']}:initial",
                "scenario": scenario["id"],
                "event_id": None,
                "logical_time": None,
                "values": cast(JsonValue, initial_values),
                "continuation": _runtime_continuation(
                    checked,
                    lifecycle_state=_runtime_lifecycle_roles(checked)["ready"],
                    step_boundary=_runtime_boundary_roles(checked)["initial"],
                    scenario_cursor=scenario_index,
                    event_catalog_count=len(scenario_event_catalog),
                    event_catalog_identity=event_catalog_identity,
                    pending_event_count=len(ordered_events),
                    committed_event_count=committed_event_count,
                    committed_trace_identity=committed_trace_identity,
                    snapshot_index=len(snapshots),
                    event_id=None,
                    logical_time=None,
                    rng=rng,
                    event_steps=0,
                    node_steps=total_steps,
                    admitted_event_count=admitted_event_count,
                    next_enqueue_sequence=next_enqueue_sequence,
                    root_event_map_identity=root_event_map_identity,
                    resolved_runtime_profile_identity=resolved_runtime.content_identity,
                ),
            },
        )
        initial_snapshot["snapshot_identity"] = _projected_runtime_identity(
            _scheduler_contract(checked)["snapshot_identity"],
            {
                "experiment_identity": checked.content_identity,
                "scenario_id": scenario["id"],
                "index": initial_snapshot["index"],
                "logical_time": None,
                "event_id": None,
                "values": cast(JsonValue, initial_values),
                "continuation": initial_snapshot["continuation"],
            },
        )
        snapshots.append(initial_snapshot)
        current_snapshot_identity = cast(str, initial_snapshot["snapshot_identity"])
        scenario_event_outputs[scenario["id"]] = []
        operation = (
            operations[scenario_entrypoints[0]["operation"]["id"]]
            if scenario_entrypoints
            else None
        )
        draws: list[dict[str, JsonValue]] = []
        call_trace: list[dict[str, JsonValue]] = []
        formula_evaluations: list[dict[str, JsonValue]] = []
        schedule_trace: list[dict[str, JsonValue]] = []
        cancellation_trace: list[dict[str, JsonValue]] = []
        buffered_children: list[dict[str, Any]] = []
        canceled_event_ids: set[str] = set()
        event_id = ""

        def execute_operation(
            selected_operation: dict[str, Any],
            arguments: dict[str, Any],
            state_references: dict[str, bytes],
            call_path: tuple[str, ...],
            call_site_identity: str | None,
        ) -> tuple[str, Any]:
            nonlocal admitted_event_count
            nonlocal event_steps, next_enqueue_sequence, total_steps
            operation_before: dict[bytes, int] = dict(state)
            variables: dict[str, Any] = dict(arguments)
            extensions = selected_operation.get("extensions", {})
            snapshot_operands = (
                extensions.get("standard.snapshot-operands")
                if isinstance(extensions, dict)
                else None
            )
            if isinstance(snapshot_operands, dict):
                for row in cast(
                    list[dict[str, Any]],
                    snapshot_operands.get("operands", []),
                ):
                    identity = canonical_bytes(cast(JsonValue, row["resolved_symbol"]))
                    variables[cast(str, row["name"])] = actual_values[identity]
            operation_results: dict[str, Any] = {}
            outcome = selected_operation["default_outcome"]
            operation_steps = 0
            evaluation_sites = _instruction_evaluation_sites(selected_operation)
            for instruction_index, instruction in enumerate(selected_operation["body"]):
                evaluation_site_identity = evaluation_sites.get(instruction_index)
                node_contract = node_contracts[instruction["node"]]
                charge = node_contract["resource_charge"]["amount"]
                total_steps += charge
                event_steps += charge
                operation_steps += charge
                if (
                    total_steps > runtime_limit
                    or event_steps > root_step_limit
                    or operation_steps
                    > selected_operation["resource_bounds"]["max_steps"]
                ):
                    raise _RuntimeExecutionFault(
                        signal="step-limit",
                        operation=selected_operation["id"],
                        call_path=call_path,
                        call_site_identity=call_site_identity,
                        evaluation_site_identity=evaluation_site_identity,
                        instruction_index=instruction_index,
                    )
                semantics = node_contract["semantics"]
                operator = semantics["operator"]
                if operator == "invoke-operation":
                    child = operations[instruction["operation"]["id"]]
                    resolved_call_site = call_sites[
                        (selected_operation["id"], instruction["site"])
                    ]
                    child_arguments: dict[str, Any] = {}
                    child_state_references: dict[str, bytes] = {}
                    for binding in instruction["arguments"]:
                        actual = binding["operand"]
                        if actual["kind"] == "port":
                            child_arguments[binding["port"]] = variables[actual["port"]]
                            if actual["port"] in state_references:
                                child_state_references[binding["port"]] = (
                                    state_references[actual["port"]]
                                )
                        elif actual["kind"] == "local":
                            child_arguments[binding["port"]] = variables[
                                actual["local"]
                            ]
                        else:
                            child_arguments[binding["port"]] = actual["literal"]
                    child_outcome, child_result = execute_operation(
                        child,
                        child_arguments,
                        child_state_references,
                        (*call_path, instruction["site"]),
                        resolved_call_site["identity"],
                    )
                    resolved_outcome = next(
                        row
                        for row in resolved_call_site["outcomes"]
                        if row["outcome"] == child_outcome
                    )
                    call_trace.append(
                        {
                            "site": "/".join((*call_path, instruction["site"])),
                            "call_site_identity": resolved_call_site["identity"],
                            "operation": resolved_call_site["operation"],
                            "outcome": {
                                "id": child_outcome,
                                "identity": resolved_outcome["identity"],
                            },
                            "arguments": [
                                {
                                    "formal_port_identity": row["port"]["identity"],
                                    "actual_operand_identity": row["operand"][
                                        "identity"
                                    ],
                                }
                                for row in resolved_call_site["arguments"]
                            ],
                            "result_identity": resolved_call_site["result"]["identity"],
                        }
                    )
                    result_binding = instruction["result"]
                    if result_binding["kind"] == "local":
                        variables[result_binding["name"]] = child_result
                    elif result_binding["kind"] == "operation-result":
                        operation_results[instruction["site"]] = child_result
                    for alias, actual in state_references.items():
                        variables[alias] = state[actual]
                    mapping = next(
                        row
                        for row in instruction["outcomes"]
                        if row["outcome"] == child_outcome
                    )
                    if mapping["action"]["kind"] == "propagate":
                        outcome = mapping["action"]["outcome"]
                        break
                    continue
                if operator == "schedule-operation":
                    child_operation = operations[instruction["operation"]["id"]]
                    child_arguments: dict[str, Any] = {}
                    child_state_references: dict[str, bytes] = {}
                    for binding in instruction["arguments"]:
                        operand = binding["operand"]
                        if operand["kind"] == "port":
                            child_arguments[binding["port"]] = variables[
                                operand["port"]
                            ]
                            if operand["port"] in state_references:
                                child_state_references[binding["port"]] = (
                                    state_references[operand["port"]]
                                )
                        elif operand["kind"] == "local":
                            child_arguments[binding["port"]] = variables[
                                operand["local"]
                            ]
                        else:
                            child_arguments[binding["port"]] = operand["literal"]
                    scheduler = _scheduler_contract(checked)
                    schedule_identity = scheduler["call_site_identity"]["schedule"]
                    schedule_identity_body = {
                        "parent_event_id": event_id,
                        "parent_operation": selected_operation["id"],
                        "site": instruction["site"],
                        "operation": instruction["operation"],
                    }
                    schedule_call_site_identity = content_identity(
                        cast(str, schedule_identity["domain"]),
                        cast(JsonValue, schedule_identity_body),
                    )
                    scheduled_logical_time = cast(int, instruction["logical_time"])
                    scheduled_priority = cast(int, instruction["priority"])
                    active_logical_time = cast(int, event_spec["logical_time"])
                    active_priority = cast(int, event_spec["priority"])

                    def refuse_schedule(signal: str) -> None:
                        raise _RuntimeExecutionFault(
                            signal=signal,
                            operation=selected_operation["id"],
                            call_path=call_path,
                            call_site_identity=schedule_call_site_identity,
                            evaluation_site_identity=evaluation_site_identity,
                            instruction_index=instruction_index,
                        )

                    child_phase = cast(str, scheduler["schedule"]["child_phase"])
                    position_signal = runtime_scheduler.schedule_position_signal(
                        {
                            "logical_time": active_logical_time,
                            "phase": event_spec["phase"],
                            "priority": active_priority,
                        },
                        {
                            "logical_time": scheduled_logical_time,
                            "phase": instruction.get("phase", child_phase),
                            "priority": scheduled_priority,
                        },
                    )
                    if position_signal is not None:
                        refuse_schedule(position_signal)
                    if scheduled_logical_time > runtime_bounds["max_logical_time"]:
                        refuse_schedule("logical-time-limit")
                    zero_time_depth = (
                        cast(int, event_spec.get("zero_time_depth", 0)) + 1
                        if scheduled_logical_time == active_logical_time
                        else 0
                    )
                    if zero_time_depth > runtime_bounds["max_zero_time_depth"]:
                        refuse_schedule("zero-time-depth-limit")
                    if admitted_event_count + 1 > runtime_bounds["max_total_events"]:
                        refuse_schedule("event-limit")
                    provisional_count = sum(
                        child["event_id"] not in canceled_event_ids
                        for child in buffered_children
                    )
                    pending_count = sum(
                        pending["event_id"] not in canceled_event_ids
                        for pending in pending_events
                    )
                    if (
                        pending_count + provisional_count + 1
                        > runtime_bounds["max_queue_events"]
                    ):
                        refuse_schedule("queue-limit")
                    child_event: dict[str, Any] = {
                        "arguments": child_arguments,
                        "call_site_identity": schedule_call_site_identity,
                        "enqueue_sequence": next_enqueue_sequence,
                        "logical_time": scheduled_logical_time,
                        "operation": child_operation["id"],
                        "operation_ref": instruction["operation"],
                        "parent_event_id": event_id,
                        "phase": child_phase,
                        "priority": scheduled_priority,
                        "schedule_sequence": len(schedule_trace),
                        "state_references": child_state_references,
                        "zero_time_depth": zero_time_depth,
                    }
                    next_enqueue_sequence += 1
                    admitted_event_count += 1
                    child_event["event_id"] = _scheduled_event_id(
                        checked, scenario["id"], child_event
                    )
                    projected_child = _pending_event_projection(child_event)
                    buffered_children.append(child_event)
                    result_binding = instruction["result"]
                    variables[result_binding["name"]] = child_event["event_id"]
                    schedule_trace.append(
                        {
                            "event_id": child_event["event_id"],
                            "call_site_identity": schedule_call_site_identity,
                            "parent_operation": selected_operation["id"],
                            "call_path": "/".join(call_path),
                            "operation": instruction["operation"],
                            "arguments": projected_child["arguments"],
                            "state_references": projected_child["state_references"],
                            "ordering_key": {
                                "logical_time": child_event["logical_time"],
                                "phase": child_event["phase"],
                                "priority": child_event["priority"],
                                "enqueue_sequence": child_event["enqueue_sequence"],
                            },
                            "outcome": "queued",
                        }
                    )
                    continue
                if operator == "cancel-event":
                    target_contract = node_contracts[instruction["node"]]["semantics"][
                        "target_reference"
                    ]
                    target = instruction[target_contract["instruction_member"]]
                    target_variants = {
                        variant["kind"]: variant
                        for variant in target_contract["variants"]
                    }
                    target_variant = target_variants.get(target.get("kind"))
                    target_value_member = (
                        target_variant["value_member"]
                        if target_variant is not None
                        else ""
                    )
                    target_variable = target.get(target_value_member)
                    cancel_signals = _scheduler_contract(checked)["cancel"][
                        "refusal_signals"
                    ]
                    if (
                        target_variant is None
                        or not isinstance(target_variable, str)
                        or target_variable not in variables
                    ):
                        raise _RuntimeExecutionFault(
                            signal=cast(str, cancel_signals["unknown"]),
                            operation=selected_operation["id"],
                            call_path=call_path,
                            call_site_identity=call_site_identity,
                            evaluation_site_identity=evaluation_site_identity,
                            instruction_index=instruction_index,
                        )
                    target_event_id = variables[target_variable]
                    target_status = (
                        "unknown"
                        if target_event_id in canceled_event_ids
                        else "active"
                        if target_event_id == event_id
                        else "completed"
                        if any(
                            completed["event_id"] == target_event_id
                            for completed in events
                        )
                        else "provisional"
                        if any(
                            child["event_id"] == target_event_id
                            for child in buffered_children
                        )
                        else "pending"
                        if any(
                            child["event_id"] == target_event_id
                            for child in pending_events
                        )
                        else "unknown"
                    )
                    cancel_signal = runtime_scheduler.cancel_target_signal(
                        target_status
                    )
                    if cancel_signal is not None:
                        raise _RuntimeExecutionFault(
                            signal=cancel_signal,
                            operation=selected_operation["id"],
                            call_path=call_path,
                            call_site_identity=call_site_identity,
                            evaluation_site_identity=evaluation_site_identity,
                            instruction_index=instruction_index,
                        )
                    cancel_identity = _scheduler_contract(checked)[
                        "call_site_identity"
                    ]["cancel"]
                    cancel_identity_body = {
                        "canceling_event_id": event_id,
                        "operation": selected_operation["id"],
                        "site": instruction["site"],
                        "target_event_id": target_event_id,
                    }
                    cancel_call_site_identity = content_identity(
                        cast(str, cancel_identity["domain"]),
                        cast(JsonValue, cancel_identity_body),
                    )
                    canceled_event_ids.add(cast(str, target_event_id))
                    for scheduled in schedule_trace:
                        if scheduled["event_id"] == target_event_id:
                            scheduled["outcome"] = "canceled"
                    cancellation_trace.append(
                        {
                            "call_site_identity": cancel_call_site_identity,
                            "event_id": target_event_id,
                            "outcome": "canceled",
                        }
                    )
                    continue
                if operator == "gameplay-precondition":
                    if not _integer_compare(
                        semantics["comparison"],
                        variables[instruction["left"]],
                        variables[instruction["right"]],
                    ):
                        outcome = instruction["outcome"]
                        break
                elif operator == "named-integer-draw":
                    value, index, candidate, accepted = rng.draw(
                        instruction["stream"],
                        instruction["minimum"],
                        instruction["maximum"],
                    )
                    variables[instruction["target"]] = value
                    draws.append(
                        {
                            "stream": instruction["stream"],
                            "index": index,
                            "candidate_hex": rng.encode_candidate(candidate),
                            "accepted": accepted,
                            "minimum": instruction["minimum"],
                            "maximum": instruction["maximum"],
                            "value": value,
                        }
                    )
                elif node_contract["family"] == "expression":
                    try:
                        _execute_value_instruction(
                            instruction,
                            variables,
                            numeric,
                            node_contract,
                        )
                    except OverflowError as error:
                        raise _RuntimeExecutionFault(
                            signal="numeric-overflow",
                            operation=selected_operation["id"],
                            call_path=call_path,
                            call_site_identity=call_site_identity,
                            evaluation_site_identity=evaluation_site_identity,
                            instruction_index=instruction_index,
                        ) from error
                elif operator in {"state-integer-subtract", "state-write"}:
                    formal = instruction["symbol"]
                    actual = state_references[formal]
                    value = (
                        state[actual] - variables[instruction["value"]]
                        if operator == "state-integer-subtract"
                        else variables[instruction["value"]]
                    )
                    try:
                        state[actual] = _admit_declared_numeric(
                            value,
                            numeric,
                            declarations[actual],
                        )
                    except OverflowError as error:
                        raise _RuntimeExecutionFault(
                            signal="numeric-overflow",
                            operation=selected_operation["id"],
                            call_path=call_path,
                            call_site_identity=call_site_identity,
                            evaluation_site_identity=evaluation_site_identity,
                            instruction_index=instruction_index,
                        ) from error
                    for alias, alias_actual in state_references.items():
                        if alias_actual == actual:
                            variables[alias] = state[actual]
                else:
                    raise ValueError(
                        f"admitted evaluator lacks runtime operator {operator}"
                    )
                if (
                    evaluation_site_identity is not None
                    and evaluation_sites.get(instruction_index + 1)
                    != evaluation_site_identity
                ):
                    binding = formula_bindings_by_site[evaluation_site_identity]
                    evaluation = _operation_formula_evaluation_record(
                        selected_operation,
                        binding,
                        variables,
                        evaluation_site_identity=evaluation_site_identity,
                        frame_identity=current_snapshot_identity,
                        call_path=call_path,
                    )
                    if evaluation is None:
                        raise ValueError(
                            "admitted Formula evaluation record is incomplete"
                        )
                    formula_evaluations.append(evaluation)
            outcome_definition = next(
                row for row in selected_operation["outcomes"] if row["id"] == outcome
            )
            if outcome_definition["state_policy"] == "rollback":
                state.clear()
                state.update(operation_before)
            result_source = selected_operation["result"]["source"]
            if outcome_definition["kind"] != "success":
                result = None
            elif result_source["kind"] in {"local", "port"}:
                result = variables[result_source["name"]]
            elif result_source["kind"] == "operation-result":
                result = operation_results[result_source["site"]]
            else:
                result = None
            return cast(str, outcome), result

        pending_events = list(ordered_events)
        event_position = 0
        terminal_condition = scenario["terminal_condition"]
        terminal_maximum = (
            terminal_condition["maximum"]
            if terminal_condition["kind"] == "event-count"
            else None
        )
        last_logical_time: int | None = None
        while pending_events:
            pending_events[:] = runtime_scheduler.ordered_events(pending_events)
            event_spec = pending_events.pop(0)
            last_logical_time = cast(int, event_spec["logical_time"])
            external_input = event_spec.get("kind") == "external-input"
            if external_input:
                entrypoint = None
                operation = None
                event_id = cast(str, event_spec["event_id"])
            elif "entrypoint" in event_spec:
                entrypoint = entrypoints[event_spec["entrypoint"]]
                operation = operations[entrypoint["operation"]["id"]]
                event_id = cast(str, event_spec["event_id"])
            else:
                entrypoint = None
                operation = operations[event_spec["operation"]]
                event_id = event_spec["event_id"]
            outcomes = (
                {row["id"]: row for row in operation["outcomes"]}
                if operation is not None
                else {}
            )
            draws = []
            call_trace = []
            formula_evaluations = []
            schedule_trace = []
            cancellation_trace = []
            buffered_children = []
            canceled_event_ids = set()
            event_steps = 0
            root_step_limit = runtime_bounds["max_event_steps"]
            before = dict(state)
            rng_before = rng.snapshot()
            admitted_event_count_before = admitted_event_count
            next_enqueue_sequence_before = next_enqueue_sequence
            root_arguments: dict[str, Any] = {}
            root_state_references: dict[str, bytes] = {}
            event_actual_values = dict(actual_values)
            payload_values = (
                {
                    canonical_bytes(cast(JsonValue, row["target"])): row["value"]
                    for row in event_spec["payload"]
                }
                if entrypoint is not None
                else {}
            )
            event_actual_values.update(payload_values)
            dispatch_path = (
                (f"input:{event_spec['root_event_ref']}",)
                if external_input
                else (
                    (cast(str, entrypoint["id"]),)
                    if entrypoint is not None
                    else (f"scheduled:{event_spec['call_site_identity']}",)
                )
            )
            event_formula_fault: _RuntimeExecutionFault | None = None
            if not external_input:
                assert operation is not None
                try:
                    total_steps = _evaluate_initialization_programs(
                        checked,
                        event_actual_values,
                        consumed_steps=total_steps,
                        runtime_limit=runtime_limit,
                        cache=initialization_cache,
                        selected_entrypoints=scenario_entrypoints,
                        frame_identity=current_snapshot_identity,
                        phase="event",
                    )
                except _InitializationProgramFault as fault:
                    event_formula_fault = _RuntimeExecutionFault(
                        signal=fault.signal,
                        operation=cast(str, operation["id"]),
                        call_path=dispatch_path,
                        call_site_identity=None,
                        evaluation_site_identity=fault.evaluation_site_identity,
                        instruction_index=None,
                    )
            if external_input:
                for fact in event_spec["facts"]:
                    identity = canonical_bytes(cast(JsonValue, fact["target"]))
                    event_actual_values[identity] = fact["value"]
            elif entrypoint is None:
                root_arguments.update(event_spec["arguments"])
                root_state_references.update(event_spec["state_references"])
                for port, identity in root_state_references.items():
                    root_arguments[port] = actual_values[identity]
            else:
                for binding in entrypoint["arguments"]:
                    resolved_operand = binding["operand"]
                    if resolved_operand["kind"] == "symbol":
                        identity = canonical_bytes(
                            cast(JsonValue, resolved_operand["symbol"])
                        )
                        declaration = declarations[identity]
                        root_arguments[binding["port"]["name"]] = event_actual_values[
                            identity
                        ]
                        if declaration["role"] == "state":
                            root_state_references[binding["port"]["name"]] = identity
                    elif resolved_operand["kind"] == "event-reference":
                        reference_bindings = {
                            row["name"]: row["root_event_ref"]
                            for row in event_spec.get("event_references", [])
                        }
                        root_event_ref = reference_bindings[resolved_operand["name"]]
                        root_arguments[binding["port"]["name"]] = (
                            root_event_ids_by_scenario[scenario["id"]][root_event_ref]
                        )
                    else:
                        root_arguments[binding["port"]["name"]] = resolved_operand[
                            "value"
                        ]
            try:
                if event_formula_fault is not None:
                    raise event_formula_fault
                if external_input:
                    outcome, root_result = "input-admitted", None
                else:
                    assert operation is not None
                    outcome, root_result = execute_operation(
                        operation,
                        root_arguments,
                        root_state_references,
                        dispatch_path,
                        None,
                    )
            except _RuntimeExecutionFault as fault:
                state.clear()
                state.update(before)
                rng.restore(rng_before)
                admitted_event_count = admitted_event_count_before
                next_enqueue_sequence = next_enqueue_sequence_before
                code = _diagnostic_for_signal(checked, fault.signal, "runtime")
                message = {
                    "step-limit": "Runtime program exhausted its exact step bound",
                    "numeric-overflow": (
                        "Exact-int64 operation overflowed its numeric domain"
                    ),
                }.get(
                    fault.signal,
                    f"Runtime scheduler refused {fault.signal}",
                )
                return _runtime_refusal_outcome(
                    checked,
                    scenario_id=scenario["id"],
                    scenario_index=scenario_index,
                    code=code,
                    message=message,
                    events=events,
                    event_catalog=event_catalog,
                    root_event_map=root_event_map,
                    terminal_condition=terminal_condition,
                    last_snapshot_identity=current_snapshot_identity,
                    last_snapshot_record=snapshots[-1],
                    budget_counters={
                        "event_steps": event_steps,
                        "logical_time": cast(int, event_spec["logical_time"]),
                        "node_steps": total_steps,
                        "queue_events": len(pending_events),
                        "total_events": admitted_event_count,
                        "zero_time_depth": cast(
                            int, event_spec.get("zero_time_depth", 0)
                        ),
                    },
                    entrypoint_id=(
                        entrypoint["id"]
                        if entrypoint is not None
                        else f"scheduled:{event_spec['call_site_identity']}"
                    ),
                    entrypoint_identity=(
                        entrypoint["identity"]
                        if entrypoint is not None
                        else event_spec["call_site_identity"]
                    ),
                    operation=fault.operation,
                    call_path=fault.call_path,
                    call_site_identity=fault.call_site_identity,
                    evaluation_site_identity=fault.evaluation_site_identity,
                    instruction_index=fault.instruction_index,
                    refusing_event_id=event_id,
                    refusing_event_spec=_pending_event_projection(event_spec),
                    refusing_attempted_calls=call_trace,
                    refusing_ordering_key=cast(
                        dict[str, JsonValue],
                        {
                            "logical_time": event_spec["logical_time"],
                            "phase": event_spec["phase"],
                            "priority": event_spec["priority"],
                            "enqueue_sequence": event_spec["enqueue_sequence"],
                        },
                    ),
                    refusing_snapshot_before_identity=current_snapshot_identity,
                    state_before={
                        display_names[identity]: value
                        for identity, value in before.items()
                    },
                )
            if external_input:
                actual_values.update(event_actual_values)
            for identity, value in state.items():
                actual_values[identity] = value
                event_actual_values[identity] = value
            if external_input:
                typed_outcome = {"id": outcome, "kind": "success"}
            else:
                outcome_definition = outcomes[outcome]
                if (
                    outcome_definition["kind"] == "success"
                    and entrypoint is not None
                    and entrypoint["result"]["kind"] == "symbol"
                ):
                    result_identity = canonical_bytes(
                        cast(JsonValue, entrypoint["result"]["symbol"])
                    )
                    event_actual_values[result_identity] = root_result
                typed_outcome = {
                    "id": outcome,
                    "kind": outcome_definition["kind"],
                }
            pending_events[:] = [
                pending
                for pending in pending_events
                if pending["event_id"] not in canceled_event_ids
            ]
            for child in buffered_children:
                catalog_record = _event_catalog_record(
                    checked,
                    scenario["id"],
                    _pending_event_projection(child),
                )
                scenario_event_catalog.append(catalog_record)
                event_catalog.append(catalog_record)
                event_catalog_identity = _extend_runtime_journal_identity(
                    journal_contract["event_catalog"],
                    event_catalog_identity,
                    catalog_record,
                )
                if child["event_id"] not in canceled_event_ids:
                    pending_events.append(child)
            event_payload = cast(
                dict[str, JsonValue],
                {
                    "index": len(events),
                    "event_id": event_id,
                    "ordering_key": {
                        "logical_time": event_spec["logical_time"],
                        "phase": event_spec["phase"],
                        "priority": event_spec["priority"],
                        "enqueue_sequence": event_spec["enqueue_sequence"],
                    },
                    "operation": operation["id"] if operation is not None else None,
                    "entrypoint": (
                        {
                            "id": entrypoint["id"],
                            "identity": entrypoint["identity"],
                        }
                        if entrypoint is not None
                        else None
                    ),
                    "calls": call_trace,
                    "formula_evaluations": formula_evaluations,
                    "schedules": schedule_trace,
                    "cancellations": cancellation_trace,
                    "outcome": typed_outcome,
                    "facts": _resolved_value_rows(event_actual_values, display_names),
                    "state_before": _resolved_int_rows(before, display_names),
                    "state_after": _resolved_int_rows(state, display_names),
                    "rng_draws": draws,
                    "snapshot_before_identity": current_snapshot_identity,
                    "observation": None,
                    "external_input_identity": (
                        _external_input_identity(checked, scenario["id"], event_spec)
                        if external_input
                        else None
                    ),
                },
            )
            if "root_event_ref" in event_spec:
                event_payload["root_event_ref"] = event_spec["root_event_ref"]
            else:
                event_payload["parent_event_id"] = event_spec["parent_event_id"]
                event_payload["schedule_call_site_identity"] = event_spec[
                    "call_site_identity"
                ]
            event = cast(dict[str, JsonValue], event_payload)
            event_position += 1
            step_boundary = _runtime_step_boundary(
                checked,
                active_logical_time=cast(int, event_spec["logical_time"]),
                pending_events=pending_events,
                event_position=event_position,
                terminal_maximum=terminal_maximum,
            )
            committed_event_count += 1
            committed_trace_identity = _extend_runtime_journal_identity(
                journal_contract["committed_trace"],
                committed_trace_identity,
                _committed_event_projection(event),
            )
            snapshot_index = len(snapshots)
            continuation = _runtime_continuation(
                checked,
                lifecycle_state=(
                    _runtime_lifecycle_roles(checked)["ready"]
                    if step_boundary is not None
                    else _runtime_lifecycle_roles(checked)["active"]
                ),
                step_boundary=step_boundary,
                scenario_cursor=scenario_index,
                event_catalog_count=len(scenario_event_catalog),
                event_catalog_identity=event_catalog_identity,
                pending_event_count=len(pending_events),
                committed_event_count=committed_event_count,
                committed_trace_identity=committed_trace_identity,
                snapshot_index=snapshot_index,
                event_id=event_id,
                logical_time=cast(int, event_spec["logical_time"]),
                rng=rng,
                event_steps=event_steps,
                node_steps=total_steps,
                admitted_event_count=admitted_event_count,
                next_enqueue_sequence=next_enqueue_sequence,
                root_event_map_identity=root_event_map_identity,
                resolved_runtime_profile_identity=resolved_runtime.content_identity,
            )
            snapshot = cast(
                dict[str, JsonValue],
                {
                    "index": snapshot_index,
                    "name": f"{scenario['id']}:event:{event_id}",
                    "scenario": scenario["id"],
                    "event_id": event_id,
                    "logical_time": event_spec["logical_time"],
                    "values": _resolved_int_rows(state, display_names),
                    "continuation": continuation,
                },
            )
            snapshot["snapshot_identity"] = _projected_runtime_identity(
                _scheduler_contract(checked)["snapshot_identity"],
                {
                    "experiment_identity": checked.content_identity,
                    "scenario_id": scenario["id"],
                    "index": snapshot["index"],
                    "logical_time": event_spec["logical_time"],
                    "event_id": event_id,
                    "values": snapshot["values"],
                    "continuation": continuation,
                },
            )
            event["snapshot_after_identity"] = snapshot["snapshot_identity"]
            events.append(event)
            snapshots.append(snapshot)
            snapshot_identity = cast(str, snapshot["snapshot_identity"])
            current_snapshot_identity = snapshot_identity
            scenario_event_outputs[scenario["id"]].append(
                (
                    event,
                    {
                        display_names[identity]: value
                        for identity, value in state.items()
                    },
                    outcome,
                )
            )
            if step_boundary is None:
                continue
            try:
                total_steps = _evaluate_initialization_programs(
                    checked,
                    actual_values,
                    consumed_steps=total_steps,
                    runtime_limit=runtime_limit,
                    cache=initialization_cache,
                    selected_entrypoints=scenario_entrypoints,
                    frame_identity=snapshot_identity,
                    phase="observation",
                )
            except _InitializationProgramFault as fault:
                code = _diagnostic_for_signal(checked, fault.signal, "runtime")
                message = (
                    "Runtime program exhausted its exact step bound"
                    if fault.signal == "step-limit"
                    else "Exact-int64 operation overflowed its numeric domain"
                )
                return _runtime_refusal_outcome(
                    checked,
                    scenario_id=scenario["id"],
                    scenario_index=scenario_index,
                    code=code,
                    message=message,
                    events=events,
                    event_catalog=event_catalog,
                    root_event_map=root_event_map,
                    terminal_condition=terminal_condition,
                    last_snapshot_identity=current_snapshot_identity,
                    last_snapshot_record=snapshots[-1],
                    budget_counters={
                        "event_steps": event_steps,
                        "logical_time": cast(int, event_spec["logical_time"]),
                        "node_steps": total_steps,
                        "queue_events": len(pending_events),
                        "total_events": admitted_event_count,
                        "zero_time_depth": cast(
                            int, event_spec.get("zero_time_depth", 0)
                        ),
                    },
                    entrypoint_id=(
                        entrypoint["id"]
                        if entrypoint is not None
                        else f"scheduled:{event_spec['call_site_identity']}"
                    ),
                    entrypoint_identity=(
                        entrypoint["identity"]
                        if entrypoint is not None
                        else event_spec["call_site_identity"]
                    ),
                    operation=(
                        operation["id"] if operation is not None else "external-input"
                    ),
                    call_path=dispatch_path,
                    call_site_identity=None,
                    evaluation_site_identity=fault.evaluation_site_identity,
                    instruction_index=None,
                    refusing_event_id=event_id,
                    refusing_event_spec=_pending_event_projection(event_spec),
                    refusing_attempted_calls=call_trace,
                    refusing_ordering_key=cast(
                        dict[str, JsonValue],
                        {
                            "logical_time": event_spec["logical_time"],
                            "phase": event_spec["phase"],
                            "priority": event_spec["priority"],
                            "enqueue_sequence": event_spec["enqueue_sequence"],
                        },
                    ),
                    refusing_snapshot_before_identity=current_snapshot_identity,
                    state_before={
                        display_names[identity]: value
                        for identity, value in state.items()
                    },
                )
            if step_boundary == _runtime_boundary_roles(checked)["terminal"]:
                break
        scenario_terminal_states[scenario["id"]] = {
            display_names[identity]: value for identity, value in state.items()
        }

        terminal_reason = (
            "event-count-reached"
            if terminal_maximum is not None and event_position >= terminal_maximum
            else "queue-drained"
        )
        if last_logical_time is None:
            raise ValueError("admitted Scenario produced no runtime Event")
        logical_time = last_logical_time
        terminal_event_id = cast(str, events[-1]["event_id"])
        terminal_snapshot_identity = current_snapshot_identity
        terminal_event_count = event_position
        observation_event_ids: list[str] = []
        observation_contract = cast(dict[str, Any], scheduler["observation"])
        for metric_index, metric in enumerate(checked.value["metrics"]):
            metric_identity = _metric_definition_identity(metric)
            observation_event_id = _observation_event_id(
                checked,
                scenario["id"],
                metric_identity,
                logical_time=logical_time,
                enqueue_sequence=next_enqueue_sequence,
            )
            observation_ordering_key = cast(
                dict[str, JsonValue],
                {
                    "logical_time": logical_time,
                    "phase": observation_contract["phase"],
                    "priority": observation_contract["priority"],
                    "enqueue_sequence": next_enqueue_sequence,
                },
            )
            observation_event_spec = cast(
                dict[str, JsonValue],
                {
                    "event_id": observation_event_id,
                    "kind": "observation",
                    "ordering_key": observation_ordering_key,
                    "metric_definition_identity": metric_identity,
                },
            )
            if admitted_event_count + 1 > runtime_bounds["max_total_events"]:
                return _runtime_refusal_outcome(
                    checked,
                    scenario_id=scenario["id"],
                    scenario_index=scenario_index,
                    code=_diagnostic_for_signal(checked, "event-limit", "runtime"),
                    message="Runtime scheduler refused event-limit",
                    events=events,
                    event_catalog=event_catalog,
                    root_event_map=root_event_map,
                    terminal_condition=terminal_condition,
                    last_snapshot_identity=current_snapshot_identity,
                    last_snapshot_record=snapshots[-1],
                    budget_counters={
                        "event_steps": 0,
                        "logical_time": logical_time,
                        "node_steps": total_steps,
                        "queue_events": len(pending_events),
                        "total_events": admitted_event_count,
                        "zero_time_depth": 0,
                    },
                    entrypoint_id=f"observation:{metric['id']}",
                    entrypoint_identity=metric_identity,
                    operation="observation",
                    call_path=("observation", cast(str, metric["id"])),
                    call_site_identity=None,
                    evaluation_site_identity=None,
                    instruction_index=None,
                    refusing_event_id=observation_event_id,
                    refusing_event_spec=observation_event_spec,
                    refusing_attempted_calls=[],
                    refusing_ordering_key=observation_ordering_key,
                    refusing_snapshot_before_identity=current_snapshot_identity,
                    state_before={
                        display_names[identity]: value
                        for identity, value in state.items()
                    },
                )
            admitted_event_count += 1
            next_enqueue_sequence += 1
            observation_catalog_record = _event_catalog_record(
                checked,
                scenario["id"],
                observation_event_spec,
            )
            scenario_event_catalog.append(observation_catalog_record)
            event_catalog.append(observation_catalog_record)
            event_catalog_identity = _extend_runtime_journal_identity(
                journal_contract["event_catalog"],
                event_catalog_identity,
                observation_catalog_record,
            )
            resolved_state = _resolved_int_rows(state, display_names)
            observation_event = cast(
                dict[str, JsonValue],
                {
                    "index": len(events),
                    "event_id": observation_event_id,
                    "ordering_key": observation_ordering_key,
                    "operation": None,
                    "entrypoint": None,
                    "calls": [],
                    "formula_evaluations": [],
                    "schedules": [],
                    "cancellations": [],
                    "outcome": {
                        "id": "observation-emitted",
                        "kind": "success",
                    },
                    "facts": _resolved_value_rows(actual_values, display_names),
                    "state_before": resolved_state,
                    "state_after": resolved_state,
                    "rng_draws": [],
                    "snapshot_before_identity": current_snapshot_identity,
                    "external_input_identity": None,
                    "observation": {
                        "metric": metric["id"],
                        "metric_definition_identity": metric_identity,
                        "window": {
                            "kind": metric["window"]["kind"],
                            "name": metric["window"]["name"],
                        },
                    },
                },
            )
            observation_event_ids.append(observation_event_id)
            committed_event_count += 1
            committed_trace_identity = _extend_runtime_journal_identity(
                journal_contract["committed_trace"],
                committed_trace_identity,
                _committed_event_projection(observation_event),
            )
            snapshot_index = len(snapshots)
            continuation = _runtime_continuation(
                checked,
                lifecycle_state=(
                    _runtime_lifecycle_roles(checked)["terminal"]
                    if metric_index + 1 == len(checked.value["metrics"])
                    else _runtime_lifecycle_roles(checked)["active"]
                ),
                step_boundary=(
                    _runtime_boundary_roles(checked)["terminal"]
                    if metric_index + 1 == len(checked.value["metrics"])
                    else _runtime_boundary_roles(checked)["observation"]
                ),
                scenario_cursor=scenario_index,
                event_catalog_count=len(scenario_event_catalog),
                event_catalog_identity=event_catalog_identity,
                pending_event_count=len(pending_events),
                committed_event_count=committed_event_count,
                committed_trace_identity=committed_trace_identity,
                snapshot_index=snapshot_index,
                event_id=observation_event_id,
                logical_time=logical_time,
                rng=rng,
                event_steps=0,
                node_steps=total_steps,
                admitted_event_count=admitted_event_count,
                next_enqueue_sequence=next_enqueue_sequence,
                root_event_map_identity=root_event_map_identity,
                resolved_runtime_profile_identity=resolved_runtime.content_identity,
            )
            snapshot = cast(
                dict[str, JsonValue],
                {
                    "index": snapshot_index,
                    "name": (
                        f"{scenario['id']}:terminal"
                        if metric_index + 1 == len(checked.value["metrics"])
                        else f"{scenario['id']}:observation:{metric['id']}"
                    ),
                    "scenario": scenario["id"],
                    "event_id": observation_event_id,
                    "logical_time": logical_time,
                    "values": resolved_state,
                    "continuation": continuation,
                },
            )
            snapshot["snapshot_identity"] = _projected_runtime_identity(
                _scheduler_contract(checked)["snapshot_identity"],
                {
                    "experiment_identity": checked.content_identity,
                    "scenario_id": scenario["id"],
                    "index": snapshot["index"],
                    "logical_time": logical_time,
                    "event_id": observation_event_id,
                    "values": snapshot["values"],
                    "continuation": continuation,
                },
            )
            observation_event["snapshot_after_identity"] = snapshot["snapshot_identity"]
            events.append(observation_event)
            snapshots.append(snapshot)
            current_snapshot_identity = cast(str, snapshot["snapshot_identity"])
            scenario_observation_evidence[(scenario["id"], metric["id"])] = (
                observation_event_id,
                current_snapshot_identity,
                logical_time,
            )

        terminal_statuses.append(
            cast(
                dict[str, JsonValue],
                {
                    "scenario": scenario["id"],
                    "condition": terminal_condition,
                    "reason": terminal_reason,
                    "event_count": terminal_event_count,
                    "terminal_event_id": terminal_event_id,
                    "terminal_snapshot_identity": terminal_snapshot_identity,
                    "observation_event_ids": observation_event_ids,
                    "final_snapshot_identity": current_snapshot_identity,
                    "logical_time": logical_time,
                },
            )
        )

    samples: list[dict[str, JsonValue]] = []
    for metric in checked.value["metrics"]:
        metric_identity = _metric_definition_identity(metric)
        observation = metric["observation"]
        matched_replications = 0
        for scenario in checked.value["scenarios"]:
            matched: list[int] = []
            if observation["source"] == "event":
                for event, _event_state, outcome in scenario_event_outputs[
                    scenario["id"]
                ]:
                    if outcome != observation["name"]:
                        continue
                    facts = {
                        row["name"]: row.get("integer")
                        for row in event["facts"]
                        if row["kind"] == "integer"
                    }
                    value = facts.get(observation["member"])
                    if isinstance(value, int):
                        matched.append(value)
            else:
                expected_name = observation["name"]
                if expected_name not in {"terminal", f"{scenario['id']}:terminal"}:
                    continue
                value = scenario_terminal_states[scenario["id"]].get(
                    observation["member"]
                )
                if isinstance(value, int):
                    matched.append(value)
            if len(matched) != 1:
                return _refusal(
                    stage="evaluation",
                    code=_diagnostic_for_signal(
                        checked, "observation-unavailable", "evaluation"
                    ),
                    identity=checked.content_identity,
                    pointer=f"/metrics/{metric['id']}/observation",
                    message=(
                        "Metric observation did not resolve to exactly one value "
                        f"for scenario {scenario['id']}"
                    ),
                )
            matched_replications += 1
            value = matched[0]
            scenario_id = scenario["id"]
            terminal_event_id, terminal_snapshot_identity, terminal_logical_time = (
                scenario_observation_evidence[(scenario_id, metric["id"])]
            )
            target = metric["target"]
            samples.append(
                {
                    "metric": metric["id"],
                    "metric_definition_identity": metric_identity,
                    "scenario": scenario_id,
                    "status": "value",
                    "value": value,
                    "unit": metric["unit"],
                    "logical_time": terminal_logical_time,
                    "event_id": terminal_event_id,
                    "snapshot_identity": terminal_snapshot_identity,
                    "window": metric["window"]["name"],
                    "dimensions": metric["dimensions"],
                    "replication_identity": scenario_id,
                    "source_kind": "simulated",
                    "provenance": {
                        "scenario": scenario_id,
                        "observation_source": observation["source"],
                        "observation_name": observation["name"],
                        "observation_member": observation["member"],
                    },
                    "within_target": target["minimum"] <= value <= target["maximum"],
                    "source": observation["source"],
                    "member": observation["member"],
                }
            )
        if matched_replications == 0:
            return _refusal(
                stage="evaluation",
                code=_diagnostic_for_signal(
                    checked, "observation-unavailable", "evaluation"
                ),
                identity=checked.content_identity,
                pointer=f"/metrics/{metric['id']}/observation",
                message="Metric observation did not select any scenario",
            )

    metric_definition_identities, samples = _canonical_metric_dataset(samples)
    trace = _artifact(
        checked,
        "event-trace",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "scenario": ",".join(row["id"] for row in checked.value["scenarios"]),
                "root_event_map": root_event_map,
                "terminal_statuses": terminal_statuses,
                "events": events,
            },
        ),
    )
    snapshot_series = _artifact(
        checked,
        "snapshot-series",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "scenario": ",".join(row["id"] for row in checked.value["scenarios"]),
                "event_trace_identity": trace.content_identity,
                "event_catalog": event_catalog,
                "root_event_map": root_event_map,
                "snapshots": snapshots,
            },
        ),
    )
    metric_dataset = _artifact(
        checked,
        "metric-dataset",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "metric_definition_identities": metric_definition_identities,
                "source_provenance": {
                    "kind": "simulated",
                    "resolved_model_identity": checked.resolved_model[
                        "content_identity"
                    ],
                    "resolved_runtime_profile_identity": (
                        resolved_runtime.content_identity
                    ),
                    "evaluator_manifest_identity": evaluator.content_identity,
                },
                "data_version": "1",
                "partition": "evaluation",
                "ordering": ("metric-definition-identity,replication-identity"),
                "ingestion_transformation_identity": None,
                "samples": samples,
            },
        ),
    )
    reproduction = _reproduction_receipt(checked, evaluator, resolved_runtime)
    failed_metrics = tuple(
        cast(str, sample["metric"])
        for sample in samples
        if sample["within_target"] is False
    )
    if failed_metrics:
        primary = _artifact(
            checked,
            "experiment-verdict",
            cast(
                dict[str, JsonValue],
                {
                    "experiment_identity": checked.content_identity,
                    "resolved_runtime_profile_identity": (
                        resolved_runtime.content_identity
                    ),
                    "event_trace_identity": trace.content_identity,
                    "snapshot_series_identity": snapshot_series.content_identity,
                    "metric_dataset_identity": metric_dataset.content_identity,
                    "reproduction_receipt_identity": reproduction.content_identity,
                    "root_event_map": root_event_map,
                    "terminal_statuses": terminal_statuses,
                    "outcome": "rejected",
                    "failed_metrics": list(failed_metrics),
                },
            ),
        )
        primary_name = "experiment-verdict"
    else:
        primary = _artifact(
            checked,
            "evaluation-run",
            cast(
                dict[str, JsonValue],
                {
                    "experiment_identity": checked.content_identity,
                    "resolved_runtime_profile_identity": (
                        resolved_runtime.content_identity
                    ),
                    "evaluator_manifest_identity": evaluator.content_identity,
                    "event_trace_identity": trace.content_identity,
                    "snapshot_series_identity": snapshot_series.content_identity,
                    "metric_dataset_identity": metric_dataset.content_identity,
                    "reproduction_receipt_identity": reproduction.content_identity,
                    "root_event_map": root_event_map,
                    "terminal_statuses": terminal_statuses,
                    "outcome": "accepted",
                },
            ),
        )
        primary_name = "evaluation-run"
    return EvaluationArtifacts(
        members={
            primary_name: primary,
            "event-trace": trace,
            "snapshot-series": snapshot_series,
            "metric-dataset": metric_dataset,
            "reproduction-receipt": reproduction,
            "resolved-runtime-profile": resolved_runtime,
            "evaluator-capability-manifest": evaluator,
        },
        accepted=not failed_metrics,
        failed_metrics=failed_metrics,
    )
