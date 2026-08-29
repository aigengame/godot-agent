"""The live wire's NUMBER domain — what a JSON number survives on the way to and
from an engine session (#752).

The live legs carry JSON (ADR-0021): the daemon writes ``{op, params}`` with
Python's ``json``, the harness reads it with Godot's ``JSON.parse_string``, and the
reply comes back as the ADR-0002 sentinel string the harness built with Godot's
``JSON.stringify``. Python's serializer and parser are exact for every binary64
value; Godot's two are not, and they fail DIFFERENTLY in each direction. This
module is the one authority on what that costs, so the guard, the help prose, the
schema description and the Skill all read one decision instead of four.

The behaviour below is recorded in ``tests/live_number_corpus.py``, a real-engine
differential corpus (Godot 4.6.3.stable.official.7d41c59c4) measured in BOTH
directions: normal, ``DBL_MIN``, subnormal, both signs, short-form and
full-precision literals, the flattening boundary at its exact step, and named rows
for each drift band. The e2e re-derives every verdict from a live engine, so what
this module claims is checkable rather than asserted. Where a percentage appears
below it is a point-in-time measurement taken during #752 against that engine
build — colour, not a property the suite defends.

**Result direction — fixed, not disclosed.** Godot's default ``JSON.stringify``
renders a float through ``String::num``, which formats FIXED-POINT (``%.*lf``) with
at most ``MAX_DECIMALS`` (32) decimals. So it flattens every value below
about ``1e-32.6`` to ``0.0`` and rounds ordinary values to ~15 significant digits
(``3.141592653589793`` came back as ``3.14159265358979``); it left 41 of the 96
corpus rows unchanged, and a 5500-value sweep during #752 put it at 33%. Godot's
``full_precision`` mode instead renders through ``String::num_scientific``
(grisu2, shortest round-tripping form), which was exact on **95 of the 96** corpus
rows and on all 5500 of that sweep — the sweep drew no negative zero, and the
single corpus miss IS that value. The harness therefore stringifies every reply with
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
- **Low-order drift.** Where the power IS finite the value still arrives changed
  in its last bits, for two separate reasons, both recorded per corpus row as
  ``request_ulp_gap``:

  - ``fraction / dblExp`` is two roundings (the table product is not the
    correctly-rounded power), and ``fraction`` itself passes 2^53 once a literal
    carries 16–17 significant digits. Ordinary game magnitudes land **1 ULP**
    away (``13.591409142295225``, ``1250.3538761287377``); the scientific band
    reaches **2**.
  - The engine keeps at most **18 mantissa digits** and drops the rest. Python
    writes fixed notation for ``|v| >= 1e-4``, so the leading zeros after the
    point spend that budget: a full-precision literal between ``1e-4`` and
    ``1e-2`` loses its last decimal digits outright — the corpus records
    ``0.0012345678901234567`` arriving **31** doubles away and
    ``0.00014285714285714284`` **105**. This band is far worse than one ULP, and
    is why the contract does not describe the residual as "1–2 ULP".

  All of it is DISCLOSED, not refused — refusing it would reject ordinary game
  values (a sweep during #752 put the drift at 8.8% of uniform ±10⁴ values), and
  preserving it would mean not sending a JSON number at all, which is the bespoke
  daemon↔harness representation ADR-0021 rejected.

The predicate below is not a decimal heuristic: it recomputes the engine's own
``exp`` intermediate from the literal gda is about to write. ``tests/
test_live_numbers.py`` pins it against the recorded engine verdicts, and
``tests/test_e2e_live_number_transport.py`` re-derives those verdicts from a real
engine, in both directions. Note it answers only the FLATTENING question; the
drift bands above are recorded, not predicted, because nothing branches on them.

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
