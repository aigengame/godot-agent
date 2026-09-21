"""Independent Formula return-source judgments over the original authored Source."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.model import (
    CheckedModel,
    admit_resolved_model,
    check_model_source_value,
)
from gda_balancing.domain.model._compilation import lower_checked_model
from gda_balancing.domain.model._resolution import ModelSourceContext
from gda_balancing.domain.formula.notation import admit_formula_pair
from schema2_formula_conformance_support import parse_canonical
from test_formula_operation_returns import (
    _renamed_return_case,
    _return_case,
    _runtime_case,
    _two_formal_return_case,
)
from test_schema2_model_lowerer_conformance import (
    _reference_admits_semantic_artifacts,
    _reference_check_source,
    _reference_semantic_artifacts,
)
from test_trace_protocol_structure import _graph, _index

_SEMANTIC_ROLES = (
    "package-lock",
    "rir-semantic-payload",
    "resolved-model",
    "debug-map",
)


def _independent_case(kind):
    kernel, authored, source, request = _return_case(kind)
    language = _index(kernel, _graph(kernel, authored))
    return kernel, language, source, request


def _operation(authored, identity, *, package="core.quantity"):
    return next(
        row
        for owner in authored["packages"]
        if owner["id"] == package
        for closure in owner["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == identity
    )


@pytest.mark.parametrize("literal", [1, 17])
def test_effective_accuracy_actual_literal_keeps_its_contextual_anchor(literal):
    context = packaged_authority_context()
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    module = source["modules"][0]
    formula = next(
        row for row in module["formulas"] if row["id"] == "effective-accuracy"
    )
    formula["body"]["nodes"][0]["arguments"][1]["operand"]["value"] = literal
    formula["expression"] = (
        f"let `minimum-accuracy` = max(base, {literal});\n`minimum-accuracy`"
    )
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source["package_requirements"],
        "modules": source["modules"],
        "module": module,
        "formula": formula,
    }
    admit_formula_pair(request, context)
    parsed = parse_canonical(
        formula["expression"], request, context.language_bundle, kernel=context.kernel
    )
    assert parsed == formula["body"]
    assert parsed["nodes"][0]["result"]["domain"] == {
        "minimum": 0,
        "maximum": 1000,
    }


def test_independent_formula_consumes_a_port_operation_result_from_source():
    kernel, language, _source, request = _independent_case("port")

    parsed = parse_canonical(
        request["formula"]["expression"],
        request,
        language,
        kernel=kernel,
    )

    assert parsed == request["formula"]["body"]


def test_independent_formula_consumes_a_nested_local_operation_result_from_source():
    kernel, language, _source, request = _independent_case("nested-local")

    parsed = parse_canonical(
        request["formula"]["expression"],
        request,
        language,
        kernel=kernel,
    )

    assert parsed == request["formula"]["body"]


def test_independent_formula_consumes_a_nested_direct_operation_result_from_source():
    kernel, language, _source, request = _independent_case("nested-operation-result")

    parsed = parse_canonical(
        request["formula"]["expression"],
        request,
        language,
        kernel=kernel,
    )

    assert parsed == request["formula"]["body"]


def test_independent_formula_refuses_a_unit_operation_result_from_source():
    kernel, language, _source, request = _independent_case("unit-discard")

    with pytest.raises(ValueError, match="Operation result is not scalar"):
        parse_canonical(
            request["formula"]["expression"],
            request,
            language,
            kernel=kernel,
        )


def test_independent_model_and_production_type_refuse_unit_invocation_from_source():
    kernel, language, source, _request = _independent_case("unit-discard")

    production = check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language,
    )
    reference = _reference_check_source(source, kernel, language)

    assert isinstance(production, Schema2RefusalReport), production
    assert len(production.diagnostics) == 1
    diagnostic = production.diagnostics[0]
    assert isinstance(diagnostic.primary, ArtifactLocation)
    assert (diagnostic.code, diagnostic.primary.pointer) == (
        "language.formula_type_mismatch",
        "/modules/0/formulas/0/expression",
    )
    assert reference == (
        ("language.formula_type_mismatch", "/modules/0/formulas/0/expression"),
    )


@pytest.mark.parametrize(
    "kind",
    [
        "local",
        "port",
        "empty-port",
        "nested-local",
        "nested-operation-result",
    ],
)
def test_independent_lowerer_mutually_consumes_scalar_operation_return_artifacts(kind):
    kernel, language, source, _request = _independent_case(kind)
    production_checked = check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language,
    )
    reference_checked = _reference_check_source(source, kernel, language)
    assert isinstance(production_checked, CheckedModel), production_checked
    assert isinstance(reference_checked, ModelSourceContext), reference_checked

    production = lower_checked_model(production_checked)
    reference = _reference_semantic_artifacts(reference_checked)
    assert all(production[role] == reference[role] for role in _SEMANTIC_ROLES)
    assert _reference_admits_semantic_artifacts(production, reference_checked)

    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    admitted = admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    )
    assert admitted.admitted


@pytest.mark.parametrize(
    ("name", "case"),
    [
        ("original", lambda: _return_case("nested-operation-result")),
        ("renamed", _renamed_return_case),
    ],
)
def test_independent_consumers_keep_exact_operation_owner_formal_and_site(name, case):
    kernel, authored, source, request = case()
    language = _index(kernel, _graph(kernel, authored))

    parsed = parse_canonical(
        request["formula"]["expression"],
        request,
        language,
        kernel=kernel,
    )
    assert parsed == request["formula"]["body"]
    expected_owner = "core.quantity" if name == "original" else "example.returnowner"
    expected_port = "value" if name == "original" else "source_value"
    parsed_call = parsed["nodes"][0]
    assert parsed_call["operation"] == {
        "package": expected_owner,
        "id": "quantity.identity",
    }
    assert [row["port"] for row in parsed_call["arguments"]] == [expected_port]

    production_checked = check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language,
    )
    reference_checked = _reference_check_source(source, kernel, language)
    assert isinstance(production_checked, CheckedModel), production_checked
    assert isinstance(reference_checked, ModelSourceContext), reference_checked
    production = lower_checked_model(production_checked)
    reference = _reference_semantic_artifacts(reference_checked)
    assert all(production[role] == reference[role] for role in _SEMANTIC_ROLES)
    assert _reference_admits_semantic_artifacts(production, reference_checked)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted

    formula = reference["rir-semantic-payload"]["formulas"][0]
    assert formula["body"]["nodes"][0]["operation"]["package"] == expected_owner
    selected = {
        (row["package"], row["definition"]["id"])
        for row in reference["rir-semantic-payload"]["selected_semantics"]["operations"]
    }
    assert (expected_owner, "quantity.identity") in selected


@pytest.mark.parametrize(
    ("return_port", "expected_domain"),
    [
        ("first", {"minimum": 1, "maximum": 100}),
        ("second", {"minimum": 7, "maximum": 7}),
    ],
)
def test_independent_consumers_bind_formal_order_and_literal_return_contract(
    return_port, expected_domain
):
    kernel, authored, source, request = _two_formal_return_case(return_port)
    language = _index(kernel, _graph(kernel, authored))

    parsed = parse_canonical(
        request["formula"]["expression"],
        request,
        language,
        kernel=kernel,
    )
    assert parsed == request["formula"]["body"]
    node = parsed["nodes"][0]
    assert [argument["port"] for argument in node["arguments"]] == [
        "first",
        "second",
    ]
    assert node["result"]["domain"] == expected_domain

    production_checked = check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language,
    )
    reference_checked = _reference_check_source(source, kernel, language)
    assert isinstance(production_checked, CheckedModel), production_checked
    assert isinstance(reference_checked, ModelSourceContext), reference_checked
    production = lower_checked_model(production_checked)
    reference = _reference_semantic_artifacts(reference_checked)
    assert all(production[role] == reference[role] for role in _SEMANTIC_ROLES)
    assert _reference_admits_semantic_artifacts(production, reference_checked)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("missing-local", "local result producer is unresolved"),
        ("wrong-local-producer", "local result producer is unresolved"),
        ("missing-site", "Operation result producer is unresolved"),
        ("wrong-site", "Operation result producer is unresolved"),
        ("duplicate-site", "Operation site is unresolved"),
        ("wrong-namespace", "nested Operation is unresolved"),
        ("wrong-formal", "arguments are unresolved"),
    ],
)
def test_independent_formula_refuses_unresolved_result_owners(fault, message):
    kernel, authored, _source, request = _return_case("nested-operation-result")
    operation = _operation(authored, "quantity.identity")
    invocation = operation["body"][0]
    if fault == "missing-local":
        operation["result"]["source"] = {"kind": "local", "name": "absent"}
    elif fault == "wrong-local-producer":
        operation["result"]["source"] = {"kind": "local", "name": "value"}
    elif fault == "missing-site":
        operation["result"]["source"]["site"] = "absent"
    elif fault == "wrong-site":
        invocation["site"] = "other"
    elif fault == "duplicate-site":
        operation["body"].append(deepcopy(invocation))
    elif fault == "wrong-namespace":
        invocation["operation"]["package"] = "game.combat"
    else:
        invocation["arguments"][0]["port"] = "other"
    language = _index(kernel, _graph(kernel, authored))

    with pytest.raises(ValueError, match=message):
        parse_canonical(
            request["formula"]["expression"],
            request,
            language,
            kernel=kernel,
        )


@pytest.mark.parametrize("node", ["fold", "lookup"])
def test_independent_formula_refuses_unsupported_operation_body_shapes(node):
    kernel, authored, _source, request = _return_case("port")
    operation = _operation(authored, "quantity.identity")
    operation["body"] = [{"node": node, "target": "ignored"}]
    language = _index(kernel, _graph(kernel, authored))

    with pytest.raises(ValueError, match="inference instruction is unresolved"):
        parse_canonical(
            request["formula"]["expression"],
            request,
            language,
            kernel=kernel,
        )


def test_independent_port_result_does_not_hide_a_later_body_fault():
    kernel, authored, _source, request = _return_case("port")
    operation = _operation(authored, "quantity.identity")
    operation["body"].append({"node": "copy", "target": "late", "value": "absent"})
    language = _index(kernel, _graph(kernel, authored))

    with pytest.raises(ValueError, match="inference operand is unresolved"):
        parse_canonical(
            request["formula"]["expression"],
            request,
            language,
            kernel=kernel,
        )


def test_independent_artifacts_preserve_transitive_resource_and_refusal_contracts():
    kernel, authored, source, _request = _return_case("nested-operation-result")
    operation = _operation(authored, "quantity.identity")
    operation["refusals"] = ["runtime.reason.numeric-overflow"]
    language = _index(kernel, _graph(kernel, authored))
    expected_steps = 1 + operation["resource_bounds"]["max_steps"]

    production_checked = check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language,
    )
    reference_checked = _reference_check_source(source, kernel, language)
    assert isinstance(production_checked, CheckedModel), production_checked
    assert isinstance(reference_checked, ModelSourceContext), reference_checked
    production = lower_checked_model(production_checked)
    reference = _reference_semantic_artifacts(reference_checked)
    assert all(production[role] == reference[role] for role in _SEMANTIC_ROLES)

    rir = reference["rir-semantic-payload"]
    assert rir["formulas"][0]["closure"]["resource_charge"] == {
        "max_steps": expected_steps
    }
    assert rir["formulas"][0]["closure"]["refusals"] == [
        "runtime.reason.numeric-overflow"
    ]
    assert all(
        program["resource_bounds"] == {"max_steps": expected_steps}
        and len(program["body"]) == expected_steps
        and program["refusals"] == ["runtime.reason.numeric-overflow"]
        for program in rir["initialization_programs"]
    )


@pytest.mark.parametrize("kind", ["port", "nested-operation-result"])
def test_independent_slot_lowerer_mutually_consumes_scalar_return_artifacts(kind):
    kernel, authored, source = _runtime_case(kind)
    language = _index(kernel, _graph(kernel, authored))
    production_checked = check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language,
    )
    reference_checked = _reference_check_source(source, kernel, language)
    assert isinstance(production_checked, CheckedModel), production_checked
    assert isinstance(reference_checked, ModelSourceContext), reference_checked

    production = lower_checked_model(production_checked)
    reference = _reference_semantic_artifacts(reference_checked)
    assert all(production[role] == reference[role] for role in _SEMANTIC_ROLES)
    assert _reference_admits_semantic_artifacts(production, reference_checked)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted

    rir = reference["rir-semantic-payload"]
    bound_formula = next(
        formula for formula in rir["formulas"] if formula["id"] == "mitigated-damage"
    )
    specialized = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["package"] == "game.combat"
        and row["definition"]["id"] == "game.combat.damage-v1"
    )
    provenance = specialized["extensions"]["standard.instruction-provenance"]
    assert (
        len(provenance["sites"])
        == bound_formula["closure"]["resource_charge"]["max_steps"]
    )
