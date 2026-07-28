"""Schema 2.0 Model Source checking and build commands."""

from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalDetailSpec,
)
from gda_balancing.path_contracts import reject_input_aliasing
from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.canonical import JsonValue
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
)
from gda_balancing.schema2.migration import (
    MigrationFailure,
    MigrationSuccess,
    converter_specification,
    load_design_source_observation,
    migrate_design_source,
)
from gda_balancing.schema2.model import (
    MODEL_REFUSAL_CATALOG,
    CheckedModel,
    PublicationMember,
    admit_resolved_model,
    artifact_wire_schema,
    check_model_source,
    check_model_source_value,
    identified_artifact,
    lower_checked_model,
    publication_authentication_key,
    publish_artifact_set,
    publish_model_artifacts,
    refusal_catalog_for_stages,
    verify_artifact,
    wire_schema_identity,
)
from gda_balancing.schema2.surface import descriptor_identity


class ModelCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str


class ModelCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: bool
    kernel_identity: str
    language_bundle_identity: str


def run_model_check(
    inp: ModelCheckInput,
) -> ModelCheckResult | Schema2RefusalReport:
    checked = check_model_source(inp.source)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    assert isinstance(checked, CheckedModel)
    artifacts = lower_checked_model(checked)
    semantic_admission = admit_resolved_model(
        {
            name: artifacts[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        }
    )
    if not semantic_admission.admitted:
        raise RuntimeError("checked Resolved Model failed exact-authority admission")
    return ModelCheckResult(
        checked=True,
        kernel_identity=checked.kernel["content_identity"],
        language_bundle_identity=checked.language_bundle["content_identity"],
    )


class ModelBuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    out: str
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactSetMemberLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_name: str
    locator: str


class ModelBuildResult(BaseModel):
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


def model_build_handler(
    *, publication_fault: str | None = None
) -> Callable[[ModelBuildInput], ModelBuildResult | Schema2RefusalReport]:
    """Create the build handler; ``publication_fault`` is test-only injection."""

    if publication_fault not in {
        None,
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    }:
        raise ValueError("unknown publication fault")

    def _run(inp: ModelBuildInput) -> ModelBuildResult | Schema2RefusalReport:
        authentication_key = publication_authentication_key()
        checked = check_model_source(inp.source)
        if isinstance(checked, Schema2RefusalReport):
            return checked
        receipt = publish_model_artifacts(
            checked,
            inp.source,
            inp.out,
            inp.invocation_key,
            descriptor_identity(MODEL_BUILD),
            MODEL_BUILD.artifact_set,
            publication_fault,
            authentication_key=authentication_key,
        )
        return ModelBuildResult.model_validate(receipt)

    return _run


run_model_build = model_build_handler()


_MODEL_MIGRATE_ARTIFACT_SET = (
    ArtifactSetMemberSpec("migration-report", "migration-report"),
    ArtifactSetMemberSpec(
        "model-source-package", "model-source-package", role="primary"
    ),
)
MIGRATION_REFUSAL_CATALOG = refusal_catalog_for_stages(frozenset({"migration"}))


@lru_cache(maxsize=1)
def _migration_authorities() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the immutable packaged migration authorities once per process."""
    return load_authorities()


def _migration_report_schema() -> dict[str, object]:
    _, language_bundle = _migration_authorities()
    return artifact_wire_schema(language_bundle, "migration-refusal-report")


def run_model_migrate(
    inp: ModelMigrateInput,
) -> ModelMigrateResult | Schema2RefusalReport:
    reject_input_aliasing(inp.out, inp.source, input_is_known_path=True)
    data, input_identity = load_design_source_observation(inp.source)
    kernel, language_bundle = _migration_authorities()
    admission = admit_authorities(kernel, language_bundle)
    if not admission.admitted:
        return bootstrap_refusal(admission)
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
        kernel=kernel,
        language_bundle=language_bundle,
        authority_admission=admission,
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
            kernel=kernel,
            language_bundle=language_bundle,
            authority_admission=admission,
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


_VALID_SOURCE = """{
  "schema_version": "2.0.0",
  "manifest": {"id": "example.quantity-model", "version": "1.0.0", "entry_module": "main"},
  "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
  "modules": [{
    "id": "main",
    "imports": [{"alias": "quantity", "package": "core.quantity", "version": "2.0.0", "symbol": "Quantity"}],
    "symbols": [
      {"symbol":"constant_value","type":"quantity","role":"constant","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"model-fixed","value":1}},
      {"symbol":"parameter_value","type":"quantity","role":"parameter","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"experiment-required"}},
      {"symbol":"input_value","type":"quantity","role":"input","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"experiment-required"}},
      {"symbol":"state_value","type":"quantity","role":"state","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"experiment-required"}},
      {"symbol":"derived_value","type":"quantity","role":"derived","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"none"}},
      {"symbol":"output_value","type":"quantity","role":"output","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"none"}},
      {"symbol":"random_value","type":"quantity","role":"random","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64","value_policy":{"mode":"named-stream"}}
    ]
  }],
  "entrypoints": []
}"""


MODEL_CHECK = CommandDescriptor(
    group="model",
    command="check",
    description="Check a Standard Schema 2.0 Model Source Package.",
    input_model=ModelCheckInput,
    output_model=ModelCheckResult,
    handler=run_model_check,
    fixtures=ConformanceFixtures(valid_document=_VALID_SOURCE),
    positional_field="source",
    schema_major=2,
    structured_params=True,
    refusal_catalog=MODEL_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)


MODEL_BUILD = CommandDescriptor(
    group="model",
    command="build",
    description="Build and atomically publish a Standard Schema 2.0 Model.",
    input_model=ModelBuildInput,
    output_model=ModelBuildResult,
    handler=run_model_build,
    fixtures=ConformanceFixtures(valid_document=_VALID_SOURCE),
    positional_field="source",
    artifact_set=(
        ArtifactSetMemberSpec("build-receipt", "build-receipt"),
        ArtifactSetMemberSpec("capability-manifest", "capability-manifest"),
        ArtifactSetMemberSpec("debug-map", "debug-map"),
        ArtifactSetMemberSpec("package-lock", "package-lock"),
        ArtifactSetMemberSpec("resolution-receipt", "resolution-receipt"),
        ArtifactSetMemberSpec("resolved-model", "resolved-model", role="primary"),
        ArtifactSetMemberSpec("rir-semantic-payload", "rir-semantic-payload"),
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=MODEL_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "invocation_key_conflict",
        "unknown_argument",
        "unreadable_input",
        "unwritable_output",
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
