"""Declared Enum parameter containers refuse before member evaluation."""

import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.structured_values import evaluate_structured_value_vector
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _bind_package_vector_set,
    _consumer_b,
    _consumer_b_evaluate_structured_value_vector,
)
from schema2_bootstrap_production_support import _reidentify_graph_root
from test_current_namespace_public import _PublicCandidate, _members


def _enum_authorities(*, renamed=False, malformed=None):
    kernel, language = mutable_authorities()
    packages = language["language"]["packages"]
    constructor = next(
        definition
        for package in packages
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.constructors"
        for definition in closure["definitions"]
        if definition.get("value_rule", {}).get("operator") == "enum-member"
    )
    original_member = constructor["value_rule"]["members_member"]
    selected_member = "labels" if renamed else original_member
    constructor["parameters"] = [selected_member]
    constructor["value_rule"]["members_member"] = selected_member
    definition_kind = constructor["value_rule"]["definition_kind"]

    def rename_type(expression):
        # Only Type-expression positions are traversed, never authored values.
        if isinstance(expression, dict):
            if expression.get("kind") == definition_kind and renamed:
                expression[selected_member] = expression.pop(original_member)
            for value in expression.values():
                rename_type(value)
        elif isinstance(expression, list):
            for value in expression:
                rename_type(value)

    for package in packages:
        for closure in package["semantic_closure"]:
            if closure["authority_path"] == "language.nominal_types":
                for nominal in closure["definitions"]:
                    rename_type(nominal["definition"])
    for vector_set in language.package_conformance_vector_sets:
        for vector in vector_set["vector_definitions"]:
            if vector.get("kind") != "structured-value":
                continue
            for side in ("left", "right"):
                envelope = vector["input"].get(side)
                if isinstance(envelope, dict):
                    rename_type(envelope.get("type"))
            rename_type(vector["expect"].get("type"))

    if malformed is not None:
        package = next(package for package in packages if package["id"] == "game.build")
        nominal = next(
            nominal
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.nominal_types"
            for nominal in closure["definitions"]
            if nominal["constructor"] == constructor["id"]
        )
        definition = nominal["definition"]
        if malformed == "missing":
            del definition[selected_member]
        elif malformed == "null":
            definition[selected_member] = None
        elif malformed == "integer":
            definition[selected_member] = 1
        else:
            assert malformed == "string"
            # Every previous member remains a substring. A host membership test
            # must not mistake this scalar for the declared Enum collection.
            definition[selected_member] = "::".join(definition[selected_member])
    vector_sets = {
        vector_set["package_id"]: vector_set
        for vector_set in language.package_conformance_vector_sets
    }
    for package in packages:
        _bind_package_vector_set(package, vector_sets[package["id"]], kernel=kernel)
    _reidentify_graph_root(language)
    return kernel, language


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "renamed"])
def test_complete_enum_parameter_rename_preserves_vectors_and_public_execution(
    tmp_path, renamed
):
    kernel, language = _enum_authorities(renamed=renamed)
    assert isinstance(
        admit_authority_context(kernel, language), AdmittedAuthorityContext
    )
    assert _consumer_b(kernel, language)["admitted"]
    arguments = {
        "nominal_types": language.package_releases,
        "kernel": kernel,
        "resource_limit": language.root["resources"]["max_rule_match_steps"],
    }
    vectors = [
        vector
        for vector_set in language.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector.get("kind") == "structured-value"
    ]
    assert vectors
    # Keep every original expected observation, including the three anonymous
    # type expressions whose selectors must travel with the constructor rename.
    for vector in vectors:
        assert evaluate_structured_value_vector(vector, **arguments) == vector["expect"]
        assert (
            _consumer_b_evaluate_structured_value_vector(vector, **arguments)
            == vector["expect"]
        )
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, language))
    example = Path(__file__).parents[1] / "examples/schema2/bounded-fold"
    candidate.write_source(json.loads((example / "model-source.json").read_text()))
    candidate.cli("model", "check", str(candidate.source))
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "a1" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    rir_path = tmp_path / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = json.loads((example / "experiment.json").read_text())
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    specification_path = tmp_path / "experiment.json"
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
        str(tmp_path / "run.json"),
        "--invocation-key",
        "a2" * 32,
    )
    metrics = _members(run)["metric-dataset"]
    assert {row["metric"]: row["value"] for row in metrics["samples"]} == {
        "ordered_value": 1234,
        "selected_count": 2,
    }


@pytest.mark.parametrize("malformed", ["missing", "null", "integer", "string"])
def test_resealed_malformed_enum_parameter_refuses_authority_and_public_loading(
    tmp_path, malformed
):
    kernel, language = _enum_authorities(renamed=True, malformed=malformed)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, language))
    # Enter through the real subprocess before checking either in-process
    # consumer: malformed authority must produce the typed refusal envelope.
    result = candidate.cli("package", "list", success=False)
    assert candidate.receipts[-1]["returncode"] == 2
    assert result["error"]["category"] == "refusal"
    assert [row["code"] for row in result["error"]["diagnostics"]] == [
        "kernel.vector_mismatch"
    ]
    first = admit_authority_context(kernel, language)
    second = _consumer_b(kernel, language)
    assert not isinstance(first, AdmittedAuthorityContext)
    assert [row.code for row in first.diagnostics] == ["kernel.vector_mismatch"]
    assert not second["admitted"]
    assert [row[1] for row in second["diagnostics"]] == ["kernel.vector_mismatch"]
