"""Authenticated artifact publication, recovery, and retrieval."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from gda_balancing.domain.artifact_errors import (
    PublishedArtifactIntegrityError,
    PublishedArtifactUnavailable,
)
from gda_balancing.domain.artifacts import _identified_artifact, _verify_artifact
from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    parse_canonical_object,
)
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.domain.publication_types import (
    PublicationAdmissionError,
    PublicationError,
    PublicationMember,
    RecoveredArtifactSet,
)
from gda_balancing.infrastructure.atomic_files import (
    NonDirectoryPathError,
    NonRegularPathError,
    PathKind,
    SymlinkPathError,
    assert_no_symlink_ancestors,
    commit_directory,
    ensure_directory_chain,
    environment_value,
    exclusive_file_lock as _invocation_lock,
    fsync_directory as _fsync_directory,
    inspect_path,
    make_stage_directory,
    materialize_bytes,
    normalized_absolute_path as _normalized_absolute_path,
    read_regular_bytes,
    read_regular_bytes_following_symlink,
    regular_files,
    remove_empty_directory,
    remove_tree,
    write_immutable_link,
    write_exclusive_bytes,
)

_STORE_DIRECTORY_ENV = "GDA_BALANCING_STORE_DIR"
_ANCHOR_KEY_ENV = "GDA_BALANCING_ANCHOR_KEY"


type ArtifactSetProvider = Callable[[], dict[str, dict[str, JsonValue]]]
type ModelArtifactValidator = Callable[
    [dict[str, dict[str, JsonValue]], str, AdmittedAuthorityContext], None
]


@dataclass(frozen=True)
class AuthenticatedArtifactSet:
    """One locally authenticated publication ready for Domain admission."""

    authority_context: AdmittedAuthorityContext
    receipt: dict[str, Any]
    artifacts: dict[str, dict[str, Any]]


def find_published_artifacts(
    requested: tuple[tuple[str, str, str], ...],
    language_bundle: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Resolve one exact named subset through one authenticated store traversal."""
    names = [logical_name for logical_name, _kind, _identity in requested]
    if not requested or len(names) != len(set(names)):
        raise ValueError("published artifact requests require unique logical names")
    matches = _resolve_published_artifacts(requested, language_bundle)
    return {name: artifact for name, artifact in zip(names, matches, strict=True)}


def _resolve_published_artifacts(
    requested: tuple[tuple[str, str, str], ...],
    language_bundle: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    anchors = _store_root() / "anchors"
    authentication_key = publication_authentication_key()
    matches: list[list[dict[str, Any]]] = [[] for _request in requested]
    integrity_errors: list[PublishedArtifactIntegrityError | None] = [
        None for _request in requested
    ]
    for anchor_path in regular_files(anchors, "*/*.json"):
        try:
            index = _verified_anchor(anchor_path, authentication_key)
            if (
                not _verify_artifact(index, language_bundle)
                or not isinstance(index.get("descriptor_identity"), str)
                or not isinstance(index.get("invocation_key"), str)
            ):
                continue
            invocation_path = _store_invocation_path(
                cast(str, index["descriptor_identity"]),
                cast(str, index["invocation_key"]),
            )
            committed_index = _read_canonical_artifact(
                invocation_path / "publication-index.json"
            )
            if committed_index != index:
                continue
            manifest = _read_canonical_artifact(
                invocation_path / "artifact-set-manifest.json"
            )
            receipt = _read_canonical_artifact(
                invocation_path / "artifact-set-receipt.json"
            )
            if (
                not _verify_artifact(receipt, language_bundle)
                or receipt.get("content_identity") != index.get("receipt_identity")
                or receipt.get("descriptor_identity")
                != index.get("descriptor_identity")
                or receipt.get("invocation_key") != index.get("invocation_key")
                or receipt.get("manifest_locator")
                != str((invocation_path / "artifact-set-manifest.json").absolute())
                or not _verify_artifact(manifest, language_bundle)
                or manifest.get("content_identity") != receipt.get("manifest_identity")
            ):
                continue
            members = manifest.get("members")
            member_locators = receipt.get("member_locators")
            if (
                not isinstance(members, list)
                or not isinstance(member_locators, list)
                or member_locators
                != [
                    {
                        "logical_name": member.get("logical_name"),
                        "locator": str(
                            (
                                invocation_path / f"{member.get('logical_name')}.json"
                            ).absolute()
                        ),
                    }
                    for member in members
                    if isinstance(member, dict)
                    and isinstance(member.get("logical_name"), str)
                ]
                or len(member_locators) != len(members)
            ):
                continue
            requested_members: list[tuple[int, dict[str, Any]]] = []
            ambiguous = False
            for request_index, request in enumerate(requested):
                logical_name, artifact_kind, content_identity_value = request
                candidates = [
                    member
                    for member in members
                    if isinstance(member, dict)
                    and member.get("artifact_kind") == artifact_kind
                    and member.get("content_identity") == content_identity_value
                    and isinstance(member.get("logical_name"), str)
                    and member.get("logical_name") == logical_name
                ]
                if len(candidates) > 1:
                    if integrity_errors[request_index] is None:
                        integrity_errors[request_index] = (
                            PublishedArtifactIntegrityError(
                                "authenticated publication contains ambiguous exact "
                                "member descriptors",
                                logical_name=logical_name,
                            )
                        )
                    ambiguous = True
                elif len(candidates) == 1:
                    requested_members.append((request_index, candidates[0]))
            if ambiguous:
                continue
            if not requested_members:
                continue
            try:
                artifacts = _read_complete_publication_members(
                    invocation_path,
                    members,
                    language_bundle,
                )
            except (OSError, RuntimeError, PublicationError, ValueError):
                for request_index, _member in requested_members:
                    if integrity_errors[request_index] is None:
                        logical_name = requested[request_index][0]
                        integrity_errors[request_index] = (
                            PublishedArtifactIntegrityError(
                                "authenticated publication contains a missing, damaged, "
                                "or identity-inconsistent member",
                                logical_name=logical_name,
                            )
                        )
                continue
            for request_index, member in requested_members:
                member_name = cast(str, member["logical_name"])
                artifact = artifacts[member_name]
                matches[request_index].append(artifact)
        except (OSError, RuntimeError, PublicationError, ValueError):
            continue
    resolved: list[dict[str, Any]] = []
    for request, candidates, integrity_error in zip(
        requested, matches, integrity_errors, strict=True
    ):
        logical_name, artifact_kind, _content_identity_value = request
        if integrity_error is not None:
            raise integrity_error
        if not candidates:
            raise PublishedArtifactUnavailable(
                logical_name,
                artifact_kind,
            )
        canonical = canonical_bytes(cast(JsonValue, candidates[0]))
        if any(
            canonical_bytes(cast(JsonValue, candidate)) != canonical
            for candidate in candidates[1:]
        ):
            raise PublishedArtifactIntegrityError(
                "one exact artifact request resolved to different authenticated "
                "artifacts",
                logical_name=logical_name,
            )
        resolved.append(candidates[0])
    return tuple(resolved)


def _read_complete_publication_members(
    invocation_path: Path,
    members: list[Any],
    language_bundle: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Re-admit every member declared by one selected publication manifest."""
    artifacts: dict[str, dict[str, Any]] = {}
    for member in members:
        if not isinstance(member, dict):
            raise RuntimeError(
                "authenticated publication member descriptor is malformed"
            )
        logical_name = member.get("logical_name")
        artifact_kind = member.get("artifact_kind")
        wire_schema_identity = member.get("wire_schema_identity")
        content_identity_value = member.get("content_identity")
        if (
            not isinstance(logical_name, str)
            or not isinstance(artifact_kind, str)
            or not isinstance(wire_schema_identity, str)
            or not isinstance(content_identity_value, str)
            or logical_name in artifacts
        ):
            raise RuntimeError(
                "authenticated publication member descriptor is not unique and closed"
            )
        artifact = _read_canonical_artifact(invocation_path / f"{logical_name}.json")
        if (
            not _verify_artifact(artifact, language_bundle)
            or artifact.get("artifact_kind") != artifact_kind
            or artifact.get("wire_schema_identity") != wire_schema_identity
            or artifact.get("content_identity") != content_identity_value
        ):
            raise RuntimeError(
                "authenticated publication member failed schema or identity verification"
            )
        artifacts[logical_name] = artifact
    return artifacts


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    data = canonical_bytes(cast(JsonValue, value))
    write_exclusive_bytes(path, data)


def _read_canonical_artifact(path: Path) -> dict[str, Any]:
    try:
        data = read_regular_bytes(path)
        value = parse_canonical_object(
            data,
            artifact_name="committed publication member",
        )
    except SymlinkPathError as err:
        raise PublicationError(
            "unsafe_path",
            f"publication members must not be symlinks: {path.name}",
        ) from err
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as err:
        raise RuntimeError(
            f"committed publication member is unreadable: {path.name}"
        ) from err
    if data != canonical_bytes(cast(JsonValue, value)):
        raise RuntimeError(
            f"committed publication member is not canonical: {path.name}"
        )
    return value


def _read_receipt_input(path: Path) -> dict[str, Any]:
    """Decode a public CLI JSON presentation before artifact admission."""
    try:
        return parse_canonical_object(
            read_regular_bytes_following_symlink(path),
            artifact_name="Artifact-set receipt",
        )
    except NonRegularPathError as err:
        raise UnreadableInputError(
            f"input document is not a regular file: {path}"
        ) from err
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as err:
        raise PublicationAdmissionError(
            "kernel.identity_mismatch",
            "receipt",
            "Artifact-set receipt is not an admissible JSON artifact",
        ) from err


def _inspect_committed_artifact(
    path: Path,
    *,
    code: str,
    subject: str,
) -> dict[str, Any]:
    try:
        return _read_canonical_artifact(path)
    except (RuntimeError, PublicationError) as err:
        raise PublicationAdmissionError(
            code,
            subject,
            f"committed artifact-set member failed admission: {path.name}",
        ) from err


def read_authenticated_artifact_set(
    receipt_path: str,
    expected_descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> AuthenticatedArtifactSet:
    """Authenticate and load all members of one committed artifact set."""
    path = _normalized_absolute_path(receipt_path)
    receipt = _read_receipt_input(path)
    context = packaged_authority_context()
    language_bundle = context.language_bundle
    if (
        not _verify_artifact(receipt, language_bundle)
        or receipt.get("artifact_kind") != "artifact-set-receipt"
    ):
        raise PublicationAdmissionError(
            "kernel.identity_mismatch",
            "receipt",
            "Artifact-set receipt failed exact-authority admission",
        )
    descriptor_identity_value = receipt.get("descriptor_identity")
    invocation_key = receipt.get("invocation_key")
    if descriptor_identity_value != expected_descriptor_identity or not isinstance(
        invocation_key, str
    ):
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "receipt.descriptor_identity",
            "Artifact-set receipt belongs to another command or invocation",
        )
    invocation_path = _store_invocation_path(
        expected_descriptor_identity, invocation_key
    )
    manifest_locator = receipt.get("manifest_locator")
    if not isinstance(manifest_locator, str):
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "receipt.manifest_locator",
            "Artifact-set receipt has no manifest locator",
        )
    manifest_path = _normalized_absolute_path(manifest_locator)
    publication_dir = manifest_path.parent
    try:
        _assert_directory_without_symlink(publication_dir)
    except (RuntimeError, PublicationError) as err:
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "receipt.manifest_locator",
            "Artifact-set manifest locator failed admission",
        ) from err
    expected_manifest_path = invocation_path / "artifact-set-manifest.json"
    if manifest_path != expected_manifest_path:
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "receipt.manifest_locator",
            "Artifact-set receipt does not locate its committed publication",
        )
    anchor_path = _store_anchor_path(expected_descriptor_identity, invocation_key)
    authentication_key = publication_authentication_key()
    try:
        _assert_ancestor_chain_without_symlink(invocation_path)
        _assert_ancestor_chain_without_symlink(anchor_path)
        _require_immutable_anchor(anchor_path)
        index = _verified_anchor(anchor_path, authentication_key)
        committed_index = _read_canonical_artifact(
            invocation_path / "publication-index.json"
        )
        committed_receipt = _read_canonical_artifact(
            invocation_path / "artifact-set-receipt.json"
        )
    except (OSError, RuntimeError, PublicationError, ValueError) as err:
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "publication-index",
            "Artifact-set publication anchor failed authentication",
        ) from err
    if (
        not _verify_artifact(index, language_bundle)
        or committed_index != index
        or index.get("descriptor_identity") != expected_descriptor_identity
        or index.get("invocation_key") != invocation_key
        or index.get("receipt_identity") != receipt.get("content_identity")
        or committed_receipt != receipt
    ):
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "publication-index",
            "Artifact-set publication index does not authenticate the receipt",
        )
    manifest = _inspect_committed_artifact(
        expected_manifest_path,
        code="kernel.binding_mismatch",
        subject="manifest",
    )
    if not _verify_artifact(manifest, language_bundle) or manifest.get(
        "content_identity"
    ) != receipt.get("manifest_identity"):
        raise PublicationAdmissionError(
            "kernel.binding_mismatch",
            "manifest",
            "Artifact-set manifest failed exact-authority admission",
        )
    members = manifest.get("members")
    locators = receipt.get("member_locators")
    if not isinstance(members, list) or not isinstance(locators, list):
        raise PublicationAdmissionError(
            "kernel.member_set_mismatch",
            "manifest.members",
            "Artifact-set publication has no closed member map",
        )
    expected_names = [member.logical_name for member in artifact_set]
    expected_kinds = {
        member.logical_name: member.artifact_kind for member in artifact_set
    }
    expected_locators = [
        {
            "logical_name": name,
            "locator": str((invocation_path / f"{name}.json").absolute()),
        }
        for name in expected_names
    ]
    if (
        [row.get("logical_name") for row in members if isinstance(row, dict)]
        != expected_names
        or len(members) != len(expected_names)
        or locators != expected_locators
    ):
        raise PublicationAdmissionError(
            "kernel.member_set_mismatch",
            "manifest.members",
            "Publication does not match the command artifact set",
        )
    artifacts: dict[str, dict[str, Any]] = {}
    for row in members:
        if not isinstance(row, dict):
            raise PublicationAdmissionError(
                "kernel.member_set_mismatch",
                "manifest.members",
                "Artifact-set publication contains a malformed member",
            )
        name = row.get("logical_name")
        if not isinstance(name, str) or row.get("artifact_kind") != expected_kinds.get(
            name
        ):
            raise PublicationAdmissionError(
                "kernel.member_set_mismatch",
                "manifest.members",
                "Artifact-set publication contains an undeclared member",
            )
        artifact = _inspect_committed_artifact(
            invocation_path / f"{name}.json",
            code="kernel.binding_mismatch",
            subject=name,
        )
        if (
            not _verify_artifact(artifact, language_bundle)
            or artifact.get("artifact_kind") != row.get("artifact_kind")
            or artifact.get("content_identity") != row.get("content_identity")
            or artifact.get("wire_schema_identity") != row.get("wire_schema_identity")
        ):
            raise PublicationAdmissionError(
                "kernel.binding_mismatch",
                name,
                "Committed artifact-set member failed exact-authority admission",
            )
        artifacts[name] = artifact

    return AuthenticatedArtifactSet(
        authority_context=context,
        receipt=receipt,
        artifacts=artifacts,
    )


def _assert_directory_without_symlink(path: Path) -> None:
    try:
        inspection = inspect_path(path)
    except OSError as err:
        raise RuntimeError(f"publication directory is unavailable: {path}") from err
    if inspection.kind is PathKind.SYMLINK:
        raise PublicationError(
            "unsafe_path", f"publication directory must not be a symlink: {path}"
        )
    if inspection.kind is not PathKind.DIRECTORY:
        raise RuntimeError(f"publication path is not a directory: {path}")


def _store_root() -> Path:
    configured = environment_value(_STORE_DIRECTORY_ENV)
    if configured:
        return _normalized_absolute_path(configured)
    state_home = environment_value("XDG_STATE_HOME")
    base = (
        _normalized_absolute_path(state_home)
        if state_home
        else Path.home() / ".local" / "state"
    )
    return base / "gda-balancing" / "store-v2"


def _store_invocation_path(descriptor_identity: str, invocation_key: str) -> Path:
    if not descriptor_identity.startswith("sha256:"):
        raise ValueError("descriptor identity is not content addressed")
    descriptor_key = descriptor_identity.removeprefix("sha256:")
    return _store_root() / "invocations" / descriptor_key / invocation_key


def _store_anchor_path(descriptor_identity: str, invocation_key: str) -> Path:
    if not descriptor_identity.startswith("sha256:"):
        raise ValueError("descriptor identity is not content addressed")
    descriptor_key = descriptor_identity.removeprefix("sha256:")
    return _store_root() / "anchors" / descriptor_key / f"{invocation_key}.json"


def _store_lock_path(descriptor_identity: str, invocation_key: str) -> Path:
    if not descriptor_identity.startswith("sha256:"):
        raise ValueError("descriptor identity is not content addressed")
    descriptor_key = descriptor_identity.removeprefix("sha256:")
    return _store_root() / "locks" / descriptor_key / f"{invocation_key}.lock"


def publication_authentication_key() -> bytes:
    encoded = environment_value(_ANCHOR_KEY_ENV)
    if (
        encoded is None
        or len(encoded) != 64
        or encoded.lower() != encoded
        or any(character not in "0123456789abcdef" for character in encoded)
    ):
        raise PublicationError(
            "invalid_configuration",
            f"{_ANCHOR_KEY_ENV} must contain exactly 64 lowercase hexadecimal digits",
        )
    return bytes.fromhex(encoded)


def _authenticated_anchor(
    index: dict[str, JsonValue],
    authentication_key: bytes,
) -> dict[str, JsonValue]:
    authentication = hmac.new(
        authentication_key,
        canonical_bytes(cast(JsonValue, index)),
        hashlib.sha256,
    ).hexdigest()
    return {
        "anchor_kind": "authenticated-publication-index-v1",
        "algorithm": "hmac-sha256",
        "publication_index": cast(JsonValue, index),
        "authentication": authentication,
    }


def _verified_anchor(path: Path, authentication_key: bytes) -> dict[str, Any]:
    envelope = _read_canonical_artifact(path)
    if set(envelope) != {
        "anchor_kind",
        "algorithm",
        "publication_index",
        "authentication",
    }:
        raise RuntimeError("committed publication anchor envelope is malformed")
    index = envelope.get("publication_index")
    authentication = envelope.get("authentication")
    if (
        envelope.get("anchor_kind") != "authenticated-publication-index-v1"
        or envelope.get("algorithm") != "hmac-sha256"
        or not isinstance(index, dict)
        or not isinstance(authentication, str)
    ):
        raise RuntimeError("committed publication anchor envelope is malformed")
    expected = hmac.new(
        authentication_key,
        canonical_bytes(cast(JsonValue, index)),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(authentication, expected):
        raise RuntimeError("committed publication anchor authentication is invalid")
    return index


def _require_immutable_anchor(path: Path) -> None:
    try:
        inspection = inspect_path(path)
    except OSError as err:
        raise RuntimeError("committed publication anchor is unavailable") from err
    if inspection.kind is not PathKind.REGULAR or inspection.writable:
        raise RuntimeError("committed publication anchor trust boundary is invalid")


def _write_anchor_exclusive(
    path: Path,
    artifact: dict[str, JsonValue],
    authentication_key: bytes,
    *,
    before_commit: bool = False,
) -> None:
    data = canonical_bytes(
        cast(JsonValue, _authenticated_anchor(artifact, authentication_key))
    )
    try:
        write_immutable_link(path, data, before_commit=before_commit)
    except FileExistsError as err:
        raise RuntimeError(
            "publication anchor already exists or is unwritable"
        ) from err


def _primary_artifact_name(
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> str:
    primary = [
        member.logical_name for member in artifact_set if member.role == "primary"
    ]
    if len(primary) != 1:
        raise ValueError("artifact set must declare exactly one primary member")
    return primary[0]


def _assert_ancestor_chain_without_symlink(path: Path) -> None:
    try:
        assert_no_symlink_ancestors(path)
    except SymlinkPathError as err:
        raise PublicationError(
            "unsafe_path",
            f"publication path ancestors must not be symlinks: {err}",
        ) from err
    except OSError as err:
        raise RuntimeError(f"cannot inspect publication path ancestor: {path}") from err


def _ensure_directory_chain(path: Path) -> None:
    try:
        ensure_directory_chain(path)
    except SymlinkPathError as err:
        raise PublicationError(
            "unsafe_path",
            f"publication path ancestors must not be symlinks: {err}",
        ) from err
    except NonDirectoryPathError as err:
        raise RuntimeError(f"publication path is not a directory: {path}") from err


def _validate_presentation_path(out_path: Path, invocation_path: Path) -> None:
    """Keep every presentation outside the immutable store and symlink aliases."""
    store_root = _store_root()
    if (
        out_path == store_root
        or store_root in out_path.parents
        or out_path in store_root.parents
        or out_path == invocation_path
        or invocation_path in out_path.parents
        or out_path in invocation_path.parents
    ):
        raise PublicationError(
            "unsafe_path",
            "presentation path must not overlap the immutable publication store",
        )
    parent = out_path.parent
    _assert_ancestor_chain_without_symlink(parent)
    if inspect_path(parent).kind is not PathKind.DIRECTORY:
        raise PublicationError(
            "output_unavailable", f"cannot write output directory: {out_path}"
        )
    if inspect_path(out_path).kind is PathKind.SYMLINK:
        raise PublicationError("unsafe_path", "presentation path must not be a symlink")


def _materialize_primary(out_path: Path, resolved: dict[str, Any]) -> None:
    data = canonical_bytes(cast(JsonValue, resolved))
    try:
        materialize_bytes(out_path, data)
    except SymlinkPathError as err:
        raise PublicationError(
            "unsafe_path", "presentation path must not be a symlink"
        ) from err
    except NonRegularPathError as err:
        raise PublicationError(
            "output_unavailable", f"output is not a regular file: {out_path}"
        ) from err
    except FileExistsError as err:
        raise PublicationError(
            "output_unavailable", f"output already contains different bytes: {out_path}"
        ) from err
    except OSError as err:
        raise PublicationError(
            "output_unavailable", f"cannot inspect output: {out_path}"
        ) from err


def _recover_publication(
    invocation_path: Path,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    source_identity: str,
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    authentication_key: bytes,
    validator: ModelArtifactValidator,
) -> dict[str, JsonValue]:
    authority_context = admit_authority_context(kernel, language_bundle)
    if isinstance(authority_context, BootstrapAdmission):
        raise RuntimeError("committed publication authorities failed admission")
    member_files = {
        member.logical_name: f"{member.logical_name}.json" for member in artifact_set
    }
    expected_names = [member.logical_name for member in artifact_set]
    member_kinds = {
        member.logical_name: member.artifact_kind for member in artifact_set
    }
    _assert_directory_without_symlink(invocation_path)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    _assert_ancestor_chain_without_symlink(anchor_path)
    _require_immutable_anchor(anchor_path)
    anchor = _verified_anchor(anchor_path, authentication_key)
    index = _read_canonical_artifact(invocation_path / "publication-index.json")
    if not _verify_artifact(index, language_bundle) or index != anchor:
        raise RuntimeError("committed publication index identity is invalid")
    if index.get("descriptor_identity") != descriptor_identity:
        raise RuntimeError("publication index belongs to another command")
    if index.get("invocation_key") != invocation_key:
        raise RuntimeError("publication index belongs to another invocation")
    if index.get("command_input_identity") != command_input_identity:
        raise PublicationError(
            "invocation_key_conflict",
            "Invocation key is already bound to a different canonical input",
        )

    receipt = _read_canonical_artifact(invocation_path / "artifact-set-receipt.json")
    if not _verify_artifact(receipt, language_bundle) or receipt.get(
        "content_identity"
    ) != index.get("receipt_identity"):
        raise RuntimeError(
            "committed artifact-set receipt does not match its index anchor"
        )
    if (
        receipt.get("descriptor_identity") != descriptor_identity
        or receipt.get("invocation_key") != invocation_key
        or receipt.get("manifest_locator")
        != str((invocation_path / "artifact-set-manifest.json").absolute())
        or receipt.get("member_locators")
        != [
            {
                "logical_name": logical_name,
                "locator": str(
                    (invocation_path / member_files[logical_name]).absolute()
                ),
            }
            for logical_name in expected_names
        ]
    ):
        raise RuntimeError("committed artifact-set receipt has invalid bindings")
    manifest = _read_canonical_artifact(invocation_path / "artifact-set-manifest.json")
    if not _verify_artifact(manifest, language_bundle) or manifest.get(
        "content_identity"
    ) != receipt.get("manifest_identity"):
        raise RuntimeError("committed artifact-set manifest does not match its receipt")
    members = manifest.get("members")
    if (
        not isinstance(members, list)
        or [item.get("logical_name") for item in members if isinstance(item, dict)]
        != expected_names
    ):
        raise RuntimeError("committed artifact-set manifest is incomplete")
    artifacts: dict[str, dict[str, Any]] = {}
    for member in members:
        if not isinstance(member, dict):
            raise RuntimeError("committed artifact-set manifest member is malformed")
        logical_name = member.get("logical_name")
        if not isinstance(logical_name, str) or logical_name not in member_files:
            raise RuntimeError("committed artifact-set manifest member is unknown")
        expected_path = invocation_path / member_files[logical_name]
        artifact = _read_canonical_artifact(expected_path)
        if (
            not _verify_artifact(artifact, language_bundle)
            or artifact.get("content_identity") != member.get("content_identity")
            or artifact.get("artifact_kind") != member.get("artifact_kind")
            or artifact.get("artifact_kind") != member_kinds[logical_name]
            or artifact.get("wire_schema_identity")
            != member.get("wire_schema_identity")
        ):
            raise RuntimeError("committed artifact-set member failed revalidation")
        artifacts[logical_name] = artifact
    validator(artifacts, source_identity, authority_context)
    _materialize_primary(out_path, artifacts[_primary_artifact_name(artifact_set)])
    return cast(dict[str, JsonValue], receipt)


def publish_artifact_set(
    artifacts: dict[str, PublicationMember],
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    member_validator: Callable[[str, dict[str, Any]], bool],
    publication_fault: str | None = None,
    *,
    artifact_set_validator: Callable[[dict[str, dict[str, Any]]], bool] | None = None,
    authentication_key: bytes | None = None,
) -> dict[str, JsonValue]:
    """Atomically publish a pre-admitted heterogeneous Schema 2.x artifact set.

    Model build owns its semantic recovery audit separately.  This entry point
    serves descriptor-owned sets whose primary value is not itself a runtime
    artifact, while retaining the same invocation lock, authenticated anchor,
    immutable manifest, retry, and all-or-nothing publication protocol.
    """
    if publication_fault not in {
        None,
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    }:
        raise ValueError("unknown publication fault")
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    declared = {member.logical_name: member.artifact_kind for member in artifact_set}
    if set(artifacts) != set(declared) or any(
        artifacts[name].artifact_kind != kind for name, kind in declared.items()
    ):
        raise RuntimeError("prepared output does not match the descriptor artifact set")
    if not all(member_validator(name, artifacts[name].value) for name in artifacts):
        raise RuntimeError("prepared output failed artifact-schema admission")
    artifact_values = {name: member.value for name, member in artifacts.items()}
    if artifact_set_validator is not None and not artifact_set_validator(
        artifact_values
    ):
        raise RuntimeError("prepared output failed artifact-set semantic admission")

    out_path = _normalized_absolute_path(out)
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    _validate_presentation_path(out_path, invocation_path)
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    if inspect_path(lock_path).kind is PathKind.SYMLINK:
        raise PublicationError(
            "unsafe_path", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
        anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
        _assert_ancestor_chain_without_symlink(invocation_path)
        invocation_kind = inspect_path(invocation_path).kind
        anchor_kind = inspect_path(anchor_path).kind
        if invocation_kind is PathKind.SYMLINK:
            raise PublicationError(
                "unsafe_path",
                "Invocation-key publication must not be a symlink",
            )
        if invocation_kind is not PathKind.MISSING and anchor_kind is PathKind.MISSING:
            _assert_directory_without_symlink(invocation_path)
            remove_tree(invocation_path)
            _fsync_directory(invocation_path.parent)
        if inspect_path(invocation_path).kind is not PathKind.MISSING:
            return _recover_generic_publication(
                invocation_path,
                out_path,
                invocation_key,
                descriptor_identity,
                command_input_identity,
                language_bundle,
                artifact_set,
                artifacts,
                member_validator,
                authentication_key,
            )
        if inspect_path(out_path).kind is not PathKind.MISSING:
            raise PublicationError(
                "output_unavailable", f"output already exists: {out_path}"
            )
        return _commit_generic_publication(
            invocation_path,
            anchor_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            language_bundle,
            artifact_set,
            artifacts,
            member_validator,
            authentication_key,
            publication_fault,
        )


def recover_committed_artifact_set(
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    candidate_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
    member_validator: Callable[[str, dict[str, Any]], bool],
    *,
    artifact_set_validator: Callable[[dict[str, dict[str, Any]]], bool] | None = None,
    authentication_key: bytes | None = None,
) -> RecoveredArtifactSet | None:
    """Recover one committed producing outcome before its producer reruns."""
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    out_path = _normalized_absolute_path(out)
    _validate_presentation_path(out_path, invocation_path)
    if (
        inspect_path(invocation_path).kind is PathKind.MISSING
        or inspect_path(anchor_path).kind is PathKind.MISSING
    ):
        return None
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    with _invocation_lock(lock_path):
        if (
            inspect_path(invocation_path).kind is PathKind.MISSING
            or inspect_path(anchor_path).kind is PathKind.MISSING
        ):
            return None
        manifest = _read_canonical_artifact(
            invocation_path / "artifact-set-manifest.json"
        )
        if not _verify_artifact(manifest, language_bundle):
            raise RuntimeError("committed artifact-set manifest failed revalidation")
        rows = manifest.get("members")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError("committed artifact-set manifest is malformed")
        signature = [
            (row.get("logical_name"), row.get("artifact_kind")) for row in rows
        ]
        matching_sets = [
            candidate
            for candidate in candidate_sets
            if signature
            == [(member.logical_name, member.artifact_kind) for member in candidate]
        ]
        if len(matching_sets) != 1:
            raise RuntimeError(
                "committed artifact set does not name one descriptor outcome"
            )
        artifact_set = matching_sets[0]
        artifacts: dict[str, dict[str, Any]] = {}
        expected: dict[str, PublicationMember] = {}
        for member, row in zip(artifact_set, rows, strict=True):
            artifact = _read_canonical_artifact(
                invocation_path / f"{member.logical_name}.json"
            )
            if (
                not _verify_artifact(artifact, language_bundle)
                or not member_validator(member.logical_name, artifact)
                or artifact.get("artifact_kind") != member.artifact_kind
                or artifact.get("content_identity") != row.get("content_identity")
                or artifact.get("wire_schema_identity")
                != row.get("wire_schema_identity")
            ):
                raise RuntimeError("committed artifact-set member failed revalidation")
            artifacts[member.logical_name] = artifact
            expected[member.logical_name] = PublicationMember(
                value=artifact,
                artifact_kind=member.artifact_kind,
                wire_schema_identity=cast(str, artifact["wire_schema_identity"]),
                content_identity=cast(str, artifact["content_identity"]),
            )
        if artifact_set_validator is not None and not artifact_set_validator(artifacts):
            raise RuntimeError(
                "committed artifact set failed semantic cross-revalidation"
            )
        receipt = _recover_generic_publication(
            invocation_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            language_bundle,
            artifact_set,
            expected,
            member_validator,
            authentication_key,
        )
        return RecoveredArtifactSet(
            receipt=receipt,
            artifact_set=artifact_set,
            artifacts=artifacts,
        )


def _recover_generic_publication(
    invocation_path: Path,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    expected_artifacts: dict[str, PublicationMember],
    member_validator: Callable[[str, dict[str, Any]], bool],
    authentication_key: bytes,
) -> dict[str, JsonValue]:
    """Authenticate and re-admit every member before replaying a committed set."""
    _assert_directory_without_symlink(invocation_path)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    _assert_ancestor_chain_without_symlink(anchor_path)
    _require_immutable_anchor(anchor_path)
    anchor = _verified_anchor(anchor_path, authentication_key)
    index = _read_canonical_artifact(invocation_path / "publication-index.json")
    if (
        not _verify_artifact(index, language_bundle)
        or index != anchor
        or index.get("descriptor_identity") != descriptor_identity
        or index.get("invocation_key") != invocation_key
    ):
        raise RuntimeError("committed publication index identity is invalid")
    if index.get("command_input_identity") != command_input_identity:
        raise PublicationError(
            "invocation_key_conflict",
            "Invocation key is already bound to a different canonical input",
        )

    receipt = _read_canonical_artifact(invocation_path / "artifact-set-receipt.json")
    manifest = _read_canonical_artifact(invocation_path / "artifact-set-manifest.json")
    if (
        not _verify_artifact(receipt, language_bundle)
        or receipt.get("content_identity") != index.get("receipt_identity")
        or not _verify_artifact(manifest, language_bundle)
        or manifest.get("content_identity") != receipt.get("manifest_identity")
    ):
        raise RuntimeError("committed artifact-set framing failed revalidation")
    expected_names = [member.logical_name for member in artifact_set]
    members = manifest.get("members")
    if (
        not isinstance(members, list)
        or [item.get("logical_name") for item in members if isinstance(item, dict)]
        != expected_names
    ):
        raise RuntimeError("committed artifact-set manifest is incomplete")
    for row in members:
        if not isinstance(row, dict):
            raise RuntimeError("committed artifact-set manifest member is malformed")
        name = row.get("logical_name")
        if not isinstance(name, str) or name not in expected_artifacts:
            raise RuntimeError("committed artifact-set manifest member is unknown")
        expected = expected_artifacts[name]
        artifact = _read_canonical_artifact(invocation_path / f"{name}.json")
        if (
            artifact != expected.value
            or not member_validator(name, artifact)
            or row.get("artifact_kind") != expected.artifact_kind
            or row.get("wire_schema_identity") != expected.wire_schema_identity
            or row.get("content_identity") != expected.content_identity
        ):
            raise RuntimeError("committed artifact-set member failed revalidation")
    expected_locators = [
        {
            "logical_name": name,
            "locator": str((invocation_path / f"{name}.json").absolute()),
        }
        for name in expected_names
    ]
    if (
        receipt.get("descriptor_identity") != descriptor_identity
        or receipt.get("invocation_key") != invocation_key
        or receipt.get("manifest_locator")
        != str((invocation_path / "artifact-set-manifest.json").absolute())
        or receipt.get("member_locators") != expected_locators
    ):
        raise RuntimeError("committed artifact-set receipt has invalid bindings")
    primary = _primary_artifact_name(artifact_set)
    _materialize_primary(out_path, expected_artifacts[primary].value)
    return cast(dict[str, JsonValue], receipt)


def _commit_generic_publication(
    invocation_path: Path,
    anchor_path: Path,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    artifacts: dict[str, PublicationMember],
    member_validator: Callable[[str, dict[str, Any]], bool],
    authentication_key: bytes,
    publication_fault: str | None,
) -> dict[str, JsonValue]:
    descriptor_parent = invocation_path.parent
    store_root = _store_root()
    created_directories: list[Path] = []
    for directory in (
        store_root,
        store_root / "invocations",
        descriptor_parent,
        store_root / "anchors",
        anchor_path.parent,
    ):
        existed = inspect_path(directory).kind is not PathKind.MISSING
        _ensure_directory_chain(directory)
        if not existed:
            created_directories.append(directory)
    members = [
        {
            "logical_name": member.logical_name,
            "artifact_kind": artifacts[member.logical_name].artifact_kind,
            "wire_schema_identity": artifacts[member.logical_name].wire_schema_identity,
            "content_identity": artifacts[member.logical_name].content_identity,
        }
        for member in artifact_set
    ]
    member_locators = [
        {
            "logical_name": member.logical_name,
            "locator": str(
                (invocation_path / f"{member.logical_name}.json").absolute()
            ),
        }
        for member in artifact_set
    ]
    manifest = _identified_artifact(
        language_bundle,
        "artifact-set-manifest",
        {
            "frame": "typed-logical-member-map-v1",
            "members": cast(JsonValue, members),
        },
    )
    receipt = _identified_artifact(
        language_bundle,
        "artifact-set-receipt",
        {
            "descriptor_identity": descriptor_identity,
            "invocation_key": invocation_key,
            "manifest_identity": manifest["content_identity"],
            "manifest_locator": str(
                (invocation_path / "artifact-set-manifest.json").absolute()
            ),
            "member_locators": cast(JsonValue, member_locators),
        },
    )
    index = _identified_artifact(
        language_bundle,
        "publication-index",
        {
            "adapter": "local-filesystem-directory-rename-v1",
            "descriptor_identity": descriptor_identity,
            "invocation_key": invocation_key,
            "command_input_identity": command_input_identity,
            "receipt_identity": receipt["content_identity"],
        },
    )
    stage = make_stage_directory(descriptor_parent, f".{invocation_key}.")
    anchored = False
    committed = False
    try:
        for index_value, member in enumerate(artifact_set):
            name = member.logical_name
            _write_json(stage / f"{name}.json", artifacts[name].value)
            if publication_fault == "after-member-write" and index_value == 0:
                raise RuntimeError("injected publication fault after member write")
        framing = {
            "artifact-set-manifest": manifest,
            "artifact-set-receipt": receipt,
            "publication-index": index,
        }
        for name, artifact in framing.items():
            _write_json(stage / f"{name}.json", artifact)
        for name, member in artifacts.items():
            staged = _read_canonical_artifact(stage / f"{name}.json")
            if staged != member.value or not member_validator(name, staged):
                raise RuntimeError("staged artifact verification failed")
        for name, artifact in framing.items():
            staged = _read_canonical_artifact(stage / f"{name}.json")
            if staged != artifact or not _verify_artifact(staged, language_bundle):
                raise RuntimeError("staged artifact verification failed")
        _fsync_directory(stage)
        if publication_fault == "before-commit":
            raise RuntimeError("injected publication fault before commit")
        if inspect_path(invocation_path).kind is not PathKind.MISSING:
            raise RuntimeError("Invocation-key publication appeared before commit")
        commit_directory(stage, invocation_path)
        committed = True
        _fsync_directory(descriptor_parent)
        _write_anchor_exclusive(
            anchor_path,
            index,
            authentication_key,
            before_commit=publication_fault == "before-anchor-commit",
        )
        anchored = True
        if publication_fault == "after-commit":
            raise RuntimeError("injected publication fault after commit")
        primary = _primary_artifact_name(artifact_set)
        _materialize_primary(out_path, artifacts[primary].value)
    except Exception:
        if inspect_path(stage).kind is not PathKind.MISSING:
            remove_tree(stage)
        if (
            committed
            and not anchored
            and inspect_path(invocation_path).kind is not PathKind.MISSING
            and inspect_path(anchor_path).kind is PathKind.MISSING
        ):
            remove_tree(invocation_path)
            _fsync_directory(invocation_path.parent)
        for directory in reversed(created_directories):
            try:
                remove_empty_directory(directory)
            except OSError:
                pass
        raise
    return receipt


def publish_lazy_artifact_set(
    authority_context: AdmittedAuthorityContext,
    semantic_input_identity: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    artifact_provider: ArtifactSetProvider,
    validator: ModelArtifactValidator,
    publication_fault: str | None = None,
    *,
    authentication_key: bytes | None = None,
) -> dict[str, JsonValue]:
    """Serialize one invocation key before inspecting or changing its publication."""
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    out_path = _normalized_absolute_path(out)
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    _validate_presentation_path(out_path, invocation_path)
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    if inspect_path(lock_path).kind is PathKind.SYMLINK:
        raise PublicationError(
            "unsafe_path", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
        return _publish_lazy_artifact_set_locked(
            authority_context,
            semantic_input_identity,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            artifact_set,
            authentication_key,
            artifact_provider,
            validator,
            publication_fault,
        )


def _publish_lazy_artifact_set_locked(
    authority_context: AdmittedAuthorityContext,
    semantic_input_identity: str,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    authentication_key: bytes,
    artifact_provider: ArtifactSetProvider,
    validator: ModelArtifactValidator,
    publication_fault: str | None = None,
) -> dict[str, JsonValue]:
    """Atomically publish one complete set while its invocation lock is held."""
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    kernel = authority_context.kernel
    language_bundle = authority_context.language_bundle
    _assert_ancestor_chain_without_symlink(invocation_path)
    invocation_kind = inspect_path(invocation_path).kind
    anchor_kind = inspect_path(anchor_path).kind
    if invocation_kind is PathKind.SYMLINK:
        raise PublicationError(
            "unsafe_path", "Invocation-key publication must not be a symlink"
        )
    if invocation_kind is not PathKind.MISSING and anchor_kind is PathKind.MISSING:
        _assert_directory_without_symlink(invocation_path)
        remove_tree(invocation_path)
        _fsync_directory(invocation_path.parent)
    if inspect_path(invocation_path).kind is not PathKind.MISSING:
        return _recover_publication(
            invocation_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            semantic_input_identity,
            kernel,
            language_bundle,
            artifact_set,
            authentication_key,
            validator,
        )
    if inspect_path(out_path).kind is not PathKind.MISSING:
        raise PublicationError(
            "output_unavailable", f"output already exists: {out_path}"
        )

    artifacts = artifact_provider()
    validator(artifacts, semantic_input_identity, authority_context)
    declared = {member.logical_name: member.artifact_kind for member in artifact_set}
    if set(artifacts) != set(declared) or any(
        artifacts[name]["artifact_kind"] != declared[name] for name in artifacts
    ):
        raise RuntimeError("prepared output does not match the descriptor artifact set")
    if not all(
        _verify_artifact(cast(dict[str, Any], artifact), language_bundle)
        for artifact in artifacts.values()
    ):
        raise RuntimeError("prepared output failed artifact-schema admission")
    publication_artifacts = {
        name: PublicationMember(
            value=cast(dict[str, Any], artifact),
            artifact_kind=cast(str, artifact["artifact_kind"]),
            wire_schema_identity=cast(str, artifact["wire_schema_identity"]),
            content_identity=cast(str, artifact["content_identity"]),
        )
        for name, artifact in artifacts.items()
    }
    return _commit_generic_publication(
        invocation_path,
        anchor_path,
        out_path,
        invocation_key,
        descriptor_identity,
        command_input_identity,
        language_bundle,
        artifact_set,
        publication_artifacts,
        lambda _name, value: _verify_artifact(value, language_bundle),
        authentication_key,
        publication_fault,
    )
