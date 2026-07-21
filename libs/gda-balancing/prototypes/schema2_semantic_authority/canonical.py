"""Wire-level helpers that are deliberately semantics-free."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def identity(kind: str, value: Any) -> str:
    digest = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return f"sha256:{kind}:{digest}"


def artifact(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    payload = {"kind": kind, **value}
    return {**payload, "identity": identity(kind, payload)}


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value))
