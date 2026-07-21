from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bundle import LanguageBundle
from canonical import content_identity, identified
from refusals import Refusal, source_location


@dataclass(frozen=True)
class CompileResult:
    ast: dict[str, Any]
    hir: dict[str, Any]
    package_lock: dict[str, Any]
    rir: dict[str, Any]


def _load_json(path: Path, expected_kind: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Refusal(
            "ingress",
            "schema2.source.unreadable",
            str(exc),
            {"kind": "invocation"},
        ) from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Refusal(
            "parse",
            "schema2.source.invalid-json",
            str(exc),
            {
                "kind": "source",
                "module_id": "<wire>",
                "package_id": "<unknown>",
                "span": {"pointer": ""},
            },
        ) from exc
    if not isinstance(document, dict) or document.get("artifact_kind") != expected_kind:
        raise Refusal(
            "parse",
            "schema2.source.invalid-kind",
            f"expected {expected_kind}",
            {
                "kind": "source",
                "module_id": "<wire>",
                "package_id": "<unknown>",
                "span": {"pointer": "/artifact_kind"},
            },
        )
    return document


def load_experiment(path: Path) -> dict[str, Any]:
    return _load_json(path, "experiment-specification")


def _type_of_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int"
    raise ValueError("prototype literals require an explicit nominal type")


def _validate_typed_value(
    value: Any,
    type_id: str,
    *,
    bundle: LanguageBundle,
    package_id: str,
    module_id: str,
    pointer: str,
) -> None:
    bundle.require(
        "type.admitted",
        {"admitted": bundle.types, "actual": type_id},
        message=f"unknown type {type_id}",
        location=source_location(package_id, module_id, pointer),
    )
    if type_id in {"Int", "Quantity:damage", "Quantity:mana", "Quantity:health"}:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif type_id == "Bool":
        valid = isinstance(value, bool)
    else:
        valid = isinstance(value, str)
    bundle.require(
        "type.value-inhabits",
        {"valid": valid},
        message=f"value does not inhabit {type_id}",
        location=source_location(package_id, module_id, pointer),
    )


def _resolved_symbol(package_key: str, module_id: str, symbol_id: str) -> str:
    return f"{package_key}::{module_id}::{symbol_id}"


def _resolve_visible_symbols(
    modules: list[dict[str, Any]],
    package_key: str,
    package_id: str,
    bundle: LanguageBundle,
) -> tuple[dict[str, dict[str, tuple[str, str]]], dict[str, dict[str, Any]]]:
    module_by_id: dict[str, dict[str, Any]] = {}
    declared: dict[str, dict[str, tuple[str, str]]] = {}
    for module_index, module in enumerate(modules):
        module_id = module.get("id")
        bundle.require(
            "resolution.unique",
            {"unique": isinstance(module_id, str) and module_id not in module_by_id},
            message=f"duplicate or invalid module id {module_id!r}",
            location=source_location(
                package_id, str(module_id), f"/modules/{module_index}/id"
            ),
        )
        assert isinstance(module_id, str)
        module_by_id[module_id] = module
        declared[module_id] = {}
        for declaration_index, declaration in enumerate(module.get("declarations", [])):
            symbol_id = declaration.get("id")
            bundle.require(
                "resolution.unique",
                {
                    "unique": isinstance(symbol_id, str)
                    and symbol_id not in declared[module_id]
                },
                message=f"duplicate or invalid declaration {symbol_id!r}",
                location=source_location(
                    package_id,
                    module_id,
                    f"/modules/{module_index}/declarations/{declaration_index}/id",
                ),
            )
            assert isinstance(symbol_id, str)
            declared[module_id][symbol_id] = (
                _resolved_symbol(package_key, module_id, symbol_id),
                str(declaration.get("type")),
            )

    visible: dict[str, dict[str, tuple[str, str]]] = {}
    for module_index, module in enumerate(modules):
        module_id = module["id"]
        names = dict(declared[module_id])
        for import_index, imported in enumerate(module.get("imports", [])):
            target_id = imported.get("module")
            alias = imported.get("alias")
            selected = imported.get("names")
            bundle.require(
                "resolution.import",
                {
                    "alias_explicit": isinstance(alias, str),
                    "module_exists": target_id in declared,
                    "selected_explicit": isinstance(selected, list),
                },
                message="imports require an existing module, explicit alias, and selected names",
                location=source_location(
                    package_id,
                    module_id,
                    f"/modules/{module_index}/imports/{import_index}",
                ),
            )
            for selected_name in selected:
                bundle.require(
                    "resolution.name",
                    {"names": declared[target_id], "requested": selected_name},
                    message=f"unresolved imported symbol {target_id}.{selected_name}",
                    location=source_location(
                        package_id,
                        module_id,
                        f"/modules/{module_index}/imports/{import_index}",
                    ),
                )
                qualified = f"{alias}.{selected_name}"
                bundle.require(
                    "resolution.unique",
                    {"unique": qualified not in names},
                    message=f"import shadows visible symbol {qualified}",
                    location=source_location(
                        package_id,
                        module_id,
                        f"/modules/{module_index}/imports/{import_index}",
                    ),
                )
                names[qualified] = declared[target_id][selected_name]
        visible[module_id] = names
    return visible, module_by_id


def _compile_expression(
    expression: dict[str, Any],
    *,
    visible: dict[str, tuple[str, str]],
    locals_: dict[str, str],
    package_id: str,
    module_id: str,
    pointer: str,
    bundle: LanguageBundle,
) -> tuple[dict[str, Any], str]:
    if set(expression) == {"read"}:
        name = expression["read"]
        bundle.require(
            "resolution.name",
            {"names": visible, "requested": name},
            message=f"unresolved symbol {name}",
            location=source_location(package_id, module_id, pointer),
        )
        resolved_id, type_id = visible[name]
        return {"read_symbol": resolved_id, "type": type_id}, type_id
    if (
        "literal" in expression
        and "type" in expression
        and set(expression) == {"literal", "type"}
    ):
        type_id = str(expression["type"])
        _validate_typed_value(
            expression["literal"],
            type_id,
            bundle=bundle,
            package_id=package_id,
            module_id=module_id,
            pointer=pointer,
        )
        return {"literal": expression["literal"], "type": type_id}, type_id
    if (
        "event" in expression
        and "type" in expression
        and set(expression) == {"event", "type"}
    ):
        type_id = str(expression["type"])
        bundle.require(
            "type.admitted",
            {"admitted": bundle.types, "actual": type_id},
            message=f"unknown event field type {type_id}",
            location=source_location(package_id, module_id, pointer),
        )
        return {"event_field": expression["event"], "type": type_id}, type_id
    if (
        "signal" in expression
        and "type" in expression
        and set(expression) == {"signal", "type"}
    ):
        type_id = str(expression["type"])
        bundle.require(
            "type.admitted",
            {"admitted": bundle.types, "actual": type_id},
            message=f"unknown signal field type {type_id}",
            location=source_location(package_id, module_id, pointer),
        )
        return {"signal_field": expression["signal"], "type": type_id}, type_id
    if set(expression) == {"local"}:
        name = str(expression["local"])
        bundle.require(
            "resolution.name",
            {"names": locals_, "requested": name},
            message=f"unresolved local {name}",
            location=source_location(package_id, module_id, pointer),
        )
        return {"local": name, "type": locals_[name]}, locals_[name]
    if expression.get("op") == "add" and set(expression) == {"op", "args"}:
        compiled_args: list[dict[str, Any]] = []
        arg_types: list[str] = []
        for index, argument in enumerate(expression["args"]):
            compiled, type_id = _compile_expression(
                argument,
                visible=visible,
                locals_=locals_,
                package_id=package_id,
                module_id=module_id,
                pointer=f"{pointer}/args/{index}",
                bundle=bundle,
            )
            compiled_args.append(compiled)
            arg_types.append(type_id)
        bundle.require(
            "type.add-compatible",
            {
                "valid": bool(arg_types)
                and len(set(arg_types)) == 1
                and arg_types[0]
                in {"Int", "Quantity:damage", "Quantity:mana", "Quantity:health"}
            },
            message="add requires a non-empty list of one exact numeric type",
            location=source_location(package_id, module_id, pointer),
        )
        return {
            "args": compiled_args,
            "kernel": "exact.add",
            "type": arg_types[0],
        }, arg_types[0]
    try:
        inferred = _type_of_literal(expression)
    except ValueError:
        inferred = "<invalid>"
    bundle.require(
        "type.expression",
        {"valid": False},
        message=f"expression is outside the closed kernel (inferred {inferred})",
        location=source_location(package_id, module_id, pointer),
    )
    raise AssertionError("a rejecting Language rule returned")


def compile_model(path: Path, bundle: LanguageBundle) -> CompileResult:
    source = _load_json(path, "model-source-package")
    manifest = source.get("manifest", {})
    package_id = str(manifest.get("package_id", "<unknown>"))
    version = str(manifest.get("version", "<unknown>"))
    package_key = f"{package_id}@{version}"
    modules = source.get("modules")
    if not isinstance(modules, list) or len(modules) < 2:
        raise Refusal(
            "parse",
            "schema2.source.modules-required",
            "tracer Model Source Package requires at least two modules",
            source_location(package_id, "<manifest>", "/modules"),
        )

    ast_content = {
        "modules": modules,
        "package_manifest": manifest,
        "source_identity": content_identity(source),
        "source_spans": "json-pointer-prototype",
    }
    ast = identified("authoring-ast", ast_content)

    visible_by_module, _ = _resolve_visible_symbols(
        modules, package_key, package_id, bundle
    )

    locked_packages: list[dict[str, str]] = []
    locked_ids: set[str] = set()
    for index, requirement in enumerate(manifest.get("requires", [])):
        required_id = requirement.get("id")
        required_version = requirement.get("version")
        admitted = bundle.packages.get(required_id)
        bundle.require(
            "package.exact",
            {
                "admitted": admitted is not None,
                "actual_version": admitted.get("version") if admitted else None,
                "expected_version": required_version,
                "unique": required_id not in locked_ids,
            },
            message=f"cannot bind exact unique package {required_id}@{required_version}",
            location=source_location(
                package_id, "<manifest>", f"/manifest/requires/{index}"
            ),
        )
        locked_ids.add(required_id)
        locked_packages.append({"id": required_id, "version": str(required_version)})
    package_lock = identified(
        "package-lock",
        {
            "bundle_identity": bundle.identity,
            "packages": sorted(locked_packages, key=lambda item: item["id"]),
            "resolver": "schema2-prototype-exact-v1",
        },
    )

    hir_declarations: list[dict[str, Any]] = []
    hir_entities: list[dict[str, Any]] = []
    hir_handlers: list[dict[str, Any]] = []
    handler_ids: dict[str, str] = {}

    for module_index, module in enumerate(modules):
        module_id = module["id"]
        visible = visible_by_module[module_id]
        for declaration_index, declaration in enumerate(module.get("declarations", [])):
            type_id = str(declaration.get("type"))
            bundle.require(
                "type.admitted",
                {"admitted": bundle.types, "actual": type_id},
                message=f"unknown declaration type {type_id}",
                location=source_location(
                    package_id,
                    module_id,
                    f"/modules/{module_index}/declarations/{declaration_index}/type",
                ),
            )
            compiled_declaration: dict[str, Any] = {
                "id": _resolved_symbol(package_key, module_id, declaration["id"]),
                "role": declaration["role"],
                "type": type_id,
            }
            if "value" in declaration:
                _validate_typed_value(
                    declaration["value"],
                    type_id,
                    bundle=bundle,
                    package_id=package_id,
                    module_id=module_id,
                    pointer=f"/modules/{module_index}/declarations/{declaration_index}/value",
                )
                compiled_declaration["value"] = declaration["value"]
            else:
                expression, expression_type = _compile_expression(
                    declaration["expression"],
                    visible=visible,
                    locals_={},
                    package_id=package_id,
                    module_id=module_id,
                    pointer=f"/modules/{module_index}/declarations/{declaration_index}/expression",
                    bundle=bundle,
                )
                bundle.require(
                    "type.equal",
                    {"actual": expression_type, "expected": type_id},
                    message=f"derived declaration expects {type_id}, got {expression_type}",
                    location=source_location(
                        package_id,
                        module_id,
                        f"/modules/{module_index}/declarations/{declaration_index}/expression",
                    ),
                )
                compiled_declaration["expression"] = expression
            hir_declarations.append(compiled_declaration)

        for entity_index, entity in enumerate(module.get("entities", [])):
            compiled_fields: dict[str, dict[str, Any]] = {}
            for field_name, typed_value in entity.get("fields", {}).items():
                type_id = str(typed_value.get("type"))
                _validate_typed_value(
                    typed_value.get("value"),
                    type_id,
                    bundle=bundle,
                    package_id=package_id,
                    module_id=module_id,
                    pointer=f"/modules/{module_index}/entities/{entity_index}/fields/{field_name}",
                )
                compiled_fields[field_name] = {
                    "type": type_id,
                    "value": typed_value["value"],
                }
            hir_entities.append(
                {
                    "entity_id": entity["id"],
                    "entity_type": entity["type"],
                    "fields": compiled_fields,
                }
            )

        for handler_index, handler in enumerate(module.get("handlers", [])):
            authored_handler_id = f"{module_id}.{handler['id']}"
            resolved_handler_id = _resolved_symbol(
                package_key, module_id, f"handler:{handler['id']}"
            )
            bundle.require(
                "resolution.unique",
                {"unique": authored_handler_id not in handler_ids},
                message=f"duplicate handler {authored_handler_id}",
                location=source_location(
                    package_id,
                    module_id,
                    f"/modules/{module_index}/handlers/{handler_index}",
                ),
            )
            handler_ids[authored_handler_id] = resolved_handler_id
            locals_: dict[str, str] = {}
            compiled_calls: list[dict[str, Any]] = []
            observed_effects: set[str] = set()
            for call_index, call in enumerate(handler.get("calls", [])):
                operation_id = call.get("operation")
                operation = bundle.operations.get(operation_id)
                pointer = f"/modules/{module_index}/handlers/{handler_index}/calls/{call_index}"
                bundle.require(
                    "operation.admitted",
                    {"admitted": bundle.operations, "operation": operation_id},
                    message=f"operation is not admitted: {operation_id}",
                    location=source_location(
                        package_id, module_id, f"{pointer}/operation"
                    ),
                )
                assert operation is not None
                owner_package = operation["package"]
                bundle.require(
                    "package.capability",
                    {"locked": locked_ids, "owner": owner_package},
                    message=f"operation package is not locked: {owner_package}",
                    location=source_location(
                        package_id, module_id, f"{pointer}/operation"
                    ),
                )
                input_specs = {
                    entry["name"]: entry["type"] for entry in operation["inputs"]
                }
                bundle.require(
                    "type.call-arguments",
                    {
                        "actual": list(call.get("arguments", {})),
                        "expected": list(input_specs),
                    },
                    message=f"operation {operation_id} arguments do not match its bundle signature",
                    location=source_location(
                        package_id, module_id, f"{pointer}/arguments"
                    ),
                )
                compiled_args: dict[str, dict[str, Any]] = {}
                for argument_name, argument_expression in call["arguments"].items():
                    compiled_expression, actual_type = _compile_expression(
                        argument_expression,
                        visible=visible,
                        locals_=locals_,
                        package_id=package_id,
                        module_id=module_id,
                        pointer=f"{pointer}/arguments/{argument_name}",
                        bundle=bundle,
                    )
                    expected_type = input_specs[argument_name]
                    bundle.require(
                        "type.call",
                        {"actual": actual_type, "expected": expected_type},
                        message=(
                            f"{operation_id}.{argument_name} expects {expected_type}, got {actual_type}"
                        ),
                        location=source_location(
                            package_id,
                            module_id,
                            f"{pointer}/arguments/{argument_name}",
                        ),
                    )
                    compiled_args[argument_name] = compiled_expression
                result_type = operation["result"]
                bind = call.get("bind")
                if result_type == "Unit" and bind is not None:
                    bundle.require(
                        "type.call",
                        {"actual": bind, "expected": None},
                        message=f"Unit operation {operation_id} cannot bind a local",
                        location=source_location(package_id, module_id, pointer),
                    )
                    raise AssertionError("a rejecting Language rule returned")
                if result_type != "Unit":
                    bundle.require(
                        "resolution.unique",
                        {"unique": isinstance(bind, str) and bind not in locals_},
                        message=f"operation {operation_id} requires one non-shadowing bind",
                        location=source_location(package_id, module_id, pointer),
                    )
                    assert isinstance(bind, str)
                    locals_[bind] = result_type
                observed_effects.update(operation["effects"])
                compiled_calls.append(
                    {
                        "arguments": compiled_args,
                        "bind": bind,
                        "effects": operation["effects"],
                        "operation": operation_id,
                        "primitive": operation["primitive"],
                        "result_type": result_type,
                    }
                )
            declared_effects = sorted(handler.get("declared_effects", []))
            bundle.require(
                "effect.declared",
                {"actual": observed_effects, "expected": declared_effects},
                message="handler declared effects must exactly match bundle-composed call effects",
                location=source_location(
                    package_id,
                    module_id,
                    f"/modules/{module_index}/handlers/{handler_index}/declared_effects",
                ),
            )
            hir_handlers.append(
                {
                    "authored_id": authored_handler_id,
                    "calls": compiled_calls,
                    "declared_effects": declared_effects,
                    "id": resolved_handler_id,
                }
            )

    hir_subscriptions: list[dict[str, str]] = []
    for subscription_index, subscription in enumerate(source.get("subscriptions", [])):
        signal_id = subscription.get("signal")
        handler_name = subscription.get("handler")
        bundle.require(
            "subscription.valid",
            {
                "handler_resolved": handler_name in handler_ids,
                "signal_admitted": signal_id in bundle.signals,
            },
            message="subscription signal and handler must both resolve",
            location=source_location(
                package_id, "<manifest>", f"/subscriptions/{subscription_index}"
            ),
        )
        hir_subscriptions.append(
            {"handler": handler_ids[handler_name], "signal": signal_id}
        )

    hir = identified(
        "typed-hir",
        {
            "ast_identity": ast["identity"],
            "bundle_identity": bundle.identity,
            "declarations": sorted(hir_declarations, key=lambda item: item["id"]),
            "entities": sorted(hir_entities, key=lambda item: item["entity_id"]),
            "handlers": sorted(hir_handlers, key=lambda item: item["id"]),
            "package_key": package_key,
            "subscriptions": sorted(
                hir_subscriptions, key=lambda item: (item["signal"], item["handler"])
            ),
        },
    )

    # The prototype's lowering relation is deliberately small: Typed HIR is
    # stripped of source spellings while resolved ids, types, effects and bundle
    # primitives remain. Runtime receives only this RIR artifact.
    for handler in hir["content"]["handlers"]:
        for call in handler["calls"]:
            bundle.require(
                "lower.operation",
                {
                    "operation_admitted": call["operation"] in bundle.operations,
                    "primitive_present": bool(call["primitive"]),
                },
                message=f"cannot lower operation {call['operation']}",
                location={
                    "artifact_identity": hir["identity"],
                    "kind": "artifact",
                    "pointer": "/content/handlers",
                },
            )

    rir_content = {
        "bundle_identity": bundle.identity,
        "compiler_identity": "schema2-tracer-compiler@1",
        "declarations": hir["content"]["declarations"],
        "entities": hir["content"]["entities"],
        "exports": {
            name: handler_id for name, handler_id in sorted(handler_ids.items())
        },
        "handlers": [
            {
                "calls": handler["calls"],
                "declared_effects": handler["declared_effects"],
                "id": handler["id"],
            }
            for handler in hir["content"]["handlers"]
        ],
        "package_lock_identity": package_lock["identity"],
        "subscriptions": hir["content"]["subscriptions"],
    }
    rir = identified("resolved-model-rir", rir_content)
    return CompileResult(ast=ast, hir=hir, package_lock=package_lock, rir=rir)
