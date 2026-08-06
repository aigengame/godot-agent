"""Authenticated retrieval of published Model explanations."""

from typing import Any, cast

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue
from gda_balancing.domain.model.compilation import validate_compiled_artifacts
from gda_balancing.domain.model.inspection_types import ModelInspectAdmissionError
from gda_balancing.domain.model.admission import _model_explanation_pairs_are_admitted
from gda_balancing.domain.publication import read_authenticated_artifact_set
from gda_balancing.domain.publication_types import PublicationAdmissionError


def read_model_explanation(
    receipt_path: str,
    expected_descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> dict[str, JsonValue]:
    """Retrieve and authenticate one explanation from a committed Model build."""
    try:
        publication = read_authenticated_artifact_set(
            receipt_path,
            expected_descriptor_identity,
            artifact_set,
        )
    except PublicationAdmissionError as err:
        raise ModelInspectAdmissionError(err.code, err.subject, err.message) from err
    artifacts = publication.artifacts
    build_receipt = artifacts["build-receipt"]
    source_identity = build_receipt.get("source_identity")
    if not isinstance(source_identity, str):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "build-receipt",
            "committed Model build has no source identity",
        )
    try:
        validate_compiled_artifacts(
            cast(dict[str, dict[str, JsonValue]], artifacts),
            source_identity,
            publication.authority_context,
            validate_explanation_projection=False,
        )
    except (KeyError, RuntimeError, TypeError, ValueError) as err:
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "resolved-model",
            "committed Model build members failed semantic admission",
        ) from err
    explanation = artifacts["model-explanation"]
    if not _model_explanation_pairs_are_admitted(
        explanation,
        artifacts["rir-semantic-payload"],
        artifacts["package-lock"],
        publication.authority_context,
    ):
        raise ModelInspectAdmissionError(
            "kernel.binding_mismatch",
            "model-explanation",
            "committed Model explanation Formula pairs failed admission",
        )
    return cast(dict[str, JsonValue], cast(dict[str, Any], explanation))
