"""Model Source checking and exact-authority self-admission."""

from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import (
    CheckedModel,
    admit_resolved_model,
    check_model_source,
    lower_checked_model,
)


def check_source(path: str) -> CheckedModel | Schema2RefusalReport:
    """Check one Model Source Package against admitted authority."""
    return check_model_source(path)


def verify_resolved_model_admission(checked: CheckedModel) -> None:
    """Require the checked source's lowered Model to admit under the same authority."""
    artifacts = lower_checked_model(checked)
    admission = admit_resolved_model(
        {
            name: artifacts[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        },
        authority_context=checked.authority_context,
    )
    if not admission.admitted:
        raise RuntimeError("checked Resolved Model failed exact-authority admission")
