"""Production scheduler adapter and detector checks for conformance tests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from gda_balancing.schema2.runtime_scheduler import RuntimeScheduler


@dataclass(frozen=True)
class _RuntimeSchedulerMutation:
    allow_backward: bool = False
    order_by_event_id: bool = False
    omit_enqueue_sequence: bool = False
    read_initial_state: bool = False
    share_scenario_state: bool = False


_PRODUCTION_SCHEDULER_MUTATIONS = {
    "backward-scheduling": _RuntimeSchedulerMutation(allow_backward=True),
    "host-assigned-ordering": _RuntimeSchedulerMutation(order_by_event_id=True),
    "omitted-key": _RuntimeSchedulerMutation(omit_enqueue_sequence=True),
    "pre-commit-visibility": _RuntimeSchedulerMutation(read_initial_state=True),
    "scenario-as-timestep": _RuntimeSchedulerMutation(share_scenario_state=True),
}


def scheduler_detector_inventory(kernel: Mapping[str, Any]) -> tuple[str, ...]:
    kinds = kernel["meta_format"]["package_vector"]["kinds"]
    scheduler_kinds = [kind for kind in kinds if kind["id"] == "scheduler-scenario"]
    if len(scheduler_kinds) != 1:
        raise ValueError("Kernel scheduler-vector kind is not unique")
    detectors = scheduler_kinds[0]["mutation_detectors"]
    if (
        not isinstance(detectors, list)
        or not detectors
        or not all(isinstance(detector, str) and detector for detector in detectors)
        or detectors != sorted(set(detectors))
    ):
        raise ValueError("Kernel scheduler detector inventory is not closed")
    return tuple(detectors)


def require_complete_scheduler_detector_bindings(
    kernel: Mapping[str, Any],
    bindings: Mapping[str, object],
    *,
    consumer: str,
) -> None:
    declared = set(scheduler_detector_inventory(kernel))
    implemented = set(bindings)
    missing = sorted(declared - implemented)
    unexpected = sorted(implemented - declared)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing detector implementations: {', '.join(missing)}")
        if unexpected:
            details.append(
                f"unexpected detector implementations: {', '.join(unexpected)}"
            )
        raise ValueError(
            f"{consumer} scheduler detector bindings are incomplete; "
            + "; ".join(details)
        )


def evaluate_runtime_scheduler_vector(
    kernel: Mapping[str, Any],
    vector: Mapping[str, Any],
    *,
    mutation: str | None = None,
) -> dict[str, Any]:
    """Execute a scheduler vector through the production Runtime seam."""

    scheduler = RuntimeScheduler.from_kernel(kernel)
    require_complete_scheduler_detector_bindings(
        kernel,
        _PRODUCTION_SCHEDULER_MUTATIONS,
        consumer="production",
    )
    if mutation is None:
        mutant = _RuntimeSchedulerMutation()
    else:
        try:
            mutant = _PRODUCTION_SCHEDULER_MUTATIONS[mutation]
        except KeyError as error:
            raise ValueError(f"unsupported scheduler mutation: {mutation}") from error
    events = vector["input"]["events"]
    initial_states = vector["input"]["initial_states"]
    scenario_order = {
        row["scenario"]: index for index, row in enumerate(initial_states)
    }
    states = {row["scenario"]: row["value"] for row in initial_states}
    by_id = {event["id"]: event for event in events}

    def refused(signal: str) -> dict[str, Any]:
        return {
            "event_order": [],
            "observations": [],
            "outcome": "refused",
            "signal": signal,
            "terminal_reason": None,
            "terminal_states": deepcopy(initial_states),
        }

    for event in events:
        if event["cancel_requested"]:
            signal = scheduler.cancel_target_signal(event["status"])
            if signal is not None:
                return refused(signal)
    for event in events:
        parent_id = event["parent_id"]
        if parent_id is not None:
            signal = scheduler.schedule_position_signal(by_id[parent_id], event)
            if (
                mutant.allow_backward
                and signal
                == scheduler.contract["schedule"]["refusal_signals"]["backward"]
            ):
                signal = None
            if signal is not None:
                return refused(signal)

    def ordering_key(event: Mapping[str, Any]) -> tuple[Any, ...]:
        if mutant.order_by_event_id:
            return (event["id"],)
        runtime_key = scheduler.ordering_key(event)
        if mutant.omit_enqueue_sequence:
            runtime_key = runtime_key[:-1]
        return (scenario_order[event["scenario"]], *runtime_key)

    admitted = sorted(
        (
            event
            for event in events
            if event["status"] not in {"canceled", "completed"}
            and not event["cancel_requested"]
        ),
        key=ordering_key,
    )
    observations = []
    shared_state = next(iter(states.values()))
    for event in admitted:
        scenario = event["scenario"]
        before = shared_state if mutant.share_scenario_state else states[scenario]
        if mutant.read_initial_state:
            before = next(
                row["value"] for row in initial_states if row["scenario"] == scenario
            )
        after = before + event["state_delta"]
        if mutant.share_scenario_state:
            shared_state = after
        else:
            states[scenario] = after
        observations.append(
            {
                "event_id": event["id"],
                "scenario": scenario,
                "state_after": after,
                "state_before": before,
            }
        )
    if mutant.share_scenario_state:
        states = {scenario: shared_state for scenario in states}
    return {
        "event_order": [event["id"] for event in admitted],
        "observations": observations,
        "outcome": "admitted",
        "signal": None,
        "terminal_reason": vector["input"]["terminal_condition"],
        "terminal_states": [
            {"scenario": row["scenario"], "value": states[row["scenario"]]}
            for row in initial_states
        ],
    }
