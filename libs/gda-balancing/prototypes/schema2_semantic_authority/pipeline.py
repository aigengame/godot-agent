"""Vertical orchestration across authority, compile, runtime, metrics, and replay gates."""

from __future__ import annotations

from typing import Any

from authority import (
    KERNEL_SPEC,
    experiment,
    language_bundle,
    runtime_profile,
    scenario,
    source_package,
)
from bootstrap_a import BootstrapA
from bootstrap_b import BootstrapB
from canonical import artifact, clone
from compiler_a import CompilerA
from compiler_b import CompilerB
from evaluator_a import EvaluatorA
from evaluator_b import EvaluatorB


INGRESS_ADMISSION_CODES = {
    "bundle.identity-mismatch",
    "bundle.kernel-mismatch",
    "bundle.ontology-mismatch",
    "kernel.identity-mismatch",
}


def admit(bundle: dict[str, Any]) -> dict[str, Any]:
    result_a = BootstrapA().admit(KERNEL_SPEC, bundle)
    result_b = BootstrapB().admit(KERNEL_SPEC, bundle)
    comparable_a = {
        key: value for key, value in result_a.items() if key != "implementation"
    }
    comparable_b = {
        key: value for key, value in result_b.items() if key != "implementation"
    }
    if comparable_a != comparable_b:
        raise ValueError("bootstrap.conformance-disagreement")
    receipt_a = artifact("bundle-admission-receipt", result_a)
    receipt_b = artifact("bundle-admission-receipt", result_b)
    refusal_stage = None
    if result_a["diagnostics"]:
        refusal_stage = (
            "ingress"
            if any(
                diagnostic["code"] in INGRESS_ADMISSION_CODES
                for diagnostic in result_a["diagnostics"]
            )
            else "static"
        )
    return {
        "admitted": result_a["admitted"],
        "diagnostics": result_a["diagnostics"],
        "refusal_stage": refusal_stage,
        "receipt_a": receipt_a,
        "receipt_b": receipt_b,
    }


def resolve(bundle: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    package_facts = {
        fact["id"]: fact for fact in bundle["facts"] if fact.get("kind") == "package"
    }
    selected: list[dict[str, str]] = []
    providers: dict[str, str] = {}
    operations: dict[str, str] = {}
    graph: list[dict[str, Any]] = []
    for requirement in sorted(source["requires"], key=lambda row: row["package"]):
        package = package_facts.get(requirement["package"])
        if package is None or requirement["constraint"] != f"={package['version']}":
            raise ValueError("resolution.package-unsatisfied")
        package_identity = f"{package['id']}@{package['version']}"
        selected.append(
            {"package": package_identity, "constraint": requirement["constraint"]}
        )
        graph.append(
            {"package": package_identity, "dependencies": clone(package["requires"])}
        )
        for capability in package["provides"]:
            if capability in providers:
                raise ValueError("resolution.capability-conflict")
            providers[capability] = package_identity
        for operation in package["operations"]:
            operations[operation] = package_identity
    lock = artifact(
        "package-lock",
        {
            "kernel": KERNEL_SPEC["identity"],
            "language_bundle": bundle["identity"],
            "resolution_profile": "closed-exact-resolution-v1",
            "transitive_graph": graph,
            "selected": selected,
            "capability_providers": providers,
            "operation_bindings": operations,
            "type_closure": ["Int", "Record", "Variant"],
            "conversion_closure": [],
            "conflict_disposition": "no-conflicts",
        },
    )
    receipt = artifact(
        "resolution-receipt",
        {
            "resolver": "probe-resolver-v1",
            "source_requirements": clone(source["requires"]),
            "kernel": KERNEL_SPEC["identity"],
            "language_bundle": bundle["identity"],
            "package_lock": lock["identity"],
            "diagnostics": [],
        },
    )
    return {"lock": lock, "receipt": receipt}


def build(
    compiler_name: str,
    source_variant: str,
    *,
    bundle: dict[str, Any] | None = None,
    base_damage: int = 4,
) -> dict[str, Any]:
    selected_bundle = language_bundle() if bundle is None else clone(bundle)
    admission = admit(selected_bundle)
    if not admission["admitted"]:
        return {"status": "refused", "admission": admission}
    source = source_package(source_variant, base_damage=base_damage)
    resolution = resolve(selected_bundle, source)
    compiler = CompilerA() if compiler_name == "a" else CompilerB()
    compiled = compiler.compile(
        KERNEL_SPEC,
        selected_bundle,
        source,
        resolution["lock"],
        resolution["receipt"],
    )
    return {
        "status": "completed",
        "kernel": clone(KERNEL_SPEC),
        "bundle": clone(selected_bundle),
        "admission": admission,
        "resolution": resolution,
        "compiled": compiled,
    }


def execute(
    compiler_name: str,
    evaluator_name: str,
    source_variant: str,
    scenario_name: str,
    profile: dict[str, Any],
    *,
    bundle: dict[str, Any] | None = None,
    base_damage: int = 4,
) -> dict[str, Any]:
    built = build(
        compiler_name,
        source_variant,
        bundle=bundle,
        base_damage=base_damage,
    )
    if built["status"] != "completed":
        return built
    evaluator = EvaluatorA() if evaluator_name == "a" else EvaluatorB()
    result = evaluator.run(
        KERNEL_SPEC,
        built["bundle"],
        built["resolution"]["lock"],
        built["compiled"]["rir"],
        profile,
        scenario(scenario_name),
    )
    return {"status": result["status"], "build": built, "runtime": result}


def metric_dataset(
    run: dict[str, Any], experiment_artifact: dict[str, Any]
) -> dict[str, Any]:
    return artifact(
        "metric-dataset",
        {
            "evaluation_run": run["identity"],
            "experiment": experiment_artifact["identity"],
            "definitions": clone(experiment_artifact["metric_definitions"]),
            "observations": clone(run["metrics"]),
        },
    )


def compare_cross_evaluator() -> dict[str, Any]:
    build_a = build("a", "a")
    build_b = build("b", "b")
    if build_a["status"] != "completed" or build_b["status"] != "completed":
        raise ValueError("comparison.build-refused")
    rir_a = build_a["compiled"]["rir"]
    rir_b = build_b["compiled"]["rir"]
    if rir_a != rir_b:
        raise ValueError("comparison.rir-not-identical")
    profile = runtime_profile()
    run_a = EvaluatorA().run(
        KERNEL_SPEC,
        build_b["bundle"],
        build_b["resolution"]["lock"],
        rir_b,
        profile,
        scenario("success"),
    )
    run_b = EvaluatorB().run(
        KERNEL_SPEC,
        build_a["bundle"],
        build_a["resolution"]["lock"],
        rir_a,
        profile,
        scenario("success"),
    )
    if run_a["status"] != "completed" or run_b["status"] != "completed":
        raise ValueError("comparison.run-refused")
    experiment_value = experiment()
    experiment_value["resolved_model"] = rir_a["identity"]
    experiment_artifact = artifact("experiment-specification", experiment_value)
    run_artifact_a = run_a["run"]
    run_artifact_b = run_b["run"]
    dataset_a = metric_dataset(run_artifact_a, experiment_artifact)
    dataset_b = metric_dataset(run_artifact_b, experiment_artifact)
    policy = experiment_artifact["replay_policy"]
    observation_mismatches = [
        field
        for field in policy["compare"]
        if run_artifact_a[field] != run_artifact_b[field]
    ]
    gate_report = {
        "kind": "evaluation-gate-report",
        "policy": policy["id"],
        "left_resolved_profile": run_a["profile"]["identity"],
        "right_resolved_profile": run_b["profile"]["identity"],
        "semantic_profile": run_artifact_a["semantic_runtime_profile"],
        "required_profile_rule": "identical-resolved-runtime-profile",
        "observation_mismatches": observation_mismatches,
        "gate": "decision-required",
        "diagnostic": "evaluation.resolved-runtime-profile-identity-conflict",
        "authority_conflict": [
            "bADR-0014-identical-resolved-profile",
            "independent-evaluator-profile-binds-evaluator-identity",
        ],
    }
    return {
        "status": "refused",
        "stage": "evaluation",
        "diagnostics": [
            {
                "code": "evaluation.resolved-runtime-profile-identity-conflict",
                "detail": "design-decision-required",
            }
        ],
        "build_a": build_a,
        "build_b": build_b,
        "run_a": run_a,
        "run_b": run_b,
        "experiment": experiment_artifact,
        "datasets": [dataset_a, dataset_b],
        "gate_report": gate_report,
    }


def build_members(result: dict[str, Any]) -> list[dict[str, Any]]:
    admission = result["admission"]
    resolution = result["resolution"]
    compiled = result["compiled"]
    return [
        result["kernel"],
        result["bundle"],
        admission["receipt_a"],
        admission["receipt_b"],
        resolution["lock"],
        resolution["receipt"],
        compiled["source"],
        compiled["ast"],
        compiled["hir"],
        compiled["rir"],
        compiled["debug_map"],
        compiled["build_receipt"],
    ]
