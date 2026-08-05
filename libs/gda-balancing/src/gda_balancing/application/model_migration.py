"""Migrate an admitted Standard Schema 1.x source into 2.x artifacts."""

from collections.abc import Callable
from typing import Any, cast

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.artifacts import (
    identified_artifact,
    verify_artifact,
    wire_schema_identity,
)
from gda_balancing.domain.migration import (
    MigrationFailure,
    MigrationSuccess,
    converter_specification,
    load_design_source_observation,
    migrate_design_source,
)
from gda_balancing.domain.publication import (
    PublicationMember,
    publication_authentication_key,
    publish_artifact_set,
)
from gda_balancing.schema2.authority import (
    AdmittedAuthorityContext,
    packaged_authority_context,
)
from gda_balancing.schema2.canonical import JsonValue
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import CheckedModel, check_model_source_value


MigrationAuthorityProvider = Callable[[], AdmittedAuthorityContext]


def migrate_model(
    source: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    *,
    authority_context_provider: MigrationAuthorityProvider = packaged_authority_context,
) -> dict[str, Any] | Schema2RefusalReport:
    """Convert, self-admit, and publish one supported 1.x source."""
    data, input_identity = load_design_source_observation(source)
    context = authority_context_provider()
    kernel = context.kernel
    language_bundle = context.language_bundle
    converter = converter_specification(language_bundle)
    converter_identity = cast(str, converter["content_identity"])

    migrated = migrate_design_source(
        data,
        language_bundle,
        input_identity=input_identity,
    )
    if isinstance(migrated, MigrationFailure):
        refusal_payload: dict[str, JsonValue] = {
            "status": "refused",
            "input_identity": migrated.input_identity,
            "target_schema_version": "2.0.0",
            "converter_identity": converter_identity,
            "converter_specification": cast(JsonValue, converter),
            "kernel_identity": cast(str, kernel["content_identity"]),
            "language_bundle_identity": cast(str, language_bundle["content_identity"]),
            "mappings": cast(JsonValue, list(migrated.mappings)),
            "defaults": cast(JsonValue, list(migrated.defaults)),
            "warnings": cast(JsonValue, list(migrated.warnings)),
            "deprecated_constructs": cast(
                JsonValue, list(migrated.deprecated_constructs)
            ),
            "truncated": migrated.refusal.truncated,
            "refusals": cast(
                JsonValue,
                [
                    diagnostic.model_dump(mode="json")
                    for diagnostic in migrated.refusal.diagnostics
                ],
            ),
        }
        if migrated.source_schema_version is not None:
            refusal_payload["source_schema_version"] = migrated.source_schema_version
        report = identified_artifact(
            language_bundle,
            "migration-refusal-report",
            refusal_payload,
        )
        return Schema2RefusalReport(
            stage=migrated.refusal.stage,
            diagnostics=migrated.refusal.diagnostics,
            truncated=migrated.refusal.truncated,
            migration_report=cast(dict[str, Any], report),
        )

    assert isinstance(migrated, MigrationSuccess)
    checked = check_model_source_value(
        cast(dict[str, Any], migrated.source),
        authority_context=context,
    )
    if isinstance(checked, Schema2RefusalReport):
        raise RuntimeError("migrated Model Source failed exact-authority admission")
    assert isinstance(checked, CheckedModel)

    report = identified_artifact(
        language_bundle,
        "migration-report",
        {
            "status": "migrated",
            "input_identity": migrated.input_identity,
            "source_schema_version": migrated.source_schema_version,
            "target_schema_version": "2.0.0",
            "converter_identity": converter_identity,
            "converter_specification": cast(JsonValue, converter),
            "kernel_identity": cast(str, kernel["content_identity"]),
            "language_bundle_identity": cast(str, language_bundle["content_identity"]),
            "output_identity": checked.source_identity,
            "mappings": cast(JsonValue, list(migrated.mappings)),
            "defaults": cast(JsonValue, list(migrated.defaults)),
            "warnings": cast(JsonValue, list(migrated.warnings)),
            "deprecated_constructs": [],
            "refusals": [],
        },
    )
    command_input = identified_artifact(
        language_bundle,
        "model-migrate-command-input",
        {
            "input_identity": migrated.input_identity,
            "converter_identity": converter_identity,
            "kernel_identity": cast(str, kernel["content_identity"]),
            "language_bundle_identity": cast(str, language_bundle["content_identity"]),
        },
    )
    artifacts = {
        "migration-report": PublicationMember(
            value=cast(dict[str, Any], report),
            artifact_kind="migration-report",
            wire_schema_identity=cast(str, report["wire_schema_identity"]),
            content_identity=cast(str, report["content_identity"]),
        ),
        "model-source-package": PublicationMember(
            value=cast(dict[str, Any], migrated.source),
            artifact_kind="model-source-package",
            wire_schema_identity=wire_schema_identity(
                language_bundle, "model-source-package"
            ),
            content_identity=checked.source_identity,
        ),
    }

    def member_is_admitted(name: str, value: dict[str, Any]) -> bool:
        if name == "migration-report":
            return verify_artifact(value, language_bundle)
        admitted = check_model_source_value(value, authority_context=context)
        return (
            isinstance(admitted, CheckedModel)
            and admitted.source_identity == checked.source_identity
        )

    return publish_artifact_set(
        artifacts,
        out,
        invocation_key,
        descriptor_identity,
        cast(str, command_input["content_identity"]),
        language_bundle,
        artifact_set,
        member_is_admitted,
        authentication_key=publication_authentication_key(),
    )
