"""Structural reachability for selected RIR Operation and Formula programs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.operation_program import (
    OperationCoordinate,
    closed_operation_coordinates,
    operation_coordinate,
    operation_body_instructions,
    selected_operation_index,
)


LIFECYCLE_PHASES = ("initialization", "event", "observation")


@dataclass(frozen=True)
class LifecycleFormulaPrograms:
    """Reachable Formula programs grouped by their admitted lifecycle phase."""

    initialization: tuple[dict[str, Any], ...]
    event: tuple[dict[str, Any], ...]
    observation: tuple[dict[str, Any], ...]

    def for_phase(self, phase: str) -> tuple[dict[str, Any], ...]:
        """Return the reachable Formula programs for one lifecycle phase."""
        if phase not in LIFECYCLE_PHASES:
            raise ValueError(f"unsupported Formula lifecycle phase: {phase}")
        return cast(tuple[dict[str, Any], ...], getattr(self, phase))


@dataclass(frozen=True)
class ReachableProgramStructure:
    """Deterministic structural facts for one exact Model-entrypoint set."""

    operation_coordinates: frozenset[OperationCoordinate]
    runtime_node_ids: frozenset[str]
    formula_programs: LifecycleFormulaPrograms


def reachable_formula_programs(
    rir: Mapping[str, Any],
    selected_entrypoints: Sequence[Mapping[str, Any]],
    *,
    phase: str,
) -> tuple[dict[str, Any], ...]:
    """Return Formula sites structurally reachable in one lifecycle phase."""
    if phase not in LIFECYCLE_PHASES:
        raise ValueError(f"unsupported Formula lifecycle phase: {phase}")
    programs = [
        program
        for program in cast(list[dict[str, Any]], rir["initialization_programs"])
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
    return tuple(
        program
        for program in programs
        if canonical_bytes(cast(JsonValue, program["target"])) in reachable_targets
    )


def project_reachable_program_structure(
    rir: Mapping[str, Any],
    selected_entrypoints: Sequence[Mapping[str, Any]],
) -> ReachableProgramStructure:
    """Project Operation and Formula structure without applying consumer policy."""
    selected = cast(Mapping[str, Any], rir["selected_semantics"])
    operations = selected_operation_index(selected)
    roots = {
        operation_coordinate(cast(Mapping[str, Any], entrypoint["operation"]))
        for entrypoint in selected_entrypoints
    }
    reachable_operations = closed_operation_coordinates(roots, operations)
    if missing := reachable_operations - operations.keys():
        raise ValueError(
            "selected Model entrypoint Operation is absent from the RIR: "
            f"{sorted(missing)!r}"
        )
    operation_node_ids = {
        cast(str, instruction["node"])
        for coordinate in reachable_operations
        for instruction in operation_body_instructions(
            cast(list[dict[str, Any]], operations[coordinate]["body"])
        )
    }

    formula_programs = LifecycleFormulaPrograms(
        initialization=reachable_formula_programs(
            rir, selected_entrypoints, phase="initialization"
        ),
        event=reachable_formula_programs(rir, selected_entrypoints, phase="event"),
        observation=reachable_formula_programs(
            rir, selected_entrypoints, phase="observation"
        ),
    )
    formula_node_ids = {
        cast(str, row["instruction"]["node"])
        for phase in LIFECYCLE_PHASES
        for program in formula_programs.for_phase(phase)
        for row in cast(list[dict[str, Any]], program["body"])
    }
    return ReachableProgramStructure(
        operation_coordinates=frozenset(reachable_operations),
        runtime_node_ids=frozenset(operation_node_ids | formula_node_ids),
        formula_programs=formula_programs,
    )
