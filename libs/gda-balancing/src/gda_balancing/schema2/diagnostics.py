"""Stage-aware Schema 2.0 diagnostics and refusal envelopes."""

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.schema2.bootstrap import BootstrapAdmission

RefusalStage = Literal[
    "ingress",
    "parse",
    "static",
    "resolution",
    "runtime",
    "evaluation",
    "migration",
    "approval",
]


class ArtifactLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["artifact"] = "artifact"
    content_identity: str
    pointer: str


class Schema2Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    primary: ArtifactLocation
    related: tuple[ArtifactLocation, ...] = ()


class Schema2RefusalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: RefusalStage
    diagnostics: tuple[Schema2Diagnostic, ...] = Field(min_length=1)
    truncated: bool


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
            item.primary.pointer,
            item.code,
            item.primary.content_identity,
        )
    )
    return Schema2RefusalReport(
        stage=cast(RefusalStage, stage),
        diagnostics=tuple(diagnostics),
        truncated=admission.truncated,
    )


def refusal_envelope(report: Schema2RefusalReport) -> dict[str, object]:
    """Build the closed Schema 2.0 refusal Error envelope."""
    return {
        "error": {
            "category": "refusal",
            "stage": report.stage,
            "diagnostics": [
                item.model_dump(mode="json") for item in report.diagnostics
            ],
            "truncated": report.truncated,
        }
    }
