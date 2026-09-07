"""Private, immutable meaning owned by one checked Model request."""

from dataclasses import dataclass, fields
from typing import Any

from gda_balancing.domain.authority.context import _deep_freeze
from gda_balancing.domain.canonical import JsonValue


@dataclass(frozen=True)
class _TypedHIR:
    package_lock: dict[str, Any]
    declarations: list[dict[str, JsonValue]]
    lowering: dict[str, Any]
    source_rows: list[tuple[dict[str, Any], tuple[object, ...]]]
    formulas: list[dict[str, JsonValue]]
    formula_bindings: list[dict[str, JsonValue]]
    formula_debug_entries: list[tuple[str, str]]
    runtime_projection: dict[str, Any]
    initialization_programs: list[dict[str, Any]]
    entrypoints: list[dict[str, Any]]
    call_sites: list[dict[str, Any]]

    def __post_init__(self) -> None:
        for member in fields(self):
            object.__setattr__(
                self, member.name, _deep_freeze(getattr(self, member.name))
            )

    def __deepcopy__(self, memo: dict[int, Any]) -> "_TypedHIR":
        return self
