"""Schema 2.0 Formula notation conversion commands."""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.formula_conversion import parse_formula, render_formula
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.infrastructure.input_bytes import InputReadError
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model.resolution import refusal_catalog_for_reasons


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


def run_formula_render(
    inp: FormulaRenderInput,
) -> FormulaConversionResult | Schema2RefusalReport:
    try:
        result = render_formula(inp.source, packaged_authority_context)
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


def run_formula_parse(
    inp: FormulaParseInput,
) -> FormulaConversionResult | Schema2RefusalReport:
    try:
        result = parse_formula(inp.source, packaged_authority_context)
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


def _formula_conversion_result_schema() -> dict[str, object]:
    language = cast(
        dict[str, Any], packaged_authority_context().language_bundle["language"]
    )
    source_schema = next(
        cast(dict[str, Any], item["schema"])
        for item in cast(list[dict[str, Any]], language["wire_schemas"])
        if item.get("artifact_kind") == "model-source-package"
    )
    body_schema = source_schema["properties"]["modules"]["items"]["properties"][
        "formulas"
    ]["items"]["properties"]["body"]
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


_VALID_RENDER_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {
    "id": "main",
    "imports": []
  },
  "formula": {
    "id": "identity",
    "parameters": [{"id": "value", "type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"}],
    "result": {"type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"},
    "body": {"node": "parameter", "parameter": "value"}
  }
}"""

_VALID_PARSE_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {"id": "main", "imports": []},
  "formula": {
    "id": "identity",
    "parameters": [{"id": "value", "type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"}],
    "result": {"type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"},
    "expression": "value"
  }
}"""

_REFUSING_PARSE_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {"id": "main", "imports": []},
  "formula": {
    "id": "identity",
    "parameters": [{"id": "value", "type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"}],
    "result": {"type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"},
    "expression": "identity(value"
  }
}"""

_REFUSING_RENDER_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {"id": "main", "imports": []},
  "formula": {
    "id": "unknown-operation",
    "parameters": [{"id": "value", "type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"}],
    "result": {"type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"},
    "body": {
      "nodes": [{
        "id": "result",
        "node": "operation-call",
        "operation": {"package": "core.quantity", "version": "2.1.0", "id": "quantity.unknown"},
        "arguments": [{"port": "value", "operand": {"kind": "parameter", "parameter": "value"}}],
        "result": {"type": "Boolean", "representation": "Bool", "kind": "boolean", "unit": "1", "domain": {"kind": "boolean"}, "numeric_policy": "exact-bool"}
      }],
      "result": {"kind": "local", "local": "result"}
    }
  }
}"""


FORMULA_PARSE = CommandDescriptor(
    group="formula",
    command="parse",
    description="Parse mathematical notation into a canonical structured Formula body.",
    input_model=FormulaParseInput,
    output_model=FormulaConversionResult,
    handler=run_formula_parse,
    fixtures=ConformanceFixtures(
        valid_document=_VALID_PARSE_REQUEST,
        refusing_document=_REFUSING_PARSE_REQUEST,
    ),
    positional_field="source",
    schema_major=2,
    structured_params=True,
    success_schema=_formula_conversion_result_schema,
    refusal_catalog=refusal_catalog_for_reasons(
        (
            "formula.reason.notation-parse-failure",
            "formula.reason.notation-resource-exhausted",
            "model.reason.unresolved-name",
            "model.reason.name-ambiguity",
            "model.reason.formula-type-mismatch",
            "model.reason.source-parse-failure",
            "model.reason.source-too-large",
            "model.reason.source-contract-mismatch",
        )
    ),
    usage_codes=(
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)


FORMULA_RENDER = CommandDescriptor(
    group="formula",
    command="render",
    description="Render a structured Formula body as canonical mathematical notation.",
    input_model=FormulaRenderInput,
    output_model=FormulaConversionResult,
    handler=run_formula_render,
    fixtures=ConformanceFixtures(
        valid_document=_VALID_RENDER_REQUEST,
        refusing_document=_REFUSING_RENDER_REQUEST,
    ),
    positional_field="source",
    schema_major=2,
    structured_params=True,
    success_schema=_formula_conversion_result_schema,
    refusal_catalog=refusal_catalog_for_reasons(
        (
            "model.reason.unresolved-name",
            "model.reason.name-ambiguity",
            "model.reason.formula-notation-mismatch",
            "model.reason.formula-type-mismatch",
            "model.reason.source-parse-failure",
            "model.reason.source-too-large",
            "model.reason.source-contract-mismatch",
        )
    ),
    usage_codes=(
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
