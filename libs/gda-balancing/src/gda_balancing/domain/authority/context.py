"""Domain lifecycle for the permanent, packaged Kernel/LDB authority artifacts.

The JSON resources are the language authority.  This host module only reads,
independently admits, and defensively copies them; changing Python dispatch
cannot silently add a law, rule, diagnostic, or package to the language.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Never, cast

from gda_balancing.infrastructure.package_resources import read_package_resource
from gda_balancing.domain.authority.graph import (
    LanguageBundleGraph,
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.domain.authority.admission import (
    BootstrapAdmission,
    admit_authorities,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes

_AUTHORITY_PACKAGE = "gda_balancing.schema2.authorities"
_BOOTSTRAP_MAX_AUTHORITY_BYTES = 262144
_BOOTSTRAP_MAX_NESTING_DEPTH = 32
_BOOTSTRAP_MAX_PACKAGE_MEMBERS = 256


class _FrozenDict(Mapping[str, Any]):
    """A dict-compatible view that does not inherit a mutable builtin.

    ``__class__`` preserves the existing structural ``isinstance(value, dict)``
    consumer contract. Unlike a ``dict`` subclass, unbound builtin mutators
    cannot bypass this boundary because the object has no mutable dict storage.
    """

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    @property
    def __class__(self) -> type[dict[str, Any]]:
        return dict

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    @staticmethod
    def _reject(*_args: Any, **_kwargs: Any) -> Never:
        raise TypeError("admitted authority data is immutable")

    def __setattr__(self, _name: str, _value: Any) -> None:
        self._reject()

    __setitem__ = _reject
    __delitem__ = _reject
    clear = _reject
    pop = _reject
    popitem = _reject
    setdefault = _reject
    update = _reject
    __ior__ = _reject

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return False

    def __ne__(self, other: object) -> bool:
        return not self == other

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        duplicate = deepcopy(dict(self), memo)
        memo[id(self)] = duplicate
        return duplicate


class _FrozenList(tuple[Any, ...]):
    """A list-compatible immutable sequence backed by a tuple."""

    @property
    def __class__(self) -> type[list[Any]]:
        return list

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return False

    def __ne__(self, other: object) -> bool:
        return not self == other

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


class _FrozenLanguageBundleIndex(_FrozenDict):
    """Immutable lookup view carrying its exact admitted graph source."""

    __slots__ = (
        "_package_byte_sizes",
        "_package_conformance_vector_sets",
        "_package_releases",
        "_root",
        "_root_byte_size",
        "_vector_set_byte_sizes",
    )

    def __init__(self, source: LanguageBundleIndex) -> None:
        super().__init__({key: _deep_freeze(child) for key, child in source.items()})
        object.__setattr__(self, "_root", _deep_freeze(source.root))
        object.__setattr__(
            self, "_package_releases", _deep_freeze(source.package_releases)
        )
        object.__setattr__(
            self,
            "_package_conformance_vector_sets",
            _deep_freeze(source.package_conformance_vector_sets),
        )
        object.__setattr__(self, "_root_byte_size", source.root_byte_size)
        object.__setattr__(
            self, "_package_byte_sizes", tuple(source.package_byte_sizes)
        )
        object.__setattr__(
            self, "_vector_set_byte_sizes", tuple(source.vector_set_byte_sizes)
        )

    @property
    def __class__(self) -> type[LanguageBundleIndex]:
        return LanguageBundleIndex

    @property
    def root(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._root)

    @property
    def package_releases(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._package_releases)

    @property
    def package_conformance_vector_sets(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._package_conformance_vector_sets)

    @property
    def root_byte_size(self) -> int:
        return self._root_byte_size

    @property
    def package_byte_sizes(self) -> tuple[int, ...]:
        return self._package_byte_sizes

    @property
    def vector_set_byte_sizes(self) -> tuple[int, ...]:
        return self._vector_set_byte_sizes

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


def _replay_comparison_policy_index(
    language_bundle: dict[str, Any],
) -> Mapping[str, Mapping[str, Any]]:
    language = cast(dict[str, Any], language_bundle["language"])
    index: dict[str, dict[str, Any]] = {}
    for policy in cast(
        list[dict[str, Any]], language.get("replay_comparison_policies", [])
    ):
        policy_id = cast(str, policy["id"])
        owners = [
            release
            for release in cast(list[dict[str, Any]], language["packages"])
            if policy_id
            in cast(
                list[str],
                release.get("exports", {}).get("replay_comparison_policies", []),
            )
        ]
        if policy_id in index or len(owners) != 1:
            raise ValueError("admitted Replay comparison policy ownership is invalid")
        owner = owners[0]
        index[policy_id] = {
            "owner": {
                "package": owner["id"],
                "package_version": owner["version"],
            },
            "policy": policy,
        }
    return cast(Mapping[str, Mapping[str, Any]], _deep_freeze(index))


@dataclass(frozen=True)
class AdmittedAuthorityContext:
    """One exact, deeply immutable admitted Kernel/LDB lifecycle."""

    kernel: dict[str, Any]
    language_bundle: dict[str, Any]
    replay_comparison_policy_index: Mapping[str, Mapping[str, Any]] = field(init=False)
    admission: BootstrapAdmission
    canonical_kernel_bytes: bytes = field(init=False)
    canonical_language_bundle_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kernel, _FrozenDict) or not isinstance(
            self.language_bundle, _FrozenLanguageBundleIndex
        ):
            raise ValueError("an admitted context requires a sealed Kernel and LDB")
        if (
            not self.admission.admitted
            or self.admission.kernel_identity != self.kernel.get("content_identity")
            or self.admission.language_bundle_identity
            != self.language_bundle.get("content_identity")
        ):
            raise ValueError("authority admission does not match the sealed context")
        object.__setattr__(
            self,
            "canonical_kernel_bytes",
            canonical_bytes(cast(JsonValue, self.kernel)),
        )
        object.__setattr__(
            self,
            "canonical_language_bundle_bytes",
            _language_bundle_canonical_bytes(self.language_bundle),
        )
        object.__setattr__(
            self,
            "replay_comparison_policy_index",
            _replay_comparison_policy_index(self.language_bundle),
        )

    def __deepcopy__(self, memo: dict[int, Any]) -> "AdmittedAuthorityContext":
        """Preserve the sealed context; ``mutable_pair`` is the mutable escape hatch."""
        memo[id(self)] = self
        return self

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
_PACKAGED_CONTEXT_ERROR: _AuthorityFailureSnapshot | None = None
_PACKAGED_CONTEXT_ADMISSION_ATTEMPTS = 0


class AuthorityLoadError(Exception):
    """A candidate authority failed the non-self-hosted ingress preflight."""

    stage = "ingress"

    def __init__(self, *, code: str, subject: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.subject = subject
        self.message = message


@dataclass(frozen=True)
class _AuthorityFailureSnapshot:
    """Immutable cached refusal data; callers receive fresh exceptions."""

    code: str
    subject: str
    message: str

    def exception(self) -> AuthorityLoadError:
        return AuthorityLoadError(
            code=self.code,
            subject=self.subject,
            message=self.message,
        )


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
    try:
        data = read_package_resource(_AUTHORITY_PACKAGE, name)
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
            raise _PACKAGED_CONTEXT_ERROR.exception()
        try:
            _PACKAGED_CONTEXT_ADMISSION_ATTEMPTS += 1
            context = _load_packaged_authority_context_uncached()
        except AuthorityLoadError as err:
            failure = _AuthorityFailureSnapshot(
                code=err.code,
                subject=err.subject,
                message=err.message,
            )
            _PACKAGED_CONTEXT_ERROR = failure
            raise failure.exception() from err
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
    """Return a serializer-compatible snapshot for descriptor assembly."""
    context = packaged_authority_context()
    return context.mutable_pair()


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
