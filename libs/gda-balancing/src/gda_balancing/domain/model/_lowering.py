"""Authority-driven lowering of checked Model Sources into resolved artifacts."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast


from gda_balancing.domain.artifacts import (
    _artifact_contract,
    _identified_artifact,
)
from gda_balancing.domain.artifact_semantics import artifact_semantic_projection
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
)
from gda_balancing.domain.formula.types import (
    formula_contract_contains as _formula_contract_contains,
    formula_contract_matches as _formula_contract_matches,
    formula_contract_matches_operation as _formula_contract_matches_operation,
    resolve_formula_contract as _resolved_formula_contract,
)
from gda_balancing.domain.authority.runtime_validation import (
    fixed_operation_value_contract,
    operation_literal_context_contract as _literal_context_contract,
    operation_value_contract_matches,
)
from gda_balancing.domain.operation_program import (
    closed_operation_coordinates,
    project_operation_program,
    record_instruction_evaluation_sites,
)
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    admit_typed_value,
    language_structured_value_index,
)

from gda_balancing.domain.model._resolution import (
    CheckedModel,
    _FORMULA_REASON,
    _formula_contexts,
    _formula_policy,
    _language,
    _model_lowering,
    _operation_formula_slots,
    _operation_reference_node_ids,
    _path_value,
    _pointer,
    _resolution_profile,
    _selected_source_operation_coordinates,
    _selected_values,
)

_LOWERER_IMPLEMENTATION_IDENTITY = "gda-balancing.python-lowerer-v1"


def lowering_inputs(
    checked: CheckedModel,
) -> tuple[
    dict[str, Any],
    list[dict[str, JsonValue]],
    dict[str, Any],
    list[tuple[dict[str, Any], tuple[object, ...]]],
]:
    """Resolve the authority-owned inputs shared by checking and compilation."""
    lock = _package_lock(checked)
    language = _language(checked.language_bundle)
    lowering = _model_lowering(checked.language_bundle)
    source_rows = _resolved_source_symbols(checked.source, checked.language_bundle)
    declarations: list[dict[str, JsonValue]] = []
    for fields, _source_pointer in source_rows:
        structured = fields.get("value_kind") == "nominal-structured"
        fact = {
            "kind": lowering[
                "structured_initial_fact_kind" if structured else "initial_fact_kind"
            ],
            "fields": fields,
        }
        rule_chain_member = "structured_rule_chain" if structured else "rule_chain"
        for invocation in cast(list[dict[str, str]], lowering[rule_chain_member]):
            fact = _apply_language_rule(
                language,
                rule_id=invocation["rule"],
                phase=invocation["phase"],
                judgment=invocation["judgment"],
                facts=[fact],
            )
        declarations.append(cast(dict[str, JsonValue], fact["fields"]))
    return lock, declarations, lowering, source_rows


class _RuntimeProjectionResourceExhausted(Exception):
    """The admitted runtime-projection budget was exhausted."""


class _EntrypointBindingError(ValueError):
    """A Model entrypoint failed at one exact author-owned source pointer."""

    def __init__(self, pointer: str, message: str) -> None:
        super().__init__(message)
        self.pointer = pointer


class _FormulaResolutionError(ValueError):
    """Formula resolution failed at one exact author-owned source pointer."""

    def __init__(self, reason_id: str, pointer: str, message: str) -> None:
        super().__init__(message)
        self.reason_id = reason_id
        self.pointer = pointer


@dataclass
class _RuntimeProjectionBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise _RuntimeProjectionResourceExhausted
        self.used += 1


def checked_model_template_facts(checked: CheckedModel) -> dict[str, JsonValue]:
    """Project generic graph facts consumed by Template admission profiles."""
    lowering = _model_lowering(checked.language_bundle)
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    root_requirements = [
        {
            "id": item[requirement_package_member],
            "version": item[requirement_version_member],
        }
        for item in cast(list[dict[str, str]], checked.source[requirements_member])
    ]
    lock = _package_lock(checked)
    resolved_packages = [
        {
            "id": item["id"],
            "version": item["version"],
            "content_identity": item["content_identity"],
        }
        for item in cast(list[dict[str, JsonValue]], lock["packages"])
    ]
    source_symbols = []
    for fields, _source_pointer in _resolved_source_symbols(
        checked.source, checked.language_bundle
    ):
        resolved = cast(dict[str, str], fields["resolved_symbol"])
        source_symbols.append(
            {
                **fields,
                "id": f"{resolved['module']}.{resolved['name']}",
            }
        )
    return {
        "root_requirements": cast(JsonValue, root_requirements),
        "resolved_packages": cast(JsonValue, resolved_packages),
        "source_symbols": cast(JsonValue, source_symbols),
    }


def _rir_semantic_projection(
    language_bundle: dict[str, Any],
    rir: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Project an RIR artifact or payload to executable semantics only."""
    contract = _artifact_contract(language_bundle, "rir-semantic-payload")
    projection = contract.get("semantic_identity_projection")
    if not isinstance(projection, dict):
        raise ValueError("RIR artifact contract has no semantic identity projection")
    return artifact_semantic_projection(rir, projection)


def _rir_semantic_identity(
    language_bundle: dict[str, Any], rir: dict[str, JsonValue]
) -> str:
    contract = _artifact_contract(language_bundle, "rir-semantic-payload")
    domain = contract.get("semantic_identity_domain")
    if not isinstance(domain, str) or not domain:
        raise ValueError("RIR artifact contract has no semantic identity domain")
    return content_identity(
        domain,
        cast(JsonValue, _rir_semantic_projection(language_bundle, rir)),
    )


def _identified_rir_artifact(
    language_bundle: dict[str, Any], payload: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    return _identified_artifact(
        language_bundle,
        "rir-semantic-payload",
        {
            **payload,
            "semantic_identity": _rir_semantic_identity(language_bundle, payload),
        },
    )


def _resolved_source_symbols(
    source: dict[str, Any], language_bundle: dict[str, Any]
) -> list[tuple[dict[str, Any], tuple[object, ...]]]:
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    language = _language(language_bundle)
    model_id = _path_value(source, cast(str, profile["manifest_id_path"]))
    modules_member = cast(str, profile["modules_member"])
    module_id_member = cast(str, profile["module_id_member"])
    imports_member = cast(str, profile["imports_member"])
    symbols_member = cast(str, profile["symbols_member"])
    alias_member = cast(str, profile["import_alias_member"])
    package_member = cast(str, profile["import_package_member"])
    version_member = cast(str, profile["import_version_member"])
    import_symbol_member = cast(str, profile["import_symbol_member"])
    source_symbol_member = cast(str, profile["symbol_name_member"])
    fact_symbol_member = cast(str, profile["symbol_fact_member"])
    source_type_member = cast(str, profile["symbol_type_member"])
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    requirements = {
        (
            item[requirement_package_member],
            item[requirement_version_member],
        )
        for item in cast(list[dict[str, str]], source[requirements_member])
    }
    packages = {
        (item["id"], item["version"]): item
        for item in cast(list[dict[str, Any]], language["packages"])
    }
    selected_source_rows = {
        pointer: value
        for value, pointer in _selected_values(
            source, cast(list[str], lowering["source_selector"])
        )
    }
    rows: list[tuple[dict[str, Any], tuple[object, ...]]] = []
    resolved_source_pointers: set[tuple[object, ...]] = set()
    module_ids: set[str] = set()
    resolved_names: set[tuple[str, str, str]] = set()
    for module_index, module in enumerate(
        cast(list[dict[str, Any]], source[modules_member])
    ):
        module_id = cast(str, module[module_id_member])
        if module_id in module_ids:
            raise ValueError(f"duplicate module id: {module_id}")
        module_ids.add(module_id)
        imports: dict[str, dict[str, str]] = {}
        for item in cast(list[dict[str, str]], module[imports_member]):
            alias = item[alias_member]
            if alias in imports:
                raise ValueError(f"duplicate import alias: {alias}")
            package_key = (item[package_member], item[version_member])
            if package_key not in requirements:
                raise ValueError(f"import is not declared as a requirement: {alias}")
            package = packages.get(package_key)
            if package is None:
                raise ValueError(f"import package release is unavailable: {alias}")
            exported_types = {
                exported["id"]
                for exported in cast(list[dict[str, Any]], package["exports"]["types"])
            }
            if item[import_symbol_member] not in exported_types:
                raise ValueError(f"imported type is not exported: {alias}")
            imports[alias] = item
        for symbol_index, source_symbol in enumerate(
            cast(list[dict[str, Any]], module[symbols_member])
        ):
            source_pointer = (
                modules_member,
                module_index,
                symbols_member,
                symbol_index,
            )
            if source_pointer not in selected_source_rows:
                continue
            if selected_source_rows[source_pointer] is not source_symbol:
                raise ValueError("model lowering source selection was ambiguous")
            resolved_source_pointers.add(source_pointer)
            alias = source_symbol[source_type_member]
            imported = imports.get(alias)
            if imported is None:
                raise ValueError(f"symbol type alias is unresolved: {alias}")
            name = cast(str, source_symbol[source_symbol_member])
            resolved_symbol = {
                "model": model_id,
                "module": module_id,
                "name": name,
            }
            resolved_key = (model_id, module_id, name)
            if resolved_key in resolved_names:
                raise ValueError(f"duplicate resolved symbol: {name}")
            resolved_names.add(resolved_key)
            fields = {
                key: value
                for key, value in source_symbol.items()
                if key not in {source_symbol_member, source_type_member}
            }
            fields[fact_symbol_member] = name
            fields["resolved_symbol"] = resolved_symbol
            fields["type_identity"] = {
                "package": imported[package_member],
                "version": imported[version_member],
                "symbol": imported[import_symbol_member],
            }
            nominal_matches = [
                definition
                for definition in cast(list[dict[str, Any]], language["nominal_types"])
                if definition.get("package") == imported[package_member]
                and definition.get("version") == imported[version_member]
                and definition.get("id") == imported[import_symbol_member]
            ]
            if len(nominal_matches) == 1:
                fields["value_kind"] = "nominal-structured"
            rows.append(
                (
                    fields,
                    source_pointer,
                )
            )
    if set(selected_source_rows) != resolved_source_pointers:
        raise ValueError(
            "model lowering source selector is outside the resolution profile"
        )
    entry_module = _path_value(source, cast(str, profile["manifest_entry_module_path"]))
    if entry_module not in module_ids:
        raise ValueError("manifest entry_module does not name a module")
    return sorted(
        rows,
        key=lambda item: (
            item[0]["resolved_symbol"]["model"],
            item[0]["resolved_symbol"]["module"],
            item[0]["resolved_symbol"]["name"],
        ),
    )


def _formula_contract_mismatch_reason(
    formula_contract: dict[str, Any],
    target_contract: dict[str, Any],
    *,
    operation: bool,
) -> str | None:
    if operation:
        formula_type = formula_contract.get("type_identity")
        target_type = target_contract.get("type")
        type_matches = (
            isinstance(formula_type, dict)
            and isinstance(target_type, dict)
            and formula_type.get("package") == target_type.get("package")
            and formula_type.get("version") == target_type.get("version")
            and formula_type.get("symbol") == target_type.get("id")
            and formula_contract.get("representation")
            == target_contract.get("representation")
        )
    else:
        type_matches = (
            formula_contract.get("type_identity")
            == target_contract.get("type_identity")
            and formula_contract.get("representation")
            == target_contract.get("representation")
            and formula_contract.get("domain_kind")
            == target_contract.get("domain_kind")
            and formula_contract.get("domain") == target_contract.get("domain")
        )
    if not type_matches:
        return _FORMULA_REASON["type-mismatch"]
    if formula_contract.get("kind") != target_contract.get("kind"):
        return _FORMULA_REASON["kind-mismatch"]
    if formula_contract.get("unit") != target_contract.get("unit"):
        return _FORMULA_REASON["unit-mismatch"]
    if formula_contract.get("numeric_policy") != target_contract.get("numeric_policy"):
        return _FORMULA_REASON["numeric-profile-mismatch"]
    return None


def _formula_operation_identity(
    domains: dict[str, str],
    package: str,
    version: str,
    operation_id: str,
) -> str:
    """Identify the exact selected coordinate independently of specialization."""
    return content_identity(
        domains["operation"],
        {
            "package": package,
            "version": version,
            "id": operation_id,
        },
    )


def _resolved_formula_operand(
    source_operand: dict[str, Any],
    *,
    parameters: dict[str, dict[str, Any]],
    locals_by_id: dict[str, dict[str, Any]],
    declarations_by_source: dict[tuple[str, str], dict[str, Any]],
    expected: dict[str, Any] | None,
    actual_operand_domain: str,
) -> tuple[dict[str, JsonValue], dict[str, Any]]:
    kind = source_operand.get("kind")
    if kind == "parameter":
        parameter = parameters.get(cast(str, source_operand.get("parameter")))
        if parameter is None:
            raise ValueError("Formula operand names no parameter")
        body: dict[str, JsonValue] = {
            "kind": "parameter",
            "parameter": cast(str, source_operand["parameter"]),
        }
        contract = parameter
    elif kind == "local":
        local = locals_by_id.get(cast(str, source_operand.get("local")))
        if local is None:
            raise ValueError("Formula operand names no preceding local")
        body = {
            "kind": "local",
            "local": cast(str, source_operand["local"]),
        }
        contract = local
    elif kind == "symbol":
        symbol = declarations_by_source.get(
            (
                cast(str, source_operand.get("module")),
                cast(str, source_operand.get("symbol")),
            )
        )
        if symbol is None:
            raise ValueError("Formula operand names no resolved Symbol")
        body = {
            "kind": "symbol",
            "resolved_symbol": cast(dict[str, JsonValue], symbol["resolved_symbol"]),
        }
        contract = symbol
    elif kind == "literal":
        if expected is None:
            raise ValueError("Formula literal has no exact contextual contract")
        value = source_operand.get("value")
        domain = expected.get("domain")
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not isinstance(domain, dict)
            or not isinstance(domain.get("minimum"), int)
            or not isinstance(domain.get("maximum"), int)
            or not domain["minimum"] <= value <= domain["maximum"]
        ):
            raise ValueError("Formula literal is outside its contextual contract")
        body = {"kind": "literal", "value": value}
        contract = expected
    else:
        raise ValueError("Formula operand kind is outside the admitted policy")
    if expected is not None and not _formula_contract_matches(contract, expected):
        raise ValueError("Formula operand is incompatible with its formal contract")
    return (
        {
            **body,
            "identity": content_identity(
                actual_operand_domain,
                cast(JsonValue, body),
            ),
        },
        contract,
    )


def _resolved_formula_call_arguments(
    formula: dict[str, Any],
    node: dict[str, Any],
    operation: dict[str, Any],
    declarations_by_source: dict[tuple[str, str], dict[str, Any]],
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Project concrete value contracts for one resolved Formula Operation call."""
    parameters = {
        cast(str, parameter["id"]): parameter
        for parameter in cast(list[dict[str, Any]], formula["parameters"])
    }
    locals_by_id = {
        cast(str, item["id"]): cast(dict[str, Any], item["result"])
        for item in cast(
            list[dict[str, Any]], cast(dict[str, Any], formula["body"])["nodes"]
        )
    }
    ports = {
        cast(str, port["id"]): port
        for port in cast(list[dict[str, Any]], operation["inputs"])
    }
    resolved: dict[str, dict[str, Any]] = {}
    for argument in cast(list[dict[str, Any]], node["arguments"]):
        port_id = cast(str, argument["port"])
        operand = cast(dict[str, Any], argument["operand"])
        operand_kind = operand.get("kind")
        if operand_kind == "parameter":
            contract = parameters[cast(str, operand["parameter"])]
        elif operand_kind == "local":
            contract = locals_by_id[cast(str, operand["local"])]
        elif operand_kind == "symbol":
            symbol = cast(dict[str, str], operand["resolved_symbol"])
            contract = declarations_by_source[(symbol["module"], symbol["name"])]
        elif operand_kind == "literal":
            value = operand.get("value")
            literal_context = _literal_context_contract(
                value,
                ports[port_id],
                kernel,
                {
                    "literal_typing_profiles": [
                        {"definition": profile}
                        for profile in cast(
                            list[dict[str, Any]],
                            _language(language_bundle)["literal_typing_profiles"],
                        )
                    ]
                },
            )
            if (
                literal_context is None
                or not isinstance(value, int)
                or isinstance(value, bool)
            ):
                raise ValueError("Formula literal has no concrete call-site contract")
            literal_type = cast(dict[str, str], literal_context["type"])
            contract = {
                "type_identity": {
                    "package": literal_type["package"],
                    "version": literal_type["version"],
                    "symbol": literal_type["id"],
                },
                "representation": literal_context["representation"],
                "kind": literal_context["kind"],
                "unit": literal_context["unit"],
                "domain_kind": "closed-interval",
                "domain": {"minimum": value, "maximum": value},
                "numeric_policy": literal_context["numeric_policy"],
            }
        else:
            raise ValueError("Formula call operand has no concrete contract")
        resolved[port_id] = contract
    return resolved


def _derived_formula_evaluation_site(
    domains: dict[str, str],
    resolved_symbol: dict[str, JsonValue],
    context: dict[str, str],
) -> dict[str, JsonValue]:
    body = cast(
        dict[str, JsonValue],
        {
            "kind": "derived-symbol",
            "context": context,
            "resolved_symbol": resolved_symbol,
        },
    )
    return {
        **body,
        "identity": content_identity(domains["evaluation_site"], body),
    }


def _reachable_derived_formula_sites(
    declarations_by_symbol: dict[tuple[str, str], dict[str, Any]],
    formulas: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    entrypoints: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    """Close derived Formula sites reachable from executable entrypoints/slots."""

    def derived_symbols(value: Any) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        if isinstance(value, dict):
            if value.get("kind") == "symbol":
                reference = value.get("resolved_symbol")
                if not isinstance(reference, dict):
                    reference = value.get("symbol")
                if isinstance(reference, dict):
                    module = reference.get("module")
                    name = reference.get("name", reference.get("symbol"))
                else:
                    module = value.get("module")
                    name = value.get("symbol")
                if isinstance(module, str) and isinstance(name, str):
                    key = (module, name)
                    if declarations_by_symbol.get(key, {}).get("role") == "derived":
                        found.add(key)
            for child in value.values():
                found.update(derived_symbols(child))
        elif isinstance(value, list):
            for child in value:
                found.update(derived_symbols(child))
        return found

    formulas_by_key = {
        (cast(str, formula["module"]), cast(str, formula["id"])): formula
        for formula in formulas
    }
    bindings_by_site: dict[tuple[str, str], dict[str, Any]] = {}
    reachable_formula_keys: set[tuple[str, str]] = set()
    for binding in bindings:
        site = cast(dict[str, Any], binding["site"])
        formula_ref = cast(dict[str, Any], binding["formula"])
        formula_key = (
            cast(str, formula_ref["module"]),
            cast(str, formula_ref["id"]),
        )
        if site.get("kind") == "operation-slot":
            reachable_formula_keys.add(formula_key)
        elif site.get("kind") == "derived-symbol":
            symbol = cast(dict[str, Any], site["resolved_symbol"])
            bindings_by_site[
                (cast(str, symbol["module"]), cast(str, symbol["name"]))
            ] = binding

    reachable_sites = derived_symbols(entrypoints)
    pending_sites = list(reachable_sites)
    pending_formulas = list(reachable_formula_keys)
    visited_formulas: set[tuple[str, str]] = set()
    while pending_sites or pending_formulas:
        while pending_sites:
            site_key = pending_sites.pop()
            binding = bindings_by_site.get(site_key)
            if binding is None:
                continue
            discovered_sites = derived_symbols(binding["arguments"]) - reachable_sites
            reachable_sites.update(discovered_sites)
            pending_sites.extend(discovered_sites)
            formula_ref = cast(dict[str, Any], binding["formula"])
            formula_key = (
                cast(str, formula_ref["module"]),
                cast(str, formula_ref["id"]),
            )
            if formula_key not in visited_formulas:
                pending_formulas.append(formula_key)
        while pending_formulas:
            formula_key = pending_formulas.pop()
            if formula_key in visited_formulas:
                continue
            visited_formulas.add(formula_key)
            formula = formulas_by_key.get(formula_key)
            if formula is None:
                continue
            discovered_sites = derived_symbols(formula["body"]) - reachable_sites
            reachable_sites.update(discovered_sites)
            pending_sites.extend(discovered_sites)
            for node in cast(
                list[dict[str, Any]], cast(dict[str, Any], formula["body"])["nodes"]
            ):
                if node.get("node") != "formula-call":
                    continue
                called = cast(dict[str, Any], node["formula"])
                called_key = (
                    cast(str, called["module"]),
                    cast(str, called["id"]),
                )
                if called_key not in visited_formulas:
                    pending_formulas.append(called_key)
    return reachable_sites


def _resolved_formula_programs_and_bindings_impl(
    checked: CheckedModel,
    declarations: list[dict[str, Any]],
    policy: dict[str, Any],
    failure_context: list[str],
) -> tuple[
    list[dict[str, JsonValue]],
    list[dict[str, JsonValue]],
    list[tuple[str, str]],
]:
    profile = _resolution_profile(
        checked.language_bundle,
        cast(str, _model_lowering(checked.language_bundle)["resolution_profile"]),
    )
    modules = cast(
        list[dict[str, Any]],
        checked.source[cast(str, profile["modules_member"])],
    )
    formulas_member = cast(str, policy["module_formulas_member"])
    formula_id_member = cast(str, policy["formula_id_member"])
    formula_parameters_member = cast(str, policy["formula_parameters_member"])
    formula_result_member = cast(str, policy["formula_result_member"])
    formula_body_member = cast(str, policy["formula_body_member"])
    body_nodes_member = cast(str, policy["body_nodes_member"])
    body_result_member = cast(str, policy["body_result_member"])
    node_id_member = cast(str, policy["node_id_member"])
    parameter_id_member = cast(str, policy["parameter_id_member"])
    bindings_member = cast(str, policy["bindings_member"])
    binding_site_member = cast(str, policy["binding_site_member"])
    binding_formula_member = cast(str, policy["binding_formula_member"])
    binding_arguments_member = cast(str, policy["binding_arguments_member"])
    binding_parameter_member = cast(str, policy["binding_parameter_member"])
    binding_operand_member = cast(str, policy["binding_operand_member"])
    declarations_by_source = {
        (
            cast(dict[str, str], declaration["resolved_symbol"])["module"],
            cast(dict[str, str], declaration["resolved_symbol"])["name"],
        ): declaration
        for declaration in declarations
    }
    domains = cast(dict[str, str], policy["identity_domains"])
    formula_contexts = _formula_contexts(checked.language_bundle)
    actual_operand_domain = cast(
        str,
        checked.kernel["meta_format"]["runtime_program"]["invocation_contract"][
            "identity_domains"
        ]["actual_operand"],
    )
    prototypes: dict[tuple[str, str], dict[str, Any]] = {}
    formula_pointers: dict[tuple[str, str], str] = {}
    for module_index, module in enumerate(modules):
        module_id = cast(str, module[cast(str, profile["module_id_member"])])
        imports = {
            cast(str, item[cast(str, profile["import_alias_member"])]): {
                "alias": cast(str, item[cast(str, profile["import_alias_member"])]),
                "package": cast(str, item[cast(str, profile["import_package_member"])]),
                "version": cast(str, item[cast(str, profile["import_version_member"])]),
                "symbol": cast(str, item[cast(str, profile["import_symbol_member"])]),
            }
            for item in cast(
                list[dict[str, Any]],
                module[cast(str, profile["imports_member"])],
            )
        }
        for formula_index, source_formula in enumerate(
            cast(list[dict[str, Any]], module.get(formulas_member, []))
        ):
            failure_context[:] = [
                f"/modules/{module_index}/{formulas_member}/{formula_index}"
            ]
            formula_id = source_formula.get(formula_id_member)
            key = (module_id, cast(str, formula_id))
            if not isinstance(formula_id, str) or not formula_id or key in prototypes:
                raise ValueError("Formula declarations must have unique module names")
            resolved_parameters: list[dict[str, JsonValue]] = []
            parameter_ids: set[str] = set()
            for source_parameter in cast(
                list[dict[str, Any]], source_formula[formula_parameters_member]
            ):
                parameter_id = source_parameter.get(parameter_id_member)
                if (
                    not isinstance(parameter_id, str)
                    or not parameter_id
                    or parameter_id in parameter_ids
                ):
                    raise ValueError("Formula parameter ids must be unique")
                parameter_ids.add(parameter_id)
                resolved_parameters.append(
                    {
                        "id": parameter_id,
                        **_resolved_formula_contract(
                            source_parameter,
                            imports,
                            checked.kernel,
                            policy,
                        ),
                    }
                )
            resolved_parameters.sort(key=lambda item: cast(str, item["id"]))
            body = source_formula[formula_body_member]
            if (
                not isinstance(body, dict)
                or not isinstance(body.get(body_nodes_member), list)
                or not isinstance(body.get(body_result_member), dict)
            ):
                raise ValueError("Formula body is not an admitted bounded program")
            if len(body[body_nodes_member]) > cast(
                int, policy["max_nodes_per_formula"]
            ):
                raise _FormulaResolutionError(
                    _FORMULA_REASON["resource-exhausted"],
                    failure_context[0],
                    "Formula body exceeds its admitted node bound",
                )
            prototypes[key] = {
                "module": module_id,
                "id": formula_id,
                "parameters": resolved_parameters,
                "result": _resolved_formula_contract(
                    cast(dict[str, Any], source_formula[formula_result_member]),
                    imports,
                    checked.kernel,
                    policy,
                ),
                "imports": imports,
                "source_body": body,
                "source_expression": source_formula["expression"],
            }
            formula_pointers[key] = (
                f"/modules/{module_index}/{formulas_member}/{formula_index}"
            )

    dependencies: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for key, prototype in prototypes.items():
        failure_context[:] = [formula_pointers[key]]
        node_ids: set[str] = set()
        calls: list[tuple[str, str]] = []
        for node in cast(
            list[dict[str, Any]], prototype["source_body"][body_nodes_member]
        ):
            node_id = node.get(node_id_member)
            if not isinstance(node_id, str) or not node_id or node_id in node_ids:
                raise ValueError("Formula expression node ids must be unique")
            node_ids.add(node_id)
            if node.get("node") == "formula-call":
                formula_ref = node.get("formula")
                if not isinstance(formula_ref, dict):
                    raise ValueError("Formula call has no static declaration reference")
                target = (
                    cast(str, formula_ref.get("module")),
                    cast(str, formula_ref.get("id")),
                )
                if target not in prototypes:
                    raise ValueError("Formula call names no declaration")
                calls.append(target)
            elif node.get("node") not in cast(list[str], policy["allowed_body_nodes"]):
                raise ValueError(
                    "Formula expression node is outside the admitted policy"
                )
        dependencies[key] = calls

    visiting: set[tuple[str, str]] = set()
    visited: set[tuple[str, str]] = set()
    order: list[tuple[str, str]] = []

    def visit(key: tuple[str, str]) -> None:
        if key in visiting:
            raise _FormulaResolutionError(
                _FORMULA_REASON["cycle"],
                f"{formula_pointers[key]}/body",
                "Formula call graph contains a cycle",
            )
        if key in visited:
            return
        visiting.add(key)
        for dependency in dependencies[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
        order.append(key)

    for key in sorted(prototypes):
        visit(key)

    resolved_by_key: dict[tuple[str, str], dict[str, JsonValue]] = {}
    lock = _package_lock(checked)
    operations_by_coordinate = {
        (
            cast(str, row["package"]),
            cast(str, cast(dict[str, Any], row["definition"])["version"]),
            cast(str, cast(dict[str, Any], row["definition"])["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(list[dict[str, Any]], lock["operations"])
    }
    charge_per_node = cast(int, policy["resource_charge_per_node"])
    for key in order:
        failure_context[:] = [formula_pointers[key]]
        prototype = prototypes[key]
        parameters_by_id = {
            cast(str, item["id"]): item
            for item in cast(list[dict[str, Any]], prototype["parameters"])
        }
        locals_by_id: dict[str, dict[str, Any]] = {}
        resolved_nodes: list[dict[str, JsonValue]] = []
        transitive_formula_dependencies: set[str] = set()
        transitive_operation_dependencies: set[str] = set()
        refusals: set[str] = set()
        max_steps = 0
        termination_measure = 1
        for source_node in cast(
            list[dict[str, Any]], prototype["source_body"][body_nodes_member]
        ):
            node_id = cast(str, source_node[node_id_member])
            node_kind = source_node["node"]
            if node_kind == "formula-call":
                formula_ref = cast(dict[str, str], source_node["formula"])
                target_key = (formula_ref["module"], formula_ref["id"])
                called = resolved_by_key[target_key]
                called_parameters = {
                    cast(str, item["id"]): item
                    for item in cast(list[dict[str, Any]], called["parameters"])
                }
                source_arguments = cast(list[dict[str, Any]], source_node["arguments"])
                call_parameter_ids = [
                    cast(str, argument.get("parameter"))
                    for argument in source_arguments
                ]
                if (
                    len(call_parameter_ids) != len(called_parameters)
                    or len(call_parameter_ids) != len(set(call_parameter_ids))
                    or set(call_parameter_ids) != set(called_parameters)
                ):
                    raise ValueError(
                        "Formula call does not totally bind its parameters"
                    )
                arguments: list[dict[str, JsonValue]] = []
                for source_argument in source_arguments:
                    parameter_id = cast(str, source_argument["parameter"])
                    operand, _contract = _resolved_formula_operand(
                        cast(dict[str, Any], source_argument["operand"]),
                        parameters=parameters_by_id,
                        locals_by_id=locals_by_id,
                        declarations_by_source=declarations_by_source,
                        expected=called_parameters[parameter_id],
                        actual_operand_domain=actual_operand_domain,
                    )
                    arguments.append({"parameter": parameter_id, "operand": operand})
                arguments.sort(key=lambda item: cast(str, item["parameter"]))
                node_result = cast(dict[str, Any], called["result"])
                node_body = cast(
                    dict[str, JsonValue],
                    {
                        "id": node_id,
                        "node": "formula-call",
                        "formula": {
                            "module": called["module"],
                            "id": called["id"],
                            "identity": called["identity"],
                        },
                        "arguments": arguments,
                        "result": node_result,
                    },
                )
                called_closure = cast(dict[str, Any], called["closure"])
                transitive_formula_dependencies.add(cast(str, called["identity"]))
                transitive_formula_dependencies.update(
                    cast(list[str], called_closure["formula_dependencies"])
                )
                transitive_operation_dependencies.update(
                    cast(list[str], called_closure["operation_dependencies"])
                )
                refusals.update(cast(list[str], called_closure["refusals"]))
                max_steps += charge_per_node + cast(
                    int,
                    cast(dict[str, Any], called_closure["resource_charge"])[
                        "max_steps"
                    ],
                )
                termination_measure = max(
                    termination_measure,
                    1 + cast(int, called_closure["termination_measure"]),
                )
            elif node_kind == "operation-call":
                operation_ref = cast(dict[str, str], source_node["operation"])
                coordinate = (
                    operation_ref["package"],
                    operation_ref["version"],
                    operation_ref["id"],
                )
                operation = operations_by_coordinate.get(coordinate)
                if (
                    operation is None
                    or operation.get("purity") != "pure"
                    or operation.get("operation_kind") != "pure-expression"
                    or operation.get("effects") != []
                ):
                    raise _FormulaResolutionError(
                        _FORMULA_REASON["purity-mismatch"],
                        formula_pointers[key],
                        "Formula operation call is unresolved or effectful",
                    )
                ports = {
                    cast(str, port["id"]): port
                    for port in cast(list[dict[str, Any]], operation["inputs"])
                }
                source_arguments = cast(list[dict[str, Any]], source_node["arguments"])
                port_ids = [argument.get("port") for argument in source_arguments]
                if (
                    len(port_ids) != len(ports)
                    or len(port_ids) != len(set(port_ids))
                    or set(port_ids) != set(ports)
                ):
                    raise ValueError(
                        "Formula operation call does not totally bind its ports"
                    )
                arguments = []
                for source_argument in source_arguments:
                    port_id = cast(str, source_argument["port"])
                    source_operand = cast(dict[str, Any], source_argument["operand"])
                    if source_operand.get("kind") == "literal":
                        literal_context = _literal_context_contract(
                            source_operand.get("value"),
                            ports[port_id],
                            checked.kernel,
                            {
                                "literal_typing_profiles": [
                                    {"definition": profile}
                                    for profile in cast(
                                        list[dict[str, Any]],
                                        _language(checked.language_bundle)[
                                            "literal_typing_profiles"
                                        ],
                                    )
                                ]
                            },
                        )
                        if literal_context is None:
                            raise ValueError(
                                "Formula literal is incompatible with its "
                                "Operation port"
                            )
                        operand_body = cast(
                            dict[str, JsonValue],
                            {
                                "kind": "literal",
                                "value": source_operand["value"],
                            },
                        )
                        operand = {
                            **operand_body,
                            "identity": content_identity(
                                actual_operand_domain, operand_body
                            ),
                        }
                        literal_type = cast(dict[str, str], literal_context["type"])
                        operand_contract = {
                            "type_identity": {
                                "package": literal_type["package"],
                                "version": literal_type["version"],
                                "symbol": literal_type["id"],
                            },
                            **{
                                member: literal_context[member]
                                for member in (
                                    "representation",
                                    "kind",
                                    "unit",
                                    "domain",
                                    "numeric_policy",
                                )
                            },
                        }
                    else:
                        operand, operand_contract = _resolved_formula_operand(
                            source_operand,
                            parameters=parameters_by_id,
                            locals_by_id=locals_by_id,
                            declarations_by_source=declarations_by_source,
                            expected=None,
                            actual_operand_domain=actual_operand_domain,
                        )
                    if not _formula_contract_matches_operation(
                        operand_contract, ports[port_id]
                    ):
                        raise ValueError(
                            "Formula operand is incompatible with its Operation port"
                        )
                    arguments.append({"port": port_id, "operand": operand})
                arguments.sort(key=lambda item: cast(str, item["port"]))
                node_result = _resolved_formula_contract(
                    cast(dict[str, Any], source_node["result"]),
                    cast(dict[str, dict[str, str]], prototype["imports"]),
                    checked.kernel,
                    policy,
                )
                if not _formula_contract_matches_operation(
                    node_result, cast(dict[str, Any], operation["result"])
                ):
                    raise ValueError(
                        "Formula local result is incompatible with its Operation"
                    )
                operation_identity = _formula_operation_identity(
                    domains, coordinate[0], coordinate[1], coordinate[2]
                )
                node_body = cast(
                    dict[str, JsonValue],
                    {
                        "id": node_id,
                        "node": "operation-call",
                        "operation": {
                            "package": coordinate[0],
                            "version": coordinate[1],
                            "id": coordinate[2],
                            "identity": operation_identity,
                        },
                        "arguments": arguments,
                        "result": node_result,
                    },
                )
                transitive_operation_dependencies.add(operation_identity)
                refusals.update(cast(list[str], operation["refusals"]))
                max_steps += charge_per_node + cast(
                    int,
                    cast(dict[str, Any], operation["resource_bounds"])["max_steps"],
                )
            elif node_kind == "conditional":
                condition, condition_contract = _resolved_formula_operand(
                    cast(dict[str, Any], source_node["condition"]),
                    parameters=parameters_by_id,
                    locals_by_id=locals_by_id,
                    declarations_by_source=declarations_by_source,
                    expected=None,
                    actual_operand_domain=actual_operand_domain,
                )
                boolean_contract = fixed_operation_value_contract(
                    checked.kernel, "kernel-boolean"
                )
                if boolean_contract is None:
                    raise ValueError(
                        "Formula conditional has no Kernel Boolean contract"
                    )
                boolean_type = cast(dict[str, str], boolean_contract["type"])
                if condition_contract.get("type_identity") != {
                    "package": boolean_type["package"],
                    "version": boolean_type["version"],
                    "symbol": boolean_type["id"],
                } or any(
                    condition_contract.get(member) != boolean_contract.get(member)
                    for member in (
                        "representation",
                        "kind",
                        "unit",
                        "domain",
                        "numeric_policy",
                    )
                ):
                    raise _FormulaResolutionError(
                        _FORMULA_REASON["type-mismatch"],
                        formula_pointers[key],
                        "Formula conditional requires the Kernel Boolean contract",
                    )
                when_true, true_contract = _resolved_formula_operand(
                    cast(dict[str, Any], source_node["when_true"]),
                    parameters=parameters_by_id,
                    locals_by_id=locals_by_id,
                    declarations_by_source=declarations_by_source,
                    expected=None,
                    actual_operand_domain=actual_operand_domain,
                )
                when_false, false_contract = _resolved_formula_operand(
                    cast(dict[str, Any], source_node["when_false"]),
                    parameters=parameters_by_id,
                    locals_by_id=locals_by_id,
                    declarations_by_source=declarations_by_source,
                    expected=true_contract,
                    actual_operand_domain=actual_operand_domain,
                )
                if not _formula_contract_matches(true_contract, false_contract):
                    raise ValueError("Formula conditional branches are incompatible")
                node_result = {
                    member: value
                    for member, value in true_contract.items()
                    if member != "id"
                }
                node_body = cast(
                    dict[str, JsonValue],
                    {
                        "id": node_id,
                        "node": "conditional",
                        "condition": condition,
                        "when_true": when_true,
                        "when_false": when_false,
                        "result": node_result,
                    },
                )
                max_steps += charge_per_node
            else:
                raise ValueError(
                    "Formula program node has no implemented admitted lowering"
                )
            resolved_nodes.append(
                {
                    **node_body,
                    "identity": content_identity(domains["expression_node"], node_body),
                }
            )
            locals_by_id[node_id] = node_result
        result_operand, result_contract = _resolved_formula_operand(
            cast(dict[str, Any], prototype["source_body"][body_result_member]),
            parameters=parameters_by_id,
            locals_by_id=locals_by_id,
            declarations_by_source=declarations_by_source,
            expected=cast(dict[str, Any], prototype["result"]),
            actual_operand_domain=actual_operand_domain,
        )
        if not _formula_contract_matches(
            result_contract, cast(dict[str, Any], prototype["result"])
        ):
            raise ValueError("Formula program result contract is incompatible")
        if result_operand["kind"] != "local":
            max_steps += charge_per_node
        closure = cast(
            dict[str, JsonValue],
            {
                "formula_dependencies": sorted(transitive_formula_dependencies),
                "operation_dependencies": sorted(transitive_operation_dependencies),
                "refusals": sorted(refusals),
                "resource_charge": {"max_steps": max_steps},
                "termination_measure": termination_measure,
            },
        )
        body = cast(
            dict[str, JsonValue],
            {
                "nodes": resolved_nodes,
                "result": result_operand,
            },
        )
        formula_body = cast(
            dict[str, JsonValue],
            {
                "module": prototype["module"],
                "id": prototype["id"],
                "parameters": prototype["parameters"],
                "result": prototype["result"],
                "body": body,
                "closure": closure,
            },
        )
        resolved_by_key[key] = {
            **formula_body,
            "expression": cast(str, prototype["source_expression"]),
            "identity": content_identity(domains["declaration"], formula_body),
        }

    failure_context.clear()
    selected_formula_keys: set[tuple[str, str]] = set()
    source_bindings = cast(
        list[dict[str, Any]], checked.source.get(bindings_member, [])
    )
    binding_pointer_by_formula: dict[tuple[str, str], str] = {}
    for binding_index, source_binding in enumerate(source_bindings):
        formula_ref = cast(dict[str, str], source_binding[binding_formula_member])
        formula_key = (formula_ref["module"], formula_ref["id"])
        selected_formula_keys.add(formula_key)
        binding_pointer_by_formula.setdefault(
            formula_key,
            f"/{bindings_member}/{binding_index}/{binding_formula_member}",
        )
    pending = list(selected_formula_keys)
    while pending:
        key = pending.pop()
        if key not in resolved_by_key:
            raise _FormulaResolutionError(
                _FORMULA_REASON["binding-missing"],
                binding_pointer_by_formula[key],
                "Formula binding names no declaration",
            )
        for dependency in dependencies[key]:
            if dependency not in selected_formula_keys:
                selected_formula_keys.add(dependency)
                pending.append(dependency)

    resolved_bindings: list[dict[str, JsonValue]] = []
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], lock["packages"])
    }
    selected_slots: dict[
        tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any], str]
    ] = {}
    formula_operation_roots = {
        (
            cast(str, operation["package"]),
            cast(str, operation["version"]),
            cast(str, operation["id"]),
        )
        for key in selected_formula_keys
        for node in cast(
            list[dict[str, Any]],
            cast(dict[str, Any], resolved_by_key[key]["body"])["nodes"],
        )
        if node.get("node") == "operation-call"
        and isinstance((operation := node.get("operation")), dict)
    }
    concrete_formula_calls: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for key in selected_formula_keys:
        resolved_formula = resolved_by_key[key]
        for node in cast(
            list[dict[str, Any]],
            cast(dict[str, Any], resolved_formula["body"])["nodes"],
        ):
            operation_ref = node.get("operation")
            if node.get("node") != "operation-call" or not isinstance(
                operation_ref, dict
            ):
                continue
            coordinate = (
                cast(str, operation_ref["package"]),
                cast(str, operation_ref["version"]),
                cast(str, operation_ref["id"]),
            )
            concrete_formula_calls.setdefault(coordinate, []).append(
                {
                    "arguments": _resolved_formula_call_arguments(
                        cast(dict[str, Any], resolved_formula),
                        node,
                        operations_by_coordinate[coordinate],
                        declarations_by_source,
                        checked.kernel,
                        checked.language_bundle,
                    ),
                    "result": node["result"],
                }
            )
    selected_operation_coordinates = _selected_source_operation_coordinates(
        checked.source,
        lock,
        _operation_reference_node_ids(checked.kernel),
        formula_operation_roots,
    )
    for operation_row in cast(list[dict[str, Any]], lock["operations"]):
        package_id = cast(str, operation_row["package"])
        definition = cast(dict[str, Any], operation_row["definition"])
        coordinate = (
            package_id,
            package_versions[package_id],
            cast(str, definition["id"]),
        )
        if coordinate not in selected_operation_coordinates:
            continue
        operation_identity = _formula_operation_identity(
            domains, coordinate[0], coordinate[1], coordinate[2]
        )
        for slot in _operation_formula_slots(definition):
            slot_key = (*coordinate, cast(str, slot["id"]))
            if slot_key in selected_slots:
                raise ValueError("selected Operation repeats a Formula slot")
            selected_slots[slot_key] = (definition, slot, operation_identity)

    bound_derived_sites: set[tuple[str, str]] = set()
    bound_operation_slots: set[tuple[str, str, str, str]] = set()
    for binding_index, source_binding in enumerate(source_bindings):
        binding_pointer = f"/{bindings_member}/{binding_index}"
        failure_context[:] = [binding_pointer]
        source_site = cast(dict[str, Any], source_binding[binding_site_member])
        source_formula_ref = cast(
            dict[str, str], source_binding[binding_formula_member]
        )
        formula = resolved_by_key[
            (source_formula_ref["module"], source_formula_ref["id"])
        ]
        binding_parameters = {
            cast(str, item["id"]): item
            for item in cast(list[dict[str, Any]], formula["parameters"])
        }
        source_arguments = cast(
            list[dict[str, Any]], source_binding[binding_arguments_member]
        )
        binding_parameter_ids = [
            cast(str, argument.get(binding_parameter_member))
            for argument in source_arguments
        ]
        if (
            len(binding_parameter_ids) != len(binding_parameters)
            or len(binding_parameter_ids) != len(set(binding_parameter_ids))
            or set(binding_parameter_ids) != set(binding_parameters)
        ):
            reason = (
                _FORMULA_REASON["binding-duplicate"]
                if len(binding_parameter_ids) != len(set(binding_parameter_ids))
                else _FORMULA_REASON["binding-missing"]
            )
            raise _FormulaResolutionError(
                reason,
                f"{binding_pointer}/arguments",
                "Formula binding does not totally bind its parameters",
            )
        arguments: list[dict[str, JsonValue]] = []
        if source_site.get("kind") == "derived-symbol":
            site_key = (
                cast(str, source_site.get("module")),
                cast(str, source_site.get("symbol")),
            )
            site_declaration = declarations_by_source.get(site_key)
            if site_declaration is None or site_declaration.get("role") != "derived":
                raise _FormulaResolutionError(
                    _FORMULA_REASON["unreachable"],
                    f"{binding_pointer}/site",
                    "Formula binding site is not a reachable derived Symbol",
                )
            if site_key in bound_derived_sites:
                raise _FormulaResolutionError(
                    _FORMULA_REASON["binding-duplicate"],
                    f"{binding_pointer}/site",
                    "Formula derived Symbol is bound more than once",
                )
            mismatch_reason = _formula_contract_mismatch_reason(
                cast(dict[str, Any], formula["result"]),
                site_declaration,
                operation=False,
            )
            if mismatch_reason is not None:
                raise _FormulaResolutionError(
                    mismatch_reason,
                    f"{binding_pointer}/formula",
                    "Formula result is incompatible with its derived Symbol",
                )
            bound_derived_sites.add(site_key)
            for source_argument in source_arguments:
                parameter_id = cast(str, source_argument[binding_parameter_member])
                operand, _contract = _resolved_formula_operand(
                    cast(dict[str, Any], source_argument[binding_operand_member]),
                    parameters={},
                    locals_by_id={},
                    declarations_by_source=declarations_by_source,
                    expected=binding_parameters[parameter_id],
                    actual_operand_domain=actual_operand_domain,
                )
                arguments.append({"parameter": parameter_id, "operand": operand})
            resolved_sites = [
                _derived_formula_evaluation_site(
                    domains,
                    cast(
                        dict[str, JsonValue],
                        site_declaration["resolved_symbol"],
                    ),
                    formula_contexts[phase],
                )
                for phase in ("initialization", "event", "observation")
            ]
        elif source_site.get("kind") == "operation-slot":
            source_operation = cast(dict[str, Any], source_site.get("operation"))
            slot_key = (
                cast(str, source_operation.get("package")),
                cast(str, source_operation.get("version")),
                cast(str, source_operation.get("id")),
                cast(str, source_site.get("slot")),
            )
            selected_slot = selected_slots.get(slot_key)
            if selected_slot is None:
                raise _FormulaResolutionError(
                    _FORMULA_REASON["unreachable"],
                    f"{binding_pointer}/site",
                    "Formula binding site is not a selected Operation slot",
                )
            if slot_key in bound_operation_slots:
                raise _FormulaResolutionError(
                    _FORMULA_REASON["binding-duplicate"],
                    f"{binding_pointer}/site",
                    "Formula Operation slot is bound more than once",
                )
            operation, slot, operation_identity = selected_slot
            if slot.get("context") != formula_contexts["event"]:
                raise _FormulaResolutionError(
                    _FORMULA_REASON["context-mismatch"],
                    f"{binding_pointer}/site",
                    "Formula Operation slot uses no admitted Runtime context",
                )
            slot_parameters = {
                cast(str, parameter["id"]): parameter
                for parameter in cast(list[dict[str, Any]], slot["parameters"])
            }
            concrete_calls = concrete_formula_calls.get(slot_key[:3], [])
            for source_argument in source_arguments:
                parameter_id = cast(str, source_argument[binding_parameter_member])
                source_operand = cast(
                    dict[str, Any], source_argument[binding_operand_member]
                )
                slot_parameter_id = cast(str, source_operand.get("parameter"))
                slot_parameter = slot_parameters.get(slot_parameter_id)
                if (
                    source_operand.get("kind") != "slot-parameter"
                    or slot_parameter is None
                ):
                    raise _FormulaResolutionError(
                        _FORMULA_REASON["binding-missing"],
                        f"{binding_pointer}/arguments/{len(arguments)}/operand",
                        "Formula Operation-slot argument is unresolved",
                    )
                mismatch_reason = _formula_contract_mismatch_reason(
                    binding_parameters[parameter_id],
                    slot_parameter,
                    operation=True,
                )
                if mismatch_reason is not None:
                    raise _FormulaResolutionError(
                        mismatch_reason,
                        f"{binding_pointer}/arguments/{len(arguments)}/operand",
                        "Formula Operation-slot argument is incompatible",
                    )
                slot_source = slot_parameter.get("source")
                concrete_port = (
                    cast(str, slot_source["name"])
                    if isinstance(slot_source, dict)
                    and slot_source.get("kind") == "port"
                    and isinstance(slot_source.get("name"), str)
                    else None
                )
                if concrete_port is not None:
                    for call in concrete_calls:
                        actual_contract = cast(
                            dict[str, Any],
                            cast(dict[str, Any], call["arguments"])[concrete_port],
                        )
                        if not _formula_contract_contains(
                            binding_parameters[parameter_id], actual_contract
                        ):
                            raise _FormulaResolutionError(
                                _FORMULA_REASON["type-mismatch"],
                                f"{binding_pointer}/arguments/{len(arguments)}/operand",
                                "Formula Operation-slot parameter does not cover its "
                                "concrete call-site domain",
                            )
                operand_body = cast(
                    dict[str, JsonValue],
                    {
                        "kind": "slot-parameter",
                        "parameter": slot_parameter_id,
                    },
                )
                arguments.append(
                    {
                        "parameter": parameter_id,
                        "operand": {
                            **operand_body,
                            "identity": content_identity(
                                actual_operand_domain, operand_body
                            ),
                        },
                    }
                )
            mismatch_reason = _formula_contract_mismatch_reason(
                cast(dict[str, Any], formula["result"]),
                cast(dict[str, Any], slot["result"]),
                operation=True,
            )
            if mismatch_reason is not None:
                raise _FormulaResolutionError(
                    mismatch_reason,
                    f"{binding_pointer}/formula",
                    "Formula result is incompatible with its Operation slot",
                )
            for call in concrete_calls:
                if not _formula_contract_contains(
                    cast(dict[str, Any], call["result"]),
                    cast(dict[str, Any], formula["result"]),
                ):
                    raise _FormulaResolutionError(
                        _FORMULA_REASON["type-mismatch"],
                        f"{binding_pointer}/formula",
                        "Formula Operation-slot result exceeds its concrete "
                        "call-site domain",
                    )
            closure = cast(dict[str, Any], formula["closure"])
            if not set(cast(list[str], closure["refusals"])) <= set(
                cast(list[str], slot["permitted_refusals"])
            ):
                raise _FormulaResolutionError(
                    _FORMULA_REASON["refusal-widening"],
                    f"{binding_pointer}/formula",
                    "Formula closure widens its Operation-slot refusals",
                )
            if operation_identity in set(
                cast(list[str], closure["operation_dependencies"])
            ):
                raise _FormulaResolutionError(
                    _FORMULA_REASON["cycle"],
                    f"{binding_pointer}/formula",
                    "Formula closure cycles through its Operation slot",
                )
            if cast(
                int,
                cast(dict[str, Any], closure["resource_charge"])["max_steps"],
            ) > cast(int, slot["resource_bounds"]["max_steps"]) or cast(
                int, closure["termination_measure"]
            ) > cast(int, slot["termination_measure"]):
                raise _FormulaResolutionError(
                    _FORMULA_REASON["resource-exhausted"],
                    f"{binding_pointer}/formula",
                    "Formula closure exceeds its Operation-slot resource contract",
                )
            bound_operation_slots.add(slot_key)
            exact_operation = cast(
                dict[str, JsonValue],
                {
                    "package": slot_key[0],
                    "version": slot_key[1],
                    "id": slot_key[2],
                    "identity": operation_identity,
                },
            )
            context = cast(dict[str, JsonValue], slot["context"])
            site_body = cast(
                dict[str, JsonValue],
                {
                    "kind": "operation-slot",
                    "operation": exact_operation,
                    "slot": slot_key[3],
                    "context": context,
                },
            )
            resolved_sites = [
                {
                    **site_body,
                    "identity": content_identity(domains["evaluation_site"], site_body),
                }
            ]
        else:
            raise ValueError("Formula binding site is outside the admitted policy")
        arguments.sort(key=lambda item: cast(str, item["parameter"]))
        for resolved_site in resolved_sites:
            binding_body = cast(
                dict[str, JsonValue],
                {
                    "site": resolved_site,
                    "formula": {
                        "module": formula["module"],
                        "id": formula["id"],
                        "identity": formula["identity"],
                    },
                    "arguments": arguments,
                },
            )
            resolved_bindings.append(
                {
                    **binding_body,
                    "identity": content_identity(domains["binding"], binding_body),
                }
            )
    if bound_operation_slots != set(selected_slots):
        raise _FormulaResolutionError(
            _FORMULA_REASON["binding-missing"],
            "/entrypoints/0/operation",
            "every selected Operation Formula slot requires exactly one binding",
        )
    resolved_formulas = [resolved_by_key[key] for key in sorted(selected_formula_keys)]
    if (
        _reachable_derived_formula_sites(
            declarations_by_source,
            cast(list[dict[str, Any]], resolved_formulas),
            cast(list[dict[str, Any]], resolved_bindings),
            cast(list[dict[str, Any]], checked.source["entrypoints"]),
        )
        != bound_derived_sites
    ):
        raise _FormulaResolutionError(
            _FORMULA_REASON["unreachable"],
            next(
                (
                    f"/{bindings_member}/{index}/{binding_site_member}"
                    for index, binding in enumerate(source_bindings)
                    if cast(dict[str, Any], binding[binding_site_member]).get("kind")
                    == "derived-symbol"
                    and (
                        cast(
                            str,
                            cast(dict[str, Any], binding[binding_site_member])[
                                "module"
                            ],
                        ),
                        cast(
                            str,
                            cast(dict[str, Any], binding[binding_site_member])[
                                "symbol"
                            ],
                        ),
                    )
                    not in _reachable_derived_formula_sites(
                        declarations_by_source,
                        cast(list[dict[str, Any]], resolved_formulas),
                        cast(list[dict[str, Any]], resolved_bindings),
                        cast(list[dict[str, Any]], checked.source["entrypoints"]),
                    )
                ),
                f"/{bindings_member}",
            ),
            "derived Formula binding is outside the executable entrypoint closure",
        )
    return (
        resolved_formulas,
        sorted(
            resolved_bindings,
            key=lambda item: cast(str, item["identity"]),
        ),
        [
            (formula_pointers[key], cast(str, resolved_by_key[key]["identity"]))
            for key in sorted(selected_formula_keys)
        ],
    )


def _resolved_formula_programs_and_bindings(
    checked: CheckedModel,
    declarations: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[
    list[dict[str, JsonValue]],
    list[dict[str, JsonValue]],
    list[tuple[str, str]],
]:
    failure_context: list[str] = []
    try:
        return _resolved_formula_programs_and_bindings_impl(
            checked,
            declarations,
            policy,
            failure_context,
        )
    except _FormulaResolutionError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        if failure_context:
            message = str(error)
            if "incompatible" in message or "does not match" in message:
                reason_id = _FORMULA_REASON["type-mismatch"]
            else:
                reason_id = cast(
                    str,
                    _resolution_profile(
                        checked.language_bundle,
                        cast(
                            str,
                            _model_lowering(checked.language_bundle)[
                                "resolution_profile"
                            ],
                        ),
                    )["structural_reason"],
                )
            raise _FormulaResolutionError(
                reason_id,
                failure_context[0],
                message,
            ) from error
        raise


def _resolved_formulas_and_bindings(
    checked: CheckedModel,
    declarations: list[dict[str, Any]],
) -> tuple[
    list[dict[str, JsonValue]],
    list[dict[str, JsonValue]],
    list[tuple[str, str]],
]:
    """Normalize authoring sugar, then resolve one Formula program grammar."""
    policy = _formula_policy(checked.language_bundle)
    profile = _resolution_profile(
        checked.language_bundle,
        cast(str, _model_lowering(checked.language_bundle)["resolution_profile"]),
    )
    normalized_source = deepcopy(checked.source)
    changed = False
    normalizations = cast(list[dict[str, str]], policy["inline_body_normalizations"])
    for module in cast(
        list[dict[str, Any]],
        normalized_source[cast(str, profile["modules_member"])],
    ):
        for formula in cast(
            list[dict[str, Any]],
            module.get(cast(str, policy["module_formulas_member"]), []),
        ):
            body = formula.get(cast(str, policy["formula_body_member"]))
            if not isinstance(body, dict):
                continue
            for normalization in normalizations:
                parameter_member = normalization["parameter_member"]
                if (
                    set(body) != {"node", parameter_member}
                    or body.get("node") != (normalization["node"])
                ):
                    continue
                formula[cast(str, policy["formula_body_member"])] = {
                    cast(str, policy["body_nodes_member"]): [],
                    cast(str, policy["body_result_member"]): {
                        "kind": normalization["result_kind"],
                        parameter_member: body[parameter_member],
                    },
                }
                changed = True
                break
    normalized = (
        CheckedModel(
            source=normalized_source,
            source_identity=checked.source_identity,
            kernel=checked.kernel,
            language_bundle=checked.language_bundle,
            authority_context=checked.authority_context,
        )
        if changed
        else checked
    )
    return _resolved_formula_programs_and_bindings(
        normalized,
        declarations,
        policy,
    )


def _assignment_policy(
    lowering: dict[str, Any],
    *,
    expected_roles: set[str] | None = None,
) -> dict[str, Any]:
    policy = lowering.get("assignment_policy")
    if not isinstance(policy, dict):
        raise ValueError("the admitted lowering has no Symbol assignment policy")
    rows = policy.get("roles")
    if (
        not isinstance(rows, list)
        or not rows
        or policy.get("scenario_target_cardinality") != "one-per-resolved-actual"
        or policy.get("duplicate_actual_policy") != "collapse"
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("role"), str)
            or not isinstance(row.get("modes"), list)
            or not row["modes"]
            or any(
                not isinstance(mode, dict)
                or not isinstance(mode.get("id"), str)
                or not mode["id"]
                or mode.get("initialization_source")
                not in {
                    "execution",
                    "experiment",
                    "model",
                    "model-with-experiment-override",
                    "named-random-stream",
                    "resolved-model",
                }
                or mode.get("value_member") not in {"forbidden", "required"}
                or mode.get("experiment_cardinality")
                not in {"forbidden", "optional", "required"}
                or mode.get("event_payload_cardinality")
                not in {"forbidden", "optional", "required"}
                or mode.get("external_fact_cardinality")
                not in {"forbidden", "optional", "required"}
                or not isinstance(mode.get("override"), bool)
                for mode in row["modes"]
            )
            or len(row["modes"]) != len({mode["id"] for mode in row["modes"]})
            or not isinstance(row.get("entrypoint_operand_access"), list)
            or any(
                access not in {"read", "read-write", "write"}
                for access in row["entrypoint_operand_access"]
            )
            or len(row["entrypoint_operand_access"])
            != len(set(row["entrypoint_operand_access"]))
            or not isinstance(row.get("entrypoint_result"), bool)
            or row.get("binding_kind") not in {"operand", "result", "internal"}
            for row in rows
        )
    ):
        raise ValueError("the admitted lowering has no total Symbol assignment policy")
    by_role = {row["role"]: row for row in rows}
    if len(by_role) != len(rows):
        raise ValueError("the admitted Symbol assignment policy repeats a role")
    if expected_roles is not None and set(by_role) != expected_roles:
        raise ValueError("the admitted Symbol assignment policy is not total")
    if any(
        not _assignment_mode_is_coherent(mode)
        for row in rows
        for mode in cast(list[dict[str, Any]], row["modes"])
    ):
        raise ValueError("the admitted Symbol assignment mode ownership is incomplete")
    if any(not _assignment_role_is_total(row) for row in rows):
        raise ValueError("the admitted lowering has no total Symbol assignment policy")
    return policy


def _assignment_mode_is_coherent(mode: dict[str, Any]) -> bool:
    source = mode.get("initialization_source")
    value_member = mode.get("value_member")
    cardinality = mode.get("experiment_cardinality")
    event_cardinality = mode.get("event_payload_cardinality")
    external_fact_cardinality = mode.get("external_fact_cardinality")
    override = mode.get("override")
    initialization_is_coherent = (
        (
            source == "model"
            and value_member == "required"
            and cardinality == "forbidden"
            and override is False
        )
        or (
            source == "experiment"
            and value_member == "forbidden"
            and cardinality == "required"
            and override is False
        )
        or (
            source == "model-with-experiment-override"
            and value_member == "required"
            and cardinality == "optional"
            and override is True
        )
        or (
            source in {"execution", "named-random-stream", "resolved-model"}
            and value_member == "forbidden"
            and cardinality == "forbidden"
            and override is False
        )
    )
    return (
        initialization_is_coherent
        and event_cardinality in {"forbidden", "optional", "required"}
        and external_fact_cardinality in {"forbidden", "optional", "required"}
    )


def _assignment_role_is_total(row: dict[str, Any]) -> bool:
    modes = cast(list[dict[str, Any]], row["modes"])
    accesses = cast(list[str], row["entrypoint_operand_access"])
    result = cast(bool, row["entrypoint_result"])
    if row["binding_kind"] == "operand":
        return (
            bool(accesses)
            and result is False
            and all(
                mode["experiment_cardinality"] != "forbidden"
                or mode["initialization_source"]
                in {"model", "model-with-experiment-override"}
                or (
                    row["role"] == "derived"
                    and mode["initialization_source"] == "resolved-model"
                )
                for mode in modes
            )
            and all(
                mode["event_payload_cardinality"] == "forbidden"
                or (
                    accesses == ["read"]
                    and mode["initialization_source"]
                    in {"experiment", "model-with-experiment-override"}
                )
                for mode in modes
            )
            and all(
                mode["external_fact_cardinality"] == "forbidden"
                or (
                    accesses == ["read"]
                    and mode["initialization_source"] == "experiment"
                )
                for mode in modes
            )
        )
    if row["binding_kind"] == "result":
        return (
            not accesses
            and result is True
            and all(mode["initialization_source"] == "execution" for mode in modes)
            and all(mode["event_payload_cardinality"] == "forbidden" for mode in modes)
            and all(mode["external_fact_cardinality"] == "forbidden" for mode in modes)
        )
    return (
        row["binding_kind"] == "internal"
        and not accesses
        and result is False
        and all(mode["event_payload_cardinality"] == "forbidden" for mode in modes)
        and all(mode["external_fact_cardinality"] == "forbidden" for mode in modes)
    )


def _assignment_policy_by_role(
    policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows = cast(list[dict[str, Any]], policy["roles"])
    by_role = {cast(str, row["role"]): row for row in rows}
    return by_role


def _assignment_mode_for_declaration(
    declaration: dict[str, Any],
    assignment_policy: dict[str, Any],
) -> dict[str, Any] | None:
    role = declaration.get("role")
    value_policy = declaration.get("value_policy")
    if not isinstance(role, str) or not isinstance(value_policy, dict):
        return None
    row = _assignment_policy_by_role(assignment_policy).get(role)
    mode_id = value_policy.get("mode")
    if row is None or not isinstance(mode_id, str):
        return None
    matches = [
        mode
        for mode in cast(list[dict[str, Any]], row["modes"])
        if mode["id"] == mode_id
    ]
    return matches[0] if len(matches) == 1 else None


def _exact_operation_coordinate(
    operation_row: dict[str, Any],
    package_versions: dict[str, str],
) -> dict[str, str]:
    package = cast(str, operation_row["package"])
    return {
        "package": package,
        "version": package_versions[package],
        "id": cast(str, operation_row["definition"]["id"]),
    }


def _value_contract_matches(
    declaration: dict[str, Any],
    contract: dict[str, Any],
) -> bool:
    expected_type = contract.get("type")
    type_matches = isinstance(expected_type, dict) and declaration.get(
        "type_identity"
    ) == {
        "package": expected_type.get("package"),
        "version": expected_type.get("version"),
        "symbol": expected_type.get("id"),
    }
    if not type_matches:
        return False
    if declaration.get("value_kind") == "nominal-structured":
        return contract.get("value_kind") == "nominal-structured"
    return all(
        declaration.get(member) == contract.get(member)
        for member in ("representation", "kind", "unit", "numeric_policy")
    )


def _inline_pure_expression_instruction(
    instruction: dict[str, Any],
    *,
    target: str,
    values: dict[str, dict[str, JsonValue]],
    reference: Callable[[dict[str, JsonValue]], str],
) -> dict[str, JsonValue]:
    """Lower a sealed pure-Operation instruction without node-specific dispatch."""
    node = instruction.get("node")
    source_target = instruction.get("target")
    if not isinstance(node, str) or not isinstance(source_target, str):
        raise ValueError("pure Operation instruction has no named result")
    compiled: dict[str, JsonValue] = {"node": node, "target": target}
    for member, value in instruction.items():
        if member in {"node", "target"}:
            continue
        if member == "literal":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("pure Operation literal is not an integer")
            compiled[member] = value
            continue
        if not isinstance(value, str) or value not in values:
            raise ValueError("pure Operation operand is not a named value")
        compiled[member] = reference(values[value])
    return compiled


def _specialize_operation_formula_slots(
    selected_semantics: dict[str, JsonValue],
    formulas: list[dict[str, JsonValue]],
    bindings: list[dict[str, JsonValue]],
) -> dict[str, JsonValue]:
    """Compile Formula slots to ordinary admitted Operation instructions."""
    specialized = deepcopy(selected_semantics)
    operation_rows = cast(
        list[dict[str, Any]],
        specialized["operations"],
    )
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], specialized["packages"])
    }
    operations = {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, cast(dict[str, Any], row["definition"])["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in operation_rows
    }
    formulas_by_identity = {
        cast(str, formula["identity"]): cast(dict[str, Any], formula)
        for formula in formulas
    }

    def runtime_operand(
        operand: dict[str, Any],
        parameter_sources: dict[str, dict[str, JsonValue]],
        local_sources: dict[str, dict[str, JsonValue]],
        snapshot_sources: dict[str, dict[str, JsonValue]],
    ) -> dict[str, JsonValue]:
        kind = operand["kind"]
        if kind == "parameter":
            return parameter_sources[cast(str, operand["parameter"])]
        if kind == "local":
            return local_sources[cast(str, operand["local"])]
        if kind == "literal":
            return {"kind": "literal", "literal": cast(int, operand["value"])}
        if kind == "symbol":
            alias = f"formula.snapshot.{operand['identity']}"
            resolved_symbol = cast(
                dict[str, JsonValue],
                operand["resolved_symbol"],
            )
            existing = snapshot_sources.get(alias)
            if existing is not None and existing != resolved_symbol:
                raise ValueError("Formula snapshot operand alias is ambiguous")
            snapshot_sources[alias] = resolved_symbol
            return {"kind": "local", "local": alias}
        raise ValueError("event Formula slot operand has no admitted runtime lowering")

    def runtime_reference(operand: dict[str, JsonValue]) -> str:
        if operand["kind"] == "port":
            return cast(str, operand["port"])
        if operand["kind"] == "local":
            return cast(str, operand["local"])
        raise ValueError(
            "Formula conditional branches require named event-frame values"
        )

    def compile_formula(
        formula: dict[str, Any],
        parameter_sources: dict[str, dict[str, JsonValue]],
        result_target: str,
        prefix: str,
        snapshot_sources: dict[str, dict[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        instructions: list[dict[str, JsonValue]] = []
        local_sources: dict[str, dict[str, JsonValue]] = {}
        result_operand = cast(dict[str, Any], formula["body"]["result"])
        final_local = (
            cast(str, result_operand["local"])
            if result_operand.get("kind") == "local"
            else None
        )
        for node in cast(list[dict[str, Any]], formula["body"]["nodes"]):
            node_id = cast(str, node["id"])
            target = result_target if node_id == final_local else f"{prefix}.{node_id}"
            if node["node"] == "operation-call":
                operation_ref = cast(dict[str, Any], node["operation"])
                called_operation = operations[
                    (
                        cast(str, operation_ref["package"]),
                        cast(str, operation_ref["version"]),
                        cast(str, operation_ref["id"]),
                    )
                ]
                child_values = {
                    cast(str, argument["port"]): runtime_operand(
                        cast(dict[str, Any], argument["operand"]),
                        parameter_sources,
                        local_sources,
                        snapshot_sources,
                    )
                    for argument in cast(list[dict[str, Any]], node["arguments"])
                }
                child_result_source = cast(
                    dict[str, Any], called_operation["result"]["source"]
                )
                child_result_name = (
                    cast(str, child_result_source["name"])
                    if child_result_source["kind"] in {"local", "port"}
                    else None
                )
                for child_index, child_instruction in enumerate(
                    cast(list[dict[str, Any]], called_operation["body"])
                ):
                    child_target_name = cast(str, child_instruction.get("target", ""))
                    child_target = (
                        target
                        if child_target_name == child_result_name
                        else f"{prefix}.{node_id}.{child_index}"
                    )

                    compiled_child = _inline_pure_expression_instruction(
                        child_instruction,
                        target=child_target,
                        values=child_values,
                        reference=runtime_reference,
                    )
                    instructions.append(compiled_child)
                    child_values[child_target_name] = {
                        "kind": "local",
                        "local": child_target,
                    }
                if child_result_name is None:
                    raise ValueError("Formula pure Operation has no value result")
                called_result = child_values[child_result_name]
                if called_result != {"kind": "local", "local": target}:
                    instructions.append(
                        {
                            "node": "copy",
                            "target": target,
                            "value": runtime_reference(called_result),
                        }
                    )
                # The Formula node itself is charged in addition to its
                # selected pure Operation body.
                instructions.append({"node": "copy", "target": target, "value": target})
            elif node["node"] == "conditional":
                condition = runtime_operand(
                    cast(dict[str, Any], node["condition"]),
                    parameter_sources,
                    local_sources,
                    snapshot_sources,
                )
                when_true = runtime_operand(
                    cast(dict[str, Any], node["when_true"]),
                    parameter_sources,
                    local_sources,
                    snapshot_sources,
                )
                when_false = runtime_operand(
                    cast(dict[str, Any], node["when_false"]),
                    parameter_sources,
                    local_sources,
                    snapshot_sources,
                )
                instructions.append(
                    {
                        "node": "if",
                        "target": target,
                        "condition": runtime_reference(condition),
                        "when_true": runtime_reference(when_true),
                        "when_false": runtime_reference(when_false),
                    }
                )
            elif node["node"] == "formula-call":
                called_ref = cast(dict[str, Any], node["formula"])
                called = formulas_by_identity[cast(str, called_ref["identity"])]
                called_sources = {
                    cast(str, argument["parameter"]): runtime_operand(
                        cast(dict[str, Any], argument["operand"]),
                        parameter_sources,
                        local_sources,
                        snapshot_sources,
                    )
                    for argument in cast(list[dict[str, Any]], node["arguments"])
                }
                instructions.extend(
                    compile_formula(
                        called,
                        called_sources,
                        target,
                        f"{prefix}.{node_id}",
                        snapshot_sources,
                    )
                )
                instructions.append({"node": "copy", "target": target, "value": target})
            else:
                raise ValueError("Formula node has no generic Operation lowering")
            local_sources[node_id] = {"kind": "local", "local": target}
        resolved_result = runtime_operand(
            result_operand,
            parameter_sources,
            local_sources,
            snapshot_sources,
        )
        if resolved_result == {"kind": "local", "local": result_target}:
            return instructions
        if resolved_result["kind"] == "literal":
            instructions.append(
                {
                    "node": "constant",
                    "target": result_target,
                    "literal": resolved_result["literal"],
                }
            )
        else:
            instructions.append(
                {
                    "node": "copy",
                    "target": result_target,
                    "value": runtime_reference(resolved_result),
                }
            )
        return instructions

    replacements: dict[
        tuple[str, str, str],
        list[tuple[int, int, list[dict[str, JsonValue]], str]],
    ] = {}
    snapshot_sources_by_operation: dict[
        tuple[str, str, str],
        dict[str, dict[str, JsonValue]],
    ] = {}
    for binding in bindings:
        site = cast(dict[str, Any], binding["site"])
        if site["kind"] != "operation-slot":
            continue
        operation_ref = cast(dict[str, Any], site["operation"])
        coordinate = (
            cast(str, operation_ref["package"]),
            cast(str, operation_ref["version"]),
            cast(str, operation_ref["id"]),
        )
        operation = operations[coordinate]
        slot = next(
            slot
            for slot in _operation_formula_slots(operation)
            if slot["id"] == site["slot"]
        )
        slot_parameters = {
            cast(str, parameter["id"]): parameter
            for parameter in cast(list[dict[str, Any]], slot["parameters"])
        }
        parameter_sources: dict[str, dict[str, JsonValue]] = {}
        for argument in cast(list[dict[str, Any]], binding["arguments"]):
            slot_parameter = slot_parameters[
                cast(str, cast(dict[str, Any], argument["operand"])["parameter"])
            ]
            source = cast(dict[str, Any], slot_parameter["source"])
            parameter_sources[cast(str, argument["parameter"])] = (
                {"kind": "port", "port": cast(str, source["name"])}
                if source["kind"] == "port"
                else {"kind": "local", "local": cast(str, source["name"])}
            )
        formula_ref = cast(dict[str, Any], binding["formula"])
        formula = formulas_by_identity[cast(str, formula_ref["identity"])]
        snapshot_sources = snapshot_sources_by_operation.setdefault(coordinate, {})
        compiled = compile_formula(
            formula,
            parameter_sources,
            cast(str, slot["target"]),
            f"formula.{site['slot']}",
            snapshot_sources,
        )
        expected_steps = cast(
            int,
            cast(dict[str, Any], formula["closure"])["resource_charge"]["max_steps"],
        )
        if len(compiled) > expected_steps:
            raise ValueError("generic event lowering exceeds Formula charge")
        placeholder_index = cast(int, slot["placeholder_index"])
        placeholder_length = cast(int, slot["placeholder_length"])
        replacements.setdefault(coordinate, []).append(
            (
                placeholder_index,
                placeholder_length,
                compiled,
                cast(str, site["identity"]),
            )
        )

    for coordinate, operation_replacements in replacements.items():
        operation = operations[coordinate]
        ordered = sorted(operation_replacements, key=lambda row: row[0])
        if any(
            left[0] + left[1] > right[0]
            for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("Operation Formula slot placeholders overlap")
        for start, length, compiled, _site_identity in reversed(ordered):
            operation["body"][start : start + length] = compiled
        extensions = cast(dict[str, Any], operation.setdefault("extensions", {}))
        snapshot_sources = snapshot_sources_by_operation.get(coordinate, {})
        if snapshot_sources:
            extensions["standard.snapshot-operands"] = {
                "kind": "pre-event-snapshot-symbols",
                "operands": [
                    {
                        "name": name,
                        "resolved_symbol": resolved_symbol,
                    }
                    for name, resolved_symbol in sorted(snapshot_sources.items())
                ],
            }
        shift = 0
        for start, length, compiled, site_identity in ordered:
            final_start = start + shift
            record_instruction_evaluation_sites(
                operation,
                first_instruction_index=final_start,
                instruction_count=len(compiled),
                evaluation_site_identity=site_identity,
            )
            shift += len(compiled) - length
    return cast(dict[str, JsonValue], specialized)


def _compile_initialization_programs(
    selected_semantics: dict[str, JsonValue],
    formulas: list[dict[str, JsonValue]],
    bindings: list[dict[str, JsonValue]],
    policy: dict[str, Any],
) -> list[dict[str, JsonValue]]:
    """Lower derived bindings to closed generic value-instruction programs."""
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], selected_semantics["packages"])
    }
    operations = {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, cast(dict[str, Any], row["definition"])["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(
            list[dict[str, Any]],
            selected_semantics["operations"],
        )
    }
    formulas_by_identity = {
        cast(str, formula["identity"]): cast(dict[str, Any], formula)
        for formula in formulas
    }
    domains = cast(dict[str, str], policy["identity_domains"])
    programs: list[dict[str, JsonValue]] = []

    for binding in bindings:
        site = cast(dict[str, Any], binding["site"])
        if site["kind"] != "derived-symbol":
            continue
        inputs: dict[str, dict[str, JsonValue]] = {}
        instructions: list[dict[str, JsonValue]] = []
        literal_index = 0

        def add_input(
            name: str,
            operand: dict[str, Any],
        ) -> dict[str, JsonValue]:
            candidate = name
            suffix = 1
            while candidate in inputs and inputs[candidate] != operand:
                suffix += 1
                candidate = f"{name}.{suffix}"
            inputs[candidate] = cast(dict[str, JsonValue], operand)
            return {"kind": "input", "name": candidate}

        parameter_sources = {
            cast(str, argument["parameter"]): add_input(
                cast(str, argument["parameter"]),
                cast(dict[str, Any], argument["operand"]),
            )
            for argument in cast(list[dict[str, Any]], binding["arguments"])
        }

        def source_for_operand(
            operand: dict[str, Any],
            parameters: dict[str, dict[str, JsonValue]],
            locals_by_id: dict[str, dict[str, JsonValue]],
            prefix: str,
        ) -> dict[str, JsonValue]:
            nonlocal literal_index
            kind = operand["kind"]
            if kind == "parameter":
                return parameters[cast(str, operand["parameter"])]
            if kind == "local":
                return locals_by_id[cast(str, operand["local"])]
            if kind == "symbol":
                symbol = cast(dict[str, str], operand["resolved_symbol"])
                return add_input(
                    f"symbol.{symbol['module']}.{symbol['name']}",
                    operand,
                )
            if kind == "literal":
                literal_index += 1
                return add_input(f"{prefix}.literal.{literal_index}", operand)
            raise ValueError("Formula operand has no generic initialization source")

        def reference(source: dict[str, JsonValue]) -> str:
            if source["kind"] in {"input", "local"}:
                return cast(str, source["name"])
            raise ValueError("initialization instruction source is not named")

        def instruction_site(
            formula: dict[str, Any],
            node_id: str,
            prefix: str,
        ) -> str:
            body = cast(
                dict[str, JsonValue],
                {
                    "kind": "initialization-instruction",
                    "root_site_identity": site["identity"],
                    "formula_identity": formula["identity"],
                    "node": node_id,
                    "path": prefix,
                },
            )
            return content_identity(domains["evaluation_site"], body)

        def emit(
            instruction: dict[str, JsonValue],
            *,
            evaluation_site_identity: str,
        ) -> None:
            instructions.append(
                {
                    "evaluation_site_identity": evaluation_site_identity,
                    "instruction": instruction,
                }
            )

        def compile_formula(
            formula: dict[str, Any],
            parameters: dict[str, dict[str, JsonValue]],
            prefix: str,
        ) -> dict[str, JsonValue]:
            locals_by_id: dict[str, dict[str, JsonValue]] = {}
            for node in cast(
                list[dict[str, Any]],
                cast(dict[str, Any], formula["body"])["nodes"],
            ):
                node_id = cast(str, node["id"])
                target = f"{prefix}.{node_id}"
                site_identity = instruction_site(formula, node_id, prefix)
                if node["node"] == "operation-call":
                    operation_ref = cast(dict[str, Any], node["operation"])
                    operation = operations[
                        (
                            cast(str, operation_ref["package"]),
                            cast(str, operation_ref["version"]),
                            cast(str, operation_ref["id"]),
                        )
                    ]
                    values = {
                        cast(str, argument["port"]): source_for_operand(
                            cast(dict[str, Any], argument["operand"]),
                            parameters,
                            locals_by_id,
                            prefix,
                        )
                        for argument in cast(list[dict[str, Any]], node["arguments"])
                    }
                    result_source = cast(dict[str, Any], operation["result"]["source"])
                    result_name = (
                        cast(str, result_source["name"])
                        if result_source["kind"] in {"local", "port"}
                        else None
                    )
                    for child_index, child in enumerate(
                        cast(list[dict[str, Any]], operation["body"])
                    ):
                        child_target_name = cast(str, child.get("target", ""))
                        child_target = f"{target}.{child_index}"

                        compiled_child = _inline_pure_expression_instruction(
                            child,
                            target=child_target,
                            values=values,
                            reference=reference,
                        )
                        emit(
                            compiled_child,
                            evaluation_site_identity=site_identity,
                        )
                        values[child_target_name] = {
                            "kind": "local",
                            "name": child_target,
                        }
                    if result_name is None:
                        raise ValueError("pure Operation has no value result")
                    operation_result = values[result_name]
                    emit(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(operation_result),
                        },
                        evaluation_site_identity=site_identity,
                    )
                elif node["node"] == "conditional":
                    condition = source_for_operand(
                        cast(dict[str, Any], node["condition"]),
                        parameters,
                        locals_by_id,
                        prefix,
                    )
                    when_true = source_for_operand(
                        cast(dict[str, Any], node["when_true"]),
                        parameters,
                        locals_by_id,
                        prefix,
                    )
                    when_false = source_for_operand(
                        cast(dict[str, Any], node["when_false"]),
                        parameters,
                        locals_by_id,
                        prefix,
                    )
                    emit(
                        {
                            "node": "if",
                            "target": target,
                            "condition": reference(condition),
                            "when_true": reference(when_true),
                            "when_false": reference(when_false),
                        },
                        evaluation_site_identity=site_identity,
                    )
                elif node["node"] == "formula-call":
                    called_ref = cast(dict[str, Any], node["formula"])
                    called = formulas_by_identity[cast(str, called_ref["identity"])]
                    called_parameters = {
                        cast(str, argument["parameter"]): source_for_operand(
                            cast(dict[str, Any], argument["operand"]),
                            parameters,
                            locals_by_id,
                            prefix,
                        )
                        for argument in cast(list[dict[str, Any]], node["arguments"])
                    }
                    called_result = compile_formula(
                        called,
                        called_parameters,
                        f"{prefix}.{node_id}",
                    )
                    emit(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(called_result),
                        },
                        evaluation_site_identity=site_identity,
                    )
                else:
                    raise ValueError(
                        "Formula node has no generic initialization lowering"
                    )
                locals_by_id[node_id] = {"kind": "local", "name": target}
            result = cast(dict[str, Any], formula["body"]["result"])
            result_source = source_for_operand(
                result,
                parameters,
                locals_by_id,
                prefix,
            )
            if result["kind"] == "local":
                return result_source
            result_target = f"{prefix}.$result"
            emit(
                {
                    "node": "copy",
                    "target": result_target,
                    "value": reference(result_source),
                },
                evaluation_site_identity=instruction_site(
                    formula,
                    "$result",
                    prefix,
                ),
            )
            return {"kind": "local", "name": result_target}

        formula_ref = cast(dict[str, Any], binding["formula"])
        formula = formulas_by_identity[cast(str, formula_ref["identity"])]
        result_source = compile_formula(
            formula,
            parameter_sources,
            f"init.{site['identity']}",
        )
        expected_steps = cast(
            int,
            cast(dict[str, Any], formula["closure"])["resource_charge"]["max_steps"],
        )
        if len(instructions) > expected_steps:
            raise ValueError("generic initialization lowering exceeds Formula charge")
        body = cast(
            dict[str, JsonValue],
            {
                "site": site,
                "target": cast(dict[str, Any], site["resolved_symbol"]),
                "inputs": [
                    {"name": name, "operand": operand}
                    for name, operand in sorted(inputs.items())
                ],
                "body": instructions,
                "result": result_source,
                "numeric_policy": cast(
                    str, cast(dict[str, Any], formula["result"])["numeric_policy"]
                ),
                "resource_bounds": {"max_steps": expected_steps},
                "refusals": cast(
                    list[str],
                    cast(dict[str, Any], formula["closure"])["refusals"],
                ),
            },
        )
        programs.append(
            {
                **body,
                "identity": content_identity(
                    domains["initialization_program"],
                    body,
                ),
            }
        )
    programs.sort(key=lambda row: cast(str, row["identity"]))
    return programs


def _value_policy_is_valid(
    declaration: dict[str, Any],
    assignment_policy: dict[str, Any],
) -> bool:
    value_policy = declaration.get("value_policy")
    if not isinstance(value_policy, dict):
        return False
    mode = _assignment_mode_for_declaration(declaration, assignment_policy)
    if mode is None:
        return False
    if mode["value_member"] == "required":
        value = value_policy.get("value")
        if (
            set(value_policy) != {"mode", "value"}
            or not isinstance(value, int)
            or isinstance(value, bool)
        ):
            return False
        domain = declaration.get("domain")
        if declaration.get("domain_kind") == "closed-interval" and (
            not isinstance(domain, dict)
            or not isinstance(domain.get("minimum"), int)
            or not isinstance(domain.get("maximum"), int)
            or value < domain["minimum"]
            or value > domain["maximum"]
        ):
            return False
        return True
    return set(value_policy) == {"mode"}


def _invalid_source_value_policy_pointer(
    source: dict[str, Any],
    language_bundle: dict[str, Any],
) -> str | None:
    lowering = _model_lowering(language_bundle)
    assignment_policy = _assignment_policy(
        lowering,
        expected_roles=set(
            cast(list[str], language_bundle["language"]["quantity"]["symbol_roles"])
        ),
    )
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    modules_member = cast(str, profile["modules_member"])
    symbols_member = cast(str, profile["symbols_member"])
    for module_index, module in enumerate(
        cast(list[dict[str, Any]], source[modules_member])
    ):
        for symbol_index, symbol in enumerate(
            cast(list[dict[str, Any]], module[symbols_member])
        ):
            if not _value_policy_is_valid(symbol, assignment_policy):
                return _pointer(
                    (
                        modules_member,
                        module_index,
                        symbols_member,
                        symbol_index,
                        "value_policy",
                    )
                )
    return None


def _formula_failure_pointer(source: dict[str, Any], message: str) -> str:
    if "binding" in message.lower() or "derived Symbol" in message:
        return "/formula_bindings"
    for module_index, module in enumerate(
        cast(list[dict[str, Any]], source.get("modules", []))
    ):
        formulas = cast(list[dict[str, Any]], module.get("formulas", []))
        if formulas:
            suffix = "/body" if "body" in message.lower() or "cycle" in message else ""
            return f"/modules/{module_index}/formulas/0{suffix}"
    return "/formula_bindings"


def _symbol_initialization_contract(
    declaration: dict[str, Any],
    assignment_policy: dict[str, Any],
    resolved_symbol: dict[str, JsonValue],
    target_identity: str,
) -> tuple[dict[str, JsonValue] | None, dict[str, JsonValue] | None]:
    value_policy = cast(dict[str, Any], declaration["value_policy"])
    mode = _assignment_mode_for_declaration(declaration, assignment_policy)
    if mode is None:
        raise ValueError("Symbol has no total assignment-policy mode")
    source = cast(str, mode["initialization_source"])
    cardinality = cast(str, mode["experiment_cardinality"])
    target: dict[str, JsonValue] | None = None
    if cardinality != "forbidden":
        target = {
            "target": resolved_symbol,
            "target_identity": target_identity,
            "owner": "experiment",
            "initialization_source": "scenario-assignment",
            "cardinality": cardinality,
            "override": cast(bool, mode["override"]),
        }
    initializer: dict[str, JsonValue] | None = None
    if source in {"model", "model-with-experiment-override"}:
        initializer = {
            "target": resolved_symbol,
            "target_identity": target_identity,
            "owner": "model",
            "initialization_source": "value-policy",
            "value": cast(int, value_policy["value"]),
        }
    return target, initializer


def _symbol_event_payload_contract(
    declaration: dict[str, Any],
    assignment_policy: dict[str, Any],
    resolved_symbol: dict[str, JsonValue],
    target_identity: str,
) -> dict[str, JsonValue] | None:
    mode = _assignment_mode_for_declaration(declaration, assignment_policy)
    if mode is None:
        raise ValueError("Symbol has no total assignment-policy mode")
    cardinality = cast(str, mode["event_payload_cardinality"])
    if cardinality == "forbidden":
        return None
    return {
        "target": resolved_symbol,
        "target_identity": target_identity,
        "owner": "experiment",
        "value_source": "event-payload",
        "cardinality": cardinality,
        "override": True,
    }


def _symbol_external_fact_contract(
    declaration: dict[str, Any],
    assignment_policy: dict[str, Any],
    resolved_symbol: dict[str, JsonValue],
    target_identity: str,
) -> dict[str, JsonValue] | None:
    mode = _assignment_mode_for_declaration(declaration, assignment_policy)
    if mode is None:
        raise ValueError("Symbol has no total assignment-policy mode")
    cardinality = cast(str, mode["external_fact_cardinality"])
    if cardinality == "forbidden":
        return None
    value_contract = (
        {
            "type_identity": cast(JsonValue, declaration["type_identity"]),
            "value_kind": "nominal-structured",
        }
        if declaration.get("value_kind") == "nominal-structured"
        else {
            member: cast(JsonValue, declaration[member])
            for member in (
                "type_identity",
                "representation",
                "kind",
                "unit",
                "domain_kind",
                "domain",
                "numeric_policy",
            )
        }
    )
    return {
        "target": resolved_symbol,
        "target_identity": target_identity,
        "owner": "external-source",
        "cardinality": cardinality,
        "value_source": "external-input-fact",
        "value_contract": value_contract,
    }


def _formula_symbol_dependencies(
    formulas: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, JsonValue]]],
    dict[tuple[str, str, str], list[dict[str, JsonValue]]],
]:
    formulas_by_identity = {
        cast(str, formula["identity"]): formula for formula in formulas
    }
    direct_by_formula: dict[str, set[tuple[str, str, str]]] = {}
    formula_calls: dict[str, set[str]] = {}
    symbols: dict[tuple[str, str, str], dict[str, JsonValue]] = {}
    for identity, formula in formulas_by_identity.items():
        direct: set[tuple[str, str, str]] = set()
        calls: set[str] = set()

        def observe_operand(operand: Any) -> None:
            if not isinstance(operand, dict) or operand.get("kind") != "symbol":
                return
            resolved = operand.get("resolved_symbol")
            if not isinstance(resolved, dict):
                return
            key = (
                cast(str, resolved["model"]),
                cast(str, resolved["module"]),
                cast(str, resolved["name"]),
            )
            direct.add(key)
            symbols[key] = cast(dict[str, JsonValue], resolved)

        body = cast(dict[str, Any], formula["body"])
        observe_operand(body.get("result"))
        for node in cast(list[dict[str, Any]], body.get("nodes", [])):
            for argument in cast(list[dict[str, Any]], node.get("arguments", [])):
                observe_operand(argument.get("operand"))
            for member in ("condition", "when_true", "when_false"):
                observe_operand(node.get(member))
            formula_ref = node.get("formula")
            if (
                node.get("node") == "formula-call"
                and isinstance(formula_ref, dict)
                and isinstance(formula_ref.get("identity"), str)
            ):
                calls.add(formula_ref["identity"])
        direct_by_formula[identity] = direct
        formula_calls[identity] = calls

    closed_formula_symbols: dict[str, set[tuple[str, str, str]]] = {}

    def close_formula(
        identity: str, visiting: frozenset[str]
    ) -> set[tuple[str, str, str]]:
        if identity in closed_formula_symbols:
            return closed_formula_symbols[identity]
        if identity in visiting or identity not in formulas_by_identity:
            raise ValueError("Formula dependency graph is cyclic or incomplete")
        result = set(direct_by_formula[identity])
        for called in formula_calls[identity]:
            result.update(close_formula(called, visiting | {identity}))
        closed_formula_symbols[identity] = result
        return result

    direct_by_site: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {}
    for binding in bindings:
        site = cast(dict[str, Any], binding["site"])
        if site.get("kind") != "derived-symbol":
            continue
        resolved_site = cast(dict[str, str], site["resolved_symbol"])
        site_key = (
            resolved_site["model"],
            resolved_site["module"],
            resolved_site["name"],
        )
        formula_ref = cast(dict[str, str], binding["formula"])
        dependencies = set(close_formula(formula_ref["identity"], frozenset()))
        for argument in cast(list[dict[str, Any]], binding["arguments"]):
            operand = cast(dict[str, Any], argument["operand"])
            if operand.get("kind") != "symbol":
                continue
            resolved = cast(dict[str, JsonValue], operand["resolved_symbol"])
            key = (
                cast(str, resolved["model"]),
                cast(str, resolved["module"]),
                cast(str, resolved["name"]),
            )
            dependencies.add(key)
            symbols[key] = resolved
        direct_by_site[site_key] = dependencies

    closed_by_site: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {}

    def close_site(
        key: tuple[str, str, str],
        visiting: frozenset[tuple[str, str, str]],
    ) -> set[tuple[str, str, str]]:
        if key in closed_by_site:
            return closed_by_site[key]
        if key in visiting:
            raise ValueError("Derived Formula binding graph is cyclic")
        result: set[tuple[str, str, str]] = set()
        for dependency in direct_by_site.get(key, set()):
            if dependency in direct_by_site:
                result.update(close_site(dependency, visiting | {key}))
            else:
                result.add(dependency)
        closed_by_site[key] = result
        return result

    derived_dependencies = {
        key: [
            symbols[dependency] for dependency in sorted(close_site(key, frozenset()))
        ]
        for key in sorted(direct_by_site)
    }
    operation_dependencies: dict[
        tuple[str, str, str],
        set[tuple[str, str, str]],
    ] = {}
    for binding in bindings:
        site = cast(dict[str, Any], binding["site"])
        if site.get("kind") != "operation-slot":
            continue
        operation = cast(dict[str, str], site["operation"])
        coordinate = (
            operation["package"],
            operation["version"],
            operation["id"],
        )
        formula_ref = cast(dict[str, str], binding["formula"])
        dependencies = operation_dependencies.setdefault(coordinate, set())
        for dependency in close_formula(formula_ref["identity"], frozenset()):
            if dependency in direct_by_site:
                dependencies.update(close_site(dependency, frozenset()))
            else:
                dependencies.add(dependency)
    return (
        derived_dependencies,
        {
            coordinate: [symbols[dependency] for dependency in sorted(dependencies)]
            for coordinate, dependencies in sorted(operation_dependencies.items())
        },
    )


def _reachable_operation_formula_dependencies(
    root: tuple[str, str, str],
    operations: dict[tuple[str, str, str], dict[str, Any]],
    dependencies: dict[
        tuple[str, str, str],
        list[dict[str, JsonValue]],
    ],
    *,
    operation_node_ids: set[str],
) -> list[dict[str, JsonValue]]:
    definitions = {
        coordinate: cast(dict[str, Any], row["definition"])
        for coordinate, row in operations.items()
    }
    reachable = closed_operation_coordinates({root}, definitions, operation_node_ids)
    symbols: dict[tuple[str, str, str], dict[str, JsonValue]] = {}
    for coordinate in reachable:
        operation_row = operations.get(coordinate)
        if operation_row is None:
            raise ValueError("Operation Formula dependency graph is incomplete")
        for symbol in dependencies.get(coordinate, []):
            key = (
                cast(str, symbol["model"]),
                cast(str, symbol["module"]),
                cast(str, symbol["name"]),
            )
            symbols[key] = symbol
    return [symbols[key] for key in sorted(symbols)]


def _resolved_entrypoints(
    checked: CheckedModel,
    declarations: list[dict[str, Any]],
    selected_semantics: dict[str, Any],
    formulas: list[dict[str, Any]] | None = None,
    formula_bindings: list[dict[str, Any]] | None = None,
) -> list[dict[str, JsonValue]]:
    """Resolve Source entrypoint bindings once; downstream consumers use only this graph."""
    lowering = _model_lowering(checked.language_bundle)
    assignment_policy = _assignment_policy(
        lowering,
        expected_roles=set(
            cast(
                list[str],
                checked.language_bundle["language"]["quantity"]["symbol_roles"],
            )
        ),
    )
    assignment_by_role = _assignment_policy_by_role(assignment_policy)
    if any(
        not _value_policy_is_valid(declaration, assignment_policy)
        for declaration in declarations
    ):
        raise ValueError("Model declarations do not close Symbol assignment policy")
    package_versions = {
        row["id"]: row["version"]
        for row in cast(list[dict[str, str]], selected_semantics["packages"])
    }
    operation_rows = cast(list[dict[str, Any]], selected_semantics["operations"])
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
            row["definition"]["id"],
        ): row
        for row in operation_rows
    }
    declarations_by_source = {
        (
            cast(dict[str, str], declaration["resolved_symbol"])["module"],
            cast(dict[str, str], declaration["resolved_symbol"])["name"],
        ): declaration
        for declaration in declarations
    }
    formula_dependencies, operation_formula_dependencies = _formula_symbol_dependencies(
        formulas or [],
        formula_bindings or [],
    )
    domains = cast(
        dict[str, str],
        checked.kernel["meta_format"]["runtime_program"]["invocation_contract"][
            "identity_domains"
        ],
    )
    structured_authority = language_structured_value_index(
        checked.language_bundle, kernel=checked.kernel
    )
    structured_resource_limit = cast(
        int, checked.language_bundle["resources"]["max_rule_match_steps"]
    )
    entrypoints: list[dict[str, JsonValue]] = []
    seen_entrypoints: set[str] = set()
    for entrypoint_index, source_entrypoint in enumerate(
        cast(list[dict[str, Any]], checked.source["entrypoints"])
    ):
        pointer = f"/entrypoints/{entrypoint_index}"
        entrypoint_id = cast(str, source_entrypoint["id"])
        if entrypoint_id in seen_entrypoints:
            raise _EntrypointBindingError(
                f"{pointer}/id",
                f"duplicate Model entrypoint: {entrypoint_id}",
            )
        seen_entrypoints.add(entrypoint_id)
        operation_ref = cast(dict[str, str], source_entrypoint["operation"])
        operation_row = operations.get(
            (
                operation_ref["package"],
                operation_ref["version"],
                operation_ref["id"],
            )
        )
        if operation_row is None:
            if operation_ref["package"] not in package_versions:
                member = "package"
            elif package_versions[operation_ref["package"]] != operation_ref["version"]:
                member = "version"
            else:
                member = "id"
            raise _EntrypointBindingError(
                f"{pointer}/operation/{member}",
                f"entrypoint Operation is not selected: {entrypoint_id}",
            )
        operation = cast(dict[str, Any], operation_row["definition"])
        exact_operation = _exact_operation_coordinate(operation_row, package_versions)
        formal_ports = cast(list[dict[str, Any]], operation["inputs"])
        source_arguments = cast(list[dict[str, Any]], source_entrypoint["arguments"])
        argument_names = [row["port"] for row in source_arguments]
        formal_names = [row["id"] for row in formal_ports]
        if argument_names != formal_names:
            if len(source_arguments) < len(formal_ports):
                argument_pointer = f"{pointer}/arguments"
            else:
                mismatch = next(
                    (
                        index
                        for index, (actual, expected) in enumerate(
                            zip(argument_names, formal_names, strict=False)
                        )
                        if actual != expected
                    ),
                    len(formal_names),
                )
                argument_pointer = f"{pointer}/arguments/{mismatch}/port"
            raise _EntrypointBindingError(
                argument_pointer,
                f"entrypoint arguments do not exactly close formal ports: {entrypoint_id}",
            )
        resolved_arguments: list[dict[str, JsonValue]] = []
        aliases: dict[str, list[tuple[str, str]]] = {}
        scenario_targets: dict[str, dict[str, JsonValue]] = {}
        event_payload_targets: dict[str, dict[str, JsonValue]] = {}
        event_reference_targets: dict[str, dict[str, JsonValue]] = {}
        external_fact_targets: dict[str, dict[str, JsonValue]] = {}
        initializers: dict[str, dict[str, JsonValue]] = {}

        def record_formula_dependency(
            dependency_symbol: dict[str, JsonValue],
        ) -> None:
            dependency_key = (
                cast(str, dependency_symbol["module"]),
                cast(str, dependency_symbol["name"]),
            )
            dependency = declarations_by_source.get(dependency_key)
            if dependency is None:
                raise _EntrypointBindingError(
                    f"{pointer}/operation",
                    "entrypoint Formula Symbol dependency is unresolved",
                )
            dependency_body = cast(
                dict[str, JsonValue],
                {
                    "kind": "symbol",
                    "symbol": dependency_symbol,
                },
            )
            dependency_identity = content_identity(
                domains["actual_operand"],
                dependency_body,
            )
            dependency_target, dependency_initializer = _symbol_initialization_contract(
                dependency,
                assignment_policy,
                dependency_symbol,
                dependency_identity,
            )
            if (
                dependency_target is None
                and dependency_initializer is None
                and dependency.get("role") != "derived"
            ):
                raise _EntrypointBindingError(
                    f"{pointer}/operation",
                    "entrypoint Formula Symbol dependency is absent from the "
                    "pre-event Snapshot",
                )
            if dependency_target is not None:
                previous_target = scenario_targets.get(dependency_identity)
                if previous_target is not None and previous_target != dependency_target:
                    raise _EntrypointBindingError(
                        f"{pointer}/operation",
                        "one Formula dependency derived conflicting assignment "
                        "contracts",
                    )
                scenario_targets[dependency_identity] = dependency_target
            event_payload_target = _symbol_event_payload_contract(
                dependency,
                assignment_policy,
                dependency_symbol,
                dependency_identity,
            )
            if event_payload_target is not None:
                previous_payload_target = event_payload_targets.get(dependency_identity)
                if (
                    previous_payload_target is not None
                    and previous_payload_target != event_payload_target
                ):
                    raise _EntrypointBindingError(
                        f"{pointer}/operation",
                        "one Formula dependency derived conflicting Event-local "
                        "payload contracts",
                    )
                event_payload_targets[dependency_identity] = event_payload_target
            external_fact_target = _symbol_external_fact_contract(
                dependency,
                assignment_policy,
                dependency_symbol,
                dependency_identity,
            )
            if external_fact_target is not None:
                previous_external_target = external_fact_targets.get(
                    dependency_identity
                )
                if (
                    previous_external_target is not None
                    and previous_external_target != external_fact_target
                ):
                    raise _EntrypointBindingError(
                        f"{pointer}/operation",
                        "one Formula dependency derived conflicting external-fact "
                        "contracts",
                    )
                external_fact_targets[dependency_identity] = external_fact_target
            if dependency_initializer is not None:
                previous_initializer = initializers.get(dependency_identity)
                if (
                    previous_initializer is not None
                    and previous_initializer != dependency_initializer
                ):
                    raise _EntrypointBindingError(
                        f"{pointer}/operation",
                        "one Formula dependency derived conflicting initializers",
                    )
                initializers[dependency_identity] = dependency_initializer

        for argument_index, (formal, source_argument) in enumerate(
            zip(formal_ports, source_arguments, strict=True)
        ):
            operand_pointer = f"{pointer}/arguments/{argument_index}/operand"
            formal_identity = content_identity(
                domains["formal_port"],
                cast(
                    JsonValue,
                    {"operation": exact_operation, "name": formal["id"]},
                ),
            )
            source_operand = cast(dict[str, Any], source_argument["operand"])
            if source_operand["kind"] == "symbol":
                declaration = declarations_by_source.get(
                    (source_operand["module"], source_operand["symbol"])
                )
                if declaration is None:
                    raise _EntrypointBindingError(
                        operand_pointer,
                        f"entrypoint Symbol operand is unresolved: {entrypoint_id}",
                    )
                if not _value_contract_matches(declaration, formal):
                    raise _EntrypointBindingError(
                        operand_pointer,
                        f"entrypoint Symbol is incompatible with port {formal['id']}",
                    )
                access = cast(str, formal["access"])
                role = cast(str, declaration["role"])
                if access not in assignment_by_role[role]["entrypoint_operand_access"]:
                    raise _EntrypointBindingError(
                        operand_pointer,
                        "entrypoint Symbol role is incompatible with "
                        f"{access} port {formal['id']}",
                    )
                resolved_symbol = cast(
                    dict[str, JsonValue], declaration["resolved_symbol"]
                )
                operand_body = cast(
                    dict[str, JsonValue],
                    {"kind": "symbol", "symbol": resolved_symbol},
                )
                operand_identity = content_identity(
                    domains["actual_operand"], cast(JsonValue, operand_body)
                )
                resolved_operand = {
                    **operand_body,
                    "identity": operand_identity,
                }
                aliases.setdefault(operand_identity, []).append(
                    (cast(str, formal["id"]), access)
                )
                target, initializer = _symbol_initialization_contract(
                    declaration,
                    assignment_policy,
                    resolved_symbol,
                    operand_identity,
                )
                if target is not None:
                    previous = scenario_targets.get(operand_identity)
                    if previous is not None and previous != target:
                        raise _EntrypointBindingError(
                            operand_pointer,
                            "one actual target derived conflicting assignment "
                            "contracts",
                        )
                    scenario_targets[operand_identity] = target
                event_payload_target = _symbol_event_payload_contract(
                    declaration,
                    assignment_policy,
                    resolved_symbol,
                    operand_identity,
                )
                if event_payload_target is not None:
                    previous_payload_target = event_payload_targets.get(
                        operand_identity
                    )
                    if (
                        previous_payload_target is not None
                        and previous_payload_target != event_payload_target
                    ):
                        raise _EntrypointBindingError(
                            operand_pointer,
                            "one actual target derived conflicting Event-local "
                            "payload contracts",
                        )
                    event_payload_targets[operand_identity] = event_payload_target
                external_fact_target = _symbol_external_fact_contract(
                    declaration,
                    assignment_policy,
                    resolved_symbol,
                    operand_identity,
                )
                if external_fact_target is not None:
                    previous_external_target = external_fact_targets.get(
                        operand_identity
                    )
                    if (
                        previous_external_target is not None
                        and previous_external_target != external_fact_target
                    ):
                        raise _EntrypointBindingError(
                            operand_pointer,
                            "one actual target derived conflicting external-fact "
                            "contracts",
                        )
                    external_fact_targets[operand_identity] = external_fact_target
                if initializer is not None:
                    previous_initializer = initializers.get(operand_identity)
                    if (
                        previous_initializer is not None
                        and previous_initializer != initializer
                    ):
                        raise _EntrypointBindingError(
                            operand_pointer,
                            "one actual target derived conflicting initializers",
                        )
                    initializers[operand_identity] = initializer
                if role == "derived":
                    resolved_key = (
                        cast(str, resolved_symbol["model"]),
                        cast(str, resolved_symbol["module"]),
                        cast(str, resolved_symbol["name"]),
                    )
                    if resolved_key not in formula_dependencies:
                        raise _EntrypointBindingError(
                            operand_pointer,
                            "entrypoint derived Symbol has no Formula value producer",
                        )
                    for dependency_symbol in formula_dependencies.get(resolved_key, []):
                        record_formula_dependency(dependency_symbol)
            elif source_operand["kind"] == "literal":
                if formal["access"] != "read":
                    raise _EntrypointBindingError(
                        operand_pointer,
                        "literal operand cannot bind a writable port",
                    )
                value = source_operand["value"]
                if isinstance(value, dict):
                    try:
                        value = admit_typed_value(
                            value,
                            authority=structured_authority,
                            resource_limit=structured_resource_limit,
                        )
                    except StructuredValueFault as fault:
                        raise _EntrypointBindingError(
                            f"{operand_pointer}/value{fault.pointer}",
                            f"structured literal was refused: {fault.code}",
                        ) from fault
                context_type = _literal_context_contract(
                    value,
                    formal,
                    checked.kernel,
                    selected_semantics,
                )
                if context_type is None:
                    raise _EntrypointBindingError(
                        operand_pointer,
                        "literal operand is incompatible with the formal value contract",
                    )
                operand_body = {
                    "kind": "literal",
                    "value": value,
                    "context_type": context_type,
                }
                resolved_operand = {
                    **operand_body,
                    "identity": content_identity(
                        domains["actual_operand"], cast(JsonValue, operand_body)
                    ),
                }
            elif source_operand["kind"] == "event-reference":
                event_reference = _resolved_event_reference_operand(
                    source_operand,
                    formal,
                    checked.kernel,
                    domains,
                )
                if event_reference is None:
                    raise _EntrypointBindingError(
                        operand_pointer,
                        "Event reference operand is incompatible with the formal "
                        "value contract",
                    )
                resolved_operand, operand_identity, reference_contract = event_reference
                aliases.setdefault(operand_identity, []).append(
                    (cast(str, formal["id"]), cast(str, formal["access"]))
                )
                name = cast(str, reference_contract["name"])
                previous_reference = event_reference_targets.get(name)
                if (
                    previous_reference is not None
                    and previous_reference != reference_contract
                ):
                    raise _EntrypointBindingError(
                        operand_pointer,
                        "one Event reference name derived conflicting contracts",
                    )
                event_reference_targets[name] = reference_contract
            else:
                raise _EntrypointBindingError(
                    operand_pointer,
                    "entrypoint operand kind is not admitted",
                )
            resolved_arguments.append(
                cast(
                    dict[str, JsonValue],
                    {
                        "port": {
                            "identity": formal_identity,
                            "operation": exact_operation,
                            "name": formal["id"],
                        },
                        "operand": resolved_operand,
                        "access": formal["access"],
                    },
                )
            )
        for dependency_symbol in _reachable_operation_formula_dependencies(
            (
                exact_operation["package"],
                exact_operation["version"],
                exact_operation["id"],
            ),
            operations,
            operation_formula_dependencies,
            operation_node_ids=_operation_reference_node_ids(checked.kernel),
        ):
            record_formula_dependency(dependency_symbol)
        try:
            alias_rows = _resolved_alias_rows(operation, aliases)
        except ValueError as err:
            raise _EntrypointBindingError(
                f"{pointer}/arguments",
                str(err),
            ) from err
        source_result = cast(dict[str, Any], source_entrypoint["result"])
        if source_result["kind"] == "discard":
            if operation["result"]["discardable"] is not True:
                raise _EntrypointBindingError(
                    f"{pointer}/result",
                    "entrypoint cannot discard a required Operation result",
                )
            result_body = cast(dict[str, JsonValue], {"kind": "discard"})
            resolved_result: dict[str, JsonValue] = {
                **result_body,
                "identity": content_identity(domains["result"], result_body),
            }
        else:
            result_declaration = declarations_by_source.get(
                (source_result["module"], source_result["symbol"])
            )
            if (
                result_declaration is None
                or assignment_by_role[cast(str, result_declaration.get("role"))][
                    "entrypoint_result"
                ]
                is not True
                or not _value_contract_matches(result_declaration, operation["result"])
            ):
                raise _EntrypointBindingError(
                    f"{pointer}/result",
                    "entrypoint result must bind one compatible output Symbol",
                )
            result_symbol = cast(
                dict[str, JsonValue], result_declaration["resolved_symbol"]
            )
            result_body = cast(
                dict[str, JsonValue],
                {"kind": "symbol", "symbol": result_symbol},
            )
            resolved_result = {
                **result_body,
                "identity": content_identity(domains["result"], result_body),
            }
        entrypoint_body = cast(
            dict[str, JsonValue],
            {
                "id": entrypoint_id,
                "operation": exact_operation,
                "arguments": resolved_arguments,
                "aliases": alias_rows,
                "result": resolved_result,
                "effects": operation["effects"],
                "refusals": operation["refusals"],
                "resource_bounds": operation["resource_bounds"],
                "scenario_input_contract": {
                    "initializers": sorted(
                        initializers.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    ),
                    "targets": sorted(
                        scenario_targets.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    ),
                },
                "event_local_payload_contract": {
                    "targets": sorted(
                        event_payload_targets.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    ),
                    "event_references": sorted(
                        event_reference_targets.values(),
                        key=lambda row: cast(str, row["name"]),
                    ),
                },
                "external_fact_contract": {
                    "targets": sorted(
                        external_fact_targets.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    )
                },
            },
        )
        entrypoints.append(
            {
                **entrypoint_body,
                "identity": content_identity(domains["entrypoint"], entrypoint_body),
            }
        )
    return sorted(entrypoints, key=lambda row: cast(str, row["id"]))


def _resolved_event_reference_operand(
    operand: dict[str, Any],
    formal: dict[str, Any],
    kernel: dict[str, Any],
    domains: dict[str, str],
) -> tuple[dict[str, JsonValue], str, dict[str, JsonValue]] | None:
    name = operand.get("name")
    event_reference_contract = fixed_operation_value_contract(
        kernel, "kernel-event-reference"
    )
    if (
        event_reference_contract is None
        or formal.get("access") != "read"
        or not isinstance(name, str)
        or not name
        or not operation_value_contract_matches(event_reference_contract, formal)
    ):
        return None
    operand_body = cast(
        dict[str, JsonValue],
        {
            "kind": "event-reference",
            "name": name,
        },
    )
    operand_identity = content_identity(
        domains["actual_operand"], cast(JsonValue, operand_body)
    )
    return (
        {**operand_body, "identity": operand_identity},
        operand_identity,
        {
            "name": name,
            "operand_identity": operand_identity,
            "cardinality": "required",
        },
    )


def _resolved_alias_rows(
    operation: dict[str, Any],
    aliases: dict[str, list[tuple[str, str]]],
) -> list[dict[str, JsonValue]]:
    policy = cast(dict[str, Any], operation["alias_policy"])
    writable_groups = cast(list[dict[str, Any]], policy["writable_groups"])
    groups = {
        frozenset(cast(list[str], group["ports"])): cast(str, group["semantics"])
        for group in writable_groups
    }
    rows: list[dict[str, JsonValue]] = []
    for actual_identity, uses in aliases.items():
        if len(uses) < 2:
            continue
        ports = [name for name, _access in uses]
        if all(access == "read" for _name, access in uses):
            alias_policy = cast(str, policy["read_only"])
        else:
            alias_policy = groups.get(frozenset(ports), "")
            if not alias_policy:
                raise ValueError("Operation does not admit this writable alias set")
        rows.append(
            {
                "actual_operand_identity": actual_identity,
                "ports": cast(JsonValue, ports),
                "policy": alias_policy,
            }
        )
    return rows


def _composition_policy(lowering: dict[str, Any]) -> dict[str, Any]:
    policy = lowering.get("composition_policy")
    if not isinstance(policy, dict):
        raise ValueError("the admitted lowering has no closed composition policy")
    return policy


def _resolved_call_sites(
    kernel: dict[str, Any],
    selected_semantics: dict[str, Any],
    composition_policy: dict[str, Any],
) -> list[dict[str, JsonValue]]:
    """Resolve LDB-authored nested calls without flattening caller/callee names."""
    effect_policy = cast(dict[str, str], composition_policy["effects"])
    refusal_policy = cast(dict[str, str], composition_policy["refusals"])
    resource_policy = cast(dict[str, str], composition_policy["resources"])
    package_versions = {
        row["id"]: row["version"]
        for row in cast(list[dict[str, str]], selected_semantics["packages"])
    }
    operation_rows = cast(list[dict[str, Any]], selected_semantics["operations"])
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
            row["definition"]["id"],
        ): row
        for row in operation_rows
    }
    domains = cast(
        dict[str, str],
        kernel["meta_format"]["runtime_program"]["invocation_contract"][
            "identity_domains"
        ],
    )
    resolved_rows: list[dict[str, JsonValue]] = []
    operation_definitions = {
        coordinate: cast(dict[str, Any], row["definition"])
        for coordinate, row in operations.items()
    }
    runtime_nodes = cast(
        list[dict[str, Any]],
        kernel["meta_format"]["runtime_program"]["nodes"],
    )
    operation_node_ids = {
        cast(str, node["id"])
        for node in runtime_nodes
        if node["semantics"]["operator"] in {"invoke-operation", "schedule-operation"}
    }
    invocation_node_ids = {
        cast(str, node["id"])
        for node in runtime_nodes
        if node["semantics"]["operator"] == "invoke-operation"
    }
    closure_cache: dict[
        tuple[str, str, str], tuple[frozenset[str], frozenset[str], int]
    ] = {}

    def operation_closure(
        operation_row: dict[str, Any],
        stack: tuple[tuple[str, str, str], ...],
    ) -> tuple[frozenset[str], frozenset[str], int]:
        parent_ref = _exact_operation_coordinate(operation_row, package_versions)
        parent_key = (
            parent_ref["package"],
            parent_ref["version"],
            parent_ref["id"],
        )
        if parent_key in stack:
            raise ValueError("Operation call graph contains a cycle")
        if parent_key in closure_cache:
            return closure_cache[parent_key]
        operation = cast(dict[str, Any], operation_row["definition"])
        projection = project_operation_program(
            parent_key,
            operation_definitions,
            operation_node_ids=operation_node_ids,
            invocation_node_ids=invocation_node_ids,
        )
        parent_ports = {
            row["id"]: row for row in cast(list[dict[str, Any]], operation["inputs"])
        }
        parent_outcomes = {
            row["id"]
            for row in cast(list[dict[str, Any]], operation.get("outcomes", []))
        }
        locals_: dict[str, dict[str, Any]] = {}
        seen_sites: set[str] = set()
        for order, instruction in enumerate(
            cast(list[dict[str, Any]], operation["body"])
        ):
            if instruction["node"] != "invoke":
                continue
            site = cast(str, instruction["site"])
            if site in seen_sites:
                raise ValueError("Operation repeats a nested call-site id")
            seen_sites.add(site)
            child_ref = cast(dict[str, str], instruction["operation"])
            child_row = operations.get(
                (child_ref["package"], child_ref["version"], child_ref["id"])
            )
            if child_row is None:
                raise ValueError("nested Operation is not in the selected closure")
            exact_child = _exact_operation_coordinate(child_row, package_versions)
            child = cast(dict[str, Any], child_row["definition"])
            child_ports = cast(list[dict[str, Any]], child["inputs"])
            authored_arguments = cast(list[dict[str, Any]], instruction["arguments"])
            if [row["port"] for row in authored_arguments] != [
                row["id"] for row in child_ports
            ]:
                raise ValueError("nested call does not exactly close formal ports")
            aliases: dict[str, list[tuple[str, str]]] = {}
            arguments: list[dict[str, JsonValue]] = []
            for formal, authored in zip(child_ports, authored_arguments, strict=True):
                formal_body = cast(
                    JsonValue,
                    {"operation": exact_child, "name": formal["id"]},
                )
                operand = cast(dict[str, Any], authored["operand"])
                if operand["kind"] == "port":
                    parent_port = parent_ports.get(operand["port"])
                    if (
                        parent_port is None
                        or not operation_value_contract_matches(parent_port, formal)
                        or (
                            formal["access"] in {"read-write", "write"}
                            and parent_port["access"] not in {"read-write", "write"}
                        )
                    ):
                        raise ValueError("nested call port operand is incompatible")
                    operand_body = cast(
                        dict[str, JsonValue],
                        {
                            "kind": "port",
                            "parent_operation": parent_ref,
                            "port": operand["port"],
                        },
                    )
                    resolved_operand = cast(
                        dict[str, JsonValue],
                        {
                            "kind": "port",
                            "port": operand["port"],
                            "identity": content_identity(
                                domains["actual_operand"],
                                cast(JsonValue, operand_body),
                            ),
                        },
                    )
                elif operand["kind"] == "local":
                    local_contract = locals_.get(operand["local"])
                    if (
                        local_contract is None
                        or formal["access"] != "read"
                        or not operation_value_contract_matches(local_contract, formal)
                    ):
                        raise ValueError("nested call local operand is incompatible")
                    operand_body = cast(
                        dict[str, JsonValue],
                        {
                            "kind": "local",
                            "parent_operation": parent_ref,
                            "local": operand["local"],
                        },
                    )
                    resolved_operand = cast(
                        dict[str, JsonValue],
                        {
                            "kind": "local",
                            "local": operand["local"],
                            "identity": content_identity(
                                domains["actual_operand"],
                                cast(JsonValue, operand_body),
                            ),
                        },
                    )
                elif operand["kind"] == "literal":
                    value = operand.get("literal")
                    context_type = _literal_context_contract(
                        value,
                        formal,
                        kernel,
                        selected_semantics,
                    )
                    if formal["access"] != "read" or context_type is None:
                        raise ValueError("nested call literal operand is incompatible")
                    operand_body = cast(
                        dict[str, JsonValue],
                        {
                            "kind": "literal",
                            "parent_operation": parent_ref,
                            "value": value,
                            "context_type": context_type,
                        },
                    )
                    resolved_operand = cast(
                        dict[str, JsonValue],
                        {
                            "kind": "literal",
                            "value": value,
                            "context_type": context_type,
                            "identity": content_identity(
                                domains["actual_operand"],
                                cast(JsonValue, operand_body),
                            ),
                        },
                    )
                else:
                    raise ValueError("nested call operand kind is not admitted")
                identity = cast(str, resolved_operand["identity"])
                aliases.setdefault(identity, []).append(
                    (cast(str, formal["id"]), cast(str, formal["access"]))
                )
                arguments.append(
                    cast(
                        dict[str, JsonValue],
                        {
                            "port": {
                                "identity": content_identity(
                                    domains["formal_port"], formal_body
                                ),
                                "operation": exact_child,
                                "name": formal["id"],
                            },
                            "operand": resolved_operand,
                            "access": formal["access"],
                        },
                    )
                )
            alias_rows = _resolved_alias_rows(child, aliases)
            authored_result = cast(dict[str, Any], instruction["result"])
            if authored_result["kind"] == "discard":
                if child["result"]["discardable"] is not True:
                    raise ValueError("nested call discards a required result")
            elif authored_result["kind"] == "local":
                name = cast(str, authored_result["name"])
                if name in locals_:
                    raise ValueError("nested call repeats a caller local result")
                locals_[name] = cast(dict[str, Any], child["result"])
            elif authored_result["kind"] == "operation-result":
                if not operation_value_contract_matches(
                    cast(dict[str, Any], child["result"]),
                    cast(dict[str, Any], operation["result"]),
                ):
                    raise ValueError("nested result is incompatible with caller result")
            else:
                raise ValueError("nested call result binding is not admitted")
            result_body = cast(
                JsonValue,
                {
                    "parent_operation": parent_ref,
                    "site": site,
                    "operation": exact_child,
                    "binding": authored_result,
                },
            )
            result = {
                "identity": content_identity(domains["result"], result_body),
                "binding": authored_result,
            }
            child_outcome_ids = [
                row["id"] for row in cast(list[dict[str, Any]], child["outcomes"])
            ]
            authored_outcomes = cast(list[dict[str, Any]], instruction["outcomes"])
            if [row["outcome"] for row in authored_outcomes] != child_outcome_ids:
                raise ValueError("nested outcome mapping is not exhaustive")
            outcomes: list[dict[str, JsonValue]] = []
            for mapping in authored_outcomes:
                action = cast(dict[str, Any], mapping["action"])
                if (
                    action["kind"] == "propagate"
                    and action.get("outcome") not in parent_outcomes
                ):
                    raise ValueError("nested outcome propagates an unknown outcome")
                outcome_body = cast(
                    JsonValue,
                    {
                        "parent_operation": parent_ref,
                        "site": site,
                        "operation": exact_child,
                        "outcome": mapping["outcome"],
                        "action": action,
                    },
                )
                outcomes.append(
                    {
                        "identity": content_identity(domains["outcome"], outcome_body),
                        "outcome": mapping["outcome"],
                        "action": action,
                    }
                )
            child_effects, child_refusals, child_charge = operation_closure(
                child_row, (*stack, parent_key)
            )
            if effect_policy["containment"] == (
                "callee-subset-of-caller-declaration"
            ) and not child_effects <= set(cast(list[str], operation["effects"])):
                raise ValueError(
                    "nested Operation effect closure exceeds caller declaration"
                )
            if refusal_policy["containment"] == (
                "callee-subset-of-caller-declaration"
            ) and not child_refusals <= set(cast(list[str], operation["refusals"])):
                raise ValueError(
                    "nested Operation refusal closure exceeds caller declaration"
                )
            call_body = cast(
                dict[str, JsonValue],
                {
                    "parent_operation": parent_ref,
                    "site": site,
                    "order": order,
                    "operation": exact_child,
                    "arguments": arguments,
                    "result": result,
                    "outcomes": outcomes,
                    "aliases": alias_rows,
                    "closure": {
                        "effects": sorted(child_effects),
                        "refusals": sorted(child_refusals),
                        "resource_charge": 1 + child_charge,
                    },
                },
            )
            resolved_rows.append(
                {
                    **call_body,
                    "identity": content_identity(domains["call_site"], call_body),
                }
            )
        if (
            resource_policy["containment"] == "transitive-charge-within-caller-bound"
            and projection.resource_charge > operation["resource_bounds"]["max_steps"]
        ):
            raise ValueError("Operation transitive resource charge exceeds its bound")
        closure_cache[parent_key] = (
            projection.effects,
            projection.refusals,
            projection.resource_charge,
        )
        return closure_cache[parent_key]

    for operation_row in sorted(
        operation_rows,
        key=lambda row: (
            cast(str, row["package"]),
            cast(str, row["definition"]["id"]),
        ),
    ):
        operation_closure(operation_row, ())
    return sorted(
        resolved_rows,
        key=lambda row: (
            cast(dict[str, str], row["parent_operation"])["package"],
            cast(dict[str, str], row["parent_operation"])["id"],
            cast(int, row["order"]),
        ),
    )


def _package_lock(checked: CheckedModel) -> dict[str, JsonValue]:
    language = _language(checked.language_bundle)
    lowering = _model_lowering(checked.language_bundle)
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    available = {
        (item["id"], item["version"]): item
        for item in cast(list[dict[str, Any]], language["packages"])
    }
    requirements = sorted(
        [
            {
                "id": item[requirement_package_member],
                "version": item[requirement_version_member],
            }
            for item in cast(list[dict[str, str]], checked.source[requirements_member])
        ],
        key=lambda item: (item["id"], item["version"]),
    )
    selected: dict[str, dict[str, Any]] = {}
    pending = list(requirements)
    dependency_edges: list[dict[str, JsonValue]] = []
    while pending:
        requirement = pending.pop(0)
        package = available.get((requirement["id"], requirement["version"]))
        if package is None:
            raise ValueError("an admitted source requirement has no exact package")
        previous = selected.get(package["id"])
        if previous is not None:
            if previous["semantic_identity"] != package["semantic_identity"]:
                raise ValueError("one package id resolved to conflicting releases")
            continue
        selected[package["id"]] = package
        for dependency_constraint in sorted(
            package["dependencies"]["required"],
            key=lambda item: (item["id"], item["version"]),
        ):
            dependency = available.get(
                (
                    dependency_constraint["id"],
                    dependency_constraint["version"],
                )
            )
            if dependency is None:
                raise ValueError("required dependency coordinate is unavailable")
            dependency_edges.append(
                {
                    "from_package": package["id"],
                    "kind": "required",
                    "to_package": dependency["id"],
                    "to_version": dependency["version"],
                }
            )
            pending.append({"id": dependency["id"], "version": dependency["version"]})

    selected_packages = [selected[name] for name in sorted(selected)]

    def package_definitions(package: dict[str, Any], authority_path: str) -> list[Any]:
        matches = [
            entry["definitions"]
            for entry in cast(list[dict[str, Any]], package["semantic_closure"])
            if entry["authority_path"] == authority_path
        ]
        if len(matches) != 1 or not isinstance(matches[0], list):
            raise ValueError(f"package semantic closure is missing {authority_path}")
        return cast(list[Any], matches[0])

    def runtime_semantic_closure(
        package: dict[str, Any],
    ) -> list[dict[str, JsonValue]]:
        runtime_paths = set(cast(list[str], package["runtime_semantic_paths"]))
        return [
            cast(dict[str, JsonValue], entry)
            for entry in cast(list[dict[str, Any]], package["semantic_closure"])
            if entry["authority_path"] in runtime_paths
        ]

    providers: dict[str, str] = {}
    for package in selected_packages:
        for capability in package["capabilities"]["provided"]:
            if capability in providers:
                raise ValueError("selected capability has multiple providers")
            providers[capability] = package["id"]
    for package in selected_packages:
        for capability in package["capabilities"]["required"]:
            if capability not in providers:
                raise ValueError("selected capability has no provider")

    def exported(collection: str) -> list[dict[str, JsonValue]]:
        rows: list[dict[str, JsonValue]] = []
        for package in selected_packages:
            definitions = {
                item["id"]: item
                for item in cast(
                    list[dict[str, Any]],
                    package_definitions(package, f"language.{collection}"),
                )
            }
            for identity in package["exports"][collection]:
                rows.append(
                    {
                        "definition": cast(JsonValue, definitions[identity]),
                        "package": package["id"],
                    }
                )
        return sorted(
            rows, key=lambda item: cast(dict[str, Any], item["definition"])["id"]
        )

    numeric_definitions = {
        item["id"]: item
        for package in selected_packages
        for item in cast(
            list[dict[str, Any]],
            package_definitions(package, "language.quantity.numeric_policies"),
        )
    }
    runtime_definitions = {
        item["id"]: item
        for package in selected_packages
        for item in cast(
            list[dict[str, Any]],
            package_definitions(package, "language.runtime_profiles"),
        )
    }
    numeric_profiles = sorted(
        {
            profile_id
            for package in selected_packages
            for profile_id in package["profiles"]["numeric"]
        }
    )
    runtime_profiles = sorted(
        {
            profile_id
            for package in selected_packages
            for profile_id in package["profiles"]["runtime"]
        }
    )
    selected_diagnostics = sorted(
        {
            code
            for package in selected_packages
            for code in package["exports"]["diagnostics"]
        }
    )
    selected_reasons = sorted(
        [
            reason
            for package in selected_packages
            for reason in cast(
                list[dict[str, JsonValue]],
                package_definitions(package, "language.reasons"),
            )
            if reason["diagnostic"] in selected_diagnostics
        ],
        key=lambda item: cast(str, item["id"]),
    )
    dependency_edges.sort(
        key=lambda edge: (
            cast(str, edge["from_package"]),
            cast(str, edge["to_package"]),
            cast(str, edge["to_version"]),
        )
    )
    selected_types: list[dict[str, JsonValue]] = [
        {**cast(dict[str, JsonValue], exported_type), "package": package["id"]}
        for package in selected_packages
        for exported_type in package["exports"]["types"]
    ]
    selected_types.sort(key=lambda item: cast(str, item["id"]))
    body = cast(
        dict[str, JsonValue],
        {
            "resolution_profile": cast(JsonValue, profile),
            "root_requirements": cast(JsonValue, requirements),
            "packages": [
                {
                    "id": package["id"],
                    "version": package["version"],
                    "content_identity": package["content_identity"],
                    "semantic_identity": package["semantic_identity"],
                }
                for package in selected_packages
            ],
            "package_semantic_closures": [
                {
                    "package": package["id"],
                    "semantic_identity": package["semantic_identity"],
                    "definitions": runtime_semantic_closure(package),
                }
                for package in selected_packages
            ],
            "dependency_edges": cast(JsonValue, dependency_edges),
            "capability_bindings": [
                {"capability": capability, "provider_package": providers[capability]}
                for capability in sorted(providers)
            ],
            "types": cast(JsonValue, selected_types),
            "components": cast(JsonValue, exported("components")),
            "conversions": cast(JsonValue, exported("conversions")),
            "operations": cast(JsonValue, exported("operations")),
            "numeric_profiles": cast(
                JsonValue, [numeric_definitions[name] for name in numeric_profiles]
            ),
            "runtime_profiles": cast(
                JsonValue, [runtime_definitions[name] for name in runtime_profiles]
            ),
            "diagnostics": selected_diagnostics,
            "diagnostic_reasons": cast(JsonValue, selected_reasons),
            "language_rules": sorted(
                {
                    rule
                    for package in selected_packages
                    for rule in package["exports"]["language_rules"]
                }
            ),
        },
    )
    semantic_projection: dict[str, JsonValue] = {
        "packages": [
            {
                "id": package["id"],
                "version": package["version"],
                "semantic_identity": package["semantic_identity"],
            }
            for package in selected_packages
        ],
        "package_semantic_closures": cast(JsonValue, body["package_semantic_closures"]),
        "capability_bindings": cast(JsonValue, body["capability_bindings"]),
        "types": cast(JsonValue, body["types"]),
        "components": cast(JsonValue, body["components"]),
        "conversions": cast(JsonValue, body["conversions"]),
        "operations": cast(JsonValue, body["operations"]),
        "numeric_profiles": cast(JsonValue, body["numeric_profiles"]),
        "runtime_profiles": cast(JsonValue, body["runtime_profiles"]),
    }
    body["selected_semantics"] = cast(JsonValue, semantic_projection)
    body["semantic_identity"] = content_identity(
        "package-lock-selected-semantics-v2",
        cast(JsonValue, semantic_projection),
    )
    return _identified_artifact(checked.language_bundle, "package-lock", body)


def _runtime_projection(
    lock: dict[str, Any],
    declarations: list[dict[str, Any]],
    lowering: dict[str, Any],
    budget: _RuntimeProjectionBudget,
) -> dict[str, Any]:
    """Project only declaration-reachable runtime semantics from a Package Lock."""
    profile = cast(dict[str, Any], lowering["runtime_projection"])

    def path_value(root: Any, path: list[str]) -> Any:
        value = root
        for segment in path:
            if not isinstance(value, dict) or segment not in value:
                raise ValueError(
                    "runtime projection path is outside its admitted value"
                )
            value = value[segment]
        return value

    catalogs: dict[str, list[dict[str, Any]]] = {}
    for collection in cast(list[dict[str, Any]], profile["collections"]):
        source = cast(dict[str, Any], collection["source"])
        rows: list[dict[str, Any]] = []
        if source["kind"] == "lock-member":
            values = lock[source["member"]]
            if not isinstance(values, list):
                raise ValueError("runtime projection lock member is not a list")
            for value in values:
                budget.consume()
                rows.append(
                    {
                        "package": path_value(value, source["package_path"]),
                        "authority_path": None,
                        "value": value,
                    }
                )
        elif source["kind"] == "semantic-closure":
            for closure in cast(
                list[dict[str, Any]], lock["package_semantic_closures"]
            ):
                entries = [
                    entry
                    for entry in cast(list[dict[str, Any]], closure["definitions"])
                    if entry["authority_path"] == source["authority_path"]
                ]
                if len(entries) > 1:
                    raise ValueError(
                        "runtime projection semantic-closure source is not unique"
                    )
                if not entries:
                    continue
                for value in cast(list[Any], entries[0]["definitions"]):
                    budget.consume()
                    rows.append(
                        {
                            "package": closure["package"],
                            "authority_path": source["authority_path"],
                            "value": value,
                        }
                    )
        else:
            raise ValueError("unknown admitted runtime projection collection source")
        catalogs[collection["id"]] = rows

    selected: dict[str, set[int]] = {collection_id: set() for collection_id in catalogs}
    for seed in cast(list[dict[str, Any]], profile["seeds"]):
        collection_id = cast(str, seed["collection"])
        catalog = catalogs[collection_id]
        for declaration in declarations:
            if seed["applicability_member"] not in declaration:
                continue
            try:
                expected = path_value(
                    declaration, cast(list[str], seed["declaration_path"])
                )
            except ValueError:
                if seed.get("missing_declaration_path") == "not-applicable":
                    continue
                raise
            package = path_value(
                declaration,
                cast(list[str], seed["declaration_package_path"]),
            )
            if seed["operator"] != "declaration-field":
                raise ValueError("unknown admitted runtime projection seed operator")
            matches = []
            for index, row in enumerate(catalog):
                budget.consume()
                if seed["same_package"] and row["package"] != package:
                    continue
                try:
                    target = path_value(
                        row["value"], cast(list[str], seed["target_path"])
                    )
                except ValueError:
                    if seed.get("missing_target") == "not-applicable":
                        continue
                    raise
                if canonical_bytes(target) == canonical_bytes(expected):
                    matches.append(index)
            if not matches:
                raise ValueError("runtime projection seed did not resolve")
            selected[collection_id].update(matches)

    changed = True
    type_reference_closure = cast(dict[str, Any], profile.get("type_reference_closure"))
    if set(type_reference_closure) != {
        "constructor_kind_path",
        "coordinate_members",
        "source_collection",
        "source_definition_path",
        "structural_kind_member",
        "target_constructor_collection",
        "target_type_collection",
    }:
        raise ValueError("runtime projection type-reference closure is incomplete")
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], lock["packages"])
    }

    def nested_type_terms(root: Any) -> tuple[set[tuple[str, str, str]], set[str]]:
        coordinate_members = cast(
            list[str], type_reference_closure["coordinate_members"]
        )
        structural_kind_member = cast(
            str, type_reference_closure["structural_kind_member"]
        )
        coordinates: set[tuple[str, str, str]] = set()
        structural_kinds: set[str] = set()

        def visit(value: Any) -> None:
            budget.consume()
            if isinstance(value, dict):
                coordinate = tuple(value.get(member) for member in coordinate_members)
                if len(coordinate) == 3 and all(
                    isinstance(item, str) and item for item in coordinate
                ):
                    coordinates.add(cast(tuple[str, str, str], coordinate))
                kind = value.get(structural_kind_member)
                if isinstance(kind, str) and kind:
                    structural_kinds.add(kind)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(root)
        return coordinates, structural_kinds

    while changed:
        changed = False
        for edge in cast(list[dict[str, Any]], profile["edges"]):
            if edge["operator"] != "equal":
                raise ValueError("unknown admitted runtime projection edge operator")
            source_id = cast(str, edge["source_collection"])
            target_id = cast(str, edge["target_collection"])
            targets = catalogs[target_id]
            for source_index in tuple(selected[source_id]):
                budget.consume()
                source_row = catalogs[source_id][source_index]
                source_value = path_value(
                    source_row["value"], cast(list[str], edge["source_path"])
                )
                matches = [
                    target_index
                    for target_index, target_row in enumerate(targets)
                    if (
                        budget.consume() is None
                        and (
                            not edge["same_package"]
                            or target_row["package"] == source_row["package"]
                        )
                    )
                    and canonical_bytes(
                        path_value(
                            target_row["value"],
                            cast(list[str], edge["target_path"]),
                        )
                    )
                    == canonical_bytes(source_value)
                ]
                if not matches:
                    if edge.get("missing_target") == "not-applicable":
                        continue
                    source_label = (
                        source_row["value"].get("id")
                        if isinstance(source_row["value"], dict)
                        else None
                    )
                    raise ValueError(
                        "runtime projection edge did not resolve: "
                        f"{source_id}->{target_id} for "
                        f"{source_label or f'{source_id}[{source_index}]'}"
                    )
                previous_count = len(selected[target_id])
                selected[target_id].update(matches)
                changed = changed or len(selected[target_id]) != previous_count

        source_id = cast(str, type_reference_closure["source_collection"])
        type_target_id = cast(str, type_reference_closure["target_type_collection"])
        constructor_target_id = cast(
            str, type_reference_closure["target_constructor_collection"]
        )
        source_definition_path = cast(
            list[str], type_reference_closure["source_definition_path"]
        )
        constructor_kind_path = cast(
            list[str], type_reference_closure["constructor_kind_path"]
        )
        coordinates: set[tuple[str, str, str]] = set()
        structural_kinds: set[str] = set()
        for source_index in tuple(selected[source_id]):
            nested_coordinates, nested_kinds = nested_type_terms(
                path_value(
                    catalogs[source_id][source_index]["value"], source_definition_path
                )
            )
            coordinates.update(nested_coordinates)
            structural_kinds.update(nested_kinds)
        type_matches = {
            index
            for index, row in enumerate(catalogs[type_target_id])
            if (
                budget.consume() is None
                and any(
                    row["package"] == package
                    and row["value"].get("id") == type_id
                    and package_versions.get(package) == version
                    for package, version, type_id in coordinates
                )
            )
        }
        constructor_matches: set[int] = set()
        for index, row in enumerate(catalogs[constructor_target_id]):
            budget.consume()
            try:
                constructor_kind = path_value(row["value"], constructor_kind_path)
            except ValueError:
                continue
            if constructor_kind in structural_kinds:
                constructor_matches.add(index)
        previous_types = len(selected[type_target_id])
        previous_constructors = len(selected[constructor_target_id])
        selected[type_target_id].update(type_matches)
        selected[constructor_target_id].update(constructor_matches)
        changed = (
            changed
            or len(selected[type_target_id]) != previous_types
            or len(selected[constructor_target_id]) != previous_constructors
        )

    selected_packages = {
        row["package"]
        for collection_id, indexes in selected.items()
        for index, row in enumerate(catalogs[collection_id])
        if index in indexes
    }
    projection: dict[str, Any] = {}
    closure_values: dict[tuple[str, str], list[Any]] = {}

    def projected_runtime_value(collection: dict[str, Any], value: Any) -> Any:
        excluded = collection.get("excluded_extension_members", [])
        if not excluded:
            return value
        if not isinstance(value, dict) or not isinstance(value.get("extensions"), dict):
            return value
        projected_value = deepcopy(value)
        extensions = cast(dict[str, Any], projected_value["extensions"])
        for member in cast(list[str], excluded):
            extensions.pop(member, None)
        if not extensions:
            projected_value.pop("extensions")
        return projected_value

    for collection in cast(list[dict[str, Any]], profile["collections"]):
        collection_id = cast(str, collection["id"])
        rows = [
            row
            for index, row in enumerate(catalogs[collection_id])
            if budget.consume() is None and index in selected[collection_id]
        ]
        rows = [
            {**row, "value": projected_runtime_value(collection, row["value"])}
            for row in rows
        ]
        for row in rows:
            authority_path = row["authority_path"]
            if isinstance(authority_path, str):
                closure_values.setdefault(
                    (cast(str, row["package"]), authority_path), []
                ).append(row["value"])
        output_member = collection["output_member"]
        if output_member is None:
            continue
        shape = collection["output_shape"]
        if shape == "as-is":
            projected_values: list[Any] = [row["value"] for row in rows]
        elif shape == "package-definition":
            projected_values = [
                {
                    "package": cast(str, row["package"]),
                    "definition": row["value"],
                }
                for row in rows
            ]
        elif shape == "definition":
            projected_values = [row["value"] for row in rows]
        else:
            raise ValueError("unknown admitted runtime projection output shape")
        projection[cast(str, output_member)] = projected_values

    for output in cast(list[dict[str, Any]], profile["outputs"]):
        source_rows = lock[output["source_member"]]
        if not isinstance(source_rows, list):
            raise ValueError("runtime projection output source is not a list")
        kind = output["kind"]
        if kind == "selected-packages":
            output_values: list[Any] = [
                {
                    member: cast(dict[str, Any], row)[member]
                    for member in cast(list[str], output["members"])
                }
                for row in source_rows
                if (
                    budget.consume() is None
                    and cast(dict[str, Any], row)[output["package_member"]]
                    in selected_packages
                )
            ]
        elif kind == "selected-semantic-closures":
            output_values = []
            for closure in cast(list[dict[str, Any]], source_rows):
                budget.consume()
                package = cast(str, closure[output["package_member"]])
                if package not in selected_packages:
                    continue
                entries = []
                for entry in cast(
                    list[dict[str, Any]], closure[output["entries_member"]]
                ):
                    authority_path = cast(str, entry[output["authority_path_member"]])
                    definitions = closure_values.get((package, authority_path))
                    if definitions:
                        entries.append(
                            {
                                output["authority_path_member"]: authority_path,
                                output["definitions_member"]: definitions,
                            }
                        )
                if entries:
                    output_values.append(
                        {
                            output["package_member"]: package,
                            output["entries_member"]: entries,
                        }
                    )
        else:
            raise ValueError("unknown admitted runtime projection output kind")
        projection[cast(str, output["output_member"])] = output_values
    return projection


def _runtime_projection_budget(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> _RuntimeProjectionBudget:
    meta_format = cast(dict[str, Any], kernel["meta_format"])
    runtime_contract = cast(dict[str, Any], meta_format["runtime_projection"])
    accounting = cast(dict[str, Any], runtime_contract["resource_accounting"])
    limit_member = cast(str, accounting["limit_member"])
    resources = cast(dict[str, Any], language_bundle["resources"])
    return _RuntimeProjectionBudget(cast(int, resources[limit_member]))


def _apply_language_rule(
    language: dict[str, Any],
    *,
    rule_id: str,
    phase: str,
    judgment: str,
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the Kernel's exact select-bind-substitute rule mechanics."""
    candidates = [
        rule
        for rule in cast(list[dict[str, Any]], language["rules"])
        if rule["id"] == rule_id
        and rule["phase"] == phase
        and rule["judgment"] == judgment
        and len(rule["premises"]) == len(facts)
        and all(
            premise["fact_kind"] == fact["kind"]
            for premise, fact in zip(rule["premises"], facts, strict=True)
        )
    ]
    if len(candidates) != 1:
        raise ValueError("language rule selection was not unique")
    rule = candidates[0]
    bindings: dict[str, Any] = {}
    for premise, fact in zip(rule["premises"], facts, strict=True):
        for variable, field in premise["bind"].items():
            value = fact["fields"][field]
            if variable in bindings and bindings[variable] != value:
                raise ValueError("language rule binding conflicted")
            bindings[variable] = value
    fields: dict[str, Any] = {}
    for name, term in rule["conclusion"]["fields"].items():
        if term["tag"] == "literal":
            fields[name] = term["value"]
        elif term["tag"] == "variable" and term["name"] in bindings:
            fields[name] = bindings[term["name"]]
        else:
            raise ValueError("language rule term could not be substituted")
    return {"kind": rule["conclusion"]["fact_kind"], "fields": fields}
