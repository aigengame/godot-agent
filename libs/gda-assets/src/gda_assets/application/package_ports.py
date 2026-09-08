"""File isolation and returning Godot capabilities needed by package acceptance."""

from pathlib import Path
from typing import Protocol

from gda_assets.domain.package import (
    PackageInspection,
    PackagePresence,
    PackageSnapshot,
)


class PackageFilesPort(Protocol):
    def snapshot(self, source: Path) -> PackageSnapshot: ...

    def remove(self, snapshot: PackageSnapshot) -> None: ...


class GodotPackagePort(Protocol):
    def resource_presence(
        self, package: Path, paths: tuple[str, ...]
    ) -> PackagePresence: ...

    def inspect_model(
        self,
        package: Path,
        path: str,
        *,
        subtree: str,
        max_nodes: int,
        max_items: int,
    ) -> PackageInspection: ...
