"""Canonical JSON emission (bADR-0005) — the single serialization seam.

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


def model_payload(model: BaseModel) -> dict[str, Any]:
    """Dump a typed model as its canonical payload, rendering each field under
    its serialization alias (``by_alias=True``) so an aliased field like
    ``DesignDocument.schema_ref`` emits as ``"$schema"`` — the key the generated
    structural schema (also alias-keyed) validates against. Alias-free models are
    unaffected.

    ``exclude_none=True`` realizes the absent-or-typed contract: an optional
    member left at its ``None`` sentinel is *omitted*, never materialized as
    ``null`` — the emission mirror of the published schema's dropped null arms
    (:mod:`gda_balancing.schema.artifacts`). Genuine domain defaults are not
    ``None`` (``accepts`` defaults to ``()``, the sections to empty models), so
    they still materialize. A ``dict``-rooted artifact model (the structural
    schema, the catalog) carries no ``None`` values after that null-arm
    stripping, so ``exclude_none`` cannot corrupt it (pinned in
    ``test_emit.py``)."""
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
