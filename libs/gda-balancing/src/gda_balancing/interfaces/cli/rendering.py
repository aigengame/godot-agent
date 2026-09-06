"""Canonical CLI JSON rendering (bADR-0005).

Every JSON document the toolkit emits — success results, error envelopes, and
`--schema` output — goes through :func:`canonical_json`: UTF-8, sorted object
keys, LF line endings, shortest-round-trip numbers (Python's ``json`` default),
and only genuine domain defaults materialized explicitly (``accepts: []``, the
empty designed sections). An **optional member is absent-or-typed, never null**
(bADR-0005; PR #527 multi#4): an absent optional is omitted, not emitted as
``null`` — so :func:`model_payload` dumps with ``exclude_none=True``. Byte-stable
output is an emergent property of this one function.
"""

import json
from typing import Any

from pydantic import BaseModel


def canonical_json(payload: Any) -> str:
    """Render ``payload`` as one canonical JSON document ending in a single LF.

    ``allow_nan=False``: NaN/±Infinity are not JSON, so a non-finite value
    reaching this seam is a toolkit bug and raises (→ `internal`/exit 4) —
    the one sanctioned non-finite path is the upstream Evaluation refusal
    (bADR-0003/0004), which never lets such a value reach emission.
    """
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )


def indented_json(payload: Any) -> str:
    """Render deterministic human-readable JSON without changing its value."""
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    )


def model_payload(model: BaseModel) -> dict[str, Any]:
    """Serialize declared aliases and omit absent optional model fields.

    Mapping contents remain authored data: ``exclude_none`` controls model
    fields and does not remove null values inside a mapping.
    """
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
