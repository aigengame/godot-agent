"""Kernel-bound scheduling seam shared by Runtime execution and conformance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, cast


_Event = TypeVar("_Event", bound=Mapping[str, Any])


@dataclass(frozen=True)
class RuntimeScheduler:
    """Interpret the exact Kernel scheduler contract for one Runtime implementation."""

    contract: Mapping[str, Any]

    @classmethod
    def from_kernel(cls, kernel: Mapping[str, Any]) -> RuntimeScheduler:
        meta_format = kernel.get("meta_format")
        runtime = (
            meta_format.get("runtime_program")
            if isinstance(meta_format, Mapping)
            else None
        )
        scheduler = runtime.get("scheduler") if isinstance(runtime, Mapping) else None
        if not isinstance(scheduler, Mapping):
            raise ValueError("Kernel scheduler contract is absent")
        return cls(scheduler)

    def ordering_key(self, event: Mapping[str, Any]) -> tuple[int, ...]:
        key: list[int] = []
        for ordering in cast(Sequence[Mapping[str, Any]], self.contract["ordering"]):
            member = cast(str, ordering["member"])
            if member == "phase":
                rank = cast(Sequence[str], ordering["rank"])
                value = rank.index(cast(str, event[member]))
            else:
                value = cast(int, event[member])
            key.append(-value if ordering["direction"] == "descending" else value)
        return tuple(key)

    def ordered_events(self, events: Sequence[_Event]) -> list[_Event]:
        return sorted(events, key=self.ordering_key)

    def schedule_position_signal(
        self,
        parent: Mapping[str, Any],
        child: Mapping[str, Any],
    ) -> str | None:
        schedule = cast(Mapping[str, Any], self.contract["schedule"])
        signals = cast(Mapping[str, str], schedule["refusal_signals"])
        if child["phase"] != schedule["child_phase"]:
            return signals["hidden_input"]
        if child["logical_time"] < parent["logical_time"]:
            return signals["backward"]
        if (
            child["logical_time"] == parent["logical_time"]
            and child["priority"] > parent["priority"]
        ):
            return signals["illegal_same_time_priority"]
        return None

    def cancel_target_signal(self, status: str) -> str | None:
        cancel = cast(Mapping[str, Any], self.contract["cancel"])
        admitted = cast(Sequence[str], cancel["admitted_target_states"])
        if status in admitted:
            return None
        return cast(Mapping[str, str], cancel["refusal_signals"])[status]
