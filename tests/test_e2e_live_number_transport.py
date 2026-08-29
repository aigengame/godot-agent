"""S1 (e2e): the #752 live-number differential corpus, measured on a real engine.

Two tiers of evidence, both against the real Godot binary:

**The corpus** re-derives, from the engine itself, the verdicts
``tests/live_number_corpus.py`` records — in BOTH directions and bit-exactly, by
carrying every value as its IEEE-754 bytes rather than as a decimal literal (a
literal is exactly the lossy thing under test). It answers three questions the
issue asks and nothing else can: does Godot's parser really flatten these
literals, does gda's guard predict that correctly, and does the full-precision
writer the harness now uses really preserve every value the default writer lost.

**The live path** then proves the same thing through a running ``gda-daemon`` and
a real engine session, which is the only place the harness's own writer is
exercised: a tiny float and a 16-digit float read back through ``gda game get``
must equal the values the running game holds, and an argument the wire would
flatten must be REFUSED instead of quietly arriving as ``0.0``.
"""

import json
import math
import re
import struct
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from gda.live_numbers import wire_flattens_to_zero

from tests.live_number_corpus import LIVE_NUMBER_CORPUS
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

_PROBE_BODY = """\
func _hex(v: float) -> String:
\tvar b := PackedByteArray()
\tb.resize(8)
\tb.encode_double(0, v)
\treturn b.hex_encode()


func _from_hex(h: String) -> float:
\tvar b := PackedByteArray()
\tb.resize(8)
\tfor i in range(8):
\t\tb[i] = ("0x" + h.substr(i * 2, 2)).hex_to_int()
\treturn b.decode_double(0)


func _initialize() -> void:
\tfor row in CORPUS:
\t\tvar hex: String = row[0]
\t\tvar literal: String = row[1]
\t\tvar v := _from_hex(hex)
\t\tvar request := "PARSE_NULL"
\t\tvar parsed: Variant = JSON.parse_string("[" + literal + "]")
\t\tif parsed != null and typeof((parsed as Array)[0]) == TYPE_FLOAT:
\t\t\trequest = _hex((parsed as Array)[0])
\t\tprint("GDA752|" + hex + "|" + request + "|" + JSON.stringify(v)
\t\t\t\t+ "|" + JSON.stringify(v, "", true, true))
\tquit(0)
"""


def _probe_source() -> str:
    """The probe script, carrying the corpus as (IEEE-754 bytes, wire literal) pairs.

    The bytes are what makes this differential: the engine reconstructs each value
    from its exact bit pattern, so the only decimal literal in play is the one the
    daemon's own serializer (``json.dumps``) would write for that value — the
    literal actually under test.
    """
    rows = ",\n".join(
        '\t["{bits}", "{literal}"]'.format(
            bits=struct.pack("<d", value).hex(), literal=json.dumps(value)
        )
        for _, value, _, _, _ in LIVE_NUMBER_CORPUS
    )
    return f"extends SceneTree\n\nconst CORPUS := [\n{rows},\n]\n\n\n{_PROBE_BODY}"


def _bits(value: float) -> str:
    return struct.pack("<d", value).hex()


def _ulp_gap(sent: float, arrived: float) -> int:
    """How many representable doubles separate two values (0 = identical).

    Sign-magnitude bit patterns are mapped to a monotone integer order first, so
    the distance is meaningful across zero and does not depend on the exponent.
    """

    def ordered(value: float) -> int:
        raw = struct.unpack("<Q", struct.pack("<d", value))[0]
        return (raw ^ 0x7FFFFFFFFFFFFFFF) - (1 << 64) if raw >> 63 else raw

    return abs(ordered(sent) - ordered(arrived))


def _plain(text: str) -> str:
    """A usage message as prose: no ANSI, no Rich box rules, one line.

    The argv-path refusal is rendered inside a Rich panel, so the sentence under
    test is broken by colour codes, box borders and hard wraps that say nothing
    about the message itself.
    """
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", text)
    stripped = re.sub(r"[\u2500-\u257f]", " ", stripped)
    return " ".join(stripped.split())


def _engine_rows(project) -> dict[str, tuple[str, str, str]]:
    """Run the probe through `gda script run` and index its lines by value bits."""
    (project / "probe.gd").write_text(_probe_source(), encoding="utf-8")
    run = subprocess.run(
        [
            *GDA_CMD,
            "script",
            "run",
            "res://probe.gd",
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
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["exit_status"] == 0, result

    rows: dict[str, tuple[str, str, str]] = {}
    for line in result["stdout"].splitlines():
        if not line.startswith("GDA752|"):
            continue
        _, bits, request, default_text, full_text = line.split("|")
        rows[bits] = (request, default_text, full_text)
    assert len(rows) == len(LIVE_NUMBER_CORPUS), rows
    return rows


@pytest.mark.e2e
def test_the_live_number_corpus_still_describes_this_engine(godot_project):
    """The whole corpus, both directions, re-derived from the running engine."""
    rows = _engine_rows(godot_project)

    parse_flattened: list[str] = []
    default_lost: list[str] = []
    for (
        label,
        value,
        recorded_parse_zeroes,
        recorded_default_exact,
        recorded_ulp_gap,
    ) in LIVE_NUMBER_CORPUS:
        request, default_text, full_text = rows[_bits(value)]

        # --- REQUEST direction: what Godot's parser makes of gda's wire literal.
        assert request != "PARSE_NULL", label
        arrived = struct.unpack("<d", bytes.fromhex(request))[0]
        engine_zeroes = arrived == 0.0 and value != 0.0
        assert engine_zeroes is recorded_parse_zeroes, (
            f"{label}: the engine's verdict moved away from the recorded corpus"
        )
        # ...and gda's guard predicts that verdict without asking the engine.
        assert wire_flattens_to_zero(value) is engine_zeroes, label
        if engine_zeroes:
            parse_flattened.append(label)
            assert recorded_ulp_gap is None, label
        else:
            # How far a value that DID arrive landed from the one sent. This is
            # what turns the disclosed residual into a measurement: the contract
            # says a carried float can arrive changed in its low-order bits, and
            # these are the bits, re-derived from the engine each run.
            assert _ulp_gap(value, arrived) == recorded_ulp_gap, label

        # --- RESULT direction: the writer the harness uses is exact...
        assert _bits(float(json.loads(full_text))) == _bits(value) or (
            value == 0.0 and math.copysign(1.0, value) < 0
        ), f"{label}: full-precision stringify changed the value"

        # ...where the DEFAULT writer, which the harness used before #752, was not.
        default_exact = _bits(float(json.loads(default_text))) == _bits(value)
        assert default_exact is recorded_default_exact, label
        if not default_exact:
            default_lost.append(label)

    # The corpus must keep proving something in both directions, so a future
    # engine that fixed one of them cannot leave this test silently vacuous.
    assert len(parse_flattened) >= 10, parse_flattened
    assert len(default_lost) >= 20, default_lost


@pytest.mark.e2e
def test_negative_zero_is_the_one_disclosed_result_residual(godot_project):
    """`-0.0` reads back as `0.0` — the residual the CLI contract states."""
    rows = _engine_rows(godot_project)
    _, _, full_text = rows[_bits(-0.0)]

    # Not a gda choice: `JSON::_stringify` returns "0.0" for anything equal to
    # zero before the full_precision argument is consulted.
    assert full_text == "0.0"
    assert math.copysign(1.0, json.loads(full_text)) > 0
    # And it really is the ONLY row the writer changes.
    changed = [
        label
        for label, value, _, _, _ in LIVE_NUMBER_CORPUS
        if _bits(float(json.loads(rows[_bits(value)][2]))) != _bits(value)
    ]
    assert changed == ["-zero"], changed


# --- The live path: the same guarantee through a real daemon + engine session ---

NUMBERS_MAIN_GD = (
    "extends Node2D\n\n"
    'const GDA_CALLABLE := ["echo_float"]\n\n'
    # Written as literals the engine's OWN parser reads exactly (the corpus
    # proves both), so the running game really holds these values.
    "var tiny := 1e-300\n"
    "var precise := 3.141592653589793\n\n"
    "func echo_float(v: float) -> float:\n"
    "\treturn v\n"
)

NUMBERS_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://numbers_main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)


def _live_runner(project):
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
            timeout=120,
        )

    return run


@pytest.mark.e2e
def test_live_reads_carry_small_and_many_digit_floats_exactly(
    tmp_path, daemon_runtime_dir
):
    """`game get` reports the value the running game holds, bit for bit."""
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(NUMBERS_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "numbers_main.gd").write_text(NUMBERS_MAIN_GD, encoding="utf-8")

    run = _live_runner(tmp_path)
    try:
        assert run("daemon", "start").returncode == 0

        # 1e-300: the default writer flattened every value below ~1e-32 to 0.0,
        # so this read used to report a zero the game never held.
        tiny = run("game", "get", "/root/Main", "--property", "tiny")
        assert tiny.returncode == 0, tiny.stdout + tiny.stderr
        assert json.loads(tiny.stdout)["properties"][0]["value"] == 1e-300

        # 3.141592653589793: the default writer kept ~15 significant digits, so
        # this read used to report 3.14159265358979 — a different double.
        precise = run("game", "get", "/root/Main", "--property", "precise")
        assert precise.returncode == 0, precise.stdout + precise.stderr
        value = json.loads(precise.stdout)["properties"][0]["value"]
        assert _bits(value) == _bits(3.141592653589793)

        # The same writer serves a call's RETURN value.
        echoed = run(
            "game",
            "call",
            "/root/Main",
            "--method",
            "echo_float",
            "--args",
            "[1e-300]",
        )
        assert echoed.returncode == 0, echoed.stdout + echoed.stderr
        assert json.loads(echoed.stdout)["value"] == 1e-300
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_live_call_refuses_an_argument_the_wire_would_flatten(
    tmp_path, daemon_runtime_dir
):
    """A value the parser cannot carry is refused, not silently delivered as 0.0."""
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(NUMBERS_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "numbers_main.gd").write_text(NUMBERS_MAIN_GD, encoding="utf-8")

    run = _live_runner(tmp_path)
    try:
        assert run("daemon", "start").returncode == 0

        before = json.loads(run("daemon", "status").stdout)["session_id"]

        # The argv path: a usage refusal decided before the wire, so the call is
        # never made and the session is never disturbed.
        for literal in (
            "5e-324",
            "2.2250738585072014e-308",
            "-1.2345678901234567e-300",
        ):
            refused = run(
                "game",
                "call",
                "/root/Main",
                "--method",
                "echo_float",
                "--args",
                f"[{literal}]",
            )
            assert refused.returncode != 0, refused.stdout + refused.stderr
            assert "cannot cross the live wire" in _plain(refused.stderr), literal
            assert "live_timeout" not in refused.stdout

        # The --params-json path reaches the same validator and reports the
        # structured envelope an agent branches on — nested, where a per-argument
        # check that only looked at the top level would have let it through.
        nested = run(
            "game",
            "call",
            "--params-json",
            json.dumps(
                {
                    "node": "/root/Main",
                    "method": "echo_float",
                    "args": [{"deep": [5e-324]}],
                }
            ),
        )
        assert nested.returncode != 0, nested.stdout
        error = json.loads(nested.stdout)["error"]
        assert error["code"] == "invalid_params"
        assert "cannot cross the live wire" in error["message"]
        assert json.loads(run("daemon", "status").stdout)["session_id"] == before

        # The neighbouring value the parser CAN carry is not caught by the guard,
        # and comes back unchanged — the refusal is narrow, not a magnitude cutoff.
        allowed = run(
            "game", "call", "/root/Main", "--method", "echo_float", "--args", "[1e-308]"
        )
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr
        assert json.loads(allowed.stdout)["value"] == 1e-308
    finally:
        run("daemon", "stop")
