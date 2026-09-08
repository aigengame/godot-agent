"""Public Evidence results preserve the claim selected from an admitted LDB."""

import json
from pathlib import Path
from typing import Any

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_trace_protocol_structure import _authored, _graph


_EXAMPLES = Path(__file__).parents[1] / "examples/schema2/bounded-fold"
_CLAIMS = {"control": "evaluable", "renamed": "review.evaluable"}


@pytest.fixture(scope="module")
def publications(tmp_path_factory):
    root = tmp_path_factory.mktemp("evidence-claim-identity")
    results: dict[str, tuple[_PublicCandidate, tuple[str, ...], dict[str, Any]]] = {}
    for case, claim_id in _CLAIMS.items():
        kernel, ldb = mutable_authorities()
        authored = _authored(ldb)
        package = next(
            package
            for package in authored["packages"]
            if any(
                closure["authority_path"] == "language.evidence_claim_kinds"
                and closure["definitions"]
                for closure in package["semantic_closure"]
            )
        )
        claim = next(
            closure["definitions"][0]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.evidence_claim_kinds"
        )
        original_id = claim["id"]
        claim["id"] = claim_id
        package["exports"]["evidence_claim_kinds"] = [
            claim_id if value == original_id else value
            for value in package["exports"]["evidence_claim_kinds"]
        ]
        # Vector identifiers are local labels, not claim-id prefix references.
        graph = _graph(kernel, authored)
        for consumer in (_consumer_a, _consumer_b):
            admission = consumer(kernel, graph)
            assert admission["admitted"], admission
        public = _PublicCandidate(root / case, authorities=(kernel, graph))
        (public.directory / "candidate.json").write_text(json.dumps(authored))
        public.write_source(json.loads((_EXAMPLES / "model-source.json").read_text()))
        public.cli("model", "check", str(public.source))
        build = _members(
            public.cli(
                "model",
                "build",
                str(public.source),
                "--out",
                str(public.directory / "build"),
                "--invocation-key",
                "ad" * 32,
            )
        )
        assert len(build) == 8
        rir = build["rir-semantic-payload"]
        rir_path = public.directory / "rir.json"
        rir_path.write_text(json.dumps(rir))
        specification = json.loads((_EXAMPLES / "experiment.json").read_text())
        specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
        specification_path = public.directory / "experiment.json"
        specification_path.write_text(json.dumps(specification))
        public.cli(
            "experiment", "check", str(specification_path), "--rir", str(rir_path)
        )
        receipt = public.cli(
            "experiment",
            "run",
            str(specification_path),
            "--rir",
            str(rir_path),
            "--out",
            str(public.directory / "run"),
            "--invocation-key",
            "ae" * 32,
        )
        receipt_path = public.directory / "run-receipt.json"
        receipt_path.write_text(json.dumps(receipt))
        assert {
            row["metric"]: row["value"]
            for row in _members(receipt)["metric-dataset"]["samples"]
        } == {"ordered_value": 1234, "selected_count": 2}
        arguments = (
            "--rir",
            str(rir_path),
            "--specification",
            str(specification_path),
            "--experiment-run-artifact-set-receipt",
            str(receipt_path),
        )
        results[case] = public, arguments, rir
    assert results["control"][2] == results["renamed"][2]
    return results


@pytest.mark.parametrize("case", _CLAIMS)
def test_public_evidence_uses_admitted_claim_identity(publications, case):
    public, arguments, rir = publications[case]
    result = public.cli("evidence", "verify", "--claim-kind", _CLAIMS[case], *arguments)
    assert result["claim_kind"] == _CLAIMS[case]
    assert result["claim_state"] == "candidate"
    assert result["producing_outcome"] == "success"
    assert result["rir_semantic_identity"] == rir["semantic_identity"]
    assert set(result) == {
        "claim_kind",
        "claim_state",
        "producing_outcome",
        "rir_semantic_identity",
        "experiment_identity",
        "resolved_runtime_profile_identity",
        "evaluator_capability_manifest_identity",
        "experiment_run_artifact_set_receipt_identity",
    }
    assert all(
        value.startswith("sha256:")
        for name, value in result.items()
        if name.endswith("_identity")
    )


def test_public_evidence_refuses_retired_claim_identity(publications):
    public, arguments, _ = publications["renamed"]
    result = public.cli(
        "evidence",
        "verify",
        "--claim-kind",
        _CLAIMS["control"],
        *arguments,
        success=False,
    )
    assert public.receipts[-1]["returncode"] == 2
    error = result["error"]
    assert error["category"] == "refusal"
    assert error["stage"] == "evaluation"
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.unknown_evidence_claim_kind"
    ]
