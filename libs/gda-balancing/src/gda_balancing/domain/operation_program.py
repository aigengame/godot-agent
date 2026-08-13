"""Static structure and provenance projections for admitted Operations."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias, cast


OperationCoordinate: TypeAlias = tuple[str, str, str]


@dataclass(frozen=True)
class OperationProgramProjection:
    """Authority-derived static closure for one admitted Operation."""

    reachable_operations: frozenset[OperationCoordinate]
    invocation_paths: tuple[tuple[tuple[str, ...], OperationCoordinate], ...]
    node_ids: frozenset[str]
    effects: frozenset[str]
    refusals: frozenset[str]
    resource_charge: int


def operation_coordinate(reference: Mapping[str, Any]) -> OperationCoordinate:
    """Return one exact Package Release and Operation coordinate."""
    return (
        cast(str, reference["package"]),
        cast(str, reference["version"]),
        cast(str, reference["id"]),
    )


def selected_operation_index(
    selected_semantics: Mapping[str, Any],
) -> dict[OperationCoordinate, dict[str, Any]]:
    """Index selected Operations by exact Package Release coordinate."""
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], selected_semantics["packages"])
    }
    return {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, cast(dict[str, Any], row["definition"])["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(list[dict[str, Any]], selected_semantics["operations"])
    }


def _body_instructions(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    instructions: list[dict[str, Any]] = []
    for instruction in body:
        instructions.append(instruction)
        nested = instruction.get("body")
        if isinstance(nested, list) and all(isinstance(row, dict) for row in nested):
            instructions.extend(_body_instructions(cast(list[dict[str, Any]], nested)))
    return instructions


def closed_operation_coordinates(
    selected: Collection[OperationCoordinate],
    operations: Mapping[OperationCoordinate, dict[str, Any]],
    operation_node_ids: Collection[str],
) -> set[OperationCoordinate]:
    """Close exact Operation references through every declared reference node."""
    closed = set(selected)
    pending = list(selected)
    while pending:
        operation = operations.get(pending.pop())
        if operation is None:
            continue
        for instruction in _body_instructions(
            cast(list[dict[str, Any]], operation.get("body", []))
        ):
            reference = instruction.get("operation")
            if instruction.get("node") not in operation_node_ids or not isinstance(
                reference, dict
            ):
                continue
            dependency = operation_coordinate(reference)
            if dependency not in closed:
                closed.add(dependency)
                pending.append(dependency)
    return closed


def expanded_operation_body(
    root: OperationCoordinate,
    operations: Mapping[OperationCoordinate, dict[str, Any]],
    visiting: frozenset[OperationCoordinate] = frozenset(),
) -> list[dict[str, Any]]:
    """Expand nested bodies and exact Operation references in authored order."""
    if root in visiting:
        raise ValueError("admitted Operation composition is cyclic")
    operation = operations.get(root)
    if operation is None:
        raise ValueError("admitted Operation composition target is absent")
    nested_visiting = visiting | {root}

    def expand(instructions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        for instruction in instructions:
            expanded.append(instruction)
            nested = instruction.get("body")
            if isinstance(nested, list) and all(
                isinstance(row, dict) for row in nested
            ):
                expanded.extend(expand(cast(list[dict[str, Any]], nested)))
            reference = instruction.get("operation")
            if not isinstance(reference, dict):
                continue
            expanded.extend(
                expanded_operation_body(
                    operation_coordinate(reference), operations, nested_visiting
                )
            )
        return expanded

    return expand(cast(list[dict[str, Any]], operation["body"]))


def project_operation_program(
    root: OperationCoordinate,
    operations: Mapping[OperationCoordinate, dict[str, Any]],
    *,
    operation_node_ids: Collection[str],
    invocation_node_ids: Collection[str],
) -> OperationProgramProjection:
    """Project reachable structure and synchronous declared closure."""
    reachable = closed_operation_coordinates({root}, operations, operation_node_ids)
    node_ids = {
        cast(str, instruction["node"])
        for coordinate in reachable
        if (operation := operations.get(coordinate)) is not None
        for instruction in _body_instructions(
            cast(list[dict[str, Any]], operation["body"])
        )
    }
    paths: list[tuple[tuple[str, ...], OperationCoordinate]] = []
    closure_cache: dict[
        OperationCoordinate, tuple[frozenset[str], frozenset[str], int]
    ] = {}

    def close(
        coordinate: OperationCoordinate,
        path: tuple[str, ...],
        stack: tuple[OperationCoordinate, ...],
    ) -> tuple[frozenset[str], frozenset[str], int]:
        if coordinate in stack:
            raise ValueError("admitted Operation invocation graph is cyclic")
        operation = operations.get(coordinate)
        if operation is None:
            raise ValueError("admitted Operation invocation target is absent")
        cached = closure_cache.get(coordinate)
        if cached is not None:
            return cached
        effects = set(cast(list[str], operation["effects"]))
        refusals = set(cast(list[str], operation["refusals"]))
        instructions = _body_instructions(
            cast(list[dict[str, Any]], operation["body"])
        )
        charge = len(instructions)
        for instruction in instructions:
            reference = instruction.get("operation")
            if instruction.get("node") not in invocation_node_ids or not isinstance(
                reference, dict
            ):
                continue
            child = operation_coordinate(reference)
            site = cast(str, instruction["site"])
            child_path = (*path, site)
            paths.append((child_path, child))
            child_effects, child_refusals, child_charge = close(
                child, child_path, (*stack, coordinate)
            )
            effects.update(child_effects)
            refusals.update(child_refusals)
            charge += child_charge
        closure = frozenset(effects), frozenset(refusals), charge
        closure_cache[coordinate] = closure
        return closure

    effects, refusals, charge = close(root, (), ())
    return OperationProgramProjection(
        reachable_operations=frozenset(reachable),
        invocation_paths=tuple(paths),
        node_ids=frozenset(node_ids),
        effects=effects,
        refusals=refusals,
        resource_charge=charge,
    )


def guard_expanded_instruction_indices(
    body: list[dict[str, Any]], *, offset: int = 0
) -> tuple[int, ...]:
    """Map top-level authored positions to nested-body audit positions."""
    indices: list[int] = []
    next_index = offset
    for instruction in body:
        indices.append(next_index)
        next_index += 1
        nested = instruction.get("body")
        if isinstance(nested, list):
            next_index += len(nested)
    return tuple(indices)


def instruction_evaluation_sites(operation: dict[str, Any]) -> dict[int, str]:
    """Project authored instruction positions to Formula evaluation sites."""
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


def record_instruction_evaluation_sites(
    operation: dict[str, Any],
    *,
    first_instruction_index: int,
    instruction_count: int,
    evaluation_site_identity: str,
) -> None:
    """Record one lowered Formula range in the Operation provenance extension."""
    extensions = cast(dict[str, Any], operation.setdefault("extensions", {}))
    provenance = cast(
        dict[str, Any],
        extensions.setdefault(
            "standard.instruction-provenance",
            {"kind": "instruction-evaluation-sites", "sites": []},
        ),
    )
    cast(list[dict[str, Any]], provenance["sites"]).extend(
        {
            "instruction_index": first_instruction_index + index,
            "evaluation_site_identity": evaluation_site_identity,
        }
        for index in range(instruction_count)
    )
