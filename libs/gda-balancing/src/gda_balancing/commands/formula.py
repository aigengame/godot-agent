"""Schema 2.0 Formula notation conversion commands."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.envelope import UnreadableInputError
from gda_balancing.schema2.authority import packaged_authority_context
from gda_balancing.schema2.canonical import JsonValue, content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    RefusalStage,
    Schema2Diagnostic,
    Schema2RefusalReport,
    reason_by_id,
)
from gda_balancing.schema2.formula_notation import (
    FormulaNotationRefusal,
    admit_formula_pair,
    formula_notation_request_identity_domain,
    parse_formula_expression,
    render_formula_body,
)
from gda_balancing.schema2.model import refusal_catalog_for_reasons


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


def _read_request(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_bytes())
    except OSError as err:
        raise UnreadableInputError from err
    if not isinstance(value, dict):
        raise ValueError("Formula conversion request must be an object")
    return value


def run_formula_render(
    inp: FormulaRenderInput,
) -> FormulaConversionResult | Schema2RefusalReport:
    request = _read_request(inp.source)
    formula = request.get("formula")
    if not isinstance(formula, dict) or not isinstance(formula.get("body"), dict):
        authority_context = packaged_authority_context()
        return _formula_refusal_report(
            request,
            authority_context.language_bundle,
            FormulaNotationRefusal(
                "model.reason.source-contract-mismatch",
                "Formula render request has no structured body",
            ),
            identity_domain=formula_notation_request_identity_domain(authority_context),
            pointer="/formula/body",
        )
    authority_context = packaged_authority_context()
    body = formula["body"]
    try:
        expression = render_formula_body(body, authority_context)
        paired_request = deepcopy(request)
        paired_formula = cast(dict[str, Any], paired_request["formula"])
        paired_formula["expression"] = expression
        admit_formula_pair(paired_request, authority_context)
    except FormulaNotationRefusal as err:
        return _formula_refusal_report(
            request,
            authority_context.language_bundle,
            err,
            identity_domain=formula_notation_request_identity_domain(authority_context),
            pointer="/formula/body",
        )
    return FormulaConversionResult(
        body=body,
        expression=expression,
        kernel_identity=authority_context.kernel["content_identity"],
        language_bundle_identity=authority_context.language_bundle["content_identity"],
    )


def run_formula_parse(
    inp: FormulaParseInput,
) -> FormulaConversionResult | Schema2RefusalReport:
    request = _read_request(inp.source)
    authority_context = packaged_authority_context()
    try:
        body = parse_formula_expression(request, authority_context)
    except FormulaNotationRefusal as err:
        return _formula_refusal_report(
            request,
            authority_context.language_bundle,
            err,
            identity_domain=formula_notation_request_identity_domain(authority_context),
            pointer="/formula/expression",
        )
    return FormulaConversionResult(
        body=body,
        expression=render_formula_body(body, authority_context),
        kernel_identity=authority_context.kernel["content_identity"],
        language_bundle_identity=authority_context.language_bundle["content_identity"],
    )


def _formula_refusal_report(
    request: dict[str, Any],
    language_bundle: dict[str, Any],
    refusal: FormulaNotationRefusal,
    *,
    identity_domain: str,
    pointer: str,
) -> Schema2RefusalReport:
    reason = reason_by_id(language_bundle, refusal.reason_id)
    request_identity = content_identity(identity_domain, cast(JsonValue, request))
    return Schema2RefusalReport(
        stage=cast(RefusalStage, reason["stage"]),
        diagnostics=(
            Schema2Diagnostic(
                code=cast(str, reason["diagnostic"]),
                message=refusal.message,
                primary=ArtifactLocation(
                    content_identity=request_identity,
                    pointer=pointer,
                ),
            ),
        ),
        truncated=False,
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
    "imports": [{"alias": "quantity", "package": "core.quantity", "version": "2.1.0", "symbol": "Quantity"}]
  },
  "formula": {
    "id": "identity",
    "parameters": [{"id": "value"}],
    "result": {},
    "body": {"node": "parameter", "parameter": "value"}
  }
}"""

_VALID_PARSE_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {"id": "main", "imports": []},
  "formula": {
    "id": "identity",
    "parameters": [{"id": "value"}],
    "result": {},
    "expression": "value"
  }
}"""

_REFUSING_PARSE_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {"id": "main", "imports": []},
  "formula": {
    "id": "identity",
    "parameters": [{"id": "value"}],
    "result": {},
    "expression": "identity(value"
  }
}"""

_REFUSING_RENDER_REQUEST = """{
  "schema_version": "2.0.0",
  "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
  "module": {"id": "main", "imports": []},
  "formula": {
    "id": "unknown-operation",
    "parameters": [{"id": "value"}],
    "result": {},
    "body": {
      "nodes": [{
        "id": "result",
        "node": "operation-call",
        "operation": {"package": "core.quantity", "version": "2.1.0", "id": "quantity.unknown"},
        "arguments": [{"port": "value", "operand": {"kind": "parameter", "parameter": "value"}}],
        "result": {}
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
            "model.reason.source-contract-mismatch",
        )
    ),
    usage_codes=(
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
