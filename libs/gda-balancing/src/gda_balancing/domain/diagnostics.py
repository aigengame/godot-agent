"""Stage-aware Schema 2.0 diagnostic and refusal values."""

from collections.abc import Iterable
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.domain.authority.admission import (
    BOOTSTRAP_REFUSAL_CATALOG,
    BootstrapAdmission,
)
from gda_balancing.domain.authority.context import packaged_authority_context

RefusalStage = Literal[
    "ingress",
    "parse",
    "static",
    "resolution",
    "runtime",
    "evaluation",
    "approval",
]


class ArtifactLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["artifact"] = "artifact"
    content_identity: str
    pointer: str


RuntimeLocationSubject = Literal[
    "run",
    "initialization-frame",
    "formula-evaluation-site",
    "event",
    "snapshot-boundary",
]


class RuntimeLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["runtime"] = "runtime"
    subject: RuntimeLocationSubject
    identity: str


type DiagnosticLocation = Annotated[
    ArtifactLocation | RuntimeLocation,
    Field(discriminator="kind"),
]


class Schema2Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    primary: DiagnosticLocation
    related: tuple[DiagnosticLocation, ...] = ()


class Schema2RefusalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: RefusalStage
    # Descriptor-owned discriminator used to validate multiple reachable
    # variants of one refusal stage. It is intentionally not serialized into
    # the closed public Error envelope.
    variant: str | None = None
    diagnostics: tuple[Schema2Diagnostic, ...] = Field(min_length=1)
    truncated: bool
    terminal_audit: dict[str, Any] | None = None


def bound_diagnostics(
    diagnostics: Iterable[Schema2Diagnostic],
    limit: int,
) -> tuple[tuple[Schema2Diagnostic, ...], bool]:
    """Deduplicate first-wins, order, and bound one diagnostic collection."""
    unique: dict[
        tuple[str, DiagnosticLocation, tuple[DiagnosticLocation, ...]],
        Schema2Diagnostic,
    ] = {}
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.primary, diagnostic.related)
        unique.setdefault(key, diagnostic)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            _location_sort_key(item.primary),
            item.code,
            tuple(_location_sort_key(related) for related in item.related),
        ),
    )
    return tuple(ordered[:limit]), len(ordered) > limit


def _location_sort_key(location: DiagnosticLocation) -> tuple[int, str, str]:
    """Return the bADR-0015 location-kind order and canonical location key."""
    if isinstance(location, ArtifactLocation):
        return (2, location.content_identity, location.pointer)
    return (4, location.subject, location.identity)


def reason_by_id(language_bundle: dict[str, Any], reason_id: str) -> dict[str, Any]:
    """Return the one LDB-owned reason with the requested stable identifier."""
    reasons = cast(list[dict[str, Any]], language_bundle["language"]["reasons"])
    matches = [reason for reason in reasons if reason.get("id") == reason_id]
    if len(matches) != 1:
        raise ValueError(f"admitted reason is not unique: {reason_id}")
    return matches[0]


def refusal_catalog_for_stages(
    stages: frozenset[str],
    language_bundle: dict[str, Any] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Project only the LDB refusals reachable by one command family."""
    if language_bundle is None:
        language_bundle = packaged_authority_context().language_bundle
    return BOOTSTRAP_REFUSAL_CATALOG + tuple(
        (cast(str, item["code"]), cast(str, item["stage"]))
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
        if item.get("stage") in stages
    )


def refusal_catalog_for_reasons(
    reason_ids: Iterable[str],
    language_bundle: dict[str, Any] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Project one command's reachable semantic reasons through the current LDB."""
    if language_bundle is None:
        language_bundle = packaged_authority_context().language_bundle
    requested = tuple(reason_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("a command refusal catalog cannot contain duplicate reasons")
    reasons = {
        cast(str, item["id"]): item
        for item in cast(list[dict[str, Any]], language_bundle["language"]["reasons"])
    }
    diagnostics = {
        cast(str, item["code"]): cast(str, item["stage"])
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
    }
    missing = [reason_id for reason_id in requested if reason_id not in reasons]
    if missing:
        raise ValueError(
            "command refusal catalog references unknown LDB reasons: "
            + ", ".join(missing)
        )
    projected: list[tuple[str, str]] = []
    for reason_id in requested:
        reason = reasons[reason_id]
        code = cast(str, reason["diagnostic"])
        stage = cast(str, reason["stage"])
        if diagnostics.get(code) != stage:
            raise ValueError(
                f"LDB reason {reason_id} does not match its diagnostic declaration"
            )
        pair = (code, stage)
        if pair not in projected:
            projected.append(pair)
    return BOOTSTRAP_REFUSAL_CATALOG + tuple(projected)


def bootstrap_refusal(admission: BootstrapAdmission) -> Schema2RefusalReport:
    """Translate a refused bootstrap result without minting new code/stage facts."""
    if admission.admitted or not admission.diagnostics:
        raise ValueError("an admitted bootstrap result is not a refusal")
    stage = admission.diagnostics[0].stage
    diagnostics: list[Schema2Diagnostic] = []
    for item in admission.diagnostics:
        if item.stage != stage:
            continue
        is_kernel = item.subject == "kernel" or item.subject.startswith("kernel.")
        identity = (
            admission.kernel_identity
            if is_kernel
            else admission.language_bundle_identity
        )
        diagnostics.append(
            Schema2Diagnostic(
                code=item.code,
                message=f"Schema 2.0 authority admission failed at {item.subject}",
                primary=ArtifactLocation(
                    content_identity=identity or "unidentified",
                    pointer="/" + item.subject.replace(".", "/"),
                ),
            )
        )
    diagnostics.sort(
        key=lambda item: (
            _location_sort_key(item.primary),
            item.code,
            tuple(_location_sort_key(related) for related in item.related),
        )
    )
    return Schema2RefusalReport(
        stage=cast(RefusalStage, stage),
        diagnostics=tuple(diagnostics),
        truncated=admission.truncated,
    )


def ingress_refusal(code: str, subject: str, message: str) -> Schema2RefusalReport:
    """Represent a raw authority preflight/decode failure before admission."""
    return Schema2RefusalReport(
        stage="ingress",
        diagnostics=(
            Schema2Diagnostic(
                code=code,
                message=message,
                primary=ArtifactLocation(
                    content_identity="unidentified",
                    pointer="/" + subject.replace(".", "/"),
                ),
            ),
        ),
        truncated=False,
    )
