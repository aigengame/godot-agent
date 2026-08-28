"""The live wire's NUMBER domain — what a JSON number survives on the way to and
from an engine session (#752).

The live legs carry JSON (ADR-0021): the daemon writes ``{op, params}`` with
Python's ``json``, the harness reads it with Godot's ``JSON.parse_string``, and the
reply comes back as the ADR-0002 sentinel string the harness built with Godot's
``JSON.stringify``. Python's serializer and parser are exact for every binary64
value; Godot's two are not, and they fail DIFFERENTLY in each direction. This
module is the one authority on what that costs, so the guard, the help prose, the
schema description and the Skill all read one decision instead of four.

The numbers below come from a real-engine differential corpus (Godot
4.6.3.stable.official.7d41c59c4) over 5580 values — a shaped set (normal,
``DBL_MIN``, subnormal, both signs, short-form and full-precision literals) plus a
random sweep — measured in BOTH directions.

**Result direction — fixed, not disclosed.** Godot's default ``JSON.stringify``
renders a float through ``String::num``, which formats FIXED-POINT (``%.*lf``) with
at most ``MAX_DECIMALS`` (32) decimals. So it flattened every value below
about ``1e-32.6`` to ``0.0`` and rounded ordinary values to ~15 significant digits
(``3.141592653589793`` came back as ``3.14159265358979``): 1822/5580 corpus values
survived unchanged. Godot's ``full_precision`` mode instead renders through
``String::num_scientific`` (grisu2, shortest round-tripping form), which was
EXACT on 5580/5580. The harness therefore stringifies every reply with
``full_precision`` (``gda_harness.gd``'s ``_json``), and the result direction
carries full binary64 precision. One residual, kept in the public contract because
it is an engine early return (``JSON::_stringify`` emits ``"0.0"`` for anything
equal to zero): a NEGATIVE ZERO reads back as ``0.0``.

**Request direction — bounded, not fixable here.** Godot's parser is
``built_in_strtod`` (``core/string/ustring.cpp``), a Tcl-derived strtod that reads
the digits into an integer ``fraction`` and applies a power of ten computed AS A
DOUBLE from a table of ``10^2^i``. Two consequences, both reproduced:

- **Underflow to zero.** ``10^309`` is not finite, so an applied exponent of −309
  or below makes the divisor ``inf`` and the whole value ``0.0`` — the defect this
  issue is named for. It is not reachable by re-spelling: ``fraction`` is an
  integer of at least 1 and the largest finite power the table can build is
  ``10^308``, so no decimal literal at all can deliver such a value. gda therefore
  REFUSES those values (:func:`wire_flattens_to_zero`) instead of letting a live
  call succeed on a number the caller never sent.
- **One-to-two ULP drift.** Where the power IS finite, ``fraction / dblExp`` is
  still two roundings (the table product is not the correctly-rounded power), so
  the arriving double can differ from the sent one in its last bits: 8.8% of
  uniform ±10⁴ values and 46.7% of uniformly random binary64 values drifted, all
  by 1–3 ULP. This is DISCLOSED, not refused — refusing it would reject ordinary
  game values, and preserving it would mean not sending a JSON number at all,
  which is the bespoke daemon↔harness representation ADR-0021 rejected.

The predicate below is not a decimal heuristic: it recomputes the engine's own
``exp`` intermediate from the literal gda is about to write. ``tests/
test_live_numbers.py`` pins it against the recorded engine verdicts, and
``tests/test_e2e_live_number_transport.py`` re-derives those verdicts from a real
engine, in both directions.

A leaf module with no ``gda`` imports (the same discipline as
``gda.exit_codes`` / ``gda.execution``), so a command module, a params model and a
test can all name the domain without an import cycle.
"""

import json

# The interoperable range for JSON INTEGER values decoded as Python ``int``
# (PR #749 review). Godot's ``JSON.parse_string`` reads every number as binary64,
# so an int outside this guaranteed-exact range may arrive changed:
# 9007199254740993 became …992, and 123456789012345678901234567890 became -2.
# A Python float is already a binary64 value and does not inherit this integer
# bound — its own bound is :func:`wire_flattens_to_zero` below.
MAX_EXACT_JSON_INT = 2**53 - 1

# The largest power of ten ``built_in_strtod`` can hold in a double. Its table of
# ``10^2^i`` products reaches ``1e308`` finite; ``10^309`` overflows to ``inf``,
# and dividing by ``inf`` is what turns a small literal into ``0.0``.
GODOT_STRTOD_MAX_POWER = 308


def godot_applied_decimal_exponent(literal: str) -> int:
    """The power of ten Godot's ``built_in_strtod`` applies to ``literal``'s digits.

    A transcription of the engine's own ``fracExp`` / ``exp`` arithmetic, not an
    approximation of it: the mantissa's digits are counted INCLUDING leading zeros
    and the decimal point's position (``decPt``) is their count before the point,
    the engine drops everything past the 18th digit (``fracExp = decPt - 18``), and
    the literal's own exponent is then added. Every quantity here has the same name
    it has in ``core/string/ustring.cpp``.
    """
    mantissa, _, exponent_text = literal.lstrip("+-").partition("e")
    integer, _, fraction = mantissa.partition(".")
    digits = integer + fraction
    # ``decPt`` is the digit count before the point; ``mantSize`` is capped at 18.
    frac_exp = len(integer) - min(len(digits), 18)
    return frac_exp + (int(exponent_text) if exponent_text else 0)


def wire_flattens_to_zero(value: float) -> bool:
    """Whether Godot's JSON parser reads ``value``'s wire literal as ``0.0``.

    Answered about the literal gda ITSELF will write — ``json.dumps`` is the
    daemon's serializer (``gda.daemon.protocol.write_message``), so asking the
    question about any other spelling would answer about a frame gda never sends.

    ``True`` only for the values the engine's parser cannot construct at all: an
    applied exponent at or below ``-(GODOT_STRTOD_MAX_POWER + 1)`` makes its
    divisor ``inf``. Zero itself is never flattened — it is already zero — and a
    non-finite value has no meaning here (RFC JSON has no literal for one, and the
    params model refuses it earlier).
    """
    if value == 0.0 or value != value or value in (float("inf"), float("-inf")):
        return False
    exponent = godot_applied_decimal_exponent(json.dumps(value))
    return exponent <= -(GODOT_STRTOD_MAX_POWER + 1)
