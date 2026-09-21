"""Schema 2.0 Evidence candidate verification."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.application.evidence_verify as evidence_verify_module
from gda_balancing.application.evidence_verify import (
    EvidenceVerifyInput,
    verify_evidence,
)
from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.application.experiment_run import (
    ExperimentRunPublication,
    ExperimentVerdictPublication,
    run_experiment,
)
from gda_balancing.domain.artifacts import (
    artifacts_by_protocol_role,
    identified_artifact,
    verify_artifact,
    wire_schema_identity,
)
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.artifact_set import resolve_artifact_set
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2RefusalReport,
    reason_by_id,
)
from gda_balancing.domain.evidence_verification import (
    EvidenceCandidate,
    evidence_outcome_mismatch_refusal,
    evaluate_evidence_candidate,
)
from gda_balancing.domain.publication import (
    select_publication_contracts,
    publish_artifact_set,
    read_authenticated_artifact_set,
    read_authenticated_declared_artifact_set,
)
from gda_balancing.domain.publication_types import PublicationMember
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_runtime_refusal_experiment,
    prepare_valid_experiment,
    prepare_verdict_experiment,
)
from gda_balancing.interfaces.cli.descriptors import artifact_sets_for_input
from gda_balancing.interfaces.cli.evidence_verify import EVIDENCE_VERIFY
from gda_balancing.interfaces.cli.experiment_run import EXPERIMENT_RUN
from gda_balancing.interfaces.cli.surface import descriptor_identity


def _verify(inp: EvidenceVerifyInput) -> EvidenceCandidate | Schema2RefusalReport:
    inputs = {item.receipt_field: item for item in EVIDENCE_VERIFY.input_artifact_sets}
    experiment_run_input = inputs["experiment_run_artifact_set_receipt"]
    return verify_evidence(
        inp,
        experiment_run_artifact_sets=artifact_sets_for_input(experiment_run_input),
    )


def _prepare_outcome_input(
    tmp_path: Path,
    token: int,
    *,
    verdict: bool = False,
    original_descriptor: str | None = None,
) -> EvidenceVerifyInput:
    prepare = prepare_verdict_experiment if verdict else prepare_valid_experiment
    fixture = prepare(tmp_path, token)
    specification_path = tmp_path / "experiment.json"
    specification_path.write_text(fixture.specification, encoding="utf-8")
    outcome_path = tmp_path / "experiment-outcome.json"
    run_receipt_path = tmp_path / "experiment-run-artifact-set-receipt.json"
    publication = run_experiment(
        str(specification_path),
        str(outcome_path),
        "e" * 64,
        original_descriptor or descriptor_identity(EXPERIMENT_RUN),
        EXPERIMENT_RUN.artifact_set,
        cast(tuple[Any, ...], EXPERIMENT_RUN.verdict_artifact_set),
        EXPERIMENT_RUN.refusal_artifact_sets[0].members,
        rir=fixture.rir,
    )
    expected_type = (
        ExperimentVerdictPublication if verdict else ExperimentRunPublication
    )
    assert isinstance(publication, expected_type)
    run_receipt_path.write_bytes(canonical_bytes(cast(JsonValue, publication.receipt)))
    return EvidenceVerifyInput(
        claim_kind="evaluable",
        rir=fixture.rir,
        specification=str(specification_path),
        experiment_run_artifact_set_receipt=str(run_receipt_path),
    )


def test_packaged_ldb_owns_the_evaluable_eligibility_policy() -> None:
    language = packaged_authority_context().language_bundle["language"]
    assert language["evidence_claim_kinds"] == [
        {
            "id": "evaluable",
            "eligibility": {
                "claim_state": "candidate",
                "runtime_dispatch": "required",
                "producing_outcomes": ["runtime-refusal", "success", "verdict"],
                "runtime_refusal_variant": "post-dispatch",
            },
            "vectors": [
                {
                    "id": "evaluable." + suffix,
                    "kind": kind,
                    "input": {
                        "producing_outcome": outcome,
                        "runtime_dispatch": dispatch,
                        "runtime_refusal_variant": variant,
                    },
                    "expect": expect,
                }
                for suffix, kind, outcome, dispatch, variant, expect in (
                    (
                        "success",
                        "positive",
                        "success",
                        "reached",
                        "not-applicable",
                        "candidate",
                    ),
                    (
                        "verdict",
                        "positive",
                        "verdict",
                        "reached",
                        "not-applicable",
                        "candidate",
                    ),
                    (
                        "runtime-refusal",
                        "positive",
                        "runtime-refusal",
                        "reached",
                        "post-dispatch",
                        "candidate",
                    ),
                    (
                        "pre-dispatch",
                        "negative",
                        "runtime-refusal",
                        "not-reached",
                        "pre-dispatch",
                        "refusal",
                    ),
                )
            ],
        }
    ]


def test_domain_reports_complete_outcome_mismatch_at_the_receipt() -> None:
    context = packaged_authority_context()
    receipt_identity = "sha256:" + "a" * 64
    result = evidence_outcome_mismatch_refusal(
        context.language_bundle, receipt_identity
    )
    assert result.stage == "evaluation"
    assert result.truncated is False
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "evaluation.evaluable_outcome_mismatch"
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.content_identity == receipt_identity
    assert (
        result.diagnostics[0].primary.pointer == "/experiment-run-artifact-set-receipt"
    )


def test_evaluable_faults_use_ldb_owned_evaluation_reasons() -> None:
    language_bundle = packaged_authority_context().language_bundle

    for suffix in (
        "ineligible-outcome",
        "outcome-mismatch",
    ):
        reason = reason_by_id(
            language_bundle,
            f"evaluation.reason.evaluable-{suffix}",
        )
        assert reason["stage"] == "evaluation"
        assert reason["diagnostic"] == "evaluation.evaluable_" + suffix.replace(
            "-", "_"
        )


def test_application_verifies_one_real_success_publication(
    tmp_path: Path,
) -> None:
    result = _verify(_prepare_outcome_input(tmp_path, 541))

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_kind == "evaluable"
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "success"


def test_application_authenticates_the_original_run_descriptor(tmp_path: Path) -> None:
    original_descriptor = "sha256:" + "9" * 64
    assert original_descriptor != descriptor_identity(EXPERIMENT_RUN)
    inp = _prepare_outcome_input(tmp_path, 557, original_descriptor=original_descriptor)
    receipt = json.loads(Path(inp.experiment_run_artifact_set_receipt).read_text())
    assert receipt["descriptor_identity"] == original_descriptor

    result = _verify(inp)

    assert isinstance(result, EvidenceCandidate)
    assert result.producing_outcome == "success"
    assert result.claim_state == "candidate"


@pytest.mark.parametrize("error_type", (RuntimeError, ValueError))
def test_application_does_not_relabel_an_unexpected_experiment_validation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    inp = _prepare_outcome_input(tmp_path, 551)

    def fail_unexpectedly(*_args, **_kwargs) -> None:
        raise error_type("unexpected Experiment validator defect")

    monkeypatch.setattr(
        evidence_verify_module,
        "check_experiment_inputs",
        fail_unexpectedly,
    )

    with pytest.raises(
        error_type,
        match="unexpected Experiment validator defect",
    ):
        _verify(inp)


def test_application_refuses_a_different_admitted_rir(tmp_path: Path) -> None:
    inp = _prepare_outcome_input(tmp_path, 552)
    different = prepare_runtime_refusal_experiment(tmp_path, 553)

    result = _verify(replace(inp, rir=different.rir))

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "resolution"
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "language.resolved_authority_mismatch"
    ]
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.pointer == "/model/rir_semantic_identity"


def test_application_uses_outcome_neutral_publication_diagnostics(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 542)
    invalid_receipt = tmp_path / "invalid-experiment-run-artifact-set-receipt.json"
    invalid_receipt.write_text("not JSON", encoding="utf-8")

    result = _verify(
        replace(inp, experiment_run_artifact_set_receipt=str(invalid_receipt))
    )

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "ingress"
    assert result.diagnostics[0].message == (
        "Artifact-set receipt is not an admissible JSON artifact"
    )


def test_application_reports_a_malformed_input_before_an_unknown_claim_kind(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 553)
    invalid_receipt = tmp_path / "invalid-experiment-run-artifact-set-receipt.json"
    invalid_receipt.write_text("not JSON", encoding="utf-8")

    result = _verify(
        replace(
            inp,
            claim_kind="unsupported",
            experiment_run_artifact_set_receipt=str(invalid_receipt),
        )
    )

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "ingress"
    assert result.diagnostics[0].code == "kernel.identity_mismatch"


def test_application_refuses_an_unknown_evidence_claim_kind(tmp_path: Path) -> None:
    inp = _prepare_outcome_input(tmp_path, 543)

    result = _verify(replace(inp, claim_kind="unsupported"))

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert result.diagnostics[0].code == "evaluation.unknown_evidence_claim_kind"
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.pointer == "/claim_kind"


def test_application_does_not_require_source_or_build_receipt(tmp_path: Path) -> None:
    inp = _prepare_outcome_input(tmp_path, 546)
    (tmp_path / "experiment-model-546.json").unlink()
    (tmp_path / "experiment-model-546-receipt.json").unlink()

    result = _verify(inp)

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_state == "candidate"
    assert {name for name in vars(result) if name.endswith("_identity")} == {
        "rir_semantic_identity",
        "experiment_identity",
        "resolved_runtime_profile_identity",
        "evaluator_capability_manifest_identity",
        "experiment_run_artifact_set_receipt_identity",
    }


def test_application_refuses_an_unauthenticated_experiment_run_artifact_set_receipt(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 547)
    receipt_path = Path(inp.experiment_run_artifact_set_receipt)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["content_identity"] = "sha256:" + "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "ingress"
    assert result.diagnostics[0].code == "kernel.identity_mismatch"
    assert result.diagnostics[0].message == (
        "Artifact-set receipt failed exact-authority admission"
    )


def _assert_corrupted_run_member_preserves_admission_diagnostic(
    inp: EvidenceVerifyInput,
    logical_name: str,
) -> None:
    receipt = json.loads(
        Path(inp.experiment_run_artifact_set_receipt).read_text(encoding="utf-8")
    )
    member_path = next(
        item["locator"]
        for item in receipt["member_locators"]
        if item["logical_name"] == logical_name
    )
    Path(member_path).write_text("{}", encoding="utf-8")

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "ingress"
    assert result.diagnostics[0].code == "kernel.binding_mismatch"
    assert isinstance(result.diagnostics[0].primary, ArtifactLocation)
    assert result.diagnostics[0].primary.pointer == f"/{logical_name}"


def test_application_preserves_the_success_member_admission_diagnostic(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 554)
    _assert_corrupted_run_member_preserves_admission_diagnostic(
        inp,
        "evaluation-run",
    )


def test_application_refuses_an_outcome_bound_to_another_experiment(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 548)
    specification_path = Path(inp.specification)
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    specification["metrics"][0]["target"]["maximum"] = 999
    specification_path.write_text(json.dumps(specification), encoding="utf-8")

    result = _verify(inp)

    assert isinstance(result, Schema2RefusalReport)
    assert result.stage == "evaluation"
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "evaluation.evaluable_outcome_mismatch"
    }
    artifact_locations = {
        diagnostic.primary.pointer
        for diagnostic in result.diagnostics
        if isinstance(diagnostic.primary, ArtifactLocation)
    }
    assert "/experiment-run-artifact-set-receipt" in (artifact_locations)


def test_application_verifies_one_real_verdict_publication(tmp_path: Path) -> None:
    result = _verify(_prepare_outcome_input(tmp_path, 544, verdict=True))

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "verdict"


def test_application_preserves_the_verdict_member_admission_diagnostic(
    tmp_path: Path,
) -> None:
    inp = _prepare_outcome_input(tmp_path, 555, verdict=True)
    _assert_corrupted_run_member_preserves_admission_diagnostic(
        inp,
        "experiment-verdict",
    )


def _prepare_runtime_refusal_input(tmp_path: Path, token: int) -> EvidenceVerifyInput:
    fixture = prepare_runtime_refusal_experiment(tmp_path, token)
    specification_path = tmp_path / "experiment.json"
    specification_path.write_text(fixture.specification, encoding="utf-8")
    run_receipt_path = tmp_path / "experiment-run-artifact-set-receipt.json"
    refusal = run_experiment(
        str(specification_path),
        str(tmp_path / "runtime-refusal.json"),
        "f" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        EXPERIMENT_RUN.artifact_set,
        cast(tuple[Any, ...], EXPERIMENT_RUN.verdict_artifact_set),
        EXPERIMENT_RUN.refusal_artifact_sets[0].members,
        rir=fixture.rir,
    )
    assert isinstance(refusal, Schema2RefusalReport)
    assert refusal.variant == "post-dispatch"
    assert refusal.terminal_audit is not None
    run_receipt_path.write_bytes(
        canonical_bytes(cast(JsonValue, refusal.terminal_audit))
    )
    return EvidenceVerifyInput(
        claim_kind="evaluable",
        rir=fixture.rir,
        specification=str(specification_path),
        experiment_run_artifact_set_receipt=str(run_receipt_path),
    )


def test_application_verifies_one_real_post_dispatch_refusal_publication(
    tmp_path: Path,
) -> None:
    result = _verify(_prepare_runtime_refusal_input(tmp_path, 545))

    assert isinstance(result, EvidenceCandidate)
    assert result.claim_state == "candidate"
    assert result.producing_outcome == "runtime-refusal"


def test_application_preserves_the_runtime_refusal_member_admission_diagnostic(
    tmp_path: Path,
) -> None:
    inp = _prepare_runtime_refusal_input(tmp_path, 556)
    _assert_corrupted_run_member_preserves_admission_diagnostic(
        inp,
        "runtime-terminal-audit",
    )


def test_public_cli_refuses_an_authenticated_incomplete_terminal_audit(
    tmp_path: Path,
    run_cli,
) -> None:
    inp = _prepare_runtime_refusal_input(tmp_path, 550)
    artifact_set = EXPERIMENT_RUN.refusal_artifact_sets[0].members
    admitted = read_authenticated_artifact_set(
        inp.experiment_run_artifact_set_receipt,
        descriptor_identity(EXPERIMENT_RUN),
        artifact_set,
        authority_context=packaged_authority_context(),
    )
    values = deepcopy(admitted.artifacts)
    audit = values["runtime-terminal-audit"]
    audit_payload = {
        key: value
        for key, value in audit.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    audit_payload["last_snapshot_identity"] = "sha256:" + "0" * 64
    values["runtime-terminal-audit"] = cast(
        dict[str, Any],
        identified_artifact(
            admitted.authority_context.language_bundle,
            "runtime-terminal-audit",
            cast(dict[str, JsonValue], audit_payload),
        ),
    )
    members = {
        name: PublicationMember(
            value=value,
            artifact_kind=cast(str, value["artifact_kind"]),
            wire_schema_identity=wire_schema_identity(
                admitted.authority_context.language_bundle,
                cast(str, value["artifact_kind"]),
            ),
            content_identity=cast(str, value["content_identity"]),
        )
        for name, value in values.items()
    }
    malformed_receipt = publish_artifact_set(
        members,
        str(tmp_path / "malformed-runtime-refusal.json"),
        "a" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        "sha256:" + "1" * 64,
        select_publication_contracts(admitted.authority_context.language_bundle),
        resolve_artifact_set(admitted.authority_context.language_bundle, artifact_set),
        lambda _name, value: verify_artifact(
            value, admitted.authority_context.language_bundle
        ),
    )
    malformed_receipt_path = tmp_path / "malformed-runtime-refusal-receipt.json"
    malformed_receipt_path.write_bytes(
        canonical_bytes(cast(JsonValue, malformed_receipt))
    )

    exit_code, stdout, stderr = run_cli(
        [
            "evidence",
            "verify",
            "--claim-kind",
            "evaluable",
            "--rir",
            inp.rir,
            "--specification",
            inp.specification,
            "--experiment-run-artifact-set-receipt",
            str(malformed_receipt_path),
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.evaluable_outcome_mismatch"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/experiment-run-artifact-set-receipt"
    )


@pytest.fixture
def admitted_fold_outcome(tmp_path, run_cli):
    example = Path(__file__).parents[1] / "examples/schema2/bounded-fold"
    code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(example / "model-source.json"),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "d1" * 32,
        ]
    )
    assert (code, stderr) == (0, ""), stdout
    build = json.loads(stdout)
    rir_path = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = example / "experiment.json"
    code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--rir",
            rir_path,
            "--out",
            str(tmp_path / "run"),
            "--invocation-key",
            "d2" * 32,
        ]
    )
    assert (code, stderr) == (0, ""), stdout
    receipt_path = tmp_path / "run-receipt.json"
    receipt_path.write_text(stdout)
    inp = EvidenceVerifyInput(
        "evaluable", rir_path, str(specification), str(receipt_path)
    )
    context = packaged_authority_context()
    checked = check_experiment_inputs(
        inp.specification, inp.rir, authority_context=context
    )
    assert isinstance(checked, CheckedExperiment)
    publication = read_authenticated_declared_artifact_set(
        inp.experiment_run_artifact_set_receipt,
        artifact_sets_for_input(EVIDENCE_VERIFY.input_artifact_sets[0]),
        authority_context=context,
    )
    assert validate_experiment_artifact_set(checked, publication.artifacts)
    return inp, checked, publication


def test_candidate_keeps_the_five_actual_admitted_identities(admitted_fold_outcome):
    inp, checked, publication = admitted_fold_outcome
    candidate = _verify(inp)
    assert isinstance(candidate, EvidenceCandidate)
    members = artifacts_by_protocol_role(checked.language_bundle, publication.artifacts)
    assert vars(candidate) == {
        "claim_kind": "evaluable",
        "claim_state": "candidate",
        "producing_outcome": "success",
        "rir_semantic_identity": checked.rir["semantic_identity"],
        "experiment_identity": checked.content_identity,
        "resolved_runtime_profile_identity": members["resolved-runtime-profile"][
            "content_identity"
        ],
        "evaluator_capability_manifest_identity": members[
            "evaluator-capability-manifest"
        ]["content_identity"],
        "experiment_run_artifact_set_receipt_identity": publication.receipt[
            "content_identity"
        ],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "extra",
        "profile-experiment",
        "profile-rir",
        "primary-experiment",
        "primary-profile",
        "evaluator-capability",
    ],
)
def test_real_outcome_integrity_replaces_the_retired_graph_obligations(
    admitted_fold_outcome, mutation
):
    _, checked, publication = admitted_fold_outcome
    artifacts = deepcopy(publication.artifacts)
    members = artifacts_by_protocol_role(checked.language_bundle, artifacts)
    if mutation == "missing":
        key = next(
            k for k, value in artifacts.items() if value is members["event-trace"]
        )
        del artifacts[key]
    elif mutation == "duplicate":
        artifacts["duplicate-profile"] = deepcopy(members["resolved-runtime-profile"])
    elif mutation == "extra":
        artifacts["unrelated-receipt"] = deepcopy(publication.receipt)
    else:
        role, field = {
            "profile-experiment": ("resolved-runtime-profile", "experiment_identity"),
            "profile-rir": ("resolved-runtime-profile", "rir_semantic_identity"),
            "primary-experiment": ("evaluation-run", "experiment_identity"),
            "primary-profile": ("evaluation-run", "resolved_runtime_profile_identity"),
            "evaluator-capability": (
                "evaluator-capability-manifest",
                "instruction_nodes",
            ),
        }[mutation]
        changed = deepcopy(members[role])
        if mutation == "evaluator-capability":
            assert "list-append" in changed[field]
            changed[field].remove("list-append")
        else:
            changed[field] = "sha256:" + "0" * 64
        contract = checked.output_contracts[role]
        changed = contract.identify(
            {
                k: value
                for k, value in changed.items()
                if k
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
        )
        assert contract.verify(changed)
        assert changed["content_identity"] != members[role]["content_identity"]
        key = next(k for k, value in artifacts.items() if value is members[role])
        artifacts[key] = changed
    assert not validate_experiment_artifact_set(checked, artifacts)


def test_application_checks_complete_outcome_before_eligibility(
    admitted_fold_outcome, tmp_path, monkeypatch
):
    inp, _, _ = admitted_fold_outcome
    evaluate = evaluate_evidence_candidate
    called = []

    def observe(claim, checked, publication):
        assert validate_experiment_artifact_set(checked, publication.artifacts)
        called.append(publication.receipt["content_identity"])
        return evaluate(claim, checked, publication)

    monkeypatch.setattr(evidence_verify_module, "evaluate_evidence_candidate", observe)
    assert isinstance(_verify(inp), EvidenceCandidate)
    assert len(called) == 1
    different = json.loads(Path(inp.specification).read_bytes())
    different["metrics"][0]["target"]["maximum"] += 1
    path = tmp_path / "different-experiment.json"
    path.write_text(json.dumps(different))
    result = _verify(replace(inp, specification=str(path)))
    assert isinstance(result, Schema2RefusalReport)
    assert [d.code for d in result.diagnostics] == [
        "evaluation.evaluable_outcome_mismatch"
    ]
    assert len(called) == 1
