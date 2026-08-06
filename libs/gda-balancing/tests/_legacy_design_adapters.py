"""Test-only driver for the retired Standard Schema 1.x design commands.

Production exposes Standard Schema 1.x only through ``model migrate``. These
helpers keep the historical funnel and canonical-format regressions without
reintroducing a 1.x descriptor or refusal path into the active CLI.
"""

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from gda_balancing.infrastructure.atomic_files import materialize_bytes
from gda_balancing.interfaces.cli.envelope import (
    ERROR_ENVELOPE_SCHEMA,
    internal_envelope,
    usage_envelope,
)
from gda_balancing.interfaces.cli.errors import UsageError
from gda_balancing.interfaces.cli.path_contracts import reject_input_aliasing
from gda_balancing.interfaces.cli.rendering import canonical_json, model_payload
from gda_balancing.schema import funnel
from gda_balancing.schema.funnel.preflight import MAX_DOCUMENT_BYTES
from gda_balancing.schema.refusal import (
    JSON_POINTER_PATTERN,
    REFUSAL_BOUND,
    RefusalReport,
)

RunResult = tuple[int, str, str]

_LEGACY_REFUSAL_SCHEMA: dict[str, Any] = {
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
                    "path": {
                        "type": "string",
                        "pattern": JSON_POINTER_PATTERN,
                        "anyOf": [{"const": ""}, {"pattern": "^/"}],
                    },
                    "detail": {"type": "string"},
                },
                "required": ["code", "path", "detail"],
                "additionalProperties": False,
            },
        },
        "truncated": {"type": "boolean"},
    },
    "required": ["category", "message", "refusals", "truncated"],
    "additionalProperties": False,
}

LEGACY_ERROR_ENVELOPE_SCHEMA = deepcopy(ERROR_ENVELOPE_SCHEMA)
LEGACY_ERROR_ENVELOPE_SCHEMA["properties"]["error"]["oneOf"].insert(
    0, _LEGACY_REFUSAL_SCHEMA
)


class ValidationResult(BaseModel):
    """A document that crossed the historical 1.x funnel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: Literal[True] = True


def refusal_envelope(report: RefusalReport) -> dict[str, Any]:
    """Project one historical 1.x refusal report into its former CLI shape."""
    return {
        "error": {
            "category": "refusal",
            "message": "the document was refused; see refusals",
            "refusals": [
                {"code": item.code, "path": item.path, "detail": item.detail}
                for item in report.refusals
            ],
            "truncated": report.truncated,
        }
    }


def _usage(code: str, message: str) -> RunResult:
    return 3, "", canonical_json(usage_envelope(code, message))


def _read_legacy_source(path: str) -> bytes:
    """Read the bounded source needed by the retired test-only CLI driver."""
    try:
        with Path(path).open("rb") as stream:
            return stream.read(MAX_DOCUMENT_BYTES + 1)
    except OSError as error:
        raise UsageError(
            "unreadable_input", f"cannot read input document: {path}"
        ) from error


def run_legacy_cli(argv: list[str]) -> RunResult:
    """Drive only the two retired commands needed by 1.x funnel regressions."""
    try:
        if len(argv) < 3 or argv[:2] not in (
            ["design", "validate"],
            ["design", "format"],
        ):
            return _usage("invalid_argument", "expected design validate|format PATH")
        source = argv[2]
        tail = argv[3:]
        if argv[1] == "validate" and tail:
            return _usage("unknown_argument", f"unknown argument: {tail[0]}")
        out: str | None = None
        if argv[1] == "format" and tail:
            if len(tail) != 2 or tail[0] != "--out":
                return _usage("unknown_argument", f"unknown argument: {tail[0]}")
            out = tail[1]
            reject_input_aliasing(out, source, input_is_known_path=True)

        outcome = funnel.validate(_read_legacy_source(source))
        if isinstance(outcome, RefusalReport):
            return 2, canonical_json(refusal_envelope(outcome)), ""
        if argv[1] == "validate":
            return 0, canonical_json(model_payload(ValidationResult())), ""

        body = canonical_json(model_payload(outcome))
        if out is None:
            return 0, body, ""
        try:
            materialize_bytes(Path(out), body.encode("utf-8"))
        except OSError:
            return _usage("unwritable_output", f"cannot write output file: {out}")
        receipt = {
            "artifact": {
                "path": os.path.realpath(out),
                "bytes": len(body.encode("utf-8")),
            }
        }
        return 0, canonical_json(receipt), ""
    except UsageError as error:
        return _usage(error.code, error.message)
    except Exception as error:
        message = f"the toolkit failed unexpectedly ({type(error).__name__})"
        return 4, "", canonical_json(internal_envelope(message))
