"""Saved-source Blender adapter; native Blender types stay in the worker."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gda_assets.application.ports import ProducedFiles, ProductionRequest, PortFailure
from gda_assets.domain.recipe import AssetFile, target_relative


class BlenderExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    animations: bool = Field(default=False, strict=True)
    materials: Literal["EXPORT", "NONE"] = "EXPORT"
    apply_modifiers: bool = Field(default=True, strict=True)


class BlenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1)
    scene: str = Field(min_length=1)
    root: str = Field(min_length=1)
    uniform_scale: float = Field(default=1, strict=True, gt=0, allow_inf_nan=False)
    export: BlenderExportOptions = Field(default_factory=BlenderExportOptions)
    executable: str | None = None
    timeout_seconds: float = Field(default=120, gt=0, le=3600, allow_inf_nan=False)


def _tail(stream) -> str:
    stream.seek(0, os.SEEK_END)
    stream.seek(max(0, stream.tell() - 16384))
    return stream.read().decode("utf-8", errors="replace")


class BlenderSavedProducer:
    def produce(
        self, request: ProductionRequest, source_root: Path | None, workspace: Path
    ) -> ProducedFiles:
        try:
            options = BlenderOptions.model_validate(request.options)
            if len(request.outputs) != 1 or request.outputs[0].role != "model":
                raise ValueError("Blender production needs exactly one model output")
            target = request.outputs[0].target
            if target_relative(target).suffix.lower() != ".glb":
                raise ValueError("Blender production requires a GLB destination")
        except ValidationError as exc:
            message = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise PortFailure("invalid_production", message) from exc
        except ValueError as exc:
            raise PortFailure("invalid_production", str(exc)) from exc
        source = Path(options.source)
        if not source.is_absolute():
            if source_root is None:
                raise PortFailure(
                    "invalid_production",
                    "source_root is required for a relative Blender source",
                )
            source = source_root / source
        source = source.resolve()
        if source.suffix.lower() != ".blend" or not source.is_file():
            raise PortFailure(
                "invalid_production", f"Saved .blend source not found: {source}"
            )
        binary = (
            options.executable
            or os.environ.get("GDA_BLENDER")
            or shutil.which("blender")
        )
        if not binary:
            raise PortFailure(
                "producer_unavailable",
                "Set Blender executable, GDA_BLENDER, or put blender on PATH",
            )
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").digest()
        output = workspace / "produced.glb"
        result_path = workspace / "production-result.json"
        request_path = workspace / "production-request.json"
        request_path.write_text(
            json.dumps(
                {
                    **options.model_dump(),
                    "output": str(output),
                    "result": str(result_path),
                }
            )
        )
        worker = Path(__file__).with_name("_blender_worker.py")
        argv = [
            binary,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            str(source),
            "--python-exit-code",
            "1",
            "--python",
            str(worker),
            "--",
            str(request_path),
        ]
        with TemporaryFile() as stdout, TemporaryFile() as stderr:
            try:
                process = subprocess.run(
                    argv, stdout=stdout, stderr=stderr, timeout=options.timeout_seconds
                )
            except subprocess.TimeoutExpired as exc:
                raise PortFailure(
                    "producer_timeout",
                    f"Blender exceeded {options.timeout_seconds:g}s",
                    cause={"stdout_tail": _tail(stdout), "stderr_tail": _tail(stderr)},
                ) from exc
            except OSError as exc:
                raise PortFailure(
                    "producer_unavailable", f"Cannot start Blender: {exc}"
                ) from exc
            diagnostics = {
                "stdout_tail": _tail(stdout),
                "stderr_tail": _tail(stderr),
                "exit_code": process.returncode,
            }
        if not result_path.is_file() or result_path.stat().st_size > 131072:
            raise PortFailure(
                "production_failed",
                "Blender did not return a bounded production result",
                cause=diagnostics,
            )
        try:
            result = json.loads(result_path.read_text())
        except (ValueError, OSError) as exc:
            raise PortFailure(
                "production_failed",
                "Cannot read Blender production result",
                cause=diagnostics,
            ) from exc
        if not isinstance(result, dict):
            raise PortFailure(
                "production_failed",
                "Invalid Blender production result",
                cause=diagnostics,
            )
        if process.returncode != 0 or result.get("failure"):
            raise PortFailure(
                "production_failed",
                f"Blender {result.get('stage', 'execution')}: {result.get('failure', 'process failed')}",
                cause={**diagnostics, **result},
            )
        if result.get("completed") != ["inspect", "prepare", "export"]:
            raise PortFailure(
                "production_failed",
                "Incomplete Blender production result",
                cause=diagnostics,
            )
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").digest() != digest:
                raise PortFailure(
                    "source_changed",
                    "Saved Blender source changed during production",
                    cause=result,
                )
        if not output.is_file() or output.is_symlink():
            raise PortFailure(
                "production_failed", "Blender export output is missing", cause=result
            )
        return ProducedFiles(
            files=(AssetFile(str(output), target),),
            source_mode="blender_saved",
            observations={
                **result,
                "source": str(source),
                "source_preserved": True,
                **diagnostics,
            },
        )
