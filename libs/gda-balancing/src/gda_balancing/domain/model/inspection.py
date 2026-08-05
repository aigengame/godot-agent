"""Authenticated retrieval of published Model explanations."""

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue


def read_model_explanation(
    receipt_path: str,
    expected_descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> dict[str, JsonValue]:
    """Retrieve and authenticate one explanation from a committed Model build."""
    from gda_balancing.domain.model.semantics import read_model_explanation as read

    return read(receipt_path, expected_descriptor_identity, artifact_set)
