"""Static structure and provenance projections for admitted Operations."""

from typing import Any, cast


def expanded_operation_body(
    operation: dict[str, Any],
    operations: dict[str, dict[str, Any]],
    visiting: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Expand guards and composed Operations in authored traversal order."""
    operation_id = cast(str, operation["id"])
    if operation_id in visiting:
        raise ValueError("admitted Operation composition is cyclic")
    nested_visiting = visiting | {operation_id}

    def expand(instructions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        for instruction in instructions:
            expanded.append(instruction)
            if instruction["node"] == "guard-block":
                expanded.extend(expand(cast(list[dict[str, Any]], instruction["body"])))
                continue
            if instruction["node"] not in {"invoke", "schedule"}:
                continue
            operation_ref = cast(dict[str, Any], instruction["operation"])
            invoked = operations.get(cast(str, operation_ref["id"]))
            if invoked is None:
                raise ValueError("admitted Operation composition target is absent")
            expanded.extend(
                expanded_operation_body(invoked, operations, nested_visiting)
            )
        return expanded

    return expand(cast(list[dict[str, Any]], operation["body"]))


def guard_expanded_instruction_indices(
    body: list[dict[str, Any]], *, offset: int = 0
) -> tuple[int, ...]:
    """Map top-level authored positions to guard-expanded audit positions."""
    indices: list[int] = []
    next_index = offset
    for instruction in body:
        indices.append(next_index)
        next_index += 1
        if instruction["node"] == "guard-block":
            next_index += len(cast(list[dict[str, Any]], instruction["body"]))
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
