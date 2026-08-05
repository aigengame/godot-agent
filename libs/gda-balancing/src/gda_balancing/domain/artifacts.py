"""Standard Schema artifact identity, schema admission, and lookup."""

from typing import Any, cast

from gda_balancing.schema2.canonical import JsonValue


class PublishedArtifactIntegrityError(RuntimeError):
    """An authenticated publication named the target but failed verification."""


def identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Construct and schema-admit one content-addressed artifact."""
    from gda_balancing.schema2.model import identified_artifact as identify

    return identify(language_bundle, artifact_kind, payload)


def verify_artifact(value: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    """Re-admit one content-addressed artifact against the exact LDB."""
    from gda_balancing.schema2.model import verify_artifact as verify

    return verify(value, language_bundle)


def find_published_artifact(
    content_identity: str,
    artifact_kind: str,
    language_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    """Find one exact artifact through authenticated committed publications."""
    from gda_balancing.schema2.model import find_published_artifact as find

    return find(content_identity, artifact_kind, language_bundle)


def wire_schema_identity(
    language_bundle: dict[str, Any],
    artifact_kind: str,
) -> str:
    """Return the LDB-owned wire-schema identity for one artifact kind."""
    from gda_balancing.schema2.model import wire_schema_identity as identity

    return identity(language_bundle, artifact_kind)


def artifact_wire_schema(
    language_bundle: dict[str, Any],
    artifact_kind: str,
) -> dict[str, object]:
    """Return an isolated copy of one LDB-owned artifact schema."""
    from gda_balancing.schema2.model import artifact_wire_schema as schema

    return cast(dict[str, object], schema(language_bundle, artifact_kind))
