"""Independent Evidence eligibility keeps no synthetic prerequisite graph."""

from copy import deepcopy

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from test_rir_protocol_structure import _definitions
from test_trace_protocol_structure import _authored, _graph


def _claim(authored):
    claims = _definitions(authored, "language.evidence_claim_kinds")
    assert len(claims) == 1
    return claims[0]


def _observations(kernel, authored):
    graph = _graph(kernel, authored)
    actual = _consumer_a(kernel, graph)
    independent = _consumer_b(kernel, graph)
    assert independent == actual
    return independent


@pytest.mark.parametrize("member", ["subject_roles", "prerequisite_edges", "graph"])
def test_independent_evidence_refuses_resealed_retired_graph_fields(member):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    claim = _claim(authored)
    if member == "subject_roles":
        claim[member] = [
            "rir-semantic-identity",
            "experiment",
            "evaluator-capability-manifest",
            "resolved-runtime-profile",
            "experiment-run-artifact-set-receipt",
        ]
    elif member == "prerequisite_edges":
        claim[member] = []
    else:
        claim["vectors"][0]["input"][member] = "exact"
    observation = _observations(kernel, authored)
    assert not observation["admitted"]
    assert observation["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize(
    "vector_id",
    [
        "evaluable.success",
        "evaluable.verdict",
        "evaluable.runtime-refusal",
        "evaluable.pre-dispatch",
    ],
)
def test_independent_evidence_executes_each_retained_vector_expectation(vector_id):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    vector = next(row for row in _claim(authored)["vectors"] if row["id"] == vector_id)
    candidate = vector["expect"] == "candidate"
    vector["expect"] = "refusal" if candidate else "candidate"
    vector["kind"] = "negative" if candidate else "positive"
    observation = _observations(kernel, authored)
    assert not observation["admitted"]
    assert observation["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.evidence-claim-kinds")
    ]


@pytest.mark.parametrize(
    "vector_id",
    [
        "evaluable.success",
        "evaluable.verdict",
        "evaluable.runtime-refusal",
        "evaluable.pre-dispatch",
    ],
)
def test_independent_evidence_requires_retained_outcome_and_dispatch_coverage(
    vector_id,
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    claim = _claim(authored)
    claim["vectors"] = [row for row in claim["vectors"] if row["id"] != vector_id]
    observation = _observations(kernel, authored)
    assert not observation["admitted"]
    assert observation["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.evidence-claim-kinds")
    ]


@pytest.mark.parametrize("exclude_success", [False, True])
def test_independent_evidence_preserves_renamed_claim_and_selected_eligibility(
    exclude_success,
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    claim = _claim(authored)
    old_id = claim["id"]
    new_id = "review.evaluable"
    claim["id"] = new_id
    owner = next(
        package
        for package in authored["packages"]
        if old_id in package["exports"]["evidence_claim_kinds"]
    )
    owner["exports"]["evidence_claim_kinds"] = [new_id]
    original_vectors = deepcopy(claim["vectors"])
    if exclude_success:
        claim["eligibility"]["producing_outcomes"].remove("success")
        success = next(
            row
            for row in claim["vectors"]
            if row["input"]["producing_outcome"] == "success"
        )
        success["kind"] = "negative"
        success["expect"] = "refusal"
    observation = _observations(kernel, authored)
    assert observation["admitted"], observation
    assert {row["id"] for row in claim["vectors"]} == {
        row["id"] for row in original_vectors
    }
    if exclude_success:
        success["kind"] = "positive"
        success["expect"] = "candidate"
        refused = _observations(kernel, authored)
        assert refused["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.evidence-claim-kinds")
        ]


def test_independent_evidence_requires_the_post_dispatch_refusal_variant():
    kernel, language = mutable_authorities()
    authored = _authored(language)
    claim = _claim(authored)
    vector = deepcopy(
        next(
            row for row in claim["vectors"] if row["id"] == "evaluable.runtime-refusal"
        )
    )
    vector["id"] = "review.refusal-before-dispatch"
    vector["input"]["runtime_refusal_variant"] = "pre-dispatch"
    vector["kind"] = "negative"
    vector["expect"] = "refusal"
    claim["vectors"].append(vector)
    assert _observations(kernel, authored)["admitted"]
    vector["kind"] = "positive"
    vector["expect"] = "candidate"
    observation = _observations(kernel, authored)
    assert observation["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.evidence-claim-kinds")
    ]
