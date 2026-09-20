"""Selected Source roles reach the actual compiler and public consumers."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.source_projection import (
    derive_source_semantic_index,
    project_source_value,
    source_schema_member,
)
from gda_balancing.domain.model import CheckedModel, check_model_source_value
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_source_roles_are_closed,
)
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
    elif case == "routing":
        members = {
            "source": {
                "manifest": "header/~",
                "package_requirements": "dependencies/~",
                "modules": "sections/~",
            },
            "manifest": {"id": "model_key/~", "entry_module": "start_module/~"},
            "module": {
                "id": "module_key/~",
                "imports": "uses/~",
                "symbols": "declarations/~",
            },
            "import": {
                "alias": "prefix/~",
                "package": "package_id/~",
                "symbol": "export_name/~",
            },
            "symbol": {"symbol": "name/~", "type": "type_ref/~"},
        }
        for role, names in members.items():
            for old, new in names.items():
                _rename_role_field(schema, {role}, old, new)
        for role, objects in (
            (
                "symbol",
                [row for module in source["modules"] for row in module["symbols"]],
            ),
            (
                "import",
                [row for module in source["modules"] for row in module["imports"]],
            ),
            ("module", source["modules"]),
            ("manifest", [source["manifest"]]),
            ("source", [source]),
        ):
            for obj in objects:
                for old, new in members[role].items():
                    obj[new] = obj.pop(old)

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
    consumer_b = _consumer_b(kernel, graph)
    assert consumer_b["admitted"], consumer_b["diagnostics"]
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
        "routing",
    ],
)
def test_source_roles_preserve_all_prepared_values(case):
    _kernel, _graph, context, source, original = _candidate(case)
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    assert checked.source == source
    assert checked.source_projection.value == original
    from gda_balancing.domain.model._compilation import lower_checked_model

    artifacts = lower_checked_model(checked)
    declarations = cast(
        list[dict[str, object]],
        artifacts["rir-semantic-payload"]["declarations"],
    )
    assert {row["symbol"] for row in declarations} == {
        row["symbol"] for module in original["modules"] for row in module["symbols"]
    }
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
        "routing",
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
        "missing-member-role",
        "duplicate-member-role",
        "branch-only-field",
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
    elif defect == "duplicate-role":
        symbols = schema["properties"]["modules"]["items"]["properties"]["symbols"][
            "items"
        ]
        symbols["oneOf"][0]["semantic_role"] = symbols["semantic_role"]
    elif defect == "missing-field":
        del entrypoint["properties"]["result"]
    elif defect == "argument-role":
        entrypoint["properties"]["arguments"]["items"]["semantic_role"] = "entrypoint"
    elif defect == "missing-member-role":
        del entrypoint["properties"]["operation"]["semantic_member"]
    elif defect == "duplicate-member-role":
        entrypoint["properties"]["id"]["semantic_member"] = "operation"
    elif defect == "branch-only-field":
        symbols = schema["properties"]["modules"]["items"]["properties"]["symbols"][
            "items"
        ]
        domain = symbols["properties"].pop("domain")
        symbols["oneOf"][0]["properties"]["domain"] = domain
    elif defect == "dangling-member-role":
        schema["semantic_member"] = "source"
    else:
        entrypoint["properties"]["ignored"] = {"type": "string"}
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result


def _source_role_nodes(schema, selected):
    result = []

    def visit(node):
        if node.get("semantic_role") == selected:
            result.append(node)
        for child in node.get("properties", {}).values():
            visit(child)
        if "items" in node:
            visit(node["items"])
        for child in node.get("oneOf", []):
            visit(child)

    visit(schema)
    return result


@pytest.mark.parametrize(
    "defect",
    [
        "missing-value-policy-mode-member",
        "native-interval-child-annotation",
        "native-boolean-child-annotation",
        "native-typed-literal-child-annotation",
        "boolean-domain",
        "typed-literal-envelope",
    ],
)
def test_source_native_and_contextual_roles_refuse_semantic_schema_drift(defect):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    if defect == "missing-value-policy-mode-member":
        policy = _source_role_nodes(schema, "value-policy")[0]
        del policy["properties"]["mode"]["semantic_member"]
    elif defect == "native-interval-child-annotation":
        symbol = _source_role_nodes(schema, "symbol")[0]
        symbol["properties"]["domain"]["properties"]["minimum"]["semantic_member"] = (
            "minimum"
        )
    elif defect == "native-boolean-child-annotation":
        contract = _source_role_nodes(schema, "boolean-value-contract")[0]
        contract["properties"]["domain"]["properties"]["kind"]["semantic_member"] = (
            "kind"
        )
    elif defect == "native-typed-literal-child-annotation":
        literal = _source_role_nodes(schema, "literal")[0]
        for branch in literal["properties"]["value"].get("oneOf", []):
            if branch.get("type") == "object":
                branch["properties"]["type"]["properties"]["id"]["semantic_member"] = (
                    "id"
                )
    elif defect == "boolean-domain":
        contract = _source_role_nodes(schema, "boolean-value-contract")[0]
        contract["properties"]["domain"]["properties"]["kind"]["const"] = "not-boolean"
    else:
        for literal in _source_role_nodes(schema, "literal"):
            value = literal["properties"]["value"]
            for alternative in value.get("oneOf", []):
                if alternative.get("type") == "object":
                    alternative["properties"]["type"]["properties"]["id"]["type"] = (
                        "integer"
                    )
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (defect, result)


@pytest.mark.parametrize(
    "change",
    [
        "array-cardinality",
        "conditional-child-role",
        "inherited-symbol-child-role",
        "conditional-operand-role",
    ],
)
def test_source_topology_changes_without_compiler_binding_are_refused(change):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    if change == "array-cardinality":
        entrypoint = schema["properties"]["entrypoints"]["items"]
        arguments = entrypoint["properties"]["arguments"]
        member = arguments["semantic_member"]
        arguments.update(arguments.pop("items"))
        arguments["type"] = "object"
        arguments["semantic_member"] = member
    elif change == "conditional-child-role":
        conditional = _source_role_nodes(schema, "conditional")[0]
        member = conditional["properties"]["condition"]
        semantic_member = member["semantic_member"]
        member.clear()
        member.update(
            {
                "semantic_member": semantic_member,
                "semantic_role": "value-policy",
                "type": "object",
                "properties": {
                    "mode": {"semantic_member": "mode", "type": "string"},
                    "value": {"semantic_member": "value", "type": "integer"},
                },
                "required": ["mode"],
                "unevaluatedProperties": False,
            }
        )
    elif change == "inherited-symbol-child-role":
        symbol = _source_role_nodes(schema, "symbol")[0]
        policy = symbol["oneOf"][0]["properties"]["value_policy"]
        semantic_member = policy["semantic_member"]
        policy.clear()
        policy.update(
            {
                "semantic_member": semantic_member,
                "semantic_role": "formula-coordinate",
                "type": "object",
                "properties": {
                    "module": {"semantic_member": "module", "type": "string"},
                    "id": {"semantic_member": "id", "type": "string"},
                },
                "required": ["module", "id"],
                "unevaluatedProperties": False,
            }
        )
    else:
        conditional = _source_role_nodes(schema, "conditional")[0]
        condition = conditional["properties"]["condition"]
        inline_parameter = _source_role_nodes(schema, "inline-parameter")[0]
        condition["oneOf"][0] = deepcopy(inline_parameter)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (change, consumer.__name__, result)


def _literal_value_union(schema):
    return _source_role_nodes(schema, "literal")[0]["properties"]["value"]


@pytest.mark.parametrize("order", ["declared", "reversed"])
def test_source_typed_literal_current_closed_union_is_admitted_after_resealing(
    order,
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    branches = _literal_value_union(_source_schema(authored))["oneOf"]
    assert [branch["type"] for branch in branches] == [
        "integer",
        "boolean",
        "object",
    ]
    if order == "reversed":
        branches.reverse()
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], (consumer.__name__, result)


@pytest.mark.parametrize(
    "defect",
    [
        "string-branch",
        "number-branch",
        "null-branch",
        "array-branch",
        "untyped-object-branch",
        "duplicate-integer-branch",
        "duplicate-envelope-branch",
        "duplicate-envelope-member",
        "open-envelope",
        "open-type-reference",
        "remove-integer",
        "remove-boolean",
        "remove-envelope",
    ],
)
def test_source_typed_literal_undeclared_capability_is_refused_after_resealing(
    defect,
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    union = _literal_value_union(_source_schema(authored))
    branches = union["oneOf"]
    envelope = branches[2]
    if defect.endswith("-branch") and defect.split("-", 1)[0] in {
        "string",
        "number",
        "null",
        "array",
    }:
        branches.append({"type": defect.split("-", 1)[0]})
    elif defect == "untyped-object-branch":
        branches.append({"type": "object", "unevaluatedProperties": False})
    elif defect == "duplicate-integer-branch":
        branches.append(deepcopy(branches[0]))
    elif defect == "duplicate-envelope-branch":
        branches.append(deepcopy(envelope))
    elif defect == "duplicate-envelope-member":
        envelope["required"].append(envelope["required"][0])
    elif defect == "open-envelope":
        del envelope["unevaluatedProperties"]
    elif defect == "open-type-reference":
        del envelope["properties"]["type"]["unevaluatedProperties"]
    elif defect.startswith("remove-"):
        kind = defect.removeprefix("remove-")
        schema_type = "object" if kind == "envelope" else kind
        branches[:] = [branch for branch in branches if branch["type"] != schema_type]
    else:
        raise AssertionError(defect)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (defect, consumer.__name__, result)


def test_source_interval_schema_can_narrow_integer_syntax_without_changing_owner():
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    symbol = _source_role_nodes(schema, "symbol")[0]
    symbol["properties"]["domain"]["properties"]["minimum"]["minimum"] = 0
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], (consumer.__name__, result)


def test_source_native_reference_path_is_authoritative():
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    symbol = _source_role_nodes(schema, "symbol")[0]
    symbol["properties"]["domain"]["semantic_native_contract"][
        "kernel_contract_paths"
    ]["value"] = (
        "kernel.meta_format.fact.field_contracts.quantity-symbol"
    )
    graph = _graph(kernel, authored)
    index = _index(kernel, graph)
    with pytest.raises(ValueError):
        derive_source_semantic_index(kernel, index)
    assert not _consumer_b_source_roles_are_closed(index, kernel["meta_format"])


@pytest.mark.parametrize(
    "defect", ["explicit-null", "malformed-location", "dangling-path", "duplicate-path"]
)
def test_source_native_reference_contract_refuses_malformed_bindings(defect):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    symbol_domain = _source_role_nodes(schema, "symbol")[0]["properties"]["domain"]
    if defect == "explicit-null":
        symbol_domain["semantic_native_contract"]["kernel_reference"] = None
    elif defect == "malformed-location":
        symbol_domain["semantic_native_contract"]["value_location"]["unknown"] = True
    elif defect == "dangling-path":
        symbol_domain["semantic_native_contract"]["language_reference"] = (
            "language.quantity.missing-domains"
        )
    else:
        literal = _source_role_nodes(schema, "literal")[0]["properties"]["value"]
        paths = literal["semantic_native_contract"]["kernel_contract_paths"]
        paths["boolean_contract"] = paths["source_kinds"]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (defect, consumer.__name__, result)


@pytest.mark.parametrize(
    "defect", ["missing-slot", "duplicate-slot", "wrong-owner", "dangling-target"]
)
def test_source_native_compiler_bindings_are_exact_and_closed(defect):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    compiler = next(
        package for package in authored["packages"] if package["id"] == "standard.compiler"
    )
    profiles = next(
        closure["definitions"]
        for closure in compiler["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
    )
    bindings = profiles[0]["source_native_bindings"]
    if defect == "missing-slot":
        bindings.pop()
    elif defect == "duplicate-slot":
        bindings.append(deepcopy(bindings[0]))
    else:
        modules = next(row for row in bindings if row["slot"] == "source.root.modules")
        if defect == "wrong-owner":
            modules["owner_slot"] = "source.module"
        else:
            modules["target_slots"] = ["source.missing"]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (defect, consumer.__name__, result)


def test_language_owned_interval_token_renames_without_kernel_reseal():
    kernel, language = mutable_authorities()
    kernel_identity = kernel["content_identity"]
    authored = _authored(language)

    def rename(value):
        if isinstance(value, dict):
            for key, child in value.items():
                value[key] = rename(child)
            return value
        if isinstance(value, list):
            return [rename(child) for child in value]
        return "bounded-range" if value == "closed-interval" else value

    rename(authored)
    graph = _graph(kernel, authored)
    assert kernel["content_identity"] == kernel_identity
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], (consumer.__name__, result["diagnostics"])


def test_language_owned_operation_call_token_renames_without_kernel_reseal(
    tmp_path: Path,
):
    from test_current_namespace_public import _PublicCandidate

    kernel, language = mutable_authorities()
    kernel_identity = kernel["content_identity"]
    authored = _authored(language)
    schema = _source_schema(authored)
    operation_calls = _source_role_nodes(schema, "operation-call")
    assert operation_calls
    for operation_call in operation_calls:
        operation_call["properties"]["node"]["const"] = "operation-invocation"
    compiler = next(
        package for package in authored["packages"] if package["id"] == "standard.compiler"
    )
    profiles = next(
        closure["definitions"]
        for closure in compiler["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
    )
    binding = next(
        row
        for row in profiles[0]["source_native_bindings"]
        if row["slot"] == "source.operation_call.discriminator"
    )
    binding["value"] = "operation-invocation"
    graph = _graph(kernel, authored)
    assert kernel["content_identity"] == kernel_identity
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], (consumer.__name__, result["diagnostics"])

    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )

    def rename(value):
        if isinstance(value, dict):
            for key, child in value.items():
                value[key] = rename(child)
            return value
        if isinstance(value, list):
            return [rename(child) for child in value]
        return "operation-invocation" if value == "operation-call" else value

    rename(source)
    public = _PublicCandidate(
        tmp_path / "operation-invocation", authorities=(kernel, graph)
    )
    public.write_source(source)
    public.cli("model", "check", str(public.source))


def test_language_owned_interval_token_reaches_public_model_and_formula(
    tmp_path: Path,
):
    from test_current_namespace_public import _PublicCandidate

    kernel, language = mutable_authorities()
    authored = _authored(language)

    def rename(value):
        if isinstance(value, dict):
            for key, child in value.items():
                value[key] = rename(child)
            return value
        if isinstance(value, list):
            return [rename(child) for child in value]
        return "bounded-range" if value == "closed-interval" else value

    rename(authored)
    graph = _graph(kernel, authored)
    public = _PublicCandidate(tmp_path / "bounded-range", authorities=(kernel, graph))
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    rename(source)
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "39" * 32,
    )

    module = source["modules"][0]
    formula = module["formulas"][0]
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source["package_requirements"],
        "module": {name: value for name, value in module.items() if name != "formulas"},
        "formula": deepcopy(formula),
    }
    request_path = public.directory / "formula.json"
    render_request = deepcopy(request)
    del render_request["formula"]["expression"]
    request_path.write_text(json.dumps(render_request))
    rendered = public.cli("formula", "render", str(request_path))
    parse_request = deepcopy(request)
    del parse_request["formula"]["body"]
    request_path.write_text(json.dumps(parse_request))
    assert public.cli("formula", "parse", str(request_path)) == rendered


def test_language_owned_derived_role_reaches_public_quantity_template(
    tmp_path: Path,
):
    from test_current_namespace_public import _PublicCandidate

    kernel, language = mutable_authorities()
    authored = _authored(language)

    def rename(value, *, template_contract=False):
        if isinstance(value, dict):
            contract = template_contract or value.get("authority_path") == (
                "language.template_admission_profiles"
            )
            for key, child in value.items():
                value[key] = rename(child, template_contract=contract)
            return value
        if isinstance(value, list):
            return [
                rename(child, template_contract=template_contract) for child in value
            ]
        return "computed" if value == "derived" and not template_contract else value

    rename(authored)
    graph = _graph(kernel, authored)
    public = _PublicCandidate(tmp_path / "computed", authorities=(kernel, graph))
    release = public.cli(
        "template",
        "get",
        "--id",
        "standard.quantity-minimal",
    )
    starter = next(
        member["payload"]
        for member in release["members"]
        if member["logical_name"] == "starter-model-source"
    )
    assert {symbol["role"] for symbol in starter["modules"][0]["symbols"]} == {
        "parameter",
        "computed",
        "output",
    }
    source = public.directory / "source.json"
    public.cli(
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--package-id",
        "example.computed",
        "--out",
        str(source),
        "--invocation-key",
        "41" * 32,
    )
    public.cli("model", "check", str(source))
    public.cli(
        "model",
        "build",
        str(source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "42" * 32,
    )


def test_coherent_source_annotation_and_compiler_path_rename_is_admitted(
    tmp_path: Path,
):
    from test_current_namespace_public import _PublicCandidate, _members

    kernel, language = mutable_authorities()
    kernel_identity = kernel["content_identity"]
    authored = _authored(language)
    schema = _source_schema(authored)
    schema["properties"]["modules"]["semantic_member"] = "compilation_units"
    for module in _source_role_nodes(schema, "module"):
        module["semantic_role"] = "compilation-unit"

    compiler = next(
        package for package in authored["packages"] if package["id"] == "standard.compiler"
    )
    profiles = next(
        closure["definitions"]
        for closure in compiler["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
    )

    def rename_paths(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"path", "semantic_selector", "semantic_scope_selector"} and isinstance(
                    child, list
                ):
                    value[key] = [
                        "compilation_units" if part == "modules" else part
                        for part in child
                    ]
                else:
                    rename_paths(child)
        elif isinstance(value, list):
            for child in value:
                rename_paths(child)

    rename_paths(profiles)
    for profile in profiles:
        for binding in profile["source_native_bindings"]:
            if binding["slot"] == "source.root.modules":
                binding["member"] = "compilation_units"
            elif binding["slot"] == "source.module":
                binding["role"] = "compilation-unit"

    for package in authored["packages"]:
        for closure in package["semantic_closure"]:
            if closure["authority_path"] == "language.model_checks":
                rename_paths(closure["definitions"])

    graph = _graph(kernel, authored)
    assert kernel["content_identity"] == kernel_identity
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], (consumer.__name__, result["diagnostics"])

    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    public = _PublicCandidate(tmp_path / "coherent-rename", authorities=(kernel, graph))
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    built = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "40" * 32,
    )
    assert len(_members(built)) == 8

    module = source["modules"][0]
    formula = module["formulas"][0]
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source["package_requirements"],
        "module": {name: value for name, value in module.items() if name != "formulas"},
        "formula": deepcopy(formula),
    }
    request_path = public.directory / "formula.json"
    render_request = deepcopy(request)
    del render_request["formula"]["expression"]
    request_path.write_text(json.dumps(render_request))
    rendered = public.cli("formula", "render", str(request_path))
    parse_request = deepcopy(request)
    del parse_request["formula"]["body"]
    request_path.write_text(json.dumps(parse_request))
    assert public.cli("formula", "parse", str(request_path)) == rendered


@pytest.mark.parametrize(
    "contract",
    [
        {},
        {"nodes": [], "result": {"kind": "missing"}},
        {"kind": "parameter"},
    ],
    ids=(
        "ambiguous-empty-union",
        "malformed-discriminator",
        "missing-required-member",
    ),
)
def test_source_projection_refuses_non_operation_contract_union_gaps(contract):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    graph = _graph(kernel, authored)
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    members = context.source_native_binding_index.members
    program_schema = context.source_semantic_index.role_anchors[
        context.source_native_binding_index.roles["source.program"]
    ][0]
    result_schema = source_schema_member(
        program_schema, members["source.program.result"]
    )[1]

    with pytest.raises(ValueError, match="no unique semantic branch"):
        project_source_value(
            contract, result_schema, context.source_native_binding_index
        )


@pytest.mark.parametrize("contract", [[], "", 0, False, None])
def test_source_projection_refuses_falsey_non_object_operation_contract(contract):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    graph = _graph(kernel, authored)
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    members = context.source_native_binding_index.members
    operation_schema = context.source_semantic_index.role_anchors[
        context.source_native_binding_index.roles["source.operation_call"]
    ][0]
    result_schema = source_schema_member(
        operation_schema, members["source.operation_call.result"]
    )[1]

    with pytest.raises(ValueError, match="no unique semantic branch"):
        project_source_value(
            cast(dict[str, Any], contract),
            result_schema,
            context.source_native_binding_index,
        )


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
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result


def test_source_semantic_keywords_have_no_parallel_metadata_selector():
    kernel, language = mutable_authorities()
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "source_notation"
    ]["semantic_annotations"]
    assert set(law) == {
        "identifier",
        "keys",
        "native_contract",
        "native_payload_annotations",
        "one_of",
        "placement",
        "role_members",
        "root_role",
    }
    keywords = kernel["meta_format"]["language_definitions"]["collections"][
        "wire_schemas"
    ]["field_types"]["schema"]["allowed_keywords"]
    assert {
        "semantic_role",
        "semantic_member",
        "semantic_native_contract",
    } <= set(keywords)
    assert _consumer_a(kernel, language)["admitted"]


def test_retired_lowering_source_selector_cannot_reintroduce_an_address_owner():
    kernel, language = mutable_authorities()
    assert _consumer_a(kernel, language)["admitted"]
    authored = _authored(language)
    lowering = next(
        definition
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.model_lowerings"
        for definition in closure["definitions"]
    )
    lowering["source_selector"] = ["modules", "*", "symbols", "*"]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result
