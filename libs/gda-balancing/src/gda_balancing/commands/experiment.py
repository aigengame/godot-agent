"""Standard Schema 2.0 Experiment checking and execution commands."""

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
    RefusalVariantSpec,
)
from gda_balancing.commands.model import (
    ModelBuildInput,
    ModelBuildResult,
    run_model_build,
)
from gda_balancing.schema2.authority import packaged_authority_context
from gda_balancing.schema2.authority_graph import LanguageBundleIndex
from gda_balancing.schema2.diagnostics import (
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.schema2.experiment import (
    CheckedExperiment,
    RuntimeRefusalOutcome,
    check_experiment,
    derive_scenario_program_requirements,
    evaluate_experiment,
    experiment_input_identity,
    runtime_terminal_audit_members,
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.schema2.model import (
    publication_authentication_key,
    publish_artifact_set,
    recover_committed_artifact_set,
    refusal_catalog_for_reasons,
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


_EXPERIMENT_CHECK_REFUSAL_REASONS = (
    "model.reason.source-too-large",
    "model.reason.source-parse-failure",
    "model.reason.source-contract-mismatch",
    "quantity.reason.invalid-domain",
    "model.reason.resolved-authority-mismatch",
    "model.reason.resolution-binding-mismatch",
)
_EXPERIMENT_RUN_ONLY_REFUSAL_REASONS = (
    "runtime.reason.capability-unsupported",
    "runtime.reason.step-limit",
    "runtime.reason.numeric-overflow",
    "runtime.reason.schedule-backward",
    "runtime.reason.cancel-active",
    "runtime.reason.cancel-completed",
    "runtime.reason.cancel-unknown",
    "evaluation.reason.observation-unavailable",
)
EXPERIMENT_CHECK_REFUSAL_CATALOG = refusal_catalog_for_reasons(
    _EXPERIMENT_CHECK_REFUSAL_REASONS
)
EXPERIMENT_RUN_REFUSAL_CATALOG = refusal_catalog_for_reasons(
    _EXPERIMENT_CHECK_REFUSAL_REASONS + _EXPERIMENT_RUN_ONLY_REFUSAL_REASONS
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
        recovered = recover_committed_artifact_set(
            inp.out,
            inp.invocation_key,
            descriptor_identity(EXPERIMENT_RUN),
            experiment_input_identity(checked.value),
            checked.language_bundle,
            (
                EXPERIMENT_RUN.artifact_set,
                EXPERIMENT_RUN.verdict_artifact_set,
                *(item.members for item in EXPERIMENT_RUN.refusal_artifact_sets),
            ),
            lambda logical_name, value: validate_experiment_member(
                checked, logical_name, value
            ),
            artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
                checked, artifacts
            ),
            authentication_key=publication_authentication_key(),
        )
        if recovered is not None:
            validated_receipt = ExperimentRunResult.model_validate(recovered.receipt)
            if recovered.artifact_set == EXPERIMENT_RUN.artifact_set:
                return validated_receipt
            if recovered.artifact_set == EXPERIMENT_RUN.verdict_artifact_set:
                verdict = recovered.artifacts["experiment-verdict"]
                return ExperimentVerdictResult(
                    outcome="rejected",
                    failed_metrics=verdict["failed_metrics"],
                    artifact_set=validated_receipt,
                )
            audit = recovered.artifacts["runtime-terminal-audit"]
            diagnostic = audit["diagnostic"]
            return Schema2RefusalReport(
                stage="runtime",
                variant="post-dispatch",
                diagnostics=(
                    Schema2Diagnostic.model_validate(
                        {
                            key: value
                            for key, value in diagnostic.items()
                            if key != "stage"
                        }
                    ),
                ),
                truncated=False,
                terminal_audit=recovered.receipt,
            )
        evaluation = evaluate_experiment(checked)
        if isinstance(evaluation, RuntimeRefusalOutcome):
            report = evaluation.report
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
                artifact_set_validator=lambda artifacts: (
                    validate_experiment_artifact_set(checked, artifacts)
                ),
                authentication_key=publication_authentication_key(),
            )
            return report.model_copy(update={"terminal_audit": receipt})
        if isinstance(evaluation, Schema2RefusalReport):
            return evaluation
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
            artifact_set_validator=lambda artifacts: validate_experiment_artifact_set(
                checked, artifacts
            ),
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


def _prepare_valid_experiment(root: Path, token: int) -> str:
    """Materialize conformance from package-owned source and runtime vectors."""
    context = packaged_authority_context()
    language_bundle = cast(LanguageBundleIndex, context.language_bundle)
    vector_set = next(
        row
        for row in language_bundle.package_conformance_vector_sets
        if row["package_id"] == "game.combat" and row["package_version"] == "2.1.0"
    )
    vectors = {row["id"]: row for row in vector_set["vector_definitions"]}
    source_fixture = vectors["game.combat.model-binding.positive"]["source_fixture"]
    runtime_vector = vectors["game.combat.cast.positive"]
    if source_fixture["mode"] != "literal":
        raise RuntimeError("Experiment conformance source fixture is not literal")
    source_value = deepcopy(source_fixture["source"])
    source = root / f"experiment-model-{token}.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    built = run_model_build(
        ModelBuildInput(
            source=str(source),
            out=str(root / f"experiment-model-{token}-out.json"),
            invocation_key=f"{token:064x}",
        )
    )
    if not isinstance(built, ModelBuildResult):
        raise RuntimeError("Experiment conformance prerequisite was refused")
    receipt = built.model_dump(mode="json")

    def member(logical_name: str) -> dict[str, Any]:
        locator = next(
            row["locator"]
            for row in receipt["member_locators"]
            if row["logical_name"] == logical_name
        )
        return json.loads(Path(locator).read_text(encoding="utf-8"))

    build = member("build-receipt")
    lock = member("package-lock")
    resolved = member("resolved-model")
    rir = member("rir-semantic-payload")
    entrypoint = next(
        row
        for row in rir["entrypoints"]
        if row["operation"]["id"] == runtime_vector["operation"]
    )
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    operation = operations[entrypoint["operation"]["id"]]
    rng_algorithm = context.kernel["meta_format"]["runtime_program"]["named_rng"][
        "algorithm"
    ]
    requirements, named_streams = derive_scenario_program_requirements(
        rir,
        entrypoint["id"],
        operation["runtime_profile"],
        rng_algorithm,
    )
    targets_by_port = {
        row["port"]["name"]: row["operand"]["symbol"]
        for row in entrypoint["arguments"]
        if row["operand"]["kind"] == "symbol"
    }
    assigned: dict[tuple[str, str, str], tuple[dict[str, str], int]] = {}
    for value in runtime_vector["input"]["values"]:
        target = targets_by_port[value["name"]]
        key = (target["model"], target["module"], target["name"])
        previous = assigned.get(key)
        if previous is not None and previous[1] != value["value"]:
            raise RuntimeError(
                "Package vector assigns conflicting values to one Model symbol"
            )
        assigned[key] = (target, value["value"])
    assignments = [
        {"target": target, "value": value}
        for target, value in (assigned[key] for key in sorted(assigned))
    ]
    result = entrypoint["result"]
    if result["kind"] != "symbol":
        raise RuntimeError("Experiment conformance entrypoint result is not observable")
    specification = {
        "schema_version": "2.0.0",
        "id": f"{source_value['manifest']['id']}.conformance",
        "version": "1.0.0",
        "kernel_identity": build["kernel_identity"],
        "language_bundle_identity": build["language_bundle_identity"],
        "model": {
            "source_identity": build["source_identity"],
            "build_receipt_identity": build["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
        },
        "runtime": {
            "profile": operation["runtime_profile"],
            "required_evaluator": requirements,
        },
        "seed": {
            "algorithm": rng_algorithm,
            "value": runtime_vector["input"]["seed"],
        },
        "scenarios": [
            {
                "id": runtime_vector["id"],
                "event_plan": [
                    {
                        "kind": "transition-invocation",
                        "root_event_ref": "conformance-entrypoint",
                        "logical_time": 0,
                        "priority": 0,
                        "entrypoint": entrypoint["id"],
                        "payload": [],
                    }
                ],
                "assignments": assignments,
                "named_streams": named_streams,
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            {
                "id": "damage",
                "kind": "scalar",
                "unit": "1",
                "dimensions": [],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
                "observation": {
                    "source": "event",
                    "name": operation["default_outcome"],
                    "member": result["symbol"]["name"],
                },
                "target": {"minimum": 0, "maximum": 1000},
            }
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }
    return json.dumps(specification)


def _prepare_verdict_experiment(root: Path, token: int) -> str:
    specification = json.loads(_prepare_valid_experiment(root, token))
    specification["metrics"][0]["target"] = {
        "minimum": 1000,
        "maximum": 1000,
    }
    return json.dumps(specification)


EXPERIMENT_CHECK = CommandDescriptor(
    group="experiment",
    command="check",
    description="Check one exact Standard Schema 2.0 Experiment Specification.",
    input_model=ExperimentCheckInput,
    output_model=ExperimentCheckResult,
    handler=run_experiment_check,
    fixtures=ConformanceFixtures(
        prepare_valid_document=_prepare_valid_experiment,
    ),
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
    fixtures=ConformanceFixtures(
        prepare_valid_document=_prepare_valid_experiment,
        prepare_verdict_document=_prepare_verdict_experiment,
    ),
    positional_field="specification",
    artifact_set=_EXPERIMENT_SUCCESS_ARTIFACT_SET,
    verdict_artifact_set=_EXPERIMENT_VERDICT_ARTIFACT_SET,
    refusal_artifact_sets=(
        RefusalArtifactSetSpec(
            stage="runtime",
            members=_EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
            variant="post-dispatch",
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
            required=False,
        ),
    ),
    refusal_variants=(
        RefusalVariantSpec(
            stage="runtime",
            id="pre-event",
            forbidden_details=("terminal_audit",),
        ),
        RefusalVariantSpec(
            stage="runtime",
            id="post-dispatch",
            required_details=("terminal_audit",),
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
