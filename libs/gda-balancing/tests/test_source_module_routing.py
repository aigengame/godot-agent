"""Declared Source collection addresses preserve execution and authored diagnostics."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.source_projection import source_schema_member
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_resolved_model,
    admit_rir,
    check_model_source_value,
)
from gda_balancing.domain.model._compilation import lower_checked_model
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    _reference_admits_semantic_artifacts,
    _reference_check_source,
    _reference_content_identity,
    _reference_semantic_artifacts,
    _reidentify_language_bundle,
)

_EXAMPLES = Path(__file__).parents[1] / "examples/schema2"


def _authorities(member):
    kernel, language = mutable_authorities()
    schema = next(
        row["schema"]
        for row in language["language"]["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )
    previous, modules_schema = source_schema_member(schema, "modules")
    assert modules_schema["items"]["semantic_role"] == "module"
    if member != previous:
        schema["properties"][member] = schema["properties"].pop(previous)
        schema["required"] = [
            member if key == previous else key for key in schema["required"]
        ]

        _reidentify_language_bundle(language)
    return kernel, language


def _source(example, member):
    source = json.loads((_EXAMPLES / example / "model-source.json").read_text())
    source[member] = source.pop("modules")
    return source


@pytest.fixture(scope="module", params=["modules", "opaque_modules", "opaque/modules~"])
def routed(request, tmp_path_factory):
    kernel, language = _authorities(request.param)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert _consumer_b(kernel, language)["admitted"]
    directory = tmp_path_factory.mktemp("source-modules")
    return (
        request.param,
        _PublicCandidate(directory, authorities=(kernel, language)),
        context,
    )


@pytest.mark.parametrize("example", ["bounded-fold", "rpg-combat-cast"])
def test_public_source_routing_preserves_compiler_and_runtime_results(routed, example):
    member, candidate, context = routed
    source = _source(example, member)
    candidate.write_source(source)
    candidate.cli("model", "check", str(candidate.source))
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / (example + "-build")),
        "--invocation-key",
        ("c1" if example == "bounded-fold" else "c2") * 32,
    )
    actual = _members(build)
    reference = _reference_check_source(source, candidate.kernel, candidate.ldb)
    assert not isinstance(reference, tuple), reference
    expected = _reference_semantic_artifacts(reference)
    assert len(expected) == 4
    assert all(actual[role] == value for role, value in expected.items())
    assert _reference_admits_semantic_artifacts(actual, reference)
    assert admit_resolved_model(
        {
            role: expected[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted
    rir = actual["rir-semantic-payload"]
    rir_path = candidate.directory / (example + "-rir.json")
    rir_path.write_text(json.dumps(rir))
    specification = json.loads((_EXAMPLES / example / "experiment.json").read_text())
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    specification_path = candidate.directory / (example + "-experiment.json")
    specification_path.write_text(json.dumps(specification))
    candidate.cli(
        "experiment", "check", str(specification_path), "--rir", str(rir_path)
    )
    run = candidate.cli(
        "experiment",
        "run",
        str(specification_path),
        "--rir",
        str(rir_path),
        "--out",
        str(candidate.directory / (example + "-run")),
        "--invocation-key",
        ("c3" if example == "bounded-fold" else "c4") * 32,
    )
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir)
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment)
    artifacts = _members(run)
    assert validate_experiment_artifact_set(checked, artifacts)
    if example == "bounded-fold":
        from schema2_runtime_independent_support import (
            reference_admits_runtime_artifacts,
            reference_runtime_artifacts,
        )

        independent = reference_runtime_artifacts(reference, rir, specification)
        assert validate_experiment_artifact_set(checked, independent)
        assert reference_admits_runtime_artifacts(
            reference, rir, specification, artifacts
        )
        assert all(
            value == artifacts[role]
            for role, value in independent.items()
            if role != "evaluator-capability-manifest"
        )
    values = {
        row["metric"]: row["value"] for row in artifacts["metric-dataset"]["samples"]
    }
    expected_values = (
        {"selected_count": 2, "ordered_value": 1234}
        if example == "bounded-fold"
        else {
            "enemy_damage_dealt": 14,
            "enemy_health_remaining": 63,
            "enemy_resource_remaining": 23,
            "player_damage_dealt": 37,
            "player_health_remaining": 86,
            "player_resource_remaining": 26,
        }
    )
    assert values == expected_values


def test_public_formula_conversion_uses_the_declared_source_collection(routed):
    member, candidate, _ = routed
    source = _source("rpg-combat-cast", member)
    module = source[member][0]
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source["package_requirements"],
        "module": {"id": module["id"], "imports": module["imports"]},
        "formula": deepcopy(module["formulas"][0]),
    }
    path = candidate.directory / "formula.json"
    path.write_text(json.dumps(request))
    rendered = candidate.cli("formula", "render", str(path))
    assert rendered["body"] == request["formula"]["body"]
    assert rendered["expression"] == request["formula"]["expression"]
    request["formula"].pop("body")
    path.write_text(json.dumps(request))
    parsed = candidate.cli("formula", "parse", str(path))
    assert parsed == rendered


@pytest.mark.parametrize("mutation", ["expression", "parameter-type"])
def test_public_formula_refusal_retains_the_authored_source_location(routed, mutation):
    member, candidate, _ = routed
    source = _source("rpg-combat-cast", member)
    formula = source[member][0]["formulas"][0]
    if mutation == "expression":
        formula["expression"] = "0"
    else:
        formula["parameters"][0]["type"] = "absent.alias"
    candidate.write_source(source)
    result = candidate.cli("model", "check", str(candidate.source), success=False)
    diagnostic = result["error"]["diagnostics"][0]
    profile = next(
        row
        for row in candidate.ldb["language"]["resolution_profiles"]
        if row.get("default")
    )
    assert diagnostic["primary"]["content_identity"] == _reference_content_identity(
        profile["source_identity_domain"], source
    )
    root = "/" + member.replace("~", "~0").replace("/", "~1") + "/0/formulas/0"
    assert diagnostic["primary"]["pointer"] == root + (
        "/expression" if mutation == "expression" else ""
    )
    assert diagnostic["code"] == (
        "language.formula_notation_mismatch"
        if mutation == "expression"
        else "language.source_contract_mismatch"
    )


def test_public_combined_root_module_import_and_symbol_routes_preserve_rir(tmp_path):
    from test_source_semantic_roles import _candidate

    kernel, graph, context, source, original = _candidate("routing")
    control = check_model_source_value(original)
    assert isinstance(control, CheckedModel), control
    expected_rir = lower_checked_model(control)["rir-semantic-payload"]
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    candidate.write_source(source)
    candidate.cli("model", "check", str(candidate.source))
    actual = _members(
        candidate.cli(
            "model",
            "build",
            str(candidate.source),
            "--out",
            str(tmp_path / "routing-build"),
            "--invocation-key",
            "c5" * 32,
        )
    )
    assert len(actual) == 8
    assert actual["rir-semantic-payload"] == expected_rir
    reference = _reference_check_source(source, kernel, context.language_bundle)
    assert not isinstance(reference, tuple), reference
    expected = _reference_semantic_artifacts(reference)
    assert len(expected) == 4
    assert all(actual[role] == value for role, value in expected.items())
    assert _reference_admits_semantic_artifacts(actual, reference)
    assert admit_resolved_model(
        {
            role: expected[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted


def test_unknown_semantic_module_route_refuses_before_source_compilation():
    kernel, language = _authorities("opaque/modules~")
    profile = next(
        row for row in language["language"]["resolution_profiles"] if row.get("default")
    )
    modules = next(row for row in profile["relation_recipes"] if row["id"] == "modules")
    assert modules["bindings"][0]["source"] == {
        "root": "source",
        "path": ["modules"],
    }
    modules["bindings"][0]["source"]["path"] = ["missing-route"]
    _reidentify_language_bundle(language)
    result = admit_authority_context(kernel, language)
    assert not isinstance(result, AdmittedAuthorityContext)
    assert [(row.stage, row.code, row.subject) for row in result.diagnostics] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]
    independent = _consumer_b(kernel, language)
    assert not independent["admitted"]
    assert independent["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]
