"""Unit-level drift guards for the live stack's cross-language / cross-process contracts.

The live capability spans three artifacts that must agree byte-for-byte but are
written in two languages and executed in three processes: the CLI's command
descriptors (Python), the GDScript harness that serves the relayed ops, and the
daemon that brokers between them. Until now nothing checked that agreement below
the end-to-end tier — a one-sided rename (an ``OP_*`` const, the launch marker, a
wire key) passed every PR gate, because PR CI runs no Godot e2e, and would only
surface hours later in the nightly e2e tier as an obscure ``unknown_operation`` /
``contract_violation`` / silently inert session.

These tests close that window at unit speed. They follow the mirror-test idiom
already established in ``tests/test_error_registry.py`` (regex-extract the
GDScript const, compare against the Python constant), and they read the command
descriptors off the LIVE Typer tree — the same authority ``gda.surface`` walks —
so they stay correct wherever the descriptors and result models physically live.
"""

import json
import re
from pathlib import Path
from typing import Any, ForwardRef, NamedTuple, get_args

import pytest
import typer
from pydantic import BaseModel
from typer.testing import CliRunner

from gda.cli import app
from gda.daemon.diag import LOG_BEGIN, parse_errors, parse_log_records
from gda.daemon.server import DAEMON_SERVED_OPS, LOG_OPS
from gda.daemon.session import CONNECT_TIMEOUT, LAUNCH_MARKER, OP_TIMEOUT
from gda.execution import ExecutionKind
from gda.live_numbers import LIVE_RESULT_PRECISION
from gda.live_runner import LIVE_REQUEST_TIMEOUT

from tests.support import panel_text

ROOT = Path(__file__).resolve().parents[1]
GDA_HARNESS_GD = ROOT / "src" / "gda" / "harness" / "gda_harness.gd"


def _leaf_commands(command, path):
    """Yield ``(name, command_obj)`` for every leaf of the Typer tree (cf. gda.surface).

    A group is identified by its ``commands`` mapping (the same Click duck-type the
    surface walker uses); a leaf has none.
    """
    subcommands = getattr(command, "commands", None)
    if subcommands is not None:
        for name, sub in subcommands.items():
            yield from _leaf_commands(sub, [*path, name])
        return
    yield " ".join(path), command


def test_gda_callable_constant_name_mirrors_the_harness():
    """The declaration constant's NAME is one contract in two languages (#749 review).

    The harness owns the runtime authority (``GDA_CALLABLE_CONST``); the command
    group quotes it in the agent-facing schema, help and prose. A one-sided
    rename would leave the published contract naming a constant the harness
    never reads — invisible to every gate until a live call, since PR CI runs no
    Godot e2e. Same mirror idiom as the op names and live error codes.
    """
    from gda.commands.game import GDA_CALLABLE_CONST

    source = GDA_HARNESS_GD.read_text(encoding="utf-8")
    match = re.search(r'const GDA_CALLABLE_CONST := "([A-Z_]+)"', source)
    assert match is not None, "the harness must declare GDA_CALLABLE_CONST"
    assert match.group(1) == GDA_CALLABLE_CONST
    # The published input contract quotes the same name, so an agent reading
    # only the schema learns where to declare.
    import json

    from typer.testing import CliRunner

    from gda.cli import app

    runner = CliRunner()
    schema = runner.invoke(app, ["game", "call", "--schema"]).stdout
    help_text = runner.invoke(app, ["game", "call", "--help"]).stdout
    doc = json.loads(schema)
    assert GDA_CALLABLE_CONST in json.dumps(doc["input"])
    # EXACT rendered consistency (#749 re-review): docstrings cannot interpolate
    # the constant, so a coordinated rename could leave published text naming the
    # old one while the two constants still matched. Every declaration-constant
    # token the public schema and help render must BE the constant — a stale name
    # shows up here as a different token.
    for rendered, label in ((schema, "schema"), (help_text, "help")):
        # Normalized, because Rich wraps help lines mid-sentence.
        flat = " ".join(rendered.split())
        named = re.findall(r"`?\b(GDA_[A-Z_]+)\b`? script constant", flat)
        assert named, f"{label} must name the declaration constant"
        assert set(named) == {GDA_CALLABLE_CONST}, (label, set(named))


def test_game_call_conversion_table_uses_only_live_json_source_types():
    """The preflight table must start from types the Godot wire can produce.

    ``JSON.parse_string`` materializes every JSON number as ``TYPE_FLOAT``. A
    ``TYPE_INT`` source row therefore advertises an engine conversion no live
    argument can exercise, and a direct-call oracle reached through the same wire
    cannot expose that vacuity (#749 third review). The real-engine e2e separately
    pins the observed numeric type; this unit guard pins the table's source set.
    """
    source = GDA_HARNESS_GD.read_text(encoding="utf-8")
    match = re.search(
        r"const JSON_ARGUMENT_CONVERSIONS := \{(?P<body>.*?)\n\}", source, re.DOTALL
    )
    assert match is not None, "the harness must declare JSON_ARGUMENT_CONVERSIONS"
    sources = set(
        re.findall(r"^\s*(TYPE_[A-Z0-9_]+):", match.group("body"), re.MULTILINE)
    )
    assert sources == {
        "TYPE_NIL",
        "TYPE_BOOL",
        "TYPE_FLOAT",
        "TYPE_STRING",
        "TYPE_ARRAY",
        "TYPE_DICTIONARY",
    }


def _descriptors():
    """The backing ``HeadlessCommand`` of every dispatchable leaf (ADR-0023).

    Read off the live command tree rather than imported from a module, so these
    guards do not depend on where the descriptors are defined.
    """
    root = typer.main.get_command(app)
    for _, command in _leaf_commands(root, []):
        descriptor = getattr(command, "gda_command", None)
        if descriptor is not None:
            yield descriptor


def _descriptor_for(operation: str):
    """The single descriptor whose ``operation`` is ``operation``."""
    matches = [d for d in _descriptors() if d.operation == operation]
    assert len(matches) == 1, (
        f"expected exactly one descriptor for operation {operation!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _live_operations() -> set[str]:
    return {d.operation for d in _descriptors() if d.kind is ExecutionKind.LIVE}


def _live_leaves():
    """Every LIVE leaf as ``(name, descriptor)``, read off the live Typer tree."""
    root = typer.main.get_command(app)
    for name, command in _leaf_commands(root, []):
        descriptor = getattr(command, "gda_command", None)
        if descriptor is not None and descriptor.kind is ExecutionKind.LIVE:
            yield name, descriptor


def test_relayed_live_params_models_carry_the_wire_number_policy():
    """A relayed request's numbers are admitted by the wire leg's rule (#752, #770).

    Godot's JSON parser reads a small-magnitude float as ``0.0`` and a large
    integer as a different integer, so a live op can SUCCEED on a value the
    caller never sent. The rule belongs to the daemon-to-harness LEG, and this
    walk is what keeps it bound there rather than to a proxy — the two proxies
    already tried both produced a defect:

    - ``game call``'s own validator left ``input mouse-move``, ``input action
      --strength`` and a nested sequence event open (#770 round 2);
    - ``ExecutionKind.LIVE`` over-refused the ops the daemon answers ITSELF, so
      ``daemon wait-ready --timeout 5e-324`` was rejected with a Godot-parser
      explanation for a number Python consumes (#770 round 3).

    So it fails BOTH ways: a relayed descriptor whose params model does not
    inherit the base, and a daemon-served one that does.
    """
    from gda.models import RelayedLiveParams

    relayed, served = [], []
    for name, descriptor in _live_leaves():
        target = served if descriptor.operation in DAEMON_SERVED_OPS else relayed
        target.append((name, descriptor.input_model))

    # Guard the walk against vacuity: an extraction that stopped matching would
    # otherwise pass by checking nothing. Both partitions must be populated, or
    # the test has stopped distinguishing the two legs it exists to distinguish.
    assert len(relayed) >= 12, relayed
    assert len(served) == len(DAEMON_SERVED_OPS), served

    missing = [
        name for name, model in relayed if not issubclass(model, RelayedLiveParams)
    ]
    assert missing == [], (
        f"these RELAYED live commands' params models do not inherit "
        f"gda.models.RelayedLiveParams, so their numbers reach Godot's JSON "
        f"parser unchecked (#752): {missing}"
    )
    over = [name for name, model in served if issubclass(model, RelayedLiveParams)]
    assert over == [], (
        f"these DAEMON-SERVED commands' params models inherit "
        f"gda.models.RelayedLiveParams, so they refuse values on a leg those "
        f"values never cross (#770): {over}"
    )


# --- The RESULT direction's published contract, derived from the result models --
#
# `LIVE_RESULT_PRECISION` is one production sentence (gda.live_numbers). What the
# #770 review found twice is that its COVERAGE was hand-picked: it reached six
# commands while `game set`'s readback, the input commands' positions and
# strengths, and `logger tail`'s structured fields returned floats with no
# published contract at all. So the required set is DERIVED from the result models
# here, not listed: any field a live reply can return a float in must publish it.


class LiveFloatField(NamedTuple):
    """One live-result field that can carry a float, and whether it is disclosed."""

    path: str
    disclosed: bool


def _is_model(annotation: object) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _carries_float(annotation: object) -> bool:
    """Whether a resolved annotation admits a JSON float.

    ``Any`` counts: the projected-value fields are typed ``Any`` and a projection
    routinely carries floats. ``int`` does not — Godot stringifies an integer
    through ``itos``, which is exact, and the request-side integer bound is the
    admission scan's business, not this contract's.
    """
    if annotation is float or annotation is Any:
        return True
    if _is_model(annotation):
        return False
    return any(_carries_float(argument) for argument in get_args(annotation))


def _nested_models(annotation: object) -> "list[type[BaseModel]]":
    if _is_model(annotation):
        return [annotation]  # type: ignore[list-item]
    found: "list[type[BaseModel]]" = []
    for argument in get_args(annotation):
        found.extend(_nested_models(argument))
    return found


def live_float_fields(
    model: "type[BaseModel]",
    prefix: str = "",
    *,
    disclosed: bool = False,
    seen: "tuple[type[BaseModel], ...]" = (),
) -> "list[LiveFloatField]":
    """Every field under ``model`` that can carry a float, with its disclosure state.

    A field's own description publishes the contract for its WHOLE subtree, which
    is what keeps the promise off the shared headless models: ``GameGetResult``
    states it on ``properties``, so the ``NodeProperty.value`` beneath it is
    covered without ``NodeProperty`` — which ``node get`` / ``resource get`` also
    use, and where #771 leaves headless fidelity different — making a live-only
    claim.

    ``model_rebuild()`` first, and a hard failure on anything still unresolved: a
    model whose annotations are still ``ForwardRef`` (several are, until first
    use) would otherwise make this walk quietly skip exactly the nested reports
    it exists to check.
    """
    if model in seen:
        return []
    model.model_rebuild()
    found: "list[LiveFloatField]" = []
    for name, field in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else f"{model.__name__}.{name}"
        annotation = field.annotation
        assert not isinstance(annotation, (str, ForwardRef)), (
            f"{path} is still an unresolved annotation ({annotation!r}); this walk "
            "would skip its fields instead of checking them"
        )
        published = disclosed or LIVE_RESULT_PRECISION in (field.description or "")
        if _carries_float(annotation):
            found.append(LiveFloatField(path, published))
        for nested in _nested_models(annotation):
            found.extend(
                live_float_fields(
                    nested, path, disclosed=published, seen=(*seen, model)
                )
            )
    return found


def _float_bearing_live_commands() -> "list[tuple[str, Any]]":
    """Every LIVE leaf whose result model can return a float, as ``(name, descriptor)``."""
    return [
        (name, descriptor)
        for name, descriptor in _live_leaves()
        if live_float_fields(descriptor.output_model)
    ]


def test_every_float_a_live_reply_returns_publishes_its_precision_contract():
    """The result contract's coverage is derived from the models, not hand-picked.

    #752 requires the selected policy to be consistent across the machine schema
    among other surfaces. This walks every LIVE result model and fails on a
    float-bearing field no description publishes the contract for — so a new live
    reply cannot ship a float that says nothing about its fidelity, and a nested
    report (a capture predicate's echo, a log record's fields) is checked as
    thoroughly as a top-level one.
    """
    undisclosed = {
        name: [
            f.path
            for f in live_float_fields(descriptor.output_model)
            if not f.disclosed
        ]
        for name, descriptor in _live_leaves()
    }
    offenders = {name: paths for name, paths in undisclosed.items() if paths}
    assert offenders == {}, (
        "these live result fields can return a float but publish no precision "
        f"contract (gda.live_numbers.LIVE_RESULT_PRECISION, #752): {offenders}"
    )

    # Vacuity floor: a walk that stopped resolving nested models would report an
    # empty offender set while checking almost nothing.
    covered = _float_bearing_live_commands()
    assert len(covered) >= 12, [name for name, _ in covered]
    # And the two shapes the walk exists to reach: a value nested two models deep,
    # and one behind a `ForwardRef` that is unresolved until the model is rebuilt.
    paths = {
        f.path
        for _, descriptor in covered
        for f in live_float_fields(descriptor.output_model)
    }
    assert "LoggerTailResult.records.fields" in paths, sorted(paths)
    assert "ScreenCaptureResult.predicate.observed" in paths, sorted(paths)


@pytest.mark.parametrize("name", [name for name, _ in _float_bearing_live_commands()])
def test_the_precision_contract_reaches_the_machine_schema(name):
    # #752's AC names the machine schema among the surfaces the policy must be
    # consistent across, and #770's review found `--schema` describing only the
    # projection SHAPE. The sentence rides the live result models' own field
    # descriptions, CONCATENATED from the production authority rather than copied,
    # so a schema client — and gda-mcp, whose wire schemas derive from the same
    # models (ADR-0004) — can discover full precision and the negative-zero
    # residual. It is deliberately NOT on the request side: that direction is a
    # refusal, stated where the refusal is made.
    rendered = CliRunner().invoke(app, [*name.split(), "--schema"])
    assert rendered.exit_code == 0, rendered.stdout
    document = json.loads(rendered.stdout)
    assert LIVE_RESULT_PRECISION in json.dumps(document["output"], ensure_ascii=False)
    assert LIVE_RESULT_PRECISION not in json.dumps(
        document["input"], ensure_ascii=False
    )


@pytest.mark.parametrize("name", [name for name, _ in _float_bearing_live_commands()])
def test_the_precision_contract_reaches_the_rendered_help(name):
    # Typer renders a command's DOCSTRING as its help and cannot interpolate a
    # constant into it, so each copy is pinned against the production authority —
    # and the SET of commands that must carry one is derived from the result
    # models above, which is what the previous round got wrong by listing it.
    rendered = CliRunner().invoke(app, [*name.split(), "--help"])
    assert rendered.exit_code == 0, rendered.stdout
    assert LIVE_RESULT_PRECISION in " ".join(panel_text(rendered.stdout).split()), name


def test_the_headless_property_shape_makes_no_live_precision_promise():
    # The shared NodeProperty description serves `node get` / `resource get` too,
    # where #771 leaves the default writer in place. A live-only guarantee stated
    # there would be false for those reads — so the live commands publish it on
    # their OWN fields, and the subtree rule above is what lets them.
    from gda.models import NodeProperty

    schema = json.dumps(NodeProperty.model_json_schema(), ensure_ascii=False)
    assert LIVE_RESULT_PRECISION not in schema
    rendered = CliRunner().invoke(app, ["node", "get", "--schema"])
    assert LIVE_RESULT_PRECISION not in json.dumps(
        json.loads(rendered.stdout)["output"], ensure_ascii=False
    )


# The harness op table: one ``const OP_<NAME> := "<wire op name>"`` per relayed live
# op (gda_harness.gd, "The live operations this harness serves"). Anchored to line
# start and scoped to the ``OP_`` prefix so the neighbouring const families
# (LIVE_ERROR_*, the markers, MAX_WINDOW_FRAMES) are not swept in.
HARNESS_OP_CONST = re.compile(r'^const OP_[A-Z0-9_]+ := "([^"]*)"$', re.MULTILINE)

# A floor on the extraction, so a regex that silently stops matching (a reformat, a
# renamed const family) FAILS loudly instead of comparing two conveniently-empty
# sets. Deliberately well below the real count — this guards vacuity, not the count.
MIN_HARNESS_OPS = 8


def _harness_operations() -> set[str]:
    harness = GDA_HARNESS_GD.read_text(encoding="utf-8")
    ops = set(HARNESS_OP_CONST.findall(harness))
    assert len(ops) >= MIN_HARNESS_OPS, (
        f"extracted only {len(ops)} OP_* consts from {GDA_HARNESS_GD.name} "
        f"({sorted(ops)}); the harness op table declares far more, so the "
        "extraction regex no longer matches the file — fix HARNESS_OP_CONST "
        "rather than letting this guard pass vacuously"
    )
    return ops


def test_log_ops_are_part_of_the_live_command_surface():
    # The two daemon-SERVED ops (`gda diag errors` / `gda logger tail`, #224/#281):
    # they reach the daemon like any live op, so each must be a LIVE descriptor —
    # but the daemon answers them from the Session log instead of relaying them.
    live_ops = _live_operations()
    assert live_ops, "the Typer tree walk found no LIVE commands"
    missing = set(LOG_OPS) - live_ops
    assert not missing, (
        f"daemon-served log ops with no LIVE command descriptor: {sorted(missing)}. "
        "Either register the command with kind=ExecutionKind.LIVE, or drop the op "
        "from gda.daemon.server.LOG_OPS."
    )


def test_relayed_live_ops_mirror_the_harness_op_table():
    # The cross-language op-name contract: every LIVE op the daemon RELAYS (i.e. the
    # LIVE surface minus the DAEMON_SERVED_OPS the daemon answers itself — the log
    # reads and the wait-ready launch, #657) must be an op the GDScript harness
    # declares, and vice versa. A one-sided rename here is invisible to the
    # unit suite otherwise: the CLI would ask for an op the harness never answers.
    from gda.commands.perf import PERF_SAMPLE_OP

    # `perf monitors`' recipe dispatches a SECOND harness op beside its
    # descriptor operation (#662: the snapshot op is the descriptor's, the
    # window op is recipe-reached). Counted from the source-side constant, so
    # the mirror still has one authority per name.
    recipe_relayed = {PERF_SAMPLE_OP}
    relayed = (_live_operations() | recipe_relayed) - set(DAEMON_SERVED_OPS)
    harness_ops = _harness_operations()

    unserved = relayed - harness_ops
    assert not unserved, (
        f"LIVE commands whose op the harness does not serve: {sorted(unserved)}. "
        f'Add a matching `const OP_… := "<op>"` to {GDA_HARNESS_GD.name} (and its '
        "dispatch branch), or correct the command descriptor's operation name."
    )
    unreachable = harness_ops - relayed
    assert not unreachable, (
        f"harness ops no CLI command can reach: {sorted(unreachable)}. Register a "
        "LIVE command descriptor with that operation name, or remove the const from "
        f"{GDA_HARNESS_GD.name}. (Daemon-SERVED ops belong in "
        "gda.daemon.server.DAEMON_SERVED_OPS, not in the harness op table.)"
    )


HARNESS_LAUNCH_MARKER = re.compile(r'^const LAUNCH_MARKER := "(.*)"$', re.MULTILINE)


def test_launch_marker_mirrors_the_harness_const():
    # The cross-process handshake token (ADR-0018): the daemon appends it to the
    # engine's user args, and the harness looks for exactly it to decide whether
    # this run is daemon-launched. A mismatch is silent and total — the harness
    # takes its inert early-return branch, so EVERY Engine session comes up with no
    # IPC connection and every live op fails to reach a harness that is right there.
    harness = GDA_HARNESS_GD.read_text(encoding="utf-8")
    match = HARNESS_LAUNCH_MARKER.search(harness)
    assert match is not None, "LAUNCH_MARKER const missing from gda_harness.gd"
    assert match.group(1) == LAUNCH_MARKER


# A representative Session log covering the three shapes `parse_log_records` /
# `parse_errors` classify — an opt-in `<<<GDA:LOG>>>` record WITH a `fields` payload
# (#282), runtime engine errors carrying `at:` lines AND a backtrace (so
# `callstack` / `source` are populated, #283), and plain info lines — and, per
# ADR-0026's closed enums, EVERY valid level (debug/info/warning/error) and origin
# (engine/script/shader/gda_log), so a consumer model that rejects any member
# fails this guard rather than the nightly e2e tier.
SESSION_LOG = (
    "Godot Engine v4.6.stable.official - https://godotengine.org\n"
    + LOG_BEGIN
    + '{"level": "warning", "message": "low health", '
    + '"fields": {"hp": 3, "actor": "panda", "airborne": true}}\n'
    + LOG_BEGIN
    + '{"level": "debug", "message": "tick"}\n'
    + "plain output line\n"
    "SCRIPT ERROR: Invalid call. Nonexistent function 'do_thing' in base 'Nil'.\n"
    "   at: b (res://main.gd:9)\n"
    "   GDScript backtrace (most recent call first):\n"
    "       [0] b (res://main.gd:9)\n"
    "       [1] a (res://main.gd:6)\n"
    "       [2] _ready (res://main.gd:3)\n"
    "SHADER ERROR: shader compilation failed\n"
    "   at: compile (res://wave.gdshader:3)\n"
    "WARNING: a warning happened\n"
    "   at: _process (res://main.gd:20)\n"
)


def test_logger_tail_wire_records_validate_against_its_result_model():
    # The cross-process wire contract: the daemon builds RAW dicts
    # (`parse_log_records`) and the CLI validates them with the command's result
    # model. Nothing bound the two at unit level, so a field rename/retype on either
    # side surfaced only in e2e, as a `contract_violation` on a real session.
    records = parse_log_records(SESSION_LOG)
    model = _descriptor_for("logger-tail").output_model
    result = model.model_validate({"records": records})

    # Not merely "it validated": the interesting payloads must survive the round trip.
    dumped = result.model_dump(mode="json")
    assert len(dumped["records"]) == len(records)

    gda_log = next(
        r
        for r in dumped["records"]
        if r["origin"] == "gda_log" and r["level"] == "warning"
    )
    assert gda_log["fields"] == {"hp": 3, "actor": "panda", "airborne": True}

    debug_log = next(
        r
        for r in dumped["records"]
        if r["origin"] == "gda_log" and r["level"] == "debug"
    )
    assert debug_log["message"] == "tick"

    script_error = next(r for r in dumped["records"] if r["origin"] == "script")
    assert script_error["level"] == "error"
    assert script_error["source"] == {
        "function": "b",
        "file": "res://main.gd",
        "line": 9,
    }

    shader_error = next(r for r in dumped["records"] if r["origin"] == "shader")
    assert shader_error["level"] == "error"

    # Every valid member of ADR-0026's closed enums crossed the wire above, so a
    # consumer model that rejects any of them fails the validate call, and a
    # fixture regression that drops a member fails these set equalities.
    assert {r["origin"] for r in dumped["records"]} == {
        None,
        "engine",
        "script",
        "shader",
        "gda_log",
    }
    assert {r["level"] for r in dumped["records"]} == {
        "debug",
        "info",
        "warning",
        "error",
    }


def test_diag_errors_wire_entries_validate_against_its_result_model():
    # The same wire-shape binding for `gda diag errors` (#224/#283): the daemon
    # replies `{"errors": parse_errors(...)}`, the CLI validates it with the
    # command's result model.
    errors = parse_errors(SESSION_LOG)
    model = _descriptor_for("diag-errors").output_model
    result = model.model_validate({"errors": errors})

    dumped = result.model_dump(mode="json")
    assert len(dumped["errors"]) == len(errors)

    script_error = next(e for e in dumped["errors"] if e["level"] == "script_error")
    assert script_error["function"] == "b"
    assert script_error["file"] == "res://main.gd"
    assert script_error["line"] == 9

    # The shader sub-kind survives the round trip too (ADR-0026's fourth origin
    # maps from this diag level).
    shader = next(e for e in dumped["errors"] if e["level"] == "shader_error")
    assert shader["file"] == "res://wave.gdshader"
    assert shader["line"] == 3
    # The backtrace frames survive as typed frames, ordered most-recent-first.
    assert script_error["callstack"] == [
        {"function": "b", "file": "res://main.gd", "line": 9},
        {"function": "a", "file": "res://main.gd", "line": 6},
        {"function": "_ready", "file": "res://main.gd", "line": 3},
    ]

    warning = next(e for e in dumped["errors"] if e["level"] == "warning")
    assert warning["message"] == "a warning happened"
    assert warning["callstack"] == []


def test_live_timeouts_are_ordered_so_the_daemon_times_out_first():
    # The three timeouts sit on one call chain: the CLI waits LIVE_REQUEST_TIMEOUT on
    # its daemon socket; the daemon waits CONNECT_TIMEOUT for a harness to attach and
    # OP_TIMEOUT for the op to answer. The daemon must always give up FIRST, so a
    # stuck harness surfaces as its typed `live_timeout` (ADR-0021) rather than as
    # the client's bare socket timeout — the latter loses the diagnosis and leaves
    # the daemon still working on an op nobody is waiting for.
    assert OP_TIMEOUT < LIVE_REQUEST_TIMEOUT, (
        f"OP_TIMEOUT ({OP_TIMEOUT}s) must stay below LIVE_REQUEST_TIMEOUT "
        f"({LIVE_REQUEST_TIMEOUT}s) so a stuck op returns the daemon's typed "
        "live_timeout instead of the client's socket timeout"
    )
    # The worst case is the FIRST op of a daemon lifetime: it also pays the lazy
    # session launch, so the client must outwait connect + op together.
    assert CONNECT_TIMEOUT + OP_TIMEOUT < LIVE_REQUEST_TIMEOUT, (
        f"CONNECT_TIMEOUT + OP_TIMEOUT ({CONNECT_TIMEOUT}s + {OP_TIMEOUT}s) must "
        f"stay below LIVE_REQUEST_TIMEOUT ({LIVE_REQUEST_TIMEOUT}s): a first live op "
        "also launches the Engine session, so a client that gives up earlier turns "
        "a normally-slow cold start into an untyped client-side timeout"
    )
