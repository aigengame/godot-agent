"""The live wire's number domain: gda's model of the engine, and the guard on it (#752).

The fast tier of the #752 evidence. It checks that
:func:`gda.live_numbers.wire_flattens_to_zero` reproduces the verdict a real Godot
4.6.3 gave every corpus row, and that ``game call`` refuses exactly the rows the
engine would flatten — on both input paths, at any nesting depth.

The engine tier that re-derives those verdicts (and covers the result direction) is
``tests/test_e2e_live_number_transport.py``; this module never launches an engine,
so it stays in the default suite.
"""

import json

import pytest
from pydantic import ValidationError

from gda.commands.game import GameCallParams
from gda.live_numbers import (
    GODOT_STRTOD_MAX_POWER,
    MAX_EXACT_JSON_INT,
    godot_applied_decimal_exponent,
    wire_flattens_to_zero,
)

from tests.live_number_corpus import LIVE_NUMBER_CORPUS


@pytest.mark.parametrize(
    ("label", "value", "engine_parse_zeroes"),
    [(label, value, zeroes) for label, value, zeroes, _ in LIVE_NUMBER_CORPUS],
)
def test_the_underflow_predicate_agrees_with_the_recorded_engine(
    label, value, engine_parse_zeroes
):
    # The whole guard rests on gda predicting what the engine's parser will do
    # with the literal the daemon is about to write. The corpus is the recording
    # of what it actually did; this is the agreement.
    assert wire_flattens_to_zero(value) is engine_parse_zeroes, label


def test_the_corpus_covers_the_classes_the_issue_named():
    # A corpus that drifted into only-subnormals would still pass every row above
    # while proving nothing, so pin the classes #752 requires it to carry.
    labels = {label for label, _, _, _ in LIVE_NUMBER_CORPUS}
    assert {"DBL_MIN", "-DBL_MIN", "1e-300", "-1e-300", "1.23..e-300"} <= labels
    assert {"DBL_TRUE_MIN 5e-324", "max subnormal", "DBL_MAX", "1e300"} <= labels
    zeroed = [value for _, value, zeroes, _ in LIVE_NUMBER_CORPUS if zeroes]
    assert any(value > 0 for value in zeroed) and any(value < 0 for value in zeroed)
    # Both sides of the boundary the predicate draws: a NORMAL value is flattened
    # (so this is not a subnormal rule), and a smaller-magnitude short-form value
    # survives (so it is not a magnitude rule either).
    assert wire_flattens_to_zero(1.2345678901234567e-300)
    assert not wire_flattens_to_zero(1e-308)
    # And the boundary is covered at its exact step, by two values of the SAME
    # magnitude that differ only in significant digits — the pair that refutes
    # any magnitude cutoff, since the LARGER one is the one that is lost.
    assert {"exp -308 (16 digits)", "exp -309 (17 digits)"} <= labels
    assert not wire_flattens_to_zero(2.209278197011611e-293)
    assert wire_flattens_to_zero(3.2956212316547955e-293)
    assert 3.2956212316547955e-293 > 2.209278197011611e-293


def test_the_applied_exponent_follows_the_engines_own_arithmetic():
    # decPt - mantSize + exponent, mantSize capped at 18 digits, leading zeros
    # counted — the quantities built_in_strtod computes under those names.
    assert godot_applied_decimal_exponent("1.0") == -1
    assert godot_applied_decimal_exponent("0.0001") == -4
    assert godot_applied_decimal_exponent("1e-300") == -300
    assert godot_applied_decimal_exponent("1.2345678901234567e-300") == -316
    assert godot_applied_decimal_exponent("-5e-324") == -324
    assert godot_applied_decimal_exponent("1e+308") == 308
    # 20 digits: everything past the 18th is dropped, and fracExp becomes decPt-18.
    assert godot_applied_decimal_exponent("1.2345678901234567890") == 1 - 18


def test_zero_and_non_finite_values_are_not_the_underflow_class():
    # Zero is already zero, and NaN/Infinity are refused earlier as their own
    # class — routing them here would relabel two different failures as one.
    for value in (0.0, -0.0, float("nan"), float("inf"), float("-inf")):
        assert wire_flattens_to_zero(value) is False


def test_the_flattening_boundary_is_the_engines_largest_finite_power():
    # The predicate must key on the engine's actual overflow point, not a spelled
    # constant that could drift from it.
    assert GODOT_STRTOD_MAX_POWER == 308
    assert godot_applied_decimal_exponent(json.dumps(5e-324)) < -GODOT_STRTOD_MAX_POWER


@pytest.mark.parametrize(
    ("label", "value"),
    [(label, value) for label, value, zeroes, _ in LIVE_NUMBER_CORPUS if zeroes],
)
def test_game_call_refuses_every_corpus_value_the_wire_would_flatten(label, value):
    with pytest.raises(ValidationError, match="cannot cross the live wire"):
        GameCallParams(node="/root/M", method="m", args=[value])


@pytest.mark.parametrize(
    ("label", "value"),
    [(label, value) for label, value, zeroes, _ in LIVE_NUMBER_CORPUS if not zeroes],
)
def test_game_call_accepts_every_corpus_value_the_wire_carries(label, value):
    # The other half of the guard's honesty: it must not over-refuse. Every value
    # the engine did read is still accepted, high-range and subnormal-adjacent
    # alike.
    params = GameCallParams(node="/root/M", method="m", args=[value])
    assert params.args == [value]


def test_the_flattening_refusal_reaches_nested_values():
    with pytest.raises(ValidationError, match="cannot cross the live wire"):
        GameCallParams(node="/root/M", method="m", args=[{"deep": [5e-324]}])


def test_the_flattening_refusal_names_the_value_and_the_consequence():
    with pytest.raises(ValidationError) as excinfo:
        GameCallParams(node="/root/M", method="m", args=[2.2250738585072014e-308])

    message = str(excinfo.value)
    assert "2.2250738585072014e-308" in message
    assert "arrive as 0.0" in message
    assert "SUCCEED on a value you never sent" in message


def test_the_three_refusal_classes_stay_distinguishable():
    # One guard, three reasons; an agent branching on the message must be able to
    # tell "not representable at all" from "too small" from "too large".
    with pytest.raises(ValidationError, match="NaN and Infinity"):
        GameCallParams(node="/root/M", method="m", args=[float("nan")])
    with pytest.raises(ValidationError, match="cannot cross the live wire"):
        GameCallParams(node="/root/M", method="m", args=[5e-324])
    with pytest.raises(ValidationError, match="integer values must be within"):
        GameCallParams(node="/root/M", method="m", args=[MAX_EXACT_JSON_INT + 2])


def test_the_game_group_still_names_the_shared_integer_bound():
    # The bound moved to the live-number authority; the group re-exports it, so a
    # caller (and the existing tests) can keep reading it where it used to live.
    from gda.commands import game

    assert game.MAX_EXACT_JSON_INT is MAX_EXACT_JSON_INT


# The one sentence the RESULT-direction guarantee is stated in. #752's AC 3 asks
# for the policy to be consistent across the surfaces that carry a live float,
# and it named `game get` and `perf` as the two that said nothing; this is what
# keeps the three copies from drifting apart, and from drifting away from the
# behaviour `tests/test_e2e_live_number_transport.py` measures.
RESULT_PRECISION_SENTENCE = (
    "cross the live wire at full binary64 precision — the reply is serialized "
    "with Godot's full-precision JSON writer, so a small or many-digit value "
    "reads back exactly (#752). The one residual: a NEGATIVE ZERO reads back as "
    "0.0, which the engine's writer decides before gda sees the value."
)


def _collapsed(text: str) -> str:
    """One line, single-spaced — a docstring's wrapping is not part of its content."""
    return " ".join(text.split())


def test_the_result_precision_guarantee_is_stated_identically_on_every_live_read():
    from gda.commands.game import game_get
    from gda.commands.perf import perf_monitor, perf_monitors

    for command in (game_get, perf_monitors, perf_monitor):
        assert RESULT_PRECISION_SENTENCE in _collapsed(command.__doc__ or ""), (
            command.__name__
        )


def test_the_result_precision_guarantee_reaches_the_rendered_help_and_the_skill():
    from typer.testing import CliRunner

    from gda.cli import app
    from gda.commands.meta import read_skill_text

    # Rendered help wraps inside a Rich panel, so assert on tokens a line break
    # cannot split rather than on the sentence.
    for argv in (
        ["game", "get", "--help"],
        ["perf", "monitors", "--help"],
        ["perf", "monitor", "--help"],
    ):
        rendered = CliRunner().invoke(app, argv)
        assert rendered.exit_code == 0, rendered.stdout
        words = set(" ".join(rendered.stdout.split()).split())
        assert "binary64" in words, argv
        assert "NEGATIVE" in words, argv

    skill = read_skill_text()
    assert "full binary64 precision" in skill
    assert "a negative zero reads back as `0.0`" in skill
