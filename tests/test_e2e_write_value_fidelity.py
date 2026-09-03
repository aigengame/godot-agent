"""S1 (e2e): the WRITE direction — what a ``--value`` literal becomes (#772).

The sibling of ``tests/test_e2e_headless_number_reads.py`` (the headless READ half,
#771) and of ``tests/test_e2e_live_number_transport.py`` (both live halves, #752).
This module asks the remaining question of both channels: when a caller spells a
number on the command line, does the project end up holding it?

It reads the SAME table the other two do, ``tests/live_number_corpus.py``. That is
not tidiness: ``String.to_float`` is ``built_in_strtod``, the very function
``JSON.parse_string`` calls for a number, so a second corpus would be a second
opinion about one engine function. What differs is WHO spells the literal — gda on
the wire, the caller on a write — which is why the write direction needs its own
spellings of those same values rather than its own values.

Two tiers, both against the real binary:

**The engine tier** feeds every corpus row to ``String.to_float`` in two spellings
and compares gda's POLICY, expressed here in Python, against what the engine did.
That is what makes the policy checkable rather than asserted: the outcomes come from
Godot, the rule comes from this file, and neither is the GDScript under test.

**The command tier** then drives the real commands — headless ``node set`` and, over
a real daemon and a real engine session, live ``game set`` — over the classes the
engine tier found. It is the regression the issue asks for: a literal in the
affected class either round-trips exactly or is REFUSED, and never lands as a
silently different number.
"""

import json
import math
import struct
import subprocess

import pytest

from tests.live_number_corpus import LIVE_NUMBER_CORPUS, value_bits
from tests.support import GODOT, Gda

from .conftest import LIVE_PROJECT_GODOT


# --- the policy, expressed independently of the GDScript that implements it ----


def names_zero(literal: str) -> bool:
    """Whether ``literal``'s own digits are all zeros — the spellings that MEAN zero."""
    mantissa = literal.lstrip("+-").lower().partition("e")[0]
    return set(mantissa) <= {"0", "."}


def policy_refuses(literal: str, parsed: float) -> bool:
    """gda's write-side rule (#772), given what the engine's parser produced."""
    return math.isnan(parsed) or (parsed == 0.0 and not names_zero(literal))


def fixed_spelling(value: float) -> str:
    """A FIXED-notation spelling of ``value`` — the one Python's ``repr`` avoids.

    The write direction's own hazard lives here: ``repr(1e-18)`` is ``1e-18``, but a
    caller who types the same number out in full hands the parser 18 leading zeros,
    which is its entire mantissa window.
    """
    from decimal import Decimal

    return "0.0" if value == 0.0 else format(Decimal(value), "f")


# --- the engine tier ----------------------------------------------------------

_PROBE = """\
extends SceneTree

const BEGIN := "<<<ROWS>>>"
const END := "<<<END>>>"

func _initialize() -> void:
\tvar path := OS.get_cmdline_user_args()[0]
\tvar file := FileAccess.open(path, FileAccess.READ)
\tvar literals: Array = JSON.parse_string(file.get_as_text())
\tfile.close()
\tvar rows := PackedStringArray()
\tfor literal in literals:
\t\tvar text: String = literal
\t\tvar bytes := PackedByteArray()
\t\tbytes.resize(8)
\t\tbytes.encode_double(0, text.to_float())
\t\trows.append(bytes.hex_encode())
\tprint(BEGIN)
\tprint(JSON.stringify(rows))
\tprint(END)

func _process(_delta: float) -> bool:
\treturn true
"""


def _parse_literals(tmp_path, literals: list[str]) -> list[float]:
    """What a real Godot's ``String.to_float`` makes of each literal, bit-exactly."""
    probe = tmp_path / "to_float_probe.gd"
    probe.write_text(_PROBE, encoding="utf-8")
    payload = tmp_path / "literals.json"
    payload.write_text(json.dumps(literals), encoding="utf-8")

    run = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--log-file",
            str(tmp_path / "probe.log"),
            "--script",
            str(probe),
            "--",
            str(payload),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    body = run.stdout.split("<<<ROWS>>>\n")[1].split("\n<<<END>>>")[0]
    rows = json.loads(body)
    assert len(rows) == len(literals), run.stdout + run.stderr
    return [struct.unpack("<d", bytes.fromhex(row))[0] for row in rows]


def _corpus_spellings() -> list[str]:
    """Every corpus row in BOTH spellings — the sweep this direction is measured on.

    ``repr`` is what ``json.dumps`` puts on the wire; the fixed spelling is what a
    caller types. A ``5e-324`` written out in full is not a spelling anyone types, so
    the fixed form is dropped past 400 characters.
    """
    literals: list[str] = []
    for case in LIVE_NUMBER_CORPUS:
        literals.append(repr(case.value))
        fixed = fixed_spelling(case.value)
        if len(fixed) < 400:
            literals.append(fixed)
    return literals


@pytest.mark.e2e
def test_the_write_policy_matches_what_this_engine_does_to_the_corpus(tmp_path):
    """Every corpus row, in both spellings, judged by the engine and by the rule.

    The rule refuses exactly the literals the parser DESTROYS — turns into ``0.0``
    when the caller wrote no zero, or into ``NaN`` — and accepts everything else,
    drift included. Asserting that over the whole corpus is what makes "observe the
    outcome" a claim about this engine rather than about three examples.
    """
    literals = _corpus_spellings()

    measured = list(zip(literals, _parse_literals(tmp_path, literals)))
    refused = [row for row in measured if policy_refuses(*row)]
    accepted = [row for row in measured if not policy_refuses(*row)]

    # Nothing the policy ACCEPTS may be a destroyed value: an accepted literal that
    # names a non-zero number must not have arrived as zero or NaN. This is the
    # whole safety claim, checked against the engine over every row.
    for literal, value in accepted:
        assert not math.isnan(value), literal
        if not names_zero(literal):
            assert value != 0.0, literal

    # ...and over these rows nothing it REFUSES is a literal this engine handled
    # faithfully, judged against a correctly-rounded parser (Python's own). `0e600`
    # is in here because the engine answers NaN where a correct parser answers 0.0 —
    # the disagreement, not the magnitude, is the test. This is a claim about the
    # corpus, not a universal one: a literal below binary64's reach (`1e-400`, which
    # BOTH parsers read as 0.0) is refused too, deliberately, and no corpus value can
    # be spelled that way. `WRITE_CASES` carries it as its own control.
    assert refused, "the corpus must contain literals this engine destroys"
    for literal, value in refused:
        assert value_bits(value) != value_bits(float(literal)), literal

    # The two mechanisms this sweep can carry, each present in it.
    refused_literals = [literal for literal, _ in refused]
    assert repr(5e-324) in refused_literals  # the -309 cliff (#752's class)
    assert repr(2.2250738585072014e-308) in refused_literals  # DBL_MIN
    # 18 leading zeros fill the parser's whole mantissa window, so the SAME value
    # the scientific spelling carries is destroyed when it is written out in full.
    assert fixed_spelling(1e-100) in refused_literals
    assert repr(1e-100) not in refused_literals

    # The remedy is real, and measured rather than asserted: the two mantissa-cap
    # rows come back EXACT once they are spelled in scientific notation, while
    # Python's own fixed spelling of them is what lands 31 and 105 doubles away.
    capped = [0.0012345678901234567, 0.00014285714285714284]
    scientific = [format(value, ".17e") for value in capped]
    for value, arrived in zip(capped, _parse_literals(tmp_path, scientific)):
        assert value_bits(arrived) == value_bits(value)


# The literal set this direction PUBLISHES its measurement over: every corpus row
# in both spellings, plus `WRITE_CASES`, plus the edge literals the contract names
# by hand. Spelled out here, and partitioned by the test below, so the published
# counts are re-derivable from an artifact instead of hand-carried in prose — the
# discipline #770 established for the READ side's `gda.live_numbers.PARTITIONS`.
NAMED_EDGE_LITERALS = (
    "1e400",  # the accepted overflow
    "0.0012345678901234567",  # the mantissa-cap rows the remedy is named on: the
    "1.2345678901234567e-3",  # fixed spelling drifts, the scientific one is exact
    "1.4285714285714284e-4",
)

# Five buckets, every literal in exactly one, measured on Godot 4.6.3. `nan` and
# `inf` are the two single-member edges the contract names; `1e-400` sits in
# `zeroed` and is refused with the rest of that bucket although 0.0 is the
# correctly-rounded answer there. `refused` is `zeroed` + `nan`, which is the whole
# rule: everything else is accepted, drift included.
PUBLISHED_PARTITION = {"exact": 109, "drifted": 31, "zeroed": 37, "nan": 1, "inf": 1}
PUBLISHED_REFUSED = 38


@pytest.mark.e2e
def test_the_published_partition_is_what_this_engine_produces(tmp_path):
    """The counts the contract publishes, re-derived from a real engine.

    The sibling test above asserts the rule's PROPERTIES over the corpus; this one
    pins the SHAPE of the outcome over the whole published set, so the numbers a
    reader is given can be checked rather than trusted. A corpus edit or an engine
    whose parser changed fails here loudly, which is the point.
    """
    literals = (
        _corpus_spellings()
        + [literal for literal, _, _ in WRITE_CASES]
        + list(NAMED_EDGE_LITERALS)
    )
    measured = list(zip(literals, _parse_literals(tmp_path, literals)))

    buckets: dict[str, list[str]] = {name: [] for name in PUBLISHED_PARTITION}
    for literal, value in measured:
        if math.isnan(value):
            buckets["nan"].append(literal)
        elif math.isinf(value):
            buckets["inf"].append(literal)
        elif value == 0.0 and not names_zero(literal):
            buckets["zeroed"].append(literal)
        elif value_bits(value) == value_bits(float(literal)):
            buckets["exact"].append(literal)
        else:
            buckets["drifted"].append(literal)

    assert {name: len(rows) for name, rows in buckets.items()} == PUBLISHED_PARTITION
    assert sum(len(rows) for rows in buckets.values()) == len(literals)
    assert buckets["nan"] == ["0e600"]
    assert buckets["inf"] == ["1e400"]
    assert "1e-400" in buckets["zeroed"]

    refused = [row for row in measured if policy_refuses(*row)]
    assert len(refused) == PUBLISHED_REFUSED
    assert PUBLISHED_REFUSED == len(buckets["zeroed"]) + len(buckets["nan"])

    # The load-bearing claim, over every published row: nothing the rule ACCEPTS is
    # a destroyed value.
    for literal, value in measured:
        if policy_refuses(literal, value):
            continue
        assert not math.isnan(value), literal
        if not names_zero(literal):
            assert value != 0.0, literal


# --- the command tier: headless `node set` ------------------------------------

# The export's default is 1.0, NOT 0.0, and that is load-bearing. Godot's scene
# packer OMITS a property whose value is not "different" from its default, and its
# difference test compares two floats APPROXIMATELY, as float32
# (`PropertyUtils::is_property_value_different` -> `Math::is_equal_approx`,
# `packed_scene.cpp`). So against a 0.0 default every value under ~1e-5 is elided
# from the .tscn and reads back as 0.0 — a real silent loss, but the PACKER's and
# not the parser's, so this module keeps it out of the way instead of measuring it
# (`docs/command-catalog.md` records it under "Number coercion").
# The extra properties are the note-attribution controls: a type that never
# reaches the float parser at all (`n`), one that takes the literal verbatim (`s`),
# and a list type whose ARITY can fail before any component is parsed (`pos2`) —
# plus the two containers (`d`, `a`), which reach the SAME rule by a different
# route: no per-element coercion, so their numbers are read from the raw text
# (#805).
PROBE_GD = (
    "extends Node2D\n\n"
    "@export var v: float = 1.0\n"
    "@export var n: int = 0\n"
    "@export var d: Dictionary = {}\n"
    "@export var a: Array = []\n"
    '@export var s: String = ""\n'
    "@export var pos2: Vector2 = Vector2.ZERO\n"
)
PROBE_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://probe.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)

# One row per class the engine tier found, plus the controls that keep the refusal
# narrow. `refused` is the outcome; `note` is the phrase the message must carry.
WRITE_CASES = [
    # The -309 cliff — the class the live wire already refuses (#752).
    ("5e-324", True, "as 0.0"),
    ("2.2250738585072014e-308", True, "as 0.0"),
    ("-1.2345678901234567e-300", True, "as 0.0"),
    # The write direction's OWN cliff: 18 leading zeros are the whole mantissa
    # window, so a fixed spelling of a value scientific notation carries exactly.
    ("0.000000000000000001", True, "as 0.0"),
    ("0.000000000000000000123", True, "as 0.0"),
    ("-0.0000000000000000000000000000001", True, "as 0.0"),
    # A zero mantissa scaled by an overflowed power.
    ("0e600", True, "as NaN"),
    # Below binary64's reach, where 0.0 is what a CORRECT parser gives too. Refused
    # all the same: the coercion reads the outcome, not the mechanism, and a caller
    # who means zero writes `0` (`gda.live_numbers` records why).
    ("1e-400", True, "as 0.0"),
    # Controls: the literals that MEAN zero are not refusals, and neither is the
    # neighbouring value the parser can build.
    ("0.0", False, None),
    ("-0.0", False, None),
    ("0", False, None),
    ("0.0000e5", False, None),
    ("1e-18", False, None),
    ("1e-308", False, None),
    ("0.00000000000000001", False, None),
]


@pytest.fixture
def probe_project(godot_project):
    (godot_project / "probe.gd").write_text(PROBE_GD, encoding="utf-8")
    (godot_project / "main.tscn").write_text(PROBE_TSCN, encoding="utf-8")
    return godot_project


@pytest.mark.e2e
def test_node_set_refuses_a_literal_the_parser_destroys(probe_project):
    """The regression the issue asks for: exact, or refused — never silently different.

    Before #772 each refused row here SUCCEEDED and stored ``0.0`` (or ``NaN``),
    reporting success on a number the caller never sent, and the scene file was
    rewritten with it.
    """
    scene = probe_project / "main.tscn"
    run = Gda(probe_project, json_output=True, timeout=180)

    for literal, refused, note in WRITE_CASES:
        before = scene.read_text(encoding="utf-8")
        result = run(
            "node",
            "set",
            str(scene),
            "--node",
            ".",
            "--property",
            "v",
            "--value",
            literal,
        )

        if refused:
            assert result.returncode == 4, (literal, result.stdout, result.stderr)
            error = json.loads(result.stdout)["error"]
            assert error["code"] == "uncoercible_value", literal
            assert "Godot's own float parser reads" in error["message"], literal
            assert note in error["message"], literal
            # A refusal leaves the scene exactly as it was: the write never happened.
            assert scene.read_text(encoding="utf-8") == before, literal
            continue

        assert result.returncode == 0, (literal, result.stdout, result.stderr)
        stored = json.loads(result.stdout)["value"]
        # `-0.0` is compared as `0.0`: the ECHO is JSON the engine writes, and its
        # one disclosed residual is that a negative zero reads back as `0.0`
        # (#752/#771). That is the writer's, decided before the value is seen, and
        # is exactly why this policy is about literals the PARSER destroys.
        expected = float(literal) + 0.0
        assert value_bits(stored) == value_bits(expected), literal

        # ...and a following read reports the same value the echo did (#771).
        read = run("node", "get", str(scene), "--node", ".")
        assert read.returncode == 0, read.stdout + read.stderr
        properties = json.loads(read.stdout)["properties"]
        value = next(entry["value"] for entry in properties if entry["name"] == "v")
        assert value_bits(value) == value_bits(stored), literal


@pytest.mark.e2e
def test_the_refusal_is_narrow_and_names_its_remedy(probe_project):
    """It refuses a LOSS, not a magnitude, and tells the caller what to type instead."""
    scene = probe_project / "main.tscn"
    run = Gda(probe_project, json_output=True, timeout=180)

    # A value that is not a number at all keeps the message it always had: the
    # fidelity note must not relabel an ordinary coercion failure.
    plain = run(
        "node", "set", str(scene), "--node", ".", "--property", "v", "--value", "abc"
    )
    assert plain.returncode == 4, plain.stdout
    assert (
        "Godot's own float parser reads"
        not in json.loads(plain.stdout)["error"]["message"]
    )

    # The remedy the refusal names is the one that works. Same value, two
    # spellings: the fixed one is refused, the scientific one is stored exactly.
    refused = run(
        "node",
        "set",
        str(scene),
        "--node",
        ".",
        "--property",
        "v",
        "--value",
        "0.000000000000000001",
    )
    assert refused.returncode == 4, refused.stdout
    assert "scientific notation" in json.loads(refused.stdout)["error"]["message"]

    accepted = run(
        "node", "set", str(scene), "--node", ".", "--property", "v", "--value", "1e-18"
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert value_bits(json.loads(accepted.stdout)["value"]) == value_bits(1e-18)

    # The disclosed residual is disclosed, not refused: a full-precision literal in
    # fixed notation is STORED, 31 doubles from what was typed, and the echo says
    # so; its scientific spelling of the same value is exact. That difference is
    # the whole reason the contract points at scientific notation.
    drifted = run(
        "node",
        "set",
        str(scene),
        "--node",
        ".",
        "--property",
        "v",
        "--value",
        "0.0012345678901234567",
    )
    assert drifted.returncode == 0, drifted.stdout + drifted.stderr
    stored = json.loads(drifted.stdout)["value"]
    assert stored != 0.0
    assert value_bits(stored) != value_bits(0.0012345678901234567)

    exact = run(
        "node",
        "set",
        str(scene),
        "--node",
        ".",
        "--property",
        "v",
        "--value",
        "1.2345678901234567e-3",
    )
    assert exact.returncode == 0, exact.stdout + exact.stderr
    assert value_bits(json.loads(exact.stdout)["value"]) == value_bits(
        0.0012345678901234567
    )

    # An OVERFLOW is the other edge the contract names, and it is not refused:
    # `1e400` reads as `inf`, which the reply reports as JSON `null`. That is a
    # value no caller can mistake for the number they typed, which is why it is
    # outside a rule about SILENT substitution.
    overflow = run(
        "node", "set", str(scene), "--node", ".", "--property", "v", "--value", "1e400"
    )
    assert overflow.returncode == 0, overflow.stdout + overflow.stderr
    assert json.loads(overflow.stdout)["value"] is None, overflow.stdout
    assert "v = inf" in scene.read_text(encoding="utf-8")


# The container corpus (#805). A number inside a JSON `--value` reaches the write
# rule by the only route it can — read out of the RAW text after the JSON gate
# accepts it — so these rows are the corpus classes above, restated where no
# per-element coercion exists to catch them.
CONTAINER_REFUSED = [
    ("d", '{"a": 1e-320}', "reads 1e-320 as 0.0"),
    ("d", '{"a": 1e-320, "b": 0.000000000000000001}', "reads 1e-320 as 0.0"),
    # Nesting is not a hiding place: the scan is over the whole text.
    ("d", '{"a": {"b": [0e600]}}', "reads 0e600 as NaN"),
    ("a", "[1.0, 5e-324]", "reads 5e-324 as 0.0"),
    ("a", "[[2.2250738585072014e-308]]", "reads 2.2250738585072014e-308 as 0.0"),
    ("a", "[-1.2345678901234567e-300]", "reads -1.2345678901234567e-300 as 0.0"),
]

# What the scan must NOT refuse — the two traps a raw-text scan invites, plus the
# ordinary values whose exactness the rule exists to protect.
CONTAINER_ACCEPTED = [
    # A STRING value that looks like a number IS a string: no float is parsed
    # anywhere in it, so there is nothing for the parser to destroy.
    ("d", '{"a": "1e-320"}', {"a": "1e-320"}),
    # Every JSON key is a string, so a key is never a number token either.
    ("d", '{"1e-320": 1.0}', {"1e-320": 1.0}),
    # ...and an ESCAPED quote must not end a string early, or the scan would read
    # this key's own text as though it sat outside one and refuse a valid write.
    ("d", '{"a\\": 1e-320 fake": 1.0}', {'a": 1e-320 fake': 1.0}),
    # Exact values still store exactly, the spellings that MEAN zero included, and
    # the non-numbers pass through untouched. `-0.0` reads back as `0.0`: the
    # engine writer's disclosed residual, decided before the value is seen.
    (
        "d",
        '{"a": 1e-18, "b": 2.5, "c": 0.0, "d": -0.0, "z": 0,'
        ' "t": true, "f": false, "n": null}',
        {
            "a": 1e-18,
            "b": 2.5,
            "c": 0.0,
            "d": 0.0,
            "z": 0,
            "t": True,
            "f": False,
            "n": None,
        },
    ),
    ("a", "[1e-308, 0.0000e5, 3]", [1e-308, 0.0, 3]),
]

# Refused, but NOT by the float parser — so each keeps the plain message. The
# first is the `str_to_var` edge: it would build a zeroed `Vector2` from that
# text, but the text is not JSON, so the gate refuses it before `str_to_var` runs.
CONTAINER_PLAIN_REFUSAL = [
    ("d", '{"a": Vector2(1e-320, 0)}', "Dictionary"),
    ("d", "[1e-320]", "Dictionary"),
    ("a", '{"x": 1e-320}', "Array"),
]


@pytest.mark.e2e
def test_node_set_refuses_a_destroyed_number_inside_a_container(probe_project):
    """The container half of the rule (#805): the last path that stored silently.

    Before this, ``--value '{"a": 1e-320}'`` returned exit 0 and wrote
    ``{"a": 0.0}`` into the scene — the exact failure shape #772 refuses for a
    scalar, alive on the one path its per-component walk could not reach.
    """
    scene = probe_project / "main.tscn"
    run = Gda(probe_project, json_output=True, timeout=180)

    for prop, value, note in CONTAINER_REFUSED:
        before = scene.read_text(encoding="utf-8")
        result = run(
            "node",
            "set",
            str(scene),
            "--node",
            ".",
            "--property",
            prop,
            "--value",
            value,
        )
        assert result.returncode == 4, (value, result.stdout, result.stderr)
        error = json.loads(result.stdout)["error"]
        assert error["code"] == "uncoercible_value", value
        # The same code AND the same message family as the scalar path, naming the
        # ONE offending literal rather than the whole argument.
        assert "Godot's own float parser reads" in error["message"], value
        assert note in error["message"], value
        assert scene.read_text(encoding="utf-8") == before, value

    for prop, value, expected in CONTAINER_ACCEPTED:
        result = run(
            "node",
            "set",
            str(scene),
            "--node",
            ".",
            "--property",
            prop,
            "--value",
            value,
        )
        assert result.returncode == 0, (value, result.stdout, result.stderr)
        assert json.loads(result.stdout)["value"] == expected, value

        # ...and a following read reports what the echo did.
        read = run("node", "get", str(scene), "--node", ".")
        assert read.returncode == 0, read.stdout + read.stderr
        properties = json.loads(read.stdout)["properties"]
        stored = next(entry["value"] for entry in properties if entry["name"] == prop)
        assert stored == expected, value

    for prop, value, type_name in CONTAINER_PLAIN_REFUSAL:
        result = run(
            "node",
            "set",
            str(scene),
            "--node",
            ".",
            "--property",
            prop,
            "--value",
            value,
        )
        assert result.returncode == 4, (value, result.stdout, result.stderr)
        error = json.loads(result.stdout)["error"]
        assert error["code"] == "uncoercible_value", value
        # The message the failure always had — no float explanation, because the
        # float parser did not decide it (the argument is quoted through
        # `c_escape`, so only the suffix is compared literally).
        assert "Godot's own float parser reads" not in error["message"], value
        assert error["message"].endswith(
            f" to {type_name} for property {prop} on node ."
        ), value


@pytest.mark.e2e
def test_the_note_explains_only_the_refusal_it_diagnosed(probe_project):
    """The note belongs to the FLOAT coercion, not to every uncoercible failure.

    A destroyed literal in the argument text is not the same fact as a coercion
    that refused BECAUSE of it. An `int`, a `Dictionary` given a value that is not
    JSON, and a wrong-arity `Vector2` are refused by something other than the float
    parser, so no re-spelling would fix them — attaching the fidelity explanation
    to them names a false cause and an unreachable remedy. Each of these carried
    the note before this test existed. (A container given valid JSON is the case
    where the parser DOES decide, and it carries the note — see
    `test_node_set_refuses_a_destroyed_number_inside_a_container`.)
    """
    scene = probe_project / "main.tscn"
    run = Gda(probe_project, json_output=True, timeout=180)

    def message(*args):
        result = run("node", "set", str(scene), "--node", ".", *args)
        assert result.returncode == 4, (args, result.stdout, result.stderr)
        payload = json.loads(result.stdout)["error"]
        assert payload["code"] == "uncoercible_value", args
        return payload["message"]

    # An int property: the int coercion refuses `1e-320` because it is not an int
    # spelling. The float parser is not involved, and the base message is exact.
    assert message("--property", "n", "--value", "1e-320") == (
        "cannot coerce value 1e-320 to int for property n on node ."
    )
    # A Dictionary property given a value that is not a JSON object: refused by
    # the JSON gate, not by `String.to_float`, so the note stays off it even
    # though the argument text spells a destroyed literal (#805).
    assert message("--property", "d", "--value", "0.000000000000000001") == (
        "cannot coerce value 0.000000000000000001 to Dictionary"
        " for property d on node ."
    )
    # A Vector2 with three components fails on ARITY, before a component is parsed.
    assert message("--property", "pos2", "--value", "1,2,1e-320") == (
        "cannot coerce value 1,2,1e-320 to Vector2 for property pos2 on node ."
    )
    # A component that is not a float spelling at all stops the walk where
    # `_coerce_float_list` stops: the failure is that component, not the later one.
    assert message("--property", "pos2", "--value", "abc,1e-320") == (
        "cannot coerce value abc,1e-320 to Vector2 for property pos2 on node ."
    )

    # The positive controls: where the float coercion IS the refusal, the note
    # stays, and a list type names the ONE offending component.
    assert "reads 1e-320 as 0.0" in message("--property", "v", "--value", "1e-320")
    assert "reads 1e-320 as 0.0" in message("--property", "pos2", "--value", "1,1e-320")

    # A String property takes the literal verbatim — there is no float to destroy,
    # so this is a SUCCESS the refusal must never reach.
    stored = run(
        "node", "set", str(scene), "--node", ".", "--property", "s", "--value", "1e-320"
    )
    assert stored.returncode == 0, stored.stdout + stored.stderr
    assert json.loads(stored.stdout)["value"] == "1e-320"


# The container rows restated for the OTHER two headless commands. `node set`
# above drives the full corpus; what these pin is that the container half travels
# with the SHARED coercion rather than with one command (#805 review). Four rows,
# one per thing that can go wrong: the two refusal classes (a literal destroyed to
# `0.0` in a Dictionary, to `NaN` in an Array), the trap the scan must not refuse,
# and an exact value. `note` is the phrase a refusal must carry; `stored` is what
# an acceptance must echo — exactly one of the two is set.
CONTAINER_PER_COMMAND = [
    ("d", '{"a": 1e-320}', "reads 1e-320 as 0.0", None),
    ("a", "[0e600]", "reads 0e600 as NaN", None),
    ("d", '{"a": "1e-320"}', None, {"a": "1e-320"}),
    ("a", "[1e-300]", None, [1e-300]),
]


@pytest.mark.e2e
def test_project_set_shares_the_refusal(probe_project):
    """The policy is the shared coercion's, not `node set`'s (the mirror's point)."""
    (probe_project / "project.godot").write_text(
        (probe_project / "project.godot").read_text(encoding="utf-8")
        + '\n[gda]\n\nprobe/value=1.5\nprobe/dict={"a": 1.0}\nprobe/arr=[1.0]\n',
        encoding="utf-8",
    )
    run = Gda(probe_project, json_output=True, timeout=180)

    refused = run(
        "project", "set", "gda/probe/value", "--value", "0.000000000000000001"
    )
    assert refused.returncode == 4, refused.stdout + refused.stderr
    assert json.loads(refused.stdout)["error"]["code"] == "uncoercible_value"
    assert (
        "Godot's own float parser reads"
        in json.loads(refused.stdout)["error"]["message"]
    )

    accepted = run("project", "set", "gda/probe/value", "--value", "1e-18")
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert value_bits(json.loads(accepted.stdout)["value"]) == value_bits(1e-18)

    # ...and the container half reaches this command too — a setting's declared
    # type is whatever it already holds, so a Dictionary/Array setting takes the
    # same JSON `--value` a Dictionary/Array property does.
    setting = {"d": "gda/probe/dict", "a": "gda/probe/arr"}
    for kind, value, note, stored in CONTAINER_PER_COMMAND:
        result = run("project", "set", setting[kind], "--value", value)
        if note is not None:
            assert result.returncode == 4, (value, result.stdout, result.stderr)
            error = json.loads(result.stdout)["error"]
            assert error["code"] == "uncoercible_value", value
            assert note in error["message"], value
            continue
        assert result.returncode == 0, (value, result.stdout, result.stderr)
        assert json.loads(result.stdout)["value"] == stored, value


# A script-backed Resource with the same two container fields the scene probe
# declares. Hand-written rather than built with `resource create`: the .tres names
# the script as an ExtResource, which loads without the project's class registry,
# so this needs no `--import` pass.
RESOURCE_PROBE_GD = (
    "extends Resource\n\n@export var d: Dictionary = {}\n@export var a: Array = []\n"
)
RESOURCE_PROBE_TRES = (
    '[gd_resource type="Resource" load_steps=2 format=3]\n\n'
    '[ext_resource type="Script" path="res://probe_res.gd" id="1"]\n\n'
    "[resource]\n"
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
def test_resource_set_shares_the_refusal(probe_project):
    """The fourth coercing command: same rule, same code, same message (#805)."""
    (probe_project / "probe_res.gd").write_text(RESOURCE_PROBE_GD, encoding="utf-8")
    resource = probe_project / "probe.tres"
    resource.write_text(RESOURCE_PROBE_TRES, encoding="utf-8")
    run = Gda(probe_project, json_output=True, timeout=180)

    # The scalar rule first, so a container failure below cannot be a `resource
    # set` that never had the rule at all.
    refused = run(
        "resource",
        "set",
        str(resource),
        "--property",
        "d",
        "--value",
        '{"a": 1e-320, "b": 2.0}',
    )
    assert refused.returncode == 4, refused.stdout + refused.stderr
    error = json.loads(refused.stdout)["error"]
    assert error["code"] == "uncoercible_value"
    assert "reads 1e-320 as 0.0" in error["message"]
    # A refusal leaves the file exactly as written: the set never happened.
    assert resource.read_text(encoding="utf-8") == RESOURCE_PROBE_TRES

    for kind, value, note, stored in CONTAINER_PER_COMMAND:
        result = run(
            "resource", "set", str(resource), "--property", kind, "--value", value
        )
        if note is not None:
            assert result.returncode == 4, (value, result.stdout, result.stderr)
            failure = json.loads(result.stdout)["error"]
            assert failure["code"] == "uncoercible_value", value
            assert note in failure["message"], value
            continue
        assert result.returncode == 0, (value, result.stdout, result.stderr)
        assert json.loads(result.stdout)["value"] == stored, value


# --- the command tier: live `game set` through a real daemon -------------------

SET_MAIN_GD = 'extends Node2D\n\nvar v := 1.5\nvar n := 0\nvar d := {"seed": 1.0}\nvar a := [1.0]\n'
SET_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://live_main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
@pytest.mark.skipif("os.name != 'posix'")
def test_game_set_refuses_the_same_literals_against_a_real_daemon(
    tmp_path, daemon_runtime_dir
):
    """The harness copy of the policy, exercised where it actually runs.

    ``game set`` carries the value as a STRING, so ``RelayedLiveParams`` (#752) never
    sees a float and cannot refuse it — the coercion block in ``gda_harness.gd`` is
    the only thing standing between the caller and a silently zeroed live write.
    This is why the block is mirrored, and why it is exercised through a real
    session rather than trusted to the drift test.
    """
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SET_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "live_main.gd").write_text(SET_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True, timeout=180)
    try:
        assert run("daemon", "start").returncode == 0

        for literal in (
            "5e-324",
            "2.2250738585072014e-308",
            "0.000000000000000001",
            "0e600",
        ):
            refused = run(
                "game", "set", "/root/Main", "--property", "v", "--value", literal
            )
            assert refused.returncode != 0, (literal, refused.stdout, refused.stderr)
            error = json.loads(refused.stdout)["error"]
            assert error["code"] == "live_uncoercible_value", literal
            assert "Godot's own float parser reads" in error["message"], literal

            # The running game still holds what it held: a refused write is not a
            # write, so the session's state is untouched.
            read = run("game", "get", "/root/Main", "--property", "v")
            assert read.returncode == 0, read.stdout + read.stderr
            assert json.loads(read.stdout)["properties"][0]["value"] == 1.5, literal

        # The neighbouring value the parser CAN build is written exactly.
        accepted = run(
            "game", "set", "/root/Main", "--property", "v", "--value", "1e-18"
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert value_bits(json.loads(accepted.stdout)["value"]) == value_bits(1e-18)

        # ...and the note's attribution is the harness copy's too: an int variable
        # never reaches the float coercion, so the live refusal keeps the plain
        # message rather than blaming a parser that never saw the literal.
        misattributed = run(
            "game", "set", "/root/Main", "--property", "n", "--value", "1e-320"
        )
        assert misattributed.returncode != 0, misattributed.stdout
        error = json.loads(misattributed.stdout)["error"]
        assert error["code"] == "live_uncoercible_value", misattributed.stdout
        assert error["message"] == (
            "cannot coerce value 1e-320 to int for script variable n on node /root/Main"
        ), misattributed.stdout

        # The container half is the harness copy's too (#805) — the mirrored block
        # is what makes that true, and this is where it is exercised rather than
        # inferred from the drift test.
        for prop, value, note in (
            ("d", '{"a": 1e-320}', "reads 1e-320 as 0.0"),
            ("a", "[0e600]", "reads 0e600 as NaN"),
        ):
            refused = run(
                "game", "set", "/root/Main", "--property", prop, "--value", value
            )
            assert refused.returncode != 0, (value, refused.stdout, refused.stderr)
            error = json.loads(refused.stdout)["error"]
            assert error["code"] == "live_uncoercible_value", value
            assert note in error["message"], value

        # ...and the traps a raw-text scan invites are not refused live either: a
        # numeric-looking string VALUE, and a numeric-looking KEY.
        for value, expected in (
            ('{"a": "1e-320"}', {"a": "1e-320"}),
            ('{"1e-320": 1.0}', {"1e-320": 1.0}),
        ):
            kept = run("game", "set", "/root/Main", "--property", "d", "--value", value)
            assert kept.returncode == 0, (value, kept.stdout, kept.stderr)
            assert json.loads(kept.stdout)["value"] == expected, value
    finally:
        run("daemon", "stop")
