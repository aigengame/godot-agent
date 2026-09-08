"""The compiler's Formula resolution meaning is a closed Kernel field."""

from copy import deepcopy
import json

import pytest

import gda_balancing.domain.authority.admission as production_admission
import schema2_bootstrap_conformance_support as independent_admission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.formula.notation import admit_formula_pair
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _reidentify
from schema2_bootstrap_production_support import _consumer_a
from schema2_formula_conformance_support import admit_pair as independent_pair
from test_current_namespace_public import _PublicCandidate
from test_schema2_formula_cli import _quantity_contract, _quantity_module
from test_schema2_template_cli import _reidentify_language_bundle


_DELETED = (
    "dynamic_lookup",
    "first_class_values",
    "binding_cardinality",
    "argument_cardinality",
    "argument_order",
    "same_name_capture",
    "declaration_scope",
    "allowed_operand_kinds",
    "allowed_binding_sites",
)


def _profile(language):
    return next(
        row for row in language["language"]["resolution_profiles"] if row["default"]
    )


def test_public_formula_consumes_compiler_generated_local_names(tmp_path):
    kernel, baseline = mutable_authorities()
    modified = deepcopy(baseline)
    _profile(modified)["formula_resolution"]["notation_conversion"]["infix_parser"][
        "generated_local_separator"
    ] = "__compiler_"
    _reidentify_language_bundle(kernel, modified)
    contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    contract["domain"] = {"minimum": -2000, "maximum": 1000}
    request = {
        "schema_version": "2.0.0",
        "package_requirements": ["core.quantity"],
        "module": _quantity_module("main"),
        "formula": {
            "id": "subtraction",
            "parameters": [_quantity_contract(name) for name in "abc"],
            "result": contract,
            "expression": "let result = a - b - c; result",
        },
    }
    for language, separator in ((baseline, "__notation_"), (modified, "__compiler_")):
        profile = _profile(language)
        assert "standard.formula" not in profile["extensions"]
        assert not set(_DELETED) & profile["formula_resolution"].keys()
        assert "allowed_body_nodes" not in profile["formula_resolution"]
        context = admit_authority_context(kernel, language)
        assert isinstance(context, AdmittedAuthorityContext), context
        assert _consumer_b(kernel, language)["admitted"]
        candidate = _PublicCandidate(
            tmp_path / separator, authorities=(kernel, language)
        )
        path = candidate.directory / "formula.json"
        path.write_text(json.dumps(request))
        result = candidate.cli("formula", "parse", str(path))
        # The two subtraction calls are independently specified; generated names
        # follow the selected compiler separator, never a resolver-built oracle.
        assert [node["id"] for node in result["body"]["nodes"]] == [
            f"result{separator}1",
            "result",
        ]
        assert [node["operation"]["id"] for node in result["body"]["nodes"]] == [
            "quantity.subtract",
            "quantity.subtract",
        ]
        pair = deepcopy(request)
        pair["formula"].update(body=result["body"], expression=result["expression"])
        admit_formula_pair(pair, context)
        assert independent_pair(pair, language, kernel=kernel)
        render = deepcopy(pair)
        render["formula"].pop("expression")
        path.write_text(json.dumps(render))
        assert candidate.cli("formula", "render", str(path))["body"] == result["body"]


@pytest.mark.parametrize("field", _DELETED)
def test_authority_refuses_deleted_formula_pseudo_configuration(field):
    kernel, language = mutable_authorities()
    _profile(language)["formula_resolution"][field] = {
        "allowed_operand_kinds": ["literal"],
        "allowed_binding_sites": ["operation-slot"],
    }.get(field, False if field in _DELETED[:2] else "unused")
    _reidentify_language_bundle(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"]
        assert ("static", "kernel.vector_mismatch", "language.definitions") in result[
            "diagnostics"
        ]


@pytest.mark.parametrize(
    "mutation",
    (
        "old-placement",
        "missing",
        "malformed",
        "source-selector",
        "static-callee",
        "dynamic-operand",
        "dynamic-binding-site",
        "unknown-inference",
        "wrong-node",
        "reversed-operands",
        "unknown-alias-contract",
        "duplicate-alias",
        "unknown-law",
        "zero-budget",
    ),
)
def test_authority_refuses_incoherent_formula_resolution(mutation):
    kernel, language = mutable_authorities()
    profile = _profile(language)
    formula = profile["formula_resolution"]
    if mutation == "old-placement":
        profile["extensions"]["standard.formula"] = profile.pop("formula_resolution")
    elif mutation == "missing":
        profile.pop("formula_resolution")
    elif mutation == "malformed":
        profile["formula_resolution"] = []
    elif mutation == "source-selector":
        formula["module_formulas_member"] = "imports"
    elif mutation == "static-callee":
        schema = next(
            row
            for row in language["language"]["wire_schemas"]
            if row.get("protocol_role") == "model-source-package"
        )["schema"]
        body = schema["properties"]["modules"]["items"]["properties"]["formulas"][
            "items"
        ]["properties"]["body"]["oneOf"][1]
        call = next(
            row
            for row in body["properties"]["nodes"]["items"]["oneOf"]
            if row["properties"]["node"]["const"] == "formula-call"
        )
        call["properties"]["formula"] = {"type": "string"}
    elif mutation in {"dynamic-operand", "dynamic-binding-site"}:
        schema = next(
            row["schema"]
            for row in language["language"]["wire_schemas"]
            if row.get("protocol_role") == "model-source-package"
        )
        if mutation == "dynamic-operand":
            bodies = schema["properties"]["modules"]["items"]["properties"]["formulas"][
                "items"
            ]["properties"]["body"]["oneOf"]
            union = next(row for row in bodies if row.get("type") == "object")[
                "properties"
            ]["result"]["oneOf"]
        else:
            union = schema["properties"]["formula_bindings"]["items"]["properties"][
                "site"
            ]["oneOf"]
        union.append(
            {
                "type": "object",
                "properties": {"kind": {"const": "dynamic-callee"}},
                "required": ["kind"],
                "unevaluatedProperties": False,
            }
        )
    elif mutation == "unknown-alias-contract":
        formula["fixed_value_type_aliases"][0]["contract"] = "unknown-contract"
    elif mutation == "duplicate-alias":
        formula["fixed_value_type_aliases"].append(
            deepcopy(formula["fixed_value_type_aliases"][0])
        )
    elif mutation == "unknown-law":
        formula["notation_conversion"]["symbol_resolution"] = "dynamic-member"
    elif mutation == "zero-budget":
        formula["max_nodes_per_formula"] = 0
    else:
        row = formula["notation_conversion"]["local_result_inference"][0]
        if mutation == "unknown-inference":
            row["rule"] = "trust-result-annotation"
        elif mutation == "wrong-node":
            row["node"] = "subtract"
        else:
            row["operand_members"].reverse()
    _reidentify_language_bundle(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"], (mutation, result)
        assert ("static", "kernel.vector_mismatch", "language.definitions") in result[
            "diagnostics"
        ]


@pytest.mark.parametrize(
    "mutation", ("missing", "unknown-role", "dynamic-callee", "wrong-operator")
)
def test_authority_refuses_unsupported_kernel_formula_resolution(mutation, monkeypatch):
    kernel, language = mutable_authorities()
    contract = kernel["meta_format"]["formula_resolution"]
    if mutation == "missing":
        kernel["meta_format"].pop("formula_resolution")
    elif mutation == "unknown-role":
        contract["source_protocol_role"] = "unknown-source"
    elif mutation == "dynamic-callee":
        contract["static_callees"][0]["coordinate_members"] = ["runtime-expression"]
    else:
        contract["inference_operators"]["closed-interval-add"] = "integer-subtract"
    _reidentify(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"]
        assert ("ingress", "kernel.identity_mismatch", "kernel") in result[
            "diagnostics"
        ]
    for implementation in (production_admission, independent_admission):
        monkeypatch.setattr(
            implementation, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
        )
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"]
        assert (
            "static",
            "kernel.vector_mismatch",
            "kernel.meta-format.formula-resolution",
        ) in result["diagnostics"]


def test_public_model_consumes_formula_source_member_selector(tmp_path):
    from test_current_namespace_public import _members
    from test_schema2_experiment_cli import _rpg_model_source

    kernel, language = mutable_authorities()
    source = _rpg_model_source()
    profile = _profile(language)
    profile["formula_resolution"]["module_formulas_member"] = "calculations"
    source_schema = next(
        row["schema"]
        for row in language["language"]["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )
    module_schema = source_schema["properties"]["modules"]["items"]
    module_schema["properties"]["calculations"] = module_schema["properties"].pop(
        "formulas"
    )
    # JSON Schema union order does not select a compiler branch.
    module_schema["properties"]["calculations"]["items"]["properties"]["body"][
        "oneOf"
    ].reverse()
    for module in source["modules"]:
        if "formulas" in module:
            module["calculations"] = module.pop("formulas")
    _reidentify_language_bundle(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert result["admitted"], result
    candidate = _PublicCandidate(tmp_path / "selectors", authorities=(kernel, language))
    candidate.write_source(source)
    assert candidate.cli("model", "check", str(candidate.source))["checked"]
    artifacts = _members(
        candidate.cli(
            "model",
            "build",
            str(candidate.source),
            "--out",
            str(candidate.directory / "build"),
            "--invocation-key",
            "38" * 32,
        )
    )
    assert (
        artifacts["package-lock"]["resolution_profile"]["formula_resolution"][
            "module_formulas_member"
        ]
        == "calculations"
    )
    assert {row["id"] for row in artifacts["rir-semantic-payload"]["formulas"]} == {
        row["id"]
        for module in source["modules"]
        for row in module.get("calculations", [])
    }


def test_authority_refuses_removed_formula_syntax_subset():
    kernel, language = mutable_authorities()
    _profile(language)["formula_resolution"]["allowed_body_nodes"] = [
        "conditional",
        "operation-call",
    ]
    _reidentify_language_bundle(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"], result
        assert ("static", "kernel.vector_mismatch", "language.definitions") in result[
            "diagnostics"
        ]
