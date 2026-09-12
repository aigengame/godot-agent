"""Selected Source roles reach the actual compiler and public consumers."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.model import CheckedModel, check_model_source_value
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_production_support import _consumer_a
from test_source_wire_owners import _source_schema
from test_trace_protocol_structure import _authored, _graph, _index


def _rename_role_field(schema, roles, old, new, inherited=None):
    role = schema.get("semantic_role", inherited)
    if role in roles:
        if old in schema.get("properties", {}):
            schema["properties"][new] = schema["properties"].pop(old)
        if "required" in schema:
            schema["required"] = [
                new if name == old else name for name in schema["required"]
            ]
    for child in schema.get("properties", {}).values():
        _rename_role_field(child, roles, old, new)
    if "items" in schema:
        _rename_role_field(schema["items"], roles, old, new)
    for child in schema.get("oneOf", []):
        _rename_role_field(child, roles, old, new, role)


def _candidate(case):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    original = deepcopy(source)
    if case == "ports":
        selected = "wire/port~"
        _rename_role_field(
            schema, {"entrypoint-argument", "operation-argument"}, "port", selected
        )
        entrypoint_ports = formula_ports = 0
        for entrypoint in source["entrypoints"]:
            for argument in entrypoint["arguments"]:
                argument[selected] = argument.pop("port")
                entrypoint_ports += 1
        for module in source["modules"]:
            for formula in module.get("formulas", []):
                for node in formula["body"].get("nodes", []):
                    if node["node"] == "operation-call":
                        for argument in node["arguments"]:
                            argument[selected] = argument.pop("port")
                            formula_ports += 1
        assert entrypoint_ports == 53 and formula_ports == 5
    elif case == "expression":
        selected = "wire/expression~"
        _rename_role_field(schema, {"formula"}, "expression", selected)
        formulas = [
            formula
            for module in source["modules"]
            for formula in module.get("formulas", [])
        ]
        assert len(formulas) == 2
        for formula in formulas:
            formula[selected] = formula.pop("expression")
    elif case == "value-policy":
        for member in ("mode", "value"):
            selected = "wire/" + member + "~"
            _rename_role_field(schema, {"value-policy"}, member, selected)
            for module in source["modules"]:
                for symbol in module["symbols"]:
                    policy = symbol["value_policy"]
                    if member in policy:
                        policy[selected] = policy.pop(member)
    elif case == "requirements":
        _rename_role_field(
            schema, {"source"}, "package_requirements", "wire/requirements~"
        )
        source["wire/requirements~"] = source.pop("package_requirements")
        from test_resolution_parse_reason import _profile

        for recipe in _profile(authored)["relation_recipes"]:
            for binding in recipe["bindings"]:
                term = binding["source"]
                if term["root"] == "source" and term["path"] == [
                    "package_requirements"
                ]:
                    term["path"] = ["wire/requirements~"]
    elif case == "entrypoint-id":
        _rename_role_field(schema, {"entrypoint"}, "id", "wire/id~")
        for entrypoint in source["entrypoints"]:
            entrypoint["wire/id~"] = entrypoint.pop("id")
    elif case == "operation-arguments":
        _rename_role_field(schema, {"operation-call"}, "arguments", "wire/arguments~")
        for module in source["modules"]:
            for formula in module.get("formulas", []):
                for node in formula["body"].get("nodes", []):
                    if node["node"] == "operation-call":
                        node["wire/arguments~"] = node.pop("arguments")
    else:
        raise AssertionError(case)
    graph = _graph(kernel, authored)
    assert _consumer_a(kernel, graph)["admitted"]
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext), context
    return kernel, graph, context, source, original


@pytest.mark.parametrize(
    "case",
    [
        "ports",
        "expression",
        "value-policy",
        "entrypoint-id",
        "operation-arguments",
        "requirements",
    ],
)
def test_source_roles_preserve_all_prepared_values(case):
    _kernel, _graph, context, source, original = _candidate(case)
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    assert checked.source == source
    assert checked.source_projection.value == original
    assert checked.hir.entrypoints
    assert checked.hir.formulas


@pytest.mark.parametrize(
    "case",
    [
        "ports",
        "expression",
        "value-policy",
        "entrypoint-id",
        "operation-arguments",
        "requirements",
    ],
)
def test_source_roles_reach_public_build_and_run(tmp_path, case):
    from gda_balancing.domain.artifacts import artifacts_by_protocol_role
    from test_bounded_fold_public import _check, _run
    from test_current_namespace_public import _PublicCandidate, _members

    kernel, graph, context, source, _original = _candidate(case)
    public = _PublicCandidate(tmp_path / case, authorities=(kernel, graph))
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    receipt = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "35" * 32,
    )
    built = artifacts_by_protocol_role(context.language_bundle, _members(receipt))
    assert len(built) == 8
    rir = built["rir-semantic-payload"]
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/experiment.json"
        ).read_text()
    )
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    path, _ = _check(public, rir_path, specification)
    artifacts = _members(_run(public, rir_path, path))
    assert artifacts


def test_source_template_provenance_roles_reach_the_real_public_writer(tmp_path):
    from test_current_namespace_public import _PublicCandidate, _members

    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    _rename_role_field(schema, {"manifest"}, "template_provenance", "wire/provenance~")
    for member in ("template_id", "template_identity", "starter_identity"):
        _rename_role_field(
            schema, {"template-provenance"}, member, "wire/" + member + "~"
        )
    graph = _graph(kernel, authored)
    assert _consumer_a(kernel, graph)["admitted"]
    public = _PublicCandidate(tmp_path / "template", authorities=(kernel, graph))
    output = public.directory / "instance.json"
    receipt = public.cli(
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--package-id",
        "example.selected-provenance",
        "--out",
        str(output),
        "--invocation-key",
        "36" * 32,
    )
    members = _members(receipt)
    source = members["model-source-package"]
    assert "template_provenance" not in source["manifest"]
    provenance = source["manifest"]["wire/provenance~"]
    assert set(provenance) == {
        "wire/template_id~",
        "wire/template_identity~",
        "wire/starter_identity~",
    }
    assert provenance["wire/template_id~"] == "standard.quantity-minimal"
    assert all(isinstance(value, str) and value for value in provenance.values())
    public.cli("model", "check", str(output))
    built = public.cli(
        "model",
        "build",
        str(output),
        "--out",
        str(public.directory / "compiled"),
        "--invocation-key",
        "37" * 32,
    )
    assert len(_members(built)) == 8


@pytest.mark.parametrize(
    "defect",
    [
        "missing-role",
        "wrong-role",
        "duplicate-role",
        "missing-field",
        "extra-field",
        "argument-role",
        "array-shape",
        "missing-member-role",
        "duplicate-member-role",
        "unsynced-recipe",
        "dangling-member-role",
    ],
)
def test_source_semantic_role_contract_refuses_incomplete_or_misowned_schema(defect):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    entrypoint = schema["properties"]["entrypoints"]["items"]
    if defect == "missing-role":
        del entrypoint["semantic_role"]
    elif defect == "wrong-role":
        operation = entrypoint["properties"]["operation"]
        operation["semantic_role"] = "formula-coordinate"
        operation["properties"]["module"] = operation["properties"].pop("package")
        operation["required"] = ["module", "id"]
        operation["properties"]["module"]["semantic_member"] = "module"
    elif defect == "duplicate-role":
        symbols = schema["properties"]["modules"]["items"]["properties"]["symbols"][
            "items"
        ]
        symbols["oneOf"][0]["semantic_role"] = symbols["semantic_role"]
    elif defect == "missing-field":
        del entrypoint["properties"]["result"]
        entrypoint["required"].remove("result")
    elif defect == "argument-role":
        entrypoint["properties"]["arguments"]["items"]["semantic_role"] = (
            "operation-argument"
        )
    elif defect == "array-shape":
        args = entrypoint["properties"]["arguments"]
        member = args["semantic_member"]
        args.update(args.pop("items"))
        args["type"] = "object"
        args["semantic_member"] = member
    elif defect == "missing-member-role":
        del entrypoint["properties"]["operation"]["semantic_member"]
    elif defect == "duplicate-member-role":
        entrypoint["properties"]["id"]["semantic_member"] = "operation"
    elif defect == "dangling-member-role":
        schema["semantic_member"] = "source"
    elif defect == "unsynced-recipe":
        _rename_role_field(
            schema, {"source"}, "package_requirements", "wire/requirements~"
        )
    else:
        entrypoint["properties"]["ignored"] = {"type": "string"}
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert not result["admitted"], result


@pytest.mark.parametrize(
    "case",
    [
        "ports",
        "expression",
        "value-policy",
        "entrypoint-id",
        "operation-arguments",
        "requirements",
    ],
)
def test_source_roles_reach_public_formula_parse_and_render(tmp_path, case):
    from test_current_namespace_public import _PublicCandidate

    kernel, graph, _context, source, _original = _candidate(case)
    module = source["modules"][0]
    formula = module["formulas"][0]
    expression_member = "wire/expression~" if case == "expression" else "expression"
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source[
            "wire/requirements~" if case == "requirements" else "package_requirements"
        ],
        "module": {name: value for name, value in module.items() if name != "formulas"},
        "formula": deepcopy(formula),
    }
    public = _PublicCandidate(tmp_path / case, authorities=(kernel, graph))
    path = public.directory / "formula.json"
    render_request = deepcopy(request)
    del render_request["formula"][expression_member]
    path.write_text(json.dumps(render_request))
    rendered = public.cli("formula", "render", str(path))
    assert rendered["body"] == formula["body"]
    assert rendered["expression"] == formula[expression_member]
    parse_request = deepcopy(request)
    del parse_request["formula"]["body"]
    path.write_text(json.dumps(parse_request))
    parsed = public.cli("formula", "parse", str(path))
    assert parsed == rendered


_RETIRED_SOURCE_SELECTORS = [
    (False, "entrypoints_member", "entrypoints"),
    (False, "import_alias_member", "alias"),
    (False, "import_package_member", "package"),
    (False, "import_symbol_member", "symbol"),
    (False, "imports_member", "imports"),
    (False, "manifest_entry_module_path", "manifest.entry_module"),
    (False, "manifest_id_path", "manifest.id"),
    (False, "module_id_member", "id"),
    (False, "modules_member", "modules"),
    (False, "requirements_member", "package_requirements"),
    (False, "schema_version_member", "schema_version"),
    (False, "symbol_name_member", "symbol"),
    (False, "symbol_type_member", "type"),
    (False, "symbols_member", "symbols"),
    (True, "binding_arguments_member", "arguments"),
    (True, "binding_formula_member", "formula"),
    (True, "binding_operand_member", "operand"),
    (True, "binding_parameter_member", "parameter"),
    (True, "binding_site_member", "site"),
    (True, "bindings_member", "formula_bindings"),
    (True, "body_nodes_member", "nodes"),
    (True, "body_result_member", "result"),
    (True, "formula_body_member", "body"),
    (True, "formula_id_member", "id"),
    (True, "formula_parameters_member", "parameters"),
    (True, "formula_result_member", "result"),
    (True, "inline_body_normalizations", [{"parameter_member": "parameter"}]),
    (True, "module_formulas_member", "formulas"),
    (True, "node_id_member", "id"),
    (True, "parameter_id_member", "id"),
]


@pytest.mark.parametrize(
    "nested,member,old_value",
    _RETIRED_SOURCE_SELECTORS,
    ids=[row[1] for row in _RETIRED_SOURCE_SELECTORS],
)
def test_retired_source_selector_cannot_reintroduce_a_second_address_owner(
    nested, member, old_value
):
    from test_resolution_parse_reason import _profile

    kernel, language = mutable_authorities()
    authored = _authored(language)
    profile = _profile(authored)
    owner = profile["formula_resolution"] if nested else profile
    assert member not in owner
    owner[member] = deepcopy(old_value)
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert not result["admitted"], result
