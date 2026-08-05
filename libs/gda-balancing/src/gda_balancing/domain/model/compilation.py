"""Resolution and lowering of an already checked Model Source Package."""

from gda_balancing.domain.canonical import JsonValue
from gda_balancing.domain.model.semantics import CheckedModel, lower_checked_model


def compile_checked_model(
    checked: CheckedModel,
) -> dict[str, dict[str, JsonValue]]:
    """Lower one checked source into its semantic and provenance artifacts."""
    return lower_checked_model(checked)
