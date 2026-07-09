"""Asset-lifecycle governance — the size-based Git-LFS gate (gADR-0015).

A large binary can appear in ANY asset category (a BGM track, a 2K/4K background),
so the plain-git-vs-LFS boundary is a single size threshold ``T`` applied uniformly,
never a per-category rule: an ``assets/**`` file at or over ``T`` must be tracked by
Git LFS; below ``T`` it stays in plain git. This gate enforces that mechanically so
a large file is *born* in LFS rather than committed to plain git and migrated later
(which rewrites history — the failure mode gADR-0015 exists to avoid).

The core (:func:`find_unlfs_oversize`) is pure — it takes the file sizes and an
injected "is this path LFS-tracked?" predicate, so it is unit-testable with no git.
The repo-scoped wiring (:func:`validate_committed_asset_sizes`) supplies the real
predicate via ``git check-attr`` and the real sizes from the working tree.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

# The default asset root the gate scans (mirrors the manifest/emitter default).
_ASSETS_ROOT = "assets"


class AssetSizeError(Exception):
    """A committed ``assets/**`` binary at/over ``T`` is not Git-LFS-tracked."""


class LicenseModeError(Exception):
    """A manifest entry's license is inconsistent with its acquire mode (gADR-0015)."""


@dataclass(frozen=True)
class LicenseModeViolation:
    """A manifest entry whose ``license`` does not match its ``acquire_mode``."""

    asset_id: str
    acquire_mode: str
    license: str
    reason: str


def find_license_mode_violations(
    entries: Iterable[tuple[str, str, str]],
    download_licenses: Collection[str],
) -> list[LicenseModeViolation]:
    """The licensing gate's pure core: which ``(id, acquire_mode, license)`` entries
    record a license inconsistent with how the asset was acquired (gADR-0015 §5d).

    A ``search_download`` asset carries a DOWNLOAD license (its source's terms — the
    ``download_licenses`` allowlist, CC0/CC-BY). A ``generation`` asset carries its
    BACKEND's usage terms instead — a distinct, non-empty token that must NOT be a
    download license (so a generated asset mislabeled ``CC0`` is caught). Other/blank
    modes carry no rule here (the record-shape gate covers missing fields). Backend-
    and game-agnostic (no manifest/dict/game coupling), so every asset slice reuses
    it; returns the violations in input order (empty when all are consistent)."""
    allowed = set(download_licenses)
    out: list[LicenseModeViolation] = []
    for asset_id, mode, license_name in entries:
        if mode == "search_download":
            if license_name not in allowed:
                out.append(
                    LicenseModeViolation(
                        asset_id,
                        mode,
                        license_name,
                        "a downloaded asset must record a download license "
                        f"({sorted(allowed)})",
                    )
                )
        elif mode == "generation":
            if not license_name:
                out.append(
                    LicenseModeViolation(
                        asset_id,
                        mode,
                        license_name,
                        "a generated asset must record its backend's usage terms",
                    )
                )
            elif license_name in allowed:
                out.append(
                    LicenseModeViolation(
                        asset_id,
                        mode,
                        license_name,
                        "a generated asset must record its backend's usage terms, "
                        f"not a download license ({sorted(allowed)}) — gADR-0015 §5d",
                    )
                )
    return out


def validate_license_modes(
    entries: Iterable[tuple[str, str, str]],
    download_licenses: Collection[str],
) -> list[LicenseModeViolation]:
    """Raise :class:`LicenseModeError` if any entry's license/mode is inconsistent.

    The wired counterpart of :func:`find_license_mode_violations` (mirrors the size
    gate's raise-on-violation shape); returns the empty violation list on success."""
    violations = find_license_mode_violations(entries, download_licenses)
    if violations:
        listing = "; ".join(
            f"{v.asset_id!r} ({v.acquire_mode}, license {v.license!r}): {v.reason}"
            for v in violations
        )
        raise LicenseModeError(
            f"{len(violations)} manifest entr(ies) with a license inconsistent with "
            f"the acquire mode (gADR-0015 §5d): {listing}"
        )
    return violations


@dataclass(frozen=True)
class OversizeAsset:
    """An ``assets/**`` file at/over ``T`` that is NOT LFS-tracked — a violation."""

    path: str
    size: int


def find_unlfs_oversize(
    files: Iterable[tuple[str, int]],
    threshold: int,
    is_lfs_tracked: Callable[[str], bool],
) -> list[OversizeAsset]:
    """The gate's pure core: which ``(path, size)`` files break the size rule.

    A file is a violation iff its ``size`` is at or over ``threshold`` (``>= T``,
    inclusive) and ``is_lfs_tracked(path)`` is false. Returns the violations in
    input order (empty when every large file is LFS-tracked).
    """
    return [
        OversizeAsset(path, size)
        for path, size in files
        if size >= threshold and not is_lfs_tracked(path)
    ]


def _is_binary(path: Path, chunk: int = 8192) -> bool:
    """Heuristic: a file whose head carries a NUL byte is binary (text has none).

    The size rule targets binary assets (textures, audio) — a large *text* asset
    (a generated JSON) stays diff-friendly plain git, so the gate skips it.
    """
    with open(path, "rb") as handle:
        return b"\0" in handle.read(chunk)


def committed_asset_files(
    root: Path, assets_root: str = _ASSETS_ROOT
) -> list[tuple[str, int]]:
    """The COMMITTED binary assets under ``<assets_root>`` as ``(relpath, size)``.

    Enumerates ``git ls-files`` (tracked files only — an untracked local scratch
    file is not a commit and is not the gate's concern) and keeps only binary
    files (:func:`_is_binary`), so the gate matches the spec's "``assets/**``
    binary ``>= T`` committed outside LFS". ``[]`` outside a git repo / when the
    tree has no tracked binaries.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", assets_root],
        cwd=root,
        capture_output=True,
        text=True,
    )
    out: list[tuple[str, int]] = []
    for rel in result.stdout.split("\0"):
        if not rel:
            continue
        path = root / rel
        if path.is_file() and _is_binary(path):
            out.append((rel, path.stat().st_size))
    return out


def git_lfs_tracked(root: Path) -> Callable[[str], bool]:
    """A predicate: is ``<root>/<relpath>`` covered by a Git-LFS filter attribute?

    Uses ``git check-attr filter``, which reads ``.gitattributes`` without needing
    the ``git-lfs`` binary or a staged file. A path an LFS pattern covers prints
    ``<path>: filter: lfs``; anything else prints ``unspecified``/another filter.
    """

    def _tracked(rel: str) -> bool:
        result = subprocess.run(
            ["git", "check-attr", "filter", "--", rel],
            cwd=root,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip().rsplit(" ", 1)[-1] == "lfs"

    return _tracked


def validate_committed_asset_sizes(
    root: Path,
    threshold: int,
    *,
    is_lfs_tracked: Callable[[str], bool] | None = None,
) -> list[OversizeAsset]:
    """Enforce the size-based LFS gate over ``root``'s committed assets tree.

    Reads on-disk sizes from the working tree and, by default, the real
    ``git check-attr`` LFS predicate. Raises :class:`AssetSizeError` listing every
    ``assets/**`` file at/over ``threshold`` that is not LFS-tracked; returns the
    (empty) violation list on success. ``is_lfs_tracked`` is injectable for tests.
    """
    predicate = is_lfs_tracked or git_lfs_tracked(root)
    violations = find_unlfs_oversize(committed_asset_files(root), threshold, predicate)
    if violations:
        listing = ", ".join(f"{v.path} ({v.size} bytes)" for v in violations)
        raise AssetSizeError(
            f"{len(violations)} asset(s) at/over {threshold} bytes committed "
            f"outside Git LFS: {listing}. Track the path(s) with `git lfs track` "
            "so a large file is born in LFS, never committed to plain git and "
            "migrated later — which rewrites history (gADR-0015)."
        )
    return violations
