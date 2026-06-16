"""The presentation layer (``gda.render``) — issue #140.

Human rendering lives in a dedicated module, selected by result type, and reads
typed surfaces (a value helper, a shared script-metadata interface) rather than
reaching into a model's ``.value`` or across a union of result types. These are
unit tests on the presentation module itself; the end-to-end human-output text
per command is pinned by the existing command tests, which still pass unchanged.
"""

import pytest

from gda import render as render_mod
from gda.models import (
    EngineVersion,
    ListedNode,
    ListedScript,
    NodeGetResult,
    NodeProperty,
    NodeSetResult,
    SceneNode,
    ScriptCreateResult,
    ScriptDeleteResult,
    ScriptGetResult,
    ScriptSetResult,
)
from gda.render import ScriptMetadata, format_value, render, render_node_tree

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
    root = leaf = model.model_construct(name="n0", type="Node", children=[], **leaf_fields)
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
    rendered = render(result)
    assert rendered == ". (Node2D)\n  position (Vector2) = [1.0, 2.0]"


def test_render_node_set_routes_value_through_the_helper():
    result = NodeSetResult(
        scene_path="res://s.tscn",
        path=".",
        property="visible",
        type="bool",
        value=False,
    )
    assert render(result) == "set ..visible (bool) = false"


def test_render_is_keyed_by_result_type():
    # render() selects the renderer by the result's concrete type, so a command
    # sources its renderer from the module by result type, not an inline closure.
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
    assert render(version) == "4.6.3-stable (official)"


def test_render_rejects_an_unregistered_result_type():
    # An unrecognized result type is a programming error (a command wired with no
    # renderer), surfaced loudly rather than silently mis-formatted.
    with pytest.raises(KeyError):
        render(object())


def test_every_command_result_type_has_a_renderer():
    # The type → renderer table covers every result type a command emits, so the
    # keyed dispatch never falls through for a real command.
    from gda import cli

    output_models = {
        cmd.output_model
        for name in dir(cli)
        if name.endswith("_COMMAND")
        for cmd in [getattr(cli, name)]
    }
    registered = set(render_mod._RENDERERS)
    assert output_models <= registered
