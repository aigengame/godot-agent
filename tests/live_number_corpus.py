"""The #752 live-number differential corpus, and the verdicts a real engine gave it.

Both a unit test (``tests/test_live_numbers.py``, which checks gda's model of the
engine against this table) and an e2e test
(``tests/test_e2e_live_number_transport.py``, which re-derives the table from a
real engine) read these rows, so the fast tier and the engine tier can never
disagree about what the corpus says.

Every row is ``(label, value, engine_parse_zeroes, default_stringify_exact,
request_ulp_gap)``:

- ``value`` is an exact binary64 value — the ``repr`` here round-trips.
- ``engine_parse_zeroes`` is the REQUEST direction: Godot 4.6.3's
  ``JSON.parse_string`` read the literal ``json.dumps(value)`` produces as
  ``0.0`` although the value is not zero. This is the verdict
  :func:`gda.live_numbers.wire_flattens_to_zero` must reproduce.
- ``default_stringify_exact`` is the RESULT direction under Godot's DEFAULT
  ``JSON.stringify`` — false wherever the harness's pre-#752 writer would have
  changed the value. The full-precision writer the harness now uses is exact on
  every row, which is what makes that column the red-proof of the fix.
- ``request_ulp_gap`` is how far a value that DID arrive landed from the one
  sent, counted in representable doubles (0 = exact); ``None`` where the engine
  flattened it to ``0.0``, since a distance from zero would say nothing. This
  column is what makes the disclosed residual checkable rather than asserted:
  the rows record 1 and 2 for the ordinary and scientific bands, and 31 and 105
  for the MANTISSA-CAP band, where a literal carrying more than 18 mantissa
  digits has its low-order digits dropped outright.

Measured on Godot 4.6.3.stable.official.7d41c59c4. Not a specification of the
engine — a recording of it; the e2e test is what keeps the recording true.
"""

# fmt: off
LIVE_NUMBER_CORPUS: list[tuple[str, float, bool, bool, int | None]] = [
    ('zero', 0.0, False, True, 0),
    ('-zero', -0.0, False, False, 0),
    ('one', 1.0, False, True, 0),
    ('-one', -1.0, False, True, 0),
    ('half', 0.5, False, True, 0),
    ('-half', -0.5, False, True, 0),
    ('tenth', 0.1, False, True, 0),
    ('-tenth', -0.1, False, True, 0),
    ('pi', 3.141592653589793, False, False, 0),
    ('-pi', -3.141592653589793, False, False, 0),
    ('third', 0.3333333333333333, False, False, 0),
    ('-third', -0.3333333333333333, False, False, 0),
    ('1e-4', 0.0001, False, True, 0),
    ('-1e-4', -0.0001, False, True, 0),
    ('1e-5', 1e-05, False, True, 0),
    ('-1e-5', -1e-05, False, True, 0),
    ('1e15', 1000000000000000.0, False, True, 0),
    ('-1e15', -1000000000000000.0, False, True, 0),
    ('1e16', 1e+16, False, True, 0),
    ('-1e16', -1e+16, False, True, 0),
    ('1e17', 1e+17, False, True, 0),
    ('-1e17', -1e+17, False, True, 0),
    ('1e22', 1e+22, False, True, 0),
    ('-1e22', -1e+22, False, True, 0),
    ('1e23', 1e+23, False, True, 0),
    ('-1e23', -1e+23, False, True, 0),
    ('2**53', 9007199254740992.0, False, True, 0),
    ('-2**53', -9007199254740992.0, False, True, 0),
    ('1e100', 1e+100, False, True, 0),
    ('-1e100', -1e+100, False, True, 0),
    ('1.23..e100', 1.2345678901234567e+100, False, True, 1),
    ('-1.23..e100', -1.2345678901234567e+100, False, True, 1),
    ('1e300', 1e+300, False, True, 0),
    ('-1e300', -1e+300, False, True, 0),
    ('1.23..e300', 1.2345678901234567e+300, False, True, 0),
    ('-1.23..e300', -1.2345678901234567e+300, False, True, 0),
    ('1e308', 1e+308, False, True, 0),
    ('-1e308', -1e+308, False, True, 0),
    ('DBL_MAX', 1.7976931348623157e+308, False, True, 0),
    ('-DBL_MAX', -1.7976931348623157e+308, False, True, 0),
    ('1 ULP drift ~13.6', 13.591409142295225, False, False, 1),
    ('-1 ULP drift ~13.6', -13.591409142295225, False, False, 1),
    ('1 ULP drift ~1250', 1250.3538761287377, False, False, 1),
    ('-1 ULP drift ~1250', -1250.3538761287377, False, False, 1),
    ('1 ULP drift ~9e4 (16 digits)', 90333.33333333333, False, False, 1),
    ('-1 ULP drift ~9e4 (16 digits)', -90333.33333333333, False, False, 1),
    ('mantissa cap ~1.2e-3', 0.0012345678901234567, False, False, 31),
    ('-mantissa cap ~1.2e-3', -0.0012345678901234567, False, False, 31),
    ('mantissa cap ~1.4e-4', 0.00014285714285714284, False, False, 105),
    ('-mantissa cap ~1.4e-4', -0.00014285714285714284, False, False, 105),
    ('2 ULP drift ~3.1e-291', 3.141592653589793e-291, False, False, 2),
    ('-2 ULP drift ~3.1e-291', -3.141592653589793e-291, False, False, 2),
    ('1e-10', 1e-10, False, True, 0),
    ('-1e-10', -1e-10, False, True, 0),
    ('1e-31', 1e-31, False, True, 0),
    ('-1e-31', -1e-31, False, True, 0),
    ('1e-32', 1e-32, False, True, 1),
    ('-1e-32', -1e-32, False, True, 1),
    ('1e-33', 1e-33, False, False, 1),
    ('-1e-33', -1e-33, False, False, 1),
    ('1e-40', 1e-40, False, False, 0),
    ('-1e-40', -1e-40, False, False, 0),
    ('1e-100', 1e-100, False, False, 0),
    ('-1e-100', -1e-100, False, False, 0),
    ('1.23..e-100', 1.2345678901234567e-100, False, False, 0),
    ('-1.23..e-100', -1.2345678901234567e-100, False, False, 0),
    ('1e-200', 1e-200, False, False, 0),
    ('-1e-200', -1e-200, False, False, 0),
    ('1e-300', 1e-300, False, False, 0),
    ('-1e-300', -1e-300, False, False, 0),
    ('1.0000000000000002e-300', 1.0000000000000002e-300, True, False, None),
    ('-1.0000000000000002e-300', -1.0000000000000002e-300, True, False, None),
    ('1.23..e-300', 1.2345678901234568e-300, True, False, None),
    ('-1.23..e-300', -1.2345678901234568e-300, True, False, None),
    ('1e-305', 1e-305, False, False, 1),
    ('-1e-305', -1e-305, False, False, 1),
    ('1e-307', 1e-307, False, False, 1),
    ('-1e-307', -1e-307, False, False, 1),
    ('1e-308', 1e-308, False, False, 0),
    ('-1e-308', -1e-308, False, False, 0),
    ('DBL_MIN', 2.2250738585072014e-308, True, False, None),
    ('-DBL_MIN', -2.2250738585072014e-308, True, False, None),
    ('max subnormal', 2.225073858507201e-308, True, False, None),
    ('-max subnormal', -2.225073858507201e-308, True, False, None),
    ('exp -308 (16 digits)', 2.209278197011611e-293, False, False, 0),
    ('-exp -308 (16 digits)', -2.209278197011611e-293, False, False, 0),
    ('exp -309 (17 digits)', 3.2956212316547955e-293, True, False, None),
    ('-exp -309 (17 digits)', -3.2956212316547955e-293, True, False, None),
    ('1e-309', 1e-309, True, False, None),
    ('-1e-309', -1e-309, True, False, None),
    ('1e-310', 1e-310, True, False, None),
    ('-1e-310', -1e-310, True, False, None),
    ('1e-320', 1e-320, True, False, None),
    ('-1e-320', -1e-320, True, False, None),
    ('DBL_TRUE_MIN 5e-324', 5e-324, True, False, None),
    ('-DBL_TRUE_MIN 5e-324', -5e-324, True, False, None),
]
# fmt: on
