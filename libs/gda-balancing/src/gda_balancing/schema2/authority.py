"""Loader for the permanent, packaged Kernel/LDB authority artifacts.

The JSON resources are the language authority.  This host module only reads,
independently admits, and defensively copies them; changing Python dispatch
cannot silently add a law, rule, diagnostic, or package to the language.
"""

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from gda_balancing.schema2.bootstrap import admit_authorities

_AUTHORITY_PACKAGE = "gda_balancing.schema2.authorities"
_BOOTSTRAP_MAX_AUTHORITY_BYTES = 262144
_BOOTSTRAP_MAX_NESTING_DEPTH = 32


class AuthorityLoadError(Exception):
    """A candidate authority failed the non-self-hosted ingress preflight."""

    stage = "ingress"

    def __init__(self, *, code: str, subject: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.subject = subject
        self.message = message


def _raw_nesting_depth(data: bytes) -> int:
    depth = 0
    maximum = 0
    in_string = False
    escaped = False
    for byte in data:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            maximum = max(maximum, depth)
        elif byte in (0x7D, 0x5D):
            depth -= 1
    return maximum


def _decode_authority(text: str, name: str, subject: str) -> dict[str, Any]:
    def reject_number(_value: str) -> Any:
        raise ValueError("non-integer number")

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate object key: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            text,
            object_pairs_hook=closed_object,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as err:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is not canonical JSON: {err}",
        ) from err
    if not isinstance(value, dict):
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is not an object",
        )
    return value


def _load(name: str) -> dict[str, Any]:
    resource = files(_AUTHORITY_PACKAGE).joinpath(name)
    data = resource.read_bytes()
    subject = "kernel" if name == "kernel.json" else "language-bundle"
    if (
        len(data) > _BOOTSTRAP_MAX_AUTHORITY_BYTES
        or _raw_nesting_depth(data) > _BOOTSTRAP_MAX_NESTING_DEPTH
    ):
        raise AuthorityLoadError(
            code="kernel.resource_exhausted",
            subject=subject,
            message=f"packaged authority {name} exceeds the raw ingress bound",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is not UTF-8",
        ) from err
    return _decode_authority(text, name, subject)


def load_authorities() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load fresh copies of both packaged authority artifacts."""
    return _load("kernel.json"), _load("language-bundle.json")


def authority_set() -> dict[str, Any]:
    """Return a defensive copy of the independently admitted authority pair."""
    kernel, ldb = load_authorities()
    admission = admit_authorities(kernel, ldb)
    return {
        "kernel": deepcopy(kernel),
        "language_bundle": deepcopy(ldb),
        "admission": {
            "admitted": admission.admitted,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }
