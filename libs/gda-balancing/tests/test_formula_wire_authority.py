"""Formula notation is declared Source authority, outside JSON Schema metadata."""

from copy import deepcopy
import json
import re

import pytest

import gda_balancing.domain.authority.admission as production_admission
import schema2_bootstrap_conformance_support as independent_admission

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.formula.notation import admit_formula_pair
from gda_balancing.domain.wire_schema import wire_schema_identity_for_kind
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _reidentify
from schema2_bootstrap_production_support import _consumer_a
from schema2_formula_conformance_support import admit_pair as independently_admit_pair
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_experiment_cli import _rpg_model_source
from test_schema2_template_cli import _reidentify_language_bundle


def _definition(language):
    return next(
        row
        for row in language["language"]["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )


def test_public_formula_consumes_declared_grammar_without_changing_source_schema(
    tmp_path,
):
    kernel, baseline = mutable_authorities()
    modified = deepcopy(baseline)
    grammar = _definition(modified)["formula_grammar"]
    grammar["binding_keyword"] = "bind"
    grammar["reserved_identifiers"] = sorted(
        "bind" if word == "let" else word for word in grammar["reserved_identifiers"]
    )
    _reidentify_language_bundle(kernel, modified)

    originals = _definition(baseline)
    assert "$defs" not in originals["schema"]
    assert "version" not in originals["formula_grammar"]
    assert _definition(modified)["schema"] == originals["schema"]
    assert wire_schema_identity_for_kind(
        baseline, originals["artifact_kind"]
    ) == wire_schema_identity_for_kind(modified, originals["artifact_kind"])
    assert baseline.root["content_identity"] != modified.root["content_identity"]
    packages = [
        next(row for row in language.package_releases if row["id"] == "standard.schema")
        for language in (baseline, modified)
    ]
    assert packages[0]["content_identity"] != packages[1]["content_identity"]
    built = []
    for language, keyword in ((baseline, "let"), (modified, "bind")):
        context = admit_authority_context(kernel, language)
        assert isinstance(context, AdmittedAuthorityContext), context
        assert _consumer_b(kernel, language)["admitted"]
        source = _rpg_model_source()
        for module in source["modules"]:
            for formula in module.get("formulas", []):
                formula["expression"] = re.sub(
                    r"^let ", keyword + " ", formula["expression"], flags=re.MULTILINE
                )
        module = source["modules"][0]
        formula = deepcopy(module["formulas"][0])
        request = {
            "schema_version": source["schema_version"],
            "package_requirements": source["package_requirements"],
            "module": {
                key: value for key, value in module.items() if key != "formulas"
            },
            "formula": formula,
        }
        expected = formula["expression"]
        assert expected.startswith(keyword + " ")
        admit_formula_pair(request, context)
        assert independently_admit_pair(request, language, kernel=kernel)
        candidate = _PublicCandidate(tmp_path / keyword, authorities=(kernel, language))
        render_request = deepcopy(request)
        render_request["formula"].pop("expression")
        request_path = candidate.directory / "formula.json"
        request_path.write_text(json.dumps(render_request))
        rendered = candidate.cli("formula", "render", str(request_path))
        assert rendered["body"] == formula["body"]
        assert rendered["expression"] == expected
        parse_request = deepcopy(request)
        parse_request["formula"].pop("body")
        request_path.write_text(json.dumps(parse_request))
        parsed = candidate.cli("formula", "parse", str(request_path))
        assert parsed["body"] == formula["body"]
        assert parsed["expression"] == expected
        candidate.write_source(source)
        assert candidate.cli("model", "check", str(candidate.source))["checked"]
        built.append(
            _members(
                candidate.cli(
                    "model",
                    "build",
                    str(candidate.source),
                    "--out",
                    str(candidate.directory / "build"),
                    "--invocation-key",
                    "85" * 32,
                )
            )
        )
    assert built[0]["package-lock"] == built[1]["package-lock"]
    old_rir, new_rir = (members["rir-semantic-payload"] for members in built)
    assert old_rir["semantic_identity"] == new_rir["semantic_identity"]
    assert old_rir["content_identity"] != new_rir["content_identity"]


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-grammar",
        "missing-notation-schema",
        "version-label",
        "old-placement",
        "duplicate-old-placement",
        "malformed-grammar",
        "reference-schema",
        "empty-token",
        "invalid-pattern",
        "wrong-group-arity",
        "wrong-keyword-arity",
        "wrong-schema-role",
    ),
)
def test_authority_refuses_unclosed_formula_wire_fields(mutation):
    kernel, language = mutable_authorities()
    definition = _definition(language)
    grammar = definition["formula_grammar"]
    if mutation == "missing-grammar":
        definition.pop("formula_grammar")
    elif mutation == "missing-notation-schema":
        definition.pop("operation_notation_schema")
    elif mutation == "version-label":
        grammar["version"] = "1.1.0"
    elif mutation in {"old-placement", "duplicate-old-placement"}:
        definition["schema"]["$defs"] = {
            "formulaNotationGrammar": {"const": deepcopy(grammar)},
            "formulaOperationNotation": deepcopy(
                definition["operation_notation_schema"]
            ),
        }
        if mutation == "old-placement":
            definition.pop("formula_grammar")
            definition.pop("operation_notation_schema")
    elif mutation == "malformed-grammar":
        definition["formula_grammar"] = []
    elif mutation == "reference-schema":
        definition["operation_notation_schema"]["$ref"] = "#/$defs/missing"
    elif mutation == "empty-token":
        grammar["identifier_token_pattern"] = "a*"
        grammar["bare_identifier_pattern"] = "^a*$"
    elif mutation == "invalid-pattern":
        grammar["integer_literal_pattern"] = "["
    elif mutation == "wrong-group-arity":
        grammar["group_delimiters"] = ["("]
    elif mutation == "wrong-keyword-arity":
        grammar["conditional_keywords"] = ["if", "then"]
    else:
        extra = deepcopy(definition)
        extra["artifact_kind"] = "probe.non-source"
        extra.pop("protocol_role")
        language["language"]["wire_schemas"].append(extra)
        owner = next(
            row
            for row in language["language"]["packages"]
            if row["id"] == "standard.schema"
        )
        owner["exports"]["wire_schemas"].append(extra["artifact_kind"])
    _reidentify_language_bundle(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        outcome = consumer(kernel, language)
        assert not outcome["admitted"], (mutation, outcome)
        assert any(
            row[1] == "kernel.vector_mismatch" and row[2] == "language.definitions"
            for row in outcome["diagnostics"]
        ), outcome


@pytest.mark.parametrize("mutation", ("missing", "unknown-role", "partial-members"))
def test_authority_refuses_an_unsupported_kernel_source_notation_contract(
    mutation, monkeypatch
):
    kernel, language = mutable_authorities()
    protocols = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]
    if mutation == "missing":
        protocols.pop("source_notation")
    elif mutation == "unknown-role":
        protocols["source_notation"]["role"] = "unknown-source"
    else:
        protocols["source_notation"]["required_members"] = ["formula_grammar"]
    _reidentify(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        outcome = consumer(kernel, language)
        assert not outcome["admitted"], outcome
        assert ("ingress", "kernel.identity_mismatch", "kernel") in outcome[
            "diagnostics"
        ]
    # Isolate the structural interpreter after separately proving the public
    # unsupported-Kernel gate. No candidate gains production admission.
    for implementation in (production_admission, independent_admission):
        monkeypatch.setattr(
            implementation, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
        )
    for consumer in (_consumer_a, _consumer_b):
        outcome = consumer(kernel, language)
        assert not outcome["admitted"], outcome
        assert (
            "static",
            "kernel.vector_mismatch",
            "kernel.meta-format.source-notation",
        ) in outcome["diagnostics"]
