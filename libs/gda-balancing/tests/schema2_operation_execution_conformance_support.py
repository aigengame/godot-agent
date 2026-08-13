"""Orchestrate dual-consumer Operation execution conformance."""

from typing import Any

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_operation_execution_independent_support import reference_execute_event
from schema2_operation_execution_production_support import (
    evaluate_operation_execution_vector,
)


def operation_execution_vectors(ldb: Any) -> list[tuple[str, dict[str, Any]]]:
    """Discover every manifest-bound Operation execution vector."""
    return [
        (vector_set["package_id"], vector)
        for vector_set in ldb.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector.get("kind") == "operation-execution"
    ]


def independent_operation_execution_projection(
    kernel: dict[str, Any],
    ldb: Any,
    operations: dict[str, dict[str, Any]],
    vector: dict[str, Any],
) -> dict[str, Any]:
    """Project the independent adapter result to the canonical vector shape."""
    operation = operations[vector["operation"]]
    event = reference_execute_event(
        kernel,
        operation,
        operations,
        {"id": vector["id"], "values": vector["input"]["values"]},
        seed=vector["input"]["seed"],
        state_names={
            row["id"] for row in operation["inputs"] if row["access"] == "read-write"
        },
        language_bundle=ldb,
    )
    state_after = {row["name"]: row["value"] for row in event["state_after"]}
    state_names = [
        row["id"] for row in operation["inputs"] if row["access"] == "read-write"
    ]
    if "refusal" in event:
        return {
            "completion": {"kind": "refusal", "reason": event["refusal"]["reason"]},
            "result": {"kind": "not-produced"},
            "rng_draws": [],
            "state_after": [
                {"name": name, "value": state_after[name]} for name in state_names
            ],
        }
    return {
        "completion": {"kind": "outcome", "id": event["outcome"]["id"]},
        "result": (
            {"kind": "value", "value": event["result"]}
            if event["outcome"]["kind"] == "success"
            else {"kind": "not-produced"}
        ),
        "rng_draws": [
            {
                member: draw[member]
                for member in ("candidate_hex", "index", "stream", "value")
            }
            for draw in event["rng_draws"]
        ],
        "state_after": [
            {"name": name, "value": state_after[name]} for name in state_names
        ],
    }


def candidate_conformance_failures(
    kernel: dict[str, Any],
    ldb: Any,
    *,
    vector_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return bounded candidate-graph and execution-vector disagreements."""
    production_admission = _consumer_a(kernel, ldb)
    independent_admission = _consumer_b(kernel, ldb)
    if production_admission != independent_admission:
        return [
            {
                "kind": "admission-divergence",
                "independent": independent_admission,
                "production": production_admission,
            }
        ]
    if production_admission["admitted"] is not True:
        return [
            {
                "kind": "candidate-refused",
                "observed": production_admission["diagnostics"],
            }
        ]
    context = admit_authority_context(kernel, ldb)
    assert isinstance(context, AdmittedAuthorityContext)
    operations = {row["id"]: row for row in ldb["language"]["operations"]}
    failures: list[dict[str, Any]] = []
    overrides = vector_overrides or {}
    for package_id, declared in operation_execution_vectors(ldb):
        vector = overrides.get(declared["id"], declared)
        production = evaluate_operation_execution_vector(context, vector)
        independent = independent_operation_execution_projection(
            kernel, ldb, operations, vector
        )
        if production != independent or production != vector["expect"]:
            failures.append(
                {
                    "kind": "vector-divergence",
                    "package": package_id,
                    "vector": vector["id"],
                    "expected": vector["expect"],
                    "production": production,
                    "independent": independent,
                }
            )
    return failures
