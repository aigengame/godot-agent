from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn


@dataclass(frozen=True)
class Refusal(Exception):
    stage: str
    code: str
    message: str
    location: dict[str, Any]
    terminal_evidence: dict[str, Any] | None = None

    def envelope(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "category": "refusal",
            "diagnostics": [
                {
                    "code": self.code,
                    "message": self.message,
                    "primary_location": self.location,
                    "related_locations": [],
                }
            ],
            "stage": self.stage,
            "truncated": False,
        }
        if self.terminal_evidence is not None:
            error["terminal_evidence"] = self.terminal_evidence
        return {"error": error}


def source_location(package_id: str, module_id: str, pointer: str) -> dict[str, Any]:
    return {
        "kind": "source",
        "module_id": module_id,
        "package_id": package_id,
        "span": {"pointer": pointer},
    }


def runtime_location(run_id: str, event_id: str, snapshot_id: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "kind": "runtime",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
    }


def refuse(
    stage: str,
    code: str,
    message: str,
    location: dict[str, Any],
) -> NoReturn:
    raise Refusal(stage, code, message, location)
