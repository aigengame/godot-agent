"""Authority-driven canonical Formula notation conversion."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.formula.types import (
    formula_contract_from_operation,
    formula_contract_matches,
    formula_contract_matches_operation,
    resolve_formula_contract,
)
from gda_balancing.domain.authority.runtime_validation import (
    operation_literal_context_contract,
)
from gda_balancing.domain.formula.inference import infer_formula_operation_result


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    offset: int


@dataclass(frozen=True)
class _OperationNotation:
    coordinate: tuple[str, str, str]
    declaration: dict[str, Any]
    notation: dict[str, Any]


class FormulaNotationRefusal(ValueError):
    """One Formula notation refusal projected through LDB-owned reason data."""

    def __init__(self, reason_id: str, message: str) -> None:
        super().__init__(message)
        self.reason_id = reason_id
        self.message = message


class FormulaPairRefusal(FormulaNotationRefusal):
    """One exact body/expression-pair refusal with its owning member."""

    def __init__(self, reason_id: str, member: str, message: str) -> None:
        super().__init__(reason_id, message)
        self.member = member


class _FormulaNotationSyntaxError(ValueError):
    """A grammar-level failure before contextual Formula resolution."""


class _FormulaNotationResourceError(ValueError):
    """A deterministic notation resource bound was exceeded."""


class _FormulaContextError(ValueError):
    """A contextual failure with an explicit LDB-owned machine reason."""

    def __init__(self, reason_id: str, message: str) -> None:
        super().__init__(message)
        self.reason_id = reason_id


def _contextual_refusal(error: ValueError) -> FormulaNotationRefusal:
    message = str(error)
    reason = (
        error.reason_id
        if isinstance(error, _FormulaContextError)
        else "model.reason.source-contract-mismatch"
    )
    return FormulaNotationRefusal(reason, message)


def _notation_authority(
    authority_context: AdmittedAuthorityContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    packages = cast(
        list[dict[str, Any]], authority_context.language_bundle["language"]["packages"]
    )
    matches: list[dict[str, Any]] = []
    for package in packages:
        if package.get("id") != "standard.schema":
            continue
        for closure in cast(list[dict[str, Any]], package["semantic_closure"]):
            if closure.get("authority_path") != "language.wire_schemas":
                continue
            matches.extend(
                cast(dict[str, Any], definition["schema"])
                for definition in cast(list[dict[str, Any]], closure["definitions"])
                if definition.get("artifact_kind") == "model-source-package"
            )
    if len(matches) != 1:
        raise ValueError("standard.schema has no unique Formula notation authority")
    definitions = matches[0].get("$defs")
    if not isinstance(definitions, dict):
        raise ValueError("standard.schema has no Formula notation definitions")
    grammar_schema = definitions.get("formulaNotationGrammar")
    notation_schema = definitions.get("formulaOperationNotation")
    grammar = grammar_schema.get("const") if isinstance(grammar_schema, dict) else None
    if not isinstance(grammar, dict) or not isinstance(notation_schema, dict):
        raise ValueError("standard.schema Formula notation authority is incomplete")
    token_pattern = grammar.get("identifier_token_pattern")
    bare_pattern = grammar.get("bare_identifier_pattern")
    integer_pattern = grammar.get("integer_literal_pattern")
    whitespace_pattern = grammar.get("whitespace_pattern")
    if (
        grammar.get("version") != "1.1.0"
        or not isinstance(token_pattern, str)
        or bare_pattern != f"^{token_pattern}$"
        or not isinstance(integer_pattern, str)
        or not isinstance(whitespace_pattern, str)
        or grammar.get("signed_integer_context") != "operand-position"
        or not isinstance(grammar.get("max_group_depth"), int)
        or cast(int, grammar["max_group_depth"]) < 1
    ):
        raise ValueError("standard.schema Formula notation grammar is malformed")
    try:
        if (
            re.fullmatch(token_pattern, "") is not None
            or re.fullmatch(integer_pattern, "") is not None
            or re.fullmatch(whitespace_pattern, "") is not None
        ):
            raise ValueError("Formula notation token patterns admit empty input")
    except re.error as err:
        raise ValueError("Formula notation token pattern is malformed") from err
    return grammar, notation_schema


def formula_notation_request_identity_domain(
    authority_context: AdmittedAuthorityContext,
) -> str:
    """Return the authority-owned domain for conversion-request locations."""
    grammar, _notation_schema = _notation_authority(authority_context)
    identity_domain = grammar.get("request_identity_domain")
    if not isinstance(identity_domain, str) or not identity_domain:
        raise ValueError("Formula notation request identity domain is malformed")
    return identity_domain


def _identifier(value: object, grammar: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Formula notation requires a non-empty identifier")
    pattern = grammar.get("bare_identifier_pattern")
    reserved = grammar.get("reserved_identifiers")
    quote = grammar.get("identifier_quote")
    escape = grammar.get("escape_character")
    escapable = grammar.get("escapable_identifier_characters")
    if not (
        isinstance(pattern, str)
        and isinstance(reserved, list)
        and isinstance(quote, str)
        and len(quote) == 1
        and isinstance(escape, str)
        and len(escape) == 1
        and isinstance(escapable, list)
        and set(escapable) == {quote, escape}
    ):
        raise ValueError("Formula notation identifier grammar is malformed")
    if re.fullmatch(pattern, value) and value not in reserved:
        return value
    escaped = value.replace(escape, escape + escape).replace(quote, escape + quote)
    return quote + escaped + quote


def _operation_catalog(
    authority_context: AdmittedAuthorityContext,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    catalog: dict[tuple[str, str, str], dict[str, Any]] = {}
    packages = cast(
        list[dict[str, Any]], authority_context.language_bundle["language"]["packages"]
    )
    for package in packages:
        package_id = cast(str, package["id"])
        version = cast(str, package["version"])
        for closure in cast(list[dict[str, Any]], package["semantic_closure"]):
            if closure.get("authority_path") != "language.operations":
                continue
            for operation in cast(list[dict[str, Any]], closure["definitions"]):
                catalog[(package_id, version, cast(str, operation["id"]))] = operation
    return catalog


def _validated_operation_notation(
    operation: dict[str, Any],
    grammar: dict[str, Any],
    notation_schema: dict[str, Any],
) -> dict[str, Any] | None:
    extensions = operation.get("extensions")
    notation = (
        extensions.get("standard.formula-notation")
        if isinstance(extensions, dict)
        else None
    )
    if not isinstance(notation, dict):
        return None
    if list(jsonschema.Draft202012Validator(notation_schema).iter_errors(notation)):
        raise ValueError("Formula Operation notation declaration is malformed")
    kind = notation.get("kind")
    spelling = notation.get("token" if kind == "infix" else "name")
    if not isinstance(spelling, str) or not spelling:
        raise ValueError("Formula Operation notation spelling is malformed")
    if kind == "function":
        if (
            re.fullmatch(cast(str, grammar["bare_identifier_pattern"]), spelling)
            is None
            or spelling in grammar["reserved_identifiers"]
        ):
            raise _FormulaContextError(
                "model.reason.name-ambiguity",
                "Formula function notation spelling is ambiguous",
            )
        return notation
    structural_tokens = {
        *cast(list[str], grammar["group_delimiters"]),
        cast(str, grammar["named_argument_operator"]),
        cast(str, grammar["binding_terminator"]),
        cast(str, grammar["argument_separator"]),
        cast(str, grammar["coordinate_separator"]),
        cast(str, grammar["identifier_quote"]),
        cast(str, grammar["escape_character"]),
    }
    if (
        any(spelling.startswith(token) for token in structural_tokens if token)
        or re.match(cast(str, grammar["identifier_token_pattern"]), spelling)
        or re.match(cast(str, grammar["integer_literal_pattern"]), spelling)
        or re.match(cast(str, grammar["whitespace_pattern"]), spelling)
    ):
        raise ValueError("Formula infix notation collides with grammar tokenization")
    return notation


def _selected_operation_notations(
    request: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
) -> tuple[_OperationNotation, ...]:
    grammar, notation_schema = _notation_authority(authority_context)
    requirements = request.get("package_requirements")
    if not isinstance(requirements, list):
        raise ValueError("Formula context has no package requirements")
    selected = {
        (item.get("id"), item.get("version"))
        for item in requirements
        if isinstance(item, dict)
    }
    declarations: list[_OperationNotation] = []
    for coordinate, operation in _operation_catalog(authority_context).items():
        if coordinate[:2] not in selected or operation.get("purity") != "pure":
            continue
        notation = _validated_operation_notation(operation, grammar, notation_schema)
        if notation is not None:
            declarations.append(_OperationNotation(coordinate, operation, notation))
    spellings = [
        (
            item.notation["kind"],
            item.notation.get("token" if item.notation["kind"] == "infix" else "name"),
        )
        for item in declarations
    ]
    if len(set(spellings)) != len(spellings):
        raise _FormulaContextError(
            "model.reason.name-ambiguity",
            "Formula Operation notation spelling is ambiguous",
        )
    return tuple(declarations)


def _formula_resolution_profile(
    authority_context: AdmittedAuthorityContext,
) -> dict[str, Any]:
    language = cast(dict[str, Any], authority_context.language_bundle["language"])
    profiles = [
        profile
        for profile in cast(list[dict[str, Any]], language["resolution_profiles"])
        if profile.get("default") is True
    ]
    if len(profiles) != 1:
        raise ValueError("Formula conversion requires one default resolution profile")
    profile = profiles[0]
    lowerings = [
        lowering
        for lowering in cast(list[dict[str, Any]], language["model_lowerings"])
        if lowering.get("id") == profile.get("model_lowering")
        and lowering.get("resolution_profile") == profile.get("id")
    ]
    if len(lowerings) != 1:
        raise ValueError("Formula conversion has no selected Model lowering")
    return profile


def _formula_policy(authority_context: AdmittedAuthorityContext) -> dict[str, Any]:
    profile = _formula_resolution_profile(authority_context)
    extensions = profile.get("extensions")
    policy = (
        extensions.get("standard.formula") if isinstance(extensions, dict) else None
    )
    if not isinstance(policy, dict):
        raise ValueError("Formula conversion has no selected Formula policy")
    conversion = policy.get("notation_conversion")
    infix_parser = (
        conversion.get("infix_parser") if isinstance(conversion, dict) else None
    )
    if (
        not isinstance(conversion, dict)
        or conversion.get("condition_contract") != "kernel-boolean"
        or conversion.get("formula_argument_compatibility") != "exact-resolved-contract"
        or conversion.get("formula_result_compatibility") != "exact-resolved-contract"
        or conversion.get("literal_typing") != "selected-unique-formal-match"
        or conversion.get("literal_result_inference") != "contextual-anchor"
        or conversion.get("operation_argument_compatibility")
        != "exact-operation-formal"
        or conversion.get("symbol_resolution") != "exact-module-coordinate"
        or not isinstance(infix_parser, dict)
        or infix_parser.get("algorithm") != "shunting-yard"
        or not isinstance(infix_parser.get("generated_local_separator"), str)
        or not infix_parser["generated_local_separator"]
    ):
        raise ValueError("Formula conversion policy is incomplete")
    return policy


def formula_schema_version(
    authority_context: AdmittedAuthorityContext,
) -> str:
    packages = cast(
        list[dict[str, Any]], authority_context.language_bundle["language"]["packages"]
    )
    versions = [
        definition.get("schema", {})
        .get("properties", {})
        .get("schema_version", {})
        .get("const")
        for package in packages
        if package.get("id") == "standard.schema"
        for closure in cast(list[dict[str, Any]], package["semantic_closure"])
        if closure.get("authority_path") == "language.wire_schemas"
        for definition in cast(list[dict[str, Any]], closure["definitions"])
        if definition.get("artifact_kind") == "model-source-package"
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise ValueError("Formula conversion has no exact source schema version")
    return versions[0]


def _module_imports(
    module: dict[str, Any],
    request: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
    profile: dict[str, Any],
) -> dict[str, dict[str, str]]:
    requirements = request.get(profile["requirements_member"])
    if not isinstance(requirements, list):
        raise ValueError("Formula context has no package requirements")
    requirement_keys: set[tuple[str, str]] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict) or not all(
            isinstance(requirement.get(profile[member]), str)
            for member in ("requirement_package_member", "requirement_version_member")
        ):
            raise ValueError("Formula package requirement is malformed")
        key = (
            cast(str, requirement[profile["requirement_package_member"]]),
            cast(str, requirement[profile["requirement_version_member"]]),
        )
        if key in requirement_keys:
            raise _FormulaContextError(
                "model.reason.name-ambiguity",
                "Formula package requirement is duplicate",
            )
        requirement_keys.add(key)
    packages = {
        (cast(str, item["id"]), cast(str, item["version"])): item
        for item in cast(
            list[dict[str, Any]],
            authority_context.language_bundle["language"]["packages"],
        )
    }
    if any(key not in packages for key in requirement_keys):
        raise _FormulaContextError(
            "model.reason.unresolved-name",
            "Formula package requirement is unresolved",
        )
    if len({package for package, _version in requirement_keys}) != len(
        requirement_keys
    ):
        raise _FormulaContextError(
            "model.reason.name-ambiguity",
            "Formula package requirement version is ambiguous",
        )
    imports = module.get(profile["imports_member"])
    if not isinstance(imports, list):
        raise ValueError("Formula module context has no imports")
    resolved: dict[str, dict[str, str]] = {}
    for item in imports:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(profile[member]), str)
            for member in (
                "import_alias_member",
                "import_package_member",
                "import_version_member",
                "import_symbol_member",
            )
        ):
            raise ValueError("Formula module import is malformed")
        alias = cast(str, item[profile["import_alias_member"]])
        if alias in resolved:
            raise _FormulaContextError(
                "model.reason.name-ambiguity",
                "Formula module import alias is ambiguous",
            )
        package_key = (
            cast(str, item[profile["import_package_member"]]),
            cast(str, item[profile["import_version_member"]]),
        )
        package = packages.get(package_key)
        if package_key not in requirement_keys or package is None:
            raise _FormulaContextError(
                "model.reason.unresolved-name",
                f"Formula import {alias!r} is unresolved",
            )
        exported_types = {
            exported.get("id")
            for exported in cast(list[dict[str, Any]], package["exports"]["types"])
            if isinstance(exported, dict)
        }
        symbol = cast(str, item[profile["import_symbol_member"]])
        if symbol not in exported_types:
            raise _FormulaContextError(
                "model.reason.unresolved-name",
                f"Formula import {alias!r} is unresolved",
            )
        resolved[alias] = {
            "package": package_key[0],
            "version": package_key[1],
            "symbol": symbol,
        }
    return resolved


def _lex(
    expression: str,
    operator_tokens: tuple[str, ...],
    grammar: dict[str, Any],
) -> list[_Token]:
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    coordinate_separator = cast(str, grammar["coordinate_separator"])
    punctuation = {
        *cast(list[str], grammar["group_delimiters"]),
        cast(str, grammar["named_argument_operator"]),
        cast(str, grammar["binding_terminator"]),
        cast(str, grammar["argument_separator"]),
        coordinate_separator,
    }
    whitespace_pattern = re.compile(cast(str, grammar["whitespace_pattern"]))
    identifier_pattern = re.compile(cast(str, grammar["identifier_token_pattern"]))
    integer_pattern = re.compile(cast(str, grammar["integer_literal_pattern"]))
    tokens: list[_Token] = []
    index = 0
    ordered_operators = sorted(operator_tokens, key=len, reverse=True)
    group_depth = 0
    max_group_depth = cast(int, grammar["max_group_depth"])
    open_group, close_group = cast(list[str], grammar["group_delimiters"])
    while index < len(expression):
        character = expression[index]
        whitespace = whitespace_pattern.match(expression, index)
        if whitespace is not None:
            index = whitespace.end()
            continue
        if character in punctuation:
            tokens.append(_Token(character, character, index))
            if character == open_group:
                group_depth += 1
                if group_depth > max_group_depth:
                    raise _FormulaNotationResourceError(
                        "Formula expression exceeds its admitted group-depth bound"
                    )
            elif character == close_group:
                group_depth -= 1
            index += 1
            continue
        if character == quote:
            start = index
            index += 1
            quoted_chars: list[str] = []
            while index < len(expression) and expression[index] != quote:
                if expression[index] == escape:
                    index += 1
                    if index >= len(expression) or expression[index] not in {
                        quote,
                        escape,
                    }:
                        raise _FormulaNotationSyntaxError(
                            f"invalid quoted identifier escape at byte {index}"
                        )
                quoted_chars.append(expression[index])
                index += 1
            if index >= len(expression):
                raise _FormulaNotationSyntaxError(
                    f"unterminated quoted identifier at byte {start}"
                )
            index += 1
            tokens.append(_Token("identifier", "".join(quoted_chars), start))
            continue
        previous = tokens[-1] if tokens else None
        can_end_operand = previous is not None and (
            previous.kind in {"integer", "identifier", close_group}
            and previous.value
            not in {
                grammar["binding_keyword"],
                *cast(list[str], grammar["conditional_keywords"]),
            }
        )
        integer = None if can_end_operand else integer_pattern.match(expression, index)
        if integer is not None:
            tokens.append(_Token("integer", integer.group(0), index))
            index = integer.end()
            continue
        identifier = identifier_pattern.match(expression, index)
        if identifier is not None:
            identifier_value = identifier.group(0)
            tokens.append(_Token("identifier", identifier_value, index))
            index = identifier.end()
            continue
        operator = next(
            (
                token
                for token in ordered_operators
                if expression.startswith(token, index)
            ),
            None,
        )
        if operator is not None:
            tokens.append(_Token("operator", operator, index))
            index += len(operator)
            continue
        raise _FormulaNotationSyntaxError(
            f"unexpected Formula notation token at byte {index}"
        )
    tokens.append(_Token("eof", "", len(expression)))
    return tokens


class _FormulaParser:
    def __init__(
        self,
        expression: str,
        request: dict[str, Any],
        authority_context: AdmittedAuthorityContext,
    ) -> None:
        self.request = request
        formula = request.get("formula")
        if not isinstance(formula, dict):
            raise ValueError("Formula parse request has no declaration context")
        self.formula = formula
        module = request.get("module")
        if not isinstance(module, dict):
            raise ValueError("Formula context has no module scope")
        module_id = module.get("id")
        declarations = module.get("formulas", [])
        if not isinstance(module_id, str) or not isinstance(declarations, list):
            raise ValueError("Formula module context is malformed")
        self.authority_context = authority_context
        if request.get("schema_version") != formula_schema_version(authority_context):
            raise ValueError("Formula conversion source schema version is unavailable")
        self.profile = _formula_resolution_profile(authority_context)
        self.policy = _formula_policy(authority_context)
        self.conversion_policy = cast(
            dict[str, Any], self.policy["notation_conversion"]
        )
        modules = request.get("modules", [module])
        if not isinstance(modules, list) or not modules:
            raise ValueError("Formula conversion has no module closure")
        modules_by_id: dict[str, dict[str, Any]] = {}
        imports_by_module: dict[str, dict[str, dict[str, str]]] = {}
        for candidate in modules:
            if not isinstance(candidate, dict):
                raise _FormulaContextError(
                    "model.reason.name-ambiguity",
                    "Formula module closure is malformed or ambiguous",
                )
            candidate_id = candidate.get("id")
            if not isinstance(candidate_id, str) or candidate_id in modules_by_id:
                raise _FormulaContextError(
                    "model.reason.name-ambiguity",
                    "Formula module closure is malformed or ambiguous",
                )
            modules_by_id[candidate_id] = candidate
            imports_by_module[candidate_id] = _module_imports(
                candidate, request, authority_context, self.profile
            )
        if module_id not in modules_by_id:
            raise ValueError("Formula current module is outside its module closure")
        closure_module = modules_by_id[module_id]
        for member in (
            self.profile["imports_member"],
            self.profile["symbols_member"],
            self.policy["module_formulas_member"],
        ):
            if member in module and module[member] != closure_module.get(member, []):
                raise ValueError(
                    "Formula current module conflicts with its module closure"
                )
        self.imports = imports_by_module[module_id]
        self.source_type_aliases = {
            (identity["package"], identity["version"], identity["symbol"]): alias
            for alias, identity in self.imports.items()
        }
        fixed_contracts = cast(
            dict[str, dict[str, Any]],
            authority_context.kernel["meta_format"]["runtime_program"][
                "fixed_value_contracts"
            ],
        )
        for row in cast(list[dict[str, str]], self.policy["fixed_value_type_aliases"]):
            fixed = fixed_contracts.get(row["contract"])
            fixed_type = fixed.get("type") if isinstance(fixed, dict) else None
            if isinstance(fixed_type, dict):
                self.source_type_aliases[
                    (
                        cast(str, fixed_type["package"]),
                        cast(str, fixed_type["version"]),
                        cast(str, fixed_type["id"]),
                    )
                ] = row["alias"]
        self.formula_declarations: dict[
            tuple[str, str], tuple[dict[str, Any], dict[str, dict[str, str]]]
        ] = {}
        for declaration_module, candidate in modules_by_id.items():
            candidate_formulas = candidate.get("formulas", [])
            if not isinstance(candidate_formulas, list):
                raise ValueError("Formula module declarations are malformed")
            for item in candidate_formulas:
                formula_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(formula_id, str):
                    raise _FormulaContextError(
                        "model.reason.name-ambiguity",
                        "Formula declaration coordinate is ambiguous",
                    )
                key = (declaration_module, formula_id)
                if key in self.formula_declarations:
                    raise _FormulaContextError(
                        "model.reason.name-ambiguity",
                        "Formula declaration coordinate is ambiguous",
                    )
                self.formula_declarations[key] = (
                    item,
                    imports_by_module[declaration_module],
                )
        parameters = formula.get("parameters")
        if not isinstance(parameters, list):
            raise ValueError("Formula declaration has no parameter context")
        self.contracts: dict[str, dict[str, Any]] = {
            cast(str, item["id"]): {
                key: deepcopy(value) for key, value in item.items() if key != "id"
            }
            for item in parameters
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if len(self.contracts) != len(parameters):
            raise _FormulaContextError(
                "model.reason.name-ambiguity",
                "Formula parameter context is malformed or duplicate",
            )
        for contract in self.contracts.values():
            self.resolve_contract(contract)
        result_contract = formula.get("result")
        if not isinstance(result_contract, dict):
            raise ValueError("Formula declaration has no result contract")
        self.result_contract = deepcopy(result_contract)
        self.resolve_contract(self.result_contract)
        self.symbol_contracts: dict[tuple[str, str], dict[str, Any]] = {}
        for symbol_module, candidate in modules_by_id.items():
            symbols = candidate.get("symbols", [])
            if not isinstance(symbols, list):
                raise ValueError("Formula module Symbol context is malformed")
            for symbol in symbols:
                if not isinstance(symbol, dict):
                    raise ValueError("Formula module Symbol declaration is malformed")
                resolved_symbol = symbol.get("resolved_symbol")
                if isinstance(resolved_symbol, dict):
                    coordinate = (
                        resolved_symbol.get("module"),
                        resolved_symbol.get("name"),
                    )
                else:
                    coordinate = (symbol_module, symbol.get("symbol"))
                if not all(isinstance(item, str) for item in coordinate):
                    raise ValueError("Formula module Symbol coordinate is malformed")
                key = cast(tuple[str, str], coordinate)
                if key in self.symbol_contracts:
                    raise _FormulaContextError(
                        "model.reason.name-ambiguity",
                        "Formula module Symbol coordinate is ambiguous",
                    )
                self.resolve_contract(symbol, imports_by_module[symbol_module])
                self.symbol_contracts[key] = {
                    member: deepcopy(value)
                    for member, value in symbol.items()
                    if member
                    not in {"resolved_symbol", "role", "symbol", "value_policy"}
                }
        boolean_contract = fixed_contracts.get("kernel-boolean")
        if not isinstance(boolean_contract, dict):
            raise ValueError("Formula conversion has no Kernel Boolean contract")
        self.boolean_contract = cast(
            dict[str, Any], formula_contract_from_operation(boolean_contract)
        )
        self.literal_semantics = {
            "literal_typing_profiles": [
                {"definition": profile}
                for profile in cast(
                    list[dict[str, Any]],
                    authority_context.language_bundle["language"][
                        "literal_typing_profiles"
                    ],
                )
            ]
        }
        self.locals: dict[str, dict[str, Any]] = {}
        self.grammar, _notation_schema = _notation_authority(authority_context)
        group_delimiters = cast(list[str], self.grammar["group_delimiters"])
        if len(group_delimiters) != 2:
            raise ValueError("Formula notation group delimiters are malformed")
        self.open_group, self.close_group = group_delimiters
        self.notations = _selected_operation_notations(request, authority_context)
        operators = tuple(
            cast(str, item.notation["token"])
            for item in self.notations
            if item.notation.get("kind") == "infix"
            and isinstance(item.notation.get("token"), str)
        )
        if len(expression.encode("utf-8")) > cast(
            int, self.grammar["max_expression_bytes"]
        ):
            raise _FormulaNotationResourceError(
                "Formula expression exceeds its admitted byte bound"
            )
        self.tokens = _lex(expression, operators, self.grammar)
        if len(self.tokens) - 1 > cast(int, self.grammar["max_tokens"]):
            raise _FormulaNotationResourceError(
                "Formula expression exceeds its admitted token bound"
            )
        self.index = 0

    def current(self) -> _Token:
        return self.tokens[self.index]

    def take(self, kind: str, value: str | None = None) -> _Token:
        token = self.current()
        if token.kind != kind or (value is not None and token.value != value):
            expected = value if value is not None else kind
            raise _FormulaNotationSyntaxError(
                f"expected {expected!r} at byte {token.offset}, got {token.value!r}"
            )
        self.index += 1
        return token

    def operation_for(self, *, kind: str, spelling: str) -> _OperationNotation:
        matches = [
            item
            for item in self.notations
            if item.notation.get("kind") == kind
            and item.notation.get("token" if kind == "infix" else "name") == spelling
        ]
        if not matches:
            raise FormulaNotationRefusal(
                "model.reason.unresolved-name",
                f"Formula notation {spelling!r} is unresolved",
            )
        if len(matches) != 1:
            raise FormulaNotationRefusal(
                "model.reason.name-ambiguity",
                f"Formula notation {spelling!r} is ambiguous",
            )
        return matches[0]

    def operand(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        token = self.current()
        if token.kind == "integer":
            self.index += 1
            return {"kind": "literal", "value": int(token.value)}, None
        if token.kind != "identifier":
            raise _FormulaNotationSyntaxError(
                f"expected Formula operand at byte {token.offset}"
            )
        self.index += 1
        segments = [token.value]
        coordinate_separator = cast(str, self.grammar["coordinate_separator"])
        while self.current().kind == coordinate_separator:
            self.index += 1
            segments.append(self.take("identifier").value)
        if len(segments) == 1 and segments[0] in self.locals:
            return (
                {"kind": "local", "local": segments[0]},
                self.locals[segments[0]],
            )
        if len(segments) == 1 and segments[0] in self.contracts:
            return (
                {"kind": "parameter", "parameter": segments[0]},
                self.contracts[segments[0]],
            )
        if len(segments) == 2:
            contract = self.symbol_contracts.get((segments[0], segments[1]))
            if contract is None:
                raise FormulaNotationRefusal(
                    "model.reason.unresolved-name",
                    f"Formula Symbol {'.'.join(segments)!r} is unresolved",
                )
            return (
                {"kind": "symbol", "module": segments[0], "symbol": segments[1]},
                contract,
            )
        raise FormulaNotationRefusal(
            "model.reason.unresolved-name",
            f"Formula name {'.'.join(segments)!r} is unresolved",
        )

    def parenthesized_operand(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        depth = 0
        while self.current().kind == self.open_group:
            self.index += 1
            depth += 1
        parsed = self.operand()
        for _ in range(depth):
            self.take(self.close_group)
        return parsed

    def resolve_contract(
        self,
        contract: dict[str, Any],
        imports: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            resolve_formula_contract(
                contract,
                imports if imports is not None else self.imports,
                self.authority_context.kernel,
                self.policy,
            ),
        )

    def operand_against_formula_contract(
        self,
        operand: dict[str, Any],
        contract: dict[str, Any] | None,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        if contract is None and operand.get("kind") == "literal":
            value = operand.get("value")
            domain = expected.get("domain")
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not isinstance(domain, dict)
                or not isinstance(domain.get("minimum"), int)
                or not isinstance(domain.get("maximum"), int)
                or not domain["minimum"] <= value <= domain["maximum"]
            ):
                raise _FormulaContextError(
                    "model.reason.formula-type-mismatch",
                    "Formula literal is outside its contextual contract",
                )
            contract = expected
        if contract is None or not formula_contract_matches(
            self.resolve_contract(contract),
            self.resolve_contract(expected),
        ):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula operand is incompatible with its formal contract",
            )
        return contract

    def operand_against_operation_contract(
        self,
        operand: dict[str, Any],
        contract: dict[str, Any] | None,
        expected: dict[str, Any],
    ) -> dict[str, Any] | None:
        if contract is None and operand.get("kind") == "literal":
            literal_contract = operation_literal_context_contract(
                operand.get("value"),
                expected,
                self.authority_context.kernel,
                self.literal_semantics,
            )
            if literal_contract is None:
                raise _FormulaContextError(
                    "model.reason.formula-type-mismatch",
                    "Formula operand is incompatible with its Operation port",
                )
            literal_domain = literal_contract.get("domain")
            value = operand.get("value")
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and isinstance(literal_domain, dict)
                and literal_domain.get("kind") == "closed-interval"
            ):
                return cast(
                    dict[str, Any],
                    formula_contract_from_operation(literal_contract)
                    | {
                        "domain_kind": "closed-interval",
                        "domain": {"minimum": value, "maximum": value},
                    },
                )
            return None
        if contract is None or not formula_contract_matches_operation(
            self.resolve_contract(contract), expected
        ):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula operand is incompatible with its Operation port",
            )
        return contract

    def right_hand_side(
        self, local: str
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        conditional_keywords = cast(list[str], self.grammar["conditional_keywords"])
        if (
            self.current().kind == "identifier"
            and self.current().value == conditional_keywords[0]
        ):
            self.index += 1
            condition, condition_contract = self.parenthesized_operand()
            self.operand_against_formula_contract(
                condition,
                condition_contract,
                self.boolean_contract,
            )
            self.take("identifier", conditional_keywords[1])
            when_true, true_contract = self.parenthesized_operand()
            self.take("identifier", conditional_keywords[2])
            when_false, false_contract = self.parenthesized_operand()
            if true_contract is None or false_contract is None:
                raise _FormulaContextError(
                    "model.reason.formula-type-mismatch",
                    "Formula conditional branch contract cannot be inferred",
                )
            if not formula_contract_matches(
                self.resolve_contract(true_contract),
                self.resolve_contract(false_contract),
            ):
                raise _FormulaContextError(
                    "model.reason.formula-type-mismatch",
                    "Formula conditional branches are incompatible",
                )
            return [
                (
                    {
                        "id": local,
                        "node": "conditional",
                        "condition": condition,
                        "when_true": when_true,
                        "when_false": when_false,
                    },
                    deepcopy(true_contract),
                )
            ]
        if (
            self.current().kind == "identifier"
            and self.tokens[self.index + 1].kind == self.grammar["coordinate_separator"]
            and self.tokens[self.index + 2].kind == "identifier"
            and self.tokens[self.index + 3].kind == self.open_group
        ):
            module = self.take("identifier").value
            self.take(cast(str, self.grammar["coordinate_separator"]))
            formula_id = self.take("identifier").value
            resolved_declaration = self.formula_declarations.get((module, formula_id))
            if resolved_declaration is None:
                raise _FormulaContextError(
                    "model.reason.unresolved-name",
                    "Formula call coordinate is unresolved",
                )
            declaration, declaration_imports = resolved_declaration
            self.take(self.open_group)
            arguments: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
            if self.current().kind != self.close_group:
                while True:
                    parameter = self.take("identifier").value
                    self.take(cast(str, self.grammar["named_argument_operator"]))
                    if parameter in arguments:
                        raise _FormulaContextError(
                            "model.reason.name-ambiguity",
                            "Formula call repeats a named argument",
                        )
                    arguments[parameter] = self.parenthesized_operand()
                    if self.current().kind != self.grammar["argument_separator"]:
                        break
                    self.index += 1
            self.take(self.close_group)
            parameters = declaration.get("parameters")
            result = declaration.get("result")
            if not isinstance(parameters, list) or not isinstance(result, dict):
                raise ValueError("Formula call declaration is incomplete")
            resolved_parameters = {
                cast(str, item["id"]): {
                    key: deepcopy(value) for key, value in item.items() if key != "id"
                }
                for item in parameters
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for contract in resolved_parameters.values():
                self.resolve_contract(contract, declaration_imports)
            parameter_ids = list(resolved_parameters)
            if set(arguments) != set(parameter_ids) or len(parameter_ids) != len(
                parameters
            ):
                raise _FormulaContextError(
                    "model.reason.formula-type-mismatch",
                    "Formula call does not totally bind its parameters",
                )
            for parameter, (operand, contract) in arguments.items():
                self.operand_against_formula_contract(
                    operand,
                    contract,
                    self.resolve_contract(
                        resolved_parameters[parameter], declaration_imports
                    ),
                )
            return [
                (
                    {
                        "id": local,
                        "node": "formula-call",
                        "formula": {"module": module, "id": formula_id},
                        "arguments": [
                            {"parameter": parameter, "operand": arguments[parameter][0]}
                            for parameter in sorted(arguments)
                        ],
                    },
                    self.resolve_contract(deepcopy(result), declaration_imports),
                )
            ]
        if (
            self.current().kind == "identifier"
            and self.tokens[self.index + 1].kind == self.open_group
        ):
            name = self.take("identifier").value
            operation = self.operation_for(kind="function", spelling=name)
            self.take(self.open_group)
            operands: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
            if self.current().kind != self.close_group:
                operands.append(self.parenthesized_operand())
                while self.current().kind == self.grammar["argument_separator"]:
                    self.index += 1
                    operands.append(self.parenthesized_operand())
            self.take(self.close_group)
            return [self.operation_node(local, operation, operands)]
        return self.infix_bindings(local)

    def infix_bindings(self, local: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Parse one infix RHS with authority-declared precedence and associativity."""
        output: list[
            tuple[dict[str, Any], dict[str, Any] | None] | _OperationNotation
        ] = []
        operators: list[_OperationNotation | None] = []
        expect_operand = True
        operator_count = 0

        def precedence(operation: _OperationNotation) -> int:
            value = operation.notation.get("precedence")
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("Formula infix precedence is malformed")
            return value

        def reduce_operator() -> None:
            operation = operators.pop()
            if operation is None:
                raise _FormulaNotationSyntaxError(
                    "Formula infix grouping is unbalanced"
                )
            output.append(operation)

        while self.current().kind != self.grammar["binding_terminator"]:
            token = self.current()
            if expect_operand:
                if token.kind == self.open_group:
                    operators.append(None)
                    self.index += 1
                    continue
                if token.kind not in {"identifier", "integer"}:
                    raise _FormulaNotationSyntaxError(
                        f"expected Formula operand at byte {token.offset}"
                    )
                output.append(self.operand())
                expect_operand = False
                continue
            if token.kind == self.close_group:
                while operators and operators[-1] is not None:
                    reduce_operator()
                if not operators:
                    raise _FormulaNotationSyntaxError(
                        f"unmatched Formula group at byte {token.offset}"
                    )
                operators.pop()
                self.index += 1
                continue
            if token.kind != "operator":
                raise _FormulaNotationSyntaxError(
                    f"expected Formula infix operator at byte {token.offset}"
                )
            incoming = self.operation_for(kind="infix", spelling=token.value)
            incoming_precedence = precedence(incoming)
            associativity = incoming.notation.get("associativity")
            if associativity not in {"left", "none", "right"}:
                raise ValueError("Formula infix associativity is malformed")
            while operators and operators[-1] is not None:
                top = cast(_OperationNotation, operators[-1])
                top_precedence = precedence(top)
                if top_precedence < incoming_precedence:
                    break
                if top_precedence == incoming_precedence:
                    if associativity == "right":
                        break
                    if associativity == "none":
                        raise _FormulaNotationSyntaxError(
                            "Formula non-associative infix cannot be chained"
                        )
                reduce_operator()
            operators.append(incoming)
            operator_count += 1
            self.index += 1
            expect_operand = True
        if expect_operand or operator_count == 0:
            raise _FormulaNotationSyntaxError("Formula infix expression is incomplete")
        max_nodes = self.policy.get("max_nodes_per_formula")
        if (
            not isinstance(max_nodes, int)
            or isinstance(max_nodes, bool)
            or len(self.locals) + operator_count > max_nodes
        ):
            raise _FormulaNotationResourceError(
                "Formula infix expansion exceeds its admitted node bound"
            )
        while operators:
            reduce_operator()

        values: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        bindings: list[tuple[dict[str, Any], dict[str, Any]]] = []
        separator = self.conversion_policy.get("infix_parser", {}).get(
            "generated_local_separator"
        )
        if not isinstance(separator, str) or not separator:
            raise ValueError("Formula infix generated-local policy is malformed")
        reduction = 0
        for item in output:
            if not isinstance(item, _OperationNotation):
                values.append(item)
                continue
            if len(values) < 2:
                raise _FormulaNotationSyntaxError("Formula infix arity is malformed")
            right = values.pop()
            left = values.pop()
            reduction += 1
            target = (
                local
                if reduction == operator_count
                else f"{local}{separator}{reduction}"
            )
            if target != local and (target in self.locals or target in self.contracts):
                raise _FormulaContextError(
                    "model.reason.name-ambiguity",
                    "Formula generated local identity is ambiguous",
                )
            node, contract = self.operation_node(target, item, [left, right])
            bindings.append((node, contract))
            values.append(({"kind": "local", "local": target}, contract))
        if len(values) != 1 or len(bindings) != operator_count:
            raise _FormulaNotationSyntaxError("Formula infix reduction is malformed")
        return bindings

    def operation_node(
        self,
        local: str,
        operation: _OperationNotation,
        operands: list[tuple[dict[str, Any], dict[str, Any] | None]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ports = operation.notation.get("ordered_ports")
        if not isinstance(ports, list) or len(ports) != len(operands):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula call does not totally bind notation ports",
            )
        inputs = operation.declaration.get("inputs")
        if not isinstance(inputs, list):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula Operation has no formal port contracts",
            )
        formals = {
            item.get("id"): item
            for item in inputs
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if set(ports) != set(formals) or len(formals) != len(inputs):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula notation ports do not close Operation inputs",
            )
        typed_operands = [
            (
                operand,
                self.operand_against_operation_contract(
                    operand,
                    contract,
                    cast(dict[str, Any], formals[port]),
                ),
            )
            for port, (operand, contract) in zip(ports, operands, strict=True)
        ]
        result = self.infer_operation_result(operation, ports, typed_operands)
        arguments = [
            {"port": port, "operand": operand}
            for port, (operand, _contract) in zip(ports, operands, strict=True)
        ]
        arguments.sort(key=lambda argument: cast(str, argument["port"]))
        node = {
            "id": local,
            "node": "operation-call",
            "operation": {
                "package": operation.coordinate[0],
                "version": operation.coordinate[1],
                "id": operation.coordinate[2],
            },
            "arguments": arguments,
            "result": result,
        }
        return node, result

    def infer_operation_result(
        self,
        operation: _OperationNotation,
        ports: list[Any],
        operands: list[tuple[dict[str, Any], dict[str, Any] | None]],
    ) -> dict[str, Any]:
        fallback = self.formula.get("result")
        if not isinstance(fallback, dict):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula local result cannot be inferred",
            )
        anchor = next(
            (contract for _operand, contract in operands if isinstance(contract, dict)),
            self.resolve_contract(fallback),
        )
        if (
            self.conversion_policy.get("literal_result_inference")
            != "contextual-anchor"
        ):
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                "Formula literal result-inference policy is malformed",
            )
        contracts = [
            cast(dict[str, Any], contract or anchor) for _operand, contract in operands
        ]
        try:
            return infer_formula_operation_result(
                operation.declaration,
                [cast(str, port) for port in ports],
                contracts,
                self.resolve_contract(fallback),
                self.conversion_policy,
                self.source_type_aliases,
            )
        except ValueError as err:
            raise _FormulaContextError(
                "model.reason.formula-type-mismatch",
                str(err),
            ) from err

    def parse(self) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        while (
            self.current().kind == "identifier"
            and self.current().value == self.grammar["binding_keyword"]
        ):
            self.index += 1
            local = self.take("identifier").value
            if local in self.locals or local in self.contracts:
                raise _FormulaContextError(
                    "model.reason.name-ambiguity",
                    "Formula local identity is duplicate or captures a parameter",
                )
            self.take(cast(str, self.grammar["named_argument_operator"]))
            bindings = self.right_hand_side(local)
            self.take(cast(str, self.grammar["binding_terminator"]))
            for node, contract in bindings:
                nodes.append(node)
                self.locals[cast(str, node["id"])] = contract
        result, contract = self.parenthesized_operand()
        self.take("eof")
        self.operand_against_formula_contract(
            result,
            contract,
            self.result_contract,
        )
        if not nodes and result.get("kind") == "parameter":
            return {"node": "parameter", "parameter": result["parameter"]}
        return {"nodes": nodes, "result": result}


def parse_formula_expression(
    request: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
) -> dict[str, Any]:
    """Parse one contextual expression into a canonical structured Formula body."""
    formula = request.get("formula")
    expression = formula.get("expression") if isinstance(formula, dict) else None
    if not isinstance(expression, str):
        raise FormulaNotationRefusal(
            "formula.reason.notation-parse-failure",
            "Formula parse request has no expression",
        )
    try:
        return _FormulaParser(expression, request, authority_context).parse()
    except _FormulaNotationResourceError as err:
        raise FormulaNotationRefusal(
            "formula.reason.notation-resource-exhausted", str(err)
        ) from err
    except _FormulaNotationSyntaxError as err:
        raise FormulaNotationRefusal(
            "formula.reason.notation-parse-failure", str(err)
        ) from err
    except FormulaNotationRefusal:
        raise
    except ValueError as err:
        raise _contextual_refusal(err) from err


def admit_formula_pair(
    request: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
    *,
    canonical_body: dict[str, Any] | None = None,
) -> None:
    """Require one Formula body/expression pair to be exact and reversible."""
    formula = request.get("formula")
    if not isinstance(formula, dict):
        raise ValueError("Formula pair request has no declaration")
    body = formula.get("body")
    expression = formula.get("expression")
    if not isinstance(body, dict) or not isinstance(expression, str):
        raise ValueError("Formula pair request is structurally incomplete")
    try:
        rendered = render_formula_body(body, authority_context)
    except FormulaNotationRefusal as err:
        raise FormulaPairRefusal(err.reason_id, "body", err.message) from err
    if expression != rendered:
        raise FormulaPairRefusal(
            "model.reason.formula-notation-mismatch",
            "expression",
            "Formula expression is not the canonical projection of its body",
        )
    try:
        parsed = parse_formula_expression(request, authority_context)
    except FormulaNotationRefusal as err:
        raise FormulaPairRefusal(err.reason_id, "expression", err.message) from err
    if canonical_bytes(cast(JsonValue, parsed)) != canonical_bytes(
        cast(JsonValue, canonical_body if canonical_body is not None else body)
    ):
        raise FormulaPairRefusal(
            "model.reason.formula-notation-mismatch",
            "expression",
            "Formula expression does not reconstruct its canonical body",
        )


def _render_operand(operand: object, grammar: dict[str, Any]) -> str:
    if not isinstance(operand, dict):
        raise ValueError("Formula notation operand must be an object")
    kind = operand.get("kind")
    if kind == "parameter":
        return _identifier(operand.get("parameter"), grammar)
    if kind == "local":
        return _identifier(operand.get("local"), grammar)
    if kind == "symbol":
        resolved_symbol = operand.get("resolved_symbol")
        if isinstance(resolved_symbol, dict):
            return cast(str, grammar["coordinate_separator"]).join(
                (
                    _identifier(resolved_symbol.get("module"), grammar),
                    _identifier(resolved_symbol.get("name"), grammar),
                )
            )
        return cast(str, grammar["coordinate_separator"]).join(
            (
                _identifier(operand.get("module"), grammar),
                _identifier(operand.get("symbol"), grammar),
            )
        )
    if kind == "literal" and isinstance(operand.get("value"), int):
        return str(operand["value"])
    raise ValueError("Formula notation operand kind is not admitted")


def _render_operation_call(
    node: dict[str, Any],
    catalog: dict[tuple[str, str, str], dict[str, Any]],
    grammar: dict[str, Any],
    notation_schema: dict[str, Any],
) -> str:
    coordinate = node.get("operation")
    if not isinstance(coordinate, dict):
        raise ValueError("Formula operation call has no exact coordinate")
    operation = catalog.get(
        (
            cast(str, coordinate.get("package")),
            cast(str, coordinate.get("version")),
            cast(str, coordinate.get("id")),
        )
    )
    if operation is None or operation.get("purity") != "pure":
        raise FormulaNotationRefusal(
            "model.reason.unresolved-name",
            "Formula operation call is unresolved or effectful",
        )
    notation = _validated_operation_notation(operation, grammar, notation_schema)
    if notation is None:
        raise ValueError("Formula operation has no admitted notation declaration")
    arguments = node.get("arguments")
    ordered_ports = notation.get("ordered_ports")
    if not isinstance(arguments, list) or not isinstance(ordered_ports, list):
        raise _FormulaContextError(
            "model.reason.formula-type-mismatch",
            "Formula notation has no total ordered port mapping",
        )
    by_port = {
        argument.get("port"): argument.get("operand")
        for argument in arguments
        if isinstance(argument, dict)
    }
    if set(by_port) != set(ordered_ports) or len(by_port) != len(arguments):
        raise _FormulaContextError(
            "model.reason.formula-type-mismatch",
            "Formula operation arguments do not match notation ports",
        )
    rendered = [_render_operand(by_port[port], grammar) for port in ordered_ports]
    if notation.get("kind") == "infix" and len(rendered) == 2:
        token = notation.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("Formula infix notation has no token")
        return f"{rendered[0]} {token} {rendered[1]}"
    if notation.get("kind") == "function":
        name = notation.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Formula function notation has no name")
        separator = cast(str, grammar["argument_separator"]) + " "
        delimiters = cast(list[str], grammar["group_delimiters"])
        return f"{name}{delimiters[0]}{separator.join(rendered)}{delimiters[1]}"
    raise ValueError("Formula notation declaration kind is not admitted")


def _render_formula_call(node: dict[str, Any], grammar: dict[str, Any]) -> str:
    coordinate = node.get("formula")
    arguments = node.get("arguments")
    if not isinstance(coordinate, dict) or not isinstance(arguments, list):
        raise ValueError("Formula call has no coordinate or named arguments")
    name = cast(str, grammar["coordinate_separator"]).join(
        (
            _identifier(coordinate.get("module"), grammar),
            _identifier(coordinate.get("id"), grammar),
        )
    )
    normalized: list[tuple[str, str]] = []
    for argument in arguments:
        if not isinstance(argument, dict):
            raise ValueError("Formula call argument must be an object")
        parameter = argument.get("parameter")
        normalized.append(
            (
                _identifier(parameter, grammar),
                _render_operand(argument.get("operand"), grammar),
            )
        )
    normalized.sort(key=lambda item: item[0])
    separator = cast(str, grammar["argument_separator"]) + " "
    assignment = f" {grammar['named_argument_operator']} "
    delimiters = cast(list[str], grammar["group_delimiters"])
    rendered_arguments = separator.join(
        key + assignment + value for key, value in normalized
    )
    return f"{name}{delimiters[0]}{rendered_arguments}{delimiters[1]}"


def _render_formula_body(
    body: object,
    authority_context: AdmittedAuthorityContext,
) -> str:
    """Render one structured Formula body from sealed operation notation."""
    grammar, notation_schema = _notation_authority(authority_context)
    if not isinstance(body, dict):
        raise ValueError("Formula body must be an object")
    if set(body) == {"node", "parameter"} and body.get("node") == "parameter":
        return _identifier(body.get("parameter"), grammar)
    nodes = body.get("nodes")
    result = body.get("result")
    if not isinstance(nodes, list) or not isinstance(result, dict):
        raise ValueError("Formula body is not an admitted program")
    catalog = _operation_catalog(authority_context)
    lines: list[str] = []
    seen_locals: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("Formula node has no admitted renderer")
        local = node.get("id")
        if not isinstance(local, str) or local in seen_locals:
            raise ValueError("Formula local identities must be unique")
        seen_locals.add(local)
        if node.get("node") == "operation-call":
            expression = _render_operation_call(node, catalog, grammar, notation_schema)
        elif node.get("node") == "formula-call":
            expression = _render_formula_call(node, grammar)
        elif node.get("node") == "conditional":
            conditional_keywords = cast(list[str], grammar["conditional_keywords"])
            expression = (
                f"{conditional_keywords[0]} "
                f"{_render_operand(node.get('condition'), grammar)} "
                f"{conditional_keywords[1]} "
                f"{_render_operand(node.get('when_true'), grammar)} "
                f"{conditional_keywords[2]} "
                f"{_render_operand(node.get('when_false'), grammar)}"
            )
        else:
            raise ValueError("Formula node has no admitted renderer")
        lines.append(
            f"{grammar['binding_keyword']} {_identifier(local, grammar)} "
            f"{grammar['named_argument_operator']} {expression}"
            f"{grammar['binding_terminator']}"
        )
    lines.append(_render_operand(result, grammar))
    return "\n".join(lines)


def render_formula_body(
    body: object,
    authority_context: AdmittedAuthorityContext,
) -> str:
    """Render one body and type every authority or contextual refusal."""
    try:
        return _render_formula_body(body, authority_context)
    except FormulaNotationRefusal:
        raise
    except ValueError as err:
        raise _contextual_refusal(err) from err
