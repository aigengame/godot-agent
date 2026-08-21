"""Schema 2.0 Evidence candidate verification."""

from gda_balancing.domain.authority.context import packaged_authority_context


def test_packaged_ldb_owns_the_complete_evaluable_claim_kind() -> None:
    language = packaged_authority_context().language_bundle["language"]

    assert language["evidence_claim_kinds"] == [
        {
            "id": "evaluable",
            "version": "1.0.0",
            "subject_roles": [
                "kernel",
                "language-bundle",
                "model-source",
                "resolved-model",
                "model-build-receipt",
                "experiment",
                "evaluator-capability-manifest",
                "resolved-runtime-profile",
                "experiment-outcome-receipt",
            ],
            "prerequisite_edges": [
                {"subject": "language-bundle", "prerequisite": "kernel"},
                {"subject": "resolved-model", "prerequisite": "kernel"},
                {
                    "subject": "resolved-model",
                    "prerequisite": "language-bundle",
                },
                {"subject": "resolved-model", "prerequisite": "model-source"},
                {
                    "subject": "model-build-receipt",
                    "prerequisite": "model-source",
                },
                {
                    "subject": "model-build-receipt",
                    "prerequisite": "resolved-model",
                },
                {"subject": "experiment", "prerequisite": "kernel"},
                {"subject": "experiment", "prerequisite": "language-bundle"},
                {"subject": "experiment", "prerequisite": "resolved-model"},
                {
                    "subject": "evaluator-capability-manifest",
                    "prerequisite": "kernel",
                },
                {
                    "subject": "evaluator-capability-manifest",
                    "prerequisite": "language-bundle",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "kernel",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "language-bundle",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "resolved-model",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "experiment",
                },
                {
                    "subject": "resolved-runtime-profile",
                    "prerequisite": "evaluator-capability-manifest",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "model-build-receipt",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "experiment",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "resolved-runtime-profile",
                },
                {
                    "subject": "experiment-outcome-receipt",
                    "prerequisite": "evaluator-capability-manifest",
                },
            ],
            "eligibility": {
                "claim_state": "candidate",
                "runtime_dispatch": "required",
                "producing_outcomes": ["runtime-refusal", "success", "verdict"],
                "runtime_refusal_variant": "post-dispatch",
            },
            "permitted_issuer_classes": [],
            "permitted_verifier_classes": [],
            "vectors": [
                {
                    "id": "evaluable.success",
                    "kind": "positive",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "success",
                        "runtime_dispatch": "reached",
                        "runtime_refusal_variant": "not-applicable",
                    },
                    "expect": "candidate",
                },
                {
                    "id": "evaluable.verdict",
                    "kind": "positive",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "verdict",
                        "runtime_dispatch": "reached",
                        "runtime_refusal_variant": "not-applicable",
                    },
                    "expect": "candidate",
                },
                {
                    "id": "evaluable.runtime-refusal",
                    "kind": "positive",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "runtime-refusal",
                        "runtime_dispatch": "reached",
                        "runtime_refusal_variant": "post-dispatch",
                    },
                    "expect": "candidate",
                },
                {
                    "id": "evaluable.pre-dispatch",
                    "kind": "negative",
                    "input": {
                        "graph": "exact",
                        "producing_outcome": "runtime-refusal",
                        "runtime_dispatch": "not-reached",
                        "runtime_refusal_variant": "pre-dispatch",
                    },
                    "expect": "refusal",
                },
                *[
                    {
                        "id": f"evaluable.graph-{graph}",
                        "kind": "negative",
                        "input": {
                            "graph": graph,
                            "producing_outcome": "success",
                            "runtime_dispatch": "reached",
                            "runtime_refusal_variant": "not-applicable",
                        },
                        "expect": "refusal",
                    }
                    for graph in (
                        "missing",
                        "extra",
                        "mismatched",
                        "cyclic",
                        "unresolved",
                    )
                ],
            ],
        }
    ]
