"""Authenticated retrieval of published Model explanations."""

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.schema2.canonical import JsonValue


class ModelInspectAdmissionError(ValueError):
    """A supplied build receipt or its committed set failed admission."""

    def __init__(self, code: str, subject: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.subject = subject
        self.message = message


def read_model_explanation(
    receipt_path: str,
    expected_descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> dict[str, JsonValue]:
    """Retrieve and authenticate one explanation from a committed Model build."""
    from gda_balancing.schema2.model import read_model_explanation as read

    return read(receipt_path, expected_descriptor_identity, artifact_set)
