"""Schema 2.0 Formula notation conversion commands."""

from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.formula_conversion import parse_formula, render_formula
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    authority_context_handler,
)
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.application.authority import admit_command_authority
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    packaged_authority_context,
    resolve_authority_context,
)
from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.diagnostics import (
    refusal_catalog_for_reasons,
    source_resolution_profile,
)
from gda_balancing.domain.authority.source_projection import (
    author_source_value,
    source_schema_member,
)


class FormulaRenderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str


class FormulaParseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str


class FormulaConversionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    body: dict[str, Any]
    expression: str
    kernel_identity: str
    language_bundle_identity: str


def _formula_authority_context() -> AdmittedAuthorityContext:
    """Resolve the live packaged provider used by the registered Formula surface."""
    return packaged_authority_context()


def _admitted_formula_context(
    provider: AuthorityContextProvider,
) -> AdmittedAuthorityContext:
    context = resolve_authority_context(provider)
    if isinstance(context, BootstrapAdmission):
        raise ValueError("Formula projection requires admitted authority")
    return context


def _formula_handler(
    convert: Callable[..., Any],
    authority_context_provider: AuthorityContextProvider,
) -> Callable[..., FormulaConversionResult | Schema2RefusalReport]:
    def _run(
        inp: FormulaRenderInput | FormulaParseInput,
        authority_context: AdmittedAuthorityContext | None = None,
    ) -> FormulaConversionResult | Schema2RefusalReport:
        context = authority_context or admit_command_authority(
            authority_context_provider
        )
        if isinstance(context, Schema2RefusalReport):
            return context
        try:
            result = convert(inp.source, lambda: context)
        except InputReadError as err:
            raise UnreadableInputError from err
        if isinstance(result, Schema2RefusalReport):
            return result
        return FormulaConversionResult(
            body=result.body,
            expression=result.expression,
            kernel_identity=result.kernel_identity,
            language_bundle_identity=result.language_bundle_identity,
        )

    return authority_context_handler(_run)


def _formula_conversion_result_schema(
    context: AdmittedAuthorityContext | None = None,
) -> dict[str, object]:
    context = context or packaged_authority_context()
    source_schema = context.source_semantic_index.schema
    members = context.source_native_binding_index.members
    module_schema = source_schema_member(source_schema, members["source.root.modules"])[
        1
    ]["items"]
    formula_schema = source_schema_member(
        module_schema, members["source.module.formulas"]
    )[1]["items"]
    body_schema = source_schema_member(formula_schema, members["source.formula.body"])[
        1
    ]
    return {
        "type": "object",
        "properties": {
            "body": body_schema,
            "expression": {"type": "string"},
            "kernel_identity": {"type": "string"},
            "language_bundle_identity": {"type": "string"},
        },
        "required": [
            "body",
            "expression",
            "kernel_identity",
            "language_bundle_identity",
        ],
        "unevaluatedProperties": False,
    }


def _formula_schemas(
    context: AdmittedAuthorityContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_schema = context.source_semantic_index.schema
    members = context.source_native_binding_index.members
    module_schema = source_schema_member(source_schema, members["source.root.modules"])[
        1
    ]["items"]
    formula_schema = source_schema_member(
        module_schema, members["source.module.formulas"]
    )[1]["items"]
    return dict(module_schema), dict(formula_schema)


def _formula_fixture(
    context: AdmittedAuthorityContext,
    *,
    parsing: bool,
    refusing: bool,
) -> str:
    profile = source_resolution_profile(context.language_bundle)
    aliases = [
        row["alias"]
        for row in profile["formula_resolution"]["fixed_value_type_aliases"]
        if row.get("contract") == "kernel-boolean" and isinstance(row.get("alias"), str)
    ]
    if len(aliases) != 1:
        raise ValueError("Formula fixtures require one Kernel Boolean Source alias")
    fixed = deepcopy(
        dict(
            context.kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
                "kernel-boolean"
            ]
        )
    )
    fixed.pop("type")
    value_contract = {"type": aliases[0], **fixed}
    formula: dict[str, Any] = {
        "id": "identity" if not refusing or parsing else "unknown-operation",
        "parameters": [{"id": "value", **deepcopy(value_contract)}],
        "result": deepcopy(value_contract),
    }
    if parsing:
        formula["expression"] = "identity(value" if refusing else "value"
    elif refusing:
        formula["body"] = {
            "nodes": [
                {
                    "id": "result",
                    "node": "operation-call",
                    "operation": {
                        "package": "core.quantity",
                        "id": "quantity.unknown",
                    },
                    "arguments": [
                        {
                            "port": "value",
                            "operand": {"kind": "parameter", "parameter": "value"},
                        }
                    ],
                    "result": deepcopy(value_contract),
                }
            ],
            "result": {"kind": "local", "local": "result"},
        }
    else:
        formula["body"] = {"node": "parameter", "parameter": "value"}
    module_schema, formula_schema = _formula_schemas(context)
    bindings = context.source_native_binding_index
    module = author_source_value({"id": "main", "imports": []}, module_schema, bindings)
    authored_formula = author_source_value(formula, formula_schema, bindings)
    _, version_schema = source_schema_member(
        context.source_semantic_index.schema,
        bindings.members["source.root.schema_version"],
    )
    return json.dumps(
        {
            "schema_version": version_schema["const"],
            "package_requirements": ["core.quantity"],
            "module": module,
            "formula": authored_formula,
        },
        indent=2,
    )


def _formula_fixture_args(
    authority_context_provider: AuthorityContextProvider,
    *,
    parsing: bool,
) -> Callable[[Path, int, bool], tuple[str, ...]]:
    def prepare(directory: Path, token: int, refusing: bool) -> tuple[str, ...]:
        context = _admitted_formula_context(authority_context_provider)
        path = directory / f"formula-{'parse' if parsing else 'render'}-{token}.json"
        path.write_text(
            _formula_fixture(context, parsing=parsing, refusing=refusing),
            encoding="utf-8",
        )
        return (str(path),)

    return prepare


def _refusal_catalog(
    context: AdmittedAuthorityContext | None = None,
    *,
    parsing: bool,
) -> tuple[tuple[str, str], ...]:
    context = context or packaged_authority_context()
    profile = source_resolution_profile(context.language_bundle)
    reasons = profile["formula_resolution"]["refusal_reasons"]
    categories = ["name-unresolved", "name-ambiguity", "type-mismatch"]
    if parsing:
        categories.extend(["notation-parse", "notation-resource"])
    else:
        categories.append("notation-mismatch")
    selected = [
        profile[member]
        for member in ("parse_reason", "source_byte_reason", "structural_reason")
    ]
    selected.extend(reasons[category] for category in categories)
    return refusal_catalog_for_reasons(dict.fromkeys(selected), context.language_bundle)


def formula_parse_descriptor(
    authority_context_provider: AuthorityContextProvider = _formula_authority_context,
) -> CommandDescriptor:
    return CommandDescriptor(
        group="formula",
        command="parse",
        description=(
            "Parse mathematical notation into a canonical structured Formula body."
        ),
        input_model=FormulaParseInput,
        output_model=FormulaConversionResult,
        handler=_formula_handler(parse_formula, authority_context_provider),
        fixtures=ConformanceFixtures(
            prepare_args=_formula_fixture_args(authority_context_provider, parsing=True)
        ),
        positional_field="source",
        schema_major=2,
        structured_params=True,
        authority_context_provider=authority_context_provider,
        success_schema=lambda: _formula_conversion_result_schema(
            _admitted_formula_context(authority_context_provider)
        ),
        refusal_catalog_provider=lambda context: _refusal_catalog(
            context, parsing=True
        ),
        usage_codes=(
            "invalid_argument",
            "unknown_argument",
            "unreadable_input",
        ),
    )


def formula_render_descriptor(
    authority_context_provider: AuthorityContextProvider = _formula_authority_context,
) -> CommandDescriptor:
    return CommandDescriptor(
        group="formula",
        command="render",
        description=(
            "Render a structured Formula body as canonical mathematical notation."
        ),
        input_model=FormulaRenderInput,
        output_model=FormulaConversionResult,
        handler=_formula_handler(render_formula, authority_context_provider),
        fixtures=ConformanceFixtures(
            prepare_args=_formula_fixture_args(
                authority_context_provider, parsing=False
            )
        ),
        positional_field="source",
        schema_major=2,
        structured_params=True,
        authority_context_provider=authority_context_provider,
        success_schema=lambda: _formula_conversion_result_schema(
            _admitted_formula_context(authority_context_provider)
        ),
        refusal_catalog_provider=lambda context: _refusal_catalog(
            context, parsing=False
        ),
        usage_codes=(
            "invalid_argument",
            "unknown_argument",
            "unreadable_input",
        ),
    )


run_formula_parse = _formula_handler(parse_formula, _formula_authority_context)
run_formula_render = _formula_handler(render_formula, _formula_authority_context)
FORMULA_PARSE = formula_parse_descriptor()
FORMULA_RENDER = formula_render_descriptor()
