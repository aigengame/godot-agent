"""Formula notation conversion use cases."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from gda_balancing.domain.formula import notation
from gda_balancing.domain.formula.conversion import (
    FormulaConversion,
    formula_refusal_report,
    parse_formula_request,
    read_formula_request,
    render_formula_request,
)
from gda_balancing.infrastructure.input_bytes import (
    InputTooLargeError,
    read_bounded_input,
)
from gda_balancing.schema2.authority import AdmittedAuthorityContext
from gda_balancing.schema2.diagnostics import Schema2RefusalReport


FormulaAuthorityProvider = Callable[[], AdmittedAuthorityContext]


@dataclass(frozen=True)
class FormulaConversionReport:
    """A Formula conversion paired with its authority identities."""

    body: dict[str, Any]
    expression: str
    kernel_identity: str
    language_bundle_identity: str


def _convert_formula(
    source: str,
    provider: FormulaAuthorityProvider,
    mode: Literal["render", "parse"],
) -> FormulaConversionReport | Schema2RefusalReport:
    context = provider()
    identity_domain = notation.formula_notation_request_identity_domain(context)
    max_bytes = cast(int, context.language_bundle["resources"]["max_source_bytes"])
    try:
        data = read_bounded_input(source, max_bytes)
    except InputTooLargeError:
        refusal = notation.FormulaNotationRefusal(
            "model.reason.source-too-large",
            "Formula conversion request exceeds the admitted ingress bound",
        )
        return formula_refusal_report(
            {},
            context.language_bundle,
            refusal,
            identity_domain=identity_domain,
            pointer="",
        )
    try:
        request = read_formula_request(data)
    except notation.FormulaNotationRefusal as err:
        return formula_refusal_report(
            {},
            context.language_bundle,
            err,
            identity_domain=identity_domain,
            pointer="",
        )
    try:
        conversion: FormulaConversion = (
            render_formula_request(request, context)
            if mode == "render"
            else parse_formula_request(request, context)
        )
    except notation.FormulaNotationRefusal as err:
        return formula_refusal_report(
            request,
            context.language_bundle,
            err,
            identity_domain=identity_domain,
            pointer="/formula/body" if mode == "render" else "/formula/expression",
        )
    return FormulaConversionReport(
        body=conversion.body,
        expression=conversion.expression,
        kernel_identity=context.kernel["content_identity"],
        language_bundle_identity=context.language_bundle["content_identity"],
    )


def render_formula(
    source: str,
    provider: FormulaAuthorityProvider,
) -> FormulaConversionReport | Schema2RefusalReport:
    """Render a structured Formula body as canonical notation."""
    return _convert_formula(source, provider, "render")


def parse_formula(
    source: str,
    provider: FormulaAuthorityProvider,
) -> FormulaConversionReport | Schema2RefusalReport:
    """Parse notation into a canonical structured Formula body."""
    return _convert_formula(source, provider, "parse")
