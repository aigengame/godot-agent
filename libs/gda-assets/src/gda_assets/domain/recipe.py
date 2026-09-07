"""Project-selected file handoff inputs."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal


@dataclass(frozen=True)
class Resize:
    width: int
    height: int
    resampling: Literal["nearest", "bilinear", "lanczos"] = "nearest"


@dataclass(frozen=True)
class AssetFile:
    source: str
    target: str
    resize: Resize | None = None
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetRecipe:
    files: tuple[AssetFile, ...]
    overwrite: bool = False
    source_mode: Literal["existing", "imagegen"] = "existing"
    provenance: dict[str, Any] | None = None


def target_relative(target: str) -> PurePosixPath:
    """Require an explicit portable resource destination outside engine metadata."""
    if not target.startswith("res://"):
        raise ValueError("Targets must use res:// paths")
    relative = target[6:]
    parts = relative.split("/")
    if (
        any(part in {"", ".", ".."} for part in parts)
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError(f"Invalid destination: {target}")
    if parts[0] in {".godot", ".git"}:
        raise ValueError(f"Destination belongs to tool metadata: {target}")
    return PurePosixPath(relative)


def validate_recipe(recipe: AssetRecipe) -> None:
    if recipe.source_mode not in {"existing", "imagegen"}:
        raise ValueError("Source mode must be existing or imagegen")
    if not 1 <= len(recipe.files) <= 32:
        raise ValueError("A handoff must select between 1 and 32 files")
    targets = set()
    for item in recipe.files:
        target_relative(item.target)
        if item.resize is not None:
            size = item.resize
            if (
                type(size.width) is not int
                or type(size.height) is not int
                or not 1 <= size.width <= 16384
                or not 1 <= size.height <= 16384
                or size.width * size.height > 64 * 1024 * 1024
            ):
                raise ValueError(
                    "Resize dimensions must be positive integers, at most 16384 per axis and 64 megapixels"
                )
            if size.resampling not in {"nearest", "bilinear", "lanczos"}:
                raise ValueError("Unsupported PNG resampling method")
            if not item.target.lower().endswith(".png"):
                raise ValueError("Resize is supported only for PNG files")
        if item.target in targets:
            raise ValueError(f"Duplicate destination: {item.target}")
        targets.add(item.target)
    for item in recipe.files:
        if len(set(item.references)) != len(item.references):
            raise ValueError(f"Duplicate references: {item.target}")
        for reference in item.references:
            if reference not in targets:
                raise ValueError(f"Reference is not a selected member: {reference}")
