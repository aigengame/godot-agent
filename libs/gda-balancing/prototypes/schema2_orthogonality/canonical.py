"""Canonical wire helpers; deliberately contains no language or game semantics."""

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


def identity(domain: str, value: Any) -> str:
    return f"sha256:{domain}:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def artifact(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    payload = {"kind": kind, **value}
    return {**payload, "identity": identity(kind, payload)}


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def verify_artifact(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    kind = value.get("kind")
    claimed = value.get("identity")
    if not isinstance(kind, str) or not isinstance(claimed, str):
        return False
    bare = {key: item for key, item in value.items() if key != "identity"}
    return claimed == identity(kind, bare)
