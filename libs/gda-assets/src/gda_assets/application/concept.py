"""Prepare, select, and author from project-owned concept references."""

from gda_assets.application.concept_ports import (
    ConceptAuthoringPort,
    ConceptFilesPort,
)
from gda_assets.application.ports import PortFailure
from gda_assets.application.prompt import inspect_prompt, prepare_prompt
from gda_assets.application.prompt_ports import PromptFilesPort
from gda_assets.domain.concept import (
    ConceptAuthoringResult,
    ConceptAuthorRequest,
    ConceptCandidate,
    ConceptPreparation,
    ConceptPrepareRequest,
    ConceptSelection,
    ConceptSelectRequest,
    ValidatedConceptCandidate,
    concept_prompt,
    validate_brief,
    validate_layout,
)
from gda_assets.domain.prompt import PromptPrepareRequest


def prepare_concept(
    request: ConceptPrepareRequest,
    *,
    files: ConceptFilesPort,
    prompts: PromptFilesPort,
) -> ConceptPreparation:
    brief = files.read_brief(request.brief)
    try:
        validate_brief(brief)
        prompt = prepare_prompt(
            PromptPrepareRequest(
                record=request.record,
                text=concept_prompt(brief),
                producer=request.producer,
                requested_options=request.requested_options,
            ),
            files=prompts,
        )
    except ValueError as exc:
        raise PortFailure("invalid_concept", str(exc)) from exc
    try:
        snapshot = files.save_brief(prompt.record.record, brief)
    except PortFailure as exc:
        raise PortFailure(
            "concept_prepare_failed",
            f"Prompt was preserved but its concept brief was not: {exc}",
            cause={"prepared_record": str(prompt.record.record)},
        ) from exc
    return ConceptPreparation(brief, snapshot, prompt)


def select_concept(
    request: ConceptSelectRequest,
    *,
    files: ConceptFilesPort,
    prompts: PromptFilesPort,
) -> ConceptSelection:
    if not 1 <= len(request.candidates) <= 8:
        raise PortFailure("invalid_concept", "Select between 1 and 8 candidates")
    pairs = tuple((str(item.record), item.output) for item in request.candidates)
    if len(set(pairs)) != len(pairs):
        raise PortFailure("invalid_concept", "Concept candidates must be unique")
    brief, snapshot = files.load_brief(request.brief_record)
    selected = []
    for candidate in request.candidates:
        try:
            record = inspect_prompt(candidate.record, files=prompts).record
        except PortFailure as exc:
            raise PortFailure(
                "invalid_concept_candidate",
                f"Invalid candidate prompt record {candidate.record}: {exc}",
            ) from exc
        output = next(
            (item for item in record.outputs if item.name == candidate.output), None
        )
        if output is None:
            raise PortFailure(
                "concept_candidate_incomplete",
                f"Candidate output is not registered: {candidate.output}",
            )
        if output.caller_declarations.get("generation_completed") is not True:
            raise PortFailure(
                "concept_candidate_incomplete",
                "Candidate requires caller-declared generation_completed=true; this is not provider proof",
            )
        if (
            output.file.width is None
            or output.file.height is None
            or output.file.width <= 0
            or output.file.height <= 0
        ):
            raise PortFailure(
                "invalid_concept_candidate",
                "Candidate PNG dimensions are unavailable",
            )
        selected.append(
            ValidatedConceptCandidate(
                ConceptCandidate(record.record, candidate.output),
                output,
                record.resolved_sha256,
            )
        )
    return files.create_handoff(request, brief, snapshot, tuple(selected))


def author_concept(
    request: ConceptAuthorRequest,
    *,
    files: ConceptFilesPort,
    author: ConceptAuthoringPort,
) -> ConceptAuthoringResult:
    selection = files.load_handoff(request.handoff)
    if not 0 <= request.reference_index < len(selection.selected):
        raise PortFailure("invalid_concept", "Selected reference index is out of range")
    expected_consumer = (
        "blender-reference-blockout"
        if selection.brief.use == "model"
        else "sprite-sheet-reference"
    )
    if request.consumer != expected_consumer:
        raise PortFailure(
            "invalid_concept",
            f"Concept use {selection.brief.use} requires {expected_consumer}",
        )
    if request.consumer == "sprite-sheet-reference":
        if request.sprite_layout is None:
            raise PortFailure(
                "invalid_concept", "Sprite authoring requires a sheet layout"
            )
        try:
            validate_layout(request.sprite_layout)
        except ValueError as exc:
            raise PortFailure("invalid_concept", str(exc)) from exc
        if request.blender_executable is not None:
            raise PortFailure(
                "invalid_concept", "Sprite authoring does not use Blender"
            )
    elif request.consumer == "blender-reference-blockout":
        if request.sprite_layout is not None:
            raise PortFailure(
                "invalid_concept", "Blender authoring does not use a sprite layout"
            )
    else:
        raise PortFailure(
            "unsupported_concept_consumer",
            f"Unsupported concept consumer: {request.consumer}",
        )
    return author.author(request, selection)
