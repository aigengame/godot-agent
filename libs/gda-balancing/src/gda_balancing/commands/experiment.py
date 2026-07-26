"""Standard Schema 2.0 Experiment checking and execution commands."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
)
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.experiment import (
    CheckedExperiment,
    check_experiment,
    evaluate_experiment,
    experiment_input_identity,
    runtime_terminal_audit_members,
    validate_experiment_member,
)
from gda_balancing.schema2.model import (
    publication_authentication_key,
    publish_artifact_set,
    refusal_catalog_for_stages,
)
from gda_balancing.schema2.surface import descriptor_identity


class ExperimentCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str


class ExperimentCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: bool
    experiment_identity: str
    resolved_model_identity: str
    runtime_profile: str


class ExperimentRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str
    out: str = Field(min_length=1)
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentArtifactSetMemberLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_name: str
    locator: str


class ExperimentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: str
    artifact_version: str
    wire_schema_identity: str
    descriptor_identity: str
    invocation_key: str
    manifest_identity: str
    manifest_locator: str
    member_locators: list[ExperimentArtifactSetMemberLocator]
    content_identity: str


class ExperimentVerdictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: str
    failed_metrics: list[str]
    artifact_set: ExperimentRunResult


EXPERIMENT_CHECK_REFUSAL_CATALOG = refusal_catalog_for_stages(
    frozenset({"ingress", "parse", "static", "resolution"})
)
EXPERIMENT_RUN_REFUSAL_CATALOG = refusal_catalog_for_stages(
    frozenset({"ingress", "parse", "static", "resolution", "runtime", "evaluation"})
)

_EXPERIMENT_SUCCESS_ARTIFACT_SET = (
    ArtifactSetMemberSpec("evaluation-run", "evaluation-run", role="primary"),
    ArtifactSetMemberSpec("event-trace", "event-trace"),
    ArtifactSetMemberSpec("snapshot-series", "snapshot-series"),
    ArtifactSetMemberSpec("metric-dataset", "metric-dataset"),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest",
        "evaluator-capability-manifest",
    ),
)
_EXPERIMENT_VERDICT_ARTIFACT_SET = (
    ArtifactSetMemberSpec(
        "experiment-verdict",
        "experiment-verdict",
        role="primary",
    ),
    ArtifactSetMemberSpec("event-trace", "event-trace"),
    ArtifactSetMemberSpec("snapshot-series", "snapshot-series"),
    ArtifactSetMemberSpec("metric-dataset", "metric-dataset"),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest",
        "evaluator-capability-manifest",
    ),
)
_EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET = (
    ArtifactSetMemberSpec(
        "runtime-terminal-audit",
        "runtime-terminal-audit",
        role="primary",
    ),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest",
        "evaluator-capability-manifest",
    ),
)


def _terminal_audit_receipt_schema() -> dict[str, object]:
    return ExperimentRunResult.model_json_schema()


def run_experiment_check(
    inp: ExperimentCheckInput,
) -> ExperimentCheckResult | Schema2RefusalReport:
    checked = check_experiment(inp.specification)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    return ExperimentCheckResult(
        checked=True,
        experiment_identity=checked.content_identity,
        resolved_model_identity=checked.resolved_model["content_identity"],
        runtime_profile=checked.value["runtime"]["profile"],
    )


def experiment_run_handler(
    *, publication_fault: str | None = None
) -> Callable[
    [ExperimentRunInput],
    ExperimentRunResult | ExperimentVerdictResult | Schema2RefusalReport,
]:
    """Create the run handler; publication fault injection is test-only."""

    def _run(
        inp: ExperimentRunInput,
    ) -> ExperimentRunResult | ExperimentVerdictResult | Schema2RefusalReport:
        checked = check_experiment(inp.specification)
        if isinstance(checked, Schema2RefusalReport):
            return checked
        assert isinstance(checked, CheckedExperiment)
        evaluation = evaluate_experiment(checked)
        if isinstance(evaluation, Schema2RefusalReport):
            if evaluation.stage != "runtime":
                return evaluation
            runtime_set = next(
                item.members
                for item in EXPERIMENT_RUN.refusal_artifact_sets
                if item.stage == "runtime"
            )
            members = runtime_terminal_audit_members(checked, evaluation)
            receipt = publish_artifact_set(
                members,
                inp.out,
                inp.invocation_key,
                descriptor_identity(EXPERIMENT_RUN),
                experiment_input_identity(checked.value),
                checked.language_bundle,
                runtime_set,
                lambda logical_name, value: validate_experiment_member(
                    checked, logical_name, value
                ),
                publication_fault,
                authentication_key=publication_authentication_key(),
            )
            return evaluation.model_copy(update={"terminal_audit": receipt})
        artifact_set = (
            EXPERIMENT_RUN.artifact_set
            if evaluation.accepted
            else EXPERIMENT_RUN.verdict_artifact_set
        )
        receipt = publish_artifact_set(
            evaluation.members,
            inp.out,
            inp.invocation_key,
            descriptor_identity(EXPERIMENT_RUN),
            experiment_input_identity(checked.value),
            checked.language_bundle,
            artifact_set,
            lambda logical_name, value: validate_experiment_member(
                checked, logical_name, value
            ),
            publication_fault,
            authentication_key=publication_authentication_key(),
        )
        validated_receipt = ExperimentRunResult.model_validate(receipt)
        if evaluation.accepted:
            return validated_receipt
        return ExperimentVerdictResult(
            outcome="rejected",
            failed_metrics=list(evaluation.failed_metrics),
            artifact_set=validated_receipt,
        )

    return _run


run_experiment_run = experiment_run_handler()

_VALID_EXPERIMENT = """{
  "schema_version": "2.0.0",
  "id": "conformance.experiment",
  "version": "1.0.0",
  "kernel_identity": "sha256:fixture",
  "language_bundle_identity": "sha256:fixture",
  "model": {
    "source_identity": "sha256:fixture",
    "build_receipt_identity": "sha256:fixture",
    "resolved_model_identity": "sha256:fixture",
    "package_lock_identity": "sha256:fixture",
    "rir_identity": "sha256:fixture"
  },
  "runtime": {
    "profile": "rpg.exact-int64-event-v1",
    "required_evaluator": {
      "operation_kinds": ["event-program"],
      "instruction_nodes": ["constant"],
      "effects": ["event.commit"],
      "numeric_policies": ["exact-int64"],
      "rng_algorithms": ["splitmix64-v1"]
    }
  },
  "seed": {"algorithm": "splitmix64-v1", "value": 1},
  "external_inputs": [],
  "scenarios": [{
    "id": "one",
    "operation": "rpg.combat.cast-v1",
    "values": [{"name": "value", "value": 1}],
    "named_streams": [],
    "terminal_condition": {"kind": "event-count", "maximum": 1}
  }],
  "metrics": [{
    "id": "value",
    "kind": "scalar",
    "unit": "1",
    "observation": {"source": "snapshot", "name": "terminal", "member": "value"},
    "target": {"minimum": 0, "maximum": 1}
  }],
  "acceptance": {"policy": "all-metrics-within-target"}
}"""


EXPERIMENT_CHECK = CommandDescriptor(
    group="experiment",
    command="check",
    description="Check one exact Standard Schema 2.0 Experiment Specification.",
    input_model=ExperimentCheckInput,
    output_model=ExperimentCheckResult,
    handler=run_experiment_check,
    fixtures=ConformanceFixtures(valid_document=_VALID_EXPERIMENT),
    positional_field="specification",
    schema_major=2,
    structured_params=True,
    refusal_catalog=EXPERIMENT_CHECK_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)


EXPERIMENT_RUN = CommandDescriptor(
    group="experiment",
    command="run",
    description="Run and atomically publish one exact Standard Schema 2.0 Experiment.",
    input_model=ExperimentRunInput,
    output_model=ExperimentRunResult,
    verdict_model=ExperimentVerdictResult,
    handler=run_experiment_run,
    fixtures=ConformanceFixtures(valid_document=_VALID_EXPERIMENT),
    positional_field="specification",
    artifact_set=_EXPERIMENT_SUCCESS_ARTIFACT_SET,
    verdict_artifact_set=_EXPERIMENT_VERDICT_ARTIFACT_SET,
    refusal_artifact_sets=(
        RefusalArtifactSetSpec(
            stage="runtime",
            members=_EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
        ),
    ),
    schema_major=2,
    structured_params=True,
    stochastic=True,
    refusal_catalog=EXPERIMENT_RUN_REFUSAL_CATALOG,
    refusal_details=(
        RefusalDetailSpec(
            stage="runtime",
            field_name="terminal_audit",
            schema=_terminal_audit_receipt_schema,
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
