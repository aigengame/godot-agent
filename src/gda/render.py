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
    ListedNode,
    NodeAddResult,
    NodeDuplicateResult,
    NodeGetResult,
    NodeListResult,
    NodeRemoveResult,
    NodeSetResult,
    SceneCreateResult,
    SceneDeleteResult,
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


def render_node_tree(node: "SceneNode | ListedNode", depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans."""
    lines = [f"{'  ' * depth}{node.name} ({node.type})"]
    lines += (render_node_tree(child, depth + 1) for child in node.children)
    return "\n".join(lines)


def render_scene_metadata(scene: "SceneCreateResult") -> str:
    """Render a created scene as ``created <path> (root <type>)``."""
    return f"created {scene.path} (root {scene.root_type})"


def render_scene_tree(scene: "SceneGetResult") -> str:
    """Render a read scene's node tree."""
    return render_node_tree(scene.root)


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
    SceneListResult: render_scene_list,
    SceneDeleteResult: render_scene_delete,
    NodeAddResult: render_node_add,
    NodeListResult: render_node_list,
    NodeGetResult: render_node_properties,
    NodeSetResult: render_node_set,
    NodeRemoveResult: render_node_remove,
    NodeDuplicateResult: render_node_duplicate,
    ScriptCreateResult: render_script_create,
    ScriptGetResult: render_script_get,
    ScriptListResult: render_script_list,
    ScriptDeleteResult: render_script_delete,
    ScriptSetResult: render_script_set,
    ScriptAttachResult: render_script_attach,
    ScriptValidateResult: render_script_validate,
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
