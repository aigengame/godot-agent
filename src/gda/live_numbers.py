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
(``3.141592653589793`` came back as ``3.14159265358979``). Over the 96 corpus
rows it split **41 exact / 15 changed / 40 flattened to ``0.0``**, and a
5500-value sweep during #752 put its exact share at 33%. Godot's
``full_precision`` mode instead renders through ``String::num_scientific``
(grisu2, shortest round-tripping form), which was exact on **95 of the 96** corpus
rows and on all 5500 of that sweep — the sweep drew no negative zero, and the
single corpus miss IS that value. The harness therefore stringifies every reply with
``full_precision`` (``gda_harness.gd``'s ``_json``), and the result direction
carries full binary64 precision. One residual, kept in the public contract because
it is an engine early return (``JSON::_stringify`` emits ``"0.0"`` for anything
equal to zero): a NEGATIVE ZERO reads back as ``0.0``.

**The result path has TWO writers, and each float has exactly one of them.** The
paragraph above is about the engine's: a value the game reports is stringified by
``gda_harness.gd``'s ``_json`` and read back by Python. But a live result can
also carry a number the engine never wrote — one gda computes or echoes CLI-side
(``perf monitors``' window statistics, and the budget bounds it copies out of the
caller's own file). Those never meet Godot's writer, so the engine's residual is
not theirs: gda's serializer keeps a negative zero, and a real daemon returning
``{"value": 1.0, "min": -0.0, "max": -0.0}`` is what the #770 review used to
falsify the blanket claim. Hence TWO published sentences, each naming its writer
— :data:`LIVE_ENGINE_PRECISION` and :data:`LIVE_DERIVED_PRECISION`. Which one a
field carries is not a matter of taste: ``tests/test_live_contract_guards.py``
MEASURES the provenance (a probe drives each result-assembling recipe with a
sentinel-bearing reply and sees which fields the sentinels reach) and fails a
field disclosing the wrong writer.

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

The **request-side admission scan** (:func:`find_unrepresentable`) is where that
policy is applied. It is a property of the daemon-to-harness LEG — the one Godot's
parser reads — not of any one command and not of every live command either: the
ops the daemon answers itself (``gda.daemon.server.DAEMON_SERVED_OPS``) carry
their numbers over a Python-to-Python leg that loses nothing. So every RELAYED
live params model inherits the scan through
:class:`gda.models.RelayedLiveParams` — one recursive pass over the model's own
fields, before the daemon writes the frame. Three classes are refused there: a
non-finite float (JSON has no literal for one), an integer outside
:data:`MAX_EXACT_JSON_INT`, and a float this module's predicate says the parser
reads as ``0.0``.

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
import math

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


def find_unrepresentable(value: object, path: str) -> "str | None":
    """The first value under ``path`` the live wire cannot carry, or ``None``.

    The request direction's whole admission rule, in one recursive pass. It
    answers about the JSON frame gda is ABOUT to write, so it reads a params
    model's own dumped fields — a nested value is as harmful as a top-level one,
    and the ``path`` it returns names where the offender sits (``args[0]``,
    ``events[2]['x']``) rather than only that one exists.

    Three classes, each reproduced end to end, each refused because letting it
    through makes a live call SUCCEED on a value the caller never sent:

    - **Non-finite floats.** JSON has no ``NaN``/``Infinity`` literals, but
      Python's ``json.loads`` accepts them by extension and pydantic keeps them
      in an ``Any`` field — and the daemon then writes a frame the harness's
      ``JSON.parse_string`` cannot read, so the call never arrives: the caller
      waits out the 30 s relay bound, gets ``live_timeout``, and the daemon
      retires the channel, LOSING the engine session's runtime state.
    - **Python ints outside the exact-integer range** the live parser's binary64
      number domain guarantees (PR #749 re-review): those may arrive as a
      different number. A Python float already IS a binary64 value and does not
      inherit the integer safe-range bound; the reproduced high-range values such
      as ``1e300`` cross unchanged.
    - **Floats the engine's parser reads as** ``0.0`` (#752), per
      :func:`wire_flattens_to_zero` above: ``5e-324``,
      ``2.2250738585072014e-308`` (``DBL_MIN``) and even the ordinary normal
      ``1.2345678901234567e-300``. Refused rather than re-spelled because no
      decimal literal at all can deliver such a value through that parser.

    It does NOT reject every float Godot can change: a value the parser CAN
    construct arrives changed in its low-order bits — 1 ULP at ordinary
    magnitudes, and 31 to 105 doubles away for a full-precision literal between
    ``1e-4`` and ``1e-2``, where the parser drops everything past its 18th
    mantissa digit. That residual is DISCLOSED rather than refused: refusing it
    would reject ordinary game values, and removing it would mean not sending a
    JSON number at all, the bespoke daemon-harness representation ADR-0021
    rejected. The result direction has no such residual (see
    :data:`LIVE_ENGINE_PRECISION`).
    """
    if isinstance(value, bool):
        pass  # bool is not an int argument here, despite subclassing it
    elif isinstance(value, float) and not math.isfinite(value):
        return (
            f"{path} must be finite JSON values; NaN and Infinity are not "
            "representable on the live wire."
        )
    elif isinstance(value, float) and wire_flattens_to_zero(value):
        return (
            f"{path} float value {value!r} cannot cross the live wire: Godot's "
            "JSON parser scales it by a power of ten it cannot hold in a double, "
            "so it would arrive as 0.0 and the call would SUCCEED on a value you "
            "never sent. No decimal spelling avoids it — the value needs fewer "
            "significant digits or a larger magnitude."
        )
    elif isinstance(value, int) and abs(value) > MAX_EXACT_JSON_INT:
        return (
            f"{path} integer values must be within +/-{MAX_EXACT_JSON_INT} (the "
            "live wire reads JSON numbers as binary64, so a larger integer may "
            f"arrive as a DIFFERENT value); got {value}."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            found = find_unrepresentable(item, f"{path}[{key!r}]")
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = find_unrepresentable(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


# The RESULT direction's public contract — one sentence PER WRITER (#752, #770
# review). Both are quoted verbatim by the live commands' Typer docstrings (which
# Typer renders as `--help` and cannot interpolate a constant into, so a test pins
# them against THESE strings) and concatenated into the live result models' field
# descriptions, which `--schema` publishes. Both deliberately say nothing about the
# REQUEST direction: that one is a refusal, stated where the refusal is made.
#
# Each names its writer in its first words, because that is the fact it is a
# property of: the #770 review found the engine sentence inherited by fields the
# engine never wrote, and a claim that does not say whose value it describes
# invites exactly that.

# For a value the ENGINE produced and its full-precision writer serialized.
LIVE_ENGINE_PRECISION = (
    "A value the engine reports crosses the wire at full binary64 precision — "
    "the reply is serialized with Godot's full-precision JSON writer, so a "
    "small or many-digit value reads back exactly (#752). The one residual is "
    "that writer's: a NEGATIVE ZERO reads back as 0.0, decided before gda sees "
    "the value."
)

# For a value GDA produced CLI-side, which no Godot writer ever touched.
LIVE_DERIVED_PRECISION = (
    "A value gda derives CLI-side in Python — from what the engine reported, or "
    "from input you supplied — never meets Godot's JSON writer: it carries full "
    "binary64 precision, and that writer's negative-zero residual does not "
    "apply, so a -0.0 stays -0.0 (#752)."
)
