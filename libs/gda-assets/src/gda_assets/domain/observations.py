"""Selected disk facts; no durable asset or workflow identity."""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Literal


@dataclass(frozen=True)
class CollectionRequest:
    save_to: Path | None = None
    declared_output_sha256: dict[str, str] = field(default_factory=dict)


def validate_collection(request: CollectionRequest, targets: list[str]) -> None:
    for path, digest in request.declared_output_sha256.items():
        if path not in targets:
            raise ValueError(f"Declared output is not selected: {path}")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None
        ):
            raise ValueError(
                f"Declared output SHA-256 must be 64 hexadecimal characters: {path}"
            )


@dataclass(frozen=True)
class ImportAssetFacts:
    path: str
    cache_status: str
    configuration: str | None = None
    artifacts: tuple[str, ...] = ()
    declared_importer: str | None = None
    declared_source_file: str | None = None
    artifacts_omitted: int = 0


@dataclass(frozen=True)
class FileDigest:
    path: str
    state: Literal["observed", "missing", "unavailable", "changed"]
    sha256: str | None = None
    size: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FileChange:
    before: FileDigest
    after: FileDigest | None


@dataclass
class AssetDiskObservation:
    path: str
    declared_dependencies: tuple[str, ...]
    import_before: ImportAssetFacts | None = None
    import_after: ImportAssetFacts | None = None
    source_before: FileDigest | None = None
    source_after: FileDigest | None = None
    configuration_before: FileDigest | None = None
    configuration_after: FileDigest | None = None
    artifacts: list[FileDigest] = field(default_factory=list)
    engine: dict[str, Any] | None = None
    unavailable: list[str] = field(default_factory=list)


@dataclass
class ContentObservations:
    status: Literal["incomplete", "stable", "changed"] = "incomplete"
    assets: list[AssetDiskObservation] = field(default_factory=list)
    declared_output_sha256: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    changes: list[FileChange] = field(default_factory=list)
    saved_to: str | None = None
    limitations: tuple[str, ...] = (
        "SHA-256 identifies observed file bytes, not semantic configuration or asset identity.",
        "Inputs cover selected installed sources and recipe-declared selected references only; other importer inputs are unresolved.",
        "Configuration is the published sidecar file, not proof of every effective importer setting.",
        "Stability compares bounded reads under the single-driver assumption; unobserved changes and cross-tool atomicity are not covered.",
        "Disk/import observations do not prove runtime instance content or full reproducibility.",
    )


def compare_file(
    result: ContentObservations, before: FileDigest | None, after: FileDigest | None
) -> None:
    """A missing pre-import configuration can be created by a cold import."""
    if (
        before is not None
        and before.state == "observed"
        and (after is None or after.state in {"observed", "missing"})
        and before != after
    ):
        result.changes.append(FileChange(before, after))
    if (
        before is not None
        and before.state == "changed"
        or after is not None
        and after.state == "changed"
    ):
        result.status = "changed"
    if result.changes:
        result.status = "changed"


def require_digest(
    result: ContentObservations, digest: FileDigest | None, description: str
) -> None:
    if digest is None or digest.state != "observed":
        result.issues.append(
            f"{description}: {digest.reason if digest else 'not published'}"
        )
        if digest is not None and digest.state == "changed":
            result.status = "changed"


def declared_hash_mismatches(result: ContentObservations) -> list[str]:
    return [
        f"{asset.path}: declared SHA-256 {expected} differs from observed {asset.source_before.sha256}"
        for asset in result.assets
        if (expected := result.declared_output_sha256.get(asset.path)) is not None
        and asset.source_before is not None
        and asset.source_before.state == "observed"
        and expected.lower() != asset.source_before.sha256
    ]
