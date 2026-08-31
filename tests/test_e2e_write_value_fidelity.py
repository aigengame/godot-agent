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

from gda.binary import resolve_godot_binary

from tests.live_number_corpus import LIVE_NUMBER_CORPUS, value_bits
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


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


@pytest.mark.e2e
def test_the_write_policy_matches_what_this_engine_does_to_the_corpus(tmp_path):
    """Every corpus row, in both spellings, judged by the engine and by the rule.

    The rule refuses exactly the literals the parser DESTROYS — turns into ``0.0``
    when the caller wrote no zero, or into ``NaN`` — and accepts everything else,
    drift included. Asserting that over the whole corpus is what makes "observe the
    outcome" a claim about this engine rather than about three examples.
    """
    literals: list[str] = []
    for case in LIVE_NUMBER_CORPUS:
        literals.append(repr(case.value))
        fixed = fixed_spelling(case.value)
        if len(fixed) < 400:  # a 5e-324 written out in full is not a spelling
            literals.append(fixed)

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


# --- the command tier: headless `node set` ------------------------------------

# The export's default is 1.0, NOT 0.0, and that is load-bearing. Godot's scene
# packer OMITS a property whose value is not "different" from its default, and its
# difference test compares two floats APPROXIMATELY, as float32
# (`PropertyUtils::is_property_value_different` -> `Math::is_equal_approx`,
# `packed_scene.cpp`). So against a 0.0 default every value under ~1e-5 is elided
# from the .tscn and reads back as 0.0 — a real silent loss, but the PACKER's and
# not the parser's, so this module keeps it out of the way instead of measuring it
# (`docs/command-catalog.md` records it under "Number coercion").
PROBE_GD = "extends Node2D\n\n@export var v: float = 1.0\n"
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


def _headless_runner(project):
    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

    return run


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
    run = _headless_runner(probe_project)

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
    run = _headless_runner(probe_project)

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


@pytest.mark.e2e
def test_project_set_shares_the_refusal(probe_project):
    """The policy is the shared coercion's, not `node set`'s (the mirror's point)."""
    (probe_project / "project.godot").write_text(
        (probe_project / "project.godot").read_text(encoding="utf-8")
        + "\n[gda]\n\nprobe/value=1.5\n",
        encoding="utf-8",
    )
    run = _headless_runner(probe_project)

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


# --- the command tier: live `game set` through a real daemon -------------------

LIVE_MAIN_GD = "extends Node2D\n\nvar v := 1.5\n"
LIVE_MAIN_TSCN = (
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
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(LIVE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "live_main.gd").write_text(LIVE_MAIN_GD, encoding="utf-8")

    run = _headless_runner(tmp_path)
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
    finally:
        run("daemon", "stop")
