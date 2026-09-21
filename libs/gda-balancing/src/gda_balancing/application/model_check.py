"""Check a Standard Schema Model Source Package."""

from dataclasses import dataclass

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.model import check_model_source, verify_checked_model
from gda_balancing.domain.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class ModelCheckReport:
    """Successful Model Source checking and its authority identities."""

    kernel_identity: str
    language_bundle_identity: str


def check_model(
    source: str,
    *,
    authority_context: AdmittedAuthorityContext | None = None,
) -> ModelCheckReport | Schema2RefusalReport:
    """Check and self-admit one Model Source Package."""
    checked = check_model_source(source, authority_context=authority_context)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    verify_checked_model(checked)
    return ModelCheckReport(
        kernel_identity=checked.kernel["content_identity"],
        language_bundle_identity=checked.language_bundle["content_identity"],
    )
