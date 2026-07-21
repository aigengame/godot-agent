"""Executable dogfooding vectors for the repaired orthogonality probe."""

# ruff: noqa: E402 -- direct script and pytest collection share local modules.

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from authority import (
    DIAGNOSTIC_AUTHORITY,
    DOMAIN_PACKAGE_RELEASES,
    KERNEL,
    base_bundle,
    experiment,
    extend_bundle,
    full_bundle,
    model_source,
)
from canonical import canonical_bytes, clone, identity, verify_artifact
from cli import HANDLER_CALLS, dispatch
from compiler import CompileRefusal, compile_model
from descriptor import (
    RUN_DESCRIPTOR,
    SURFACE_MANIFEST,
    DescriptorViolation,
    reverse_conform_handlers,
    validate_artifact_set,
    validate_handler_result,
    validate_public_envelope,
)
from projections import generate, reverse_conformance
from runtime import EVALUATOR_ID, actual_platform, execute, resolved_runtime_profile
from store import ArtifactStore, PublicationError


CLI = ROOT / "cli.py"


def _reidentify(value: dict[str, Any]) -> dict[str, Any]:
    value["identity"] = identity(
        value["kind"], {key: item for key, item in value.items() if key != "identity"}
    )
    return value


def _reidentify_bundle(bundle: dict[str, Any], release: dict[str, Any]) -> None:
    _reidentify(release)
    _reidentify(bundle)


def _expect_compile_refusal(
    bundle: dict[str, Any], source: dict[str, Any], code: str
) -> CompileRefusal:
    try:
        compile_model(bundle, source)
    except CompileRefusal as refusal:
        assert refusal.code == code
        return refusal
    raise AssertionError(f"expected {code}")


def _key(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _resource_operation(
    bundle: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    release = next(item for item in bundle["packages"] if item["id"] == "game.resource")
    return release, release["operations"][0]


def _request(directory: str, label: str, **params: Any) -> dict[str, Any]:
    return {
        "command": "probe run",
        "invocation_key": _key(label),
        "params": params,
        "store": directory,
    }


def _experiment(
    built: dict[str, Any], scenario: str, **overrides: Any
) -> dict[str, Any]:
    return experiment(scenario, built["rir"]["identity"], **overrides)


def test_vertical_pipeline_consumes_independent_experiment() -> None:
    bundle = full_bundle()
    source = model_source()
    built = compile_model(bundle, source)
    spec = _experiment(built, "interrupted")
    result = execute(bundle, built, spec)
    assert result["status"] == "completed"
    assert [built[name]["kind"] for name in ("source", "ast", "hir", "rir")] == [
        "model-source-package",
        "authoring-ast",
        "typed-hir",
        "resolved-model",
    ]
    assert "event_sequence" not in built["rir"]
    assert [item["id"] for item in built["rir"]["use_sites"]] == [
        "reserve",
        "interrupt",
        "effect_apply",
        "effect_reapply",
        "effect_remove",
    ]
    assert result["experiment"] == spec
    assert result["experiment_binding"]["experiment"] == spec["identity"]
    assert result["experiment_binding"]["rir"] == built["rir"]["identity"]
    assert [item["use_site"] for item in result["run"]["trace"]] == [
        "reserve",
        "interrupt",
    ]


def test_experiment_input_drives_insufficient_without_source_mutation() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    success_spec = _experiment(built, "success")
    insufficient_spec = _experiment(built, "insufficient")
    assert built["source"]["identity"] == built["source"]["identity"]
    success = execute(bundle, built, success_spec)
    insufficient = execute(bundle, built, insufficient_spec)
    assert success["run"]["initial_state"]["resource.current"] == 10
    assert insufficient["run"]["initial_state"]["resource.current"] == 2
    assert success["run"]["outcomes"][0]["tag"] == "reserved"
    assert insufficient["run"]["outcomes"][0]["tag"] == "insufficient"
    assert insufficient["run"]["initial_state"] == insufficient["run"]["final_state"]


def test_experiment_selectors_are_executed_including_empty_selection() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source(extra_attribute=True))
    empty = execute(bundle, built, _experiment(built, "success", selectors=[]))
    assert empty["metrics"]["samples"] == []
    selected = execute(
        bundle,
        built,
        _experiment(built, "success", selectors=[{"kind": "all-exported-quantities"}]),
    )
    names = [sample["metric"] for sample in selected["metrics"]["samples"]]
    assert names == [
        "symbol.final.focus",
        "symbol.final.health",
        "symbol.final.resource",
    ]


def test_experiment_acceptance_changes_verdict() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    accepted = execute(
        bundle,
        built,
        _experiment(
            built,
            "success",
            acceptance={"kind": "final-value", "path": "resource.current", "equals": 7},
        ),
    )
    rejected = execute(
        bundle,
        built,
        _experiment(
            built,
            "success",
            acceptance={
                "kind": "final-value",
                "path": "resource.current",
                "equals": 99,
            },
        ),
    )
    assert accepted["evaluation"]["verdict"] == "satisfied"
    assert rejected["evaluation"]["verdict"] == "unsatisfied"
    assert accepted["experiment"]["identity"] != rejected["experiment"]["identity"]


def test_experiment_shape_input_sequence_selector_and_acceptance_refuse_predispatch() -> (
    None
):
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    cases: list[tuple[dict[str, Any], str]] = []
    bad_input = _experiment(built, "success")
    bad_input["inputs"]["resource.current"] = "ten"
    cases.append((_reidentify(bad_input), "experiment.input-type-invalid"))
    bad_sequence = _experiment(built, "interrupted")
    bad_sequence["event_sequence"][1]["sequence"] = 1
    cases.append((_reidentify(bad_sequence), "experiment.event-sequence-invalid"))
    bad_selector = _experiment(built, "success")
    bad_selector["metric_selectors"][0]["host_filter"] = True
    cases.append((_reidentify(bad_selector), "experiment.selector-unknown"))
    bad_acceptance = _experiment(built, "success")
    bad_acceptance["acceptance"] = {
        "kind": "final-value",
        "path": "host.secret",
        "equals": 1,
    }
    cases.append((_reidentify(bad_acceptance), "experiment.acceptance-invalid"))
    for specification, code in cases:
        result = execute(bundle, built, specification)
        assert result["status"] == "refused" and result["phase"] == "pre-dispatch"
        assert result["diagnostic"]["code"] == code
        assert result["terminal_audit"] is None


def test_experiment_is_exactly_bound_to_one_rir() -> None:
    bundle = full_bundle()
    base = compile_model(bundle, model_source())
    extended = compile_model(bundle, model_source(extra_attribute=True))
    base_spec = _experiment(base, "success")
    assert execute(bundle, base, base_spec)["status"] == "completed"
    refused = execute(bundle, extended, base_spec)
    assert refused["status"] == "refused" and refused["phase"] == "pre-dispatch"
    assert refused["diagnostic"]["code"] == "experiment.rir-binding-mismatch"
    assert refused["terminal_audit"] is None
    assert execute(bundle, extended, _experiment(extended, "success"))["status"] == (
        "completed"
    )


def test_experiment_quantity_support_refuses_before_evaluation_dispatch() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    spec = _experiment(built, "success")
    spec["inputs"]["resource.current"] = -1
    _reidentify(spec)
    result = execute(bundle, built, spec)
    assert result["status"] == "refused" and result["phase"] == "pre-dispatch"
    assert result["stage"] == "evaluation"
    assert result["diagnostic"]["code"] == "experiment.input-support-invalid"
    assert result["terminal_audit"] is None


def test_attribute_only_edit_uses_admitted_generic_quantity() -> None:
    bundle = full_bundle()
    base = compile_model(bundle, model_source())
    extended = compile_model(bundle, model_source(extra_attribute=True))
    focus = next(
        symbol
        for symbol in extended["hir"]["symbols"]
        if symbol["symbol"].endswith("::focus")
    )
    assert focus["type"]["kind"] == "game.stat.generic"
    assert focus["type"]["unit"] == "game:point"
    assert focus["type"]["numeric_profile"] == "exact-int-v1"
    assert base["lock"] == extended["lock"]
    assert base["projections"] == extended["projections"]
    assert base["rir"]["use_sites"] == extended["rir"]["use_sites"]
    assert base["rir"]["identity"] != extended["rir"]["identity"]
    base_run = execute(bundle, base, _experiment(base, "success"))
    extended_run = execute(bundle, extended, _experiment(extended, "success"))
    assert base_run["run"]["outcomes"] == extended_run["run"]["outcomes"]
    assert extended_run["run"]["final_state"]["attributes.focus"] == 7


def test_unknown_quantity_kind_unit_and_profile_refuse() -> None:
    bundle = full_bundle()
    for field, value, code in (
        ("kind", "probe.unadmitted", "static.quantity-kind-unknown"),
        ("unit", "game:mana", "static.quantity-unit-unknown"),
        ("numeric_profile", "host-float", "static.quantity-numeric-profile-unknown"),
    ):
        source = model_source(extra_attribute=True)
        source["symbols"][-1]["type"][field] = value
        _reidentify(source)
        _expect_compile_refusal(bundle, source, code)


def test_malformed_quantity_support_is_always_a_typed_static_refusal() -> None:
    bundle = full_bundle()
    supports: tuple[Any, ...] = (
        None,
        {"minimum": "zero", "maximum": 999},
        {"minimum": 10, "maximum": 0},
        {"minimum": False, "maximum": 999},
    )
    for support in supports:
        source = model_source()
        source["symbols"][0]["type"]["support"] = support
        _reidentify(source)
        refusal = _expect_compile_refusal(
            bundle, source, "static.quantity-support-invalid"
        )
        assert refusal.stage == "static"


def test_package_releases_are_complete_content_addressed_authorities() -> None:
    bundle = full_bundle()
    required = {
        "kind",
        "identity",
        "id",
        "version",
        "dependencies",
        "provides",
        "requires_capabilities",
        "quantity_kinds",
        "units",
        "numeric_profiles",
        "runtime_profiles",
        "operations",
        "vectors",
        "diagnostics",
    }
    assert set(DOMAIN_PACKAGE_RELEASES) == {
        "foundation",
        "resource",
        "interruption",
        "effect",
    }
    assert all(
        set(release) == required and verify_artifact(release)
        for release in bundle["packages"]
    )
    built = compile_model(bundle, model_source())
    selected = {item["release_identity"] for item in built["lock"]["selected"]}
    assert selected == {release["identity"] for release in bundle["packages"]}
    for operation, binding in built["lock"]["operation_bindings"].items():
        assert binding["package_release"] in selected
        assert binding["program_identity"].startswith("sha256:operation-program:")
        assert binding["operation_identity"].startswith(
            "sha256:operation-specification:"
        )
        assert operation.startswith("game.")
    for release in bundle["packages"]:
        for operation in release["operations"]:
            assert set(operation["effects"]) == {
                "state_reads",
                "state_writes",
                "emitted_signals",
                "scheduled_events",
                "canceled_events",
                "named_random_streams",
            }
            assert set(operation["state_contract"]) == set(operation["kind_rules"])
            assert set(operation["state_contract"]) == set(operation["unit_rules"])
            assert operation["permitted_numeric_profiles"] == ["exact-int-v1"]


def test_package_record_tampering_refuses_before_resolution() -> None:
    bundle = full_bundle()
    release, operation = _resource_operation(bundle)
    operation["body"]["then"]["outcome"]["fields"]["amount"]["value"] = 4
    _reidentify(bundle)
    refusal = _expect_compile_refusal(
        bundle, model_source(), "bundle.package-release-identity-invalid"
    )
    assert refusal.stage == "ingress"
    assert not verify_artifact(release)


def test_generated_package_surface_rejects_missing_extra_and_changed() -> None:
    bundle = full_bundle()
    expected = generate(bundle)
    reverse_conformance(bundle, expected)
    missing = clone(expected)
    del missing["vectors"]
    try:
        reverse_conformance(bundle, missing)
    except Exception as refusal:
        assert getattr(refusal, "code") == "projection.inventory-mismatch"
    else:
        raise AssertionError("missing projection accepted")
    extra = clone(expected)
    extra["host_registry"] = clone(expected["registry"])
    try:
        reverse_conformance(bundle, extra)
    except Exception as refusal:
        assert getattr(refusal, "code") == "projection.inventory-mismatch"
    else:
        raise AssertionError("extra projection accepted")
    changed = clone(expected)
    changed["schema"]["packages"][0]["types"] = []
    _reidentify(changed["schema"])
    try:
        compile_model(bundle, model_source(), supplied_projections=changed)
    except CompileRefusal as refusal:
        assert refusal.code == "projection.content-mismatch"
    else:
        raise AssertionError("changed projection accepted")


def test_use_site_closed_variants_refuse_before_rir() -> None:
    bundle = full_bundle()
    base = model_source()
    reserve = next(item for item in base["use_sites"] if item["id"] == "reserve")
    cases: list[tuple[dict[str, Any], str]] = []
    missing = clone(base)
    next(item for item in missing["use_sites"] if item["id"] == "reserve")[
        "match"
    ].pop()
    cases.append((missing, "static.variant-arm-missing"))
    duplicate = clone(base)
    duplicate_reserve = next(
        item for item in duplicate["use_sites"] if item["id"] == "reserve"
    )
    duplicate_reserve["match"].append(clone(duplicate_reserve["match"][0]))
    cases.append((duplicate, "static.variant-arm-duplicate"))
    unknown = clone(base)
    next(item for item in unknown["use_sites"] if item["id"] == "reserve")["match"][0][
        "tag"
    ] = "other"
    cases.append((unknown, "static.variant-arm-unknown"))
    payload = clone(base)
    next(item for item in payload["use_sites"] if item["id"] == "reserve")["match"][1][
        "payload"
    ]["amount"] = "Enum"
    cases.append((payload, "static.variant-payload-type-invalid"))
    assert reserve["operation"] == "game.resource.reserve"
    for source, code in cases:
        _reidentify(source)
        _expect_compile_refusal(bundle, source, code)


def test_operation_undeclared_write_refuses_static() -> None:
    bundle = full_bundle()
    release, operation = _resource_operation(bundle)
    operation["body"]["then"]["writes"].append(
        {
            "node": "write",
            "path": "attributes.health",
            "value": {"node": "literal", "value": 1},
        }
    )
    _reidentify_bundle(bundle, release)
    _expect_compile_refusal(bundle, model_source(), "static.program-write-unknown")


def test_operation_wrong_outcome_tag_refuses_static() -> None:
    bundle = full_bundle()
    release, operation = _resource_operation(bundle)
    operation["body"]["then"]["outcome"]["tag"] = "host-success"
    _reidentify_bundle(bundle, release)
    _expect_compile_refusal(bundle, model_source(), "static.operation-result-drift")


def test_operation_wrong_outcome_payload_refuses_static() -> None:
    bundle = full_bundle()
    release, operation = _resource_operation(bundle)
    operation["body"]["then"]["outcome"]["fields"]["amount"] = {
        "node": "literal",
        "value": "three",
    }
    _reidentify_bundle(bundle, release)
    _expect_compile_refusal(bundle, model_source(), "static.operation-result-drift")


def test_operation_unknown_kernel_node_refuses_static() -> None:
    bundle = full_bundle()
    release, operation = _resource_operation(bundle)
    operation["body"]["condition"]["node"] = "host_callback"
    _reidentify_bundle(bundle, release)
    _expect_compile_refusal(bundle, model_source(), "static.program-node-unknown")


def test_operation_kernel_nodes_are_closed_against_extra_fields() -> None:
    bundle = full_bundle()
    release, operation = _resource_operation(bundle)
    operation["body"]["host_hint"] = "call-resource-reserver"
    _reidentify_bundle(bundle, release)
    _expect_compile_refusal(bundle, model_source(), "static.program-node-shape-invalid")


def test_operation_semantic_declarations_are_closed_and_typed() -> None:
    mutations: tuple[tuple[Callable[[dict[str, Any]], None], str], ...] = (
        (
            lambda operation: operation["result"].__setitem__("host_hint", True),
            "static.operation-result-invalid",
        ),
        (
            lambda operation: operation["result"].__setitem__("kind", 7),
            "static.operation-result-invalid",
        ),
        (
            lambda operation: operation["kind_rules"].__setitem__(
                "resource.current", "host.unknown"
            ),
            "static.operation-kind-unit-rules-invalid",
        ),
        (
            lambda operation: operation["unit_rules"].__setitem__(
                "resource.current", "host:unknown"
            ),
            "static.operation-kind-unit-rules-invalid",
        ),
        (
            lambda operation: operation["parameters"].__setitem__("amount", "Int"),
            "static.operation-parameter-unconsumed",
        ),
        (
            lambda operation: operation.__setitem__("purity", "host-defined"),
            "static.operation-purity-invalid",
        ),
        (
            lambda operation: operation["resource_bounds"].__setitem__("host_steps", 1),
            "static.operation-resource-bound-invalid",
        ),
        (
            lambda operation: operation["resource_bounds"].__setitem__(
                "max_reads", "one"
            ),
            "static.operation-resource-bound-invalid",
        ),
    )
    for mutate, code in mutations:
        bundle = full_bundle()
        release, operation = _resource_operation(bundle)
        mutate(operation)
        _reidentify_bundle(bundle, release)
        refusal = _expect_compile_refusal(bundle, model_source(), code)
        assert refusal.stage == "static"


def test_runtime_revalidates_full_rir_operation_projection() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    mutations: tuple[Callable[[dict[str, Any]], None], ...] = (
        lambda use_site: use_site["effects"]["emitted_signals"].append("host.hidden"),
        lambda use_site: use_site["result"].__setitem__("kind", "ForgedOutcome"),
    )
    for mutate in mutations:
        changed = clone(built)
        mutate(changed["rir"]["use_sites"][0])
        _reidentify(changed["rir"])
        result = execute(
            bundle,
            changed,
            _experiment(changed, "success"),
            profile=resolved_runtime_profile(bundle, changed),
        )
        assert result["status"] == "refused" and result["phase"] == "pre-dispatch"
        assert result["diagnostic"]["code"] == ("runtime.operation-projection-mismatch")
        assert result["terminal_audit"] is None


def test_runtime_refuses_rir_operation_outside_selected_lock() -> None:
    bundle = full_bundle()
    selected = compile_model(bundle, model_source(extensions=("resource",)))
    complete = compile_model(bundle, model_source())
    effect_use = next(
        item for item in complete["rir"]["use_sites"] if item["id"] == "effect_apply"
    )
    selected["rir"]["use_sites"].append(clone(effect_use))
    _reidentify(selected["rir"])
    profile = resolved_runtime_profile(bundle, selected)
    result = execute(
        bundle, selected, _experiment(selected, "effect_lifecycle"), profile=profile
    )
    assert result["status"] == "refused"
    assert result["phase"] == "pre-dispatch"
    assert result["diagnostic"]["code"] == "runtime.operation-unselected"
    assert result["terminal_audit"] is None


def test_unused_package_keeps_lock_but_changes_exact_ldb_bound_rir() -> None:
    selected_bundle = extend_bundle(base_bundle(), "resource")
    expanded_bundle = extend_bundle(selected_bundle, "effect")
    source = model_source(extensions=("resource",))
    before = compile_model(selected_bundle, source)
    after = compile_model(expanded_bundle, source)
    assert before["lock"] == after["lock"]
    assert before["rir"]["use_sites"] == after["rir"]["use_sites"]
    assert before["rir"]["identity"] != after["rir"]["identity"]
    before_run = execute(selected_bundle, before, _experiment(before, "success"))
    after_run = execute(expanded_bundle, after, _experiment(after, "success"))
    assert before_run["run"]["outcomes"] == after_run["run"]["outcomes"]
    assert before_run["run"]["final_state"] == after_run["run"]["final_state"]


def test_resolved_profile_binds_every_execution_authority() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    profile = resolved_runtime_profile(bundle, built)
    assert profile["kernel"] == KERNEL["identity"]
    assert profile["language_bundle"] == bundle["identity"]
    assert profile["package_lock"] == built["lock"]["identity"]
    assert profile["rir"] == built["rir"]["identity"]
    assert profile["definition_id"] in built["lock"]["runtime_profiles"]
    assert profile["numeric_profile"] in built["lock"]["numeric_profiles"]
    assert profile["event_law"] in KERNEL["event_laws"]
    assert profile["evaluator"] == EVALUATOR_ID
    assert profile["platform"] == actual_platform()
    assert (
        execute(bundle, built, _experiment(built, "success"), profile=profile)["status"]
        == "completed"
    )


def test_profile_mutations_are_predispatch_refusals_without_audit() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    mutations = (
        ("definition", "sha256:runtime-profile-definition:" + "0" * 64),
        ("numeric_profile", "host-float"),
        ("event_law", "parallel-host-order"),
        ("rir", "sha256:resolved-model:" + "1" * 64),
        ("package_lock", "sha256:package-lock:" + "2" * 64),
    )
    for field, value in mutations:
        profile = resolved_runtime_profile(bundle, built)
        profile[field] = value
        _reidentify(profile)
        result = execute(bundle, built, _experiment(built, "success"), profile=profile)
        assert result["status"] == "refused"
        assert result["phase"] == "pre-dispatch"
        assert result["diagnostic"]["code"] == "runtime.profile-binding-invalid"
        assert result["terminal_audit"] is None
    invalid_budget = resolved_runtime_profile(bundle, built)
    invalid_budget["budgets"]["max_events"] = -1
    _reidentify(invalid_budget)
    result = execute(
        bundle, built, _experiment(built, "success"), profile=invalid_budget
    )
    assert result["diagnostic"]["code"] == "runtime.profile-budget-invalid"
    assert result["terminal_audit"] is None
    extra_field = resolved_runtime_profile(bundle, built)
    extra_field["host_mode"] = "fallback"
    _reidentify(extra_field)
    result = execute(bundle, built, _experiment(built, "success"), profile=extra_field)
    assert result["diagnostic"]["code"] == "runtime.profile-shape-invalid"
    assert result["terminal_audit"] is None


def test_profile_evaluator_and_platform_tampering_refuse_predispatch() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    evaluator = resolved_runtime_profile(bundle, built)
    evaluator["evaluator"] = "forged-evaluator"
    _reidentify(evaluator)
    platform_profile = resolved_runtime_profile(bundle, built)
    platform_profile["platform"]["machine"] = "forged-machine"
    _reidentify(platform_profile)
    for profile, code in (
        (evaluator, "runtime.profile-evaluator-mismatch"),
        (platform_profile, "runtime.profile-platform-mismatch"),
    ):
        result = execute(bundle, built, _experiment(built, "success"), profile=profile)
        assert result["status"] == "refused" and result["phase"] == "pre-dispatch"
        assert result["diagnostic"]["code"] == code
        assert result["terminal_audit"] is None


def test_resource_outcomes_remain_values_not_refusals() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    success = execute(bundle, built, _experiment(built, "success"))
    insufficient = execute(bundle, built, _experiment(built, "insufficient"))
    assert success["status"] == insufficient["status"] == "completed"
    assert success["run"]["outcomes"][0]["tag"] == "reserved"
    assert insufficient["run"]["outcomes"][0]["tag"] == "insufficient"
    assert insufficient["evaluation"]["verdict"] == "satisfied"


def test_interruption_refund_and_effect_lifecycle_still_execute() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    interrupted = execute(bundle, built, _experiment(built, "interrupted"))
    assert [item["tag"] for item in interrupted["run"]["outcomes"]] == [
        "reserved",
        "interrupted",
    ]
    assert interrupted["run"]["final_state"]["resource.current"] == 10
    effect = execute(bundle, built, _experiment(built, "effect_lifecycle"))
    assert [item["tag"] for item in effect["run"]["outcomes"]] == [
        "applied",
        "reapplied",
        "removed",
    ]
    assert [
        (snapshot["state"]["effect.stacks"], snapshot["state"]["effect.duration"])
        for snapshot in effect["snapshots"]
    ] == [(0, 0), (1, 3), (2, 5), (0, 0)]


def test_later_event_refusal_preserves_prior_commit_and_full_audit() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    profile = resolved_runtime_profile(bundle, built, max_event_writes=2)
    spec = _experiment(built, "interrupted")
    result = execute(bundle, built, spec, profile=profile)
    assert result["status"] == "refused" and result["phase"] == "post-dispatch"
    audit = result["terminal_audit"]
    assert len(audit["committed_trace_prefix"]) == 1
    assert audit["last_snapshot"]["state"]["resource.current"] == 7
    assert audit["last_snapshot"]["state"]["reservation.amount"] == 3
    assert audit["refusing_event"] == {"sequence": 2, "use_site": "interrupt"}
    assert audit["rollback"]["discarded_writes"] == {
        "action.status": "interrupted",
        "reservation.amount": 0,
        "resource.current": 10,
    }
    assert audit["rollback"]["state_unchanged_from_last_snapshot"] is True
    assert audit["diagnostic"] == {
        "code": "runtime.event-write-budget",
        "message": "The Event write set exceeded the resolved Runtime budget.",
        "primary_location": {
            "kind": "runtime-event",
            "sequence": 2,
            "use_site": "interrupt",
            "path": "$.experiment.event_sequence[1]",
        },
        "related_locations": [],
    }
    assert audit["refusal_stage"] == "runtime"
    assert audit["diagnostic_authority"] == DIAGNOSTIC_AUTHORITY["identity"]
    assert audit["resolved_runtime_profile"] == profile["identity"]
    assert audit["reproduction"] == {
        "kernel": KERNEL["identity"],
        "language_bundle": bundle["identity"],
        "package_lock": built["lock"]["identity"],
        "rir": built["rir"]["identity"],
        "experiment": spec["identity"],
        "profile": profile["identity"],
        "diagnostic_authority": DIAGNOSTIC_AUTHORITY["identity"],
    }
    assert audit["partial_success_artifacts"] == []
    assert result["replay"] is result["evidence"] is None


def test_zero_event_budget_audits_the_first_refusing_event() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    profile = resolved_runtime_profile(bundle, built, max_events=0)
    result = execute(bundle, built, _experiment(built, "success"), profile=profile)
    assert result["status"] == "refused" and result["phase"] == "post-dispatch"
    audit = result["terminal_audit"]
    assert audit["committed_trace_prefix"] == []
    assert audit["refusing_event"] == {"sequence": 1, "use_site": "reserve"}
    assert audit["diagnostic"] == {
        "code": "runtime.event-budget",
        "message": "The Experiment event count exceeded the resolved Runtime budget.",
        "primary_location": {
            "kind": "runtime-event",
            "sequence": 1,
            "use_site": "reserve",
            "path": "$.experiment.event_sequence[0]",
        },
        "related_locations": [],
    }
    assert audit["last_snapshot"]["sequence"] == 0
    assert audit["rollback"]["discarded_writes"] == {}
    assert audit["rollback"]["state_unchanged_from_last_snapshot"] is True


def test_determinism_remains_non_normative_and_issues_no_evidence() -> None:
    bundle = full_bundle()
    built = compile_model(bundle, model_source())
    spec = _experiment(built, "effect_lifecycle")
    first = execute(bundle, built, spec)
    second = execute(bundle, built, spec)
    for name in (
        "profile",
        "snapshots",
        "run",
        "experiment",
        "experiment_binding",
        "metrics",
        "evaluation",
    ):
        assert first[name] == second[name]
    assert first["replay"] is second["replay"] is None
    assert first["evidence"] is second["evidence"] is None
    assert first["evaluation"]["semantic_authority_gate"] == "unvalidated"


def test_descriptor_owns_handlers_outcomes_and_complete_membership() -> None:
    assert SURFACE_MANIFEST["commands"] == [RUN_DESCRIPTOR]
    assert RUN_DESCRIPTOR["request_envelope"]["closed"] is True
    assert set(RUN_DESCRIPTOR["outcomes"]) == {
        "completed",
        "runtime_refused",
        "predispatch_refused",
        "usage_error",
        "internal_error",
    }
    reverse_conform_handlers({RUN_DESCRIPTOR["handler"]: object()})
    try:
        reverse_conform_handlers({"host.extra": object()})
    except DescriptorViolation as error:
        assert str(error) == "descriptor.handler-inventory-mismatch"
    else:
        raise AssertionError("extra handler accepted")
    try:
        validate_artifact_set("completed", [])
    except DescriptorViolation as error:
        assert str(error).startswith("descriptor.artifact-multiplicity")
    else:
        raise AssertionError("empty success set accepted")


def test_descriptor_rejects_missing_extra_and_wrong_typed_outcome_fields() -> None:
    envelopes = (
        {"outcome": "usage_error", "code": "probe.invalid"},
        {
            "outcome": "usage_error",
            "code": "probe.invalid",
            "field": "params",
            "host_detail": "leak",
        },
        {"outcome": "usage_error", "code": "probe.invalid", "field": 7},
    )
    for index, envelope in enumerate(envelopes):
        result = {
            "outcome_name": "usage_error",
            "envelope": clone(envelope),
            "members": [],
        }
        try:
            validate_handler_result(result)
        except DescriptorViolation:
            pass
        else:
            raise AssertionError("invalid handler envelope accepted")
        with tempfile.TemporaryDirectory() as directory:
            request = _request(directory, f"invalid-envelope-{index}")

            def invalid_handler(
                _bound: dict[str, Any], invalid_result: dict[str, Any] = result
            ) -> dict[str, Any]:
                return clone(invalid_result)

            exit_code, stdout, stderr = dispatch(
                request, handlers={RUN_DESCRIPTOR["handler"]: invalid_handler}
            )
            assert exit_code == 4 and stdout is None and stderr is not None
            assert stderr["outcome"] == "internal_error"
            assert stderr["code"].startswith("descriptor.envelope-")
    try:
        validate_public_envelope(
            "usage_error",
            {"outcome": "usage_error", "code": "probe.invalid", "field": False},
        )
    except DescriptorViolation as error:
        assert str(error) == "descriptor.envelope-field-invalid:field"
    else:
        raise AssertionError("invalid public envelope accepted")


def test_cli_success_set_is_descriptor_validated_and_anchored() -> None:
    with tempfile.TemporaryDirectory() as directory:
        request = _request(directory, "cli-success", scenario="success")
        exit_code, stdout, stderr = dispatch(request)
        assert exit_code == 0 and stderr is None and stdout is not None
        assert stdout["artifact_set"] == "evaluation-artifact-set"
        record = ArtifactStore(Path(directory)).lookup(request["invocation_key"])
        assert record is not None
        assert record["anchor"]["publication_receipt"] == record["receipt"]["identity"]
        assert record["anchor"]["publication_record"] == record["record"]["identity"]
        validate_artifact_set(record["outcome_name"], record["members"])
        missing_release = clone(record["members"])
        missing_release.pop(
            next(
                index
                for index, member in enumerate(missing_release)
                if member["kind"] == "domain-package-release"
            )
        )
        try:
            validate_artifact_set(record["outcome_name"], missing_release)
        except DescriptorViolation as error:
            assert str(error) == "descriptor.artifact-relation-mismatch"
        else:
            raise AssertionError("selected package release omission accepted")


def test_cli_runtime_refusal_publishes_retrievable_terminal_audit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        request = _request(
            directory,
            "cli-runtime-refusal",
            scenario="interrupted",
            max_event_writes=2,
        )
        exit_code, stdout, stderr = dispatch(request)
        assert exit_code == 2 and stderr is None and stdout is not None
        assert stdout["phase"] == "post-dispatch"
        assert stdout["artifact_set"] == "terminal-audit-artifact-set"
        assert stdout["publication_receipt"].startswith("sha256:publication-receipt:")
        stored = ArtifactStore(Path(directory)).lookup(request["invocation_key"])
        assert stored is not None
        audits = [
            member for member in stored["members"] if member["kind"] == "terminal-audit"
        ]
        assert len(audits) == 1 and audits[0]["identity"] == stdout["terminal_audit"]
        assert not {
            "evaluation-run",
            "metric-dataset",
            "runtime-run",
            "replay",
            "evidence",
        } & {member["kind"] for member in stored["members"]}


def test_invocation_key_conflict_is_usage_error_before_handler() -> None:
    with tempfile.TemporaryDirectory() as directory:
        first = _request(directory, "key-conflict", scenario="success")
        assert dispatch(first)[0] == 0
        calls_after_first = len(HANDLER_CALLS)
        changed = clone(first)
        changed["params"] = {"scenario": "insufficient"}
        exit_code, stdout, stderr = dispatch(changed)
        assert exit_code == 3 and stdout is None
        assert stderr == {
            "outcome": "usage_error",
            "code": "invocation.key-conflict",
            "field": "invocation_key",
        }
        assert len(HANDLER_CALLS) == calls_after_first
        retry = dispatch(first)
        assert retry[0] == 0 and retry[1] is not None
        assert retry[1]["idempotent_replay"] is True
        assert len(HANDLER_CALLS) == calls_after_first


def test_coherent_member_record_receipt_rewrite_fails_unchanged_anchor() -> None:
    with tempfile.TemporaryDirectory() as directory:
        request = _request(directory, "coherent-rewrite", scenario="success")
        assert dispatch(request)[0] == 0
        root = Path(directory) / "committed" / request["invocation_key"]
        receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
        record = json.loads((root / "record.json").read_text(encoding="utf-8"))
        old_member_id = next(
            member_id
            for member_id in receipt["members"]
            if ":metric-dataset:" in member_id
        )
        old_path = root / "members" / (old_member_id.replace(":", "_") + ".json")
        member = json.loads(old_path.read_text(encoding="utf-8"))
        member["samples"].append({"metric": "forged", "value": 99})
        _reidentify(member)
        new_member_id = member["identity"]
        new_path = root / "members" / (new_member_id.replace(":", "_") + ".json")
        new_path.write_bytes(canonical_bytes(member) + b"\n")
        receipt["members"] = sorted(
            new_member_id if item == old_member_id else item
            for item in receipt["members"]
        )
        _reidentify(receipt)
        record["members"] = clone(receipt["members"])
        record["publication_receipt"] = receipt["identity"]
        _reidentify(record)
        (root / "receipt.json").write_bytes(canonical_bytes(receipt) + b"\n")
        (root / "record.json").write_bytes(canonical_bytes(record) + b"\n")
        try:
            ArtifactStore(Path(directory)).lookup(request["invocation_key"])
        except PublicationError as error:
            assert str(error) == "publication.anchor-binding-mismatch"
        else:
            raise AssertionError("coherent rewrite accepted")


def test_record_outcome_disagreement_with_receipt_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        request = _request(directory, "outcome-mismatch", scenario="success")
        assert dispatch(request)[0] == 0
        root = Path(directory) / "committed" / request["invocation_key"]
        anchor_path = Path(directory) / "anchors" / f"{request['invocation_key']}.json"
        record = json.loads((root / "record.json").read_text(encoding="utf-8"))
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        record["outcome_name"] = "runtime_refused"
        _reidentify(record)
        anchor["publication_record"] = record["identity"]
        _reidentify(anchor)
        (root / "record.json").write_bytes(canonical_bytes(record) + b"\n")
        anchor_path.write_bytes(canonical_bytes(anchor) + b"\n")
        try:
            ArtifactStore(Path(directory)).lookup(request["invocation_key"])
        except PublicationError as error:
            assert str(error) == "publication.metadata-mismatch:outcome_name"
        else:
            raise AssertionError("record/receipt outcome disagreement accepted")


def test_publication_fault_has_no_visible_anchor() -> None:
    with tempfile.TemporaryDirectory() as directory:
        failed = _request(
            directory, "publication-fault", scenario="success", fault="before_commit"
        )
        exit_code, stdout, stderr = dispatch(failed)
        assert exit_code == 4 and stdout is None
        assert stderr == {
            "outcome": "internal_error",
            "code": "publication.injected-before-commit",
        }
        assert ArtifactStore(Path(directory)).visible_keys() == []


def test_subprocess_cli_channels_follow_descriptor() -> None:
    with tempfile.TemporaryDirectory() as directory:
        request = _request(directory, "subprocess", scenario="success")
        completed = subprocess.run(
            [sys.executable, str(CLI), json.dumps(request)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0 and completed.stderr == ""
        assert json.loads(completed.stdout)["outcome"] == "completed"
        malformed = subprocess.run(
            [sys.executable, str(CLI), "not-json"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        assert malformed.returncode == 3 and malformed.stdout == ""
        assert json.loads(malformed.stderr)["outcome"] == "usage_error"


TESTS: list[Callable[[], None]] = [
    test_vertical_pipeline_consumes_independent_experiment,
    test_experiment_input_drives_insufficient_without_source_mutation,
    test_experiment_selectors_are_executed_including_empty_selection,
    test_experiment_acceptance_changes_verdict,
    test_experiment_shape_input_sequence_selector_and_acceptance_refuse_predispatch,
    test_experiment_is_exactly_bound_to_one_rir,
    test_experiment_quantity_support_refuses_before_evaluation_dispatch,
    test_attribute_only_edit_uses_admitted_generic_quantity,
    test_unknown_quantity_kind_unit_and_profile_refuse,
    test_malformed_quantity_support_is_always_a_typed_static_refusal,
    test_package_releases_are_complete_content_addressed_authorities,
    test_package_record_tampering_refuses_before_resolution,
    test_generated_package_surface_rejects_missing_extra_and_changed,
    test_use_site_closed_variants_refuse_before_rir,
    test_operation_undeclared_write_refuses_static,
    test_operation_wrong_outcome_tag_refuses_static,
    test_operation_wrong_outcome_payload_refuses_static,
    test_operation_unknown_kernel_node_refuses_static,
    test_operation_kernel_nodes_are_closed_against_extra_fields,
    test_operation_semantic_declarations_are_closed_and_typed,
    test_runtime_revalidates_full_rir_operation_projection,
    test_runtime_refuses_rir_operation_outside_selected_lock,
    test_unused_package_keeps_lock_but_changes_exact_ldb_bound_rir,
    test_resolved_profile_binds_every_execution_authority,
    test_profile_mutations_are_predispatch_refusals_without_audit,
    test_profile_evaluator_and_platform_tampering_refuse_predispatch,
    test_resource_outcomes_remain_values_not_refusals,
    test_interruption_refund_and_effect_lifecycle_still_execute,
    test_later_event_refusal_preserves_prior_commit_and_full_audit,
    test_zero_event_budget_audits_the_first_refusing_event,
    test_determinism_remains_non_normative_and_issues_no_evidence,
    test_descriptor_owns_handlers_outcomes_and_complete_membership,
    test_descriptor_rejects_missing_extra_and_wrong_typed_outcome_fields,
    test_cli_success_set_is_descriptor_validated_and_anchored,
    test_cli_runtime_refusal_publishes_retrievable_terminal_audit,
    test_invocation_key_conflict_is_usage_error_before_handler,
    test_coherent_member_record_receipt_rewrite_fails_unchanged_anchor,
    test_record_outcome_disagreement_with_receipt_is_rejected,
    test_publication_fault_has_no_visible_anchor,
    test_subprocess_cli_channels_follow_descriptor,
]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(TESTS)}/{len(TESTS)} orthogonality groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
