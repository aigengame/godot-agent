"""Semantic admission for bounded reports supplied to the asset pipeline."""

import math
from collections.abc import Iterable, Sequence

from gda.commands.resource import ModelNode, ResourceInspectModelResult


_DETAIL_COMPONENT = {
    "surfaces": "mesh",
    "textures": "mesh",
    "bones": "skeleton",
    "skin_binds": "skin",
    "animations": "animation_player",
    "animation_tracks": "animation_player",
}


def _require_finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("model report numeric facts must be finite")
    if isinstance(value, dict):
        for item in value.values():
            _require_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_finite(item)


def _prefix_indices(items: Iterable[object], label: str) -> None:
    indices = [getattr(item, "index") for item in items]
    if indices != list(range(len(indices))):
        raise ValueError(f"{label} indices must be an exact zero-based prefix")


def _has_omission(
    omissions: set[tuple[str, str, str]], node_path: str, section: str
) -> bool:
    return (node_path, section, "detail_limit") in omissions


def _check_counted_prefix(
    count: int,
    items: Sequence[object],
    *,
    label: str,
    omitted: bool,
) -> None:
    if count < 0:
        raise ValueError(f"{label} count must be non-negative")
    _prefix_indices(items, label)
    if (
        len(items) > count
        or (omitted and len(items) >= count)
        or (not omitted and len(items) != count)
    ):
        raise ValueError(
            f"{label} records contradict declared count or omission coverage"
        )


def _component_present(node: ModelNode, section: str) -> bool:
    component = _DETAIL_COMPONENT[section]
    if component == "skin":
        return node.mesh is not None and node.mesh.skin is not None
    return getattr(node, component) is not None


def _is_full_node_locator(path: str) -> bool:
    if path == ".":
        return True
    return (
        bool(path)
        and not path.startswith("/")
        and ":" not in path
        and all(part not in ("", ".", "..") for part in path.split("/"))
    )


def validate_model_report(report: ResourceInspectModelResult) -> None:
    """Reject contradictions that make expectation coverage ambiguous."""
    raw = report.model_dump(mode="python")
    _require_finite(raw)

    paths = [node.path for node in report.nodes]
    if (
        not paths
        or paths[0] != report.subtree
        or not _is_full_node_locator(report.subtree)
        or any(not _is_full_node_locator(path) for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise ValueError("model report node paths must be unique exact locators")
    if report.subtree != "." and any(
        path != report.subtree and not path.startswith(report.subtree + "/")
        for path in paths
    ):
        raise ValueError("model report nodes must lie within the selected subtree")

    summary = report.summary
    if (
        min(summary.node_count, summary.mesh_instance_count, summary.unique_mesh_count)
        < 0
    ):
        raise ValueError("model report summary counts must be non-negative")
    mesh_count = sum(node.mesh is not None for node in report.nodes)
    if summary.node_count != len(report.nodes):
        raise ValueError("model report summary node_count contradicts nodes")
    if summary.mesh_instance_count != mesh_count:
        raise ValueError("model report summary mesh_instance_count contradicts nodes")
    if not 0 <= summary.unique_mesh_count <= mesh_count:
        raise ValueError("model report unique_mesh_count contradicts mesh instances")
    if (summary.unique_mesh_count == 0) != (mesh_count == 0):
        raise ValueError("model report unique_mesh_count contradicts mesh instances")
    if report.bounds is not None:
        if any(size < 0 for size in report.bounds.size):
            raise ValueError("model report bounds size must be non-negative")
        if mesh_count == 0:
            raise ValueError("model report bounds require a visited mesh instance")

    omission_keys = [
        (item.node_path, item.section, item.reason) for item in report.omissions
    ]
    omissions = set(omission_keys)
    if report.truncated != bool(omissions):
        raise ValueError("model report truncated flag contradicts omission coverage")
    if len(omissions) != len(omission_keys):
        raise ValueError("model report omission locators must be unique")
    nodes = {node.path: node for node in report.nodes}
    for omission in report.omissions:
        if omission.section == "nodes":
            if omission.reason != "node_limit" or omission.node_path != report.subtree:
                raise ValueError("nodes omission must locate the selected subtree")
            continue
        if (
            omission.section not in _DETAIL_COMPONENT
            or omission.reason != "detail_limit"
        ):
            raise ValueError("model report contains an unrecognized omission")
        node = nodes.get(omission.node_path)
        if node is None or not _component_present(node, omission.section):
            raise ValueError(
                "model report omission does not locate a matching component"
            )

    for node in report.nodes:
        if node.mesh is not None:
            mesh = node.mesh
            _check_counted_prefix(
                mesh.surface_count,
                mesh.surfaces,
                label="surfaces",
                omitted=_has_omission(omissions, node.path, "surfaces"),
            )
            if mesh.skin is not None:
                skin = mesh.skin
                if (skin.resolved_skeleton_path is None) == (
                    skin.unresolved_reason is None
                ):
                    raise ValueError(
                        "skin skeleton resolution facts contradict each other"
                    )
                _check_counted_prefix(
                    skin.bind_count,
                    skin.binds,
                    label="skin binds",
                    omitted=_has_omission(omissions, node.path, "skin_binds"),
                )
                for bind in skin.binds:
                    if (bind.resolved_bone_index is None) == (
                        bind.unresolved_reason is None
                    ):
                        raise ValueError(
                            "skin bind resolution facts contradict each other"
                        )
                    if (
                        bind.resolved_bone_index is not None
                        and bind.resolved_bone_index < 0
                    ):
                        raise ValueError(
                            "resolved skin bind index must be non-negative"
                        )
        if node.skeleton is not None:
            _check_counted_prefix(
                node.skeleton.bone_count,
                node.skeleton.bones,
                label="bones",
                omitted=_has_omission(omissions, node.path, "bones"),
            )
        if node.animation_player is not None:
            player = node.animation_player
            if (player.resolved_root_path is None) == (
                player.unresolved_reason is None
            ):
                raise ValueError(
                    "animation root resolution facts contradict each other"
                )
            animations_omitted = _has_omission(omissions, node.path, "animations")
            if (
                player.animation_count < 0
                or len(player.animations) > player.animation_count
            ):
                raise ValueError("animations contradict declared count")
            if animations_omitted:
                if len(player.animations) >= player.animation_count:
                    raise ValueError(
                        "animations omission requires a short emitted prefix"
                    )
            elif len(player.animations) != player.animation_count:
                raise ValueError(
                    "animations records contradict declared count or omission coverage"
                )
            names = [animation.name for animation in player.animations]
            if len(names) != len(set(names)):
                raise ValueError("animation names must be unique within a player")
            tracks_omitted = _has_omission(omissions, node.path, "animation_tracks")
            any_short = False
            for animation in player.animations:
                _prefix_indices(animation.tracks, "animation tracks")
                if (
                    animation.track_count < 0
                    or len(animation.tracks) > animation.track_count
                ):
                    raise ValueError("animation tracks contradict declared count")
                any_short |= len(animation.tracks) < animation.track_count
                if (
                    not tracks_omitted
                    and len(animation.tracks) != animation.track_count
                ):
                    raise ValueError("animation tracks lack matching omission coverage")
                if animation.length < 0 or animation.loop_mode not in (0, 1, 2):
                    raise ValueError("animation timing facts are invalid")
            if tracks_omitted and not any_short:
                raise ValueError(
                    "animation_tracks omission requires at least one short track prefix"
                )

    for node in report.nodes:
        if node.mesh is not None:
            for surface in node.mesh.surfaces:
                for count in (
                    surface.vertex_count,
                    surface.index_count,
                    surface.triangle_count,
                ):
                    if count is not None and count < 0:
                        raise ValueError("surface counts must be non-negative")
        if node.animation_player is not None:
            for animation in node.animation_player.animations:
                for track in animation.tracks:
                    if track.status == "resolved":
                        if (
                            track.target_node_path is None
                            or track.resolution_scope is None
                            or track.reason is not None
                        ):
                            raise ValueError(
                                "resolved animation track facts contradict their status"
                            )
                    elif track.resolution_scope is not None or not track.reason:
                        raise ValueError(
                            "unresolved animation track facts contradict their status"
                        )
