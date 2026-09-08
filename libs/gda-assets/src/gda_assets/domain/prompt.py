"""Project-owned prompt records and their explicit external-generation handoff."""

from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Literal, TypeAlias, get_args
import math


JsonScalar: TypeAlias = str | int | float | bool | None
PromptOptionKey: TypeAlias = Literal[
    "aspect_ratio",
    "background",
    "model",
    "output_format",
    "quality",
    "seed",
    "size",
    "style",
]
PromptDeclarationKey: TypeAlias = Literal[
    "generation_completed", "model", "provider", "request_id", "tool"
]
REQUESTED_OPTION_KEYS = frozenset(get_args(PromptOptionKey))
DECLARATION_KEYS = frozenset(get_args(PromptDeclarationKey))
_TEXT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PromptPrepareRequest:
    record: Path
    text: str | None = None
    template: Path | None = None
    style: Path | None = None
    variables: dict[str, str] = field(default_factory=dict)
    references: tuple[Path, ...] = ()
    producer: str | None = None
    requested_options: dict[str, JsonScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptRevisionRequest:
    source_record: Path
    record: Path
    text: str | None = None
    template: Path | None = None
    style: Path | None = None
    remove_style: bool = False
    variables: dict[str, str] | None = None
    references: tuple[Path, ...] | None = None
    producer: str | None = None
    requested_options: dict[str, JsonScalar] | None = None


@dataclass(frozen=True)
class PromptOutputRequest:
    record: Path
    output: Path
    name: str
    submitted_prompt: str | None = None
    caller_declarations: dict[str, JsonScalar] = field(default_factory=dict)
    reported_provider: str | None = None
    reported_model: str | None = None
    reported_options: dict[str, JsonScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptFile:
    declared_path: str
    path: Path
    sha256: str
    size_bytes: int
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class PromptOutput:
    name: str
    file: PromptFile
    submitted_prompt: str | None
    caller_declarations: dict[str, JsonScalar]
    reported_provider: str | None
    reported_model: str | None
    reported_options: dict[str, JsonScalar]


@dataclass(frozen=True)
class PromptRecord:
    schema: Literal[1]
    record: Path
    mode: Literal["plain", "template"]
    authored_text: str | None
    template: PromptFile | None
    style: PromptFile | None
    variables: dict[str, str]
    resolved_prompt: str
    resolved_path: Path
    resolved_sha256: str
    references: tuple[PromptFile, ...]
    producer: str | None
    requested_options: dict[str, JsonScalar]
    generation_status: Literal["unknown"] = "unknown"
    outputs: tuple[PromptOutput, ...] = ()
    revised_from: str | None = None


@dataclass(frozen=True)
class PromptHandoff:
    action: Literal["external_generation_required"]
    generation_status: Literal["unknown"]
    record: Path
    prompt: str
    prompt_path: Path
    references: tuple[Path, ...]
    producer: str | None
    requested_options: dict[str, JsonScalar]
    registration_operation: Literal["prompt-register-output"] = "prompt-register-output"


@dataclass(frozen=True)
class PromptPreparation:
    record: PromptRecord
    handoff: PromptHandoff


@dataclass(frozen=True)
class PromptRevision:
    preparation: PromptPreparation
    changed_fields: tuple[str, ...]


def validate_options(
    values: dict[str, JsonScalar], *, declarations: bool = False
) -> None:
    allowed = DECLARATION_KEYS if declarations else REQUESTED_OPTION_KEYS
    if len(values) > len(allowed) or any(key not in allowed for key in values):
        raise ValueError("Prompt options contain unsupported keys")
    for key, value in values.items():
        if isinstance(value, str) and len(value) > 1024:
            raise ValueError(f"Prompt option {key} is too long")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Prompt option {key} must be finite")
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError(f"Prompt option {key} must be a JSON scalar")


def validate_prepare_request(request: PromptPrepareRequest) -> None:
    if len(request.references) > 16:
        raise ValueError("Select at most 16 prompt references")
    if request.producer is not None and not 0 < len(request.producer) <= 256:
        raise ValueError("Prompt producer must be a nonempty bounded string")
    if len(request.variables) > 64 or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or len(key) > 128
        or len(value) > 4096
        for key, value in request.variables.items()
    ):
        raise ValueError("Prompt variables must contain at most 64 bounded strings")
    validate_options(request.requested_options)


def validate_output_request(request: PromptOutputRequest) -> None:
    validate_options(request.caller_declarations, declarations=True)
    validate_options(request.reported_options)
    completed = request.caller_declarations.get("generation_completed")
    if completed is not None and type(completed) is not bool:
        raise ValueError("Caller-declared generation_completed must be boolean")
    for label, value in (
        ("submitted prompt", request.submitted_prompt),
        ("reported provider", request.reported_provider),
        ("reported model", request.reported_model),
    ):
        if value is not None and (
            not isinstance(value, str) or len(value.encode()) > _TEXT_BYTES
        ):
            raise ValueError(f"Prompt {label} must be a bounded string")


def resolve_prompt(
    *,
    text: str | None,
    template_text: str | None,
    style_text: str | None,
    variables: dict[str, str],
) -> tuple[Literal["plain", "template"], str]:
    if (text is None) == (template_text is None):
        raise ValueError("Provide exactly one of prompt text or template")
    if text is not None:
        if variables:
            raise ValueError("Plain prompt text does not accept template variables")
        main = text
        mode: Literal["plain", "template"] = "plain"
    else:
        template = Template(template_text or "")
        if not template.is_valid():
            raise ValueError("Prompt template syntax is invalid")
        identifiers = set(template.get_identifiers())
        if identifiers != set(variables):
            raise ValueError(
                "Prompt template variables must exactly match its placeholders"
            )
        main = template.substitute(variables)
        mode = "template"
    if not main.strip():
        raise ValueError("Resolved prompt must not be empty")
    resolved = f"{style_text.rstrip()}\n\n{main}" if style_text else main
    if len(resolved.encode()) > _TEXT_BYTES:
        raise ValueError("Resolved prompt exceeds its size limit")
    return mode, resolved


def handoff(record: PromptRecord) -> PromptPreparation:
    return PromptPreparation(
        record,
        PromptHandoff(
            "external_generation_required",
            "unknown",
            record.record,
            record.resolved_prompt,
            record.resolved_path,
            tuple(item.path for item in record.references),
            record.producer,
            record.requested_options,
        ),
    )
