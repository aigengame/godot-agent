"""Bounded staging for one caller-supplied Godot package."""

from pathlib import Path
import shutil
import stat
import tempfile

from gda_assets.application.ports import PortFailure
from gda_assets.adapters.file_copy import copy_with_sha256
from gda_assets.domain.package import PackageSnapshot


MAX_PACKAGE_BYTES = 1024 * 1024 * 1024


class PackageFiles:
    """Stage and remove only package directories created by this instance."""

    def __init__(self) -> None:
        self._owned: dict[Path, tuple[Path, tuple[int, int]]] = {}

    def snapshot(self, source: Path) -> PackageSnapshot:
        if source.suffix.lower() != ".pck":
            raise PortFailure("invalid_package", "Package source must be a PCK file")
        try:
            source = source.resolve(strict=True)
            before_path = source.stat()
        except OSError as exc:
            raise PortFailure(
                "invalid_package", f"Could not read package source: {exc}"
            ) from exc
        if not stat.S_ISREG(before_path.st_mode):
            raise PortFailure(
                "invalid_package", f"Package source is not a regular file: {source}"
            )
        if before_path.st_size > MAX_PACKAGE_BYTES:
            raise PortFailure(
                "invalid_package",
                f"Package source exceeds the {MAX_PACKAGE_BYTES}-byte limit",
            )
        root: Path | None = None
        try:
            root = Path(tempfile.mkdtemp(prefix="gda-package-"))
            destination = root / "package.pck"
            digest, size = copy_with_sha256(
                source, destination, max_bytes=MAX_PACKAGE_BYTES
            )
            root_info = root.stat()
            self._owned[root] = (
                destination,
                (root_info.st_dev, root_info.st_ino),
            )
            return PackageSnapshot(
                source=str(source),
                path=destination,
                root=root,
                sha256=digest,
                size_bytes=size,
            )
        except PortFailure as exc:
            if root is not None:
                self._clean_partial(root, exc)
            raise
        except (OSError, shutil.Error) as exc:
            if root is not None:
                self._clean_partial(root, exc)
            raise PortFailure(
                "package_stage_failed", f"Could not stage package: {exc}"
            ) from exc

    @staticmethod
    def _clean_partial(root: Path, stage_error: Exception) -> None:
        try:
            shutil.rmtree(root)
        except (OSError, shutil.Error) as cleanup_error:
            raise PortFailure(
                "package_cleanup_failed",
                f"Could not clean failed package staging directory {root}: {cleanup_error}",
                cause={"stage_error": str(stage_error), "retained_root": str(root)},
            ) from cleanup_error

    def remove(self, snapshot: PackageSnapshot) -> None:
        root = snapshot.root
        owned = self._owned.get(root)
        try:
            root_info = root.lstat()
            identity = (root_info.st_dev, root_info.st_ino)
            if (
                owned is None
                or snapshot.path != owned[0]
                or snapshot.path.parent != root
                or identity != owned[1]
                or not stat.S_ISDIR(root_info.st_mode)
            ):
                raise ValueError("snapshot is not owned by this adapter instance")
            shutil.rmtree(root)
        except (OSError, ValueError, shutil.Error) as exc:
            raise PortFailure(
                "package_cleanup_failed",
                f"Refusing or unable to remove package snapshot: {exc}",
            ) from exc
        del self._owned[root]
