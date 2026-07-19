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
    """Render ``payload`` as one canonical JSON document ending in a single LF."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


def model_payload(model: BaseModel) -> dict[str, Any]:
    """Dump a typed model with its defined defaults materialized explicitly."""
    return model.model_dump(mode="json")
