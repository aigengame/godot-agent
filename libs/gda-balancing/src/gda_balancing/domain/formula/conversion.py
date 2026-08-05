"""Canonical Formula body and mathematical-notation conversion."""

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.formula import notation
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.canonical import (
    JsonValue,
    content_identity,
    parse_canonical_object,
)
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    RefusalStage,
    Schema2Diagnostic,
    Schema2RefusalReport,
    reason_by_id,
)


@dataclass(frozen=True)
class FormulaConversion:
    """A canonical structured Formula paired with its notation."""

    body: dict[str, Any]
    expression: str


def read_formula_request(data: bytes) -> dict[str, Any]:
    """Admit one canonical Formula conversion request document."""
    try:
        return parse_canonical_object(data, artifact_name="Formula conversion request")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as err:
        raise notation.FormulaNotationRefusal(
            "model.reason.source-parse-failure",
            f"Formula conversion request is outside canonical JSON: {err}",
        ) from err


def render_formula_request(
    request: dict[str, Any],
    context: AdmittedAuthorityContext,
) -> FormulaConversion:
    """Render and reverse-admit one structured Formula body."""
    formula = request.get("formula")
    if not isinstance(formula, dict) or not isinstance(formula.get("body"), dict):
        raise notation.FormulaNotationRefusal(
            "model.reason.source-contract-mismatch",
            "Formula render request has no structured body",
        )
    body = cast(dict[str, Any], formula["body"])
    expression = notation.render_formula_body(body, context)
    paired_request = deepcopy(request)
    paired_formula = cast(dict[str, Any], paired_request["formula"])
    paired_formula["expression"] = expression
    notation.admit_formula_pair(paired_request, context)
    return FormulaConversion(body=body, expression=expression)


def parse_formula_request(
    request: dict[str, Any],
    context: AdmittedAuthorityContext,
) -> FormulaConversion:
    """Parse notation and reverse-admit its canonical Formula pair."""
    body = notation.parse_formula_expression(request, context)
    expression = notation.render_formula_body(body, context)
    paired_request = deepcopy(request)
    paired_formula = cast(dict[str, Any], paired_request["formula"])
    paired_formula["body"] = body
    paired_formula["expression"] = expression
    notation.admit_formula_pair(paired_request, context)
    return FormulaConversion(body=body, expression=expression)


def formula_refusal_report(
    request: dict[str, Any],
    language_bundle: dict[str, Any],
    refusal: notation.FormulaNotationRefusal,
    *,
    identity_domain: str,
    pointer: str,
) -> Schema2RefusalReport:
    """Project one Formula refusal through LDB-owned diagnostic policy."""
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
