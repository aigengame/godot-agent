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
import math
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
from gda.live_numbers import LIVE_DERIVED_PRECISION, LIVE_ENGINE_PRECISION
from gda.live_runner import LIVE_REQUEST_TIMEOUT
from gda.runner import RunResult

from tests.support import (
    PNG_1X1_B64,
    inject_live_runner,
    panel_text,
    screen_capture_reply,
    sentinel,
)

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


# --- The RESULT direction's published contract, bound to each value's WRITER ---
#
# The live result path has TWO writers, and a float's fidelity is a property of
# WHICH one produced it (gda.live_numbers): the engine's full-precision JSON
# writer, or gda's own Python serializer over a number gda computed or echoed
# CLI-side. Round 3's walk asked only whether a field said SOMETHING, and #770's
# round-4 review found the consequence — `perf monitors`' statistics and budget
# bounds inheriting the ENGINE's sentence, so a real daemon returned
# `{"value": 1.0, "min": -0.0, "max": -0.0}` under a published claim that a
# negative zero reads back as 0.0.
#
# So the required sentence is chosen by provenance, and provenance is
# ESTABLISHED, not declared:
#
#   * A live command with no `recipe` is fulfilled by
#     `classify_live(raw, request, cmd.output_model)` (gda.dispatch's own
#     branch): the CLI constructs no result, so every float in it was parsed out
#     of the JSON the harness wrote. That branch is exercised on a real command
#     by `test_the_classify_path_hands_back_the_engines_own_floats`.
#   * A live command WITH a recipe assembles its result CLI-side, where the two
#     writers mix. Its provenance is MEASURED: a probe drives the descriptor's
#     own recipe with a reply whose floats are sentinels, and reads which fields
#     the sentinels reach. A recipe-bearing float-bearing live command with no
#     probe FAILS below rather than being assumed engine-written.

ENGINE_WRITTEN = "engine"
GDA_DERIVED = "gda"

# The one sentence each writer publishes (gda.live_numbers is the authority).
SENTENCE_FOR = {
    ENGINE_WRITTEN: LIVE_ENGINE_PRECISION,
    GDA_DERIVED: LIVE_DERIVED_PRECISION,
}


class LiveFloatField(NamedTuple):
    """One live-result field that can carry a float, and the sentences covering it."""

    path: str
    covering: "frozenset[str]"


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
    covering: "frozenset[str]" = frozenset(),
    seen: "tuple[type[BaseModel], ...]" = (),
) -> "list[LiveFloatField]":
    """Every field under ``model`` that can carry a float, and what covers it.

    A description covers its own field AND its whole subtree, which is what keeps
    the promise off the shared headless models: ``GameGetResult`` states it on
    ``properties``, so the ``NodeProperty.value`` beneath it is covered without
    ``NodeProperty`` — which ``node get`` / ``resource get`` also use, and which
    must not inherit a sentence about the live WIRE (#771) — making a live-only
    claim. Coverage
    is collected as a SET rather than a boolean because the caller checks it
    against the field's measured writer: a parent that blankets a mixed subtree
    with one writer's sentence is then a failure, not a pass.

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
        description = field.description or ""
        here = covering | {
            sentence for sentence in SENTENCE_FOR.values() if sentence in description
        }
        if _carries_float(annotation):
            found.append(LiveFloatField(path, frozenset(here)))
        for nested in _nested_models(annotation):
            found.extend(
                live_float_fields(nested, path, covering=here, seen=(*seen, model))
            )
    return found


def _float_bearing_live_commands() -> "list[tuple[str, Any]]":
    """Every LIVE leaf whose result model can return a float, as ``(name, descriptor)``."""
    return [
        (name, descriptor)
        for name, descriptor in _live_leaves()
        if live_float_fields(descriptor.output_model)
    ]


# --- Measuring provenance on a result-assembling recipe -----------------------


def _scalar_floats(value: object) -> "list[float]":
    """Every float scalar inside ``value``, through dicts and sequences."""
    if isinstance(value, bool):
        return []
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [f for item in value.values() for f in _scalar_floats(item)]
    if isinstance(value, (list, tuple)):
        return [f for item in value for f in _scalar_floats(item)]
    return []


def _model_instances(value: object) -> "list[BaseModel]":
    """Every nested model instance inside ``value``, through dicts and sequences."""
    if isinstance(value, BaseModel):
        return [value]
    if isinstance(value, dict):
        return [m for item in value.values() for m in _model_instances(item)]
    if isinstance(value, (list, tuple)):
        return [m for item in value for m in _model_instances(item)]
    return []


def _floats_by_field(instance: BaseModel, prefix: str = "") -> "dict[str, list[float]]":
    """The floats a produced result actually carries, keyed by the walk's paths.

    The instance-side twin of :func:`live_float_fields`: same path scheme, so a
    measured value can be matched to the field whose description must describe it.
    """
    model = type(instance)
    found: "dict[str, list[float]]" = {}
    for name, field in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else f"{model.__name__}.{name}"
        value = getattr(instance, name)
        if _carries_float(field.annotation):
            found.setdefault(path, []).extend(_scalar_floats(value))
        for nested in _model_instances(value):
            for nested_path, floats in _floats_by_field(nested, path).items():
                found.setdefault(nested_path, []).extend(floats)
    return found


def _measured_provenance(runs) -> "dict[str, str]":
    """Classify each field a probe exercised by whether its floats came from the reply.

    A field holding only sentinels is one the recipe passed through from the
    engine's JSON; anything else is a number gda made. ``GDA_DERIVED`` wins across
    runs — a field that can carry gda's own number is gda's, and must say so even
    in the modes where it happens to echo an engine value.
    """
    provenance: "dict[str, str]" = {}
    for result, sentinels in runs:
        for path, floats in _floats_by_field(result).items():
            if not floats:
                continue  # not exercised by this run
            writer = (
                ENGINE_WRITTEN
                if all(value in sentinels for value in floats)
                else GDA_DERIVED
            )
            if provenance.get(path) != GDA_DERIVED:
                provenance[path] = writer
    return provenance


def _perf_monitors_probe(monkeypatch, tmp_path):
    """Drive `perf monitors`' recipe in BOTH modes with sentinel-bearing replies."""
    from gda.commands.perf import (
        PERF_MONITORS_COMMAND,
        PerfMonitorsParams,
        PerfMonitorsResult,
    )

    assert PERF_MONITORS_COMMAND.recipe is not None
    runs = []

    snapshot_value = 101.25
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    "timestamp": 12345,
                    "monitors": {
                        "fps": {"name": "fps", "type": "float", "value": snapshot_value}
                    },
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )
    snapshot = PERF_MONITORS_COMMAND.recipe(
        PerfMonitorsParams(), project=tmp_path, godot=None
    )
    assert isinstance(snapshot, PerfMonitorsResult), snapshot
    runs.append((snapshot, {snapshot_value}))

    # Window mode. The sampled values are DISTINCT and their mean is not one of
    # them, so an aggregate gda computed cannot be mistaken for a value it
    # selected; the budget gates `mean` and declares bounds no sample carries, so
    # every number in the verdict is gda's.
    sampled = [61.5, 63.5, 67.5, 71.5]
    budget = tmp_path / "probe-budget.json"
    budget.write_text(
        json.dumps({"fps": {"stat": "mean", "min": 7.25, "max": 9.75}}),
        encoding="utf-8",
    )
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    "kind": "sample",
                    "frames": len(sampled),
                    "monitors": ["fps"],
                    "samples": [
                        {"frame": index, "timestamp": 100 + index, "values": {"fps": v}}
                        for index, v in enumerate(sampled)
                    ],
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )
    window = PERF_MONITORS_COMMAND.recipe(
        PerfMonitorsParams.model_validate(
            {"frames": len(sampled), "monitors": ["fps"], "budget": str(budget)}
        ),
        project=tmp_path,
        godot=None,
    )
    assert isinstance(window, PerfMonitorsResult), window
    runs.append((window, set(sampled)))
    return runs


def _screen_capture_probe(monkeypatch, tmp_path):
    """Drive `screen capture`'s recipe with a gated reply whose floats are sentinels."""
    from gda.commands.screen import (
        SCREEN_CAPTURE_COMMAND,
        ScreenCaptureParams,
        ScreenCaptureResult,
    )

    assert SCREEN_CAPTURE_COMMAND.recipe is not None
    observed = 12.5
    reply = screen_capture_reply(PNG_1X1_B64, width=8, height=8)
    reply["predicate"] = {
        "node": "/root/Main/VFX",
        "property": "frame",
        "expected": observed,
        "observed": observed,
        "engine_frame": 240,
        "frames_waited": 5,
    }
    reply["receipt"].update(observed=observed, engine_frame=240)
    inject_live_runner(
        monkeypatch,
        RunResult(stdout=sentinel(reply), stderr="", exit_code=0),
    )
    result = SCREEN_CAPTURE_COMMAND.recipe(
        ScreenCaptureParams(
            output=str(tmp_path / "probe-shot.png"),
            await_node="/root/Main/VFX",
            await_property="frame",
            await_value=observed,
        ),
        project=tmp_path,
        godot=None,
    )
    assert isinstance(result, ScreenCaptureResult), result
    return [(result, {observed})]


# The recipes whose results mix the two writers, and the probe that measures each.
# Not a list of what to disclose — a list of what to MEASURE, and a recipe-bearing
# command missing from it fails rather than defaulting to the engine's sentence.
PROVENANCE_PROBES = {
    "perf monitors": _perf_monitors_probe,
    "screen capture": _screen_capture_probe,
}


def float_provenance(name, descriptor, monkeypatch, tmp_path) -> "dict[str, str]":
    """Which writer produces each float-bearing field of ``name``'s result."""
    paths = [field.path for field in live_float_fields(descriptor.output_model)]
    if descriptor.recipe is None:
        # gda.dispatch hands a recipe-less command's raw reply straight to
        # `classify_live(..., cmd.output_model)`; the CLI builds no result, so
        # every float in it is one the harness wrote.
        return {path: ENGINE_WRITTEN for path in paths}
    probe = PROVENANCE_PROBES.get(name)
    assert probe is not None, (
        f"{name} assembles its result CLI-side (its descriptor carries a recipe), "
        "so its floats' writer cannot be read off the dispatch branch: add a probe "
        "to PROVENANCE_PROBES so the sentence it must publish is MEASURED"
    )
    measured = _measured_provenance(probe(monkeypatch, tmp_path))
    unexercised = [path for path in paths if path not in measured]
    assert not unexercised, (
        f"{name}'s provenance probe never put a float in {unexercised}, so nothing "
        "measured which writer produces them"
    )
    return measured


def test_every_float_a_live_reply_returns_publishes_its_writers_contract(
    monkeypatch, tmp_path
):
    """The result contract is derived from the models AND bound to the value's writer.

    #752 requires the selected policy to be consistent across the machine schema
    among other surfaces. This walks every LIVE result model, establishes each
    float-bearing field's writer, and fails on a field that publishes nothing —
    or publishes the OTHER writer's sentence, which is what #770's round-4 review
    caught: a subtree blanketed with the engine's claim over numbers gda made.
    """
    offenders: "dict[str, list[tuple[str, str]]]" = {}
    derived: "list[str]" = []
    for name, descriptor in _live_leaves():
        fields = live_float_fields(descriptor.output_model)
        if not fields:
            continue
        provenance = float_provenance(name, descriptor, monkeypatch, tmp_path)
        for field in fields:
            writer = provenance[field.path]
            if writer == GDA_DERIVED:
                derived.append(field.path)
            wrong = SENTENCE_FOR[
                ENGINE_WRITTEN if writer == GDA_DERIVED else GDA_DERIVED
            ]
            if SENTENCE_FOR[writer] not in field.covering or wrong in field.covering:
                offenders.setdefault(name, []).append((field.path, writer))
    assert offenders == {}, (
        "these live result fields do not publish the precision contract of the "
        "writer that produces them (gda.live_numbers, #752/#770): {path: writer} "
        f"{offenders}"
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

    # Discrimination floor: a probe that classified everything one way would pass
    # the loop above by making the whole surface agree with itself. These four are
    # the shapes the measurement exists to tell apart — a bound copied from the
    # caller's budget file and an aggregate gda computed are gda's; a selected
    # sample and the raw rows it was selected from are the engine's.
    assert "PerfMonitorsResult.budget.min" in derived, sorted(derived)
    assert "PerfMonitorsResult.stats.mean" in derived, sorted(derived)
    assert "PerfMonitorsResult.stats.min" not in derived, sorted(derived)
    assert "PerfMonitorsResult.samples.values" not in derived, sorted(derived)


def test_the_classify_path_hands_back_the_engines_own_floats(monkeypatch, tmp_path):
    # Why a recipe-less live command's floats are engine-written: gda.dispatch
    # gives the raw reply to `classify_live(..., cmd.output_model)` and the CLI
    # constructs nothing, so the number the caller reads is the one the harness's
    # full-precision writer emitted. Exercised end to end on `game get` with two
    # values Godot's DEFAULT writer would have lost (1e-300 flattens, and
    # 3.141592653589793 loses its last digits), so the assertion would also fail
    # if anything CLI-side re-rendered the value.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    reply = {
        "path": "/root/Main/Player",
        "name": "Player",
        "type": "CharacterBody2D",
        "properties": [
            {"name": "tiny", "type": "float", "value": 1e-300},
            {"name": "precise", "type": "float", "value": 3.141592653589793},
        ],
    }
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(reply), stderr="", exit_code=0)
    )

    rendered = CliRunner().invoke(
        app,
        ["game", "get", "/root/Main/Player", "--project", str(tmp_path), "--json"],
    )

    assert rendered.exit_code == 0, rendered.stdout
    values = [p["value"] for p in json.loads(rendered.stdout)["properties"]]
    assert values == [1e-300, 3.141592653589793], values


def test_a_gda_derived_float_keeps_a_negative_zero_and_discloses_it(
    monkeypatch, tmp_path
):
    # #770's round-4 finding, reproduced through the recipe: a real daemon
    # returned `{"value": 1.0, "min": -0.0, "max": -0.0}` for a budget verdict
    # while the field published the ENGINE's sentence, which says a negative zero
    # reads back as 0.0. The bounds are copied out of the caller's own file and
    # meet no Godot writer, so the -0.0 survives — and the field now says whose
    # number it is.
    from gda.commands.perf import (
        PERF_MONITORS_COMMAND,
        PerfBudgetVerdict,
        PerfMonitorsParams,
        PerfMonitorsResult,
    )

    budget = tmp_path / "negative-zero-budget.json"
    budget.write_text(
        json.dumps({"fps": {"stat": "mean", "min": -0.0, "max": -0.0}}),
        encoding="utf-8",
    )
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel(
                {
                    "kind": "sample",
                    "frames": 2,
                    "monitors": ["fps"],
                    "samples": [
                        {"frame": 0, "timestamp": 100, "values": {"fps": 0.5}},
                        {"frame": 1, "timestamp": 101, "values": {"fps": 1.5}},
                    ],
                }
            ),
            stderr="",
            exit_code=0,
        ),
    )
    assert PERF_MONITORS_COMMAND.recipe is not None

    result = PERF_MONITORS_COMMAND.recipe(
        PerfMonitorsParams.model_validate(
            {"frames": 2, "monitors": ["fps"], "budget": str(budget)}
        ),
        project=tmp_path,
        godot=None,
    )

    assert isinstance(result, PerfMonitorsResult), result
    assert result.budget is not None
    verdict = result.budget["fps"]
    assert verdict.value == 1.0
    assert verdict.min is not None and verdict.max is not None
    # The review's observation, as a bit pattern rather than a comparison
    # (-0.0 == 0.0 is True): the sign survives gda's serializer.
    assert [math.copysign(1.0, bound) for bound in (verdict.min, verdict.max)] == [
        -1.0,
        -1.0,
    ]
    assert json.dumps(result.model_dump()).count("-0.0") == 2

    for name in ("value", "min", "max"):
        description = PerfBudgetVerdict.model_fields[name].description or ""
        assert LIVE_DERIVED_PRECISION in description, name
        assert LIVE_ENGINE_PRECISION not in description, name


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
    assert LIVE_ENGINE_PRECISION in json.dumps(document["output"], ensure_ascii=False)
    assert LIVE_ENGINE_PRECISION not in json.dumps(
        document["input"], ensure_ascii=False
    )


@pytest.mark.parametrize("name", [name for name, _ in _float_bearing_live_commands()])
def test_the_precision_contract_reaches_the_rendered_help(name):
    # Typer renders a command's DOCSTRING as its help and cannot interpolate a
    # constant into it, so each copy is pinned against the production authority —
    # and the SET of commands that must carry one is derived from the result
    # models above, which is what an earlier round got wrong by listing it.
    rendered = CliRunner().invoke(app, [*name.split(), "--help"])
    assert rendered.exit_code == 0, rendered.stdout
    assert LIVE_ENGINE_PRECISION in " ".join(panel_text(rendered.stdout).split()), name


def test_only_the_replies_that_carry_a_gda_number_publish_the_derived_contract(
    monkeypatch, tmp_path
):
    # The derived sentence follows the same two surfaces as the engine's, and it
    # is published where — and ONLY where — the measurement says a reply carries
    # a number gda made. Both directions matter: a command that returns one and
    # stays silent leaves the round-4 defect in the help and the schema, while
    # pasting both sentences everywhere would restore the blanket claim the whole
    # guard exists to prevent.
    for name, descriptor in _float_bearing_live_commands():
        carries_gda_number = (
            GDA_DERIVED
            in float_provenance(name, descriptor, monkeypatch, tmp_path).values()
        )

        schema = CliRunner().invoke(app, [*name.split(), "--schema"])
        assert schema.exit_code == 0, schema.stdout
        published = json.dumps(json.loads(schema.stdout)["output"], ensure_ascii=False)
        assert (LIVE_DERIVED_PRECISION in published) is carries_gda_number, name

        rendered = CliRunner().invoke(app, [*name.split(), "--help"])
        assert rendered.exit_code == 0, rendered.stdout
        helped = " ".join(panel_text(rendered.stdout).split())
        assert (LIVE_DERIVED_PRECISION in helped) is carries_gda_number, name


def test_the_headless_property_shape_makes_no_live_precision_promise():
    # The shared NodeProperty description serves `node get` / `resource get` too.
    # Since #771 those reads carry the same full binary64 precision, but not over
    # the same LEG: both published sentences speak about the live wire (one about
    # the writer that frames what crosses it, one about a number that never meets
    # it), and neither is true of a headless read as WORDED. So the live commands
    # keep publishing them on their OWN fields, and the subtree rule above is what
    # lets them; `gda.live_numbers` records why no headless twin was authored.
    from gda.models import NodeProperty

    schema = json.dumps(NodeProperty.model_json_schema(), ensure_ascii=False)
    rendered = CliRunner().invoke(app, ["node", "get", "--schema"])
    published = json.dumps(json.loads(rendered.stdout)["output"], ensure_ascii=False)
    for sentence in SENTENCE_FOR.values():
        assert sentence not in schema
        assert sentence not in published


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
