"""Executable conformance questions for the disposable authority prototype."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from authority import KERNEL_SPEC, language_bundle, runtime_profile, scenario
from bootstrap_a import BootstrapA
from bootstrap_b import BootstrapB
from canonical import canonical_bytes, clone, identity
from cli import HANDLER_IMPLEMENTATIONS, dispatch
from descriptor import COMMANDS, bind
from evaluator_a import EvaluatorA
from evaluator_b import EvaluatorB
from pipeline import build, compare_cross_evaluator, execute
from store import ArtifactStore, InvocationConflict, PublicationError


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "cli.py"


def reidentify_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    bundle["identity"] = identity(
        "ldb", {key: value for key, value in bundle.items() if key != "identity"}
    )
    return bundle


def reidentify_rir(rir: dict[str, Any]) -> dict[str, Any]:
    rir["identity"] = identity(
        "resolved-model",
        {key: value for key, value in rir.items() if key != "identity"},
    )
    return rir


def bootstrap_pair(bundle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    first = BootstrapA().admit(KERNEL_SPEC, bundle)
    second = BootstrapB().admit(KERNEL_SPEC, bundle)
    comparable_first = {
        key: value for key, value in first.items() if key != "implementation"
    }
    comparable_second = {
        key: value for key, value in second.items() if key != "implementation"
    }
    assert comparable_first == comparable_second
    return first, second


def mutate_first_operator(value: Any, old: str, new: str) -> bool:
    if isinstance(value, dict):
        if value.get("node") == "calculate" and value.get("operator") == old:
            value["operator"] = new
            return True
        for child in value.values():
            if mutate_first_operator(child, old, new):
                return True
    if isinstance(value, list):
        for child in value:
            if mutate_first_operator(child, old, new):
                return True
    return False


def find_node(
    value: Any, predicate: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    if isinstance(value, dict):
        if predicate(value):
            return value
        for child in value.values():
            try:
                return find_node(child, predicate)
            except LookupError:
                pass
    elif isinstance(value, list):
        for child in value:
            try:
                return find_node(child, predicate)
            except LookupError:
                pass
    raise LookupError("node-not-found")


def invocation_key(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def subprocess_cli(
    request: dict[str, Any],
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    completed = subprocess.run(
        [sys.executable, str(CLI), json.dumps(request)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = json.loads(completed.stdout) if completed.stdout else None
    stderr = json.loads(completed.stderr) if completed.stderr else None
    return completed.returncode, stdout, stderr


def evaluate(
    evaluator: EvaluatorA | EvaluatorB,
    built: dict[str, Any],
    profile: dict[str, Any],
    scenario_value: dict[str, Any],
) -> dict[str, Any]:
    return evaluator.run(
        KERNEL_SPEC,
        built["bundle"],
        built["resolution"]["lock"],
        built["compiled"]["rir"],
        profile,
        scenario_value,
    )


def test_bootstrap_agreement_and_closed_ontology() -> None:
    valid = language_bundle()
    first, second = bootstrap_pair(valid)
    assert first["admitted"] and second["admitted"]
    assert set(first["consulted_rules"]) == {
        "admit.diagnostic.v1",
        "admit.operation.v1",
        "admit.package.v1",
        "admit.runtime_profile.v1",
    }
    assert first["bundle_identity"] == valid["identity"]

    unknown_fact = clone(valid)
    unknown_fact["facts"].append({"kind": "spell", "id": "unknown"})
    reidentify_bundle(unknown_fact)
    first, _ = bootstrap_pair(unknown_fact)
    assert first["diagnostics"][-1]["code"] == "bundle.fact-kind-unknown"

    ill_typed = clone(valid)
    ill_typed["facts"][0]["id"] = 7
    reidentify_bundle(ill_typed)
    first, _ = bootstrap_pair(ill_typed)
    assert any(item["code"] == "bundle.fact-invalid" for item in first["diagnostics"])

    unknown_premise = clone(valid)
    unknown_premise["rules"][0]["premises"][0]["op"] = "host_callback"
    reidentify_bundle(unknown_premise)
    first, _ = bootstrap_pair(unknown_premise)
    assert first["diagnostics"][0]["code"] == "bundle.premise-operator-unknown"


def test_rule_selection_and_consulted_rule_mutations() -> None:
    original = language_bundle()
    ambiguous = clone(original)
    operation_rule = next(
        rule for rule in ambiguous["rules"] if rule["id"] == "admit.operation.v1"
    )
    duplicate = clone(operation_rule)
    duplicate["id"] = "admit.operation.shadow-v1"
    ambiguous["rules"].append(duplicate)
    reidentify_bundle(ambiguous)
    result, _ = bootstrap_pair(ambiguous)
    assert (
        sum(
            diagnostic["code"] == "bundle.rule-selection-ambiguous"
            for diagnostic in result["diagnostics"]
        )
        == 2
    )

    removed = clone(original)
    removed["rules"] = [
        rule for rule in removed["rules"] if rule["id"] != "admit.operation.v1"
    ]
    reidentify_bundle(removed)
    result, _ = bootstrap_pair(removed)
    assert result["bundle_identity"] != original["identity"]
    assert any(
        item["code"] == "bundle.rule-selection-none" for item in result["diagnostics"]
    )

    changed = clone(original)
    changed_rule = next(
        rule for rule in changed["rules"] if rule["id"] == "admit.operation.v1"
    )
    required = next(
        item for item in changed_rule["premises"] if item["op"] == "required_fields"
    )
    required["fields"].append("authority_proof")
    reidentify_bundle(changed)
    result, _ = bootstrap_pair(changed)
    assert result["bundle_identity"] != original["identity"]
    assert any(item["code"] == "bundle.fact-invalid" for item in result["diagnostics"])


def test_bootstrap_malformed_containers_are_closed_diagnostics() -> None:
    malformed_rule = language_bundle()
    malformed_rule["rules"][0]["premises"] = {"not": "a-list"}
    reidentify_bundle(malformed_rule)
    first, second = bootstrap_pair(malformed_rule)
    assert first["admitted"] is second["admitted"] is False
    assert first["diagnostics"] == [
        {"code": "bundle.malformed-container", "detail": "container", "path": "$"}
    ]

    malformed_expression = language_bundle()
    operation = next(
        fact for fact in malformed_expression["facts"] if fact["kind"] == "operation"
    )
    operation["body"] = {"node": "record", "fields": []}
    reidentify_bundle(malformed_expression)
    first, _ = bootstrap_pair(malformed_expression)
    assert first["diagnostics"][0]["code"] == "bundle.malformed-container"


def test_kernel_identity_is_independently_rehashed_on_all_four_paths() -> None:
    tampered_kernel = clone(KERNEL_SPEC)
    tampered_kernel["rng"]["bounded_mapping"] = "biased-host-modulo"
    bundle = language_bundle()
    for bootstrap in (BootstrapA(), BootstrapB()):
        result = bootstrap.admit(tampered_kernel, bundle)
        assert result["admitted"] is False
        assert result["diagnostics"][0] == {
            "code": "kernel.identity-mismatch",
            "detail": "identity",
            "path": "$.kernel",
        }

    built = build("a", "a")
    for evaluator in (EvaluatorA(), EvaluatorB()):
        result = evaluator.run(
            tampered_kernel,
            built["bundle"],
            built["resolution"]["lock"],
            built["compiled"]["rir"],
            runtime_profile(),
            scenario(),
        )
        assert result["status"] == "refused"
        assert result["terminal_audit"]["diagnostic"]["code"] == (
            "runtime.kernel-identity-invalid"
        )


def test_independent_compilers_make_semantic_normal_form() -> None:
    first = build("a", "a")
    second = build("b", "b")
    cross_source_a = build("a", "b")
    cross_source_b = build("b", "a")
    assert first["status"] == second["status"] == "completed"
    assert first["compiled"]["rir"] == second["compiled"]["rir"]
    assert cross_source_a["compiled"]["rir"] == first["compiled"]["rir"]
    assert cross_source_b["compiled"]["rir"] == first["compiled"]["rir"]
    assert (
        first["compiled"]["debug_map"]["identity"]
        != second["compiled"]["debug_map"]["identity"]
    )
    assert (
        first["compiled"]["build_receipt"]["identity"]
        != second["compiled"]["build_receipt"]["identity"]
    )
    assert first["compiled"]["ast"]["identity"] != second["compiled"]["ast"]["identity"]
    assert "compiler" not in first["compiled"]["rir"]
    assert "source" not in first["compiled"]["rir"]

    semantic_change = build("a", "a", base_damage=5)
    assert (
        semantic_change["compiled"]["rir"]["identity"]
        != first["compiled"]["rir"]["identity"]
    )


def test_package_lock_is_closed_and_provenance_is_separate() -> None:
    built = build("a", "a")
    lock = built["resolution"]["lock"]
    receipt = built["resolution"]["receipt"]
    assert lock["transitive_graph"]
    assert lock["capability_providers"]["rpg.resource"] == "rpg.combat@2.0.0-probe"
    assert (
        lock["operation_bindings"]["rpg.action.resolve@1"] == "rpg.combat@2.0.0-probe"
    )
    assert lock["type_closure"] == ["Int", "Record", "Variant"]
    assert lock["conversion_closure"] == []
    assert "resolver" not in lock
    assert receipt["resolver"] == "probe-resolver-v1"


def test_crossed_evaluators_and_exact_rng_agree() -> None:
    built_a = build("a", "a")
    built_b = build("b", "b")
    profile = runtime_profile()
    result_a = evaluate(EvaluatorA(), built_b, profile, scenario("success"))
    result_b = evaluate(EvaluatorB(), built_a, profile, scenario("success"))
    assert result_a["status"] == result_b["status"] == "completed"
    run_a = result_a["run"]
    run_b = result_b["run"]
    for key in ("outcome", "payload", "final_state", "metrics", "rng_trace"):
        assert run_a[key] == run_b[key]
    assert run_a["outcome"] == "Resolved"
    assert run_a["payload"] == {"damage": 5}
    assert run_a["final_state"] == {"actor": {"resource": 2}, "target": {"hp": 7}}
    assert run_a["rng_trace"] == [
        {
            "accepted": True,
            "candidate": 12569293548191996068,
            "counter": 0,
            "stream": "combat.damage",
        }
    ]


def test_discriminated_insufficient_cannot_commit() -> None:
    for compiler_name, evaluator_name in (("a", "b"), ("b", "a")):
        result = execute(
            compiler_name,
            evaluator_name,
            compiler_name,
            "insufficient",
            runtime_profile(),
        )
        assert result["status"] == "completed"
        run = result["runtime"]["run"]
        assert run["outcome"] == "Insufficient"
        assert run["final_state"] == run["initial_state"]
        assert run["metrics"] == []
        assert run["rng_trace"] == []


def test_runtime_limits_refuse_and_roll_back() -> None:
    built = build("a", "a")
    for evaluator in (EvaluatorA(), EvaluatorB()):
        step_result = evaluate(
            evaluator, built, runtime_profile(max_steps=5), scenario()
        )
        assert step_result["status"] == "refused"
        step_audit = step_result["terminal_audit"]
        assert step_audit["diagnostic"]["code"] == "runtime.limit-exceeded"
        assert step_audit["diagnostic"]["detail"] == "steps"
        assert step_audit["rolled_back_state"] == scenario()["initial_state"]

        draw_result = evaluate(
            evaluator, built, runtime_profile(max_draws=0), scenario()
        )
        assert draw_result["status"] == "refused"
        draw_audit = draw_result["terminal_audit"]
        assert draw_audit["diagnostic"] == {
            "code": "runtime.limit-exceeded",
            "detail": "draws",
        }
        assert draw_audit["rolled_back_state"] == scenario()["initial_state"]

        invalid_seed = scenario()
        invalid_seed["seed"] = -1
        seed_result = evaluate(evaluator, built, runtime_profile(), invalid_seed)
        assert seed_result["status"] == "refused"
        assert (
            seed_result["terminal_audit"]["diagnostic"]["code"]
            == "runtime.rng-seed-invalid"
        )

        invalid_bound_build = clone(built)
        invalid_bound_rir = invalid_bound_build["compiled"]["rir"]
        invalid_bound_rir["entries"][0]["arguments"]["roll_bound"] = 0
        reidentify_rir(invalid_bound_rir)
        bound_result = evaluate(
            evaluator, invalid_bound_build, runtime_profile(), scenario()
        )
        assert bound_result["status"] == "refused"
        assert (
            bound_result["terminal_audit"]["diagnostic"]["code"]
            == "runtime.rng-bound-invalid"
        )


def test_resolved_runtime_profile_binding_and_tamper_refusals() -> None:
    built = build("a", "a")
    for evaluator_type in (EvaluatorA, EvaluatorB):
        completed = evaluate(evaluator_type(), built, runtime_profile(), scenario())
        resolved = completed["profile"]
        assert resolved["kernel"] == KERNEL_SPEC["identity"]
        assert resolved["language_bundle"] == built["bundle"]["identity"]
        assert resolved["package_lock"] == built["resolution"]["lock"]["identity"]
        assert resolved["rir"] == built["compiled"]["rir"]["identity"]
        assert resolved["evaluator"] == evaluator_type.implementation
        assert resolved["platform"]["implementation"]
        assert resolved["concrete_budgets"] == {
            "max_draws": 8,
            "max_steps": 512,
        }

        wrong_kernel = clone(built)
        wrong_kernel["compiled"]["rir"]["kernel"] = f"sha256:kernel:{'0' * 64}"
        reidentify_rir(wrong_kernel["compiled"]["rir"])
        refused = evaluate(
            evaluator_type(), wrong_kernel, runtime_profile(), scenario()
        )
        assert (
            refused["terminal_audit"]["diagnostic"]["code"]
            == "runtime.kernel-binding-mismatch"
        )

        wrong_profile = runtime_profile()
        wrong_profile["numeric_profile"] = "host-int"
        refused = evaluate(evaluator_type(), built, wrong_profile, scenario())
        assert (
            refused["terminal_audit"]["diagnostic"]["code"]
            == "runtime.profile-definition-mismatch"
        )

        wrong_lock = clone(built)
        lock = wrong_lock["resolution"]["lock"]
        lock["language_bundle"] = f"sha256:ldb:{'1' * 64}"
        lock["identity"] = identity(
            "package-lock",
            {key: value for key, value in lock.items() if key != "identity"},
        )
        wrong_lock["compiled"]["rir"]["package_lock"] = lock["identity"]
        reidentify_rir(wrong_lock["compiled"]["rir"])
        refused = evaluate(evaluator_type(), wrong_lock, runtime_profile(), scenario())
        assert (
            refused["terminal_audit"]["diagnostic"]["code"]
            == "runtime.bundle-binding-mismatch"
        )


def test_closed_outcome_tags_and_payloads() -> None:
    base = build("a", "a")
    mutations = (
        ("unknown-tag", "runtime.outcome-tag-invalid"),
        ("bad-payload", "runtime.outcome-payload-invalid"),
    )
    for mutation, expected_code in mutations:
        mutated = clone(base)
        rir = mutated["compiled"]["rir"]
        if mutation == "unknown-tag":
            node = find_node(
                rir,
                lambda item: (
                    item.get("node") == "variant" and item.get("tag") == "Insufficient"
                ),
            )
            node["tag"] = "Mystery"
            scenario_value = scenario("insufficient")
        else:
            node = find_node(
                rir,
                lambda item: (
                    item.get("node") == "variant" and item.get("tag") == "Resolved"
                ),
            )
            node.clear()
            node.update({"node": "literal", "value": {"tag": "Resolved", "fields": []}})
            scenario_value = scenario("success")
        reidentify_rir(rir)
        for evaluator in (EvaluatorA(), EvaluatorB()):
            refused = evaluate(evaluator, mutated, runtime_profile(), scenario_value)
            assert refused["status"] == "refused"
            assert refused["terminal_audit"]["diagnostic"]["code"] == expected_code


def test_event_writes_are_buffered_snapshot_reads_and_single_final_write() -> None:
    base = build("a", "a")
    read_after_write = clone(base)
    rir = read_after_write["compiled"]["rir"]
    sequence = find_node(rir, lambda item: item.get("node") == "sequence")
    sequence["items"].insert(
        1,
        {
            "node": "emit_metric",
            "metric": "resource.observed-after-buffered-write",
            "value": {"node": "state_read", "path": "actor.resource"},
        },
    )
    reidentify_rir(rir)
    for evaluator in (EvaluatorA(), EvaluatorB()):
        result = evaluate(evaluator, read_after_write, runtime_profile(), scenario())
        assert result["status"] == "completed"
        observed = next(
            item
            for item in result["run"]["metrics"]
            if item["metric"] == "resource.observed-after-buffered-write"
        )
        assert observed["value"] == 5
        assert result["run"]["final_state"]["actor"]["resource"] == 2

    duplicate = clone(base)
    rir = duplicate["compiled"]["rir"]
    sequence = find_node(rir, lambda item: item.get("node") == "sequence")
    sequence["items"].insert(1, clone(sequence["items"][0]))
    reidentify_rir(rir)
    for evaluator in (EvaluatorA(), EvaluatorB()):
        result = evaluate(evaluator, duplicate, runtime_profile(), scenario())
        assert result["status"] == "refused"
        assert (
            result["terminal_audit"]["diagnostic"]["code"]
            == "runtime.duplicate-state-write"
        )
        assert (
            result["terminal_audit"]["rolled_back_state"] == scenario()["initial_state"]
        )


def test_unknown_primitive_has_no_host_fallback() -> None:
    built = build("a", "a")
    rir = built["compiled"]["rir"]
    action = next(
        item for item in rir["operations"] if item["id"] == "rpg.action.resolve@1"
    )
    assert mutate_first_operator(action["body"], "add_int", "host_magic")
    reidentify_rir(rir)
    for evaluator in (EvaluatorA(), EvaluatorB()):
        result = evaluate(evaluator, built, runtime_profile(), scenario())
        assert result["status"] == "refused"
        assert (
            result["terminal_audit"]["diagnostic"]["code"]
            == "runtime.unknown-primitive"
        )
        assert (
            result["terminal_audit"]["rolled_back_state"] == scenario()["initial_state"]
        )


def test_ldb_composition_changes_identity_and_both_behaviors() -> None:
    baseline = build("a", "a")
    changed_bundle = language_bundle(damage_operator="sub_int")
    changed_a = build("a", "a", bundle=changed_bundle)
    changed_b = build("b", "b", bundle=changed_bundle)
    assert changed_bundle["identity"] != baseline["bundle"]["identity"]
    assert (
        changed_a["compiled"]["rir"]["identity"]
        != baseline["compiled"]["rir"]["identity"]
    )
    assert changed_a["compiled"]["rir"] == changed_b["compiled"]["rir"]
    outcomes = []
    for evaluator in (EvaluatorA(), EvaluatorB()):
        result = evaluate(evaluator, changed_a, runtime_profile(), scenario())
        assert result["status"] == "completed"
        outcomes.append(result["run"]["payload"])
    assert outcomes == [{"damage": 3}, {"damage": 3}]


def test_replay_profile_conflict_blocks_positive_evidence() -> None:
    result = compare_cross_evaluator()
    assert result["status"] == "refused"
    assert result["stage"] == "evaluation"
    assert result["gate_report"]["gate"] == "decision-required"
    assert (
        result["gate_report"]["left_resolved_profile"]
        != result["gate_report"]["right_resolved_profile"]
    )
    assert (
        result["run_a"]["run"]["semantic_runtime_profile"]
        == result["run_b"]["run"]["semantic_runtime_profile"]
    )
    assert result["gate_report"]["observation_mismatches"] == []
    assert len(result["datasets"]) == 2
    assert "comparison" not in result
    assert "evidence" not in result


def test_evaluators_share_no_domain_or_semantic_implementation() -> None:
    source_a = (ROOT / "evaluator_a.py").read_text(encoding="utf-8")
    source_b = (ROOT / "evaluator_b.py").read_text(encoding="utf-8")
    assert "rpg." not in source_a
    assert "rpg." not in source_b
    assert "evaluator_b" not in source_a
    assert "evaluator_a" not in source_b
    semantic_modules = {"authority", "bootstrap", "compiler", "evaluator", "pipeline"}
    for source in (source_a, source_b):
        import_lines = [
            line for line in source.splitlines() if line.startswith("from ")
        ]
        assert not any(
            any(name in line for name in semantic_modules) for line in import_lines
        )


def test_cli_descriptor_defaults_and_cross_layer_commands() -> None:
    with tempfile.TemporaryDirectory(prefix="schema2-authority-cli-") as temporary:
        store = str(Path(temporary) / "store")
        build_request = {
            "command": "build",
            "invocation_key": invocation_key("build-defaults"),
            "params": {},
            "store": store,
        }
        code, stdout, stderr = subprocess_cli(build_request)
        assert code == 0 and stderr is None
        assert stdout is not None and stdout["set_kind"] == "build-artifact-set"

        run_request = {
            "command": "run",
            "invocation_key": invocation_key("structured-run"),
            "params": {
                "compiler": "b",
                "evaluator": "a",
                "scenario": "success",
                "source_variant": "b",
            },
            "store": store,
        }
        code, stdout, stderr = subprocess_cli(run_request)
        assert code == 0 and stderr is None
        assert stdout is not None and stdout["set_kind"] == "evaluation-artifact-set"

        compare_request = {
            "command": "compare",
            "invocation_key": invocation_key("cross-compare"),
            "params": {},
            "store": store,
        }
        code, stdout, stderr = subprocess_cli(compare_request)
        assert code == 2 and stderr is None
        assert stdout is not None
        assert stdout["error"]["stage"] == "evaluation"
        assert stdout["error"]["gate_report"]["gate"] == "decision-required"

        invalid = clone(build_request)
        invalid["invocation_key"] = invocation_key("unknown-param")
        invalid["params"] = {"host_default": True}
        code, stdout, stderr = subprocess_cli(invalid)
        assert code == 3 and stdout is None
        assert stderr is not None
        assert stderr["error"]["code"] == "invocation.parameter-unknown"

        wrong_type = clone(build_request)
        wrong_type["invocation_key"] = invocation_key("wrong-type")
        wrong_type["params"] = {"compiler": 7}
        code, stdout, stderr = subprocess_cli(wrong_type)
        assert code == 3 and stdout is None
        assert stderr is not None
        assert stderr["error"]["code"] == "invocation.parameter-invalid"

        static_refusal = clone(build_request)
        static_refusal["invocation_key"] = invocation_key("static-refusal")
        static_refusal["params"] = {"bundle_fixture": "malformed-rule"}
        code, stdout, stderr = subprocess_cli(static_refusal)
        assert code == 2 and stderr is None
        assert stdout is not None and stdout["error"]["stage"] == "static"

        ingress_refusal = clone(build_request)
        ingress_refusal["invocation_key"] = invocation_key("ingress-refusal")
        ingress_refusal["params"] = {"bundle_fixture": "identity-mismatch"}
        code, stdout, stderr = subprocess_cli(ingress_refusal)
        assert code == 2 and stderr is None
        assert stdout is not None and stdout["error"]["stage"] == "ingress"


def test_invocation_key_and_canonical_input_contract() -> None:
    base = {
        "command": "build",
        "invocation_key": invocation_key("canonical-a"),
        "params": {"compiler": "a"},
        "store": "/tmp/presentation-a",
    }
    first = bind(base)
    moved = clone(base)
    moved["invocation_key"] = invocation_key("canonical-b")
    moved["store"] = "/tmp/presentation-b"
    second = bind(moved)
    assert first["canonical_input_identity"] == second["canonical_input_identity"]
    assert first["descriptor_identity"] == COMMANDS["build"]["identity"]
    changed = clone(base)
    changed["params"] = {"compiler": "b"}
    assert (
        bind(changed)["canonical_input_identity"] != first["canonical_input_identity"]
    )

    for invalid_key in ("abc", "A" * 64):
        request = clone(base)
        request["invocation_key"] = invalid_key
        code, stdout, stderr = subprocess_cli(request)
        assert code == 3 and stdout is None
        assert stderr is not None
        assert stderr["error"]["code"] == "invocation.key-invalid"


def test_descriptor_identity_routing_and_reverse_conformance() -> None:
    assert {descriptor["handler"] for descriptor in COMMANDS.values()} == set(
        HANDLER_IMPLEMENTATIONS
    )
    for name, descriptor in COMMANDS.items():
        bare = {key: value for key, value in descriptor.items() if key != "identity"}
        assert descriptor["identity"] == identity("command-descriptor", bare)
        assert descriptor["command"] == name
        if name != "compare":
            assert descriptor["outcomes"]["success"]["channel"] == "stdout"
        assert descriptor["outcomes"]["usage"] == {
            "outcome": "usage_error",
            "exit": 3,
            "channel": "stderr",
        }
        assert descriptor["outcomes"]["internal"] == {
            "outcome": "internal_error",
            "exit": 4,
            "channel": "stderr",
        }
    assert COMMANDS["compare"]["artifact_producing"] is False
    assert COMMANDS["compare"]["execution_marking"] == ("gate-only-authority-conflict")
    assert COMMANDS["compare"]["parameters"] == {}
    assert "success" not in COMMANDS["compare"]["outcomes"]

    original_compare = HANDLER_IMPLEMENTATIONS["compare.v1"]
    HANDLER_IMPLEMENTATIONS["compare.v1"] = lambda _bound, _store: {
        "outcome": "completed"
    }
    try:
        with tempfile.TemporaryDirectory(
            prefix="schema2-authority-undeclared-success-"
        ) as temporary:
            bound = bind(
                {
                    "command": "compare",
                    "invocation_key": invocation_key("undeclared-compare-success"),
                    "params": {},
                    "store": temporary,
                }
            )
            try:
                dispatch(bound)
            except PublicationError as error:
                assert str(error) == "descriptor.success-undeclared"
            else:
                raise AssertionError("compare accepted an undeclared success outcome")
    finally:
        HANDLER_IMPLEMENTATIONS["compare.v1"] = original_compare


def test_invocation_idempotency_conflict_and_recovery() -> None:
    with tempfile.TemporaryDirectory(
        prefix="schema2-authority-idempotency-"
    ) as temporary:
        store = str(Path(temporary) / "store")
        request = {
            "command": "build",
            "invocation_key": invocation_key("stable-key"),
            "params": {"compiler": "a"},
            "store": store,
        }
        first_code, first, first_error = subprocess_cli(request)
        second_code, second, second_error = subprocess_cli(request)
        assert first_code == second_code == 0
        assert first_error is second_error is None
        assert first is not None and second is not None
        assert first["receipt"] == second["receipt"]
        assert first["idempotent_replay"] is False
        assert second["idempotent_replay"] is True

        conflict = clone(request)
        conflict["params"] = {"compiler": "b"}
        code, stdout, stderr = subprocess_cli(conflict)
        assert code == 3 and stdout is None
        assert stderr is not None
        assert stderr["error"]["code"] == "invocation_key_conflict"

        calls = 0
        original_handler = HANDLER_IMPLEMENTATIONS["build.v1"]

        def should_not_dispatch(
            _bound: dict[str, Any], _store: ArtifactStore
        ) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            raise AssertionError("conflict-dispatched")

        HANDLER_IMPLEMENTATIONS["build.v1"] = should_not_dispatch
        try:
            changed_bound = bind(conflict)
            try:
                dispatch(changed_bound)
            except InvocationConflict:
                pass
            else:
                raise AssertionError("expected invocation conflict")
            assert calls == 0
        finally:
            HANDLER_IMPLEMENTATIONS["build.v1"] = original_handler

        delivery_request = {
            "command": "build",
            "invocation_key": invocation_key("delivery-key"),
            "params": {"fault": "after_commit"},
            "store": store,
        }
        code, stdout, stderr = subprocess_cli(delivery_request)
        assert code == 4 and stdout is None
        assert stderr is not None
        assert stderr["error"]["code"] == "internal_error"
        retry_code, retry, retry_error = subprocess_cli(delivery_request)
        assert retry_code == 0
        assert retry_error is None and retry is not None
        assert retry["invocation_key"] == invocation_key("delivery-key")
        assert retry["idempotent_replay"] is True

        inspect_request = {
            "command": "inspect",
            "invocation_key": request["invocation_key"],
            "params": {"target_command": "build"},
            "store": store,
        }
        inspect_code, inspected, inspect_error = subprocess_cli(inspect_request)
        assert inspect_code == 0 and inspect_error is None
        assert inspected is not None
        assert inspected["result"]["stored_outcome"] == {"outcome": "completed"}


def test_publication_fault_has_no_partial_visibility() -> None:
    with tempfile.TemporaryDirectory(prefix="schema2-authority-atomic-") as temporary:
        store_path = str(Path(temporary) / "store")
        request = {
            "command": "build",
            "invocation_key": invocation_key("faulted-build"),
            "params": {"fault": "before_commit"},
            "store": store_path,
        }
        code, stdout, stderr = subprocess_cli(request)
        assert code == 4 and stdout is None
        assert stderr is not None
        store = ArtifactStore(Path(store_path))
        assert (
            store.lookup(COMMANDS["build"]["identity"], request["invocation_key"])
            is None
        )
        assert store.visible_keys() == []


def test_store_rehashes_members_receipts_and_member_sets() -> None:
    with tempfile.TemporaryDirectory(prefix="schema2-authority-tamper-") as temporary:
        store_path = str(Path(temporary) / "store")
        request = {
            "command": "build",
            "invocation_key": invocation_key("tamper-member"),
            "params": {},
            "store": store_path,
        }
        code, stdout, stderr = subprocess_cli(request)
        assert code == 0 and stdout is not None and stderr is None
        descriptor = COMMANDS["build"]["identity"]
        descriptor_digest = descriptor.rsplit(":", 1)[-1]
        directory = (
            Path(store_path)
            / "committed"
            / descriptor_digest
            / request["invocation_key"]
        )
        record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
        first_member = record["members"][0]
        member_path = (
            directory
            / "artifacts"
            / f"{first_member['identity'].replace(':', '_')}.json"
        )
        stored_member = json.loads(member_path.read_text(encoding="utf-8"))
        stored_member["tampered"] = True
        member_path.write_bytes(canonical_bytes(stored_member) + b"\n")
        try:
            ArtifactStore(Path(store_path)).lookup(
                descriptor, request["invocation_key"]
            )
        except PublicationError as error:
            assert str(error) == "artifact.member-bytes-mismatch"
        else:
            raise AssertionError("tampered member was accepted")

    with tempfile.TemporaryDirectory(prefix="schema2-authority-receipt-") as temporary:
        store_path = str(Path(temporary) / "store")
        request = {
            "command": "build",
            "invocation_key": invocation_key("tamper-receipt"),
            "params": {},
            "store": store_path,
        }
        code, _, _ = subprocess_cli(request)
        assert code == 0
        descriptor = COMMANDS["build"]["identity"]
        directory = (
            Path(store_path)
            / "committed"
            / descriptor.rsplit(":", 1)[-1]
            / request["invocation_key"]
        )
        record_path = directory / "record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["receipt"]["members"] = record["receipt"]["members"][1:]
        record["receipt"]["identity"] = identity(
            "publication-receipt",
            {
                key: value
                for key, value in record["receipt"].items()
                if key != "identity"
            },
        )
        record_path.write_bytes(canonical_bytes(record) + b"\n")
        try:
            ArtifactStore(Path(store_path)).lookup(
                descriptor, request["invocation_key"]
            )
        except PublicationError as error:
            assert str(error) == "artifact.receipt-member-set-mismatch"
        else:
            raise AssertionError("forged receipt member set was accepted")

    with tempfile.TemporaryDirectory(
        prefix="schema2-authority-receipt-id-"
    ) as temporary:
        store_path = str(Path(temporary) / "store")
        request = {
            "command": "build",
            "invocation_key": invocation_key("tamper-receipt-identity"),
            "params": {},
            "store": store_path,
        }
        code, _, _ = subprocess_cli(request)
        assert code == 0
        descriptor = COMMANDS["build"]["identity"]
        directory = (
            Path(store_path)
            / "committed"
            / descriptor.rsplit(":", 1)[-1]
            / request["invocation_key"]
        )
        record_path = directory / "record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["receipt"]["set_kind"] = "forged-set"
        record_path.write_bytes(canonical_bytes(record) + b"\n")
        try:
            ArtifactStore(Path(store_path)).lookup(
                descriptor, request["invocation_key"]
            )
        except PublicationError as error:
            assert str(error) == "artifact.identity-mismatch"
        else:
            raise AssertionError("tampered receipt identity was accepted")

    with tempfile.TemporaryDirectory(prefix="schema2-authority-coherent-") as temporary:
        store_path = str(Path(temporary) / "store")
        request = {
            "command": "build",
            "invocation_key": invocation_key("coherent-rewrite"),
            "params": {},
            "store": store_path,
        }
        code, _, _ = subprocess_cli(request)
        assert code == 0
        descriptor = COMMANDS["build"]["identity"]
        directory = (
            Path(store_path)
            / "committed"
            / descriptor.rsplit(":", 1)[-1]
            / request["invocation_key"]
        )
        marker = json.loads(
            (directory / "commit-marker.json").read_text(encoding="utf-8")
        )
        record_path = directory / "record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        removed = record["members"].pop()
        removed_path = (
            directory / "artifacts" / f"{removed['identity'].replace(':', '_')}.json"
        )
        removed_path.unlink()
        record["receipt"]["members"] = sorted(
            member["identity"] for member in record["members"]
        )
        record["receipt"]["identity"] = identity(
            "publication-receipt",
            {
                key: value
                for key, value in record["receipt"].items()
                if key != "identity"
            },
        )
        assert marker["publication_receipt"] != record["receipt"]["identity"]
        record_path.write_bytes(canonical_bytes(record) + b"\n")
        try:
            ArtifactStore(Path(store_path)).lookup(
                descriptor, request["invocation_key"]
            )
        except PublicationError as error:
            assert str(error) == "artifact.marker-receipt-mismatch"
        else:
            raise AssertionError("coherent member/receipt rewrite was accepted")

    with tempfile.TemporaryDirectory(prefix="schema2-authority-forged-") as temporary:
        bound = bind(
            {
                "command": "build",
                "invocation_key": invocation_key("forged-member"),
                "params": {},
                "store": str(Path(temporary) / "store"),
            }
        )
        forged = {"kind": "probe", "value": 1, "identity": f"sha256:probe:{'0' * 64}"}
        try:
            ArtifactStore(Path(bound["store"])).publish(
                bound["descriptor_identity"],
                bound["invocation_key"],
                bound["canonical_input_identity"],
                "build-artifact-set",
                {"outcome": "completed"},
                [forged],
            )
        except PublicationError as error:
            assert str(error) == "artifact.identity-mismatch"
        else:
            raise AssertionError("forged member identity was accepted")
        wrong_domain = {"kind": "probe", "value": 1}
        wrong_domain["identity"] = identity("other", wrong_domain)
        try:
            ArtifactStore(Path(bound["store"])).publish(
                bound["descriptor_identity"],
                bound["invocation_key"],
                bound["canonical_input_identity"],
                "build-artifact-set",
                {"outcome": "completed"},
                [wrong_domain],
            )
        except PublicationError as error:
            assert str(error) == "artifact.identity-domain-mismatch"
        else:
            raise AssertionError("wrong identity domain was accepted")


def test_runtime_refusal_publishes_closed_terminal_audit_set() -> None:
    with tempfile.TemporaryDirectory(prefix="schema2-authority-refusal-") as temporary:
        store_path = str(Path(temporary) / "store")
        request = {
            "command": "run",
            "invocation_key": invocation_key("limited-run"),
            "params": {"max_steps": 5},
            "store": store_path,
        }
        code, stdout, stderr = subprocess_cli(request)
        assert code == 2 and stderr is None
        assert stdout is not None
        assert stdout["outcome"] == "refused"
        assert stdout["set_kind"] == "terminal-audit-artifact-set"
        assert stdout["error"]["terminal_audit"]["kind"] == "publication-receipt"
        assert stdout["locator"].startswith("invocation:sha256:command-descriptor:")
        record = ArtifactStore(Path(store_path)).lookup(
            COMMANDS["run"]["identity"], request["invocation_key"]
        )
        assert record is not None
        assert record["descriptor"] == COMMANDS["run"]["identity"]
        assert record["receipt"]["descriptor"] == COMMANDS["run"]["identity"]
        assert (
            record["receipt"]["canonical_input_identity"]
            == bind(request)["canonical_input_identity"]
        )
        by_kind = {member["kind"]: member for member in record["members"]}
        assert (
            by_kind["terminal-audit"]["diagnostic"]["code"] == "runtime.limit-exceeded"
        )
        assert "resolved-model" in by_kind
        assert "resolved-runtime-profile" in by_kind
        assert not (
            {"evaluation-run", "metric-dataset", "evidence-assertion"} & set(by_kind)
        )
        assert by_kind["terminal-audit"]["rir"] == by_kind["resolved-model"]["identity"]
        assert (
            by_kind["terminal-audit"]["resolved_runtime_profile"]
            == by_kind["resolved-runtime-profile"]["identity"]
        )
        retry_code, retry, retry_error = subprocess_cli(request)
        assert retry_code == 2 and retry_error is None
        assert retry is not None and retry["idempotent_replay"] is True
        assert retry["error"]["terminal_audit"] == stdout["error"]["terminal_audit"]


TESTS: list[tuple[str, Callable[[], None]]] = [
    (
        "bootstrap agreement and closed ontology",
        test_bootstrap_agreement_and_closed_ontology,
    ),
    ("rule selection and mutations", test_rule_selection_and_consulted_rule_mutations),
    (
        "bootstrap malformed containers",
        test_bootstrap_malformed_containers_are_closed_diagnostics,
    ),
    (
        "kernel identity four-path rehash",
        test_kernel_identity_is_independently_rehashed_on_all_four_paths,
    ),
    ("semantic RIR normal form", test_independent_compilers_make_semantic_normal_form),
    ("package lock closure", test_package_lock_is_closed_and_provenance_is_separate),
    ("crossed evaluators and exact RNG", test_crossed_evaluators_and_exact_rng_agree),
    (
        "discriminated insufficient outcome",
        test_discriminated_insufficient_cannot_commit,
    ),
    ("runtime limits and rollback", test_runtime_limits_refuse_and_roll_back),
    (
        "resolved runtime profile bindings",
        test_resolved_runtime_profile_binding_and_tamper_refusals,
    ),
    ("closed outcome tags and payloads", test_closed_outcome_tags_and_payloads),
    (
        "buffered event writes",
        test_event_writes_are_buffered_snapshot_reads_and_single_final_write,
    ),
    ("unknown primitive refusal", test_unknown_primitive_has_no_host_fallback),
    (
        "LDB composition mutation",
        test_ldb_composition_changes_identity_and_both_behaviors,
    ),
    (
        "replay profile conflict gate",
        test_replay_profile_conflict_blocks_positive_evidence,
    ),
    (
        "independent evaluator source boundary",
        test_evaluators_share_no_domain_or_semantic_implementation,
    ),
    ("descriptor-derived CLI", test_cli_descriptor_defaults_and_cross_layer_commands),
    (
        "invocation key and canonical input",
        test_invocation_key_and_canonical_input_contract,
    ),
    (
        "descriptor routing reverse conformance",
        test_descriptor_identity_routing_and_reverse_conformance,
    ),
    (
        "invocation retry/conflict/recovery",
        test_invocation_idempotency_conflict_and_recovery,
    ),
    ("atomic publication fault", test_publication_fault_has_no_partial_visibility),
    (
        "store member and receipt integrity",
        test_store_rehashes_members_receipts_and_member_sets,
    ),
    (
        "terminal-audit publication",
        test_runtime_refusal_publishes_closed_terminal_audit_set,
    ),
]


def main() -> int:
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"PASS all {len(TESTS)} groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
