"""CLI adapter for exact Experiment Replay comparison."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.application.experiment_replay import (
    ExperimentReplayPublication,
    ExperimentReplayVerdictPublication,
    replay_experiment,
)
from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.interfaces.cli.descriptors import (
    ArtifactSetInputSpec,
    CommandDescriptor,
    ConformanceFixtures,
    RefusalArtifactSetSpec,
    RefusalDetailSpec,
    RefusalVariantSpec,
    artifact_sets_for_input,
)
from gda_balancing.interfaces.cli.experiment_fixtures import prepare_valid_experiment
from gda_balancing.interfaces.cli.experiment_run import (
    EXPERIMENT_RUN,
    ExperimentRunInput,
    ExperimentRunResult,
    run_experiment_run,
)
from gda_balancing.interfaces.cli.surface import descriptor_identity


class ExperimentReplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    specification: str
    original_experiment_run_artifact_set_receipt: str
    out: str = Field(min_length=1)
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_state: Literal["candidate"]
    artifact_set: ExperimentRunResult


class ExperimentReplayVerdictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["mismatched"]
    mismatches: list[str]
    artifact_set: ExperimentRunResult


_REPLAY_SUCCESS_ARTIFACT_SET = (
    ArtifactSetMemberSpec("replay-comparison", "replay-comparison", role="primary"),
    ArtifactSetMemberSpec("evaluation-run", "evaluation-run"),
    ArtifactSetMemberSpec("event-trace", "event-trace"),
    ArtifactSetMemberSpec("snapshot-series", "snapshot-series"),
    ArtifactSetMemberSpec("metric-dataset", "metric-dataset"),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest", "evaluator-capability-manifest"
    ),
)
_REPLAY_VERDICT_ARTIFACT_SET = tuple(
    member
    for member in _REPLAY_SUCCESS_ARTIFACT_SET
    if member.logical_name != "evaluation-run"
)
_REPLAY_RUNTIME_REFUSAL_ARTIFACT_SET = (
    ArtifactSetMemberSpec(
        "runtime-terminal-audit", "runtime-terminal-audit", role="primary"
    ),
    ArtifactSetMemberSpec("reproduction-receipt", "reproduction-receipt"),
    ArtifactSetMemberSpec("resolved-runtime-profile", "resolved-runtime-profile"),
    ArtifactSetMemberSpec(
        "evaluator-capability-manifest", "evaluator-capability-manifest"
    ),
)


def _artifact_set_input() -> ArtifactSetInputSpec:
    return EXPERIMENT_REPLAY.input_artifact_sets[0]


def _refusal_catalog() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            set(EXPERIMENT_RUN.resolved_refusal_catalog())
            | {
                ("evaluation.replay_ineligible_outcome", "evaluation"),
                ("evaluation.replay_reproduction_mismatch", "evaluation"),
            }
        )
    )


def experiment_replay_handler(
    *, publication_fault: str | None = None
) -> Callable[
    [ExperimentReplayInput],
    ExperimentReplayResult
    | ExperimentReplayVerdictResult
    | Schema2RefusalReport,
]:
    def _replay(
        inp: ExperimentReplayInput,
    ) -> (
        ExperimentReplayResult
        | ExperimentReplayVerdictResult
        | Schema2RefusalReport
    ):
        try:
            original_input = _artifact_set_input()
            result = replay_experiment(
                inp.specification,
                inp.original_experiment_run_artifact_set_receipt,
                inp.out,
                inp.invocation_key,
                descriptor_identity(EXPERIMENT_REPLAY),
                descriptor_identity(original_input.producer),
                artifact_sets_for_input(original_input),
                EXPERIMENT_REPLAY.artifact_set,
                EXPERIMENT_REPLAY.verdict_artifact_set,
                _REPLAY_RUNTIME_REFUSAL_ARTIFACT_SET,
                publication_fault=publication_fault,
            )
        except InputReadError as error:
            raise UnreadableInputError(
                "cannot read an Experiment Replay input document"
            ) from error
        if isinstance(result, Schema2RefusalReport):
            return result
        receipt = ExperimentRunResult.model_validate(result.receipt)
        if isinstance(result, ExperimentReplayPublication):
            return ExperimentReplayResult(
                claim_state="candidate", artifact_set=receipt
            )
        assert isinstance(result, ExperimentReplayVerdictPublication)
        return ExperimentReplayVerdictResult(
            outcome="mismatched",
            mismatches=list(result.mismatches),
            artifact_set=receipt,
        )

    return _replay


def _prepare_replay_args(root: Path, token: int, refusing: bool) -> tuple[str, ...]:
    specification = root / f"replay-experiment-{token}.json"
    specification_value = json.loads(prepare_valid_experiment(root, token))
    specification.write_bytes(
        canonical_bytes(cast(JsonValue, specification_value))
    )
    original = run_experiment_run(
        ExperimentRunInput(
            specification=str(specification),
            out=str(root / f"replay-original-{token}.json"),
            invocation_key=f"{token:064x}",
        )
    )
    if not isinstance(original, ExperimentRunResult):
        raise RuntimeError("Replay fixture prerequisite run did not succeed")
    receipt = root / f"replay-original-{token}-receipt.json"
    receipt.write_bytes(
        canonical_bytes(cast(JsonValue, original.model_dump(mode="json")))
    )
    if refusing:
        specification_value["seed"]["value"] += 1
        specification.write_bytes(
            canonical_bytes(cast(JsonValue, specification_value))
        )
    return (
        str(specification),
        "--original-experiment-run-artifact-set-receipt",
        str(receipt),
    )


run_experiment_replay = experiment_replay_handler()

EXPERIMENT_REPLAY = CommandDescriptor(
    group="experiment",
    command="replay",
    description="Repeat and compare one authenticated successful Experiment run.",
    input_model=ExperimentReplayInput,
    output_model=ExperimentReplayResult,
    verdict_model=ExperimentReplayVerdictResult,
    handler=run_experiment_replay,
    fixtures=ConformanceFixtures(
        prepare_args=_prepare_replay_args,
        unavailable_verdict_fixture_reason=(
            "same-head exact Replay cannot produce implementation drift"
        ),
    ),
    positional_field="specification",
    artifact_set=_REPLAY_SUCCESS_ARTIFACT_SET,
    verdict_artifact_set=_REPLAY_VERDICT_ARTIFACT_SET,
    input_artifact_sets=(
        ArtifactSetInputSpec(
            receipt_field="original_experiment_run_artifact_set_receipt",
            producer=EXPERIMENT_RUN,
        ),
    ),
    refusal_artifact_sets=(
        RefusalArtifactSetSpec(
            stage="runtime",
            members=_REPLAY_RUNTIME_REFUSAL_ARTIFACT_SET,
            variant="post-dispatch",
        ),
    ),
    schema_major=2,
    structured_params=True,
    stochastic=True,
    refusal_catalog_provider=_refusal_catalog,
    refusal_details=(
        RefusalDetailSpec(
            stage="runtime",
            field_name="terminal_audit",
            schema=ExperimentRunResult.model_json_schema,
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
