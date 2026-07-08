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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

# The default asset root the gate scans (mirrors the manifest/emitter default).
_ASSETS_ROOT = "assets"


class AssetSizeError(Exception):
    """A committed ``assets/**`` binary at/over ``T`` is not Git-LFS-tracked."""


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


def committed_asset_files(
    root: Path, assets_root: str = _ASSETS_ROOT
) -> list[tuple[str, int]]:
    """Every file under ``<root>/<assets_root>`` as ``(relpath-from-root, size)``.

    Sorted for a deterministic report; ``[]`` when the assets tree is absent.
    """
    base = root / assets_root
    if not base.exists():
        return []
    return [
        (str(p.relative_to(root)), p.stat().st_size)
        for p in sorted(base.rglob("*"))
        if p.is_file()
    ]


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
