"""Test-only driver for the retired Standard Schema 1.x design commands.

Production exposes Standard Schema 1.x only through ``model migrate``. These
helpers keep the historical funnel and canonical-format regressions without
reintroducing a 1.x descriptor or refusal path into the active CLI.
"""

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.atomic_files import materialize_bytes
from gda_balancing.interfaces.cli.envelope import internal_envelope, usage_envelope
from gda_balancing.interfaces.cli.errors import UsageError
from gda_balancing.interfaces.cli.path_contracts import reject_input_aliasing
from gda_balancing.interfaces.cli.rendering import canonical_json, model_payload
from gda_balancing.schema import funnel
from gda_balancing.schema.refusal import RefusalReport

RunResult = tuple[int, str, str]


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

        outcome = funnel.validate(funnel.load(source))
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
    except UnreadableInputError as error:
        return _usage("unreadable_input", str(error))
    except UsageError as error:
        return _usage(error.code, error.message)
    except Exception as error:
        message = f"the toolkit failed unexpectedly ({type(error).__name__})"
        return 4, "", canonical_json(internal_envelope(message))
