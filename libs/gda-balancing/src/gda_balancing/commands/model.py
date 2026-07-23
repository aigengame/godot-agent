"""Schema 2.0 Model Source checking and build commands."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import (
    MODEL_REFUSAL_CATALOG,
    CheckedModel,
    admit_resolved_model,
    check_model_source,
    lower_checked_model,
    publish_model_artifacts,
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
        )
        return ModelBuildResult.model_validate(receipt)

    return _run


run_model_build = model_build_handler()


_VALID_SOURCE = """{
  "schema_version": "2.0.0",
  "manifest": {"id": "example.quantity-model", "version": "1.0.0", "entry_module": "main"},
  "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
  "modules": [{
    "id": "main",
    "imports": [{"alias": "quantity", "package": "core.quantity", "version": "2.0.0", "symbol": "Quantity"}],
    "symbols": [
      {"symbol":"constant_value","type":"quantity","role":"constant","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"},
      {"symbol":"parameter_value","type":"quantity","role":"parameter","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"},
      {"symbol":"input_value","type":"quantity","role":"input","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"},
      {"symbol":"state_value","type":"quantity","role":"state","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"},
      {"symbol":"derived_value","type":"quantity","role":"derived","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"},
      {"symbol":"output_value","type":"quantity","role":"output","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"},
      {"symbol":"random_value","type":"quantity","role":"random","representation":"Int","kind":"scalar","unit":"1","domain_kind":"closed-interval","domain":{"minimum":0,"maximum":100},"numeric_policy":"exact-int64"}
    ]
  }]
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
