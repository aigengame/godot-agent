"""Routing follows declared output fields while recipe-local binders are renameable."""

import json

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from test_bounded_fold_public import _source, _specification
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
    _reidentify_language_bundle,
)


def _renamed_authorities():
    kernel, language = mutable_authorities()
    renamed = 0
    for profile in language["language"]["resolution_profiles"]:
        for recipe in profile["relation_recipes"]:
            names = {
                binding["name"]: f"opaque.local.{index}"
                for index, binding in enumerate(recipe["bindings"])
            }

            def replace_reference(value):
                if isinstance(value, dict):
                    if value.get("root") == "binding":
                        value["binding"] = names[value["binding"]]
                    for child in value.values():
                        replace_reference(child)
                elif isinstance(value, list):
                    for child in value:
                        replace_reference(child)

            replace_reference(recipe)
            for binding in recipe["bindings"]:
                binding["name"] = names[binding["name"]]
                renamed += 1
    assert renamed > 4
    _reidentify_language_bundle(language)
    return kernel, language


def test_all_recipe_local_binders_can_be_renamed_through_public_execution(tmp_path):
    kernel, language = _renamed_authorities()
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    independent = _consumer_b(kernel, language)
    assert independent["admitted"], independent["diagnostics"]
    source = _source()
    reference = _reference_check_source(source, kernel, language)
    assert not isinstance(reference, tuple), reference
    expected = _reference_semantic_artifacts(reference)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, language))
    candidate.write_source(source)
    built = _members(
        candidate.cli(
            "model",
            "build",
            str(candidate.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "91" * 32,
        )
    )
    assert all(built[role] == value for role, value in expected.items())
    rir = built["rir-semantic-payload"]
    rir_path = tmp_path / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = tmp_path / "experiment.json"
    specification.write_text(json.dumps(_specification(rir, [1, 2, 3, 4])))
    candidate.cli("experiment", "check", str(specification), "--rir", str(rir_path))
    outcome = _members(
        candidate.cli(
            "experiment",
            "run",
            str(specification),
            "--rir",
            str(rir_path),
            "--out",
            str(tmp_path / "run"),
            "--invocation-key",
            "92" * 32,
        )
    )
    assert {
        row["metric"]: row["value"] for row in outcome["metric-dataset"]["samples"]
    } == {
        "selected_count": 2,
        "ordered_value": 1234,
    }


@pytest.mark.parametrize(
    "mutation", ["missing-binding", "non-binding-field", "wrong-source"]
)
def test_routing_retains_actual_binding_and_source_obligations(mutation):
    kernel, language = _renamed_authorities()
    recipe = next(
        recipe
        for recipe in language["language"]["resolution_profiles"][0]["relation_recipes"]
        if recipe["id"] == "modules"
    )
    field = next(field for field in recipe["fields"] if field["name"] == "module")
    if mutation == "missing-binding":
        field["term"]["binding"] = "absent.local"
    elif mutation == "non-binding-field":
        # A valid source string cannot replace this required binding projection.
        field["term"] = {"root": "source", "path": ["manifest", "entry_module"]}
    else:
        binding = next(
            binding
            for binding in recipe["bindings"]
            if binding["name"] == field["term"]["binding"]
        )
        binding["source"]["path"] = ["manifest", "requirements"]
    _reidentify_language_bundle(language)
    assert not isinstance(
        admit_authority_context(kernel, language), AdmittedAuthorityContext
    )
    assert not _consumer_b(kernel, language)["admitted"]
