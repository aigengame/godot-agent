"""Schema 2.0 Model Source checking and build commands."""

from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalDetailSpec,
)
from gda_balancing.interfaces.cli.artifact_set import ArtifactSetMemberLocator
from gda_balancing.interfaces.cli.model_build import (
    MODEL_BUILD,
    ModelBuildInput,
    ModelBuildResult,
    run_model_build,
)
from gda_balancing.interfaces.cli.model_fixtures import VALID_MODEL_SOURCE
from gda_balancing.path_contracts import reject_input_aliasing
from gda_balancing.schema2.authority import packaged_authority_context
from gda_balancing.schema2.canonical import JsonValue
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    ingress_refusal,
)
from gda_balancing.schema2.migration import (
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
from gda_balancing.schema2.model import (
    MODEL_INSPECT_REFUSAL_CATALOG,
    CheckedModel,
    ModelInspectAdmissionError,
    artifact_wire_schema,
    check_model_source_value,
    identified_artifact,
    read_model_explanation,
    refusal_catalog_for_stages,
    verify_artifact,
    wire_schema_identity,
)
from gda_balancing.schema2.surface import descriptor_identity


class ModelInspectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: str
    format: Literal["canonical", "indented"] = "canonical"


class ModelInspectResult(RootModel[dict[str, Any]]):
    model_config = ConfigDict(frozen=True)


def run_model_inspect(
    inp: ModelInspectInput,
) -> ModelInspectResult | Schema2RefusalReport:
    try:
        explanation = read_model_explanation(
            inp.receipt,
            descriptor_identity(MODEL_BUILD),
            MODEL_BUILD.artifact_set,
        )
    except ModelInspectAdmissionError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    return ModelInspectResult.model_validate(explanation)


def _model_explanation_schema() -> dict[str, object]:
    return artifact_wire_schema(
        packaged_authority_context().language_bundle,
        "model-explanation",
    )


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


def _prepare_model_inspect(root: Path, token: int) -> str:
    source = root / f"inspect-model-{token}.json"
    source.write_text(VALID_MODEL_SOURCE, encoding="utf-8")
    result = run_model_build(
        ModelBuildInput(
            source=str(source),
            out=str(root / f"inspect-model-{token}-out.json"),
            invocation_key=f"{token:064x}",
        )
    )
    if not isinstance(result, ModelBuildResult):
        raise RuntimeError("Model inspect prerequisite build was refused")
    receipt = result.model_dump(mode="json")
    receipt_path = Path(cast(str, receipt["manifest_locator"])).with_name(
        "artifact-set-receipt.json"
    )
    return receipt_path.read_text(encoding="utf-8")


_MODEL_MIGRATE_ARTIFACT_SET = (
    ArtifactSetMemberSpec("migration-report", "migration-report"),
    ArtifactSetMemberSpec(
        "model-source-package", "model-source-package", role="primary"
    ),
)
MIGRATION_REFUSAL_CATALOG = refusal_catalog_for_stages(frozenset({"migration"}))


def _migration_authorities() -> tuple[dict[str, Any], dict[str, Any]]:
    """Borrow the one immutable packaged authority lifecycle."""
    context = packaged_authority_context()
    return context.kernel, context.language_bundle


def _migration_report_schema() -> dict[str, object]:
    _, language_bundle = _migration_authorities()
    return artifact_wire_schema(language_bundle, "migration-refusal-report")


def run_model_migrate(
    inp: ModelMigrateInput,
) -> ModelMigrateResult | Schema2RefusalReport:
    reject_input_aliasing(inp.out, inp.source, input_is_known_path=True)
    data, input_identity = load_design_source_observation(inp.source)
    kernel, language_bundle = _migration_authorities()
    context = packaged_authority_context()
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
        admitted = check_model_source_value(
            value,
            authority_context=context,
        )
        return (
            isinstance(admitted, CheckedModel)
            and admitted.source_identity == checked.source_identity
        )

    receipt = publish_artifact_set(
        artifacts,
        inp.out,
        inp.invocation_key,
        descriptor_identity(MODEL_MIGRATE),
        cast(str, command_input["content_identity"]),
        language_bundle,
        _MODEL_MIGRATE_ARTIFACT_SET,
        member_is_admitted,
        authentication_key=publication_authentication_key(),
    )
    return ModelMigrateResult.model_validate(receipt)


MODEL_INSPECT = CommandDescriptor(
    group="model",
    command="inspect",
    description="Retrieve and render one stored immutable Model explanation.",
    input_model=ModelInspectInput,
    output_model=ModelInspectResult,
    handler=run_model_inspect,
    fixtures=ConformanceFixtures(
        prepare_valid_document=_prepare_model_inspect,
        refusing_document="{}",
    ),
    positional_field="receipt",
    json_presentation_field="format",
    schema_major=2,
    structured_params=True,
    success_schema=_model_explanation_schema,
    refusal_catalog=MODEL_INSPECT_REFUSAL_CATALOG,
    usage_codes=(
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)


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
    refusal_catalog=MIGRATION_REFUSAL_CATALOG,
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
