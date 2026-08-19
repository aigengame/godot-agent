"""Human-readable rendering for ``gda`` results — the presentation layer.

The result models (``gda.models``) are pure ``--schema`` / ``--json`` data
contracts (ADR-0004); presentation does not live in them. This module owns the
human-readable text path: one renderer per result type, plus the typed helpers
that keep the presentation layer from reaching into a model's value shape or
across a union of result types. A command binds its renderer on its own
``HeadlessCommand`` descriptor (``render=``, ADR-0023) — there is no central
type-keyed dispatch table here; emission calls the descriptor's renderer.

Since ADR-0040 a group's own renderers live in its ``gda.commands.<group>``
module, beside the descriptors that bind them; what stays here are the helpers
shared ACROSS groups — value-to-text, the node-tree outline, and the property
read / set-echo lines. Two of them carry rationale worth stating here:

- **Value-to-text.** A node property's ``value`` is arbitrary JSON (every Godot
  type carried uniformly, :class:`~gda.models.NodeProperty`). :func:`format_value`
  owns the JSON projection so no renderer reaches into ``.value`` with a raw
  ``json.dumps``.
- **Node-tree outline.** :func:`render_node_tree` walks any node shape carrying
  ``name``/``type``/``children``, so the on-disk ``scene``/``node`` trees and the
  runtime ``game`` tree share one indented outline.
"""

import json
from collections.abc import Sequence
from typing import Any, Protocol

from gda.models import NodeProperty
from gda.script_errors import ScriptError


def format_value(value: Any) -> str:
    """Render a node property value (arbitrary JSON) as text.

    The one place value-to-text formatting lives, so no renderer reaches into a
    model's ``.value`` with a raw ``json.dumps``: a node property's value is the
    JSON projection of a Godot type (a scalar stays a scalar, a Vector2 becomes
    ``[x, y]``), and this owns that projection for the human path.
    """
    return json.dumps(value)


def render_script_error_location(diagnostic: ScriptError) -> str:
    """``<path>:<line>: <message>`` for one script error, dropping the parts it lacks.

    Two groups render recognized script errors now — ``script run``'s passed-through
    diagnostics and ``scene preflight``'s startup diagnostics — so the one-line
    location form lives here rather than in either group, and reads identically in
    both. Typed against :class:`~gda.script_errors.ScriptError` directly, unlike the
    structural :class:`NodeOutline` below: that one bridges several GROUP models,
    while this is one model from a foundation module the presentation layer may name
    (``gda.script_errors`` imports only ``gda.engine_log``), so a Protocol would buy
    nothing here.

    An engine-side load failure carries no script line, and some carry no path at
    all, so each piece is included only when the engine reported it — never as an
    empty ``:`` or a bare ``None``.
    """
    where = diagnostic.path or ""
    if diagnostic.path is not None and diagnostic.line is not None:
        where = f"{diagnostic.path}:{diagnostic.line}"
    return f"{where}: {diagnostic.message}" if where else diagnostic.message


class NodeOutline(Protocol):
    """The shared tree surface every renderable node shape carries.

    A structural (typing-only) interface over the ``name``/``type``/``children``
    that the on-disk ``SceneNode``/``ListedNode`` and the runtime ``GameNode``
    all have. :func:`render_node_tree` types against this surface, so the shared
    renderer names no group model and the ``commands`` → ``render`` dependency
    direction stays one-way (ADR-0040 §5). Read-only properties, so a model
    whose ``children`` is a concrete ``list`` of its own node type satisfies it.
    """

    @property
    def name(self) -> str: ...

    @property
    def type(self) -> str: ...

    @property
    def children(self) -> Sequence["NodeOutline"]: ...


def render_node_tree(node: NodeOutline, depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans.

    Types against the structural :class:`NodeOutline` surface: the renderer reads
    only ``name``/``type``/``children``, which every node in every tree shape
    carries, so one walk serves the on-disk ``scene``/``node`` trees and the
    runtime ``game`` tree without naming a union of group models.

    Iterative on purpose (issue #37): a legitimately deep scene tree can nest far
    past Python's recursion limit, so this walks the tree with an explicit stack
    (pre-order, children left-to-right — the same outline a recursive walk would
    produce) rather than recursing per level and raising an unstructured
    ``RecursionError`` on a deep-but-valid tree.
    """
    lines: list[str] = []
    # Stack of (node, depth); pushing children in reverse so the leftmost child
    # is popped first preserves the recursive pre-order, in-order traversal.
    stack: list[tuple[NodeOutline, int]] = [(node, depth)]
    while stack:
        current, current_depth = stack.pop()
        lines.append(f"{'  ' * current_depth}{current.name} ({current.type})")
        for child in reversed(current.children):
            stack.append((child, current_depth + 1))
    return "\n".join(lines)


def render_property_lines(
    path: str, type_name: str, properties: Sequence[NodeProperty]
) -> str:
    """Render a ``path (Type)`` header plus one typed line per property — the shared get surface."""
    body = (f"  {p.name} ({p.type}) = {format_value(p.value)}" for p in properties)
    return "\n".join([f"{path} ({type_name})", *body])


def render_set_echo(path: str, property_name: str, type_name: str, value: Any) -> str:
    """Render ``set <path>.<property> (<type>) = <value>`` — the shared node/resource set echo."""
    return f"set {path}.{property_name} ({type_name}) = {format_value(value)}"
