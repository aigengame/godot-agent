"""Compare bounded Godot observations, not artistic identity or equivalence."""

from dataclasses import asdict
from typing import Any, Iterable

from gda_assets.domain.model import (
    MaterialFacts,
    ModelFacts,
    NodeFacts,
    TrackFacts,
    ModelComparison,
    ModelChange,
    IncompleteSection,
    ComparedResources,
)


def _change(
    changes: list[dict[str, Any]],
    section: str,
    location: dict[str, Any],
    kind: str,
    before: Any,
    after: Any,
) -> None:
    changes.append(
        {
            "section": section,
            "location": location,
            "kind": kind,
            "before": before,
            "after": after,
        }
    )


def _omissions(*facts: ModelFacts) -> list[dict[str, Any]]:
    entries = {(section, node) for fact in facts for node, section in fact.omissions}
    return [
        {
            "section": section,
            "node": node,
            "reason": "observation omitted",
        }
        for section, node in sorted(entries, key=lambda item: (item[0], item[1] or ""))
    ]


def _incomplete(facts: ModelFacts, section: str, node: str | None = None) -> bool:
    return facts.incomplete(section, node)


def _compare_value(
    changes: list[dict[str, Any]],
    section: str,
    location: dict[str, Any],
    before: Any,
    after: Any,
) -> None:
    if before != after:
        _change(changes, section, location, "changed", before, after)


def _compare_material(
    changes: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    before_facts: ModelFacts,
    after_facts: ModelFacts,
    node: str,
    surface: int,
    before: MaterialFacts | None,
    after: MaterialFacts | None,
) -> None:
    location = {"node": node, "surface": surface}
    if before is None or after is None:
        if before != after:
            _change(
                changes,
                "materials",
                location,
                "added" if before is None else "removed",
                asdict(before) if before else None,
                asdict(after) if after else None,
            )
        return
    before_material = (before.type, before.name, before.source)
    after_material = (after.type, after.name, after.source)
    _compare_value(changes, "materials", location, before_material, after_material)
    if before.path is None or after.path is None:
        _add_incomplete(incomplete, "materials", node, "material path unavailable")
    elif before.path != after.path:
        _change(changes, "materials", location, "changed", before.path, after.path)
    if _incomplete(before_facts, "textures", node) or _incomplete(
        after_facts, "textures", node
    ):
        return
    if not before.textures_available or not after.textures_available:
        _add_incomplete(incomplete, "textures", node, "texture details unavailable")
        return
    before_textures = {item[0]: item[1:] for item in before.textures}
    after_textures = {item[0]: item[1:] for item in after.textures}
    for role in sorted(before_textures.keys() | after_textures.keys()):
        old = before_textures.get(role)
        new = after_textures.get(role)
        if old is not None and new is not None:
            _compare_value(
                changes,
                "textures",
                {**location, "texture": role},
                old[0],
                new[0],
            )
            if old[1] is None or new[1] is None:
                _add_incomplete(
                    incomplete, "textures", node, "texture path unavailable"
                )
            elif old[1] != new[1]:
                _change(
                    changes,
                    "textures",
                    {**location, "texture": role},
                    "changed",
                    old[1],
                    new[1],
                )
        elif old != new:
            _change(
                changes,
                "textures",
                {**location, "texture": role},
                "added" if old is None else "removed",
                old,
                new,
            )


def _compare_surfaces(
    changes: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    before: ModelFacts,
    after: ModelFacts,
    old: NodeFacts,
    new: NodeFacts,
) -> None:
    if _incomplete(before, "surfaces", old.path) or _incomplete(
        after, "surfaces", new.path
    ):
        return
    _compare_value(
        changes,
        "surfaces",
        {"node": old.path, "field": "count"},
        old.surface_count,
        new.surface_count,
    )
    old_items = {item.index: item for item in old.surfaces}
    new_items = {item.index: item for item in new.surfaces}
    for index in sorted(old_items.keys() | new_items.keys()):
        left = old_items.get(index)
        right = new_items.get(index)
        location = {"node": old.path, "surface": index}
        if left is None or right is None:
            _change(
                changes,
                "surfaces",
                location,
                "added" if left is None else "removed",
                asdict(left) if left else None,
                asdict(right) if right else None,
            )
            continue
        old_reason = left.geometry.get("counts_unavailable_reason")
        new_reason = right.geometry.get("counts_unavailable_reason")
        if old_reason or new_reason:
            _add_incomplete(
                incomplete,
                "geometry",
                old.path,
                str(old_reason or new_reason),
            )
        old_geometry = {
            key: value
            for key, value in left.geometry.items()
            if key != "counts_unavailable_reason"
            and value is not None
            and right.geometry.get(key) is not None
        }
        new_geometry = {key: right.geometry[key] for key in old_geometry}
        _compare_value(changes, "surfaces", location, old_geometry, new_geometry)
        _compare_material(
            changes,
            incomplete,
            before,
            after,
            old.path,
            index,
            left.material,
            right.material,
        )


def _compare_indexed(
    changes: list[dict[str, Any]],
    section: str,
    node: str,
    before: Iterable[Any],
    after: Iterable[Any],
    location_key: str,
) -> None:
    old_items = {item.index: item for item in before}
    new_items = {item.index: item for item in after}
    for index in sorted(old_items.keys() | new_items.keys()):
        left = old_items.get(index)
        right = new_items.get(index)
        location = {"node": node, location_key: index}
        if left != right:
            _change(
                changes,
                section,
                location,
                "added" if left is None else "removed" if right is None else "changed",
                asdict(left) if left else None,
                asdict(right) if right else None,
            )


def _compare_tracks(
    changes: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    node: str,
    name: str,
    before: tuple[TrackFacts, ...],
    after: tuple[TrackFacts, ...],
) -> None:
    old_items = {item.index: item for item in before}
    new_items = {item.index: item for item in after}
    for index in sorted(old_items.keys() | new_items.keys()):
        left = old_items.get(index)
        right = new_items.get(index)
        if (
            left is not None
            and right is not None
            and (left.status == "unavailable" or right.status == "unavailable")
        ):
            _add_incomplete(
                incomplete,
                "animation_tracks",
                node,
                left.reason or right.reason or "track details unavailable",
            )
            before_known = (left.type, left.path, left.enabled)
            after_known = (right.type, right.path, right.enabled)
            _compare_value(
                changes,
                "tracks",
                {"node": node, "animation": name, "track": index},
                before_known,
                after_known,
            )
        elif left != right:
            _change(
                changes,
                "tracks",
                {"node": node, "animation": name, "track": index},
                "added" if left is None else "removed" if right is None else "changed",
                asdict(left) if left else None,
                asdict(right) if right else None,
            )


def _compare_animations(
    changes: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    before: ModelFacts,
    after: ModelFacts,
    old: NodeFacts,
    new: NodeFacts,
) -> None:
    if _incomplete(before, "animations", old.path) or _incomplete(
        after, "animations", new.path
    ):
        return
    old_items = {item.name: item for item in old.animations}
    new_items = {item.name: item for item in new.animations}
    for name in sorted(old_items.keys() | new_items.keys()):
        left = old_items.get(name)
        right = new_items.get(name)
        location = {"node": old.path, "animation": name}
        if left is None or right is None:
            _change(
                changes,
                "animations",
                location,
                "added" if left is None else "removed",
                asdict(left) if left else None,
                asdict(right) if right else None,
            )
            continue
        _compare_value(
            changes,
            "animations",
            location,
            (left.length, left.loop_mode, left.track_count),
            (right.length, right.loop_mode, right.track_count),
        )
        if not (
            _incomplete(before, "animation_tracks", old.path)
            or _incomplete(after, "animation_tracks", new.path)
        ):
            _compare_tracks(
                changes, incomplete, old.path, name, left.tracks, right.tracks
            )


def compare_models(before: ModelFacts, after: ModelFacts) -> ModelComparison:
    """Compare like-for-like observations without treating omitted data as absence."""
    reasons = []
    if before.subtree != after.subtree:
        reasons.append(f"subtree differs: {before.subtree} != {after.subtree}")
    if before.measurement != after.measurement:
        reasons.append(
            f"measurement differs: {before.measurement} != {after.measurement}"
        )
    if before.engine[:2] != after.engine[:2]:
        reasons.append(
            f"engine major/minor differs: {'.'.join(map(str, before.engine[:2]))} != "
            f"{'.'.join(map(str, after.engine[:2]))}"
        )
    incomplete = _omissions(before, after)
    result: dict[str, Any] = {
        "status": "non_comparable" if reasons else "comparable",
        "reasons": reasons,
        "resources": {"before": before.resource, "after": after.resource},
        "changes": [],
        "incomplete_sections": incomplete,
    }
    if reasons:
        return _comparison_result(result)

    changes: list[dict[str, Any]] = result["changes"]
    old_nodes = {node.path: node for node in before.nodes}
    new_nodes = {node.path: node for node in after.nodes}
    common = sorted(old_nodes.keys() & new_nodes.keys())
    for path in common:
        old = old_nodes[path]
        new = new_nodes[path]
        _compare_value(
            changes,
            "nodes",
            {"node": path},
            {"type": old.type, "transform": old.transform},
            {"type": new.type, "transform": new.transform},
        )
        _compare_surfaces(changes, incomplete, before, after, old, new)
        if not (
            _incomplete(before, "bones", path) or _incomplete(after, "bones", path)
        ):
            _compare_value(
                changes,
                "bones",
                {"node": path, "field": "count"},
                old.bone_count,
                new.bone_count,
            )
            _compare_indexed(changes, "bones", path, old.bones, new.bones, "bone")
        if old.skin_unavailable or new.skin_unavailable:
            _add_incomplete(
                incomplete,
                "skin",
                path,
                old.skin_unavailable or new.skin_unavailable or "skin unavailable",
            )
        else:
            _compare_value(
                changes,
                "skin",
                {"node": path},
                (old.skin_present, old.skin_unavailable, old.skeleton),
                (new.skin_present, new.skin_unavailable, new.skeleton),
            )
        if not (
            _incomplete(before, "skin_binds", path)
            or _incomplete(after, "skin_binds", path)
        ):
            _compare_value(
                changes,
                "binds",
                {"node": path, "field": "count"},
                old.bind_count,
                new.bind_count,
            )
            old_binds = {item.index: item for item in old.binds}
            new_binds = {item.index: item for item in new.binds}
            for index in sorted(old_binds.keys() | new_binds.keys()):
                left = old_binds.get(index)
                right = new_binds.get(index)
                if (
                    left is not None
                    and right is not None
                    and (left.bone_index is None or right.bone_index is None)
                ):
                    _add_incomplete(
                        incomplete,
                        "skin_binds",
                        path,
                        left.reason or right.reason or "bind target unavailable",
                    )
                elif left != right:
                    _change(
                        changes,
                        "binds",
                        {"node": path, "bind": index},
                        "added"
                        if left is None
                        else "removed"
                        if right is None
                        else "changed",
                        asdict(left) if left else None,
                        asdict(right) if right else None,
                    )
        _compare_animations(changes, incomplete, before, after, old, new)

    nodes_complete = not (_incomplete(before, "nodes") or _incomplete(after, "nodes"))
    if nodes_complete:
        for path in sorted(old_nodes.keys() - new_nodes.keys()):
            _change(
                changes,
                "nodes",
                {"node": path},
                "removed",
                asdict(old_nodes[path]),
                None,
            )
        for path in sorted(new_nodes.keys() - old_nodes.keys()):
            _change(
                changes, "nodes", {"node": path}, "added", None, asdict(new_nodes[path])
            )
    if nodes_complete:
        for name in sorted(before.counts.keys() | after.counts.keys()):
            _compare_value(
                changes,
                "counts",
                {"count": name},
                before.counts.get(name),
                after.counts.get(name),
            )
        _compare_value(changes, "bounds", {}, before.bounds, after.bounds)
    if result["incomplete_sections"]:
        result["status"] = "partial"
    return _comparison_result(result)


def _add_incomplete(
    incomplete: list[dict[str, Any]], section: str, node: str, reason: str
) -> None:
    item = {"section": section, "node": node, "reason": reason}
    if item not in incomplete:
        incomplete.append(item)
        incomplete.sort(key=lambda entry: (entry["section"], entry.get("node", "")))


def _comparison_result(result: dict[str, Any]) -> ModelComparison:
    return ModelComparison(
        status=result["status"],
        reasons=result["reasons"],
        resources=ComparedResources(**result["resources"]),
        changes=[ModelChange(**change) for change in result["changes"]],
        incomplete_sections=[
            IncompleteSection(**section) for section in result["incomplete_sections"]
        ],
    )
