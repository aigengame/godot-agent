"""Standard Schema 2.0 Experiment checking and execution commands."""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
)
from gda_balancing.commands.model import (
    ModelBuildInput,
    ModelBuildResult,
    run_model_build,
)
from gda_balancing.schema2.canonical import content_identity
from gda_balancing.schema2.diagnostics import (
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.schema2.experiment import (
    CheckedExperiment,
    RuntimeRefusalOutcome,
    check_experiment,
    evaluate_experiment,
    experiment_input_identity,
    runtime_terminal_audit_members,
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


def _conformance_quantity(name: str, role: str) -> dict[str, object]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 1000},
        "numeric_policy": "exact-int64",
        "value_policy": {
            "mode": (
                "experiment-required"
                if role not in {"derived", "output", "random"}
                else "none"
            )
        },
    }


def _prepare_valid_experiment(root: Path, token: int) -> str:
    """Materialize the public Model prerequisite for registry conformance."""
    source_value = {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "conformance.rpg-combat",
            "version": "1.0.0",
            "entry_module": "combat",
        },
        "package_requirements": [
            {"id": "core.quantity", "version": "2.0.0"},
            {"id": "game.combat", "version": "1.0.0"},
        ],
        "modules": [
            {
                "id": "combat",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [
                    _conformance_quantity("actor_mana", "state"),
                    _conformance_quantity("action_cost", "parameter"),
                    _conformance_quantity("accuracy", "parameter"),
                    _conformance_quantity("base_damage", "parameter"),
                    _conformance_quantity("critical_threshold", "parameter"),
                    _conformance_quantity("target_defense", "input"),
                    _conformance_quantity("target_health", "state"),
                    _conformance_quantity("damage_dealt", "output"),
                ],
            }
        ],
        "entrypoints": [
            {
                "id": "combat.cast",
                "operation": {
                    "package": "game.combat",
                    "version": "1.0.0",
                    "id": "game.combat.cast-v1",
                },
                "arguments": [
                    {
                        "port": port,
                        "operand": {
                            "kind": "symbol",
                            "module": "combat",
                            "symbol": symbol,
                        },
                    }
                    for port, symbol in (
                        ("actor_resource", "actor_mana"),
                        ("action_cost", "action_cost"),
                        ("accuracy", "accuracy"),
                        ("base_damage", "base_damage"),
                        ("critical_threshold", "critical_threshold"),
                        ("hit_defense", "target_defense"),
                        ("damage_mitigation", "target_defense"),
                        ("target_health", "target_health"),
                    )
                ],
                "result": {
                    "kind": "symbol",
                    "module": "combat",
                    "symbol": "damage_dealt",
                },
            }
        ],
    }
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

    def member(logical_name: str) -> dict[str, object]:
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
    specification = {
        "schema_version": "2.0.0",
        "id": "conformance.experiment",
        "version": "1.0.0",
        "kernel_identity": build["kernel_identity"],
        "language_bundle_identity": build["language_bundle_identity"],
        "model": {
            "source_identity": content_identity(
                "model-source-package-v2", source_value
            ),
            "build_receipt_identity": build["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
        },
        "runtime": {
            "profile": "standard.exact-int64-event-v1",
            "required_evaluator": {
                "operation_kinds": ["event-fragment", "event-program"],
                "instruction_nodes": [
                    "add",
                    "constant",
                    "draw",
                    "if",
                    "invoke",
                    "less-than-or-equal",
                    "maximum",
                    "multiply",
                    "precondition-greater-than-or-equal",
                    "subtract",
                    "subtract-state",
                ],
                "effects": [
                    "event.commit",
                    "metric.observe",
                    "rng.named-stream",
                    "snapshot.commit",
                ],
                "numeric_policies": ["exact-int64"],
                "rng_algorithms": ["splitmix64-v1"],
                "runtime_profiles": ["standard.exact-int64-event-v1"],
            },
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 1},
        "external_inputs": [],
        "scenarios": [
            {
                "id": "one",
                "entrypoint": "combat.cast",
                "assignments": [
                    {
                        "target": {
                            "model": "example.rpg-combat-cast",
                            "module": "combat",
                            "name": name,
                        },
                        "value": value,
                    }
                    for name, value in (
                        ("actor_mana", 30),
                        ("action_cost", 8),
                        ("accuracy", 85),
                        ("base_damage", 24),
                        ("critical_threshold", 0),
                        ("target_defense", 6),
                        ("target_health", 100),
                    )
                ],
                "named_streams": ["critical", "hit"],
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
                    "name": "cast-resolved",
                    "member": "damage_dealt",
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
    "profile": "standard.exact-int64-event-v1",
    "required_evaluator": {
      "operation_kinds": ["event-fragment", "event-program"],
      "instruction_nodes": ["constant"],
      "effects": ["event.commit"],
      "numeric_policies": ["exact-int64"],
      "rng_algorithms": ["splitmix64-v1"],
      "runtime_profiles": ["standard.exact-int64-event-v1"]
    }
  },
  "seed": {"algorithm": "splitmix64-v1", "value": 1},
  "external_inputs": [],
  "scenarios": [{
    "id": "one",
    "entrypoint": "main",
    "assignments": [{
      "target": {"model": "fixture", "module": "main", "name": "value"},
      "value": 1
    }],
    "named_streams": [],
    "terminal_condition": {"kind": "event-count", "maximum": 1}
  }],
  "metrics": [{
    "id": "value",
    "kind": "scalar",
    "unit": "1",
    "dimensions": [],
    "window": {"kind": "scenario", "name": "terminal-event"},
    "aggregation": "single",
    "replication": {"unit": "scenario"},
    "missing": "refuse",
    "censoring": "none",
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
    fixtures=ConformanceFixtures(
        valid_document=_VALID_EXPERIMENT,
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
        valid_document=_VALID_EXPERIMENT,
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
