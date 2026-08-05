"""CLI adapter for Standard Schema 1.x source migration."""

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.application.model_migration import migrate_model
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    RefusalDetailSpec,
)
from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.artifacts import artifact_wire_schema
from gda_balancing.domain.migration import MigrationInputError
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.interfaces.cli.artifact_set import ArtifactSetMemberLocator
from gda_balancing.domain.path_contracts import reject_input_aliasing
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model.semantics import refusal_catalog_for_stages
from gda_balancing.interfaces.cli.surface import descriptor_identity


class ModelMigrateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    out: str
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelMigrateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: str
    artifact_version: str
    wire_schema_identity: str
    descriptor_identity: str
    invocation_key: str
    manifest_identity: str
    manifest_locator: str
    member_locators: list[ArtifactSetMemberLocator]
    content_identity: str


_MODEL_MIGRATE_ARTIFACT_SET = (
    ArtifactSetMemberSpec("migration-report", "migration-report"),
    ArtifactSetMemberSpec(
        "model-source-package",
        "model-source-package",
        role="primary",
    ),
)


def _migration_report_schema() -> dict[str, object]:
    return artifact_wire_schema(
        packaged_authority_context().language_bundle,
        "migration-refusal-report",
    )


def run_model_migrate(
    inp: ModelMigrateInput,
) -> ModelMigrateResult | Schema2RefusalReport:
    reject_input_aliasing(inp.out, inp.source, input_is_known_path=True)
    try:
        result = migrate_model(
            inp.source,
            inp.out,
            inp.invocation_key,
            descriptor_identity(MODEL_MIGRATE),
            MODEL_MIGRATE.artifact_set,
        )
    except MigrationInputError as err:
        raise UnreadableInputError(str(err)) from err
    if isinstance(result, Schema2RefusalReport):
        return result
    return ModelMigrateResult.model_validate(result)


MODEL_MIGRATE = CommandDescriptor(
    group="model",
    command="migrate",
    description=(
        "Migrate the semantics-preserving Standard Schema 1.x source subset "
        "into a new 2.0 Model Source Package."
    ),
    input_model=ModelMigrateInput,
    output_model=ModelMigrateResult,
    handler=run_model_migrate,
    fixtures=ConformanceFixtures(
        valid_document=(
            '{"schema_version":"1.0.0","meta":{"name":"legacy.parameters"},'
            '"parameters":{"hit_points":100}}'
        ),
        refusing_document=(
            '{"schema_version":"1.0.0","meta":{"name":"legacy.parameters"},'
            '"parameters":{"hit_points":1.5}}'
        ),
    ),
    positional_field="source",
    artifact_set=_MODEL_MIGRATE_ARTIFACT_SET,
    schema_major=2,
    structured_params=True,
    refusal_catalog=refusal_catalog_for_stages(frozenset({"migration"})),
    refusal_details=(
        RefusalDetailSpec(
            stage="migration",
            field_name="migration_report",
            schema=_migration_report_schema,
        ),
    ),
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "invocation_key_conflict",
        "unknown_argument",
        "unreadable_input",
        "unwritable_output",
    ),
)
