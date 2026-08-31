"""The #752 number corpus, and the verdicts a real engine gave it.

Three tests read these rows, so no tier can disagree with another about what the
corpus says: a unit test (``tests/test_live_numbers.py``, which checks gda's model
of the engine against this table) and two e2e tests that re-derive it from a real
engine — ``tests/test_e2e_live_number_transport.py`` for the live legs, and
``tests/test_e2e_headless_number_reads.py`` for the headless reply (#771). It is
also the ONE place the published counts come from: :data:`PARTITIONS` derives them
from the rows below, and ``tests/test_live_numbers.py`` reads back the two surfaces
allowed to state them — ``gda.live_numbers``'s module docstring and
``docs/command-catalog.md`` — requiring the derived strings verbatim, so a
hand-edited count cannot survive. ADR-0041 and the two engine-side writer comments
quote no count at all; they point at ``gda.live_numbers`` instead.

The corpus is named for the issue that measured it, not for a leg. The
``default_stringify`` column records what one ENGINE FUNCTION does to a value, so
it describes every reply Godot serializes: #752 measured it on the live wire, and
#771 found the headless reply framed by the same default writer and fixed it with
the same argument. That is why the headless direction reuses this table instead of
forking a second one, and why it needs no column of its own — a headless read is
measured against the same ``full_precision`` partition (:data:`PARTITIONS`).

Measured on Godot 4.6.3.stable.official.7d41c59c4. Not a specification of the
engine — a recording of it; the e2e tests are what keep the recording true.
"""

import math
import struct
from typing import Literal, NamedTuple

# What Godot's DEFAULT ``JSON.stringify`` did to a value on the way back. Three
# states, not two: the writer both ROUNDS ordinary values and FLATTENS small ones,
# and collapsing those into one "not exact" bit is what let the first published
# table misreport the split (#770 review).
DefaultStringify = Literal["exact", "changed", "zero"]


class LiveNumberCase(NamedTuple):
    """One corpus row: a binary64 value and what the engine did to it, both ways.

    ``value`` is exact — the ``repr`` in the table round-trips.

    ``engine_parse_zeroes`` is the REQUEST direction: Godot 4.6.3's
    ``JSON.parse_string`` read the literal ``json.dumps(value)`` produces as
    ``0.0`` although the value is not zero. This is the verdict
    :func:`gda.live_numbers.wire_flattens_to_zero` must reproduce.

    ``default_stringify`` is the RESULT direction under Godot's DEFAULT
    ``JSON.stringify`` — ``"exact"``, ``"changed"`` (a different value that the
    writer did not FLATTEN: rounded, or the ``-0.0`` that comes back as ``0.0``),
    or ``"zero"`` (a non-zero value flattened to ``0.0``). "Changed" is therefore
    not "changed to a non-zero value": the negative zero sits in it, which is what
    made the published column heading wrong (#770 round 3).
    The full-precision writer the harness now uses is exact on every row but the
    negative zero, which is what makes this column the red-proof of the fix.

    ``request_ulp_gap`` is how far a value that DID arrive landed from the one
    sent, counted in representable doubles (0 = exact); ``None`` where the engine
    flattened it to ``0.0``, since a distance from zero would say nothing. This
    column is what makes the disclosed residual checkable rather than asserted:
    the rows record 1 and 2 for the ordinary and scientific bands, and 31 and 105
    for the MANTISSA-CAP band, where a literal carrying more than 18 mantissa
    digits has its low-order digits dropped outright.
    """

    label: str
    value: float
    engine_parse_zeroes: bool
    default_stringify: DefaultStringify
    request_ulp_gap: "int | None"


# fmt: off
LIVE_NUMBER_CORPUS: list[LiveNumberCase] = [
    LiveNumberCase('zero', 0.0, False, 'exact', 0),
    LiveNumberCase('-zero', -0.0, False, 'changed', 0),
    LiveNumberCase('one', 1.0, False, 'exact', 0),
    LiveNumberCase('-one', -1.0, False, 'exact', 0),
    LiveNumberCase('half', 0.5, False, 'exact', 0),
    LiveNumberCase('-half', -0.5, False, 'exact', 0),
    LiveNumberCase('tenth', 0.1, False, 'exact', 0),
    LiveNumberCase('-tenth', -0.1, False, 'exact', 0),
    LiveNumberCase('pi', 3.141592653589793, False, 'changed', 0),
    LiveNumberCase('-pi', -3.141592653589793, False, 'changed', 0),
    LiveNumberCase('third', 0.3333333333333333, False, 'changed', 0),
    LiveNumberCase('-third', -0.3333333333333333, False, 'changed', 0),
    LiveNumberCase('1e-4', 0.0001, False, 'exact', 0),
    LiveNumberCase('-1e-4', -0.0001, False, 'exact', 0),
    LiveNumberCase('1e-5', 1e-05, False, 'exact', 0),
    LiveNumberCase('-1e-5', -1e-05, False, 'exact', 0),
    LiveNumberCase('1e15', 1000000000000000.0, False, 'exact', 0),
    LiveNumberCase('-1e15', -1000000000000000.0, False, 'exact', 0),
    LiveNumberCase('1e16', 1e+16, False, 'exact', 0),
    LiveNumberCase('-1e16', -1e+16, False, 'exact', 0),
    LiveNumberCase('1e17', 1e+17, False, 'exact', 0),
    LiveNumberCase('-1e17', -1e+17, False, 'exact', 0),
    LiveNumberCase('1e22', 1e+22, False, 'exact', 0),
    LiveNumberCase('-1e22', -1e+22, False, 'exact', 0),
    LiveNumberCase('1e23', 1e+23, False, 'exact', 0),
    LiveNumberCase('-1e23', -1e+23, False, 'exact', 0),
    LiveNumberCase('2**53', 9007199254740992.0, False, 'exact', 0),
    LiveNumberCase('-2**53', -9007199254740992.0, False, 'exact', 0),
    LiveNumberCase('1e100', 1e+100, False, 'exact', 0),
    LiveNumberCase('-1e100', -1e+100, False, 'exact', 0),
    LiveNumberCase('1.23..e100', 1.2345678901234567e+100, False, 'exact', 1),
    LiveNumberCase('-1.23..e100', -1.2345678901234567e+100, False, 'exact', 1),
    LiveNumberCase('1e300', 1e+300, False, 'exact', 0),
    LiveNumberCase('-1e300', -1e+300, False, 'exact', 0),
    LiveNumberCase('1.23..e300', 1.2345678901234567e+300, False, 'exact', 0),
    LiveNumberCase('-1.23..e300', -1.2345678901234567e+300, False, 'exact', 0),
    LiveNumberCase('1e308', 1e+308, False, 'exact', 0),
    LiveNumberCase('-1e308', -1e+308, False, 'exact', 0),
    LiveNumberCase('DBL_MAX', 1.7976931348623157e+308, False, 'exact', 0),
    LiveNumberCase('-DBL_MAX', -1.7976931348623157e+308, False, 'exact', 0),
    LiveNumberCase('1 ULP drift ~13.6', 13.591409142295225, False, 'changed', 1),
    LiveNumberCase('-1 ULP drift ~13.6', -13.591409142295225, False, 'changed', 1),
    LiveNumberCase('1 ULP drift ~1250', 1250.3538761287377, False, 'changed', 1),
    LiveNumberCase('-1 ULP drift ~1250', -1250.3538761287377, False, 'changed', 1),
    LiveNumberCase('1 ULP drift ~9e4 (16 digits)', 90333.33333333333, False, 'changed', 1),
    LiveNumberCase('-1 ULP drift ~9e4 (16 digits)', -90333.33333333333, False, 'changed', 1),
    LiveNumberCase('mantissa cap ~1.2e-3', 0.0012345678901234567, False, 'changed', 31),
    LiveNumberCase('-mantissa cap ~1.2e-3', -0.0012345678901234567, False, 'changed', 31),
    LiveNumberCase('mantissa cap ~1.4e-4', 0.00014285714285714284, False, 'changed', 105),
    LiveNumberCase('-mantissa cap ~1.4e-4', -0.00014285714285714284, False, 'changed', 105),
    LiveNumberCase('2 ULP drift ~3.1e-291', 3.141592653589793e-291, False, 'zero', 2),
    LiveNumberCase('-2 ULP drift ~3.1e-291', -3.141592653589793e-291, False, 'zero', 2),
    LiveNumberCase('1e-10', 1e-10, False, 'exact', 0),
    LiveNumberCase('-1e-10', -1e-10, False, 'exact', 0),
    LiveNumberCase('1e-31', 1e-31, False, 'exact', 0),
    LiveNumberCase('-1e-31', -1e-31, False, 'exact', 0),
    LiveNumberCase('1e-32', 1e-32, False, 'exact', 1),
    LiveNumberCase('-1e-32', -1e-32, False, 'exact', 1),
    LiveNumberCase('1e-33', 1e-33, False, 'zero', 1),
    LiveNumberCase('-1e-33', -1e-33, False, 'zero', 1),
    LiveNumberCase('1e-40', 1e-40, False, 'zero', 0),
    LiveNumberCase('-1e-40', -1e-40, False, 'zero', 0),
    LiveNumberCase('1e-100', 1e-100, False, 'zero', 0),
    LiveNumberCase('-1e-100', -1e-100, False, 'zero', 0),
    LiveNumberCase('1.23..e-100', 1.2345678901234567e-100, False, 'zero', 0),
    LiveNumberCase('-1.23..e-100', -1.2345678901234567e-100, False, 'zero', 0),
    LiveNumberCase('1e-200', 1e-200, False, 'zero', 0),
    LiveNumberCase('-1e-200', -1e-200, False, 'zero', 0),
    LiveNumberCase('1e-300', 1e-300, False, 'zero', 0),
    LiveNumberCase('-1e-300', -1e-300, False, 'zero', 0),
    LiveNumberCase('1.0000000000000002e-300', 1.0000000000000002e-300, True, 'zero', None),
    LiveNumberCase('-1.0000000000000002e-300', -1.0000000000000002e-300, True, 'zero', None),
    LiveNumberCase('1.23..e-300', 1.2345678901234568e-300, True, 'zero', None),
    LiveNumberCase('-1.23..e-300', -1.2345678901234568e-300, True, 'zero', None),
    LiveNumberCase('1e-305', 1e-305, False, 'zero', 1),
    LiveNumberCase('-1e-305', -1e-305, False, 'zero', 1),
    LiveNumberCase('1e-307', 1e-307, False, 'zero', 1),
    LiveNumberCase('-1e-307', -1e-307, False, 'zero', 1),
    LiveNumberCase('1e-308', 1e-308, False, 'zero', 0),
    LiveNumberCase('-1e-308', -1e-308, False, 'zero', 0),
    LiveNumberCase('DBL_MIN', 2.2250738585072014e-308, True, 'zero', None),
    LiveNumberCase('-DBL_MIN', -2.2250738585072014e-308, True, 'zero', None),
    LiveNumberCase('max subnormal', 2.225073858507201e-308, True, 'zero', None),
    LiveNumberCase('-max subnormal', -2.225073858507201e-308, True, 'zero', None),
    LiveNumberCase('exp -308 (16 digits)', 2.209278197011611e-293, False, 'zero', 0),
    LiveNumberCase('-exp -308 (16 digits)', -2.209278197011611e-293, False, 'zero', 0),
    LiveNumberCase('exp -309 (17 digits)', 3.2956212316547955e-293, True, 'zero', None),
    LiveNumberCase('-exp -309 (17 digits)', -3.2956212316547955e-293, True, 'zero', None),
    LiveNumberCase('1e-309', 1e-309, True, 'zero', None),
    LiveNumberCase('-1e-309', -1e-309, True, 'zero', None),
    LiveNumberCase('1e-310', 1e-310, True, 'zero', None),
    LiveNumberCase('-1e-310', -1e-310, True, 'zero', None),
    LiveNumberCase('1e-320', 1e-320, True, 'zero', None),
    LiveNumberCase('-1e-320', -1e-320, True, 'zero', None),
    LiveNumberCase('DBL_TRUE_MIN 5e-324', 5e-324, True, 'zero', None),
    LiveNumberCase('-DBL_TRUE_MIN 5e-324', -5e-324, True, 'zero', None),
]
# fmt: on


def _is_negative_zero(value: float) -> bool:
    """Whether ``value`` is the one row no full-precision writer can preserve."""
    return value == 0.0 and math.copysign(1.0, value) < 0


class Partition(NamedTuple):
    """How one direction's writer or parser split the corpus: the published table row."""

    exact: int
    changed: int
    zero: int

    @property
    def total(self) -> int:
        return self.exact + self.changed + self.zero


# The three published rows, DERIVED from the table above rather than transcribed
# beside it (#770 review found the result row's split misreported). The two
# surfaces allowed to quote a corpus count — ``gda.live_numbers``'s module
# docstring and ``docs/command-catalog.md`` — are read back against these by
# ``tests/test_live_numbers.py``, and the engine tier re-derives the same three
# rows from a running Godot.
PARTITIONS: dict[str, Partition] = {
    # `JSON.parse_string` on the literal `json.dumps` writes for the value.
    "request": Partition(
        exact=sum(1 for case in LIVE_NUMBER_CORPUS if case.request_ulp_gap == 0),
        changed=sum(
            1
            for case in LIVE_NUMBER_CORPUS
            if case.request_ulp_gap is not None and case.request_ulp_gap > 0
        ),
        zero=sum(1 for case in LIVE_NUMBER_CORPUS if case.engine_parse_zeroes),
    ),
    # Godot's DEFAULT `JSON.stringify` — the writer the harness used before #752.
    "default_stringify": Partition(
        exact=sum(
            1 for case in LIVE_NUMBER_CORPUS if case.default_stringify == "exact"
        ),
        changed=sum(
            1 for case in LIVE_NUMBER_CORPUS if case.default_stringify == "changed"
        ),
        zero=sum(1 for case in LIVE_NUMBER_CORPUS if case.default_stringify == "zero"),
    ),
    # `JSON.stringify(value, "", true, true)` — the writer the harness uses now.
    # Exact everywhere except the negative zero, which the engine renders "0.0"
    # before the precision argument is consulted, so the split follows from the
    # values themselves rather than from a recorded column.
    "full_precision": Partition(
        exact=sum(
            1 for case in LIVE_NUMBER_CORPUS if not _is_negative_zero(case.value)
        ),
        changed=sum(1 for case in LIVE_NUMBER_CORPUS if _is_negative_zero(case.value)),
        zero=0,
    ),
}


# --- The verdict helpers both engine tiers read -------------------------------
# A second definition of "exact" would be a fork of this table's semantics, so the
# live e2e and the headless e2e share these rather than each spelling their own.


def value_bits(value: float) -> str:
    """One value's IEEE-754 bytes — the only comparison that is not itself lossy."""
    return struct.pack("<d", value).hex()


def stringify_outcome(sent: float, arrived: float) -> DefaultStringify:
    """The three-state verdict one direction gave one value (cf. LiveNumberCase).

    ``changed`` and ``zero`` are DIFFERENT failures — a rounded value still
    carries the caller's magnitude, a flattened one does not — so the corpus
    records which, and the published table reports both.
    """
    if value_bits(arrived) == value_bits(sent):
        return "exact"
    if arrived == 0.0 and sent != 0.0:
        return "zero"
    return "changed"


def tally_outcome(counts: list[int], sent: float, arrived: float) -> None:
    """Add one value's verdict to an ``[exact, changed, zero]`` tally."""
    counts[("exact", "changed", "zero").index(stringify_outcome(sent, arrived))] += 1
