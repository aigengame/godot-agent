"""The live wire's number domain: gda's model of the engine, and the guard on it (#752).

The fast tier of the #752 evidence. It checks that
:func:`gda.live_numbers.wire_flattens_to_zero` reproduces the verdict a real Godot
4.6.3 gave every corpus row, that the counts every artifact publishes are DERIVED
from that corpus rather than transcribed beside it, and that every live command —
not just ``game call`` — refuses the values the engine would flatten, on both
input paths, at any nesting depth.

The engine tier that re-derives those verdicts (and covers the result direction) is
``tests/test_e2e_live_number_transport.py``; this module never launches an engine,
so it stays in the default suite.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

import gda.live_numbers as live_numbers
from gda.cli import app
from gda.commands.game import GameCallParams
from gda.live_numbers import (
    GODOT_STRTOD_MAX_POWER,
    LIVE_RESULT_PRECISION,
    MAX_EXACT_JSON_INT,
    find_unrepresentable,
    godot_applied_decimal_exponent,
    wire_flattens_to_zero,
)

from tests.live_number_corpus import LIVE_NUMBER_CORPUS, PARTITIONS
from tests.support import panel_text, usage_error_text

# The value the engine's parser cannot construct at all, used wherever a test
# needs one representative of the refused class rather than the whole corpus.
FLATTENED = 5e-324


@pytest.mark.parametrize(
    ("label", "value", "engine_parse_zeroes"),
    [(c.label, c.value, c.engine_parse_zeroes) for c in LIVE_NUMBER_CORPUS],
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
    labels = {case.label for case in LIVE_NUMBER_CORPUS}
    assert {"DBL_MIN", "-DBL_MIN", "1e-300", "-1e-300", "1.23..e-300"} <= labels
    assert {"DBL_TRUE_MIN 5e-324", "max subnormal", "DBL_MAX", "1e300"} <= labels
    zeroed = [c.value for c in LIVE_NUMBER_CORPUS if c.engine_parse_zeroes]
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


def test_the_disclosed_residual_is_anchored_by_measured_rows():
    # The contract tells callers that a float the wire DOES carry can arrive
    # changed in its low-order bits. That sentence is only honest if the suite
    # can point at the values it describes, so the corpus carries them and the
    # e2e re-derives each gap from the engine. Named rows, not a sampled
    # percentage — a percentage would need a seed, which would turn the oracle
    # into a snapshot.
    by_label = {case.label: case.request_ulp_gap for case in LIVE_NUMBER_CORPUS}

    # Ordinary game magnitudes drift by one ULP once 16-17 significant digits
    # push the parser's integer significand past 2^53.
    assert by_label["1 ULP drift ~13.6"] == 1
    assert by_label["1 ULP drift ~1250"] == 1
    assert by_label["1 ULP drift ~9e4 (16 digits)"] == 1
    assert by_label["2 ULP drift ~3.1e-291"] == 2

    # And the MANTISSA-CAP band is worse than one ULP by orders of magnitude:
    # the engine keeps at most 18 mantissa digits, and a fixed-notation literal
    # between 1e-4 and 1e-2 spends 2-3 of those on leading zeros, so full-
    # precision values there lose their last decimal digits outright.
    assert by_label["mantissa cap ~1.2e-3"] == 31
    assert by_label["mantissa cap ~1.4e-4"] == 105
    assert by_label["1e-4"] == 0  # the same band, but only one digit to carry

    # An exact row must record 0, never None: None is reserved for the values
    # the engine flattened, where a distance would be meaningless.
    assert by_label["one"] == 0
    assert by_label["DBL_TRUE_MIN 5e-324"] is None


def test_the_published_partition_is_derived_from_the_corpus():
    # The three rows every artifact quotes. They are computed from the table
    # (tests/live_number_corpus.PARTITIONS), so a row added or removed moves them
    # and nothing can publish a hand-written count; the engine tier re-derives the
    # same three splits from a running Godot. The literals here are what #770's
    # re-derivation measured — the review's finding was that the RESULT row had
    # been published as 41/37/18, mistaking the request direction's flattening
    # count for the writer's.
    assert len(LIVE_NUMBER_CORPUS) == 96
    assert PARTITIONS["request"] == (56, 22, 18)
    assert PARTITIONS["default_stringify"] == (41, 15, 40)
    assert PARTITIONS["full_precision"] == (95, 1, 0)
    for name, partition in PARTITIONS.items():
        assert partition.total == len(LIVE_NUMBER_CORPUS), name


def test_the_authority_prose_quotes_the_derived_counts():
    # `gda.live_numbers` is the ONE prose surface allowed to state these numbers
    # (the harness comment and ADR-0041 point at it instead of restating them,
    # RULES.md's DRY clause). A guard that only recomputed the corpus would leave
    # the prose free to drift, so read the docstring and require the derived
    # strings verbatim (#770 review).
    doc = live_numbers.__doc__ or ""
    default = PARTITIONS["default_stringify"]
    full = PARTITIONS["full_precision"]
    assert (
        f"**{default.exact} exact / {default.changed} changed / "
        f"{default.zero} flattened to ``0.0``**"
    ) in doc
    assert f"exact on **{full.exact} of the {full.total}** corpus" in doc

    # The command catalog is the one OTHER surface allowed to quote them, because a
    # feature spec without the measurement is not the evidence it claims to be. Same
    # rule: derived strings, not transcribed ones.
    request = PARTITIONS["request"]
    catalog = (
        Path(__file__).resolve().parents[1] / "docs/command-catalog.md"
    ).read_text(encoding="utf-8")
    total = len(LIVE_NUMBER_CORPUS)
    assert f"preserved {full.exact} of the {total} corpus rows" in catalog
    assert (
        f"default writer preserved {default.exact} of\n  the {total}: it changed "
        f"{default.changed} and flattened {default.zero} to `0.0`"
    ) in catalog
    assert f"{request.zero} of the {total} arrive as `0.0`" in catalog
    assert (
        f"{request.exact} of the {total} crossed exactly and {request.changed} changed"
    ) in catalog


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
    assert (
        godot_applied_decimal_exponent(json.dumps(FLATTENED)) < -GODOT_STRTOD_MAX_POWER
    )


# --- The admission scan itself ------------------------------------------------


def _refusal(value: object, path: str = "x") -> str:
    """The scan's refusal for ``value``, asserting there IS one."""
    found = find_unrepresentable(value, path)
    assert found is not None, value
    return found


def test_the_scan_names_where_the_offending_value_sits():
    # The refusal has to be actionable on a nested payload: "somewhere in your
    # arguments" would leave the caller bisecting by hand.
    assert find_unrepresentable(1.0, "x") is None
    assert _refusal({"a": [1.0, {"b": FLATTENED}]}, "p").startswith(
        "p['a'][1]['b'] float value"
    )
    assert _refusal([[MAX_EXACT_JSON_INT + 2]], "args").startswith(
        "args[0][0] integer values must be within"
    )


def test_the_scan_keeps_the_three_refusal_classes_distinguishable():
    # One scan, three reasons; an agent branching on the message must be able to
    # tell "not representable at all" from "too small" from "too large".
    assert "NaN and Infinity" in _refusal(float("nan"))
    assert "cannot cross the live wire" in _refusal(FLATTENED)
    assert "integer values must be within" in _refusal(MAX_EXACT_JSON_INT + 2)
    # A bool is not an integer argument here, despite subclassing int.
    assert find_unrepresentable({"flag": True, "n": 3}, "p") is None


# --- The policy, applied at EVERY live ingress ---------------------------------
#
# The #770 review reproduced silent success on the live inputs `game call` did
# not cover: `input mouse-move 5e-324 1` returned success with `[0.0, 1.0]`, and
# `input action --strength 5e-324` with `strength: 0.0`. The refusal is now the
# live wire's rule (gda.models.LiveParams), so every ingress is covered here and
# `tests/test_live_contract_guards.py` fails a LIVE command that opts out.

ARGV_INGRESSES = [
    pytest.param(["input", "mouse-move", repr(FLATTENED), "1"], id="mouse-move-x"),
    pytest.param(["input", "mouse-move", "1", repr(FLATTENED)], id="mouse-move-y"),
    pytest.param(["input", "mouse-click", repr(FLATTENED), "1"], id="mouse-click-x"),
    pytest.param(
        ["input", "action", "ui_accept", "--strength", repr(FLATTENED)],
        id="action-strength",
    ),
    pytest.param(
        ["input", "tap", "--action", "ui_accept", "--strength", repr(FLATTENED)],
        id="tap-strength",
    ),
    pytest.param(
        [
            "screen",
            "capture",
            "--output",
            "/tmp/gda-752.png",
            "--await-node",
            "/root/Main",
            "--await-property",
            "hp",
            "--await-value",
            repr(FLATTENED),
        ],
        id="screen-capture-await-value",
    ),
]


@pytest.mark.parametrize("argv", ARGV_INGRESSES)
def test_every_live_argv_ingress_refuses_a_value_the_wire_would_flatten(argv):
    result = CliRunner().invoke(app, argv)

    # A usage error decided from the params model, before any daemon is asked:
    # the refusal must not depend on a running session, and must not report the
    # live channel's `daemon_not_running` for what is an input mistake.
    message = usage_error_text(result)
    assert "cannot cross the live wire" in message, message
    assert "daemon" not in message.lower(), message


PARAMS_JSON_INGRESSES = [
    pytest.param(["input", "mouse-move"], {"x": FLATTENED, "y": 1.0}, id="mouse-move"),
    pytest.param(
        ["input", "action"],
        {"action": "ui_accept", "strength": FLATTENED},
        id="action",
    ),
    pytest.param(
        ["input", "sequence"],
        {"events": [{"type": "mouse_move", "frame": 0, "x": FLATTENED, "y": 1.0}]},
        id="sequence-nested-event",
    ),
    pytest.param(
        ["screen", "capture"],
        {
            "output": "/tmp/gda-752.png",
            "await_node": "/root/Main",
            "await_property": "hp",
            "await_value": FLATTENED,
        },
        id="screen-capture-await-value",
    ),
    pytest.param(
        ["game", "call"],
        {"node": "/root/Main", "method": "m", "args": [{"deep": [FLATTENED]}]},
        id="game-call-nested-arg",
    ),
    pytest.param(
        ["diag", "errors"], {"limit": MAX_EXACT_JSON_INT + 2}, id="diag-limit-integer"
    ),
]


@pytest.mark.parametrize(("argv", "params"), PARAMS_JSON_INGRESSES)
def test_every_live_params_json_ingress_reports_the_structured_refusal(argv, params):
    result = CliRunner().invoke(
        app, [*argv, "--params-json", json.dumps(params), "--json"]
    )

    assert result.exit_code != 0, result.stdout
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_params", error
    assert (
        "cannot cross the live wire" in error["message"]
        or "integer values must be within" in error["message"]
    ), error


def test_the_sequence_refusal_names_the_offending_event():
    result = CliRunner().invoke(
        app,
        [
            "input",
            "sequence",
            "--params-json",
            json.dumps(
                {
                    "events": [
                        {"type": "mouse_move", "frame": 0, "x": 1.0, "y": 2.0},
                        {"type": "mouse_move", "frame": 1, "x": FLATTENED, "y": 2.0},
                    ]
                }
            ),
            "--json",
        ],
    )

    # A sequence is where a per-field check would have been most tempting and
    # least sufficient: the offender is the SECOND event's x.
    message = json.loads(result.stdout)["error"]["message"]
    assert "events[1]['x']" in message, message


# --- `game call`'s own refusal, unchanged by the move to the shared base -------


@pytest.mark.parametrize(
    ("label", "value"),
    [(c.label, c.value) for c in LIVE_NUMBER_CORPUS if c.engine_parse_zeroes],
)
def test_game_call_refuses_every_corpus_value_the_wire_would_flatten(label, value):
    with pytest.raises(ValidationError, match="cannot cross the live wire"):
        GameCallParams(node="/root/M", method="m", args=[value])


@pytest.mark.parametrize(
    ("label", "value"),
    [(c.label, c.value) for c in LIVE_NUMBER_CORPUS if not c.engine_parse_zeroes],
)
def test_game_call_accepts_every_corpus_value_the_wire_carries(label, value):
    # The other half of the guard's honesty: it must not over-refuse. Every value
    # the engine did read is still accepted, high-range and subnormal-adjacent
    # alike.
    params = GameCallParams(node="/root/M", method="m", args=[value])
    assert params.args == [value]


def test_the_flattening_refusal_reaches_nested_values():
    with pytest.raises(ValidationError, match="cannot cross the live wire"):
        GameCallParams(node="/root/M", method="m", args=[{"deep": [FLATTENED]}])


def test_the_flattening_refusal_names_the_value_and_the_consequence():
    with pytest.raises(ValidationError) as excinfo:
        GameCallParams(node="/root/M", method="m", args=[2.2250738585072014e-308])

    message = str(excinfo.value)
    assert "2.2250738585072014e-308" in message
    assert "arrive as 0.0" in message
    assert "SUCCEED on a value you never sent" in message
    # The path is still rooted at the field the caller passed, so moving the scan
    # to the shared base did not blur where the offender sits.
    assert "args[0]" in message


def test_the_three_refusal_classes_stay_distinguishable():
    with pytest.raises(ValidationError, match="NaN and Infinity"):
        GameCallParams(node="/root/M", method="m", args=[float("nan")])
    with pytest.raises(ValidationError, match="cannot cross the live wire"):
        GameCallParams(node="/root/M", method="m", args=[FLATTENED])
    with pytest.raises(ValidationError, match="integer values must be within"):
        GameCallParams(node="/root/M", method="m", args=[MAX_EXACT_JSON_INT + 2])


def test_the_game_group_still_names_the_shared_integer_bound():
    # The bound moved to the live-number authority; the group re-exports it, so a
    # caller (and the existing tests) can keep reading it where it used to live.
    from gda.commands import game

    assert game.MAX_EXACT_JSON_INT is MAX_EXACT_JSON_INT


# --- The RESULT direction's one published sentence ----------------------------


def _collapsed(text: str) -> str:
    """One line, single-spaced — a docstring's wrapping is not part of its content."""
    return " ".join(text.split())


def test_the_result_precision_guarantee_is_stated_identically_on_every_live_read():
    from gda.commands.game import game_get, game_rect
    from gda.commands.perf import perf_monitor, perf_monitors
    from gda.commands.screen import screen_capture

    # Every live surface that returns a float: the property reads, the Control
    # rect, the monitor counters and timelines, and a gated capture's predicate
    # echo. Typer renders a command's DOCSTRING as its help and cannot
    # interpolate a constant into it, so each copy is pinned against the
    # production authority (#770 review moved that authority out of this test).
    for command in (game_get, game_rect, perf_monitors, perf_monitor, screen_capture):
        assert LIVE_RESULT_PRECISION in _collapsed(command.__doc__ or ""), (
            command.__name__
        )


LIVE_RESULT_SCHEMA_COMMANDS = [
    ["game", "get"],
    ["game", "rect"],
    ["game", "call"],
    ["perf", "monitors"],
    ["perf", "monitor"],
    ["screen", "capture"],
]


@pytest.mark.parametrize("argv", LIVE_RESULT_SCHEMA_COMMANDS, ids=" ".join)
def test_the_result_precision_guarantee_reaches_the_machine_schema(argv):
    # #752's AC names the machine schema among the surfaces the policy must be
    # consistent across, and #770's review found `--schema` describing only the
    # projection SHAPE. The sentence rides the live result models' own field
    # descriptions, CONCATENATED from the authority rather than copied, so a
    # schema client can discover full precision and the negative-zero residual.
    # It is deliberately NOT on the shared headless NodeProperty description:
    # #771 leaves headless fidelity different, and that model serves both.
    rendered = CliRunner().invoke(app, [*argv, "--schema"])
    assert rendered.exit_code == 0, rendered.stdout
    document = json.loads(rendered.stdout)
    assert LIVE_RESULT_PRECISION in json.dumps(document["output"], ensure_ascii=False)
    assert LIVE_RESULT_PRECISION not in json.dumps(
        document["input"], ensure_ascii=False
    )


def test_the_headless_property_shape_makes_no_live_precision_promise():
    # The shared NodeProperty description serves `node get` / `resource get` too,
    # where #771 leaves the default writer in place. A live-only guarantee stated
    # there would be false for those reads.
    from gda.models import NodeProperty

    schema = json.dumps(NodeProperty.model_json_schema(), ensure_ascii=False)
    assert LIVE_RESULT_PRECISION not in schema
    rendered = CliRunner().invoke(app, ["node", "get", "--schema"])
    assert LIVE_RESULT_PRECISION not in json.dumps(
        json.loads(rendered.stdout)["output"], ensure_ascii=False
    )


def test_the_result_precision_guarantee_reaches_the_rendered_help_and_the_skill():
    from gda.commands.meta import read_skill_text

    # Rendered help wraps inside a Rich panel, so normalize it with the shared
    # tests/support normalizer and assert on tokens a line break cannot split.
    for argv in (
        ["game", "get", "--help"],
        ["game", "rect", "--help"],
        ["perf", "monitors", "--help"],
        ["perf", "monitor", "--help"],
        ["screen", "capture", "--help"],
    ):
        rendered = CliRunner().invoke(app, argv)
        assert rendered.exit_code == 0, rendered.stdout
        words = set(panel_text(rendered.stdout).split())
        assert "binary64" in words, argv
        assert "NEGATIVE" in words, argv

    skill = read_skill_text()
    assert "full binary64 precision" in skill
    assert "a negative zero reads back as `0.0`" in skill
