"""Authenticated artifact publication, recovery, and retrieval."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from gda_balancing.domain.artifact_errors import PublishedArtifactIntegrityError
from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.authority.context import (
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    parse_canonical_object,
)
from gda_balancing.domain.errors import UnreadableInputError, UsageError
from gda_balancing.domain.model.inspection_types import ModelInspectAdmissionError
from gda_balancing.domain.model.semantics import (
    CheckedModel,
    _LOWERER_IMPLEMENTATION_IDENTITY,
    _RESOLVER_IMPLEMENTATION_IDENTITY,
    _capability_manifest,
    _identified_artifact,
    _model_explanation,
    _model_explanation_pairs_are_admitted,
    _model_lowering,
    _normalized_absolute_path,
    _resolution_profile,
    _strict_object,
    _verify_artifact,
    admit_resolved_model,
    lower_checked_model,
)
from gda_balancing.domain.path_contracts import reject_input_aliasing
from gda_balancing.domain.publication_types import (
    PublicationMember,
    RecoveredArtifactSet,
)
from gda_balancing.infrastructure.atomic_files import (
    exclusive_file_lock as _invocation_lock,
    fsync_directory as _fsync_directory,
    write_exclusive_bytes,
)

_STORE_DIRECTORY_ENV = "GDA_BALANCING_STORE_DIR"
_ANCHOR_KEY_ENV = "GDA_BALANCING_ANCHOR_KEY"


def find_published_artifact(
    content_identity_value: str,
    artifact_kind: str,
    language_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve one exact artifact through authenticated committed publications.

    Locators remain transport facts: callers bind semantic identities, while
    this local-store adapter discovers a locator and then revalidates the
    authenticated publication frame, artifact schema, and content hash.
    """
    anchors = _store_root() / "anchors"
    if not anchors.exists():
        return None
    authentication_key = publication_authentication_key()
    matches: list[dict[str, Any]] = []
    for anchor_path in sorted(anchors.glob("*/*.json")):
        if anchor_path.is_symlink() or not anchor_path.is_file():
            continue
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
            for member in members:
                if (
                    not isinstance(member, dict)
                    or member.get("artifact_kind") != artifact_kind
                    or member.get("content_identity") != content_identity_value
                    or not isinstance(member.get("logical_name"), str)
                ):
                    continue
                try:
                    artifact = _read_canonical_artifact(
                        invocation_path / f"{member['logical_name']}.json"
                    )
                except (OSError, RuntimeError, UsageError, ValueError) as err:
                    raise PublishedArtifactIntegrityError(
                        "authenticated publication member is unreadable or non-canonical"
                    ) from err
                if not (
                    _verify_artifact(artifact, language_bundle)
                    and artifact.get("artifact_kind") == artifact_kind
                    and artifact.get("content_identity") == content_identity_value
                ):
                    raise PublishedArtifactIntegrityError(
                        "authenticated publication member failed schema or identity "
                        "verification"
                    )
                matches.append(artifact)
        except PublishedArtifactIntegrityError:
            raise
        except (OSError, RuntimeError, UsageError, ValueError):
            continue
    if not matches:
        return None
    canonical = canonical_bytes(cast(JsonValue, matches[0]))
    if any(canonical_bytes(cast(JsonValue, item)) != canonical for item in matches[1:]):
        raise PublishedArtifactIntegrityError(
            "one content identity resolved to different authenticated artifacts"
        )
    return matches[0]


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    data = canonical_bytes(cast(JsonValue, value))
    write_exclusive_bytes(path, data)


def _read_canonical_artifact(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise UsageError(
                "argument_conflict",
                f"publication members must not be symlinks: {path.name}",
            )
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(
                f"committed publication member is not a regular file: {path.name}"
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read()
        value = _strict_object(data)
    except UsageError:
        raise
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
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise UnreadableInputError(f"input document is not a regular file: {path}")
        return parse_canonical_object(
            path.read_bytes(),
            artifact_name="Model build receipt",
        )
    except UnreadableInputError:
        raise
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as err:
        raise ModelInspectAdmissionError(
            "kernel.identity_mismatch",
            "receipt",
            "Model build receipt is not an admissible JSON artifact",
        ) from err


def _inspect_committed_artifact(
    path: Path,
    *,
    code: str,
    subject: str,
) -> dict[str, Any]:
    try:
        return _read_canonical_artifact(path)
    except (RuntimeError, UsageError) as err:
        raise ModelInspectAdmissionError(
            code,
            subject,
            f"committed Model build member failed admission: {path.name}",
        ) from err


def read_model_explanation(
    receipt_path: str,
    expected_descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> dict[str, JsonValue]:
    """Retrieve and authenticate the stored explanation from one committed build."""
    path = _normalized_absolute_path(receipt_path)
    receipt = _read_receipt_input(path)
    context = packaged_authority_context()
    kernel = context.kernel
    language_bundle = context.language_bundle
    if (
        not _verify_artifact(receipt, language_bundle)
        or receipt.get("artifact_kind") != "artifact-set-receipt"
    ):
        raise ModelInspectAdmissionError(
            "kernel.identity_mismatch",
            "receipt",
            "Model build receipt failed exact-authority admission",
        )
    descriptor_identity_value = receipt.get("descriptor_identity")
    invocation_key = receipt.get("invocation_key")
    if descriptor_identity_value != expected_descriptor_identity or not isinstance(
        invocation_key, str
    ):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "receipt.descriptor_identity",
            "Model build receipt belongs to another command or invocation",
        )
    invocation_path = _store_invocation_path(
        expected_descriptor_identity, invocation_key
    )
    manifest_locator = receipt.get("manifest_locator")
    if not isinstance(manifest_locator, str):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "receipt.manifest_locator",
            "Model build receipt has no manifest locator",
        )
    manifest_path = _normalized_absolute_path(manifest_locator)
    publication_dir = manifest_path.parent
    try:
        _assert_directory_without_symlink(publication_dir)
    except (RuntimeError, UsageError) as err:
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "receipt.manifest_locator",
            "Model build manifest locator failed admission",
        ) from err
    expected_manifest_path = invocation_path / "artifact-set-manifest.json"
    if manifest_path != expected_manifest_path:
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "receipt.manifest_locator",
            "Model build receipt does not locate its committed publication",
        )
    anchor_path = _store_anchor_path(expected_descriptor_identity, invocation_key)
    authentication_key = publication_authentication_key()
    try:
        _assert_ancestor_chain_without_symlink(invocation_path)
        _assert_ancestor_chain_without_symlink(anchor_path)
        anchor_metadata = anchor_path.lstat()
        if (
            not stat.S_ISREG(anchor_metadata.st_mode)
            or stat.S_IMODE(anchor_metadata.st_mode) & 0o222
        ):
            raise RuntimeError("committed publication anchor is not immutable")
        index = _verified_anchor(anchor_path, authentication_key)
        committed_index = _read_canonical_artifact(
            invocation_path / "publication-index.json"
        )
        committed_receipt = _read_canonical_artifact(
            invocation_path / "artifact-set-receipt.json"
        )
    except (OSError, RuntimeError, UsageError, ValueError) as err:
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "publication-index",
            "Model build publication anchor failed authentication",
        ) from err
    if (
        not _verify_artifact(index, language_bundle)
        or committed_index != index
        or index.get("descriptor_identity") != expected_descriptor_identity
        or index.get("invocation_key") != invocation_key
        or index.get("receipt_identity") != receipt.get("content_identity")
        or committed_receipt != receipt
    ):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "publication-index",
            "Model build publication index does not authenticate the receipt",
        )
    manifest = _inspect_committed_artifact(
        expected_manifest_path,
        code="kernel.binding_mismatch",
        subject="manifest",
    )
    if not _verify_artifact(manifest, language_bundle) or manifest.get(
        "content_identity"
    ) != receipt.get("manifest_identity"):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "manifest",
            "Model build manifest failed exact-authority admission",
        )
    members = manifest.get("members")
    locators = receipt.get("member_locators")
    if not isinstance(members, list) or not isinstance(locators, list):
        raise ModelInspectAdmissionError(
            "kernel.member_set_mismatch",
            "manifest.members",
            "Model build has no closed artifact member map",
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
        raise ModelInspectAdmissionError(
            "kernel.member_set_mismatch",
            "manifest.members",
            "Model build publication does not match the command artifact set",
        )
    artifacts: dict[str, dict[str, Any]] = {}
    for row in members:
        if not isinstance(row, dict):
            raise ModelInspectAdmissionError(
                "kernel.member_set_mismatch",
                "manifest.members",
                "Model build publication contains a malformed member",
            )
        name = row.get("logical_name")
        if not isinstance(name, str) or row.get("artifact_kind") != expected_kinds.get(
            name
        ):
            raise ModelInspectAdmissionError(
                "kernel.member_set_mismatch",
                "manifest.members",
                "Model build publication contains an undeclared member",
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
            raise ModelInspectAdmissionError(
                "kernel.binding_mismatch",
                name,
                "committed Model build member failed exact-authority admission",
            )
        artifacts[name] = artifact

    if not admit_resolved_model(
        {
            name: artifacts[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        },
        authority_context=context,
    ).admitted:
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "resolved-model",
            "committed Resolved Model failed exact-authority admission",
        )
    lock = artifacts["package-lock"]
    rir = artifacts["rir-semantic-payload"]
    resolved = artifacts["resolved-model"]
    capability_manifest = artifacts["capability-manifest"]
    build_receipt = artifacts["build-receipt"]
    debug_map = artifacts["debug-map"]
    resolution_receipt = artifacts["resolution-receipt"]
    explanation = artifacts["model-explanation"]
    source_identity = build_receipt.get("source_identity")
    expected_build_bindings = {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "source_identity": source_identity,
        "kernel_identity": kernel["content_identity"],
        "language_bundle_identity": language_bundle["content_identity"],
        "package_lock_identity": lock["content_identity"],
        "rir_identity": rir["content_identity"],
        "resolved_model_identity": resolved["content_identity"],
        "capability_manifest_identity": capability_manifest["content_identity"],
        "debug_map_identity": debug_map["content_identity"],
        "model_explanation_identity": explanation["content_identity"],
        "resolution_receipt_identity": resolution_receipt["content_identity"],
    }
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    if (
        not isinstance(source_identity, str)
        or capability_manifest
        != _capability_manifest(lock, rir, resolved, language_bundle)
        or any(
            build_receipt.get(key) != value
            for key, value in expected_build_bindings.items()
        )
        or debug_map.get("source_identity") != source_identity
        or debug_map.get("rir_identity") != rir["content_identity"]
        or resolution_receipt.get("resolver") != _RESOLVER_IMPLEMENTATION_IDENTITY
        or resolution_receipt.get("resolution_profile") != profile["id"]
        or resolution_receipt.get("source_identity") != source_identity
        or resolution_receipt.get("kernel_identity") != kernel["content_identity"]
        or resolution_receipt.get("language_bundle_identity")
        != language_bundle["content_identity"]
        or resolution_receipt.get("package_lock_identity") != lock["content_identity"]
        or resolution_receipt.get("diagnostics") != []
    ):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "build-receipt",
            "committed Model build members have inconsistent bindings",
        )
    if not _model_explanation_pairs_are_admitted(
        explanation,
        rir,
        lock,
        context,
    ):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "model-explanation",
            "committed Model explanation Formula pairs failed admission",
        )
    return cast(dict[str, JsonValue], explanation)


def _assert_directory_without_symlink(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as err:
        raise RuntimeError(f"publication directory is unavailable: {path}") from err
    if stat.S_ISLNK(metadata.st_mode):
        raise UsageError(
            "argument_conflict", f"publication directory must not be a symlink: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"publication path is not a directory: {path}")


def _store_root() -> Path:
    configured = os.environ.get(_STORE_DIRECTORY_ENV)
    if configured:
        return _normalized_absolute_path(configured)
    state_home = os.environ.get("XDG_STATE_HOME")
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
    encoded = os.environ.get(_ANCHOR_KEY_ENV)
    if (
        encoded is None
        or len(encoded) != 64
        or encoded.lower() != encoded
        or any(character not in "0123456789abcdef" for character in encoded)
    ):
        raise UsageError(
            "invalid_argument",
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
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        if before_commit:
            raise RuntimeError("injected publication fault before anchor commit")
        try:
            os.link(temporary, path)
        except OSError as err:
            raise RuntimeError(
                "publication anchor already exists or is unwritable"
            ) from err
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


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
    for candidate in reversed((path, *path.parents)):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        try:
            metadata = candidate.lstat()
        except OSError as err:
            raise RuntimeError(
                f"cannot inspect publication path ancestor: {candidate}"
            ) from err
        if stat.S_ISLNK(metadata.st_mode):
            raise UsageError(
                "argument_conflict",
                f"publication path ancestors must not be symlinks: {candidate}",
            )


def _ensure_directory_chain(path: Path) -> None:
    _assert_ancestor_chain_without_symlink(path)
    missing = [
        candidate
        for candidate in reversed((path, *path.parents))
        if not candidate.exists()
    ]
    for directory in missing:
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        else:
            _fsync_directory(directory.parent)
    _assert_directory_without_symlink(path)


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
        raise UsageError(
            "argument_conflict",
            "--out must not overlap the immutable publication store",
        )
    parent = out_path.parent
    _assert_ancestor_chain_without_symlink(parent)
    if parent.is_symlink() or not parent.is_dir():
        raise UsageError(
            "unwritable_output", f"cannot write output directory: {out_path}"
        )
    if out_path.is_symlink():
        raise UsageError("argument_conflict", "--out must not be a symlink")


def _materialize_primary(out_path: Path, resolved: dict[str, Any]) -> None:
    data = canonical_bytes(cast(JsonValue, resolved))
    if out_path.is_symlink():
        raise UsageError("argument_conflict", "--out must not be a symlink")
    if out_path.exists():
        try:
            metadata = out_path.lstat()
            existing = out_path.read_bytes()
        except OSError as err:
            raise UsageError(
                "unwritable_output", f"cannot inspect output: {out_path}"
            ) from err
        if not stat.S_ISREG(metadata.st_mode):
            raise UsageError(
                "unwritable_output", f"output is not a regular file: {out_path}"
            )
        if existing == data:
            return
        raise UsageError(
            "unwritable_output", f"output already contains different bytes: {out_path}"
        )
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{out_path.name}.", dir=out_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if out_path.is_symlink() or out_path.exists():
            raise UsageError(
                "unwritable_output", f"output appeared during publication: {out_path}"
            )
        os.replace(temporary, out_path)
        _fsync_directory(out_path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


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
    try:
        anchor_metadata = anchor_path.lstat()
    except OSError as err:
        raise RuntimeError("committed publication anchor is unavailable") from err
    if (
        not stat.S_ISREG(anchor_metadata.st_mode)
        or stat.S_IMODE(anchor_metadata.st_mode) & 0o222
    ):
        raise RuntimeError("committed publication anchor trust boundary is invalid")
    anchor = _verified_anchor(anchor_path, authentication_key)
    index = _read_canonical_artifact(invocation_path / "publication-index.json")
    if not _verify_artifact(index, language_bundle) or index != anchor:
        raise RuntimeError("committed publication index identity is invalid")
    if index.get("descriptor_identity") != descriptor_identity:
        raise RuntimeError("publication index belongs to another command")
    if index.get("invocation_key") != invocation_key:
        raise RuntimeError("publication index belongs to another invocation")
    if index.get("command_input_identity") != command_input_identity:
        raise UsageError(
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
    semantic_artifacts = {
        name: artifacts[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }
    if not admit_resolved_model(semantic_artifacts).admitted:
        raise RuntimeError("committed Resolved Model failed exact-authority admission")
    lock = artifacts["package-lock"]
    rir = artifacts["rir-semantic-payload"]
    resolved = artifacts["resolved-model"]
    if artifacts["capability-manifest"] != _capability_manifest(
        lock, rir, resolved, language_bundle
    ):
        raise RuntimeError("committed Capability manifest is not an exact projection")
    if artifacts["model-explanation"] != _model_explanation(
        authority_context,
        cast(dict[str, JsonValue], lock),
        cast(dict[str, JsonValue], rir),
        cast(dict[str, JsonValue], artifacts["debug-map"]),
    ):
        raise RuntimeError("committed Model explanation is not an exact projection")
    build_receipt = artifacts["build-receipt"]
    debug_map = artifacts["debug-map"]
    resolution_receipt = artifacts["resolution-receipt"]
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    kernel_identity = kernel["content_identity"]
    expected_build_bindings = {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "source_identity": source_identity,
        "kernel_identity": kernel_identity,
        "language_bundle_identity": language_bundle["content_identity"],
        "package_lock_identity": lock["content_identity"],
        "rir_identity": rir["content_identity"],
        "resolved_model_identity": resolved["content_identity"],
        "capability_manifest_identity": artifacts["capability-manifest"][
            "content_identity"
        ],
        "debug_map_identity": debug_map["content_identity"],
        "model_explanation_identity": artifacts["model-explanation"][
            "content_identity"
        ],
        "resolution_receipt_identity": resolution_receipt["content_identity"],
    }
    if any(
        build_receipt.get(key) != value
        for key, value in expected_build_bindings.items()
    ):
        raise RuntimeError("committed build receipt has invalid bindings")
    if (
        debug_map.get("source_identity") != source_identity
        or debug_map.get("rir_identity") != rir["content_identity"]
        or resolution_receipt.get("resolver") != _RESOLVER_IMPLEMENTATION_IDENTITY
        or resolution_receipt.get("resolution_profile") != profile["id"]
        or resolution_receipt.get("source_identity") != source_identity
        or resolution_receipt.get("kernel_identity") != kernel_identity
        or resolution_receipt.get("language_bundle_identity")
        != language_bundle["content_identity"]
        or resolution_receipt.get("package_lock_identity") != lock["content_identity"]
        or resolution_receipt.get("diagnostics") != []
    ):
        raise RuntimeError("committed provenance artifacts have invalid bindings")
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
    if lock_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
        anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
        _assert_ancestor_chain_without_symlink(invocation_path)
        if invocation_path.is_symlink():
            raise UsageError(
                "argument_conflict",
                "Invocation-key publication must not be a symlink",
            )
        if invocation_path.exists() and not anchor_path.exists():
            _assert_directory_without_symlink(invocation_path)
            shutil.rmtree(invocation_path)
            _fsync_directory(invocation_path.parent)
        if invocation_path.exists():
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
        if out_path.exists():
            raise UsageError("unwritable_output", f"output already exists: {out_path}")
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
    if not invocation_path.exists() or not anchor_path.exists():
        return None
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    with _invocation_lock(lock_path):
        if not invocation_path.exists() or not anchor_path.exists():
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
    try:
        anchor_metadata = anchor_path.lstat()
    except OSError as err:
        raise RuntimeError("committed publication anchor is unavailable") from err
    if (
        not stat.S_ISREG(anchor_metadata.st_mode)
        or stat.S_IMODE(anchor_metadata.st_mode) & 0o222
    ):
        raise RuntimeError("committed publication anchor trust boundary is invalid")
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
        raise UsageError(
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
        existed = directory.exists()
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
    stage = Path(tempfile.mkdtemp(prefix=f".{invocation_key}.", dir=descriptor_parent))
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
        if invocation_path.exists() or invocation_path.is_symlink():
            raise RuntimeError("Invocation-key publication appeared before commit")
        os.replace(stage, invocation_path)
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
        if stage.exists():
            shutil.rmtree(stage)
        if (
            committed
            and not anchored
            and invocation_path.exists()
            and not anchor_path.exists()
        ):
            shutil.rmtree(invocation_path)
            _fsync_directory(invocation_path.parent)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return receipt


def publish_model_artifacts(
    checked: CheckedModel,
    source_path: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    publication_fault: str | None = None,
    *,
    authentication_key: bytes | None = None,
    compiler: (Callable[[CheckedModel], dict[str, dict[str, JsonValue]]] | None) = None,
) -> dict[str, JsonValue]:
    """Serialize one invocation key before inspecting or changing its publication."""
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    out_path = _normalized_absolute_path(out)
    reject_input_aliasing(out_path, source_path, input_is_known_path=True)
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    _validate_presentation_path(out_path, invocation_path)
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    if lock_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
        return _publish_model_artifacts_locked(
            checked,
            out_path,
            invocation_key,
            descriptor_identity,
            artifact_set,
            authentication_key,
            publication_fault,
            compiler,
        )


def _publish_model_artifacts_locked(
    checked: CheckedModel,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    authentication_key: bytes,
    publication_fault: str | None = None,
    compiler: Callable[[CheckedModel], dict[str, dict[str, JsonValue]]] | None = None,
) -> dict[str, JsonValue]:
    """Atomically publish one complete build set while its invocation lock is held."""
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    command_input = _identified_artifact(
        checked.language_bundle,
        "model-build-command-input",
        {
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
        },
    )
    command_input_identity = cast(str, command_input["content_identity"])
    _assert_ancestor_chain_without_symlink(invocation_path)
    if invocation_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key publication must not be a symlink"
        )
    if invocation_path.exists() and not anchor_path.exists():
        _assert_directory_without_symlink(invocation_path)
        shutil.rmtree(invocation_path)
        _fsync_directory(invocation_path.parent)
    if invocation_path.exists():
        return _recover_publication(
            invocation_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            checked.source_identity,
            checked.kernel,
            checked.language_bundle,
            artifact_set,
            authentication_key,
        )
    if out_path.exists():
        raise UsageError("unwritable_output", f"output already exists: {out_path}")

    artifacts = (compiler or lower_checked_model)(checked)
    semantic_admission = admit_resolved_model(
        {
            name: cast(dict[str, Any], artifacts[name])
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        }
    )
    if not semantic_admission.admitted:
        raise RuntimeError("lowerer produced a Resolved Model that failed admission")
    declared = {member.logical_name: member.artifact_kind for member in artifact_set}
    if set(artifacts) != set(declared) or any(
        artifacts[name]["artifact_kind"] != declared[name] for name in artifacts
    ):
        raise RuntimeError("lowerer output does not match the descriptor artifact set")
    if not all(
        _verify_artifact(cast(dict[str, Any], artifact), checked.language_bundle)
        for artifact in artifacts.values()
    ):
        raise RuntimeError("lowerer output failed artifact-schema admission")
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
        checked.language_bundle,
        artifact_set,
        publication_artifacts,
        lambda _name, value: _verify_artifact(value, checked.language_bundle),
        authentication_key,
        publication_fault,
    )
