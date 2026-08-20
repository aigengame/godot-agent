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

import re
from pathlib import Path

import typer

from gda.cli import app
from gda.daemon.diag import LOG_BEGIN, parse_errors, parse_log_records
from gda.daemon.server import DAEMON_SERVED_OPS, LOG_OPS
from gda.daemon.session import CONNECT_TIMEOUT, LAUNCH_MARKER, OP_TIMEOUT
from gda.execution import ExecutionKind
from gda.live_runner import LIVE_REQUEST_TIMEOUT

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
    relayed = _live_operations() - set(DAEMON_SERVED_OPS)
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
