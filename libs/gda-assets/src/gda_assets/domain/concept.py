"""Concept briefs, selected references, and bounded authoring observations."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from gda_assets.domain.prompt import (
    JsonScalar,
    PromptOptionKey,
    PromptOutput,
    PromptPreparation,
)


ConceptUse: TypeAlias = Literal["model", "sprite"]
ConceptConsumer: TypeAlias = Literal[
    "blender-reference-blockout", "sprite-sheet-reference"
]


@dataclass(frozen=True)
class ConceptBrief:
    use: ConceptUse
    subject: str
    style: str
    views: tuple[str, ...] = ()
    poses: tuple[str, ...] = ()
    instructions: str = ""


@dataclass(frozen=True)
class ConceptBriefSnapshot:
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ConceptPrepareRequest:
    brief: Path
    record: Path
    producer: str | None = None
    requested_options: dict[PromptOptionKey, JsonScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class ConceptPreparation:
    brief: ConceptBrief
    brief_snapshot: ConceptBriefSnapshot
    prompt: PromptPreparation


@dataclass(frozen=True)
class ConceptCandidate:
    record: Path
    output: str


@dataclass(frozen=True)
class ValidatedConceptCandidate:
    candidate: ConceptCandidate
    output: PromptOutput
    resolved_prompt_sha256: str


@dataclass(frozen=True)
class ConceptSelectRequest:
    brief_record: Path
    handoff: Path
    candidates: tuple[ConceptCandidate, ...]


@dataclass(frozen=True)
class SelectedConcept:
    index: int
    prompt_record: str
    output: str
    resolved_prompt_sha256: str
    path: Path
    sha256: str
    size_bytes: int
    width: int
    height: int
    generation_completed_by_caller: Literal[True]


@dataclass(frozen=True)
class ConceptSelection:
    schema: Literal[1]
    handoff: Path
    brief: ConceptBrief
    brief_snapshot: ConceptBriefSnapshot
    selected: tuple[SelectedConcept, ...]
    authoring_status: Literal["ready"] = "ready"
    limitations: tuple[str, ...] = (
        "Selected image copies are self-contained; prepared and submitted prompt fields remain in originating prompt records and become unavailable if those records are deleted.",
        "Caller-declared generation completion is not verified provider execution.",
    )


@dataclass(frozen=True)
class SpriteSheetLayout:
    width: int
    height: int
    cell_width: int
    cell_height: int
    frames: int


@dataclass(frozen=True)
class ConceptAuthorRequest:
    handoff: Path
    consumer: ConceptConsumer
    output: Path
    reference_index: int = 0
    blender_executable: Path | None = None
    sprite_layout: SpriteSheetLayout | None = None


@dataclass(frozen=True)
class ConsumedConcept:
    index: int
    path: Path
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class AuthoringArtifact:
    role: Literal["blend_source", "godot_glb", "sprite_sheet"]
    path: Path
    sha256: str
    size_bytes: int
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class SpriteSheetObservation:
    width: int
    height: int
    cell_width: int
    cell_height: int
    frames: int


@dataclass(frozen=True)
class ConceptAuthoringResult:
    consumer: ConceptConsumer
    handoff: Path
    consumed: ConsumedConcept
    reference_loaded: Literal[True]
    influence: Literal[
        "material_color_from_reference_pixels", "frames_from_reference_pixels"
    ]
    artifacts: tuple[AuthoringArtifact, ...]
    material_color: tuple[float, float, float, float] | None = None
    sprite_sheet: SpriteSheetObservation | None = None
    limitations: tuple[str, ...] = ()


def validate_brief(brief: ConceptBrief) -> None:
    if brief.use not in ("model", "sprite"):
        raise ValueError("Concept use must be model or sprite")
    for label, value, limit in (
        ("subject", brief.subject, 4096),
        ("style", brief.style, 4096),
        ("instructions", brief.instructions, 16384),
    ):
        if (
            not isinstance(value, str)
            or len(value) > limit
            or (label != "instructions" and not value.strip())
        ):
            raise ValueError(f"Concept {label} is invalid")
    if not brief.views and not brief.poses:
        raise ValueError("Concept brief requires at least one view or pose")
    for label, values in (("views", brief.views), ("poses", brief.poses)):
        if (
            len(values) > 8
            or len(set(values)) != len(values)
            or any(not value.strip() or len(value) > 128 for value in values)
        ):
            raise ValueError(f"Concept {label} must be unique bounded strings")


def concept_prompt(brief: ConceptBrief) -> str:
    validate_brief(brief)
    lines = [
        f"Intended use: {brief.use}",
        f"Subject: {brief.subject}",
        f"Style: {brief.style}",
    ]
    if brief.views:
        lines.append(f"Requested views: {', '.join(brief.views)}")
    if brief.poses:
        lines.append(f"Requested poses: {', '.join(brief.poses)}")
    if brief.instructions:
        lines.append(f"Project instructions: {brief.instructions}")
    return "\n".join(lines)


def validate_layout(layout: SpriteSheetLayout) -> None:
    values = (layout.width, layout.height, layout.cell_width, layout.cell_height)
    if any(type(value) is not int or not 1 <= value <= 2048 for value in values):
        raise ValueError("Sprite sheet dimensions must be integers in 1..2048")
    if layout.width % layout.cell_width or layout.height % layout.cell_height:
        raise ValueError("Sprite sheet cell dimensions must divide the sheet")
    cells = (layout.width // layout.cell_width) * (layout.height // layout.cell_height)
    if type(layout.frames) is not int or not 1 <= layout.frames <= min(64, cells):
        raise ValueError("Sprite sheet frame count exceeds its bounded cell grid")
