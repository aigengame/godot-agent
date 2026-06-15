"""Human-readable rendering for ``gda`` results — the presentation layer.

The result models (``gda.models``) are pure ``--schema`` / ``--json`` data
contracts (ADR-0004); presentation does not live in them. This module owns the
human-readable text path: one renderer per result type, selected by result type
via :func:`render`, plus the typed helpers that keep the presentation layer from
reaching into a model's value shape or across a union of result types.

Two seams are deliberately funnelled through one place here:

- **Value-to-text.** A node property's ``value`` is arbitrary JSON (every Godot
  type carried uniformly, :class:`~gda.models.NodeProperty`). :func:`format_value`
  owns the JSON projection so no renderer reaches into ``.value`` with a raw
  ``json.dumps``.
- **Script metadata.** Five script result types share the same human-facing
  ``path``/``class_name``/``extends`` surface. :class:`ScriptMetadata` is the
  structural interface the metadata renderer reads, so the renderer types against
  one surface rather than a five-way union.
"""

import json
from typing import Any, Protocol, runtime_checkable

from gda.models import (
    EngineVersion,
    ExportGetResult,
    ExportListResult,
    NodeAddResult,
    NodeConnectSignalResult,
    NodeDisconnectSignalResult,
    NodeDuplicateResult,
    NodeGetResult,
    NodeListResult,
    NodeMoveResult,
    NodeRemoveResult,
    NodeSetResult,
    ResourceCreateResult,
    ResourceGetResult,
    ResourceUidResult,
    SceneCreateResult,
    SceneDeleteResult,
    SceneGetExportsResult,
    SceneGetResult,
    SceneListResult,
    SceneNode,
    ScriptAttachResult,
    ScriptCreateResult,
    ScriptDeleteResult,
    ScriptGetResult,
    ScriptListResult,
    ScriptSetResult,
    ScriptValidateResult,
)


@runtime_checkable
class ScriptMetadata(Protocol):
    """The shared human-facing surface of every script result type.

    A structural (typing-only) interface — fields, no methods — over the
    ``path``/``class_name``/``extends`` that :class:`~gda.models.ScriptCreateResult`,
    :class:`~gda.models.ScriptGetResult`, :class:`~gda.models.ListedScript`,
    :class:`~gda.models.ScriptDeleteResult` and :class:`~gda.models.ScriptSetResult`
    all carry. The metadata renderer types against this surface, so adding a
    script result type that carries the same fields needs no renderer change and
    the renderer never reads across a union. It is a ``Protocol`` rather than a
    shared base model so it imposes nothing on the models' JSON Schema or field
    order (the ``--schema`` contract stays byte-for-byte unchanged).
    """

    path: str
    class_name: str | None
    extends: str | None


def format_value(value: Any) -> str:
    """Render a node property value (arbitrary JSON) as text.

    The one place value-to-text formatting lives, so no renderer reaches into a
    model's ``.value`` with a raw ``json.dumps``: a node property's value is the
    JSON projection of a Godot type (a scalar stays a scalar, a Vector2 becomes
    ``[x, y]``), and this owns that projection for the human path.
    """
    return json.dumps(value)


def render_node_tree(node: "SceneNode", depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans.

    Types against ``SceneNode`` alone: ``ListedNode`` is a ``SceneNode`` subclass
    (one tree shape), so node list's tree flows through here without naming a
    union — the renderer reads only ``name``/``type``/``children``, which every
    node in the tree carries.

    Iterative on purpose (issue #37): a legitimately deep scene tree can nest far
    past Python's recursion limit, so this walks the tree with an explicit stack
    (pre-order, children left-to-right — the same outline a recursive walk would
    produce) rather than recursing per level and raising an unstructured
    ``RecursionError`` on a deep-but-valid tree.
    """
    lines: list[str] = []
    # Stack of (node, depth); pushing children in reverse so the leftmost child
    # is popped first preserves the recursive pre-order, in-order traversal.
    stack: list[tuple["SceneNode", int]] = [(node, depth)]
    while stack:
        current, current_depth = stack.pop()
        lines.append(f"{'  ' * current_depth}{current.name} ({current.type})")
        for child in reversed(current.children):
            stack.append((child, current_depth + 1))
    return "\n".join(lines)


def render_scene_metadata(scene: "SceneCreateResult") -> str:
    """Render a created scene as ``created <path> (root <type>)``."""
    return f"created {scene.path} (root {scene.root_type})"


def render_scene_tree(scene: "SceneGetResult") -> str:
    """Render a read scene's node tree."""
    return render_node_tree(scene.root)


def render_scene_exports(scene: "SceneGetExportsResult") -> str:
    """Render a scene's per-node @export properties for humans.

    One ``path (Type)`` header per node that declares exports, then a
    ``name (Type) = value`` line per export — reusing :func:`format_value` for
    the value, the same projection ``node get`` renders. An empty listing (no
    exported variables anywhere) reads as ``(no exports)``.
    """
    if not scene.nodes:
        return "(no exports)"
    lines = []
    for node in scene.nodes:
        lines.append(f"{node.path} ({node.type})")
        for export in node.exports:
            lines.append(
                f"  {export.name} ({export.type}) = {format_value(export.value)}"
            )
    return "\n".join(lines)


def render_scene_list(listed: "SceneListResult") -> str:
    """Render the enumerated scenes as ``path (root_name: root_type)`` lines."""
    if not listed.scenes:
        return "(no scenes)"
    lines = []
    for scene in listed.scenes:
        if scene.root_name is not None and scene.root_type is not None:
            lines.append(f"{scene.path} ({scene.root_name}: {scene.root_type})")
        else:
            lines.append(f"{scene.path} (unreadable)")
    return "\n".join(lines)


def render_scene_delete(removed: "SceneDeleteResult") -> str:
    """Render a deleted scene as ``deleted <path> (root <name>: <type>)``."""
    return f"deleted {removed.path} (root {removed.root_name}: {removed.root_type})"


def render_node_add(added: "NodeAddResult") -> str:
    """Render an added node as ``added <path> (<type>) to <scene>``."""
    return f"added {added.path} ({added.type}) to {added.scene_path}"


def render_node_list(listed: "NodeListResult") -> str:
    """Render a listed scene's node tree (with node paths)."""
    return render_node_tree(listed.root)


def render_node_properties(got: "NodeGetResult") -> str:
    """Render a node's properties as ``name (Type) = value`` lines for humans."""
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_node_set(was_set: "NodeSetResult") -> str:
    """Render a set property as ``set <path>.<prop> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)}"
    )


def render_node_remove(removed: "NodeRemoveResult") -> str:
    """Render a removed node as ``removed <path> (<type>) from <scene>``."""
    return f"removed {removed.path} ({removed.type}) from {removed.scene_path}"


def render_node_duplicate(duplicated: "NodeDuplicateResult") -> str:
    """Render a duplicated node as ``duplicated <source> to <path> (<type>)``."""
    return (
        f"duplicated {duplicated.source_path} to {duplicated.path} "
        f"({duplicated.type})"
    )


def render_node_move(moved: "NodeMoveResult") -> str:
    """Render a moved node as ``moved <source> to <path> (<type>)``."""
    return f"moved {moved.source_path} to {moved.path} ({moved.type})"


def render_node_connect_signal(connected: "NodeConnectSignalResult") -> str:
    """Render a wired connection as ``connected <from>.<signal> -> <to>.<method>``."""
    return (
        f"connected {connected.from_node}.{connected.signal} -> "
        f"{connected.to}.{connected.method}"
    )


def render_node_disconnect_signal(disconnected: "NodeDisconnectSignalResult") -> str:
    """Render an unwired connection as ``disconnected <from>.<signal> -> <to>.<method>``."""
    return (
        f"disconnected {disconnected.from_node}.{disconnected.signal} -> "
        f"{disconnected.to}.{disconnected.method}"
    )


def render_script_metadata(script: ScriptMetadata) -> str:
    """Render a script's path plus its class_name/extends for humans.

    Reads the shared :class:`ScriptMetadata` surface, so it serves every script
    result type without naming the union.
    """
    meta = []
    if script.extends is not None:
        meta.append(f"extends {script.extends}")
    if script.class_name is not None:
        meta.append(f"class_name {script.class_name}")
    if not meta:
        return script.path
    return f"{script.path} ({', '.join(meta)})"


def render_script_create(created: "ScriptCreateResult") -> str:
    """Render a created script as ``created <metadata>``."""
    return f"created {render_script_metadata(created)}"


def render_script_get(got: "ScriptGetResult") -> str:
    """Render a read script as its metadata line followed by its source."""
    return "\n".join([render_script_metadata(got), got.source])


def render_script_list(listed: "ScriptListResult") -> str:
    """Render the enumerated scripts as ``path (extends X, class_name Y)`` lines."""
    if not listed.scripts:
        return "(no scripts)"
    return "\n".join(render_script_metadata(script) for script in listed.scripts)


def render_script_delete(removed: "ScriptDeleteResult") -> str:
    """Render a deleted script as ``deleted <metadata>``."""
    return f"deleted {render_script_metadata(removed)}"


def render_script_set(edited: "ScriptSetResult") -> str:
    """Render an edited script as ``set <metadata>``."""
    return f"set {render_script_metadata(edited)}"


def render_script_attach(attached: "ScriptAttachResult") -> str:
    """Render an attached script as ``attached <script> to <node> in <scene>``."""
    return (
        f"attached {attached.script} to {attached.node} in {attached.scene_path}"
    )


def render_script_validate(validated: "ScriptValidateResult") -> str:
    """Render a validate result: valid/invalid plus best-effort diagnostics."""
    if validated.valid:
        return f"valid {validated.path}"
    lines = [f"invalid {validated.path}"]
    if validated.error_string is not None:
        lines.append(f"  {validated.error_string}")
    for diag in validated.diagnostics:
        location = f"line {diag.line}" if diag.line is not None else "unknown line"
        lines.append(f"  {location}: {diag.message}")
    return "\n".join(lines)


def render_resource_create(created: "ResourceCreateResult") -> str:
    """Render a created resource as ``created <path> (<type>)``."""
    return f"created {created.path} ({created.type})"


def render_resource_properties(got: "ResourceGetResult") -> str:
    """Render a resource's properties as ``name (Type) = value`` lines for humans.

    Mirrors :func:`render_node_properties`: a header naming the resource and its
    type, then one typed line per storage property — the same human surface a
    node's properties get, since both read the shared :class:`NodeProperty`.
    """
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_export_list(listed: "ExportListResult") -> str:
    """Render the enumerated presets as ``name (platform) [runnable]`` lines."""
    if not listed.presets:
        return "(no presets)"
    lines = []
    for preset in listed.presets:
        runnable = " [runnable]" if preset.runnable else ""
        lines.append(f"{preset.name} ({preset.platform}){runnable}")
    return "\n".join(lines)


def render_export_get(got: "ExportGetResult") -> str:
    """Render one preset's details plus its export-template readiness."""
    runnable = " [runnable]" if got.runnable else ""
    header = f"{got.name} ({got.platform}){runnable}"
    templates = (
        f"templates installed ({got.templates_version})"
        if got.templates_installed
        else f"templates missing ({got.templates_version})"
    )
    return "\n".join([header, f"  export_path: {got.export_path}", f"  {templates}"])


def render_resource_uid(resolved: "ResourceUidResult") -> str:
    """Render a resolved UID↔path mapping as ``<uid> -> <path>`` for humans."""
    return f"{resolved.uid} -> {resolved.path}"


def render_engine_version(version: "EngineVersion") -> str:
    """Render the engine version as its one-line version string."""
    return version.string


# Renderer selection keyed by result type: each result model maps to the one
# renderer that turns it into human-readable text. :func:`render` dispatches on
# ``type(result)``, so a command sources its renderer from this module by its
# result type rather than carrying an inline closure (composes with #139's
# ``render`` dispatch parameter).
_RENDERERS = {
    SceneCreateResult: render_scene_metadata,
    SceneGetResult: render_scene_tree,
    SceneGetExportsResult: render_scene_exports,
    SceneListResult: render_scene_list,
    SceneDeleteResult: render_scene_delete,
    NodeAddResult: render_node_add,
    NodeListResult: render_node_list,
    NodeGetResult: render_node_properties,
    NodeSetResult: render_node_set,
    NodeRemoveResult: render_node_remove,
    NodeDuplicateResult: render_node_duplicate,
    NodeMoveResult: render_node_move,
    NodeConnectSignalResult: render_node_connect_signal,
    NodeDisconnectSignalResult: render_node_disconnect_signal,
    ScriptCreateResult: render_script_create,
    ScriptGetResult: render_script_get,
    ScriptListResult: render_script_list,
    ScriptDeleteResult: render_script_delete,
    ScriptSetResult: render_script_set,
    ScriptAttachResult: render_script_attach,
    ScriptValidateResult: render_script_validate,
    ResourceCreateResult: render_resource_create,
    ResourceGetResult: render_resource_properties,
    ExportListResult: render_export_list,
    ExportGetResult: render_export_get,
    ResourceUidResult: render_resource_uid,
    EngineVersion: render_engine_version,
}


def render(result: Any) -> str:
    """Render any ``gda`` result to human-readable text, keyed by its type.

    Looks the result's concrete type up in the type → renderer table and applies
    the matching renderer. A result type with no registered renderer is a
    programming error (a new command wired without a renderer), not a runtime
    user error, so it raises rather than guessing a format.
    """
    renderer = _RENDERERS.get(type(result))
    if renderer is None:
        raise KeyError(f"no renderer registered for result type {type(result)!r}")
    return renderer(result)
