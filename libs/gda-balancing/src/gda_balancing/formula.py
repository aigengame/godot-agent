"""The one public formula seam (bADR-0003).

This module is the **single sanctioned formula seam** of bADR-0003. It owns
#504's two **definition-time** evaluators — the named-form interpreter and the
expression-tree walker — behind one public surface, and #510 **reuses this
same seam** for runtime magnitude evaluation rather than growing a second
evaluator. It is also the **authorized external test boundary**: the normative
numeric vectors (V2/V3/V16) are asserted against this module, not against the
model classes.

Numeric contract (bADR-0003, summarized; the bADR is authoritative):

* Values are IEEE-754 doubles. n-ary operators fold strictly **left-to-right**
  over ``args`` and are never reassociated; binary operators apply as
  ``args[0] op args[1]``. ``add``/``subtract``/``multiply``/``divide`` are
  plain, individually-rounded float ops (no FMA contraction).
* ``round`` rounds **half away from zero** (never banker's rounding);
  ``floor``/``ceil``/``round`` preserve the zero's sign; ``min``/``max`` follow
  IEEE 754-2019 minimum/maximum (``min(+0, −0) = −0``, ``max(+0, −0) = +0``).
* Integer-valued ``power`` with ``|n| ≤ 64`` is exact (repeated multiplication;
  ``x^0 = 1`` including ``0^0``; a negative exponent takes a **single**
  reciprocal); everything else uses the platform ``math.pow``.
* **Finiteness** is checked after every operator application and on every
  leaf/env read: any non-finite value (``/0``, overflow, NaN) is an
  :class:`EvaluationRefusal` carrying the stable
  :data:`NON_FINITE_EVALUATION` code — never a propagated ``inf``/``nan``.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from gda_balancing.schema.model.formula import (
    AttrRef,
    Base,
    BinaryOp,
    DirectBase,
    ExponentialForm,
    Formula,
    FormulaBase,
    InputRef,
    LinearForm,
    LiteralNode,
    LookupTableForm,
    NamedForm,
    NaryOp,
    Node,
    OpNode,
    ParamRef,
    PiecewiseLinearForm,
    PolynomialForm,
    ScalarField,
    UnaryOp,
)

if TYPE_CHECKING:
    from gda_balancing.schema.model.attributes import Bounds
    from gda_balancing.schema.model.document import DesignDocument

__all__ = [
    # Refusal contract
    "NON_FINITE_EVALUATION",
    "EvaluationRefusal",
    # Environment + public functions
    "FormulaEnv",
    "parse_formula",
    "evaluate",
    "evaluate_bases",
    # Re-exported model vocabulary
    "Formula",
    "NamedForm",
    "Node",
    "AttrRef",
    "ParamRef",
    "LiteralNode",
    "InputRef",
    "ScalarField",
    "NaryOp",
    "BinaryOp",
    "UnaryOp",
    "OpNode",
    "LinearForm",
    "PiecewiseLinearForm",
    "PolynomialForm",
    "ExponentialForm",
    "LookupTableForm",
    "DirectBase",
    "FormulaBase",
    "Base",
]

# The downstream refusal-code family bADR-0003 sanctions for a non-finite
# evaluation result. It is NOT part of the boundary funnel's semantic rule
# catalog (bADR-0005) — finiteness depends on runtime values the funnel cannot
# see, so the evaluator refuses with this stable code at evaluation time.
NON_FINITE_EVALUATION = "non_finite_evaluation"

# Integer-exponent `power` is exact only on this bounded domain (bADR-0003);
# beyond it, evaluation falls through to the platform `math.pow`.
_EXACT_POWER_BOUND = 64


class EvaluationRefusal(Exception):
    """A formula evaluated to a non-finite value (bADR-0003).

    Carries the stable :data:`NON_FINITE_EVALUATION` ``code`` plus a
    human-readable ``detail``; a downstream consumer maps it onto the refusal
    envelope (bADR-0004). It is raised, never returned — a finite result is the
    only successful outcome.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.code: str = NON_FINITE_EVALUATION
        self.detail: str = detail


@dataclass(frozen=True)
class FormulaEnv:
    """The read environment one formula evaluates against (bADR-0003).

    ``attr_values`` maps attribute id → its observed/definition-time value;
    ``params`` maps parameter id → its document constant. The boundary funnel
    guarantees every referenced id is **declared** before evaluation runs, so a
    missing id here is a **caller bug** (surfacing as ``KeyError``), not an
    :class:`EvaluationRefusal`.
    """

    attr_values: Mapping[str, float]
    params: Mapping[str, float]


_FORMULA_ADAPTER: TypeAdapter[Formula] = TypeAdapter(Formula)


def parse_formula(data: object) -> Formula:
    """Parse a JSON-shaped value into a validated :data:`Formula`.

    Raises ``pydantic.ValidationError`` on any local-shape violation (unknown
    node kind, wrong operator arity, a non-literal collection element, …).
    """
    return _FORMULA_ADAPTER.validate_python(data)


def evaluate(formula: Formula, env: FormulaEnv) -> float:
    """Evaluate a formula against ``env``, returning a finite double.

    Raises :class:`EvaluationRefusal` if any step produces a non-finite value
    (bADR-0003's single sanctioned downstream refusal class).
    """
    if isinstance(
        formula,
        (
            LinearForm,
            PiecewiseLinearForm,
            PolynomialForm,
            ExponentialForm,
            LookupTableForm,
        ),
    ):
        return _eval_form(formula, env)
    return _eval_node(formula, env)


def evaluate_bases(document: "DesignDocument") -> dict[str, float]:
    """The definition-time final value of every attribute base (bADR-0002/0003).

    Evaluates the attributes in topological order of the acyclic base-formula
    graph (bADR-0002): a ``direct`` base yields its configured value; a
    ``formula`` base evaluates against a :class:`FormulaEnv` whose ``attr_values``
    are the finals computed so far — so an ``attr`` node reads the referenced
    attribute's definition-time final. Each result is then clamped to the
    attribute's declared ``bounds`` (``floor`` first, then ``cap``; an absent
    side is unbounded). At definition time the value pipeline has no allocation
    or effect contributions, so the final **is** ``clamp(base, bounds)``
    (bADR-0002), and a dependent formula reads that clamped final.

    **Precondition:** ``document`` has passed the boundary funnel (references
    declared, graph acyclic — bADR-0004); violations are caller bugs, not
    handled here. A non-finite base raises :class:`EvaluationRefusal`
    (bADR-0003's single sanctioned downstream refusal class), which propagates.
    """
    # Lazy import: the seam depends on schema internals, never the reverse
    # (bADR-0003) — and importing at call time keeps the module-load graph free
    # of the funnel package.
    from gda_balancing.schema.funnel.semantic.graph import topological_order

    items = document.attributes.items
    finals: dict[str, float] = {}
    for attr_id in topological_order(document):
        base = items[attr_id].base
        if isinstance(base, DirectBase):
            value = _finite(base.direct, f"base {attr_id!r}")
        else:
            value = evaluate(
                base.formula,
                FormulaEnv(attr_values=finals, params=document.parameters),
            )
        finals[attr_id] = _clamp(value, items[attr_id].bounds)
    return finals


def _clamp(value: float, bounds: "Bounds | None") -> float:
    """Clamp ``value`` to ``bounds`` — ``floor`` first, then ``cap`` — treating
    an absent side as unbounded (bADR-0002)."""
    if bounds is None:
        return value
    if bounds.floor is not None:
        value = max(value, bounds.floor)
    if bounds.cap is not None:
        value = min(value, bounds.cap)
    return value


# --- Finiteness, division, and the signed-zero-aware min/max ---------------


def _finite(value: float, where: str) -> float:
    if not math.isfinite(value):
        raise EvaluationRefusal(f"non-finite value produced by {where}")
    return value


def _divide(dividend: float, divisor: float, where: str) -> float:
    # Python floats RAISE ZeroDivisionError on /0.0 (they do not return inf);
    # both a true division by zero and an overflowing quotient are refusals.
    try:
        quotient = dividend / divisor
    except ZeroDivisionError as exc:
        raise EvaluationRefusal(f"division by zero in {where}") from exc
    return _finite(quotient, where)


def _ieee_min(a: float, b: float) -> float:
    # IEEE 754-2019 minimum. Inputs are already finite (checked at the leaves),
    # so only the signed-zero tie needs special handling — Python's builtin
    # `min` returns the first argument on a tie and would leak `+0` for
    # `min(+0, -0)`.
    if a < b:
        return a
    if b < a:
        return b
    if a == 0.0:  # both are zero; minimum prefers the negative zero
        negative = math.copysign(1.0, a) == -1.0 or math.copysign(1.0, b) == -1.0
        return -0.0 if negative else 0.0
    return a


def _ieee_max(a: float, b: float) -> float:
    # IEEE 754-2019 maximum, mirror of `_ieee_min`.
    if a > b:
        return a
    if b > a:
        return b
    if a == 0.0:  # both are zero; maximum prefers the positive zero
        positive = math.copysign(1.0, a) == 1.0 or math.copysign(1.0, b) == 1.0
        return 0.0 if positive else -0.0
    return a


def _power(base: float, exponent: float) -> float:
    # Integer-valued exponent within the bounded domain: exact via repeated
    # left-to-right multiplication (bADR-0003).
    if exponent == int(exponent) and abs(exponent) <= _EXACT_POWER_BOUND:
        n = int(exponent)
        if n == 0:
            return 1.0  # including 0**0 == 1
        magnitude = base
        for _ in range(abs(n) - 1):
            magnitude = magnitude * base
        if n > 0:
            return magnitude
        # n < 0: a SINGLE reciprocal of x^|n| (so 10^-2 == 1/(10*10)).
        if base == 0.0:
            raise EvaluationRefusal("zero base raised to a negative exponent")
        return 1.0 / magnitude
    # Non-integer or out-of-domain exponent: platform IEEE-754 `pow`, whose
    # final ULP may differ across platforms (bADR-0003 narrows the claim here).
    try:
        return math.pow(base, exponent)
    except (ValueError, OverflowError) as exc:
        raise EvaluationRefusal(f"power out of domain: {base}**{exponent}") from exc


# --- Expression-tree walk --------------------------------------------------


def _eval_node(node: Node, env: FormulaEnv) -> float:
    if isinstance(node, LiteralNode):
        return _finite(node.literal, "literal")
    if isinstance(node, AttrRef):
        return _finite(env.attr_values[node.attr], f"attr {node.attr!r}")
    if isinstance(node, ParamRef):
        return _finite(env.params[node.param], f"param {node.param!r}")
    return _eval_op(node, env)


def _eval_op(node: OpNode, env: FormulaEnv) -> float:
    values = [_eval_node(arg, env) for arg in node.args]
    if isinstance(node, NaryOp):
        result = values[0]
        for operand in values[1:]:
            result = _finite(_combine(node.op, result, operand), node.op)
        return result
    if isinstance(node, BinaryOp):
        return _finite(_combine(node.op, values[0], values[1]), node.op)
    # UnaryOp
    return _eval_unary(node.op, values[0])


def _combine(op: str, a: float, b: float) -> float:
    """One pairwise step of a fold / one binary application. `divide` and
    `power` raise their own refusals; the caller finiteness-checks the rest."""
    if op == "add":
        return a + b
    if op == "subtract":
        return a - b
    if op == "multiply":
        return a * b
    if op == "divide":
        return _divide(a, b, "divide")
    if op == "min":
        return _ieee_min(a, b)
    if op == "max":
        return _ieee_max(a, b)
    # power
    return _power(a, b)


def _eval_unary(op: str, x: float) -> float:
    # floor/ceil/round map to integer values but return floats, preserving the
    # zero's sign; `round` is half-away-from-zero, never banker's rounding.
    if op == "floor":
        return _signed_integral(math.floor(x), x)
    if op == "ceil":
        return _signed_integral(math.ceil(x), x)
    # round: half away from zero — floor(|x| + 0.5) re-signed.
    magnitude = math.floor(abs(x) + 0.5)
    return _signed_integral(math.copysign(magnitude, x), x)


def _signed_integral(result: float, original: float) -> float:
    # `math.floor`/`math.ceil` return int, losing −0.0; re-attach the sign on a
    # zero result so floor(-0.0) stays −0.0 (bADR-0003 sign preservation).
    if result == 0:
        return math.copysign(0.0, original)
    return float(result)


# --- Named-form interpretation ---------------------------------------------


def _eval_input(ref: InputRef, env: FormulaEnv) -> float:
    if isinstance(ref, AttrRef):
        return _finite(env.attr_values[ref.attr], f"attr {ref.attr!r}")
    return _finite(env.params[ref.param], f"param {ref.param!r}")


def _scalar(field: ScalarField, env: FormulaEnv) -> float:
    if isinstance(field, ParamRef):
        return _finite(env.params[field.param], f"param {field.param!r}")
    return _finite(field, "literal")


def _eval_form(form: NamedForm, env: FormulaEnv) -> float:
    x = _eval_input(form.input, env)
    if isinstance(form, LinearForm):
        return _eval_linear(form, env, x)
    if isinstance(form, PolynomialForm):
        return _eval_polynomial(form, x)
    if isinstance(form, PiecewiseLinearForm):
        return _eval_piecewise(form, x)
    if isinstance(form, ExponentialForm):
        return _eval_exponential(form, env, x)
    # LookupTableForm
    return _eval_lookup(form, x)


def _eval_linear(form: LinearForm, env: FormulaEnv, x: float) -> float:
    base = _scalar(form.base, env)
    per_point = _scalar(form.per_point, env)
    product = _finite(per_point * x, "linear")  # multiply first, then add
    return _finite(base + product, "linear")


def _eval_polynomial(form: PolynomialForm, x: float) -> float:
    coefficients = form.coefficients
    acc = _finite(coefficients[0], "polynomial")
    power_of_x = 1.0
    for coefficient in coefficients[1:]:
        power_of_x = _finite(power_of_x * x, "polynomial")
        term = _finite(coefficient * power_of_x, "polynomial")
        acc = _finite(acc + term, "polynomial")
    return acc


def _eval_piecewise(form: PiecewiseLinearForm, x: float) -> float:
    points = form.points
    first_x, first_y = points[0]
    if x <= first_x:  # clamp below the range — no extrapolation
        return _finite(first_y, "piecewise_linear")
    last_x, last_y = points[-1]
    if x >= last_x:  # clamp above the range
        return _finite(last_y, "piecewise_linear")
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            # y0 + (y1 - y0) * ((x - x0) / (x1 - x0)), individually rounded.
            fraction = _divide(x - x0, x1 - x0, "piecewise_linear")
            scaled = _finite((y1 - y0) * fraction, "piecewise_linear")
            return _finite(y0 + scaled, "piecewise_linear")
    # Unreachable for strictly-increasing points (a semantic-phase guarantee).
    return _finite(last_y, "piecewise_linear")


def _eval_exponential(form: ExponentialForm, env: FormulaEnv, x: float) -> float:
    coefficient = _scalar(form.coefficient, env)
    growth_rate = _scalar(form.growth_rate, env)
    powered = _finite(_power(growth_rate, x), "exponential")
    return _finite(coefficient * powered, "exponential")


def _eval_lookup(form: LookupTableForm, x: float) -> float:
    table = form.table
    first_x, first_y = table[0]
    if x < first_x:  # below the first sample takes the first y
        return _finite(first_y, "lookup_table")
    selected = first_y
    for sample_x, sample_y in table:  # step: greatest x <= input wins
        if sample_x <= x:
            selected = sample_y
        else:
            break
    return _finite(selected, "lookup_table")
