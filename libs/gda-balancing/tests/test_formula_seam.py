"""The historical 1.x formula contract (bADR-0003, vectors V2/V3/V16).

The single-formula tests import only the test-local executable witness; Schema
2.0 ships no 1.x evaluator/runtime seam.
Formulas are built from JSON-shaped dicts via ``parse_formula`` so the tests
exercise the same parse path a document funnel would, never the internal model
classes.

The ``evaluate_bases`` tests are the seam's *document-level* face: they compute
the definition-time final values of a whole document's attribute bases. That
function's precondition is a **funnel-validated document** (references declared,
graph acyclic — bADR-0002/0003), so those tests obtain their input through
:func:`gda_balancing.schema.funnel.validate`, the funnel's public face — the
sanctioned way to produce the ``DesignDocument`` the seam consumes.
"""

import json
import math

import pytest
from pydantic import ValidationError

from _legacy_formula import (
    EvaluationRefusal,
    FormulaEnv,
    clamp_to_attribute,
    evaluate,
    evaluate_bases,
    parse_formula,
)
from gda_balancing.schema.funnel import validate
from gda_balancing.schema.model.attributes import Attribute
from gda_balancing.schema.model.document import DesignDocument


def _eval(data: object, *, attrs=None, params=None) -> float:
    env = FormulaEnv(attr_values=attrs or {}, params=params or {})
    return evaluate(parse_formula(data), env)


def _validated(document: dict) -> DesignDocument:
    outcome = validate(json.dumps(document).encode("utf-8"))
    assert isinstance(outcome, DesignDocument), outcome
    return outcome


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


# --- evaluate_bases: definition-time final values (bADR-0002/0003) ----------


def test_evaluate_bases_v2_typed_refs() -> None:
    # V2: `strike` reads `power`'s definition-time final (5) plus the parameter
    # `power` (10) -> 15; the topological order evaluates `power` first.
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "v2"},
            "parameters": {"power": 10},
            "attributes": {
                "items": {
                    "power": {"domain": "number", "base": {"direct": 5}},
                    "strike": {
                        "domain": "number",
                        "base": {
                            "formula": {
                                "op": "add",
                                "args": [{"attr": "power"}, {"param": "power"}],
                            }
                        },
                    },
                }
            },
        }
    )
    assert evaluate_bases(document) == {"power": 5.0, "strike": 15.0}


def test_evaluate_bases_clamps_then_dependents_read_the_clamped_final() -> None:
    # `capped` has direct base 10 but a cap of 5 -> final 5. A dependent formula
    # reading `capped` observes the CLAMPED final (5), never the raw base (10).
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "clamp"},
            "attributes": {
                "items": {
                    "capped": {
                        "domain": "number",
                        "base": {"direct": 10},
                        "bounds": {"cap": 5},
                    },
                    "dependent": {
                        "domain": "number",
                        "base": {"formula": {"attr": "capped"}},
                    },
                }
            },
        }
    )
    assert evaluate_bases(document) == {"capped": 5.0, "dependent": 5.0}


def test_evaluate_bases_floor_clamp() -> None:
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "floor"},
            "attributes": {
                "items": {
                    "floored": {
                        "domain": "number",
                        "base": {"direct": -3},
                        "bounds": {"floor": 0},
                    }
                }
            },
        }
    )
    assert evaluate_bases(document) == {"floored": 0.0}


def test_power_intermediate_overflow_refuses() -> None:
    # 1e200^-2: the intermediate square overflows — a refusal, never a
    # silent 0.0 behind the reciprocal.
    with pytest.raises(EvaluationRefusal) as excinfo:
        _eval({"op": "power", "args": [{"literal": 1e200}, {"literal": -2.0}]})
    assert excinfo.value.code == "non_finite_evaluation"


def test_power_underflowed_reciprocal_refuses() -> None:
    # 1e-200^-2: the square underflows to 0.0; the reciprocal must be the
    # checked division's typed refusal, never a raw ZeroDivisionError.
    with pytest.raises(EvaluationRefusal) as excinfo:
        _eval({"op": "power", "args": [{"literal": 1e-200}, {"literal": -2.0}]})
    assert excinfo.value.code == "non_finite_evaluation"


def test_power_zero_base_negative_exponent_refuses() -> None:
    with pytest.raises(EvaluationRefusal):
        _eval({"op": "power", "args": [{"literal": 0.0}, {"literal": -1.0}]})


# --- Intrinsic domain clamp (bADR-0002, finding-3 #527 recheck-2) -----------
#
# A `probability` domain intrinsically pins the value space to [0, 1]; declared
# bounds only *narrow within* it. The static rules refuse a probability's
# declared bounds / direct base outside [0, 1], but a formula-derived base can
# still overshoot — the definition-time clamp must compose the intrinsic [0, 1]
# with any declared bounds. `percentage`/`number` carry no intrinsic space.


def _prob_attr(base: dict, bounds: dict | None = None) -> Attribute:
    attr: dict = {"domain": "probability", "base": base}
    if bounds is not None:
        attr["bounds"] = bounds
    return Attribute.model_validate(attr)


def test_probability_formula_base_over_one_clamps_to_domain_ceiling() -> None:
    # formula literal 2 with only a declared floor of 0: the intrinsic cap of 1
    # (not restated in the bounds) still clamps the overshoot to 1.0.
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "prob-ceiling"},
            "attributes": {
                "items": {
                    "crit": {
                        "domain": "probability",
                        "base": {"formula": {"literal": 2}},
                        "bounds": {"floor": 0},
                    }
                }
            },
        }
    )
    assert evaluate_bases(document) == {"crit": 1.0}


def test_probability_formula_base_below_zero_clamps_to_domain_floor() -> None:
    # formula literal -0.5 with only a declared cap of 0.5: the intrinsic floor
    # of 0 (not restated) clamps the undershoot to 0.0.
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "prob-floor"},
            "attributes": {
                "items": {
                    "crit": {
                        "domain": "probability",
                        "base": {"formula": {"literal": -0.5}},
                        "bounds": {"cap": 0.5},
                    }
                }
            },
        }
    )
    assert evaluate_bases(document) == {"crit": 0.0}


def test_probability_declared_narrowing_bound_still_applies() -> None:
    # A declared cap of 0.5 narrows *within* [0, 1]: a formula value of 0.9 is
    # clamped to the tighter declared cap, not the intrinsic ceiling.
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "prob-narrow"},
            "attributes": {
                "items": {
                    "crit": {
                        "domain": "probability",
                        "base": {"formula": {"literal": 0.9}},
                        "bounds": {"cap": 0.5},
                    }
                }
            },
        }
    )
    assert evaluate_bases(document) == {"crit": 0.5}


def test_number_formula_base_has_no_intrinsic_clamp() -> None:
    # A `number` attribute with no bounds is unbounded: a formula value of 2 is
    # not clamped — only `probability` carries the intrinsic [0, 1] space.
    document = _validated(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "num"},
            "attributes": {
                "items": {
                    "power": {
                        "domain": "number",
                        "base": {"formula": {"literal": 2}},
                    }
                }
            },
        }
    )
    assert evaluate_bases(document) == {"power": 2.0}


# --- clamp_to_attribute: the composed-clamp seam (#510 reuses it) -----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2.0, 1.0), (-0.5, 0.0), (0.5, 0.5)],
)
def test_clamp_to_attribute_probability_absent_bounds_uses_intrinsic_space(
    value: float, expected: float
) -> None:
    # No declared bounds: the effective bounds ARE the intrinsic [0, 1].
    attr = _prob_attr({"direct": 0.3})
    assert clamp_to_attribute(value, attr) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.1, 0.2), (0.9, 0.8), (0.5, 0.5)],
)
def test_clamp_to_attribute_probability_present_bounds_narrow_within_domain(
    value: float, expected: float
) -> None:
    # Declared floor 0.2 / cap 0.8 narrow within [0, 1]: effective floor
    # max(0, 0.2) = 0.2, effective cap min(1, 0.8) = 0.8.
    attr = _prob_attr({"direct": 0.3}, {"floor": 0.2, "cap": 0.8})
    assert clamp_to_attribute(value, attr) == expected


@pytest.mark.parametrize(("value", "expected"), [(2.0, 2.0), (-5.0, -5.0)])
def test_clamp_to_attribute_number_absent_bounds_is_unbounded(
    value: float, expected: float
) -> None:
    attr = Attribute.model_validate({"domain": "number", "base": {"direct": 5}})
    assert clamp_to_attribute(value, attr) == expected


def test_clamp_to_attribute_number_declared_floor_only() -> None:
    attr = Attribute.model_validate(
        {"domain": "number", "base": {"direct": 5}, "bounds": {"floor": 0}}
    )
    assert clamp_to_attribute(-5.0, attr) == 0.0
    assert clamp_to_attribute(7.0, attr) == 7.0


def test_clamp_to_attribute_percentage_absent_bounds_has_no_intrinsic_ceiling() -> None:
    # A percentage is a fraction, unbounded above: 2.0 (200%) is NOT clamped.
    attr = Attribute.model_validate(
        {"domain": "percentage", "base": {"direct": 0.3}, "bounds": {"floor": 0}}
    )
    assert clamp_to_attribute(2.0, attr) == 2.0
