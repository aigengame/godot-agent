"""The presentation layer (``gda.render``) — issue #140.

Human rendering lives in a dedicated module, one renderer per result type, reading
typed surfaces (a value helper, a shared script-metadata interface) rather than
reaching into a model's ``.value`` or across a union of result types. These are
unit tests on the renderers themselves; the end-to-end human-output text per
command is pinned by ``test_human_output.py``, and the descriptor-carried
renderer invariant (every command has one, none orphaned — ADR-0023) by
``test_command_descriptor_registry.py``.

Since ADR-0023 each command binds its renderer on its ``HeadlessCommand``
descriptor and there is no central ``render()`` type-dispatch, so these tests call
the renderer functions directly — the assertions (a renderer's exact text) are
unchanged.
"""

import pytest

from gda.commands.node import (
    ListedNode,
    NodeGetResult,
    NodeSetResult,
    render_node_properties,
    render_node_set,
)
from gda.commands.scene import SceneNode
from gda.commands.script import (
    ListedScript,
    ScriptCreateResult,
    ScriptDeleteResult,
    ScriptGetResult,
    ScriptSetResult,
)
from gda.commands.daemon import (
    DaemonStartResult,
    DaemonStatusResult,
    DaemonUninstallResult,
    render_daemon_start,
    render_daemon_status,
    render_daemon_uninstall,
)
from gda.commands.game import (
    GameGetResult,
    GameRectResult,
    GameSetResult,
    render_game_get,
    render_game_rect,
    render_game_set,
)
from gda.commands.perf import (
    PerfMonitor,
    PerfMonitorResult,
    PerfMonitorsResult,
    PerfPropertySample,
    PerfSignalEmission,
    render_perf_monitor,
    render_perf_monitors,
)
from gda.models import EngineVersion, NodeProperty
from gda.commands.meta import render_engine_version
from gda.commands.script import ScriptMetadata
from gda.render import format_value, render_node_tree

# The five script result types the metadata renderer used to read as a union.
SCRIPT_METADATA_MODELS = [
    ScriptCreateResult,
    ScriptGetResult,
    ListedScript,
    ScriptDeleteResult,
    ScriptSetResult,
]


@pytest.mark.parametrize("model", SCRIPT_METADATA_MODELS)
def test_script_result_types_satisfy_the_shared_metadata_interface(model):
    # Each script result type structurally matches ScriptMetadata, so the
    # metadata renderer reads ONE typed surface, not a five-way union.
    instance = model.model_construct(path="res://s.gd", class_name=None, extends=None)
    assert isinstance(instance, ScriptMetadata)


@pytest.mark.parametrize(
    "model",
    SCRIPT_METADATA_MODELS,
    ids=[m.__name__ for m in SCRIPT_METADATA_MODELS],
)
def test_metadata_interface_declares_the_three_human_facing_fields(model):
    # The interface names exactly the fields the renderer reads; every model
    # carries them, so adding a script result type needs no renderer change.
    fields = set(model.model_fields)
    assert {"path", "class_name", "extends"} <= fields


def test_metadata_interface_is_a_protocol_so_models_keep_their_schema():
    # ScriptMetadata is a structural Protocol, not a base the models inherit, so
    # it imposes nothing on a model's JSON Schema or field order (the --schema
    # contract is unchanged). A model inheriting it would have reordered fields;
    # confirm none of them subclass it.
    for model in SCRIPT_METADATA_MODELS:
        assert ScriptMetadata not in model.__mro__


def test_format_value_owns_value_to_text():
    # The single typed value-to-text helper: a scalar stays a scalar, a packed
    # Godot type its JSON list projection — the same projection node set accepts.
    assert format_value(3) == "3"
    assert format_value([1.0, 2.0]) == "[1.0, 2.0]"
    assert format_value(True) == "true"


def _deep_chain(model, depth, **leaf_fields):
    # A single-child chain `depth` nodes deep, built via model_construct so it
    # bypasses pydantic's recursive validation (issue #37): the point is to
    # exercise the RENDER path's recursion in isolation, at a depth past the
    # ~255 pydantic-core ceiling a legitimately deep scene can reach.
    root = leaf = model.model_construct(
        name="n0", type="Node", children=[], **leaf_fields
    )
    for i in range(1, depth):
        child = model.model_construct(
            name=f"n{i}", type="Node", children=[], **leaf_fields
        )
        leaf.children = [child]
        leaf = child
    return root


def test_render_node_tree_does_not_recurse_on_a_deep_tree():
    # The non-`--json` render path must not raise an unstructured RecursionError
    # on a legitimately deep scene tree (issue #37): a 2000-deep chain — far past
    # the ~255 pydantic-core ceiling — renders one indented line per node.
    deep = _deep_chain(SceneNode, 2000)

    rendered = render_node_tree(deep)

    lines = rendered.split("\n")
    assert len(lines) == 2000
    assert lines[0] == "n0 (Node)"
    assert lines[-1] == "  " * 1999 + "n1999 (Node)"


def test_render_node_tree_renders_listed_nodes_deeply_too():
    # node list shares the same recursive renderer over ListedNode; a deep listed
    # tree must render without RecursionError as well (issue #37).
    deep = _deep_chain(ListedNode, 2000, path=".")

    rendered = render_node_tree(deep)

    assert len(rendered.split("\n")) == 2000


def test_render_node_properties_routes_value_through_the_helper():
    result = NodeGetResult(
        scene_path="res://s.tscn",
        path=".",
        name="Root",
        type="Node2D",
        properties=[NodeProperty(name="position", type="Vector2", value=[1.0, 2.0])],
    )
    rendered = render_node_properties(result)
    assert rendered == ". (Node2D)\n  position (Vector2) = [1.0, 2.0]"


def test_render_node_properties_renders_a_compound_value_projection():
    # A dict-valued property (the ADR-0035 compound projection) renders through
    # the same format_value helper — json.dumps of the projected object, no
    # per-shape renderer.
    result = NodeGetResult(
        scene_path="res://s.tscn",
        path=".",
        name="Root",
        type="Node2D",
        properties=[
            NodeProperty(
                name="fire",
                type="Dictionary",
                value={"deadzone": 0.5, "events": [{"type": "InputEventKey"}]},
            )
        ],
    )
    rendered = render_node_properties(result)
    assert rendered == (
        ". (Node2D)\n"
        '  fire (Dictionary) = {"deadzone": 0.5, "events": [{"type": "InputEventKey"}]}'
    )


def test_render_node_set_routes_value_through_the_helper():
    result = NodeSetResult(
        scene_path="res://s.tscn",
        path=".",
        property="visible",
        type="bool",
        value=False,
    )
    assert render_node_set(result) == "set ..visible (bool) = false"


def test_render_game_get_renders_runtime_properties_by_absolute_path():
    result = GameGetResult(
        path="/root/Main/Player",
        name="Player",
        type="Node2D",
        properties=[NodeProperty(name="position", type="Vector2", value=[10.0, 20.0])],
    )
    rendered = render_game_get(result)
    assert rendered == "/root/Main/Player (Node2D)\n  position (Vector2) = [10.0, 20.0]"


def test_render_game_rect_renders_the_runtime_control_rect():
    result = GameRectResult(
        path="/root/Main/HUD/Stats",
        name="Stats",
        type="VBoxContainer",
        position=[24.0, 24.0],
        size=[160.0, 48.0],
    )
    assert (
        render_game_rect(result) == "/root/Main/HUD/Stats (VBoxContainer) "
        "position=[24.0, 24.0] size=[160.0, 48.0]"
    )


def test_render_game_set_renders_the_set_runtime_property():
    result = GameSetResult(
        path="/root/Main/Player",
        property="position",
        type="Vector2",
        value=[10.0, 20.0],
        verified=True,
    )
    assert (
        render_game_set(result)
        == "set /root/Main/Player.position (Vector2) = [10.0, 20.0] verified=true"
    )


def test_render_perf_monitors_renders_a_sorted_snapshot():
    result = PerfMonitorsResult(
        timestamp=500,
        monitors={
            "fps": PerfMonitor(name="fps", type="float", value=60.0),
            "node_count": PerfMonitor(name="node_count", type="float", value=3.0),
        },
    )
    # Monitors are listed in a stable (name-sorted) order under the timestamp header.
    assert (
        render_perf_monitors(result) == "perf @ 500ms\n  fps = 60.0\n  node_count = 3.0"
    )


def test_render_perf_monitor_property_renders_a_per_frame_timeline():
    result = PerfMonitorResult(
        node="/root/Main/Player",
        kind="property",
        property="position",
        frames=2,
        samples=[
            PerfPropertySample(frame=0, timestamp=100, value=[0.0, 0.0]),
            PerfPropertySample(frame=1, timestamp=116, value=[1.0, 0.0]),
        ],
    )
    assert render_perf_monitor(result) == (
        "/root/Main/Player property position (2 frames)\n"
        "  frame 0: [0.0, 0.0]\n"
        "  frame 1: [1.0, 0.0]"
    )


def test_render_perf_monitor_signal_renders_recorded_emissions():
    result = PerfMonitorResult(
        node="/root/Main/Player",
        kind="signal",
        signal="hit",
        frames=2,
        emissions=[PerfSignalEmission(frame=1, timestamp=116, args=[42])],
    )
    assert render_perf_monitor(result) == (
        "/root/Main/Player signal hit (2 frames)\n  frame 1: [42]"
    )


def test_render_daemon_start_surfaces_a_version_sync(tmp_path):
    # #225: a real version-mismatch re-materialize is surfaced as a sync to the
    # installed version (distinct from merely adding the autoload entry).
    synced = DaemonStartResult(
        pid=42,
        socket_path="/tmp/x.sock",
        installed_harness=True,
        harness_synced=True,
        harness_version="3",
        already_running=False,
    )
    assert (
        render_daemon_start(synced)
        == "daemon started: pid 42 on /tmp/x.sock (synced harness to v3)"
    )

    # A first install (changed but not a version-mismatch resync) reads as install.
    installed = synced.model_copy(update={"harness_synced": False})
    assert (
        render_daemon_start(installed)
        == "daemon started: pid 42 on /tmp/x.sock (installed harness)"
    )


def test_render_daemon_status_notes_the_windowed_session(tmp_path):
    # #251: `daemon status` surfaces the running daemon's display mode. Like
    # `daemon start`, the marker shows only when windowed (headless is the default).
    windowed = DaemonStatusResult(
        running=True, pid=42, socket_path="/tmp/x.sock", windowed=True
    )
    assert (
        render_daemon_status(windowed)
        == "daemon running: pid 42 on /tmp/x.sock [windowed]"
    )

    headless = windowed.model_copy(update={"windowed": False})
    assert render_daemon_status(headless) == "daemon running: pid 42 on /tmp/x.sock"

    # An unknown mode (e.g. a transient round-trip miss) renders no marker either.
    unknown = windowed.model_copy(update={"windowed": None})
    assert render_daemon_status(unknown) == "daemon running: pid 42 on /tmp/x.sock"

    stopped = DaemonStatusResult(running=False, socket_path="/tmp/x.sock")
    assert render_daemon_status(stopped) == "daemon not running"


def test_render_daemon_uninstall_reports_removal(tmp_path):
    # #225: uninstall renders the paired removal, with the idempotent no-op form.
    assert (
        render_daemon_uninstall(DaemonUninstallResult(removed=True))
        == "harness uninstalled"
    )
    assert (
        render_daemon_uninstall(DaemonUninstallResult(removed=False))
        == "no harness was installed"
    )


def test_render_engine_version_renders_the_one_line_version_string():
    version = EngineVersion(
        major=4,
        minor=6,
        patch=3,
        hex=0x040603,
        status="stable",
        build="official",
        hash="abc",
        string="4.6.3-stable (official)",
        timestamp=0,
    )
    assert render_engine_version(version) == "4.6.3-stable (official)"


def test_render_diag_errors_shows_the_callstack_frames_under_the_error():
    # A runtime error with a multi-frame call stack (#283): the human view lists
    # the ordered frames (most-recent-first) under the error's headline line, so
    # an agent reading the text sees where it originated, not just the top frame.
    from gda.commands.diag import DiagError, DiagErrorsResult, SourceFrame
    from gda.commands.diag import render_diag_errors

    result = DiagErrorsResult(
        errors=[
            DiagError(
                level="script_error",
                message="Nonexistent function 'do_thing' in base 'Nil'.",
                function="b",
                file="res://main.gd",
                line=9,
                callstack=[
                    SourceFrame(function="b", file="res://main.gd", line=9),
                    SourceFrame(function="a", file="res://main.gd", line=6),
                    SourceFrame(function="_ready", file="res://main.gd", line=3),
                ],
            )
        ]
    )

    rendered = render_diag_errors(result)

    # The headline still carries the top location.
    assert "res://main.gd:9" in rendered
    # Every frame appears, ordered, naming function and location.
    assert "a (res://main.gd:6)" in rendered
    assert "_ready (res://main.gd:3)" in rendered
    # Frames render below the headline, in order.
    assert rendered.index("b (res://main.gd:9)") < rendered.index("a (res://main.gd:6)")
    assert rendered.index("a (res://main.gd:6)") < rendered.index(
        "_ready (res://main.gd:3)"
    )


def test_render_diag_errors_omits_a_callstack_block_for_a_bare_error():
    # A bare error has an empty callstack: the renderer shows just its one line,
    # with no empty backtrace block.
    from gda.commands.diag import DiagError, DiagErrorsResult
    from gda.commands.diag import render_diag_errors

    rendered = render_diag_errors(
        DiagErrorsResult(errors=[DiagError(level="error", message="boom")])
    )

    assert rendered == "ERROR: boom"
