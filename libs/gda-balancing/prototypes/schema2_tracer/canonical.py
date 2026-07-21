from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    """Return the prototype's canonical UTF-8 JSON encoding."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def identified(kind: str, content: dict[str, Any]) -> dict[str, Any]:
    payload = {"artifact_kind": kind, "content": content}
    return {**payload, "identity": content_identity(payload)}


def canonical_line(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"
