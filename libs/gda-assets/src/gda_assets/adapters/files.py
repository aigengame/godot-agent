"""Local file admission, staging and installation."""

import os
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile

from gda_assets.application.ports import FilePlan, PortFailure, StagedFile
from gda_assets.domain.artifacts import InstalledFile
from gda_assets.domain.recipe import AssetRecipe, target_relative


def equal_files(left: Path, right: Path) -> bool:
    if not right.is_file() or left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as a, right.open("rb") as b:
        while chunk := a.read(65536):
            if chunk != b.read(65536):
                return False
    return True


def validate_format(source: Path) -> list[str]:
    suffix = source.suffix.lower()
    if suffix == ".png":
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(source) as image:
                if image.format != "PNG":
                    raise ValueError("Expected PNG content")
                if image.width * image.height > 64 * 1024 * 1024:
                    raise ValueError("PNG exceeds the supported 64 megapixel limit")
                image.verify()
            with Image.open(source) as image:
                image.load()
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            ValueError,
            SyntaxError,
            OSError,
        ) as exc:
            raise PortFailure("invalid_asset", f"Invalid PNG {source}: {exc}") from exc
        return []
    elif suffix == ".glb":
        from gda_assets.adapters.glb import external_uris

        return external_uris(source)
    else:
        raise PortFailure(
            "unsupported_format", f"Unsupported asset format: {source.suffix}"
        )


class LocalFiles:
    def validate(
        self, recipe: AssetRecipe, source_root: Path, project_root: Path
    ) -> list[FilePlan]:
        plans = []
        root = project_root.resolve()
        references = {}
        targets = set()
        for item in recipe.files:
            source = (source_root / item.source).resolve()
            if not source.is_file():
                raise PortFailure("source_missing", f"Source file missing: {source}")
            target = (project_root / target_relative(item.target)).resolve()
            if not target.is_relative_to(root):
                raise PortFailure(
                    "invalid_recipe", f"Destination escapes project: {item.target}"
                )
            if target.relative_to(root).parts[0] in {".godot", ".git"}:
                raise PortFailure(
                    "invalid_recipe",
                    f"Destination belongs to tool metadata: {item.target}",
                )
            key = str(target).casefold()
            if key in targets:
                raise PortFailure(
                    "invalid_recipe", f"Aliased destinations: {item.target}"
                )
            targets.add(key)
            for parent in (target, *target.parents):
                if parent == root:
                    break
                if parent.exists() and (
                    parent != target
                    and not parent.is_dir()
                    or parent == target
                    and not parent.is_file()
                ):
                    raise PortFailure(
                        "destination_conflict",
                        f"Target path conflicts with an existing entry: {item.target}",
                    )
            if source.suffix.lower() != target.suffix.lower():
                raise PortFailure(
                    "invalid_recipe", "Source and destination formats must match"
                )
            references[item.target] = validate_format(source)
            if item.resize is not None and source == target.resolve():
                raise PortFailure(
                    "invalid_recipe", "Processing must preserve the source file"
                )
            if target.exists() and not recipe.overwrite and item.resize is None:
                if not equal_files(source, target):
                    raise PortFailure(
                        "destination_conflict", f"Target exists: {item.target}"
                    )
            plans.append(FilePlan(item, source, target))
        by_target = {plan.target.resolve(): plan for plan in plans}
        sources = {plan.source for plan in plans}
        for plan in plans:
            if plan.target in sources and (
                plan.target != plan.source or plan.item.resize is not None
            ):
                raise PortFailure(
                    "invalid_recipe",
                    f"Destination would replace a selected source: {plan.item.target}",
                )
            for uri in references[plan.item.target]:
                referenced = by_target.get((plan.target.parent / uri).resolve())
                if (
                    referenced is None
                    or referenced.item.target not in plan.item.references
                    or referenced.source != (plan.source.parent / uri).resolve()
                ):
                    raise PortFailure(
                        "invalid_reference",
                        f"{plan.item.target}: declare and map relative reference {uri!r} with its source file",
                    )
        return plans

    def stage(self, plan: FilePlan, workspace: Path, index: int) -> StagedFile:
        path = workspace / str(index)
        if plan.item.resize is None:
            shutil.copyfile(plan.source, path)
        else:
            from gda_assets.adapters.raster import resize_png

            resize_png(plan.source, path, plan.item.resize)
        return StagedFile(plan, path)

    def validate_installation(
        self, staged: list[StagedFile], *, overwrite: bool
    ) -> None:
        for item in staged:
            target = item.plan.target
            if target.exists() and not overwrite and not equal_files(item.path, target):
                raise PortFailure(
                    "destination_conflict", f"Target exists: {item.plan.item.target}"
                )

    def install(self, staged: StagedFile, *, overwrite: bool) -> InstalledFile:
        plan = staged.plan
        if plan.target.resolve() != plan.target:
            raise PortFailure(
                "destination_conflict",
                f"Target path changed after validation: {plan.item.target}",
            )
        if equal_files(staged.path, plan.target):
            return InstalledFile(
                plan.item.source, plan.item.target, "unchanged", plan.item.resize
            )
        if plan.target.exists() and not overwrite:
            raise PortFailure(
                "destination_conflict", f"Target exists: {plan.item.target}"
            )
        plan.target.parent.mkdir(parents=True, exist_ok=True)
        # Each replacement is complete, but the file set is not a transaction.
        # An exception leaves earlier installed files in the returned outcomes.
        with NamedTemporaryFile(
            prefix=".gda-assets-", dir=plan.target.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(staged.path, temporary)
            if overwrite:
                os.replace(temporary, plan.target)
            else:
                # Refuse a target created after validation without truncating it.
                try:
                    os.link(temporary, plan.target)
                except FileExistsError as exc:
                    raise PortFailure(
                        "destination_conflict", f"Target appeared: {plan.item.target}"
                    ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return InstalledFile(
            plan.item.source, plan.item.target, "installed", plan.item.resize
        )
