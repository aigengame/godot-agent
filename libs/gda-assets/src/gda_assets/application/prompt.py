"""Prepare, inspect, revise, and register project-owned prompt records."""

from pathlib import Path

from gda_assets.application.ports import PortFailure
from gda_assets.application.prompt_ports import PromptFilesPort
from gda_assets.domain.prompt import (
    PromptOutputRequest,
    PromptPreparation,
    PromptPrepareRequest,
    PromptRecord,
    PromptRevision,
    PromptRevisionRequest,
    handoff,
    resolve_prompt,
    validate_output_request,
    validate_prepare_request,
)


def _prepare(
    request: PromptPrepareRequest,
    files: PromptFilesPort,
    *,
    revised_from: str | None = None,
) -> PromptPreparation:
    try:
        validate_prepare_request(request)
        template_text = files.read_text(request.template) if request.template else None
        style_text = files.read_text(request.style) if request.style else None
        mode, resolved = resolve_prompt(
            text=request.text,
            template_text=template_text,
            style_text=style_text,
            variables=request.variables,
        )
        record = files.create(
            request.record,
            mode=mode,
            authored_text=request.text,
            template=request.template,
            template_content=template_text,
            style=request.style,
            style_content=style_text,
            variables=dict(request.variables),
            resolved_prompt=resolved,
            references=request.references,
            producer=request.producer,
            requested_options=dict(request.requested_options),
            revised_from=revised_from,
        )
        return handoff(record)
    except ValueError as exc:
        raise PortFailure("invalid_prompt", str(exc)) from exc


def prepare_prompt(
    request: PromptPrepareRequest, *, files: PromptFilesPort
) -> PromptPreparation:
    return _prepare(request, files)


def inspect_prompt(record: Path, *, files: PromptFilesPort) -> PromptPreparation:
    return handoff(files.read(record))


def revise_prompt(
    request: PromptRevisionRequest, *, files: PromptFilesPort
) -> PromptRevision:
    saved = files.read(request.source_record)
    changing_mode = request.text is not None or request.template is not None
    text = request.text if changing_mode else saved.authored_text
    template = (
        request.template
        if changing_mode
        else (saved.template.path if saved.template else None)
    )
    style = (
        None
        if request.remove_style
        else request.style or (saved.style.path if saved.style else None)
    )
    prepare_request = PromptPrepareRequest(
        record=request.record,
        text=text,
        template=template,
        style=style,
        variables=request.variables
        if request.variables is not None
        else saved.variables,
        references=(
            request.references
            if request.references is not None
            else tuple(item.path for item in saved.references)
        ),
        producer=request.producer if request.producer is not None else saved.producer,
        requested_options=(
            request.requested_options
            if request.requested_options is not None
            else saved.requested_options
        ),
    )
    prepared = _prepare(prepare_request, files, revised_from=str(saved.record))
    changed = []
    pairs = {
        "mode": (saved.mode, prepared.record.mode),
        "authored_text": (saved.authored_text, prepared.record.authored_text),
        "template": (
            saved.template.sha256 if saved.template else None,
            prepared.record.template.sha256 if prepared.record.template else None,
        ),
        "style": (
            saved.style.sha256 if saved.style else None,
            prepared.record.style.sha256 if prepared.record.style else None,
        ),
        "variables": (saved.variables, prepared.record.variables),
        "resolved_prompt": (saved.resolved_prompt, prepared.record.resolved_prompt),
        "references": (
            tuple(item.sha256 for item in saved.references),
            tuple(item.sha256 for item in prepared.record.references),
        ),
        "producer": (saved.producer, prepared.record.producer),
        "requested_options": (
            saved.requested_options,
            prepared.record.requested_options,
        ),
    }
    for name, (before, after) in pairs.items():
        if before != after:
            changed.append(name)
    return PromptRevision(prepared, tuple(changed))


def register_prompt_output(
    request: PromptOutputRequest, *, files: PromptFilesPort
) -> PromptRecord:
    try:
        validate_output_request(request)
    except ValueError as exc:
        raise PortFailure("invalid_prompt", str(exc)) from exc
    return files.add_output(files.read(request.record), request)
