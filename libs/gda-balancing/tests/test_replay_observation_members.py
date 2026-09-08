"""Exact Replay compares the declared observation members without spelling aliases."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.comparison import (
    compare_exact_replay,
    select_exact_replay_contract,
    validate_exact_replay_comparison,
    validate_published_exact_replay_comparison,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_comparison import (
    _artifact_payload,
    accepted_execution as accepted_execution,
)
from test_schema2_model_lowerer_conformance import _reidentify_language_bundle

_MEMBERS = [
    "evaluation_outcome_status",
    "event_trace_identity",
    "snapshot_series_identity",
    "metric_dataset_identity",
]


def test_replay_policy_directly_references_the_complete_kernel_observation():
    kernel, language = mutable_authorities()
    kind = next(
        row
        for row in kernel["meta_format"]["package_vector"]["kinds"]
        if row["id"] == "replay-comparison"
    )
    assert kind["observation_members"] == _MEMBERS
    policy = language["language"]["replay_comparison_policies"][0]
    assert policy == {
        "id": "exact-replay-v1",
        "comparator": "canonical-equal",
        "checks": _MEMBERS,
    }
    assert isinstance(
        admit_authority_context(kernel, language), AdmittedAuthorityContext
    )
    assert _consumer_b(kernel, language)["admitted"]


@pytest.mark.parametrize(
    "change", ["alias", "missing", "duplicate", "reordered", "foreign"]
)
def test_resealed_replay_policy_cannot_change_observation_members(change):
    kernel, language = mutable_authorities()
    checks = _MEMBERS[:]
    if change == "alias":
        checks = [member.replace("_", "-") for member in checks]
    elif change == "missing":
        checks.pop()
    elif change == "duplicate":
        checks[-1] = checks[0]
    elif change == "reordered":
        checks.reverse()
    else:
        checks[-1] = "unrelated_observation"
    language["language"]["replay_comparison_policies"][0]["checks"] = checks
    # Coherently change the evidence keys too: refusal cannot rely on stale hashes
    # or on a mismatch between an authored policy and its authored vector labels.
    for vector in language["vectors"]:
        if vector.get("kind") == "replay-comparison":
            vector["expect"]["checks"] = [
                {**row, "key": key}
                for row, key in zip(vector["expect"]["checks"], checks)
            ]
    _reidentify_language_bundle(language)
    first = admit_authority_context(kernel, language)
    second = _consumer_b(kernel, language)
    assert not isinstance(first, AdmittedAuthorityContext)
    assert [row.code for row in first.diagnostics] == ["kernel.vector_mismatch"]
    assert not second["admitted"]
    assert [row[1] for row in second["diagnostics"]] == ["kernel.vector_mismatch"]


@pytest.mark.parametrize(
    "change", ["alias", "missing", "duplicate", "reordered", "false-match"]
)
def test_reidentified_comparison_cannot_forge_complete_ordered_checks(
    accepted_execution, change
):
    checked, execution = accepted_execution
    contract = select_exact_replay_contract(packaged_authority_context())
    arguments = {
        "replay_contract": contract,
        "output_contracts": checked.output_contracts,
        "original_artifact_set_receipt_identity": "sha256:" + "1" * 64,
        "original_members": execution.members,
        "replay_members": execution.members,
    }
    actual = compare_exact_replay(**arguments).value
    assert [row["key"] for row in actual["checks"]] == _MEMBERS
    assert validate_exact_replay_comparison(actual, **arguments)
    assert validate_published_exact_replay_comparison(actual, **arguments)
    payload = _artifact_payload(actual)
    rows = payload["checks"]
    if change == "alias":
        for row in rows:
            row["key"] = row["key"].replace("_", "-")
    elif change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif change == "reordered":
        rows.reverse()
    else:
        rows[-1]["match"] = False
        payload["result"] = "mismatched"
    forged = contract.artifact.identify(payload)
    assert contract.artifact.verify(forged)
    assert not validate_exact_replay_comparison(forged, **arguments)
    assert not validate_published_exact_replay_comparison(forged, **arguments)


def test_public_build_run_and_replay_use_actual_observation_members(tmp_path):
    candidate = _PublicCandidate(tmp_path, authorities=mutable_authorities())
    example = Path(__file__).parents[1] / "examples/schema2/bounded-fold"
    candidate.write_source(json.loads((example / "model-source.json").read_text()))
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "a1" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    rir_path = tmp_path / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = json.loads((example / "experiment.json").read_text())
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    specification_path = tmp_path / "experiment.json"
    specification_path.write_text(json.dumps(specification))
    candidate.cli(
        "experiment", "check", str(specification_path), "--rir", str(rir_path)
    )
    run = candidate.cli(
        "experiment",
        "run",
        str(specification_path),
        "--rir",
        str(rir_path),
        "--out",
        str(tmp_path / "run.json"),
        "--invocation-key",
        "b1" * 32,
    )
    metrics = _members(run)["metric-dataset"]
    assert {row["metric"]: row["value"] for row in metrics["samples"]} == {
        "ordered_value": 1234,
        "selected_count": 2,
    }
    receipt_path = tmp_path / "original-receipt.json"
    receipt_path.write_text(json.dumps(run))
    replay = candidate.cli(
        "experiment",
        "replay",
        str(specification_path),
        "--rir",
        str(rir_path),
        "--original-experiment-run-artifact-set-receipt",
        str(receipt_path),
        "--out",
        str(tmp_path / "comparison.json"),
        "--invocation-key",
        "c1" * 32,
    )
    assert replay["claim_state"] == "candidate"
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert comparison["result"] == "matched"
    assert [row["key"] for row in comparison["checks"]] == _MEMBERS
    assert all(row["match"] for row in comparison["checks"])
    assert comparison["original_observation"] == comparison["replay_observation"]
