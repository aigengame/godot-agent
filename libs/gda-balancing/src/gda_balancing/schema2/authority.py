"""Loader for the permanent, packaged Kernel/LDB authority artifacts.

The JSON resources are the language authority.  This host module only reads,
independently admits, and defensively copies them; changing Python dispatch
cannot silently add a law, rule, diagnostic, or package to the language.
"""

import json
import re
from copy import deepcopy
from importlib.resources import files
from typing import Any

from gda_balancing.schema2.authority_graph import (
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.schema2.bootstrap import admit_authorities

_AUTHORITY_PACKAGE = "gda_balancing.schema2.authorities"
_BOOTSTRAP_MAX_AUTHORITY_BYTES = 262144
_BOOTSTRAP_MAX_NESTING_DEPTH = 32
_BOOTSTRAP_MAX_PACKAGE_MEMBERS = 256
_PACKAGE_COORDINATE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*@[0-9]+\.[0-9]+\.[0-9]+$"
)


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


def _load(name: str, subject: str) -> tuple[dict[str, Any], int]:
    resource = files(_AUTHORITY_PACKAGE).joinpath(*name.split("/"))
    try:
        data = resource.read_bytes()
    except OSError as err:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is unreadable: {err}",
        ) from err
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
    return _decode_authority(text, name, subject), len(data)


def _package_resource_name(descriptor: dict[str, Any]) -> str:
    package_id = descriptor.get("id")
    version = descriptor.get("version")
    coordinate = f"{package_id}@{version}"
    if (
        not isinstance(package_id, str)
        or not isinstance(version, str)
        or _PACKAGE_COORDINATE.fullmatch(coordinate) is None
    ):
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="language-bundle.package_descriptors",
            message="package descriptor coordinate is not a safe canonical coordinate",
        )
    return f"packages/{coordinate}.json"


def load_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Load the exact graph and return its fresh, derived consumer index."""
    kernel, _kernel_size = _load("kernel.json", "kernel")
    root, _root_size = _load("language-bundle.json", "language-bundle")
    descriptors = root.get("package_descriptors")
    if not isinstance(descriptors, list) or not (
        1 <= len(descriptors) <= _BOOTSTRAP_MAX_PACKAGE_MEMBERS
    ):
        raise AuthorityLoadError(
            code="kernel.resource_exhausted",
            subject="language-bundle.package_descriptors",
            message="package descriptor count exceeds the bootstrap bound",
        )
    releases: list[dict[str, Any]] = []
    member_byte_sizes: list[int] = []
    for index, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, dict):
            raise AuthorityLoadError(
                code="kernel.member_set_mismatch",
                subject=f"language-bundle.package_descriptors.{index}",
                message="package descriptor is not an object",
            )
        name = _package_resource_name(descriptor)
        release, byte_size = _load(
            name, f"language-bundle.package_descriptors.{index}"
        )
        releases.append(release)
        member_byte_sizes.append(byte_size)
    required_language_members = kernel.get("admission", {}).get(
        "required_language_members"
    )
    if not isinstance(required_language_members, list) or not all(
        isinstance(item, str) for item in required_language_members
    ):
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="kernel.admission.required_language_members",
            message="kernel does not declare the admitted language index members",
        )
    try:
        index = derive_language_index(
            root,
            releases,
            required_language_members,
            member_byte_sizes=member_byte_sizes,
        )
    except ValueError as err:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="language-bundle.package_descriptors",
            message=str(err),
        ) from err
    return kernel, index


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
