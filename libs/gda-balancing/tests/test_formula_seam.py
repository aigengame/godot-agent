"""The public formula seam's contract (bADR-0003, vectors V2/V3/V16).

These tests import ONLY :mod:`gda_balancing.formula` — the one authorized
external boundary for the definition-time evaluators (bADR-0003). Formulas are
built from JSON-shaped dicts via ``parse_formula`` so the tests exercise the
same parse path a document funnel would, never the internal model classes.
"""

import math

import pytest
from pydantic import ValidationError

from gda_balancing.formula import (
    EvaluationRefusal,
    FormulaEnv,
    evaluate,
    parse_formula,
)


def _eval(data: object, *, attrs=None, params=None) -> float:
    env = FormulaEnv(attr_values=attrs or {}, params=params or {})
    return evaluate(parse_formula(data), env)


def test_v2_typed_same_id_refs_disambiguate() -> None:
    # `power` exists in both namespaces; the typed nodes disambiguate.
    result = _eval(
        {"op": "add", "args": [{"attr": "power"}, {"param": "power"}]},
        attrs={"power": 5.0},
        params={"power": 10.0},
    )
    assert result == 15.0


@pytest.mark.parametrize(("level", "expected"), [(3.0, 20.0), (0.0, 10.0), (9.0, 30.0)])
def test_v3_piecewise_linear_interpolates_and_clamps(
    level: float, expected: float
) -> None:
    result = _eval(
        {
            "form": "piecewise_linear",
            "input": {"attr": "level"},
            "points": [[1, 10], [5, 30]],
        },
        attrs={"level": level},
    )
    assert result == expected


@pytest.mark.parametrize(("level", "expected"), [(3.0, 10.0), (5.0, 30.0), (0.0, 10.0)])
def test_v3_lookup_table_steps(level: float, expected: float) -> None:
    result = _eval(
        {
            "form": "lookup_table",
            "input": {"attr": "level"},
            "table": [[1, 10], [5, 30]],
        },
        attrs={"level": level},
    )
    assert result == expected


def test_v3_collection_element_must_be_literal() -> None:
    # A `{"param": ...}` inside a pair is a structural failure (v1 literal-only
    # collection rule).
    with pytest.raises(ValidationError):
        parse_formula(
            {
                "form": "piecewise_linear",
                "input": {"attr": "level"},
                "points": [[1, 10], [5, {"param": "p"}]],
            }
        )


@pytest.mark.parametrize(("value", "expected"), [(2.5, 3.0), (-2.5, -3.0), (2.4, 2.0)])
def test_v16_round_is_half_away_from_zero(value: float, expected: float) -> None:
    # Half away from zero, never banker's rounding (round(2.5) == 3, not 2).
    assert _eval({"op": "round", "args": [{"literal": value}]}) == expected


def test_min_of_signed_zeros_is_negative_zero() -> None:
    result = _eval({"op": "min", "args": [{"literal": 0.0}, {"literal": -0.0}]})
    assert result == 0.0 and math.copysign(1.0, result) == -1.0


def test_max_of_signed_zeros_is_positive_zero() -> None:
    result = _eval({"op": "max", "args": [{"literal": 0.0}, {"literal": -0.0}]})
    assert result == 0.0 and math.copysign(1.0, result) == 1.0


def test_integer_power_negative_exponent_is_exact() -> None:
    # 10^-2 is a SINGLE reciprocal of 10*10 — exactly 0.01, not (1/10)*(1/10).
    result = _eval({"op": "power", "args": [{"literal": 10.0}, {"literal": -2.0}]})
    assert result == 1 / (10 * 10) == 0.01


def test_divide_by_zero_refuses_with_stable_code() -> None:
    with pytest.raises(EvaluationRefusal) as excinfo:
        _eval({"op": "divide", "args": [{"literal": 1.0}, {"literal": 0.0}]})
    assert excinfo.value.code == "non_finite_evaluation"


def test_overflow_to_infinity_refuses() -> None:
    with pytest.raises(EvaluationRefusal) as excinfo:
        _eval({"op": "multiply", "args": [{"literal": 1e308}, {"literal": 1e308}]})
    assert excinfo.value.code == "non_finite_evaluation"


def test_linear_form_resolves_param_scalar_field() -> None:
    # A scalar field may be a parameter knob resolved via `env.params`.
    result = _eval(
        {
            "form": "linear",
            "input": {"attr": "level"},
            "base": 20,
            "per_point": {"param": "gain"},
        },
        attrs={"level": 3.0},
        params={"gain": 5.0},
    )
    assert result == 35.0  # 20 + 5 * 3
