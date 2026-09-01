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
- **Failure layout.** :func:`render_failure` is the one human rendering of the
  shared error envelope (#685). Unlike the success renderers it is not per command
  and is not bound to a descriptor: the envelope is ONE shape for every command
  (ADR-0004), so its human form is one function nothing keys a code on.
"""

import json
from collections.abc import Sequence
from typing import Any, Protocol

from gda.models import FailureEvidence, GdaError, NodeProperty
from gda.script_errors import script_error_line


def format_value(value: Any) -> str:
    """Render a node property value (arbitrary JSON) as text.

    The one place value-to-text formatting lives, so no renderer reaches into a
    model's ``.value`` with a raw ``json.dumps``: a node property's value is the
    JSON projection of a Godot type (a scalar stays a scalar, a Vector2 becomes
    ``[x, y]``), and this owns that projection for the human path.
    """
    return json.dumps(value)


def render_failure(error: GdaError) -> str:
    """Render a failure envelope as the lines a human reads (#685).

    The human half of the public failure channel, and the counterpart of a command's
    own success renderer: :func:`gda.headless.emit_failure` calls this when the
    invocation did not ask for JSON. Before it existed there was no human channel at
    all — every failure was the ``{"error": {...}}`` line — so a caller without
    ``--json`` read a ``script run --strict`` capture as one escaped blob, which is
    the evidence that flag exists to produce.

    ONE renderer for every ``Gda error code``: nothing here keys on a code, so a
    command cannot grow a private failure layout. It is also TOTAL over the envelope
    — the verdict, the message, then each optional key (``probe`` #667, ``hint``
    #670, ``evidence`` #687) — because the text replaces a JSON line that carried all
    of them, and a human failure that quietly dropped one would say less than what it
    replaced. Every one of those keys is REACHABLE here: ``hint`` is set only by the
    near-miss refusal (``gda.hints``), which answers through this channel too rather
    than through the parser's own usage error (#798 review) — before that, totality
    over ``hint`` was a dead branch.

    The order is short-before-long: the fixed-size parts stay together under the head
    line, and ``diagnostics`` goes last because it is the only unbounded part (two
    16 KiB tail-capped captures on a timeout), so it can never push the verdict off a
    terminal. Absent parts render NOTHING — no empty section, no blank tail — and the
    string carries no trailing newline, since the CLI's ``typer.echo`` adds exactly
    one.

    The recognized script errors can therefore appear twice on the two ``script run``
    verdicts that also render them into ``diagnostics`` prose
    (``gda.errors._ended_run_diagnostics``). That is accepted rather than
    special-cased: for the four other codes carrying ``evidence.script_errors`` the
    diagnostics is RAW engine stderr, where the curated list is the summary that makes
    the dump readable — and suppressing it per code is exactly the per-command layout
    this renderer exists to prevent.
    """
    lines = [f"error: {error.code} ({error.category.value})", error.message]
    if error.probe is not None:
        lines.append(f"probe: {error.probe.name} ({error.probe.platform})")
    if error.hint is not None:
        lines.append(f"hint: {error.hint}")
    if error.evidence is not None:
        lines.extend(_evidence_lines(error.evidence))
    if error.diagnostics.strip():
        lines.extend(("", error.diagnostics.strip("\n")))
    return "\n".join(lines)


def _evidence_lines(evidence: FailureEvidence) -> list[str]:
    """The ``evidence:`` block, or nothing when this object carries no field.

    Every field of :class:`~gda.models.FailureEvidence` is individually optional and
    omitted rather than nulled (#687), so this enumerates them in the model's own
    declaration order — one authority for what the evidence IS, read the same way by
    both channels — and returns an empty list when none is set, rather than a header
    over nothing.

    The clock is rendered to two decimals, the same precision the ``launch_timeout``
    message already states it in, so the prose and the block cannot disagree about
    the same run; the full-precision value stays in the JSON channel.
    """
    body: list[str] = []
    if evidence.exit_status is not None:
        body.append(f"  exit status: {evidence.exit_status}")
    if evidence.elapsed_seconds is not None:
        body.append(f"  elapsed: {evidence.elapsed_seconds:.2f}s")
    if evidence.timeout_seconds is not None:
        body.append(f"  timeout: {evidence.timeout_seconds}s")
    if evidence.termination_phase is not None:
        body.append(f"  termination phase: {evidence.termination_phase.value}")
    if evidence.script_errors:
        body.append("  script errors:")
        body.extend(
            f"    {script_error_line(error)}" for error in evidence.script_errors
        )
    return ["evidence:", *body] if body else []


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
