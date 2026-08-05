"""The closed Error envelope, the CLI error-code registry, and exit codes.

bADR-0008 is the authority. The envelope is the single top-level-``error``
JSON object a failed invocation emits; its schema is closed (no member beyond
the field law is permitted) and byte-identical across every command's
``--schema`` output. This module is the one registry both dispatch and the
conformance harness read — there is no second list of codes anywhere.

Field law (bADR-0008): ``category`` and ``message`` are required in every
envelope. ``refusal`` requires ``refusals`` (non-empty) and ``truncated`` and
forbids an envelope-level ``code``; ``usage``/``internal`` require ``code`` and
forbid ``refusals``/``truncated``. The only optional members are
``diagnostics`` (``internal`` only, populated only under ``--debug``) and
``reproduction`` (carried once a stochastic run has drawn its seed — no v1
command is stochastic, bADR-0010).
"""

from typing import Any

from gda_balancing.schema.refusal import (
    JSON_POINTER_PATTERN,
    REFUSAL_BOUND,
    RefusalReport,
)


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

# RFC 6901 JSON Pointer ("" is the whole document; each token escapes ~ and /).
_JSON_POINTER_PATTERN = JSON_POINTER_PATTERN

# The published-schema form of the constraint. Sharing the regex TEXT alone
# is not engine-stable: Python's `re` (the jsonschema validator) lets the
# terminal `$` also match before a trailing newline, so a lone "\n" would
# satisfy the pattern via zero repetitions — while pydantic's Rust engine
# (the model side) anchors `$` at true end-of-text and rejects it. RFC 6901
# requires empty-or-leading-"/", encoded here explicitly without relying on
# `$` semantics; the sibling `pattern` keeps the token-escape validity.
_JSON_POINTER_SCHEMA: dict[str, Any] = {
    "type": "string",
    "pattern": _JSON_POINTER_PATTERN,
    "anyOf": [{"const": ""}, {"pattern": "^/"}],
}


_REPRODUCTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "seed": {"type": "integer", "minimum": 0, "exclusiveMaximum": 2**32},
        "toolkit_version": {"type": "string"},
    },
    "required": ["seed", "toolkit_version"],
    "additionalProperties": False,
}

# The closed envelope schema — the `error` key of every command's `--schema`
# output, byte-identical across the surface (bADR-0009). The `refusal` branch
# is part of the contract from day one even though #502 never emits it; its
# per-refusal codes belong to the funnel (bADR-0004), not this registry.
ERROR_ENVELOPE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Error envelope",
    "type": "object",
    "properties": {
        "error": {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "category": {"const": "refusal"},
                        "message": {"type": "string"},
                        "refusals": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": REFUSAL_BOUND,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "code": {"type": "string"},
                                    "path": _JSON_POINTER_SCHEMA,
                                    "detail": {"type": "string"},
                                },
                                "required": ["code", "path", "detail"],
                                "additionalProperties": False,
                            },
                        },
                        "truncated": {"type": "boolean"},
                        "reproduction": _REPRODUCTION_SCHEMA,
                    },
                    "required": ["category", "message", "refusals", "truncated"],
                    "additionalProperties": False,
                },
                {
                    # No `reproduction` member: a usage error is resolved at
                    # binding, before execution starts, so an effective seed
                    # can never have been drawn (bADR-0008/0010).
                    "type": "object",
                    "properties": {
                        "category": {"const": "usage"},
                        "code": {"enum": sorted(USAGE_CODES)},
                        "message": {"type": "string"},
                    },
                    "required": ["category", "code", "message"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "category": {"const": "internal"},
                        "code": {"const": INTERNAL_ERROR},
                        "message": {"type": "string"},
                        "diagnostics": {"type": "string"},
                        "reproduction": _REPRODUCTION_SCHEMA,
                    },
                    "required": ["category", "code", "message"],
                    "additionalProperties": False,
                },
            ]
        }
    },
    "required": ["error"],
    "additionalProperties": False,
}


def refusal_envelope(report: RefusalReport) -> dict[str, Any]:
    """Build a `refusal` envelope carrying the report's refusals verbatim.

    Items are projected field-by-field, not ``model_dump``ed: a `Refusal`
    subclass could otherwise serialize extra fields past the closed
    (additionalProperties: false) item schema — the envelope's shape is
    owned here, never by whatever runtime type the handler supplied.
    """
    return {
        "error": {
            "category": "refusal",
            "message": "the document was refused; see refusals",
            "refusals": [
                {"code": r.code, "path": r.path, "detail": r.detail}
                for r in report.refusals
            ],
            "truncated": report.truncated,
        }
    }


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
