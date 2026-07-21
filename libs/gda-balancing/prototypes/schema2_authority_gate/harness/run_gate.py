"""Run the disposable Executable Kernel/LDB Authority Gate.

The harness is intentionally non-semantic: it materializes content identities,
launches isolated processes, exchanges their JSON bytes, mutates authority data, and
compares fields selected by the authority.  It never implements a language rule.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUTHORITIES = ROOT / "authorities"
EVIDENCE = ROOT / "evidence"
ENGINE_A = ROOT / "impl_a" / "engine.py"
ENGINE_B = ROOT / "impl_b" / "engine.mjs"
IMPLEMENTATIONS = {
    "a": {"id": "python-recursive-a-v1", "command": [sys.executable, str(ENGINE_A)]},
    "b": {"id": "node-independent-b-v1", "command": ["node", str(ENGINE_B)]},
}


def load(name: str) -> dict[str, Any]:
    return json.loads((AUTHORITIES / name).read_text(encoding="utf-8"))


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def identity(domain: str, payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(domain.encode() + b"\0" + canonical_bytes(payload)).hexdigest()
    )


def materialize(
    kernel_payload: dict[str, Any], ldb_payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    kernel = copy.deepcopy(kernel_payload)
    kernel_envelope = {"payload": kernel, "identity": identity("kernel", kernel)}
    ldb = copy.deepcopy(ldb_payload)
    ldb["kernel_identity"] = kernel_envelope["identity"]
    ldb_envelope = {"payload": ldb, "identity": identity("ldb", ldb)}
    return kernel_envelope, ldb_envelope


def invoke(implementation: str, request: dict[str, Any]) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPYCACHEPREFIX"] = "/tmp/schema2-authority-gate-pycache"
    completed = subprocess.run(
        IMPLEMENTATIONS[implementation]["command"],
        input=canonical_bytes(request),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"{implementation} process failed: {completed.stderr.decode()}"
        )
    response = json.loads(completed.stdout)
    if response.get("status") == "internal_error" or "exception" in response:
        raise AssertionError(f"{implementation} internal error: {response}")
    return response


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def bootstrap_all(
    kernel: dict[str, Any], ldb: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    results = {
        name: invoke(name, {"command": "bootstrap", "kernel": kernel, "ldb": ldb})
        for name in IMPLEMENTATIONS
    }
    require(
        all(result.get("admitted") for result in results.values()),
        f"bootstrap disagreement: {results}",
    )
    require(
        results["a"]["kernel_identity"] == results["b"]["kernel_identity"],
        "kernel identity differs",
    )
    require(
        results["a"]["ldb_identity"] == results["b"]["ldb_identity"],
        "LDB identity differs",
    )
    return results


def compile_with(
    implementation: str,
    kernel: dict[str, Any],
    ldb: dict[str, Any],
    peer: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    return invoke(
        implementation,
        {
            "command": "compile",
            "kernel": kernel,
            "ldb": ldb,
            "peer_admission": peer,
            "source": source,
        },
    )


def resolved_profile(
    implementation: str,
    kernel: dict[str, Any],
    ldb: dict[str, Any],
    resolved_model: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "artifact_kind": "resolved-runtime-profile",
        "definition_identity": identity(
            "runtime-profile-definition",
            ldb["payload"]["runtime_profiles"][
                ldb["payload"]["default_runtime_profile"]
            ],
        ),
        "evaluator": IMPLEMENTATIONS[implementation]["id"],
        "kernel_identity": kernel["identity"],
        "ldb_identity": ldb["identity"],
        "resolved_model_identity": resolved_model["identity"],
    }
    return {"payload": payload, "identity": identity("resolved-profile", payload)}


def evaluate_with(
    implementation: str,
    kernel: dict[str, Any],
    ldb: dict[str, Any],
    compiled: dict[str, Any],
    scenario: dict[str, Any],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    profile = resolved_profile(implementation, kernel, ldb, compiled["resolved_model"])
    return invoke(
        implementation,
        {
            "command": "evaluate",
            "kernel": kernel,
            "ldb": ldb,
            "rir": compiled["rir"],
            "resolved_model": compiled["resolved_model"],
            "resolved_profile": profile,
            "scenario": scenario,
            "experiment": experiment,
        },
    )


def portable(result: dict[str, Any], ldb: dict[str, Any]) -> dict[str, Any]:
    return {
        field: result.get(field)
        for field in ldb["payload"]["comparison_policy"]["portable_fields"]
    }


def comparison_request(
    command: str,
    kernel: dict[str, Any],
    ldb: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
    left_profile: dict[str, Any],
    right_profile: dict[str, Any],
    experiment: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    return {
        "command": command,
        "kernel": kernel,
        "ldb": ldb,
        "left": left,
        "right": right,
        "left_profile": left_profile,
        "right_profile": right_profile,
        "experiment": experiment,
        "scenario": scenario,
    }


def compile_pair(
    kernel: dict[str, Any], ldb: dict[str, Any], source: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    admissions = bootstrap_all(kernel, ldb)
    compiled_a = compile_with("a", kernel, ldb, admissions["b"], source)
    compiled_b = compile_with("b", kernel, ldb, admissions["a"], source)
    require(compiled_a["status"] == compiled_b["status"], "lowerers disagree on status")
    if compiled_a["status"] == "compiled":
        require(
            canonical_bytes(compiled_a["rir"]) == canonical_bytes(compiled_b["rir"]),
            "RIR bytes do not converge",
        )
        require(
            canonical_bytes(compiled_a["package_lock"])
            == canonical_bytes(compiled_b["package_lock"]),
            "Lock bytes do not converge",
        )
        require(
            canonical_bytes(compiled_a["resolved_model"])
            == canonical_bytes(compiled_b["resolved_model"]),
            "Resolved Model differs",
        )
    else:
        require(
            compiled_a["diagnostic"] == compiled_b["diagnostic"],
            "compile diagnostics differ",
        )
    return compiled_a, compiled_b, admissions


def mutate_rule(ldb_payload: dict[str, Any], rule_id: str, kind: str) -> dict[str, Any]:
    mutated = copy.deepcopy(ldb_payload)
    index = next(
        index for index, rule in enumerate(mutated["rules"]) if rule["id"] == rule_id
    )
    if kind == "delete":
        del mutated["rules"][index]
        return mutated
    rule = mutated["rules"][index]
    if kind == "tamper":
        rule["priority"] += 1
        return mutated
    phase = rule["phase"]
    if phase == mutated["compiler_pipeline"][0]:
        original = rule["body"]["fields"]["time"]
        rule["body"]["fields"]["time"] = {
            "op": "add",
            "left": original,
            "right": {"op": "literal", "value": 1},
        }
    elif phase == mutated["compiler_pipeline"][-1]:
        original = rule["body"]["fields"]["priority"]
        rule["body"]["fields"]["priority"] = {
            "op": "add",
            "left": original,
            "right": {"op": "literal", "value": 1},
        }
    else:
        rule["when"]["right"]["value"] = f"mutated-{phase}"
    return mutated


def mutate_law(
    kernel_payload: dict[str, Any], law_id: str, kind: str
) -> dict[str, Any]:
    mutated = copy.deepcopy(kernel_payload)
    if kind == "delete":
        del mutated["laws"][law_id]
        return mutated
    body = mutated["laws"][law_id]["body"]
    if kind == "tamper":
        mutated["laws"][law_id]["result"] = (
            mutated["laws"][law_id]["result"] + "-tampered"
        )
        return mutated
    if law_id.endswith("checked_add"):
        body["value"]["op"] = "sub"
    elif law_id.endswith("seed_stream"):
        body["value"]["items"][0]["value"] += "mutated:"
    elif law_id.endswith("rng.next") or law_id.endswith(".next"):
        body["value"]["left"]["right"]["right"]["value"] = 12
    elif law_id.endswith("bounded"):
        body["items"][1]["then"]["fields"]["value"] = {"op": "literal", "value": 99}
    elif law_id.endswith("scheduler.key") or law_id.endswith(".key"):
        body["items"][2] = body["items"][2]["right"]
    elif law_id.endswith("transition.apply") or law_id.endswith(".apply"):
        original = body["value"]
        body["value"] = {
            "op": "add",
            "left": original,
            "right": {"op": "literal", "value": 1},
        }
    elif law_id.endswith("replay_compatible"):
        mutated["laws"][law_id]["body"] = {"op": "not", "value": body}
    elif law_id.endswith("rule.applicable") or law_id.endswith(".applicable"):
        mutated["laws"][law_id]["body"] = {"op": "literal", "value": False}
    elif law_id.endswith("rule.priority") or law_id.endswith(".priority"):
        mutated["laws"][law_id]["body"] = {
            "op": "sub",
            "left": {"op": "literal", "value": 0},
            "right": body,
        }
    elif law_id.endswith("rule.choose") or law_id.endswith(".choose"):
        body["direction"]["value"] = "min"
    elif law_id.startswith("effect."):
        body["fields"]["disposition"]["value"] = "unsupported_intent"
    elif law_id.endswith("transaction.accept_write") or law_id.endswith(
        ".accept_write"
    ):
        body["items"][0]["condition"] = {"op": "literal", "value": False}
    elif law_id.endswith("scheduler.child_allowed") or law_id.endswith(
        ".child_allowed"
    ):
        mutated["laws"][law_id]["body"] = {"op": "not", "value": body}
    elif law_id.endswith("budget.within") or law_id.endswith(".within"):
        mutated["laws"][law_id]["body"] = {"op": "literal", "value": False}
    else:
        raise AssertionError(f"no witness mutator for {law_id}")
    return mutated


def rename_authority(
    ldb_payload: dict[str, Any], source: dict[str, Any], scenario: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    operation_names = sorted(ldb_payload["operations"])
    rule_names = [rule["id"] for rule in ldb_payload["rules"]]
    diagnostic_names = sorted(ldb_payload["diagnostics"])
    replacements = {
        name: f"renamed.operation.{index}" for index, name in enumerate(operation_names)
    }
    replacements.update(
        {name: f"renamed.rule.{index}" for index, name in enumerate(rule_names)}
    )
    replacements.update(
        {
            name: f"renamed.diagnostic.{index}"
            for index, name in enumerate(diagnostic_names)
        }
    )
    replacements["score"] = "points"

    def replace(value: Any) -> Any:
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {
                replacements.get(key, key): replace(item) for key, item in value.items()
            }
        return value

    return replace(ldb_payload), replace(source), replace(scenario)


def static_isolation_audit(
    kernel_payload: dict[str, Any], ldb_payload: dict[str, Any]
) -> dict[str, Any]:
    source_a = ENGINE_A.read_text(encoding="utf-8")
    source_b = ENGINE_B.read_text(encoding="utf-8")
    forbidden = (
        set(ldb_payload["operations"])
        | set(ldb_payload["diagnostics"])
        | {rule["id"] for rule in ldb_payload["rules"]}
    )
    leaked = sorted(
        token for token in forbidden if token in source_a or token in source_b
    )
    require(not leaked, f"authority tokens leaked into host source: {leaked}")
    require(
        "impl_b" not in source_a and "impl_a" not in source_b,
        "implementations import each other",
    )
    banned_python = [
        r"\beval\(",
        r"\bexec\(",
        r"\bimportlib\b",
        r"(?m)^(?:import|from)\s+random\b",
        r"(?m)^(?:import|from)\s+uuid\b",
        r"\btime\.time\b",
    ]
    banned_node = [r"Math\.random", r"Date\.now", r"eval\(", r"node:vm", r"node:module"]
    require(
        not any(re.search(pattern, source_a) for pattern in banned_python),
        "forbidden Python host escape",
    )
    require(
        not any(re.search(pattern, source_b) for pattern in banned_node),
        "forbidden Node host escape",
    )
    imports_a = sorted(
        set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_.]+)", source_a, re.MULTILINE))
    )
    imports_b = sorted(set(re.findall(r"from\s+[\"']([^\"']+)[\"']", source_b)))
    failure_pattern = r'SemanticFailure\("([^\"]+)"'
    failure_reasons = sorted(
        set(re.findall(failure_pattern, source_a))
        | set(re.findall(failure_pattern, source_b))
    )
    kernel_reasons = set(kernel_payload["admission_diagnostics"])
    ldb_reasons = set(ldb_payload["reason_diagnostics"])
    authoritative_reasons = kernel_reasons | ldb_reasons
    unmapped_reasons = sorted(set(failure_reasons) - authoritative_reasons)
    require(
        not unmapped_reasons,
        f"host failure reasons lack Diagnostic authority: {unmapped_reasons}",
    )
    direct_ldb_patterns = (
        r'ldb_diagnostic\(\s*ldb,\s*"([^\"]+)"',
        r'ldbDiagnostic\(ldb,\s*"([^\"]+)"',
    )
    direct_kernel_patterns = (
        r'kernel_diagnostic\(\s*kernel,\s*"([^\"]+)"',
        r'kernelDiagnostic\(kernel,\s*"([^\"]+)"',
    )
    direct_ldb_reasons = sorted(
        {
            reason
            for source in (source_a, source_b)
            for pattern in direct_ldb_patterns
            for reason in re.findall(pattern, source)
        }
    )
    direct_kernel_reasons = sorted(
        {
            reason
            for source in (source_a, source_b)
            for pattern in direct_kernel_patterns
            for reason in re.findall(pattern, source)
        }
    )
    unmapped_direct_ldb_reasons = sorted(set(direct_ldb_reasons) - ldb_reasons)
    unmapped_direct_kernel_reasons = sorted(set(direct_kernel_reasons) - kernel_reasons)
    require(
        not unmapped_direct_ldb_reasons,
        f"direct host exits lack LDB Diagnostic authority: {unmapped_direct_ldb_reasons}",
    )
    require(
        not unmapped_direct_kernel_reasons,
        "direct host exits lack Kernel Diagnostic authority: "
        f"{unmapped_direct_kernel_reasons}",
    )
    return {
        "authority_token_leaks": leaked,
        "host_failure_reasons": failure_reasons,
        "unmapped_host_failure_reasons": unmapped_reasons,
        "direct_ldb_failure_reasons": direct_ldb_reasons,
        "unmapped_direct_ldb_failure_reasons": unmapped_direct_ldb_reasons,
        "direct_kernel_failure_reasons": direct_kernel_reasons,
        "unmapped_direct_kernel_failure_reasons": unmapped_direct_kernel_reasons,
        "imports_a": imports_a,
        "imports_b": imports_b,
        "shared_semantic_modules": [],
    }


def main() -> int:
    kernel_payload = load("kernel.json")
    ldb_payload = load("ldb.json")
    source_a = load("source-a.json")
    source_b = load("source-b.json")
    source_refusal = load("source-refusal.json")
    scenario = load("scenario-success.json")
    scenario_overflow = load("scenario-overflow.json")
    experiment = load("experiment.json")
    kernel, ldb = materialize(kernel_payload, ldb_payload)
    admissions = bootstrap_all(kernel, ldb)
    vector_results: list[dict[str, Any]] = []

    forged_peer = {
        "kernel_identity": admissions["a"]["kernel_identity"],
        "ldb_identity": admissions["a"]["ldb_identity"],
    }
    forged_peer_a = compile_with("a", kernel, ldb, forged_peer, source_a)
    forged_peer_b = compile_with("b", kernel, ldb, forged_peer, source_a)
    require(
        forged_peer_a["status"] == forged_peer_b["status"] == "refused"
        and forged_peer_a["diagnostic"] == forged_peer_b["diagnostic"],
        "unsealed peer admission was consumed",
    )
    tampered_peer = copy.deepcopy(admissions["a"])
    tampered_peer["implementation"] = "forged-bootstrap"
    tampered_peer_a = compile_with("a", kernel, ldb, tampered_peer, source_a)
    tampered_peer_b = compile_with("b", kernel, ldb, tampered_peer, source_a)
    require(
        tampered_peer_a["status"] == tampered_peer_b["status"] == "refused"
        and tampered_peer_a["diagnostic"] == tampered_peer_b["diagnostic"],
        "tampered peer admission was consumed",
    )
    vector_results.append({"id": "sealed-peer-admission", "status": "pass"})

    missing_profile_payload = copy.deepcopy(ldb_payload)
    missing_profile_payload["default_runtime_profile"] = "missing-profile"
    missing_profile_kernel, missing_profile_ldb = materialize(
        kernel_payload, missing_profile_payload
    )
    missing_profile_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": missing_profile_kernel,
                "ldb": missing_profile_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in missing_profile_results)
        and missing_profile_results[0]["diagnostic"]
        == missing_profile_results[1]["diagnostic"],
        "missing default Runtime Profile was admitted",
    )

    broken_package_payload = copy.deepcopy(ldb_payload)
    broken_package_payload["packages"]["probe.core@1"]["operations"][
        "missing.operation@1"
    ] = True
    broken_package_kernel, broken_package_ldb = materialize(
        kernel_payload, broken_package_payload
    )
    broken_package_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": broken_package_kernel,
                "ldb": broken_package_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in broken_package_results)
        and broken_package_results[0]["diagnostic"]
        == broken_package_results[1]["diagnostic"],
        "broken package-to-Operation closure was admitted",
    )
    deleted_post_diagnostic_results: list[dict[str, Any]] = []
    for reason, code in sorted(ldb_payload["reason_diagnostics"].items()):
        missing_post_diagnostic_payload = copy.deepcopy(ldb_payload)
        del missing_post_diagnostic_payload["reason_diagnostics"][reason]
        del missing_post_diagnostic_payload["diagnostics"][code]
        missing_post_kernel, missing_post_ldb = materialize(
            kernel_payload, missing_post_diagnostic_payload
        )
        missing_post_results = [
            invoke(
                name,
                {
                    "command": "bootstrap",
                    "kernel": missing_post_kernel,
                    "ldb": missing_post_ldb,
                },
            )
            for name in IMPLEMENTATIONS
        ]
        require(
            all(not result["admitted"] for result in missing_post_results)
            and missing_post_results[0]["diagnostic"]
            == missing_post_results[1]["diagnostic"],
            f"missing post-admission Diagnostic was admitted: {reason}",
        )
        deleted_post_diagnostic_results.append(missing_post_results[0])
    vector_results.extend(
        [
            {"id": "default-runtime-profile-closure", "status": "pass"},
            {"id": "package-operation-admission-closure", "status": "pass"},
            {
                "id": "ldb-diagnostic-reverse-closure-all",
                "status": "pass",
                "count": len(deleted_post_diagnostic_results),
            },
        ]
    )

    reordered_kernel_payload = {
        key: kernel_payload[key] for key in reversed(list(kernel_payload))
    }
    reordered_kernel, reordered_ldb = materialize(reordered_kernel_payload, ldb_payload)
    reordered_admissions = bootstrap_all(reordered_kernel, reordered_ldb)
    require(
        reordered_admissions["a"]["kernel_identity"]
        == admissions["a"]["kernel_identity"],
        "map order changed Kernel identity",
    )
    unicode_kernel_payload = copy.deepcopy(kernel_payload)
    unicode_kernel_payload["unicode_identity_vector"] = "é|é|🎮"
    unicode_kernel, unicode_ldb = materialize(unicode_kernel_payload, ldb_payload)
    unicode_admissions = bootstrap_all(unicode_kernel, unicode_ldb)
    require(
        unicode_admissions["a"]["kernel_identity"]
        == unicode_admissions["b"]["kernel_identity"],
        "Unicode canonical identity differs",
    )
    require(
        identity("kernel", source_a) != identity("ldb", source_a),
        "artifact-kind domain separation absent",
    )
    vector_results.append({"id": "canonical-identity", "status": "pass"})

    unknown_opcode_payload = copy.deepcopy(kernel_payload)
    unknown_opcode_payload["laws"]["numeric.checked_add"]["body"]["op"] = (
        "unknown-meta-op"
    )
    unknown_kernel, unknown_ldb = materialize(unknown_opcode_payload, ldb_payload)
    unknown_results = [
        invoke(
            name, {"command": "bootstrap", "kernel": unknown_kernel, "ldb": unknown_ldb}
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in unknown_results)
        and unknown_results[0]["diagnostic"] == unknown_results[1]["diagnostic"],
        "unknown opcode was not a common typed refusal",
    )
    missing_law_payload = copy.deepcopy(kernel_payload)
    missing_law_payload["laws"]["numeric.checked_add"]["body"] = {
        "op": "call_kernel",
        "law": "missing.kernel-law",
        "arguments": {},
    }
    missing_law_kernel, missing_law_ldb = materialize(missing_law_payload, ldb_payload)
    missing_law_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": missing_law_kernel,
                "ldb": missing_law_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in missing_law_results)
        and missing_law_results[0]["diagnostic"]
        == missing_law_results[1]["diagnostic"],
        "missing Kernel law was not a common typed refusal",
    )

    invalid_node_payload = copy.deepcopy(kernel_payload)
    invalid_node_payload["laws"]["numeric.checked_add"]["body"] = {"op": "literal"}
    invalid_node_kernel, invalid_node_ldb = materialize(
        invalid_node_payload, ldb_payload
    )
    invalid_node_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": invalid_node_kernel,
                "ldb": invalid_node_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in invalid_node_results)
        and invalid_node_results[0]["diagnostic"]
        == invalid_node_results[1]["diagnostic"],
        "invalid Kernel node shape was not a common typed refusal",
    )
    missing_kernel_diagnostic_payload = copy.deepcopy(kernel_payload)
    del missing_kernel_diagnostic_payload["admission_diagnostics"]["law_contract"]
    missing_kernel_diagnostic, missing_kernel_diagnostic_ldb = materialize(
        missing_kernel_diagnostic_payload, ldb_payload
    )
    missing_kernel_diagnostic_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": missing_kernel_diagnostic,
                "ldb": missing_kernel_diagnostic_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in missing_kernel_diagnostic_results)
        and missing_kernel_diagnostic_results[0]["diagnostic"]
        == missing_kernel_diagnostic_results[1]["diagnostic"],
        "missing Kernel admission Diagnostic was admitted",
    )
    limited_kernel_payload = copy.deepcopy(kernel_payload)
    limited_kernel_payload["limits"]["max_program_nodes"] = 1
    limited_kernel, limited_ldb = materialize(limited_kernel_payload, ldb_payload)
    limited_results = [
        invoke(
            name, {"command": "bootstrap", "kernel": limited_kernel, "ldb": limited_ldb}
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in limited_results)
        and limited_results[0]["diagnostic"] == limited_results[1]["diagnostic"],
        "program resource limit diverged",
    )
    vector_results.extend(
        [
            {"id": "unknown-opcode", "status": "pass"},
            {"id": "kernel-law-missing", "status": "pass"},
            {"id": "kernel-node-shape-invalid", "status": "pass"},
            {"id": "kernel-diagnostic-reverse-closure", "status": "pass"},
            {"id": "bootstrap-resource-limit", "status": "pass"},
        ]
    )

    compiled_sources: dict[str, dict[str, dict[str, Any]]] = {}
    for source_name, source in (("a", source_a), ("b", source_b)):
        compiled_a, compiled_b, _ = compile_pair(kernel, ldb, source)
        require(
            compiled_a["status"] == "compiled", f"source {source_name} did not compile"
        )
        compiled_sources[source_name] = {"a": compiled_a, "b": compiled_b}
    require(
        canonical_bytes(compiled_sources["a"]["a"]["rir"])
        == canonical_bytes(compiled_sources["b"]["b"]["rir"]),
        "equivalent Source did not converge",
    )
    vector_results.append({"id": "source-to-rir-convergence", "status": "pass"})

    missing_package_source = copy.deepcopy(source_a)
    missing_package_source["package"] = "missing.package@1"
    missing_package_a, missing_package_b, _ = compile_pair(
        kernel, ldb, missing_package_source
    )
    require(
        missing_package_a["status"] == missing_package_b["status"] == "refused"
        and missing_package_a["diagnostic"] == missing_package_b["diagnostic"],
        "unknown Source package was not an LDB-owned typed refusal",
    )

    unselected_operation_payload = copy.deepcopy(ldb_payload)
    del unselected_operation_payload["packages"]["probe.core@1"]["operations"][
        "probe.observe@1"
    ]
    unselected_kernel, unselected_ldb = materialize(
        kernel_payload, unselected_operation_payload
    )
    unselected_a, unselected_b, _ = compile_pair(
        unselected_kernel, unselected_ldb, source_a
    )
    require(
        unselected_a["status"] == unselected_b["status"] == "refused"
        and unselected_a["diagnostic"] == unselected_b["diagnostic"],
        "LDB-present but package-unselected Operation compiled",
    )
    rule_none_source = copy.deepcopy(source_a)
    rule_none_source["events"][0]["kind"] = "unknown-source-node"
    rule_none_a, rule_none_b, _ = compile_pair(kernel, ldb, rule_none_source)
    require(
        rule_none_a["status"] == rule_none_b["status"] == "refused"
        and rule_none_a["diagnostic"] == rule_none_b["diagnostic"],
        "missing Language rule was not a typed refusal",
    )

    parse_refusal_payload = copy.deepcopy(ldb_payload)
    parse_refusal_payload["rules"] = [
        rule
        for rule in parse_refusal_payload["rules"]
        if rule["id"] != "parse.event.v1"
    ]
    parse_refusal_kernel, parse_refusal_ldb = materialize(
        kernel_payload, parse_refusal_payload
    )
    parse_refusal_a, parse_refusal_b, _ = compile_pair(
        parse_refusal_kernel, parse_refusal_ldb, source_a
    )
    require(
        parse_refusal_a["status"] == parse_refusal_b["status"] == "refused"
        and parse_refusal_a["diagnostic"] == parse_refusal_b["diagnostic"],
        "LDB parse refusal rule did not emit its authoritative Diagnostic",
    )
    vector_results.extend(
        [
            {"id": "unknown-source-package", "status": "pass"},
            {"id": "selected-package-operation-closure", "status": "pass"},
            {"id": "source-rule-none", "status": "pass"},
            {"id": "source-parse-invalid", "status": "pass"},
        ]
    )

    exchange_rows: list[dict[str, Any]] = []
    evaluations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for bootstrap_name, source_name in (("a", "a"), ("b", "b")):
        for lowerer in IMPLEMENTATIONS:
            compiled = compile_with(
                lowerer,
                kernel,
                ldb,
                admissions[bootstrap_name],
                source_a if source_name == "a" else source_b,
            )
            require(compiled["status"] == "compiled", "matrix compile refused")
            for evaluator in IMPLEMENTATIONS:
                result = evaluate_with(
                    evaluator, kernel, ldb, compiled, scenario, experiment
                )
                require(
                    result["status"] == "completed",
                    f"matrix evaluation failed: {result}",
                )
                evaluations[(bootstrap_name, lowerer, evaluator)] = result
                exchange_rows.append(
                    {
                        "bootstrap_producer": admissions[bootstrap_name][
                            "implementation"
                        ],
                        "lowerer": compiled["implementation"],
                        "evaluator": result["implementation"],
                        "rir_identity": compiled["rir"]["identity"],
                        "status": result["status"],
                        "consulted_kernel_laws": result["consulted_kernel_laws"],
                        "consulted_ldb_rules": compiled["consulted_ldb_rules"],
                    }
                )
    baseline_a = evaluations[("b", "b", "a")]
    baseline_b = evaluations[("a", "a", "b")]
    require(
        portable(baseline_a, ldb) == portable(baseline_b, ldb),
        "cross evaluator observations differ",
    )
    required_order = [
        "input-0",
        "high",
        "scheduler",
        "child",
        "fifo-a",
        "fifo-b",
        "observe",
    ]
    require(
        [row["event"] for row in baseline_a["trace"]] == required_order,
        "phase/priority/FIFO scheduler order differs from authority",
    )
    require(
        baseline_a["metrics"][-1]["value"] == baseline_a["final_state"]["score"],
        "observation did not see final committed transition state",
    )
    vector_results.append(
        {
            "id": "scheduler-phase-priority-fifo",
            "status": "pass",
            "order": required_order,
        }
    )

    repeated_a = evaluate_with(
        "a", kernel, ldb, compiled_sources["a"]["b"], scenario, experiment
    )
    repeated_b = evaluate_with(
        "b", kernel, ldb, compiled_sources["a"]["a"], scenario, experiment
    )
    baseline_profile_a = resolved_profile(
        "a", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
    )
    baseline_profile_b = resolved_profile(
        "b", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
    )
    replay_a = invoke(
        "a",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            baseline_a,
            repeated_a,
            baseline_profile_a,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    replay_b = invoke(
        "b",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            baseline_b,
            repeated_b,
            baseline_profile_b,
            baseline_profile_b,
            experiment,
            scenario,
        ),
    )
    require(
        replay_a.get("artifact_kind")
        == ldb_payload["comparison_policy"]["replay_artifact_kind"]
        and replay_a.get("matches"),
        "A Replay failed",
    )
    require(
        replay_b.get("artifact_kind")
        == ldb_payload["comparison_policy"]["replay_artifact_kind"]
        and replay_b.get("matches"),
        "B Replay failed",
    )
    cross_a = invoke(
        "a",
        comparison_request(
            "compare_cross",
            kernel,
            ldb,
            baseline_a,
            baseline_b,
            baseline_profile_a,
            baseline_profile_b,
            experiment,
            scenario,
        ),
    )
    cross_b = invoke(
        "b",
        comparison_request(
            "compare_cross",
            kernel,
            ldb,
            baseline_a,
            baseline_b,
            baseline_profile_a,
            baseline_profile_b,
            experiment,
            scenario,
        ),
    )
    require(
        cross_a.get("matches")
        and cross_b.get("matches")
        and "reproducible" not in cross_a
        and "reproducible" not in cross_b
        and "evidence" not in cross_a
        and "evidence" not in cross_b,
        "Cross-evaluator comparison failed",
    )
    comparison_binding_fields = {
        "kernel_identity",
        "ldb_identity",
        "left_run_identity",
        "right_run_identity",
        "left_profile_identity",
        "right_profile_identity",
        "left_resolved_model_identity",
        "right_resolved_model_identity",
        "experiment_identity",
        "scenario_identity",
        "policy_identity",
        "portable_fields",
    }
    for comparison in (replay_a, replay_b, cross_a, cross_b):
        require(
            comparison.get("identity")
            == identity("comparison-artifact", comparison.get("payload"))
            and comparison_binding_fields <= set(comparison["payload"])
            and comparison["payload"]["artifact_kind"] == comparison["artifact_kind"]
            and comparison["payload"]["matches"] == comparison["matches"]
            and "evidence" not in comparison
            and "reproducible" not in comparison,
            f"unsealed or unbound comparison artifact: {comparison}",
        )
    false_replay_a = invoke(
        "a",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            baseline_a,
            baseline_b,
            baseline_profile_a,
            baseline_profile_b,
            experiment,
            scenario,
        ),
    )
    false_replay_b = invoke(
        "b",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            baseline_a,
            baseline_b,
            baseline_profile_a,
            baseline_profile_b,
            experiment,
            scenario,
        ),
    )
    require(
        false_replay_a["status"] == false_replay_b["status"] == "refused",
        "different profiles were accepted as Replay",
    )
    false_cross_a = invoke(
        "a",
        comparison_request(
            "compare_cross",
            kernel,
            ldb,
            baseline_a,
            baseline_a,
            baseline_profile_a,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    false_cross_b = invoke(
        "b",
        comparison_request(
            "compare_cross",
            kernel,
            ldb,
            baseline_a,
            baseline_a,
            baseline_profile_a,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    require(
        false_cross_a["status"] == false_cross_b["status"] == "refused"
        and false_cross_a["diagnostic"] == false_cross_b["diagnostic"],
        "same authority was accepted as Cross-Evaluator Comparison",
    )
    forged_run = copy.deepcopy(baseline_a)
    forged_run["final_state"] = {"score": -1}
    forged_a = invoke(
        "a",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            forged_run,
            repeated_a,
            baseline_profile_a,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    forged_b = invoke(
        "b",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            forged_run,
            repeated_a,
            baseline_profile_a,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    require(
        forged_a["status"] == forged_b["status"] == "refused"
        and forged_a["diagnostic"] == forged_b["diagnostic"],
        "comparison trusted forged Run content",
    )
    forged_profile = copy.deepcopy(baseline_profile_a)
    forged_profile["payload"]["evaluator"] = "forged"
    forged_profile_a = invoke(
        "a",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            baseline_a,
            repeated_a,
            forged_profile,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    forged_profile_b = invoke(
        "b",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            baseline_a,
            repeated_a,
            forged_profile,
            baseline_profile_a,
            experiment,
            scenario,
        ),
    )
    require(
        forged_profile_a["status"] == forged_profile_b["status"] == "refused"
        and forged_profile_a["diagnostic"] == forged_profile_b["diagnostic"],
        "comparison trusted forged Profile content",
    )
    coherent_profile = copy.deepcopy(baseline_profile_a)
    coherent_profile["payload"]["definition_identity"] = "sha256:coherent-forgery"
    coherent_profile["identity"] = identity(
        "resolved-profile", coherent_profile["payload"]
    )
    coherent_run = copy.deepcopy(baseline_a)
    coherent_run["resolved_profile_identity"] = coherent_profile["identity"]
    coherent_run["reproduction_identity"][3] = coherent_profile["identity"]
    coherent_run_payload = {
        key: value for key, value in coherent_run.items() if key != "run_identity"
    }
    coherent_run["run_identity"] = identity("evaluation-run", coherent_run_payload)
    coherent_profile_a = invoke(
        "a",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            coherent_run,
            coherent_run,
            coherent_profile,
            coherent_profile,
            experiment,
            scenario,
        ),
    )
    coherent_profile_b = invoke(
        "b",
        comparison_request(
            "compare_replay",
            kernel,
            ldb,
            coherent_run,
            coherent_run,
            coherent_profile,
            coherent_profile,
            experiment,
            scenario,
        ),
    )
    require(
        coherent_profile_a["status"] == coherent_profile_b["status"] == "refused"
        and coherent_profile_a["diagnostic"] == coherent_profile_b["diagnostic"],
        "comparison trusted reidentified wrong Runtime Profile definition",
    )
    vector_results.extend(
        [
            {"id": "replay-cross-evaluator-split", "status": "pass"},
            {"id": "sealed-comparison-bindings", "status": "pass"},
            {"id": "comparison-run-rehash", "status": "pass"},
            {"id": "comparison-profile-rehash", "status": "pass"},
            {"id": "comparison-profile-definition-binding", "status": "pass"},
            {"id": "cross-authority-refusal", "status": "pass"},
        ]
    )

    refusal_a_compiled, refusal_b_compiled, _ = compile_pair(
        kernel, ldb, source_refusal
    )
    refusal_a = evaluate_with(
        "a", kernel, ldb, refusal_b_compiled, scenario, experiment
    )
    refusal_b = evaluate_with(
        "b", kernel, ldb, refusal_a_compiled, scenario, experiment
    )
    require(
        refusal_a["status"] == refusal_b["status"] == "runtime_refusal",
        "atomic refusal vector did not refuse",
    )
    require(
        refusal_a["final_state"] == refusal_b["final_state"]
        and refusal_a["final_state"] != scenario["initial_state"],
        "prior commit was not preserved",
    )
    for result in (refusal_a, refusal_b):
        discarded = result["terminal_audit"]["payload"]["discarded"]
        require(
            discarded["writes"]
            and discarded["rng_draws"]
            and discarded["signals"]
            and discarded["children"],
            "terminal audit omitted rollback buffers",
        )
    vector_results.append({"id": "atomic-terminal-rollback", "status": "pass"})

    overflow_a = evaluate_with(
        "a", kernel, ldb, compiled_sources["a"]["b"], scenario_overflow, experiment
    )
    overflow_b = evaluate_with(
        "b", kernel, ldb, compiled_sources["a"]["a"], scenario_overflow, experiment
    )
    require(
        overflow_a["status"] == overflow_b["status"] == "runtime_refusal",
        "Int64 overflow did not refuse",
    )
    require(
        overflow_a["diagnostic"] == overflow_b["diagnostic"],
        "overflow diagnostics differ",
    )
    vector_results.append({"id": "int64-overflow", "status": "pass"})

    backward = copy.deepcopy(source_a)
    backward["events"][2]["arguments"]["child_priority"] = 99
    backward_a_compiled, backward_b_compiled, _ = compile_pair(kernel, ldb, backward)
    backward_a = evaluate_with(
        "a", kernel, ldb, backward_b_compiled, scenario, experiment
    )
    backward_b = evaluate_with(
        "b", kernel, ldb, backward_a_compiled, scenario, experiment
    )
    require(
        backward_a["status"] == backward_b["status"] == "runtime_refusal",
        "backward schedule accepted",
    )
    require(
        backward_a["diagnostic"] == backward_b["diagnostic"],
        "scheduler refusal differs",
    )
    vector_results.append({"id": "backward-schedule-refusal", "status": "pass"})

    invalid_bound = copy.deepcopy(source_a)
    invalid_bound["events"][1]["arguments"]["bound"] = 0
    invalid_bound_a, invalid_bound_b, _ = compile_pair(kernel, ldb, invalid_bound)
    invalid_run_a = evaluate_with(
        "a", kernel, ldb, invalid_bound_b, scenario, experiment
    )
    invalid_run_b = evaluate_with(
        "b", kernel, ldb, invalid_bound_a, scenario, experiment
    )
    require(
        invalid_run_a["status"] == invalid_run_b["status"] == "runtime_refusal"
        and invalid_run_a["diagnostic"] == invalid_run_b["diagnostic"],
        "invalid RNG bound diverged",
    )

    bool_source = copy.deepcopy(source_a)
    bool_source["events"][1]["arguments"]["delta"] = True
    bool_a, bool_b, _ = compile_pair(kernel, ldb, bool_source)
    require(
        bool_a["status"] == bool_b["status"] == "refused"
        and bool_a["diagnostic"] == bool_b["diagnostic"],
        "Bool was accepted as Int",
    )

    unknown_source = copy.deepcopy(source_a)
    unknown_source["events"][1]["operation"] = "not-selected-operation"
    unknown_a, unknown_b, _ = compile_pair(kernel, ldb, unknown_source)
    require(
        unknown_a["status"] == unknown_b["status"] == "refused"
        and unknown_a["diagnostic"] == unknown_b["diagnostic"],
        "unknown operation did not refuse",
    )

    effect_ldb_payload = copy.deepcopy(ldb_payload)
    effect_ldb_payload["operations"]["probe.add-random@1"]["effects"].remove(
        "signal.emit"
    )
    effect_kernel, effect_ldb = materialize(kernel_payload, effect_ldb_payload)
    effect_a, effect_b, _ = compile_pair(effect_kernel, effect_ldb, source_a)
    require(
        effect_a["status"] == effect_b["status"] == "refused"
        and effect_a["diagnostic"] == effect_b["diagnostic"],
        "undeclared effect reached RIR",
    )

    restricted_ldb_payload = copy.deepcopy(ldb_payload)
    restricted_ldb_payload["runtime_profiles"]["portable-exact-v1"][
        "allowed_effects"
    ].remove("signal.emit")
    restricted_kernel, restricted_ldb = materialize(
        kernel_payload, restricted_ldb_payload
    )
    restricted_a, restricted_b, _ = compile_pair(
        restricted_kernel, restricted_ldb, source_a
    )
    restricted_run_a = evaluate_with(
        "a", restricted_kernel, restricted_ldb, restricted_b, scenario, experiment
    )
    restricted_run_b = evaluate_with(
        "b", restricted_kernel, restricted_ldb, restricted_a, scenario, experiment
    )
    require(
        restricted_run_a["status"] == restricted_run_b["status"] == "runtime_refusal"
        and restricted_run_a["diagnostic"] == restricted_run_b["diagnostic"],
        "profile effect restriction diverged",
    )

    budget_ldb_payload = copy.deepcopy(ldb_payload)
    budget_ldb_payload["runtime_profiles"]["portable-exact-v1"]["budgets"][
        "max_draws"
    ] = 1
    budget_kernel, budget_ldb = materialize(kernel_payload, budget_ldb_payload)
    budget_a, budget_b, _ = compile_pair(budget_kernel, budget_ldb, source_a)
    budget_run_a = evaluate_with(
        "a", budget_kernel, budget_ldb, budget_b, scenario, experiment
    )
    budget_run_b = evaluate_with(
        "b", budget_kernel, budget_ldb, budget_a, scenario, experiment
    )
    require(
        budget_run_a["status"] == budget_run_b["status"] == "runtime_refusal"
        and budget_run_a["diagnostic"] == budget_run_b["diagnostic"],
        "RNG draw budget diverged",
    )

    event_budget_ldb_payload = copy.deepcopy(ldb_payload)
    event_budget_ldb_payload["runtime_profiles"]["portable-exact-v1"]["budgets"][
        "max_events"
    ] = 0
    event_budget_kernel, event_budget_ldb = materialize(
        kernel_payload, event_budget_ldb_payload
    )
    event_budget_a, event_budget_b, _ = compile_pair(
        event_budget_kernel, event_budget_ldb, source_a
    )
    event_budget_run_a = evaluate_with(
        "a", event_budget_kernel, event_budget_ldb, event_budget_b, scenario, experiment
    )
    event_budget_run_b = evaluate_with(
        "b", event_budget_kernel, event_budget_ldb, event_budget_a, scenario, experiment
    )
    require(
        event_budget_run_a["status"]
        == event_budget_run_b["status"]
        == "runtime_refusal"
        and event_budget_run_a["diagnostic"] == event_budget_run_b["diagnostic"]
        and "terminal_audit" in event_budget_run_a
        and "terminal_audit" in event_budget_run_b,
        "event budget was not a typed terminal refusal",
    )

    queue_budget_ldb_payload = copy.deepcopy(ldb_payload)
    queue_budget_ldb_payload["runtime_profiles"]["portable-exact-v1"]["budgets"][
        "max_queue"
    ] = 0
    queue_budget_kernel, queue_budget_ldb = materialize(
        kernel_payload, queue_budget_ldb_payload
    )
    queue_budget_a, queue_budget_b, _ = compile_pair(
        queue_budget_kernel, queue_budget_ldb, source_a
    )
    queue_budget_run_a = evaluate_with(
        "a", queue_budget_kernel, queue_budget_ldb, queue_budget_b, scenario, experiment
    )
    queue_budget_run_b = evaluate_with(
        "b", queue_budget_kernel, queue_budget_ldb, queue_budget_a, scenario, experiment
    )
    require(
        queue_budget_run_a["status"]
        == queue_budget_run_b["status"]
        == "runtime_refusal"
        and queue_budget_run_a["diagnostic"] == queue_budget_run_b["diagnostic"]
        and queue_budget_run_a["terminal_audit"]["payload"]["discarded"]["children"]
        == []
        and queue_budget_run_b["terminal_audit"]["payload"]["discarded"]["children"]
        == [],
        "queue budget was not checked before child buffering",
    )

    rule_budget_kernel_payload = copy.deepcopy(kernel_payload)
    rule_budget_kernel_payload["limits"]["max_rule_steps"] = 1
    rule_budget_kernel, rule_budget_ldb = materialize(
        rule_budget_kernel_payload, ldb_payload
    )
    rule_budget_admissions = bootstrap_all(rule_budget_kernel, rule_budget_ldb)
    rule_budget_a = compile_with(
        "a", rule_budget_kernel, rule_budget_ldb, rule_budget_admissions["b"], source_a
    )
    rule_budget_b = compile_with(
        "b", rule_budget_kernel, rule_budget_ldb, rule_budget_admissions["a"], source_a
    )
    require(
        rule_budget_a["status"] == rule_budget_b["status"] == "refused"
        and rule_budget_a["diagnostic"] == rule_budget_b["diagnostic"],
        "rule-step budget was not a typed static refusal",
    )

    multi_draw_source = copy.deepcopy(source_a)
    second_combat = copy.deepcopy(multi_draw_source["events"][3])
    second_combat["id"] = "combat-second"
    second_combat["priority"] = 1
    second_combat["arguments"]["stream"] = "combat"
    multi_draw_source["events"].insert(3, second_combat)
    multi_a, multi_b, _ = compile_pair(kernel, ldb, multi_draw_source)
    multi_run_a = evaluate_with("a", kernel, ldb, multi_b, scenario, experiment)
    multi_run_b = evaluate_with("b", kernel, ldb, multi_a, scenario, experiment)
    combat_draws_a = [
        draw for draw in multi_run_a["rng_trace"] if draw["stream"] == "combat"
    ]
    combat_draws_b = [
        draw for draw in multi_run_b["rng_trace"] if draw["stream"] == "combat"
    ]
    baseline_combat = next(
        draw for draw in baseline_a["rng_trace"] if draw["stream"] == "combat"
    )
    require(
        len(combat_draws_a) == len(combat_draws_b) == 2
        and combat_draws_a == combat_draws_b
        and combat_draws_a[0] == baseline_combat,
        "Named-stream multi-draw/isolation failed",
    )

    snapshot_source = {
        "artifact_kind": source_a["artifact_kind"],
        "package": source_a["package"],
        "aliases": {},
        "events": [
            {
                "kind": "event",
                "id": "write-read",
                "time": 0,
                "phase": "transition",
                "priority": 0,
                "operation": "probe.write-read@1",
                "arguments": {
                    "metric": "snapshot.read",
                    "target": "score",
                    "value": 77,
                },
            }
        ],
    }
    snapshot_a, snapshot_b, _ = compile_pair(kernel, ldb, snapshot_source)
    snapshot_run_a = evaluate_with("a", kernel, ldb, snapshot_b, scenario, experiment)
    snapshot_run_b = evaluate_with("b", kernel, ldb, snapshot_a, scenario, experiment)
    require(
        snapshot_run_a["status"] == snapshot_run_b["status"] == "completed"
        and snapshot_run_a["final_state"]["score"] == 77
        and snapshot_run_a["metrics"][0]["value"] == 10
        and portable(snapshot_run_a, ldb) == portable(snapshot_run_b, ldb),
        "same-event read observed buffered write",
    )

    tampered_rir = copy.deepcopy(compiled_sources["a"]["a"]["rir"])
    tampered_rir["payload"]["events"][0]["priority"] += 1
    tampered_a = invoke(
        "a",
        {
            "command": "evaluate",
            "kernel": kernel,
            "ldb": ldb,
            "rir": tampered_rir,
            "resolved_model": compiled_sources["a"]["a"]["resolved_model"],
            "resolved_profile": resolved_profile(
                "a", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
            ),
            "scenario": scenario,
            "experiment": experiment,
        },
    )
    tampered_b = invoke(
        "b",
        {
            "command": "evaluate",
            "kernel": kernel,
            "ldb": ldb,
            "rir": tampered_rir,
            "resolved_model": compiled_sources["a"]["a"]["resolved_model"],
            "resolved_profile": resolved_profile(
                "b", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
            ),
            "scenario": scenario,
            "experiment": experiment,
        },
    )
    require(
        tampered_a["status"] == tampered_b["status"] == "refused"
        and tampered_a["diagnostic"] == tampered_b["diagnostic"],
        "tampered RIR identity was trusted",
    )

    projected_a = copy.deepcopy(compiled_sources["a"]["a"])
    first_operation = next(iter(projected_a["rir"]["payload"]["operation_table"]))
    projected_a["rir"]["payload"]["operation_table"][first_operation]["effects"] = []
    projected_a["rir"]["identity"] = identity("rir", projected_a["rir"]["payload"])
    projected_a["resolved_model"]["payload"]["rir_identity"] = projected_a["rir"][
        "identity"
    ]
    projected_a["resolved_model"]["identity"] = identity(
        "resolved-model", projected_a["resolved_model"]["payload"]
    )
    projection_run_a = evaluate_with(
        "a", kernel, ldb, projected_a, scenario, experiment
    )
    projection_run_b = evaluate_with(
        "b", kernel, ldb, projected_a, scenario, experiment
    )
    require(
        projection_run_a["status"] == projection_run_b["status"] == "refused"
        and projection_run_a["diagnostic"] == projection_run_b["diagnostic"],
        "reidentified inconsistent Operation projection executed",
    )

    runtime_projection = copy.deepcopy(compiled_sources["a"]["a"])
    runtime_projection["rir"]["payload"]["runtime_profile_definition"]["budgets"][
        "max_events"
    ] += 1
    runtime_projection["rir"]["identity"] = identity(
        "rir", runtime_projection["rir"]["payload"]
    )
    runtime_projection["resolved_model"]["payload"]["rir_identity"] = (
        runtime_projection["rir"]["identity"]
    )
    runtime_projection["resolved_model"]["identity"] = identity(
        "resolved-model", runtime_projection["resolved_model"]["payload"]
    )
    runtime_projection_run_a = evaluate_with(
        "a", kernel, ldb, runtime_projection, scenario, experiment
    )
    runtime_projection_run_b = evaluate_with(
        "b", kernel, ldb, runtime_projection, scenario, experiment
    )
    require(
        runtime_projection_run_a["status"]
        == runtime_projection_run_b["status"]
        == "refused"
        and runtime_projection_run_a["diagnostic"]
        == runtime_projection_run_b["diagnostic"],
        "reidentified inconsistent Runtime Profile projection executed",
    )

    coherent_eval_profile_a = resolved_profile(
        "a", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
    )
    coherent_eval_profile_a["payload"]["definition_identity"] = (
        "sha256:wrong-runtime-definition"
    )
    coherent_eval_profile_a["identity"] = identity(
        "resolved-profile", coherent_eval_profile_a["payload"]
    )
    coherent_eval_profile_b = resolved_profile(
        "b", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
    )
    coherent_eval_profile_b["payload"]["definition_identity"] = (
        "sha256:wrong-runtime-definition"
    )
    coherent_eval_profile_b["identity"] = identity(
        "resolved-profile", coherent_eval_profile_b["payload"]
    )
    coherent_eval_a = invoke(
        "a",
        {
            "command": "evaluate",
            "kernel": kernel,
            "ldb": ldb,
            "rir": compiled_sources["a"]["a"]["rir"],
            "resolved_model": compiled_sources["a"]["a"]["resolved_model"],
            "resolved_profile": coherent_eval_profile_a,
            "scenario": scenario,
            "experiment": experiment,
        },
    )
    coherent_eval_b = invoke(
        "b",
        {
            "command": "evaluate",
            "kernel": kernel,
            "ldb": ldb,
            "rir": compiled_sources["a"]["a"]["rir"],
            "resolved_model": compiled_sources["a"]["a"]["resolved_model"],
            "resolved_profile": coherent_eval_profile_b,
            "scenario": scenario,
            "experiment": experiment,
        },
    )
    require(
        coherent_eval_a["status"] == coherent_eval_b["status"] == "refused"
        and coherent_eval_a["diagnostic"]["code"]
        == coherent_eval_b["diagnostic"]["code"]
        and coherent_eval_a["diagnostic"]["stage"]
        == coherent_eval_b["diagnostic"]["stage"],
        "reidentified wrong Resolved Runtime Profile executed",
    )

    ambiguous_ldb_payload = copy.deepcopy(ldb_payload)
    duplicate_rule = copy.deepcopy(ambiguous_ldb_payload["rules"][0])
    duplicate_rule["id"] = "duplicate-selection-vector"
    ambiguous_ldb_payload["rules"].append(duplicate_rule)
    ambiguous_kernel, ambiguous_ldb = materialize(kernel_payload, ambiguous_ldb_payload)
    ambiguous_admissions = bootstrap_all(ambiguous_kernel, ambiguous_ldb)
    ambiguous_a = compile_with(
        "a", ambiguous_kernel, ambiguous_ldb, ambiguous_admissions["b"], source_a
    )
    ambiguous_b = compile_with(
        "b", ambiguous_kernel, ambiguous_ldb, ambiguous_admissions["a"], source_a
    )
    require(
        ambiguous_a["status"] == ambiguous_b["status"] == "refused"
        and ambiguous_a["diagnostic"] == ambiguous_b["diagnostic"],
        "ambiguous rule selection did not refuse",
    )

    parameter_contract_payload = copy.deepcopy(kernel_payload)
    parameter_contract_payload["laws"]["numeric.checked_add"]["parameters"]["ghost"] = (
        "Any"
    )
    parameter_kernel, parameter_ldb = materialize(
        parameter_contract_payload, ldb_payload
    )
    parameter_a, parameter_b, _ = compile_pair(
        parameter_kernel, parameter_ldb, source_a
    )
    parameter_run_a = evaluate_with(
        "a", parameter_kernel, parameter_ldb, parameter_b, scenario, experiment
    )
    parameter_run_b = evaluate_with(
        "b", parameter_kernel, parameter_ldb, parameter_a, scenario, experiment
    )
    require(
        parameter_run_a["status"] == parameter_run_b["status"] == "runtime_refusal"
        and parameter_run_a["diagnostic"] == parameter_run_b["diagnostic"]
        and parameter_run_a["diagnostic"]["code"]
        == kernel_payload["admission_diagnostics"]["law_contract"]["code"],
        "Kernel parameter contract mutation was ignored",
    )

    effect_contract_payload = copy.deepcopy(kernel_payload)
    effect_contract_payload["laws"]["numeric.checked_add"]["effects"] = ["state.read"]
    effect_contract_kernel, effect_contract_ldb = materialize(
        effect_contract_payload, ldb_payload
    )
    effect_contract_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": effect_contract_kernel,
                "ldb": effect_contract_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in effect_contract_results)
        and effect_contract_results[0]["diagnostic"]
        == effect_contract_results[1]["diagnostic"],
        "Kernel effect contract mutation was ignored",
    )

    refusal_contract_payload = copy.deepcopy(kernel_payload)
    refusal_contract_payload["laws"]["numeric.checked_add"]["refusals"].append(
        "not_declared_by_program"
    )
    refusal_contract_kernel, refusal_contract_ldb = materialize(
        refusal_contract_payload, ldb_payload
    )
    refusal_contract_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": refusal_contract_kernel,
                "ldb": refusal_contract_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in refusal_contract_results)
        and refusal_contract_results[0]["diagnostic"]
        == refusal_contract_results[1]["diagnostic"],
        "Kernel refusal contract mutation was ignored",
    )

    resource_contract_payload = copy.deepcopy(kernel_payload)
    resource_contract_payload["laws"]["numeric.checked_add"]["resource_accounting"][
        "maximum"
    ] = 1
    resource_contract_kernel, resource_contract_ldb = materialize(
        resource_contract_payload, ldb_payload
    )
    resource_contract_a, resource_contract_b, _ = compile_pair(
        resource_contract_kernel, resource_contract_ldb, source_a
    )
    resource_contract_run_a = evaluate_with(
        "a",
        resource_contract_kernel,
        resource_contract_ldb,
        resource_contract_b,
        scenario,
        experiment,
    )
    resource_contract_run_b = evaluate_with(
        "b",
        resource_contract_kernel,
        resource_contract_ldb,
        resource_contract_a,
        scenario,
        experiment,
    )
    require(
        resource_contract_run_a["status"]
        == resource_contract_run_b["status"]
        == "runtime_refusal"
        and resource_contract_run_a["diagnostic"]
        == resource_contract_run_b["diagnostic"]
        and resource_contract_run_a["diagnostic"]["code"]
        == kernel_payload["admission_diagnostics"]["law_contract"]["code"],
        "Kernel resource contract mutation was ignored",
    )

    unknown_wire_payload = copy.deepcopy(ldb_payload)
    unknown_wire_payload["operations"]["probe.add-random@1"]["signature"]["delta"] = (
        "HostPrivateNumber"
    )
    unknown_wire_kernel, unknown_wire_ldb = materialize(
        kernel_payload, unknown_wire_payload
    )
    unknown_wire_results = [
        invoke(
            name,
            {
                "command": "bootstrap",
                "kernel": unknown_wire_kernel,
                "ldb": unknown_wire_ldb,
            },
        )
        for name in IMPLEMENTATIONS
    ]
    require(
        all(not result["admitted"] for result in unknown_wire_results)
        and unknown_wire_results[0]["diagnostic"]
        == unknown_wire_results[1]["diagnostic"],
        "unknown wire type escaped the Kernel root",
    )

    wire_values: dict[str, Any] = {
        "Any": {"any": [1]},
        "Value": ["value"],
        "Unit": None,
        "Int": 1,
        "Str": "text",
        "Bool": True,
        "Record": {"field": 1},
        "List": [1, 2],
    }
    for wire_type, value in wire_values.items():
        wire_ldb_payload = copy.deepcopy(ldb_payload)
        wire_ldb_payload["operations"]["probe.noop@1"]["signature"] = {
            "value": wire_type
        }
        wire_kernel, wire_ldb = materialize(kernel_payload, wire_ldb_payload)
        wire_source = {
            "artifact_kind": source_a["artifact_kind"],
            "package": source_a["package"],
            "aliases": {},
            "events": [
                {
                    "kind": "event",
                    "id": f"wire-{wire_type}",
                    "time": 0,
                    "phase": "transition",
                    "priority": 0,
                    "operation": "probe.noop@1",
                    "arguments": {"value": value},
                }
            ],
        }
        wire_a, wire_b, _ = compile_pair(wire_kernel, wire_ldb, wire_source)
        require(
            wire_a["status"] == wire_b["status"] == "compiled",
            f"admitted wire type rejected by argument matcher: {wire_type}",
        )

    transitive_kernel_payload = copy.deepcopy(kernel_payload)
    transitive_kernel_payload["laws"]["probe.hidden_read"] = {
        "parameters": {"path": "Str"},
        "result": "Value",
        "effects": ["state.read"],
        "refusals": [],
        "resource_accounting": {"unit": "vm_step", "maximum": 16},
        "body": {
            "op": "effect",
            "kind": "state.read",
            "arguments": {"path": {"op": "var", "name": "path"}},
        },
    }
    transitive_ldb_payload = copy.deepcopy(ldb_payload)
    transitive_ldb_payload["required_kernel_laws"].append("probe.hidden_read")
    transitive_ldb_payload["operations"]["probe.observe@1"]["effects"] = []
    transitive_ldb_payload["operations"]["probe.observe@1"]["body"] = {
        "op": "call_kernel",
        "law": "probe.hidden_read",
        "arguments": {"path": {"op": "var", "name": "target"}},
    }
    transitive_kernel, transitive_ldb = materialize(
        transitive_kernel_payload, transitive_ldb_payload
    )
    transitive_a, transitive_b, _ = compile_pair(
        transitive_kernel, transitive_ldb, source_a
    )
    require(
        transitive_a["status"] == transitive_b["status"] == "refused"
        and transitive_a["diagnostic"] == transitive_b["diagnostic"],
        "transitive call_kernel effect escaped effect closure",
    )

    vector_results.extend(
        [
            {"id": "rng-invalid-bound", "status": "pass"},
            {"id": "bool-is-not-int", "status": "pass"},
            {"id": "unknown-operation", "status": "pass"},
            {"id": "static-effect-closure", "status": "pass"},
            {"id": "runtime-effect-profile", "status": "pass"},
            {"id": "rng-draw-budget", "status": "pass"},
            {"id": "event-budget-terminal-refusal", "status": "pass"},
            {"id": "queue-budget-terminal-refusal", "status": "pass"},
            {"id": "rule-step-budget-static-refusal", "status": "pass"},
            {
                "id": "rng-multi-draw-stream-isolation",
                "status": "pass",
                "combat_draws": combat_draws_a,
            },
            {"id": "same-event-pre-snapshot", "status": "pass"},
            {"id": "rir-tamper-refusal", "status": "pass"},
            {"id": "operation-projection-refusal", "status": "pass"},
            {"id": "runtime-profile-projection-refusal", "status": "pass"},
            {"id": "resolved-profile-definition-refusal", "status": "pass"},
            {"id": "ambiguous-rule-selection", "status": "pass"},
            {"id": "kernel-law-parameter-contract", "status": "pass"},
            {"id": "kernel-law-effect-contract", "status": "pass"},
            {"id": "kernel-law-refusal-contract", "status": "pass"},
            {"id": "kernel-law-resource-contract", "status": "pass"},
            {"id": "kernel-wire-type-root", "status": "pass"},
            {"id": "all-admitted-wire-types", "status": "pass"},
            {"id": "transitive-kernel-effect-closure", "status": "pass"},
        ]
    )

    mutation_rows: list[dict[str, Any]] = []
    consulted_laws = sorted(
        set(baseline_a["consulted_kernel_laws"])
        | set(replay_a.get("consulted_kernel_laws", []))
        | set(compiled_sources["a"]["a"]["consulted_kernel_laws"])
        | set(compiled_sources["a"]["b"]["consulted_kernel_laws"])
    )
    consulted_rules = sorted(set(compiled_sources["a"]["a"]["consulted_ldb_rules"]))
    for law_id in consulted_laws:
        tampered_payload = mutate_law(kernel_payload, law_id, "tamper")
        tampered_kernel = {"payload": tampered_payload, "identity": kernel["identity"]}
        tampered_results = [
            invoke(
                name, {"command": "bootstrap", "kernel": tampered_kernel, "ldb": ldb}
            )
            for name in IMPLEMENTATIONS
        ]
        require(
            all(not result["admitted"] for result in tampered_results),
            f"tampered law accepted: {law_id}",
        )
        require(
            tampered_results[0]["diagnostic"] == tampered_results[1]["diagnostic"],
            f"tamper diagnostic differs: {law_id}",
        )

        deleted_kernel, deleted_ldb = materialize(
            mutate_law(kernel_payload, law_id, "delete"), ldb_payload
        )
        deleted_results = [
            invoke(
                name,
                {"command": "bootstrap", "kernel": deleted_kernel, "ldb": deleted_ldb},
            )
            for name in IMPLEMENTATIONS
        ]
        require(
            all(not result["admitted"] for result in deleted_results),
            f"deleted law accepted: {law_id}",
        )
        require(
            deleted_results[0]["diagnostic"] == deleted_results[1]["diagnostic"],
            f"delete diagnostic differs: {law_id}",
        )

        changed_kernel, changed_ldb = materialize(
            mutate_law(kernel_payload, law_id, "behavior"), ldb_payload
        )
        changed_a, changed_b, _ = compile_pair(changed_kernel, changed_ldb, source_a)
        if changed_a["status"] != "compiled":
            changed = changed_a["diagnostic"] == changed_b["diagnostic"]
            witness = changed_a["diagnostic"]["code"]
        elif law_id.endswith("replay_compatible"):
            changed_run_a = evaluate_with(
                "a", changed_kernel, changed_ldb, changed_b, scenario, experiment
            )
            changed_profile = resolved_profile(
                "a", changed_kernel, changed_ldb, changed_b["resolved_model"]
            )
            changed_replay = invoke(
                "a",
                comparison_request(
                    "compare_replay",
                    changed_kernel,
                    changed_ldb,
                    changed_run_a,
                    changed_run_a,
                    changed_profile,
                    changed_profile,
                    experiment,
                    scenario,
                ),
            )
            changed = changed_replay["status"] == "refused"
            witness = changed_replay["status"]
        else:
            changed_run_a = evaluate_with(
                "a", changed_kernel, changed_ldb, changed_b, scenario, experiment
            )
            changed_run_b = evaluate_with(
                "b", changed_kernel, changed_ldb, changed_a, scenario, experiment
            )
            require(
                portable(changed_run_a, changed_ldb)
                == portable(changed_run_b, changed_ldb),
                f"mutated law diverged: {law_id}",
            )
            changed = portable(changed_run_a, changed_ldb) != portable(baseline_a, ldb)
            witness = changed_run_a["status"]
        require(changed, f"used law mutation had no observable witness: {law_id}")

        contract_payload = copy.deepcopy(kernel_payload)
        original_result = contract_payload["laws"][law_id]["result"]
        contract_payload["laws"][law_id]["result"] = (
            "Record" if original_result != "Record" else "Bool"
        )
        contract_kernel, contract_ldb = materialize(contract_payload, ldb_payload)
        contract_a, contract_b, _ = compile_pair(
            contract_kernel, contract_ldb, source_a
        )
        if contract_a["status"] != "compiled":
            contract_closed = contract_a["diagnostic"] == contract_b["diagnostic"]
            contract_witness = contract_a["diagnostic"]["code"]
        else:
            contract_run_a = evaluate_with(
                "a", contract_kernel, contract_ldb, contract_b, scenario, experiment
            )
            contract_run_b = evaluate_with(
                "b", contract_kernel, contract_ldb, contract_a, scenario, experiment
            )
            if law_id.endswith("replay_compatible"):
                contract_profile_a = resolved_profile(
                    "a", contract_kernel, contract_ldb, contract_b["resolved_model"]
                )
                contract_compare_a = invoke(
                    "a",
                    comparison_request(
                        "compare_replay",
                        contract_kernel,
                        contract_ldb,
                        contract_run_a,
                        contract_run_a,
                        contract_profile_a,
                        contract_profile_a,
                        experiment,
                        scenario,
                    ),
                )
                contract_profile_b = resolved_profile(
                    "b", contract_kernel, contract_ldb, contract_a["resolved_model"]
                )
                contract_compare_b = invoke(
                    "b",
                    comparison_request(
                        "compare_replay",
                        contract_kernel,
                        contract_ldb,
                        contract_run_b,
                        contract_run_b,
                        contract_profile_b,
                        contract_profile_b,
                        experiment,
                        scenario,
                    ),
                )
                contract_closed = (
                    contract_compare_a["status"]
                    == contract_compare_b["status"]
                    == "refused"
                    and contract_compare_a["diagnostic"]
                    == contract_compare_b["diagnostic"]
                )
                contract_witness = contract_compare_a["diagnostic"]["code"]
            else:
                contract_closed = (
                    contract_run_a["status"] == contract_run_b["status"]
                    and contract_run_a["status"] in {"runtime_refusal", "refused"}
                    and contract_run_a["diagnostic"] == contract_run_b["diagnostic"]
                )
                contract_witness = contract_run_a["diagnostic"]["code"]
        require(contract_closed, f"used law contract mutation was ignored: {law_id}")
        mutation_rows.append(
            {
                "authority": "kernel",
                "id": law_id,
                "tamper": "refused",
                "deletion": "refused",
                "behavior": witness,
                "contract": contract_witness,
                "pass": True,
            }
        )
    vector_results.append(
        {
            "id": "kernel-law-result-contract-all-consulted",
            "status": "pass",
            "count": len(consulted_laws),
        }
    )

    for rule_id in consulted_rules:
        tampered_ldb_payload = mutate_rule(ldb_payload, rule_id, "tamper")
        tampered_ldb = {
            "payload": {**tampered_ldb_payload, "kernel_identity": kernel["identity"]},
            "identity": ldb["identity"],
        }
        tampered_results = [
            invoke(
                name, {"command": "bootstrap", "kernel": kernel, "ldb": tampered_ldb}
            )
            for name in IMPLEMENTATIONS
        ]
        require(
            all(not result["admitted"] for result in tampered_results),
            f"tampered rule accepted: {rule_id}",
        )

        deleted_kernel, deleted_ldb = materialize(
            kernel_payload, mutate_rule(ldb_payload, rule_id, "delete")
        )
        deleted_results = [
            invoke(
                name,
                {"command": "bootstrap", "kernel": deleted_kernel, "ldb": deleted_ldb},
            )
            for name in IMPLEMENTATIONS
        ]
        if all(not result["admitted"] for result in deleted_results):
            require(
                deleted_results[0]["diagnostic"] == deleted_results[1]["diagnostic"],
                f"deleted rule admission diverged: {rule_id}",
            )
        else:
            require(
                all(result["admitted"] for result in deleted_results),
                f"deleted rule admission split: {rule_id}",
            )
            deleted_admissions = {
                name: result for name, result in zip(IMPLEMENTATIONS, deleted_results)
            }
            deleted_a = compile_with(
                "a", deleted_kernel, deleted_ldb, deleted_admissions["b"], source_a
            )
            deleted_b = compile_with(
                "b", deleted_kernel, deleted_ldb, deleted_admissions["a"], source_a
            )
            require(
                deleted_a["status"] == deleted_b["status"] == "refused"
                and deleted_a["diagnostic"] == deleted_b["diagnostic"],
                f"deleted rule fallback: {rule_id}",
            )

        changed_kernel, changed_ldb = materialize(
            kernel_payload, mutate_rule(ldb_payload, rule_id, "behavior")
        )
        changed_a, changed_b, _ = compile_pair(changed_kernel, changed_ldb, source_a)
        if changed_a["status"] == "compiled":
            changed = (
                changed_a["rir"]["identity"]
                != compiled_sources["a"]["a"]["rir"]["identity"]
            )
            witness = "rir_changed"
        else:
            changed = changed_a["diagnostic"] == changed_b["diagnostic"]
            witness = changed_a["diagnostic"]["code"]
        require(changed, f"used rule mutation had no witness: {rule_id}")
        mutation_rows.append(
            {
                "authority": "ldb",
                "id": rule_id,
                "tamper": "refused",
                "deletion": "refused",
                "behavior": witness,
                "pass": True,
            }
        )

    renamed_ldb_payload, renamed_source, renamed_scenario = rename_authority(
        ldb_payload, source_a, scenario
    )
    renamed_kernel, renamed_ldb = materialize(kernel_payload, renamed_ldb_payload)
    renamed_a, renamed_b, _ = compile_pair(renamed_kernel, renamed_ldb, renamed_source)
    renamed_run_a = evaluate_with(
        "a", renamed_kernel, renamed_ldb, renamed_b, renamed_scenario, experiment
    )
    renamed_run_b = evaluate_with(
        "b", renamed_kernel, renamed_ldb, renamed_a, renamed_scenario, experiment
    )
    require(
        renamed_run_a["status"] == renamed_run_b["status"] == "completed",
        "authority-token rename exposed host dispatch",
    )
    require(
        portable(renamed_run_a, renamed_ldb) == portable(renamed_run_b, renamed_ldb),
        "renamed authority diverged",
    )
    vector_results.append({"id": "authority-token-rename", "status": "pass"})

    isolation = static_isolation_audit(kernel_payload, ldb_payload)
    admission_codes = {
        definition["code"]: definition["stage"]
        for definition in kernel_payload["admission_diagnostics"].values()
    }
    post_codes = {
        code: definition["stage"]
        for code, definition in ldb_payload["diagnostics"].items()
    }
    observed_diagnostics = [
        forged_peer_a["diagnostic"],
        tampered_peer_a["diagnostic"],
        missing_profile_results[0]["diagnostic"],
        broken_package_results[0]["diagnostic"],
        unknown_results[0]["diagnostic"],
        missing_law_results[0]["diagnostic"],
        invalid_node_results[0]["diagnostic"],
        missing_kernel_diagnostic_results[0]["diagnostic"],
        deleted_post_diagnostic_results[0]["diagnostic"],
        limited_results[0]["diagnostic"],
        missing_package_a["diagnostic"],
        unselected_a["diagnostic"],
        rule_none_a["diagnostic"],
        parse_refusal_a["diagnostic"],
        false_replay_a["diagnostic"],
        false_cross_a["diagnostic"],
        forged_a["diagnostic"],
        forged_profile_a["diagnostic"],
        coherent_profile_a["diagnostic"],
        refusal_a["diagnostic"],
        overflow_a["diagnostic"],
        backward_a["diagnostic"],
        invalid_run_a["diagnostic"],
        bool_a["diagnostic"],
        unknown_a["diagnostic"],
        effect_a["diagnostic"],
        restricted_run_a["diagnostic"],
        budget_run_a["diagnostic"],
        event_budget_run_a["diagnostic"],
        queue_budget_run_a["diagnostic"],
        rule_budget_a["diagnostic"],
        tampered_a["diagnostic"],
        projection_run_a["diagnostic"],
        runtime_projection_run_a["diagnostic"],
        coherent_eval_a["diagnostic"],
        ambiguous_a["diagnostic"],
        parameter_run_a["diagnostic"],
        effect_contract_results[0]["diagnostic"],
        refusal_contract_results[0]["diagnostic"],
        resource_contract_run_a["diagnostic"],
        unknown_wire_results[0]["diagnostic"],
        transitive_a["diagnostic"],
    ]
    for diagnostic in observed_diagnostics:
        require(
            (
                diagnostic["code"] in admission_codes
                and admission_codes[diagnostic["code"]] == diagnostic["stage"]
            )
            or (
                diagnostic["code"] in post_codes
                and post_codes[diagnostic["code"]] == diagnostic["stage"]
            ),
            f"host-owned diagnostic: {diagnostic}",
        )
    require(
        admissions["a"]["diagnostic_inventory"]
        == admissions["b"]["diagnostic_inventory"]
        == sorted(post_codes),
        "diagnostic reverse inventory differs",
    )
    require(
        set(admission_codes).isdisjoint(post_codes),
        "Kernel and LDB Diagnostic code namespaces overlap",
    )
    authoritative_codes = set(admission_codes) | set(post_codes)
    observed_codes = {diagnostic["code"] for diagnostic in observed_diagnostics}
    require(
        observed_codes == authoritative_codes,
        "Diagnostic behavior coverage is incomplete: "
        f"missing={sorted(authoritative_codes - observed_codes)}, "
        f"unexpected={sorted(observed_codes - authoritative_codes)}",
    )
    diagnostic_authority_closed = (
        not isolation["unmapped_host_failure_reasons"]
        and not isolation["unmapped_direct_ldb_failure_reasons"]
        and not isolation["unmapped_direct_kernel_failure_reasons"]
        and observed_codes == authoritative_codes
        and all(
            (
                diagnostic["code"] in admission_codes
                and admission_codes[diagnostic["code"]] == diagnostic["stage"]
            )
            or (
                diagnostic["code"] in post_codes
                and post_codes[diagnostic["code"]] == diagnostic["stage"]
            )
            for diagnostic in observed_diagnostics
        )
    )
    vector_results.append(
        {
            "id": "diagnostic-authority-closure",
            "status": "pass" if diagnostic_authority_closed else "fail",
        }
    )

    kernel_rows = [row for row in mutation_rows if row["authority"] == "kernel"]
    ldb_rows = [row for row in mutation_rows if row["authority"] == "ldb"]
    required_laws = set(ldb_payload["required_kernel_laws"])
    consulted_law_set = set(consulted_laws)
    consulted_rule_set = set(consulted_rules)
    kernel_row_ids = {row["id"] for row in kernel_rows}
    ldb_row_ids = {row["id"] for row in ldb_rows}
    selected_rule_phases = {
        rule["phase"]
        for rule in ldb_payload["rules"]
        if rule["id"] in consulted_rule_set
    }
    required_pipeline_phases = {
        ldb_payload["source_package_phase"],
        ldb_payload["source_collection_phase"],
        *ldb_payload["compiler_pipeline"],
    }
    expected_exchange = {
        (
            IMPLEMENTATIONS[bootstrap]["id"],
            IMPLEMENTATIONS[lowerer]["id"],
            IMPLEMENTATIONS[evaluator]["id"],
        )
        for bootstrap in IMPLEMENTATIONS
        for lowerer in IMPLEMENTATIONS
        for evaluator in IMPLEMENTATIONS
    }
    observed_exchange = {
        (row["bootstrap_producer"], row["lowerer"], row["evaluator"])
        for row in exchange_rows
    }
    vector_by_id = {row["id"]: row for row in vector_results}
    required_vector_ids = {
        "sealed-peer-admission",
        "default-runtime-profile-closure",
        "package-operation-admission-closure",
        "ldb-diagnostic-reverse-closure-all",
        "canonical-identity",
        "unknown-opcode",
        "kernel-law-missing",
        "kernel-node-shape-invalid",
        "kernel-diagnostic-reverse-closure",
        "bootstrap-resource-limit",
        "source-to-rir-convergence",
        "unknown-source-package",
        "selected-package-operation-closure",
        "source-rule-none",
        "source-parse-invalid",
        "scheduler-phase-priority-fifo",
        "replay-cross-evaluator-split",
        "sealed-comparison-bindings",
        "comparison-run-rehash",
        "comparison-profile-rehash",
        "comparison-profile-definition-binding",
        "cross-authority-refusal",
        "atomic-terminal-rollback",
        "int64-overflow",
        "backward-schedule-refusal",
        "rng-invalid-bound",
        "bool-is-not-int",
        "unknown-operation",
        "static-effect-closure",
        "runtime-effect-profile",
        "rng-draw-budget",
        "event-budget-terminal-refusal",
        "queue-budget-terminal-refusal",
        "rule-step-budget-static-refusal",
        "rng-multi-draw-stream-isolation",
        "same-event-pre-snapshot",
        "rir-tamper-refusal",
        "operation-projection-refusal",
        "runtime-profile-projection-refusal",
        "resolved-profile-definition-refusal",
        "ambiguous-rule-selection",
        "kernel-law-parameter-contract",
        "kernel-law-effect-contract",
        "kernel-law-refusal-contract",
        "kernel-law-resource-contract",
        "kernel-law-result-contract-all-consulted",
        "kernel-wire-type-root",
        "all-admitted-wire-types",
        "transitive-kernel-effect-closure",
        "authority-token-rename",
        "diagnostic-authority-closure",
    }
    policy = ldb_payload["comparison_policy"]

    gates = {
        "G1_executable_kernel_laws": (
            required_laws == consulted_law_set == kernel_row_ids
            and all(
                isinstance(kernel_payload["laws"][law_id].get("body"), dict)
                for law_id in required_laws
            )
            and all(row["pass"] and row.get("contract") for row in kernel_rows)
        ),
        "G2_ldb_driven_pipeline": (
            selected_rule_phases == required_pipeline_phases
            and consulted_rule_set == ldb_row_ids
            and len(consulted_rule_set) == len(required_pipeline_phases)
            and set(ldb_payload["compiler_artifacts"]) == {"ast", "typed_hir", "rir"}
            and compiled_sources["a"]["a"]["status"]
            == compiled_sources["b"]["b"]["status"]
            == "compiled"
            and canonical_bytes(compiled_sources["a"]["a"]["rir"])
            == canonical_bytes(compiled_sources["b"]["b"]["rir"])
            and diagnostic_authority_closed
        ),
        "G3_independent_stacks": (
            len(set(row["id"] for row in IMPLEMENTATIONS.values())) == 2
            and not isolation["authority_token_leaks"]
            and not isolation["shared_semantic_modules"]
            and not isolation["unmapped_host_failure_reasons"]
            and not isolation["unmapped_direct_ldb_failure_reasons"]
            and not isolation["unmapped_direct_kernel_failure_reasons"]
        ),
        "G4_mutual_artifact_consumption": (
            observed_exchange == expected_exchange
            and len(exchange_rows) == len(expected_exchange) == 8
            and len({row["rir_identity"] for row in exchange_rows}) == 1
            and all(row["status"] == "completed" for row in exchange_rows)
            and all(
                admission["admission_identity"]
                == identity(
                    "admission-receipt",
                    {
                        key: value
                        for key, value in admission.items()
                        if key not in {"admitted", "admission_identity"}
                    },
                )
                for admission in admissions.values()
            )
            and forged_peer_a["status"] == forged_peer_b["status"] == "refused"
            and tampered_peer_a["status"] == tampered_peer_b["status"] == "refused"
        ),
        "G5_required_discriminating_vector_slice": (
            required_vector_ids <= set(vector_by_id)
            and all(
                vector_by_id[vector_id]["status"] == "pass"
                for vector_id in required_vector_ids
            )
        ),
        "G6_replay_vs_cross_evaluator": (
            baseline_profile_a["identity"] != baseline_profile_b["identity"]
            and replay_a.get("status") == replay_b.get("status") == "completed"
            and replay_a.get("artifact_kind")
            == replay_b.get("artifact_kind")
            == policy["replay_artifact_kind"]
            and replay_a.get("matches") is replay_b.get("matches") is True
            and cross_a.get("status") == cross_b.get("status") == "completed"
            and cross_a.get("artifact_kind")
            == cross_b.get("artifact_kind")
            == policy["cross_artifact_kind"]
            and cross_a.get("matches") is cross_b.get("matches") is True
            and "evidence" not in replay_a
            and "evidence" not in replay_b
            and "evidence" not in cross_a
            and "evidence" not in cross_b
            and "reproducible" not in replay_a
            and "reproducible" not in replay_b
            and "reproducible" not in cross_a
            and "reproducible" not in cross_b
            and false_replay_a["status"] == false_replay_b["status"] == "refused"
            and false_cross_a["status"] == false_cross_b["status"] == "refused"
            and forged_a["status"] == forged_b["status"] == "refused"
            and forged_profile_a["status"] == forged_profile_b["status"] == "refused"
            and coherent_profile_a["status"]
            == coherent_profile_b["status"]
            == "refused"
            and all(
                comparison["identity"]
                == identity("comparison-artifact", comparison["payload"])
                for comparison in (replay_a, replay_b, cross_a, cross_b)
            )
        ),
        "G7_hidden_host_conditional_kill_gate": (
            kernel_row_ids == consulted_law_set
            and ldb_row_ids == consulted_rule_set
            and all(row["pass"] for row in mutation_rows)
            and renamed_run_a["status"] == renamed_run_b["status"] == "completed"
            and portable(renamed_run_a, renamed_ldb)
            == portable(renamed_run_b, renamed_ldb)
        ),
    }
    require(all(gates.values()), f"gate failed: {gates}")
    results = {
        "artifact_kind": "executable-authority-gate-results",
        "claim": "bounded-architecture-authority-gate",
        "verdict": "PASS",
        "kernel_identity": kernel["identity"],
        "ldb_identity": ldb["identity"],
        "implementations": [IMPLEMENTATIONS[name]["id"] for name in IMPLEMENTATIONS],
        "gates": gates,
        "rir_identity": compiled_sources["a"]["a"]["rir"]["identity"],
        "replay": {"a": replay_a, "b": replay_b},
        "cross_evaluator": {"a": cross_a, "b": cross_b},
        "terminal_refusal_diagnostic": refusal_a["diagnostic"],
        "overflow_diagnostic": overflow_a["diagnostic"],
        "scheduler_refusal_diagnostic": backward_a["diagnostic"],
        "diagnostic_authority": {
            "kernel": admission_codes,
            "ldb": post_codes,
            "observed": observed_diagnostics,
        },
        "isolation": isolation,
        "vectors": vector_results,
    }
    EVIDENCE.mkdir(exist_ok=True)
    profile_a = resolved_profile(
        "a", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
    )
    profile_b = resolved_profile(
        "b", kernel, ldb, compiled_sources["a"]["a"]["resolved_model"]
    )
    evidence_members: dict[str, Any] = {
        "kernel-specification.json": kernel,
        "language-definition-bundle.json": ldb,
        "source-a.json": source_a,
        "source-b.json": source_b,
        "source-refusal.json": source_refusal,
        "experiment.json": experiment,
        "scenario-success.json": scenario,
        "scenario-overflow.json": scenario_overflow,
        "admission-a.json": admissions["a"],
        "admission-b.json": admissions["b"],
        "package-lock-a.json": compiled_sources["a"]["a"]["package_lock"],
        "package-lock-b.json": compiled_sources["a"]["b"]["package_lock"],
        "typed-hir-a.json": compiled_sources["a"]["a"]["typed_hir"],
        "typed-hir-b.json": compiled_sources["a"]["b"]["typed_hir"],
        "rir-a.json": compiled_sources["a"]["a"]["rir"],
        "rir-b.json": compiled_sources["a"]["b"]["rir"],
        "debug-map-a.json": compiled_sources["a"]["a"]["debug_map"],
        "debug-map-b.json": compiled_sources["a"]["b"]["debug_map"],
        "resolved-model-a.json": compiled_sources["a"]["a"]["resolved_model"],
        "resolved-model-b.json": compiled_sources["a"]["b"]["resolved_model"],
        "runtime-profile-definition.json": ldb["payload"]["runtime_profiles"][
            ldb["payload"]["default_runtime_profile"]
        ],
        "resolved-runtime-profile-a.json": profile_a,
        "resolved-runtime-profile-b.json": profile_b,
        "evaluation-run-a.json": baseline_a,
        "evaluation-run-b.json": baseline_b,
        "replay-comparison-a.json": replay_a,
        "replay-comparison-b.json": replay_b,
        "cross-evaluator-comparison-a.json": cross_a,
        "cross-evaluator-comparison-b.json": cross_b,
        "runtime-refusal-a.json": refusal_a,
        "runtime-refusal-b.json": refusal_b,
        "terminal-audit-a.json": refusal_a["terminal_audit"],
        "terminal-audit-b.json": refusal_b["terminal_audit"],
        "exchange-matrix.json": {"rows": exchange_rows},
        "mutation-coverage.json": {"coverage": "100%", "rows": mutation_rows},
        "gate-results.json": results,
    }
    for filename, value in evidence_members.items():
        (EVIDENCE / filename).write_bytes(canonical_bytes(value))
    implementation_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    source_paths = sorted(
        [
            ROOT / "README.md",
            ROOT / "DOGFOODING.md",
            ENGINE_A,
            ENGINE_B,
            Path(__file__),
            *AUTHORITIES.glob("*.json"),
        ]
    )
    source_members = {
        path.relative_to(
            ROOT
        ).as_posix(): f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in source_paths
    }
    source_digest = hashlib.sha256(canonical_bytes(source_members)).hexdigest()
    evidence_index = {
        "artifact_kind": "authority-gate-evidence-index",
        "implementation_commit": implementation_commit,
        "implementation_commit_scope": "committed prototype sources before this generated evidence refresh",
        "prototype_source_members": source_members,
        "prototype_source_digest": f"sha256:{source_digest}",
        "kernel_identity": kernel["identity"],
        "ldb_identity": ldb["identity"],
        "members": {
            filename: f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"
            for filename, value in sorted(evidence_members.items())
        },
    }
    (EVIDENCE / "evidence-index.json").write_bytes(canonical_bytes(evidence_index))
    print(
        json.dumps(
            {
                "verdict": "PASS",
                "gates": gates,
                "exchange_rows": len(exchange_rows),
                "mutations": len(mutation_rows),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
