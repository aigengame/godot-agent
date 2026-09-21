"""Replay keeps original authentication while discarding producer eligibility."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import cast

import pytest

from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.domain.artifact_set import (
    EXPERIMENT_SUCCESS_ARTIFACT_SET,
    resolve_artifact_set,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.experiment_artifacts import (
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.publication import (
    publish_artifact_set,
    read_authenticated_artifact_set,
    read_authenticated_declared_artifact_set,
    select_publication_contracts,
)
from gda_balancing.domain.publication_types import PublicationAdmissionError
from gda_balancing.interfaces.cli.experiment_run import EXPERIMENT_RUN
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_runtime_refusal_experiment,
)
from gda_balancing.interfaces.cli.surface import descriptor_identity
from test_schema2_comparison import (
    _artifact_payload,
    _authority_context,
    _member,
    _published_original_run,
    _replay_argv,
)


def _original(tmp_path: Path, run_cli):
    specification, receipt_path, rir = _published_original_run(tmp_path, run_cli)
    checked = check_experiment_inputs(str(specification), rir)
    assert isinstance(checked, CheckedExperiment), checked
    original = read_authenticated_declared_artifact_set(
        str(receipt_path),
        (EXPERIMENT_SUCCESS_ARTIFACT_SET,),
        authority_context=_authority_context(checked),
    )
    return specification, receipt_path, rir, checked, original


@pytest.mark.parametrize("change", ["descriptor", "producer", "both"])
def test_public_replay_accepts_authenticated_provenance_only_changes(
    tmp_path: Path, run_cli, change: str
):
    specification, _receipt_path, rir, checked, original = _original(tmp_path, run_cli)
    members = {
        name: _member(checked, name, _artifact_payload(value))
        for name, value in original.artifacts.items()
    }
    original_semantics = {
        name: member.content_identity
        for name, member in members.items()
        if name != "evaluator-capability-manifest"
    }
    producer_identity = members["evaluator-capability-manifest"].content_identity
    if change in {"producer", "both"}:
        payload = _artifact_payload(members["evaluator-capability-manifest"].value)
        payload["implementation"] += ".previous-producer"
        payload["evaluator_build_identity"] = "sha256:" + "7" * 64
        payload["platform"] = {
            **payload["platform"],
            "python": "previous-python-build",
        }
        members["evaluator-capability-manifest"] = _member(
            checked, "evaluator-capability-manifest", payload
        )
        assert (
            members["evaluator-capability-manifest"].content_identity
            != producer_identity
        )
    current_descriptor = descriptor_identity(EXPERIMENT_RUN)
    producer_descriptor = (
        descriptor_identity(
            replace(EXPERIMENT_RUN, description="Earlier run command documentation.")
        )
        if change in {"descriptor", "both"}
        else current_descriptor
    )
    assert validate_experiment_artifact_set(
        checked, {name: member.value for name, member in members.items()}
    )
    receipt = publish_artifact_set(
        members,
        str(tmp_path / "previous-producer.json"),
        "1" * 64,
        producer_descriptor,
        checked.content_identity,
        select_publication_contracts(checked.language_bundle),
        resolve_artifact_set(checked.language_bundle, EXPERIMENT_SUCCESS_ARTIFACT_SET),
        lambda name, value: validate_experiment_member(checked, name, value),
        artifact_set_validator=lambda values: validate_experiment_artifact_set(
            checked, values
        ),
    )
    assert receipt["content_identity"] != original.receipt["content_identity"]
    prior_receipt = tmp_path / "previous-producer-receipt.json"
    prior_receipt.write_bytes(canonical_bytes(receipt))
    if change in {"descriptor", "both"}:
        assert receipt["descriptor_identity"] != current_descriptor
        # The separate exact-producer API still enforces an explicitly requested
        # Build/producer descriptor after authenticating the original record.
        with pytest.raises(PublicationAdmissionError, match="another command"):
            read_authenticated_artifact_set(
                str(prior_receipt),
                current_descriptor,
                resolve_artifact_set(
                    checked.language_bundle, EXPERIMENT_SUCCESS_ARTIFACT_SET
                ),
                authority_context=_authority_context(checked),
            )
    out = tmp_path / "replay.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, prior_receipt, rir, out)
    )
    assert (exit_code, stderr) == (0, ""), stdout
    comparison = json.loads(out.read_bytes())
    assert comparison["result"] == "matched"
    assert all(row["match"] for row in comparison["checks"])
    assert (
        comparison["original_evaluation_run_identity"]
        == original_semantics["evaluation-run"]
    )
    replay_receipt = json.loads(stdout)["artifact_set"]
    replay_members = {
        row["logical_name"]: json.loads(Path(row["locator"]).read_bytes())
        for row in replay_receipt["member_locators"]
    }
    assert {
        name: replay_members[name]["content_identity"] for name in original_semantics
    } == original_semantics
    if change in {"producer", "both"}:
        assert (
            replay_members["evaluator-capability-manifest"]["content_identity"]
            != members["evaluator-capability-manifest"].content_identity
        )


@pytest.mark.parametrize(
    "tamper", ["descriptor", "member", "reidentified-member", "wire-schema"]
)
def test_public_replay_authenticates_original_before_explicit_inputs(
    tmp_path: Path, run_cli, tamper: str
):
    specification, receipt_path, rir, checked, original = _original(tmp_path, run_cli)
    receipt = deepcopy(original.receipt)
    if tamper == "descriptor":
        payload = _artifact_payload(receipt)
        payload["descriptor_identity"] = "sha256:" + "8" * 64
        receipt = select_publication_contracts(
            checked.language_bundle
        ).receipt.identify(payload)
        receipt_path.write_bytes(canonical_bytes(cast(JsonValue, receipt)))
    else:
        row = next(
            row
            for row in receipt["member_locators"]
            if row["logical_name"] == "evaluator-capability-manifest"
        )
        member_path = Path(row["locator"])
        member = deepcopy(original.artifacts["evaluator-capability-manifest"])
        if tamper == "wire-schema":
            member["wire_schema_identity"] = "sha256:" + "9" * 64
        else:
            member["implementation"] += ".tampered"
            if tamper == "reidentified-member":
                member = _member(
                    checked, "evaluator-capability-manifest", _artifact_payload(member)
                ).value
        member_path.write_bytes(canonical_bytes(cast(JsonValue, member)))
    # Both explicit inputs are unreadable: original publication admission must
    # nevertheless fail first, without falling through to RIR ingress.
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(
            specification.with_name("missing-experiment.json"),
            receipt_path,
            rir + ".missing",
            out,
        )
    )
    assert (exit_code, stderr) == (2, ""), stdout
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert error["diagnostics"][0]["code"] == "kernel.binding_mismatch"
    assert not out.exists()


def test_public_replay_refuses_authenticated_undeclared_member_sets(
    tmp_path: Path, run_cli
):
    specification, _receipt_path, rir, checked, original = _original(tmp_path, run_cli)
    # This is a genuinely authenticated publication with intact member bytes;
    # its missing Snapshot member violates Replay's declared input set.
    incomplete_set = tuple(
        member
        for member in resolve_artifact_set(
            checked.language_bundle, EXPERIMENT_SUCCESS_ARTIFACT_SET
        )
        if member.logical_name != "snapshot-series"
    )
    members = {
        member.logical_name: _member(
            checked,
            member.logical_name,
            _artifact_payload(original.artifacts[member.logical_name]),
        )
        for member in incomplete_set
    }
    receipt = publish_artifact_set(
        members,
        str(tmp_path / "incomplete.json"),
        "2" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        checked.content_identity,
        select_publication_contracts(checked.language_bundle),
        incomplete_set,
        lambda name, value: validate_experiment_member(checked, name, value),
    )
    receipt_path = tmp_path / "incomplete-receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt))
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, receipt_path, rir, out)
    )
    assert (exit_code, stderr) == (2, ""), stdout
    assert (
        json.loads(stdout)["error"]["diagnostics"][0]["code"]
        == "kernel.member_set_mismatch"
    )
    assert not out.exists()


@pytest.mark.parametrize("change", ["seed", "assignment", "priority"])
def test_public_replay_refuses_changed_admitted_execution_intent_before_dispatch(
    tmp_path: Path, run_cli, monkeypatch, change: str
):
    import gda_balancing.application.experiment_replay as replay_application

    specification, receipt_path, rir, _checked, _original_value = _original(
        tmp_path, run_cli
    )
    value = json.loads(specification.read_bytes())
    if change == "seed":
        value["seed"]["value"] += 1
    elif change == "assignment":
        value["scenarios"][0]["assignments"][0]["value"] += 1
    else:
        value["scenarios"][0]["event_plan"][0]["priority"] += 1
    changed = tmp_path / "changed-experiment.json"
    changed.write_bytes(canonical_bytes(cast(JsonValue, value)))
    assert isinstance(check_experiment_inputs(str(changed), rir), CheckedExperiment)

    def dispatch_must_not_run(_prepared):
        raise AssertionError("different execution intent reached Replay dispatch")

    monkeypatch.setattr(
        replay_application, "execute_prepared_experiment", dispatch_must_not_run
    )
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(_replay_argv(changed, receipt_path, rir, out))
    assert (exit_code, stderr) == (2, ""), stdout
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert error["diagnostics"][0]["code"] == "evaluation.replay_reproduction_mismatch"
    assert not out.exists()


def test_public_replay_refuses_an_explicit_different_program_before_dispatch(
    tmp_path: Path, run_cli, monkeypatch
):
    import gda_balancing.application.experiment_replay as replay_application

    specification, receipt_path, rir, _checked, _original_value = _original(
        tmp_path, run_cli
    )
    different_root = tmp_path / "different-program"
    different_root.mkdir()
    different = prepare_runtime_refusal_experiment(different_root, 549)
    assert (
        json.loads(Path(different.rir).read_bytes())["semantic_identity"]
        != (json.loads(Path(rir).read_bytes())["semantic_identity"])
    )

    def dispatch_must_not_run(_prepared):
        raise AssertionError("different explicit program reached Replay dispatch")

    monkeypatch.setattr(
        replay_application, "execute_prepared_experiment", dispatch_must_not_run
    )
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, receipt_path, different.rir, out)
    )
    assert (exit_code, stderr) == (2, ""), stdout
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert error["diagnostics"][0]["code"] == "language.resolved_authority_mismatch"
    assert error["diagnostics"][0]["message"] == (
        "Experiment Specification does not bind the admitted RIR semantics"
    )
    assert (
        error["diagnostics"][0]["primary"]["pointer"] == "/model/rir_semantic_identity"
    )
    assert not out.exists()


def test_public_replay_refuses_an_authenticated_incapable_original_producer(
    tmp_path: Path, run_cli, monkeypatch
):
    import gda_balancing.application.experiment_replay as replay_application

    specification, _receipt_path, rir, checked, original = _original(tmp_path, run_cli)
    members = {
        name: _member(checked, name, _artifact_payload(value))
        for name, value in original.artifacts.items()
    }
    payload = _artifact_payload(members["evaluator-capability-manifest"].value)
    payload["numeric_policies"] = ["unsupported-number-system"]
    members["evaluator-capability-manifest"] = _member(
        checked, "evaluator-capability-manifest", payload
    )
    assert validate_experiment_member(
        checked,
        "evaluator-capability-manifest",
        members["evaluator-capability-manifest"].value,
    )
    assert not validate_experiment_artifact_set(
        checked, {name: member.value for name, member in members.items()}
    )
    # Authenticate intact candidate bytes, without claiming semantic admission.
    # Replay must independently reject the producer's insufficient capabilities.
    receipt = publish_artifact_set(
        members,
        str(tmp_path / "incapable.json"),
        "3" * 64,
        descriptor_identity(EXPERIMENT_RUN),
        checked.content_identity,
        select_publication_contracts(checked.language_bundle),
        resolve_artifact_set(checked.language_bundle, EXPERIMENT_SUCCESS_ARTIFACT_SET),
        lambda name, value: validate_experiment_member(checked, name, value),
    )
    receipt_path = tmp_path / "incapable-receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt))

    def dispatch_must_not_run(_prepared):
        raise AssertionError("incapable original producer reached Replay dispatch")

    monkeypatch.setattr(
        replay_application, "execute_prepared_experiment", dispatch_must_not_run
    )
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, receipt_path, rir, out)
    )
    assert (exit_code, stderr) == (2, ""), stdout
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert error["diagnostics"][0]["code"] == "evaluation.replay_reproduction_mismatch"
    assert not out.exists()
