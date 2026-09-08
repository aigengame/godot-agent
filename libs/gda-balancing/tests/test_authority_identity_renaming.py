"""Opaque LDB identities preserve semantic admission and actual public execution."""

from copy import deepcopy
import json
from typing import Any

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import AdmittedRir, admit_rir
from gda_balancing.domain.structured_values import evaluate_structured_value_vector
from priority_protocol_support import authorities, source, specification
from schema2_bootstrap_conformance_support import (
    _bind_package_vector_set,
    _consumer_b,
    _consumer_b_evaluate_structured_value_vector,
)
from schema2_bootstrap_production_support import _consumer_a, _reidentify_graph_root
from schema2_runtime_independent_support import reference_runtime_artifacts
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import _reference_check_source


_RENAMES = {
    "numeric": {"exact-int64": "opaque.numeric.policy"},
    "typed-profile": {"standard.schema.nominal-structured": "opaque.literal.profile"},
    "constructors": {
        f"standard.schema.{role}": f"opaque.constructor.{role}"
        for role in ("enum", "record", "list", "ref")
    },
    "static-reasons": {
        f"structured.reason.{fault}": f"opaque.reason.{fault}"
        for fault in (
            "type-mismatch",
            "unknown-enum",
            "record-member-mismatch",
            "resource-exhausted",
        )
    },
}


def _rename(value: Any, names: dict[str, str]) -> Any:
    if isinstance(value, str):
        return names.get(value, value)
    if isinstance(value, list):
        return [_rename(row, names) for row in value]
    if isinstance(value, dict):
        return {names.get(key, key): _rename(row, names) for key, row in value.items()}
    return value


def _seal(language):
    vectors = {
        row["package_id"]: row for row in language.package_conformance_vector_sets
    }
    for package in language["language"]["packages"]:
        _bind_package_vector_set(package, vectors[package["id"]])
    _reidentify_graph_root(language)


def _candidate(role):
    kernel, language, entries = authorities()
    names = (
        {old: new for mapping in _RENAMES.values() for old, new in mapping.items()}
        if role == "all"
        else _RENAMES.get(role, {})
    )
    for package in language["language"]["packages"]:
        renamed = _rename(package, names)
        package.clear()
        package.update(renamed)
    for vectors in language.package_conformance_vector_sets:
        renamed = _rename(vectors, names)
        vectors.clear()
        vectors.update(renamed)
    _seal(language)
    return kernel, language, _rename(source(entries), names), names


@pytest.mark.parametrize("role", ["original", *_RENAMES, "all"])
def test_opaque_authority_roles_admit_build_and_execute_publicly(tmp_path, role):
    kernel, language, model_source, names = _candidate(role)
    before = deepcopy(kernel)
    for consumer in (_consumer_a, _consumer_b):
        report = consumer(kernel, language)
        assert report["admitted"], report["diagnostics"]
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    public = _PublicCandidate(tmp_path / role, authorities=(kernel, language))
    public.write_source(model_source)
    assert public.cli("model", "check", str(public.source))["checked"]
    build = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "31" * 32,
    )
    assert len(_members(build)) == 8
    rir = _members(build)["rir-semantic-payload"]
    locator = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    value = _rename(specification(rir), names)
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(value))
    assert public.cli("experiment", "check", str(path), "--rir", locator)["checked"]
    receipt = public.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        locator,
        "--out",
        str(tmp_path / "run"),
        "--invocation-key",
        "32" * 32,
    )
    members = _members(receipt)
    checked = check_experiment_value(value, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, members)
    assert members["metric-dataset"]["samples"][0]["value"] == 7
    assert members["evaluator-capability-manifest"]["numeric_policies"] == [
        names.get("exact-int64", "exact-int64")
    ]
    assert kernel == before
    # B independently compiles and executes the same authored request, then A
    # admits all six B members. No A result is supplied to B as a template.
    reference = _reference_check_source(model_source, kernel, language)
    assert not isinstance(reference, tuple), reference
    independent = reference_runtime_artifacts(reference, rir, value)
    assert validate_experiment_artifact_set(checked, independent)
    assert (
        independent["metric-dataset"]["samples"] == members["metric-dataset"]["samples"]
    )
    # Every existing structured value vector retains its full result/refusal,
    # including code and pointer, under the renamed profile/constructors/reasons.
    vector_count = 0
    for vector_set in language.package_conformance_vector_sets:
        for vector in vector_set["vector_definitions"]:
            if vector.get("kind") != "structured-value":
                continue
            vector_count += 1
            args = dict(
                nominal_types=language["language"]["packages"],
                kernel=kernel,
                resource_limit=language["resources"]["max_rule_match_steps"],
            )
            assert evaluate_structured_value_vector(vector, **args) == vector["expect"]
            assert (
                _consumer_b_evaluate_structured_value_vector(vector, **args)
                == vector["expect"]
            )
    assert vector_count == 24
    # The current descriptor and actual public error also survive reason ID renaming.
    invalid = deepcopy(value)
    assignments = invalid["scenarios"][0]["assignments"]
    index = next(
        i for i, row in enumerate(assignments) if row["target"]["name"] == "status"
    )
    assignments[index]["value"]["value"] = "undeclared-status"
    invalid_path = tmp_path / "invalid-enum.json"
    invalid_path.write_text(json.dumps(invalid))
    refused = public.cli(
        "experiment", "check", str(invalid_path), "--rir", locator, success=False
    )
    diagnostic = refused["error"]["diagnostics"][0]
    reason = next(
        row
        for row in context.language_bundle["language"]["reasons"]
        if row.get("stage") == "static"
        and row.get("signal") == "structured-value-unknown-enum"
    )
    assert diagnostic["code"] == reason["diagnostic"]
    assert (
        diagnostic["primary"]["pointer"]
        == f"/scenarios/0/assignments/{index}/value/value"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "overflow",
        "rounding",
        "profile-missing",
        "profile-duplicate",
        "profile-malformed",
        "constructor-missing",
        "constructor-duplicate-role",
        "constructor-malformed",
        "signal-missing",
        "signal-duplicate",
    ],
)
def test_opaque_identity_support_keeps_semantic_closure_refusals(fault):
    kernel, language, _model_source, _names = _candidate("all")
    package = next(
        row
        for row in language["language"]["packages"]
        if row["id"] == "standard.schema"
    )
    closures = {
        row["authority_path"]: row["definitions"] for row in package["semantic_closure"]
    }
    if fault in {"overflow", "rounding"}:
        quantity = next(
            row
            for row in language["language"]["packages"]
            if row["id"] == "core.quantity"
        )
        policies = next(
            row["definitions"]
            for row in quantity["semantic_closure"]
            if row["authority_path"] == "language.quantity.numeric_policies"
        )
        policies[0][fault] = "wrap" if fault == "overflow" else "nearest"
    elif fault.startswith("profile"):
        profiles = closures["language.literal_typing_profiles"]
        profile = next(
            row for row in profiles if row["source_kind"] == "typed-envelope"
        )
        if fault == "profile-missing":
            profiles.remove(profile)
            package["exports"]["literal_typing_profiles"].remove(profile["id"])
        elif fault == "profile-malformed":
            profile["admission"]["type_relation"] = "assignable"
        else:
            duplicate = {**deepcopy(profile), "id": "another.typed.profile"}
            profiles.append(duplicate)
            package["exports"]["literal_typing_profiles"].append(duplicate["id"])
    elif fault.startswith("constructor"):
        constructors = closures["language.constructors"]
        constructor = next(
            row
            for row in constructors
            if row.get("value_rule", {}).get("definition_kind") == "list"
        )
        if fault == "constructor-missing":
            del constructor["value_rule"]
        elif fault == "constructor-duplicate-role":
            duplicate = {**deepcopy(constructor), "id": "another.list.constructor"}
            constructors.append(duplicate)
            package["exports"]["constructors"].append(duplicate["id"])
        else:
            constructor["value_rule"]["order"] = "sort"
    else:
        reasons = closures["language.reasons"]
        reason = next(
            row
            for row in reasons
            if row.get("signal") == "structured-value-type-mismatch"
        )
        if fault == "signal-missing":
            del reason["signal"]
        else:
            other = next(
                row
                for row in reasons
                if row.get("signal") == "structured-value-unknown-enum"
            )
            other["signal"] = reason["signal"]
    _seal(language)
    for consumer in (_consumer_a, _consumer_b):
        report = consumer(kernel, language)
        assert not report["admitted"]
        assert report["diagnostics"]
        assert all(
            row[1] != "kernel.identity_mismatch" for row in report["diagnostics"]
        )
