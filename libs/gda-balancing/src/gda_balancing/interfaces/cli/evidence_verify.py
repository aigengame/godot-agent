"""CLI adapter for exact Evidence candidate verification."""

from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.evidence_verify import (
    EvidenceVerifyInput as ApplicationInput,
    verify_evidence,
)
from gda_balancing.domain.authority.admission import BOOTSTRAP_REFUSAL_CATALOG
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.diagnostics import (
    Schema2RefusalReport,
    refusal_catalog_for_reasons,
)
from gda_balancing.domain.evidence_verification import EvidenceCandidate
from gda_balancing.domain.experiment import EXPERIMENT_CHECK_REFUSAL_REASONS
from gda_balancing.domain.model import MODEL_REFUSAL_CATALOG
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.interfaces.cli.experiment_fixtures import prepare_valid_experiment
from gda_balancing.interfaces.cli.experiment_run import (
    EXPERIMENT_RUN,
    ExperimentRunInput,
    ExperimentRunResult,
    run_experiment_run,
)
from gda_balancing.interfaces.cli.model_build import MODEL_BUILD
from gda_balancing.interfaces.cli.surface import descriptor_identity


class EvidenceVerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_kind: str
    source: str
    specification: str
    model_build_receipt: str
    experiment_outcome_receipt: str


class EvidenceVerifyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_kind: str
    claim_state: str
    producing_outcome: str
    kernel_identity: str
    language_bundle_identity: str
    model_source_identity: str
    resolved_model_identity: str
    experiment_identity: str
    resolved_runtime_profile_identity: str
    evaluator_capability_manifest_identity: str
    model_build_receipt_identity: str
    experiment_outcome_receipt_identity: str


_EVIDENCE_REFUSAL_REASONS = (
    *EXPERIMENT_CHECK_REFUSAL_REASONS,
    "evaluation.reason.evaluable-cyclic-prerequisite",
    "evaluation.reason.evaluable-extra-prerequisite",
    "evaluation.reason.evaluable-ineligible-outcome",
    "evaluation.reason.evaluable-mismatched-prerequisite",
    "evaluation.reason.evaluable-missing-prerequisite",
    "evaluation.reason.evaluable-unresolved-prerequisite",
    "evaluation.reason.unknown-evidence-claim-kind",
)


def _refusal_catalog() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            set(BOOTSTRAP_REFUSAL_CATALOG)
            | set(MODEL_REFUSAL_CATALOG)
            | set(refusal_catalog_for_reasons(_EVIDENCE_REFUSAL_REASONS))
        )
    )


def _outcome_artifact_sets():
    return (
        EXPERIMENT_RUN.artifact_set,
        EXPERIMENT_RUN.verdict_artifact_set,
        *(item.members for item in EXPERIMENT_RUN.refusal_artifact_sets),
    )


def run_evidence_verify(
    inp: EvidenceVerifyInput,
) -> EvidenceVerifyResult | Schema2RefusalReport:
    try:
        result = verify_evidence(
            ApplicationInput(
                claim_kind=inp.claim_kind,
                source=inp.source,
                specification=inp.specification,
                model_build_receipt=inp.model_build_receipt,
                experiment_outcome_receipt=inp.experiment_outcome_receipt,
            ),
            model_build_descriptor_identity=descriptor_identity(MODEL_BUILD),
            experiment_run_descriptor_identity=descriptor_identity(EXPERIMENT_RUN),
            model_build_artifact_set=MODEL_BUILD.artifact_set,
            experiment_outcome_artifact_sets=_outcome_artifact_sets(),
        )
    except InputReadError as err:
        raise UnreadableInputError("cannot read an Evidence input document") from err
    if isinstance(result, Schema2RefusalReport):
        return result
    assert isinstance(result, EvidenceCandidate)
    identities = {subject.role: subject.identity for subject in result.subjects}
    return EvidenceVerifyResult(
        claim_kind=result.claim_kind,
        claim_state=result.claim_state,
        producing_outcome=result.producing_outcome,
        kernel_identity=identities["kernel"],
        language_bundle_identity=identities["language-bundle"],
        model_source_identity=identities["model-source"],
        resolved_model_identity=identities["resolved-model"],
        experiment_identity=identities["experiment"],
        resolved_runtime_profile_identity=identities["resolved-runtime-profile"],
        evaluator_capability_manifest_identity=identities[
            "evaluator-capability-manifest"
        ],
        model_build_receipt_identity=identities["model-build-receipt"],
        experiment_outcome_receipt_identity=identities["experiment-outcome-receipt"],
    )


def _prepare_evidence_args(root: Path, token: int, refusing: bool) -> tuple[str, ...]:
    specification_path = root / f"evidence-experiment-{token}.json"
    specification_path.write_text(
        prepare_valid_experiment(root, token), encoding="utf-8"
    )
    outcome = run_experiment_run(
        ExperimentRunInput(
            specification=str(specification_path),
            out=str(root / f"evidence-outcome-{token}.json"),
            invocation_key=f"{token:064x}",
        )
    )
    if not isinstance(outcome, ExperimentRunResult):
        raise RuntimeError("Evidence fixture prerequisite run did not succeed")
    outcome_receipt_path = root / f"evidence-outcome-{token}-receipt.json"
    outcome_receipt_path.write_bytes(
        canonical_bytes(cast(JsonValue, outcome.model_dump(mode="json")))
    )
    return (
        "--claim-kind",
        "unsupported" if refusing else "evaluable",
        "--source",
        str(root / f"experiment-model-{token}.json"),
        "--specification",
        str(specification_path),
        "--model-build-receipt",
        str(root / f"experiment-model-{token}-receipt.json"),
        "--experiment-outcome-receipt",
        str(outcome_receipt_path),
    )


EVIDENCE_VERIFY = CommandDescriptor(
    group="evidence",
    command="verify",
    description="Verify one exact Evidence prerequisite graph.",
    input_model=EvidenceVerifyInput,
    output_model=EvidenceVerifyResult,
    handler=run_evidence_verify,
    fixtures=ConformanceFixtures(prepare_args=_prepare_evidence_args),
    schema_major=2,
    structured_params=True,
    refusal_catalog_provider=_refusal_catalog,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
