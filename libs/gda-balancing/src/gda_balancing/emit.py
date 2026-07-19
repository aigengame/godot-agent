"""Canonical JSON emission (bADR-0005) — the single serialization seam.

Every JSON document the toolkit emits — success results, error envelopes, and
`--schema` output — goes through :func:`canonical_json`: UTF-8, sorted object
keys, LF line endings, shortest-round-trip numbers (Python's ``json`` default),
and optional fields with defined defaults materialized explicitly (the pydantic
dump includes defaulted fields). Byte-stable output is an emergent property of
this one function.
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


def model_payload(model: BaseModel) -> dict[str, Any]:
    """Dump a typed model with its defined defaults materialized explicitly,
    rendering each field under its serialization alias (``by_alias=True``) so an
    aliased field like ``DesignDocument.schema_ref`` emits as ``"$schema"`` — the
    key the generated structural schema (also alias-keyed) validates against.
    Alias-free models are unaffected."""
    return model.model_dump(mode="json", by_alias=True)
