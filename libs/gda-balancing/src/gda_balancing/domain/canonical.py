"""Canonical bytes and content identities fixed by the Schema 2.0 Kernel.

The profile intentionally admits a small JSON subset.  It is sufficient for
the bootstrap authorities and removes host-dependent float, Unicode
normalisation, and object-order behaviour from their identity.
"""

import hashlib
import json
from typing import Any, TypeAlias, cast

JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def canonical_bytes(value: JsonValue) -> bytes:
    """Encode one value under ``gda-canonical-json-v1``.

    Objects are sorted by their UTF-8 key bytes, whitespace is absent, strings
    are emitted as UTF-8 without normalisation, and integers are signed Int64.
    Floats and lone surrogate code points are outside the profile.
    """
    _validate(value)
    materialized = _materialize(value)
    return (
        json.dumps(
            materialized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _materialize(value: JsonValue) -> JsonValue:
    """Copy dict/list-compatible immutable views into JSON builtin containers."""
    if isinstance(value, list):
        return [_materialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _materialize(item) for key, item in value.items()}
    return value


def content_identity(domain: str, value: JsonValue) -> str:
    """Return the domain-separated SHA-256 identity of ``value``."""
    prefix = f"gda-balancing:{domain}:".encode()
    return "sha256:" + hashlib.sha256(prefix + canonical_bytes(value)).hexdigest()


def parse_canonical_object(data: bytes, *, artifact_name: str) -> dict[str, Any]:
    """Decode one closed canonical-JSON object without losing duplicate keys."""

    def reject_number(_value: str) -> Any:
        raise ValueError("non-integer number")

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate object key: {key!r}")
            value[key] = item
        return value

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=closed_object,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
        if not isinstance(value, dict):
            raise ValueError(f"{artifact_name} must be an object")
        canonical_bytes(cast(JsonValue, value))
    except RecursionError as err:
        raise ValueError("JSON nesting exceeds decoder capacity") from err
    return value


def _validate(value: JsonValue) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("lone surrogate is outside canonical JSON") from exc
        return
    if isinstance(value, int):
        if not _INT64_MIN <= value <= _INT64_MAX:
            raise ValueError("integer is outside signed Int64")
        return
    if isinstance(value, list):
        for item in value:
            _validate(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            _validate(key)
            _validate(item)
        return
    raise TypeError(f"value of type {type(value).__name__} is outside canonical JSON")
