"""Local files for one isolated, owned model-preview project."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from gda_assets.adapters.files import validate_format
from gda_assets.adapters.preview_baseline import read_preview_baseline
from gda_assets.application.ports import PortFailure
from gda_assets.domain.preview import (
    PreviewCamera,
    PreviewSettings,
    validate_settings,
)
from gda_assets.domain.preview_result import PreviewResult


_FIXTURE = Path(__file__).with_name("preview_fixture")
_OWNERSHIP_MARKER = ".gda-preview-owned"
_BUDGET_LIMIT = 1024 * 1024
_READ_SIZE = 64 * 1024


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _copy_with_sha256(source: Path, destination: Path) -> str:
    before_path = source.stat()
    if not stat.S_ISREG(before_path.st_mode):
        raise OSError(f"source is not a regular file: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as reader, destination.open("xb") as writer:
        before = os.fstat(reader.fileno())
        if _identity(before_path) != _identity(before):
            raise OSError(f"source changed before copy: {source}")
        while chunk := reader.read(_READ_SIZE):
            writer.write(chunk)
            digest.update(chunk)
        writer.flush()
        os.fsync(writer.fileno())
        after = os.fstat(reader.fileno())
    current = source.stat()
    if _identity(before) != _identity(after) or _identity(after) != _identity(current):
        destination.unlink(missing_ok=True)
        raise OSError(f"source changed while copying: {source}")
    return digest.hexdigest()


def _read_budget(path: Path) -> bytes:
    if path.suffix.lower() != ".json":
        raise PortFailure("invalid_preview", "Preview budget must be a JSON file")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("budget is not a regular file")
        if info.st_size > _BUDGET_LIMIT:
            raise ValueError(f"budget exceeds the {_BUDGET_LIMIT}-byte limit")
        with path.open("rb") as reader:
            content = reader.read(_BUDGET_LIMIT + 1)
        if len(content) > _BUDGET_LIMIT:
            raise ValueError(f"budget exceeds the {_BUDGET_LIMIT}-byte limit")
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("budget must contain a JSON object")
        return content
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PortFailure(
            "invalid_preview", f"Invalid preview budget {path}: {exc}"
        ) from exc


def _camera_json(camera: PreviewCamera) -> dict[str, object]:
    return {
        "name": camera.name,
        "position": list(camera.position),
        "target": list(camera.target),
        "size": camera.size,
        "near": camera.near,
        "far": camera.far,
        "up": list(camera.up),
    }


class PreviewFiles:
    """Create and remove only the temporary project owned by one preview."""

    def read_baseline(self, path: Path) -> PreviewResult:
        return read_preview_baseline(path)

    def prepare(
        self, source: Path, output_dir: Path, budget: Path | None
    ) -> tuple[Path, str]:
        project: Path | None = None
        output_created = False
        try:
            if source.suffix.lower() != ".glb":
                raise PortFailure(
                    "invalid_preview", "Preview source must be a GLB file"
                )
            references = validate_format(source)
            if references:
                raise PortFailure(
                    "invalid_preview",
                    "Preview requires a self-contained GLB without external references",
                )
            budget_content = _read_budget(budget) if budget is not None else None
            try:
                output_dir.mkdir()
                output_created = True
            except FileExistsError as exc:
                raise PortFailure(
                    "destination_conflict",
                    f"Preview output directory already exists: {output_dir}",
                ) from exc
            project = Path(tempfile.mkdtemp(prefix="gda-preview-"))
            (project / _OWNERSHIP_MARKER).write_text("gda-assets preview project\n")
            shutil.copytree(_FIXTURE, project, dirs_exist_ok=True)
            digest = _copy_with_sha256(source, project / "model.glb")
            if budget_content is not None:
                (project / "budget.json").write_bytes(budget_content)
            return project, digest
        except PortFailure:
            self._clean_failed_prepare(project, output_dir, output_created)
            raise
        except (OSError, shutil.Error) as exc:
            self._clean_failed_prepare(project, output_dir, output_created)
            raise PortFailure(
                "preview_prepare_failed", f"Could not prepare preview files: {exc}"
            ) from exc

    def configure(
        self,
        project: Path,
        settings: PreviewSettings,
        cameras: tuple[PreviewCamera, ...],
    ) -> None:
        validate_settings(
            PreviewSettings(
                width=settings.width,
                height=settings.height,
                padding=settings.padding,
                cameras=cameras,
            )
        )
        self._require_owned(project)
        configuration = {
            "settings": {
                "width": settings.width,
                "height": settings.height,
                "padding": settings.padding,
            },
            "views": [_camera_json(camera) for camera in cameras],
        }
        (project / "preview.json").write_text(
            json.dumps(configuration, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (project / "project.godot").write_text(
            "config_version=5\n\n"
            "[application]\n"
            'config/name="gda-assets-model-preview"\n'
            'run/main_scene="res://preview.tscn"\n\n'
            "[display]\n"
            f"window/size/viewport_width={settings.width}\n"
            f"window/size/viewport_height={settings.height}\n"
            f"window/size/window_width_override={settings.width}\n"
            f"window/size/window_height_override={settings.height}\n\n"
            "[rendering]\n"
            'renderer/rendering_method="gl_compatibility"\n'
            'renderer/rendering_method.mobile="gl_compatibility"\n\n'
            "[debug]\n"
            "file_logging/enable_file_logging=false\n",
            encoding="utf-8",
        )

    def remove_project(self, project: Path) -> None:
        self._require_owned(project)
        shutil.rmtree(project)

    @staticmethod
    def _clean_failed_prepare(
        project: Path | None, output_dir: Path, output_created: bool
    ) -> None:
        # Both paths were created in this call and have not escaped to the caller.
        # Do not use the public ownership gate: marker creation itself may be the
        # operation that failed.
        if project is not None:
            shutil.rmtree(project, ignore_errors=True)
        if output_created:
            try:
                output_dir.rmdir()
            except OSError:
                # A concurrently-created entry is not ours to remove.
                pass

    @staticmethod
    def _require_owned(project: Path) -> None:
        marker = project / _OWNERSHIP_MARKER
        try:
            if marker.read_text(encoding="utf-8") != "gda-assets preview project\n":
                raise ValueError
        except (OSError, ValueError) as exc:
            raise PortFailure(
                "invalid_preview",
                f"Refusing to modify an unowned preview project: {project}",
            ) from exc
