"""Check a Standard Schema Model Source Package."""

from dataclasses import dataclass

from gda_balancing.domain.model.checking import (
    check_source,
    verify_resolved_model_admission,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class ModelCheckReport:
    """Successful Model Source checking and its authority identities."""

    kernel_identity: str
    language_bundle_identity: str


def check_model(source: str) -> ModelCheckReport | Schema2RefusalReport:
    """Check and self-admit one Model Source Package."""
    checked = check_source(source)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    verify_resolved_model_admission(checked)
    return ModelCheckReport(
        kernel_identity=checked.kernel["content_identity"],
        language_bundle_identity=checked.language_bundle["content_identity"],
    )
