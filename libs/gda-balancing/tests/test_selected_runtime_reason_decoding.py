"""Terminal refusal decoding follows selected reason meaning, not code spelling."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import (
    runtime_terminal_audit_members,
    validate_experiment_artifact_set,
)
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
    project_compiled_model_binding,
)
from gda_balancing.domain.runtime.execution import (
    RuntimeRefusalOutcome,
    evaluate_experiment,
)
from schema2_authority_support import mutable_authorities
from test_schema2_experiment_cli import (
    _experiment,
    _rpg_model_source,
    _widen_mitigated_damage_formula,
)
from test_schema2_model_cli import _reidentify_language_bundle


def _reason_context(*, remap: bool, event_limit: int | None, shared: bool = False):
    kernel, language_bundle = mutable_authorities()
    if event_limit is not None:
        next(
            row
            for row in language_bundle["language"]["runtime_profiles"]
            if row["id"] == "standard.exact-int64-event-v1"
        )["resource_bounds"]["max_event_steps"] = event_limit
    if remap:
        # Swap existing declarations rather than leaving an unowned diagnostic.
        # The unchanged Kernel permits these mappings; its existing diagnostic
        # vectors must state the same mapping to admit the candidate LDB.
        replacements = {
            "runtime.numeric_overflow": "runtime.step_limit_exceeded",
            "runtime.step_limit_exceeded": (
                "runtime.step_limit_exceeded" if shared else "runtime.numeric_overflow"
            ),
        }
        identifiers = {"runtime.reason.numeric-overflow", "runtime.reason.step-limit"}
        for reason in language_bundle["language"]["reasons"]:
            if reason["id"] in identifiers:
                reason["diagnostic"] = replacements[reason["diagnostic"]]
        for vector in language_bundle["vectors"]:
            if vector.get("reason") in identifiers:
                vector["diagnostic"] = replacements[vector["diagnostic"]]
        if shared:
            # A many-to-one mapping is legal. Remove its now-unreferenced
            # diagnostic from both the catalog and the owning package exports.
            language_bundle["diagnostics"].remove(
                next(
                    row
                    for row in language_bundle["diagnostics"]
                    if row["code"] == "runtime.numeric_overflow"
                )
            )
            next(
                row
                for row in language_bundle["language"]["packages"]
                if row["id"] == "standard.runtime"
            )["exports"]["diagnostics"].remove("runtime.numeric_overflow")
    _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    return context


@pytest.mark.parametrize(
    "event_limit", [None, 1], ids=["numeric-overflow", "step-limit"]
)
def test_legal_reason_mapping_preserves_exact_terminal_rollback_and_charge(
    tmp_path: Path, event_limit: int | None
):
    _assert_terminal_reason_mapping(tmp_path, event_limit, shared=False)


@pytest.mark.parametrize(
    "event_limit", [None, 1], ids=["numeric-overflow", "step-limit"]
)
def test_many_to_one_reason_mapping_preserves_exact_terminal_rollback_and_charge(
    tmp_path: Path, event_limit: int | None
):
    _assert_terminal_reason_mapping(tmp_path, event_limit, shared=True)


def _assert_terminal_reason_mapping(
    tmp_path: Path, event_limit: int | None, *, shared: bool
):
    source = _rpg_model_source()
    next(
        row for row in source["modules"][0]["symbols"] if row["symbol"] == "base_damage"
    )["domain"]["maximum"] = (1 << 63) - 1
    _widen_mitigated_damage_formula(source, damage_before_defense_maximum=(1 << 63) - 1)
    identities = []
    validity = []
    for remap in (False, True):
        context = _reason_context(remap=remap, event_limit=event_limit, shared=shared)
        model = check_model_source_value(source, authority_context=context)
        assert isinstance(model, CheckedModel), model
        artifacts = compile_checked_model(model)
        assert len(artifacts) == 8
        binding = project_compiled_model_binding(artifacts, context)
        identities.append(artifacts["rir-semantic-payload"]["semantic_identity"])
        receipt: dict[str, Any] = {"member_locators": []}
        for name, artifact in artifacts.items():
            path = tmp_path / f"{remap}-{name}.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            receipt["member_locators"].append(
                {"logical_name": name, "locator": str(path)}
            )
        build = artifacts["build-receipt"]
        specification = _experiment(
            kernel_identity=cast(str, build["kernel_identity"]),
            language_bundle_identity=cast(str, build["language_bundle_identity"]),
            source_identity=cast(str, build["source_identity"]),
            build_receipt=receipt,
            base_damage=1 << 62,
        )
        next(
            row
            for row in specification["scenarios"][0]["assignments"]
            if row["target"]["name"] == "critical_threshold"
        )["value"] = 100
        checked = check_experiment_value(
            specification, binding, authority_context=context
        )
        assert isinstance(checked, CheckedExperiment), checked
        outcome = evaluate_experiment(checked)
        assert isinstance(outcome, RuntimeRefusalOutcome), outcome
        members = {
            name: cast(dict[str, Any], member.value)
            for name, member in runtime_terminal_audit_members(checked, outcome).items()
        }
        audit = members["runtime-terminal-audit"]
        expected_code = (
            "runtime.numeric_overflow"
            if not (shared and remap) and (event_limit is None) != remap
            else "runtime.step_limit_exceeded"
        )
        assert audit["diagnostic"]["code"] == expected_code
        assert audit["refusing_event"]["reason"] == expected_code
        assert audit["committed_trace_prefix"] == []
        assert audit["rollback"] == {
            "committed": False,
            "state_before": [
                {"name": "actor_mana", "value": 30},
                {"name": "target_health", "value": 100},
            ],
            "state_after": [
                {"name": "actor_mana", "value": 30},
                {"name": "target_health", "value": 100},
            ],
        }
        assert audit["budget_counters"] == {
            "event_steps": 13 if event_limit is None else 2,
            "node_steps": 17 if event_limit is None else 6,
            "logical_time": 0,
            "queue_events": 0,
            "total_events": 1,
            "zero_time_depth": 0,
        }
        validity.append(validate_experiment_artifact_set(checked, members))
        if not shared:
            # Reseal both copies of the diagnostic together. Framing remains
            # valid, but its signal disagrees with the independently replayed
            # budget condition in either direction.
            tampered = deepcopy(members)
            payload = {
                key: value
                for key, value in tampered["runtime-terminal-audit"].items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
            wrong_code = (
                "runtime.numeric_overflow"
                if expected_code == "runtime.step_limit_exceeded"
                else "runtime.step_limit_exceeded"
            )
            payload["diagnostic"]["code"] = wrong_code
            payload["refusing_event"]["reason"] = wrong_code
            contract = checked.output_contracts["runtime-terminal-audit"]
            tampered["runtime-terminal-audit"] = contract.identify(payload)
            assert contract.verify(tampered["runtime-terminal-audit"])
            assert not validate_experiment_artifact_set(checked, tampered)
    assert identities[0] != identities[1]
    assert validity == [True, True]
