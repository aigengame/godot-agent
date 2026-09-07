"""Shared CLI usage/internal errors and the fixed exit-code registry.

The current Schema 2.x refusal and command-specific error schemas are projected
by ``surface.py`` under bADR-0015 and bADR-0021. This module owns the shared
usage/internal builders and their closed field law. Optional internal diagnostics
are emitted only when requested; execution inputs and producer provenance belong
to the Experiment and its published artifacts.
"""

from typing import Any

from gda_balancing.domain.diagnostics import Schema2RefusalReport


# Exit codes (bADR-0008). Channel follows meaning: exits 0-2 write stdout;
# exits 3/4 keep stdout empty and write exactly one envelope to stderr.
EXIT_SUCCESS = 0
EXIT_VERDICT_FAIL = 1  # reserved for the Phase-2 verdict channel (#509)
EXIT_REFUSAL = 2  # typed refusals; first emitted by #504
EXIT_USAGE = 3
EXIT_INTERNAL = 4

# The CLI-usage code family — the one family the CLI contract mints (v1 set).
USAGE_CODES = frozenset(
    {
        "missing_command",
        "unknown_command",
        "unknown_argument",
        "argument_conflict",
        "invalid_argument",
        "unreadable_input",
        "unwritable_output",
        "invocation_key_conflict",
    }
)

# The single fixed internal code, in the same registry.
INTERNAL_ERROR = "internal_error"

CLI_ERROR_CODES = USAGE_CODES | {INTERNAL_ERROR}

USAGE_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"const": "usage"},
        "code": {"enum": sorted(USAGE_CODES)},
        "message": {"type": "string"},
    },
    "required": ["category", "code", "message"],
    "additionalProperties": False,
}

INTERNAL_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"const": "internal"},
        "code": {"const": INTERNAL_ERROR},
        "message": {"type": "string"},
        "diagnostics": {"type": "string"},
    },
    "required": ["category", "code", "message"],
    "additionalProperties": False,
}

# Closed non-domain failures shared by the active CLI and its tests. Typed
# Schema 2.x refusals are descriptor-owned and projected in ``surface.py``.
ERROR_ENVELOPE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Error envelope",
    "type": "object",
    "properties": {"error": {"oneOf": [USAGE_ERROR_SCHEMA, INTERNAL_ERROR_SCHEMA]}},
    "required": ["error"],
    "additionalProperties": False,
}


def schema2_refusal_envelope(report: Schema2RefusalReport) -> dict[str, object]:
    """Build the closed Schema 2.0 refusal Error envelope."""
    error: dict[str, object] = {
        "category": "refusal",
        "stage": report.stage,
        "diagnostics": [item.model_dump(mode="json") for item in report.diagnostics],
        "truncated": report.truncated,
    }
    if report.terminal_audit is not None:
        if report.stage != "runtime":
            raise ValueError("a terminal audit belongs only to runtime refusal")
        error["terminal_audit"] = report.terminal_audit
    return {"error": error}


def usage_envelope(code: str, message: str) -> dict[str, Any]:
    """Build a `usage` envelope carrying exactly the permitted members."""
    if code not in USAGE_CODES:
        raise ValueError(f"not a registered CLI-usage code: {code!r}")
    return {"error": {"category": "usage", "code": code, "message": message}}


def internal_envelope(message: str, diagnostics: str | None = None) -> dict[str, Any]:
    """Build an `internal` envelope; ``diagnostics`` only under ``--debug``."""
    error: dict[str, Any] = {
        "category": "internal",
        "code": INTERNAL_ERROR,
        "message": message,
    }
    if diagnostics is not None:
        error["diagnostics"] = diagnostics
    return {"error": error}
