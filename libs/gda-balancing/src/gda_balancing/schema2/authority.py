"""Loader for the permanent, packaged Kernel/LDB authority artifacts.

The JSON resources are the language authority.  This host module only reads,
independently admits, and defensively copies them; changing Python dispatch
cannot silently add a law, rule, diagnostic, or package to the language.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Never, cast

from gda_balancing.schema2.authority_graph import (
    LanguageBundleGraph,
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.schema2.bootstrap import BootstrapAdmission, admit_authorities
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes

_AUTHORITY_PACKAGE = "gda_balancing.schema2.authorities"
_BOOTSTRAP_MAX_AUTHORITY_BYTES = 262144
_BOOTSTRAP_MAX_NESTING_DEPTH = 32
_BOOTSTRAP_MAX_PACKAGE_MEMBERS = 256


class _FrozenDict(dict[Any, Any]):
    """A dict-compatible read-only view for admitted authority data."""

    @staticmethod
    def _reject(*_args: Any, **_kwargs: Any) -> Never:
        raise TypeError("admitted authority data is immutable")

    __setitem__ = _reject
    __delitem__ = _reject
    clear = _reject
    pop = _reject
    popitem = _reject
    setdefault = _reject
    update = _reject
    __ior__ = _reject

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        duplicate = deepcopy(dict(self), memo)
        memo[id(self)] = duplicate
        return duplicate


class _FrozenList(list[Any]):
    """A list-compatible read-only view for admitted authority data."""

    @staticmethod
    def _reject(*_args: Any, **_kwargs: Any) -> Never:
        raise TypeError("admitted authority data is immutable")

    __setitem__ = _reject
    __delitem__ = _reject
    append = _reject
    clear = _reject
    extend = _reject
    insert = _reject
    pop = _reject
    remove = _reject
    reverse = _reject
    sort = _reject
    __iadd__ = _reject
    __imul__ = _reject

    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        duplicate = deepcopy(list(self), memo)
        memo[id(self)] = duplicate
        return duplicate


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, _FrozenLanguageBundleIndex):
        return value
    if isinstance(value, LanguageBundleIndex):
        return _FrozenLanguageBundleIndex(value)
    if isinstance(value, dict):
        return _FrozenDict({key: _deep_freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return _FrozenList(_deep_freeze(child) for child in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(child) for child in value)
    return value


class _FrozenLanguageBundleIndex(LanguageBundleIndex):
    """LanguageBundleIndex preserving dict compatibility without writable aliases."""

    def __init__(self, source: LanguageBundleIndex) -> None:
        self._authority_frozen = False
        super().__init__(
            deepcopy(dict(source)),
            root=deepcopy(source.root),
            package_releases=deepcopy(source.package_releases),
            package_conformance_vector_sets=deepcopy(
                source.package_conformance_vector_sets
            ),
            root_byte_size=source.root_byte_size,
            package_byte_sizes=list(source.package_byte_sizes),
            vector_set_byte_sizes=list(source.vector_set_byte_sizes),
        )
        for key, child in list(dict.items(self)):
            dict.__setitem__(self, key, _deep_freeze(child))
        self.root = _deep_freeze(self.root)
        self.package_releases = _deep_freeze(self.package_releases)
        self.package_conformance_vector_sets = _deep_freeze(
            self.package_conformance_vector_sets
        )
        self._authority_frozen = True

    def _reject_when_frozen(self) -> None:
        if self._authority_frozen:
            raise TypeError("admitted authority data is immutable")

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_authority_frozen", False):
            raise TypeError("admitted authority data is immutable")
        super().__setattr__(name, value)

    def __setitem__(self, key: str, value: Any) -> None:
        self._reject_when_frozen()
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self._reject_when_frozen()
        super().__delitem__(key)

    def clear(self) -> None:
        self._reject_when_frozen()
        super().clear()

    def pop(self, key: str, default: Any = None) -> Any:
        self._reject_when_frozen()
        return super().pop(key, default)

    def popitem(self) -> tuple[str, Any]:
        self._reject_when_frozen()
        return super().popitem()

    def setdefault(self, key: str, default: Any = None) -> Any:
        self._reject_when_frozen()
        return super().setdefault(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._reject_when_frozen()
        super().update(*args, **kwargs)

    def __ior__(self, value: Any) -> "_FrozenLanguageBundleIndex":
        self._reject_when_frozen()
        super().__ior__(value)
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> LanguageBundleIndex:
        duplicate = LanguageBundleIndex(
            deepcopy(dict(self), memo),
            root=deepcopy(self.root, memo),
            package_releases=deepcopy(self.package_releases, memo),
            package_conformance_vector_sets=deepcopy(
                self.package_conformance_vector_sets, memo
            ),
            root_byte_size=self.root_byte_size,
            package_byte_sizes=list(self.package_byte_sizes),
            vector_set_byte_sizes=list(self.vector_set_byte_sizes),
        )
        memo[id(self)] = duplicate
        return duplicate


def _language_bundle_canonical_bytes(language_bundle: dict[str, Any]) -> bytes:
    if not isinstance(language_bundle, LanguageBundleIndex):
        return canonical_bytes(cast(JsonValue, language_bundle))
    graph: dict[str, JsonValue] = {
        "root": cast(JsonValue, language_bundle.root),
        "package_releases": cast(JsonValue, language_bundle.package_releases),
        "package_conformance_vector_sets": cast(
            JsonValue, language_bundle.package_conformance_vector_sets
        ),
        "root_byte_size": language_bundle.root_byte_size,
        "package_byte_sizes": list(language_bundle.package_byte_sizes),
        "vector_set_byte_sizes": list(language_bundle.vector_set_byte_sizes),
    }
    return canonical_bytes(graph)


@dataclass(frozen=True)
class AdmittedAuthorityContext:
    """One exact, deeply immutable admitted Kernel/LDB lifecycle."""

    kernel: dict[str, Any]
    language_bundle: dict[str, Any]
    admission: BootstrapAdmission
    canonical_kernel_bytes: bytes
    canonical_language_bundle_bytes: bytes

    def mutable_pair(self) -> tuple[dict[str, Any], LanguageBundleIndex]:
        """Return an independently owned candidate for mutation/conformance tests."""
        language_bundle = deepcopy(self.language_bundle)
        if not isinstance(language_bundle, LanguageBundleIndex):
            raise TypeError("admitted authority context has no sealed LDB graph")
        return deepcopy(self.kernel), language_bundle


AuthorityProviderValue = (
    AdmittedAuthorityContext | tuple[dict[str, Any], dict[str, Any]]
)
AuthorityContextProvider = Callable[[], AuthorityProviderValue]

_PACKAGED_CONTEXT_LOCK = threading.Lock()
_PACKAGED_CONTEXT: AdmittedAuthorityContext | None = None
_PACKAGED_CONTEXT_ERROR: AuthorityLoadError | None = None
_PACKAGED_CONTEXT_ADMISSION_ATTEMPTS = 0


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


def _load(
    name: str,
    subject: str,
    *,
    max_bytes: int = _BOOTSTRAP_MAX_AUTHORITY_BYTES,
    require_canonical_bytes: bool = True,
) -> tuple[dict[str, Any], int]:
    resource = files(_AUTHORITY_PACKAGE).joinpath(*name.split("/"))
    try:
        data = resource.read_bytes()
    except OSError as err:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is unreadable: {err}",
        ) from err
    if len(data) > max_bytes or _raw_nesting_depth(data) > _BOOTSTRAP_MAX_NESTING_DEPTH:
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
    decoded = _decode_authority(text, name, subject)
    try:
        canonical = canonical_bytes(cast(JsonValue, decoded))
    except (TypeError, ValueError, UnicodeEncodeError) as err:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is outside canonical JSON: {err}",
        ) from err
    if require_canonical_bytes and data != canonical:
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject=subject,
            message=f"packaged authority {name} is not encoded as canonical JSON bytes",
        )
    return decoded, len(canonical if require_canonical_bytes else data)


def _matches_coordinate_contract(value: Any, contract: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or not isinstance(contract, dict)
        or contract.get("type") != "non-empty-string"
        or not isinstance(contract.get("pattern"), str)
    ):
        return False
    try:
        return re.fullmatch(cast(str, contract["pattern"]), value) is not None
    except re.error:
        return False


def _package_resource_names(
    descriptor: dict[str, Any], kernel: dict[str, Any]
) -> tuple[str, str]:
    package_id = descriptor.get("id")
    version = descriptor.get("version")
    field_types = (
        kernel.get("meta_format", {})
        .get("language_bundle", {})
        .get("package_descriptor", {})
        .get("field_types")
    )
    id_contract = field_types.get("id") if isinstance(field_types, dict) else None
    version_contract = (
        field_types.get("version") if isinstance(field_types, dict) else None
    )
    if (
        not _matches_coordinate_contract(package_id, id_contract)
        or not _matches_coordinate_contract(version, version_contract)
        or "/" in cast(str, package_id)
        or "\\" in cast(str, package_id)
        or "/" in cast(str, version)
        or "\\" in cast(str, version)
    ):
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="language-bundle.package_descriptors",
            message="package descriptor coordinate is not a safe canonical coordinate",
        )
    safe_package_id = cast(str, package_id)
    safe_version = cast(str, version)
    coordinate = f"{safe_package_id}@{safe_version}"
    directory = safe_package_id.replace(".", "-")
    prefix = f"packages/{directory}/{coordinate}"
    return f"{prefix}.json", f"{prefix}.conformance-vectors.json"


def _freeze_admitted_context(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    admission: BootstrapAdmission,
) -> AdmittedAuthorityContext:
    if not admission.admitted:
        raise ValueError(
            "cannot construct an admitted context from refused authorities"
        )
    if admission.kernel_identity != kernel.get(
        "content_identity"
    ) or admission.language_bundle_identity != language_bundle.get("content_identity"):
        raise ValueError("authority admission belongs to another Kernel/LDB pair")
    frozen_kernel = cast(dict[str, Any], _deep_freeze(kernel))
    frozen_language_bundle = cast(dict[str, Any], _deep_freeze(language_bundle))
    return AdmittedAuthorityContext(
        kernel=frozen_kernel,
        language_bundle=frozen_language_bundle,
        admission=admission,
        canonical_kernel_bytes=canonical_bytes(cast(JsonValue, kernel)),
        canonical_language_bundle_bytes=_language_bundle_canonical_bytes(
            language_bundle
        ),
    )


def admit_authority_context(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    *,
    admission: BootstrapAdmission | None = None,
) -> AdmittedAuthorityContext | BootstrapAdmission:
    """Admit one injected candidate into its own immutable lifecycle."""
    resolved_admission = admission or admit_authorities(kernel, language_bundle)
    if not resolved_admission.admitted:
        return resolved_admission
    return _freeze_admitted_context(kernel, language_bundle, resolved_admission)


def resolve_authority_context(
    provider: AuthorityContextProvider,
) -> AdmittedAuthorityContext | BootstrapAdmission:
    """Resolve either a packaged context provider or an injected authority pair."""
    value = provider()
    if isinstance(value, AdmittedAuthorityContext):
        return value
    kernel, language_bundle = value
    return admit_authority_context(kernel, language_bundle)


def _load_packaged_authority_context_uncached() -> AdmittedAuthorityContext:
    """Load, atomically admit, index, and freeze the exact packaged graph."""
    kernel, _kernel_size = _load("kernel.json", "kernel", require_canonical_bytes=False)
    resources = kernel.get("resources")
    if not isinstance(resources, dict):
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="kernel.resources",
            message="kernel resource bounds are absent",
        )
    root_limit = resources.get("max_ldb_root_bytes")
    child_limit = resources.get("max_ldb_child_bytes")
    package_limit = resources.get("max_ldb_package_count")
    if not all(
        isinstance(value, int) and value > 0
        for value in (root_limit, child_limit, package_limit)
    ):
        raise AuthorityLoadError(
            code="kernel.resource_exhausted",
            subject="kernel.resources",
            message="kernel graph resource bounds are invalid",
        )
    root_limit = cast(int, root_limit)
    child_limit = cast(int, child_limit)
    package_limit = cast(int, package_limit)
    root, root_size = _load(
        "language-bundle.json",
        "language-bundle",
        max_bytes=root_limit,
    )
    descriptors = root.get("package_descriptors")
    if not isinstance(descriptors, list) or not (
        1 <= len(descriptors) <= min(package_limit, _BOOTSTRAP_MAX_PACKAGE_MEMBERS)
    ):
        raise AuthorityLoadError(
            code="kernel.resource_exhausted",
            subject="language-bundle.package_descriptors",
            message="package descriptor count exceeds the bootstrap bound",
        )
    releases: list[dict[str, Any]] = []
    vector_sets: list[dict[str, Any]] = []
    package_byte_sizes: list[int] = []
    vector_set_byte_sizes: list[int] = []
    for index, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, dict):
            raise AuthorityLoadError(
                code="kernel.member_set_mismatch",
                subject=f"language-bundle.package_descriptors.{index}",
                message="package descriptor is not an object",
            )
        release_name, vector_set_name = _package_resource_names(descriptor, kernel)
        release, release_byte_size = _load(
            release_name,
            f"language-bundle.package_descriptors.{index}",
            max_bytes=child_limit,
        )
        vector_set, vector_set_byte_size = _load(
            vector_set_name,
            f"language-bundle.package_descriptors.{index}.conformance_vectors",
            max_bytes=child_limit,
        )
        releases.append(release)
        vector_sets.append(vector_set)
        package_byte_sizes.append(release_byte_size)
        vector_set_byte_sizes.append(vector_set_byte_size)
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
    descriptor_order = (
        kernel.get("meta_format", {})
        .get("language_bundle", {})
        .get("package_descriptor", {})
        .get("canonical_order")
    )
    if not isinstance(descriptor_order, list) or not all(
        isinstance(item, str) for item in descriptor_order
    ):
        raise AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="kernel.meta_format.language_bundle.package_descriptor",
            message="kernel does not declare the package descriptor order",
        )
    graph = LanguageBundleGraph(
        root=root,
        package_releases=releases,
        package_conformance_vector_sets=vector_sets,
        root_byte_size=root_size,
        package_byte_sizes=package_byte_sizes,
        vector_set_byte_sizes=vector_set_byte_sizes,
    )
    admission = admit_authorities(kernel, graph)
    if not admission.admitted:
        diagnostic = admission.diagnostics[0]
        raise AuthorityLoadError(
            code=diagnostic.code,
            subject=diagnostic.subject,
            message="packaged authority graph failed atomic admission",
        )
    index = derive_language_index(
        root,
        releases,
        vector_sets,
        required_language_members,
        root_byte_size=root_size,
        package_byte_sizes=package_byte_sizes,
        vector_set_byte_sizes=vector_set_byte_sizes,
        descriptor_order=descriptor_order,
    )
    return _freeze_admitted_context(kernel, index, admission)


def packaged_authority_context() -> AdmittedAuthorityContext:
    """Return the one process-scoped packaged authority context.

    Initialization is single-flight under the lifecycle lock. A failed packaged
    admission is remembered so concurrent and later callers observe the same
    deterministic ingress refusal rather than a partially initialized context.
    """
    global _PACKAGED_CONTEXT
    global _PACKAGED_CONTEXT_ERROR
    global _PACKAGED_CONTEXT_ADMISSION_ATTEMPTS

    with _PACKAGED_CONTEXT_LOCK:
        if _PACKAGED_CONTEXT is not None:
            return _PACKAGED_CONTEXT
        if _PACKAGED_CONTEXT_ERROR is not None:
            raise AuthorityLoadError(
                code=_PACKAGED_CONTEXT_ERROR.code,
                subject=_PACKAGED_CONTEXT_ERROR.subject,
                message=_PACKAGED_CONTEXT_ERROR.message,
            )
        try:
            _PACKAGED_CONTEXT_ADMISSION_ATTEMPTS += 1
            context = _load_packaged_authority_context_uncached()
        except AuthorityLoadError as err:
            _PACKAGED_CONTEXT_ERROR = err
            raise
        _PACKAGED_CONTEXT = context
        return context


def reset_packaged_authority_context_for_tests() -> None:
    """Clear the process context for deterministic lifecycle/fault tests only."""
    global _PACKAGED_CONTEXT
    global _PACKAGED_CONTEXT_ERROR
    global _PACKAGED_CONTEXT_ADMISSION_ATTEMPTS

    with _PACKAGED_CONTEXT_LOCK:
        _PACKAGED_CONTEXT = None
        _PACKAGED_CONTEXT_ERROR = None
        _PACKAGED_CONTEXT_ADMISSION_ATTEMPTS = 0


def authority_lifecycle_metrics() -> dict[str, int]:
    """Return deterministic process-cache counters for tests and diagnostics."""
    with _PACKAGED_CONTEXT_LOCK:
        return {
            "packaged_admission_attempts": _PACKAGED_CONTEXT_ADMISSION_ATTEMPTS,
            "packaged_context_published": int(_PACKAGED_CONTEXT is not None),
            "packaged_refusal_published": int(_PACKAGED_CONTEXT_ERROR is not None),
        }


def load_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Load a fresh mutable candidate for mutation and loader-conformance tests.

    Production consumers use :func:`packaged_authority_context`; this boundary
    deliberately returns independently owned values so injected mutations can
    never alias or poison the process-scoped admitted context.
    """
    return _load_packaged_authority_context_uncached().mutable_pair()


def load_descriptor_authorities() -> tuple[dict[str, Any], dict[str, Any]]:
    """Borrow the immutable packaged pair while assembling command descriptors."""
    context = packaged_authority_context()
    return context.kernel, context.language_bundle


def authority_set() -> dict[str, Any]:
    """Return one mutable copy of the exact already-admitted authority context."""
    context = packaged_authority_context()
    kernel, ldb = context.mutable_pair()
    admission = context.admission
    return {
        "kernel": kernel,
        "language_bundle": ldb,
        "admission": {
            "admitted": admission.admitted,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }
