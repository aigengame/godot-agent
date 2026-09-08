"""Bounded consumers proving selected concept bytes reach authoring tools."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryFile
from typing import Literal

from gda_assets.adapters.files import validate_format
from gda_assets.application.ports import PortFailure
from gda_assets.domain.concept import (
    AuthoringArtifact,
    ConceptAuthoringResult,
    ConceptAuthorRequest,
    ConceptSelection,
    ConsumedConcept,
    SpriteSheetObservation,
)


def _digest(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest(), path.stat().st_size


def _selected(request: ConceptAuthorRequest, selection: ConceptSelection):
    if request.reference_index < 0 or request.reference_index >= len(
        selection.selected
    ):
        raise PortFailure(
            "invalid_concept", "Selected concept reference index is out of range"
        )
    selected = selection.selected[request.reference_index]
    path = selected.path.resolve()
    try:
        validate_format(path)
        digest, size = _digest(path)
    except (OSError, PortFailure) as exc:
        raise PortFailure(
            "invalid_concept_handoff", f"Cannot read selected concept: {path}"
        ) from exc
    if digest != selected.sha256 or size != selected.size_bytes:
        raise PortFailure(
            "invalid_concept_handoff", "Selected concept bytes changed after handoff"
        )
    return selected, path, digest


def _artifact(
    role: Literal["blend_source", "godot_glb", "sprite_sheet"],
    path: Path,
    *,
    width=None,
    height=None,
) -> AuthoringArtifact:
    digest, size = _digest(path)
    return AuthoringArtifact(role, path, digest, size, width, height)


def _tail(stream) -> str:
    stream.seek(0, os.SEEK_END)
    stream.seek(max(0, stream.tell() - 16384))
    return stream.read().decode("utf-8", errors="replace")


def _create_output(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise PortFailure(
            "destination_conflict", f"Authoring output already exists: {path}"
        ) from exc
    except OSError as exc:
        raise PortFailure(
            "concept_author_failed", f"Cannot create authoring output: {path}"
        ) from exc


class BlenderReferenceBlockoutAuthor:
    """Load one selected PNG as a Blender image reference before blockout creation."""

    def author(
        self, request: ConceptAuthorRequest, selection: ConceptSelection
    ) -> ConceptAuthoringResult:
        if (
            request.consumer != "blender-reference-blockout"
            or request.sprite_layout is not None
        ):
            raise PortFailure(
                "invalid_concept", "Blender blockout does not accept a sprite layout"
            )
        selected, reference, digest = _selected(request, selection)
        configured = (
            request.blender_executable
            or os.environ.get("GDA_BLENDER")
            or shutil.which("blender")
        )
        binary = None if configured is None else Path(configured).expanduser()
        if binary is not None and not binary.is_absolute():
            found = shutil.which(str(binary))
            binary = None if found is None else Path(found)
        if binary is None or not binary.is_file() or not os.access(binary, os.X_OK):
            raise PortFailure(
                "unsupported_concept_consumer", "Blender executable is unavailable"
            )
        _create_output(request.output)
        result_path = request.output / "blender-result.json"
        request_path = request.output / "blender-request.json"
        try:
            request_path.write_text(
                json.dumps(
                    {
                        "reference": str(reference),
                        "output": str(request.output),
                        "result": str(result_path),
                    }
                )
            )
        except OSError as exc:
            raise PortFailure(
                "concept_author_failed", "Cannot write Blender authoring request"
            ) from exc
        worker = Path(__file__).with_name("_concept_blender_worker.py")
        argv = [
            str(binary),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
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
                    argv, stdout=stdout, stderr=stderr, timeout=180
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PortFailure(
                    "concept_author_failed",
                    f"Blender reference authoring could not complete: {exc}",
                ) from exc
            diagnostics = {
                "exit_code": process.returncode,
                "stdout_tail": _tail(stdout),
                "stderr_tail": _tail(stderr),
            }
        if not result_path.is_file() or result_path.stat().st_size > 131072:
            raise PortFailure(
                "concept_author_failed",
                "Blender returned no bounded authoring result",
                cause=diagnostics,
            )
        try:
            native = json.loads(result_path.read_text())
        except (OSError, ValueError) as exc:
            raise PortFailure(
                "concept_author_failed",
                "Blender returned no valid authoring result",
                cause=diagnostics,
            ) from exc
        if not isinstance(native, dict):
            raise PortFailure(
                "concept_author_failed",
                "Blender returned no valid authoring result",
                cause=diagnostics,
            )
        expected_steps = [
            "read_reference",
            "decode_reference",
            "create_reference",
            "create_blockout",
            "save_blend",
            "export_glb",
        ]
        if (
            process.returncode != 0
            or native.get("failure")
            or native.get("completed") != expected_steps
        ):
            raise PortFailure(
                "concept_author_failed",
                f"Blender {native.get('stage', 'execution')}: {native.get('failure', 'incomplete result')}",
                cause={**diagnostics, **native},
            )
        if (
            native.get("reference_sha256") != digest
            or native.get("reference_width") != selected.width
            or native.get("reference_height") != selected.height
            or native.get("reference_loaded") is not True
        ):
            raise PortFailure(
                "concept_author_failed",
                "Blender did not load the selected concept bytes",
                cause=native,
            )
        blend, glb = (
            request.output / "reference-blockout.blend",
            request.output / "reference-blockout.glb",
        )
        if not blend.is_file() or not glb.is_file():
            raise PortFailure(
                "concept_author_failed",
                "Blender authoring artifacts are missing",
                cause=native,
            )
        color_values = native.get("material_color")
        if not isinstance(color_values, list) or len(color_values) != 4:
            raise PortFailure(
                "concept_author_failed",
                "Blender returned no valid material color",
                cause=native,
            )
        color = (
            float(color_values[0]),
            float(color_values[1]),
            float(color_values[2]),
            float(color_values[3]),
        )
        consumed = ConsumedConcept(
            request.reference_index, reference, digest, selected.width, selected.height
        )
        return ConceptAuthoringResult(
            request.consumer,
            selection.handoff,
            consumed,
            True,
            "material_color_from_reference_pixels",
            (_artifact("blend_source", blend), _artifact("godot_glb", glb)),
            color,
            None,
            (
                "Creates one static cube blockout; it does not infer shape or establish artistic similarity.",
            ),
        )


class SpriteSheetReferenceAuthor:
    """Decode one selected PNG before deriving a bounded sprite sheet from its pixels."""

    def author(
        self, request: ConceptAuthorRequest, selection: ConceptSelection
    ) -> ConceptAuthoringResult:
        if (
            request.consumer != "sprite-sheet-reference"
            or request.sprite_layout is None
        ):
            raise PortFailure(
                "invalid_concept", "Sprite authoring requires a sprite sheet layout"
            )
        selected, reference, digest = _selected(request, selection)
        layout = request.sprite_layout
        from PIL import Image, ImageEnhance, ImageOps  # pyright: ignore[reportMissingImports]

        _create_output(request.output)
        try:
            with Image.open(reference) as opened:
                opened.load()
                decoded = opened.convert("RGBA")
            if decoded.size != (selected.width, selected.height):
                raise ValueError("selected concept dimensions differ from its handoff")
            frame = decoded.resize(
                (layout.cell_width, layout.cell_height), Image.Resampling.NEAREST
            )
            transforms = (
                lambda value: value,
                ImageOps.mirror,
                ImageOps.flip,
                lambda value: ImageEnhance.Brightness(value).enhance(0.65),
            )
            sheet = Image.new("RGBA", (layout.width, layout.height))
            columns = layout.width // layout.cell_width
            for index in range(layout.frames):
                produced = transforms[index % len(transforms)](frame)
                sheet.paste(
                    produced,
                    (
                        (index % columns) * layout.cell_width,
                        (index // columns) * layout.cell_height,
                    ),
                )
            output = request.output / "reference-sprite-sheet.png"
            sheet.save(output, format="PNG")
            with Image.open(output) as verified:
                verified.load()
                if verified.size != (layout.width, layout.height):
                    raise ValueError(
                        "written sprite sheet dimensions differ from its layout"
                    )
        except (OSError, ValueError) as exc:
            raise PortFailure(
                "concept_author_failed", f"Sprite reference authoring failed: {exc}"
            ) from exc
        consumed = ConsumedConcept(
            request.reference_index, reference, digest, selected.width, selected.height
        )
        observation = SpriteSheetObservation(
            layout.width,
            layout.height,
            layout.cell_width,
            layout.cell_height,
            layout.frames,
        )
        return ConceptAuthoringResult(
            request.consumer,
            selection.handoff,
            consumed,
            True,
            "frames_from_reference_pixels",
            (
                _artifact(
                    "sprite_sheet", output, width=layout.width, height=layout.height
                ),
            ),
            None,
            observation,
            (
                "Creates bounded pixel-derived example frames; it does not establish animation quality or runtime installation.",
            ),
        )
