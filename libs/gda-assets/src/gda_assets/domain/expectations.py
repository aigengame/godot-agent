"""Project expectations and their interpretation over bounded model facts."""

from dataclasses import asdict, dataclass
import math
from typing import Any

from gda_assets.domain.model import CheckResult, ModelFacts, NodeFacts, Verdict


@dataclass(frozen=True)
class Expectation:
    id: str
    kind: str
    node: str | None = None
    options: dict[str, Any] | None = None


def _in_range(value, options) -> bool:
    return ("min" not in options or value >= options["min"]) and (
        "max" not in options or value <= options["max"]
    )


def evaluate(
    expectations: tuple[Expectation, ...], facts: ModelFacts
) -> list[CheckResult]:
    nodes = {node.path: node for node in facts.nodes}
    results = []
    for condition in expectations:
        node = nodes.get(condition.node or "")
        expected = condition.options or {}
        location: dict[str, Any] = {"resource": facts.resource}
        verdict: Verdict = "fail"
        actual: Any = None
        reason = "Required node and type"
        if condition.kind in {"count", "dimensions"}:
            location["subtree"] = facts.subtree
            if condition.kind == "count":
                actual = facts.counts[expected["metric"]]
                passes = _in_range(actual, expected)
                reason = "Count over the inspected subtree"
            else:
                actual = facts.bounds["size"] if facts.bounds else None
                passes = actual is not None and all(
                    _in_range(
                        actual[i], {key: values[i] for key, values in expected.items()}
                    )
                    for i in range(3)
                )
                reason = (
                    "Resource-space static mesh bounds; no pose or collision inference"
                )
            verdict = (
                "insufficient"
                if facts.incomplete("nodes")
                else "pass"
                if passes
                else "fail"
            )
            if facts.incomplete("nodes"):
                reason = "Node limit omitted part of the subtree; aggregate facts are partial"
        else:
            location["node"] = condition.node
            if node is None:
                if facts.incomplete("nodes") or not facts.includes(
                    condition.node or "."
                ):
                    verdict = "insufficient"
                    reason = "Required node is outside observed coverage"
            elif condition.kind == "node":
                actual = {"type": node.type}
                verdict = "pass" if not expected or actual == expected else "fail"
            else:
                verdict, actual, reason = _check_detail(
                    condition.kind, expected, node, facts
                )
            for key in ("surface", "bind", "animation", "track"):
                if key in expected:
                    location[key] = expected[key]
        results.append(
            CheckResult(condition.id, verdict, location, expected, actual, reason)
        )
    return results


def validate_node_path(path: str) -> None:
    if path != "." and (
        not path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or ":" in path
        or "\\" in path
    ):
        raise ValueError("node must be an exact resource-relative path, or .")


def validate_conditions(conditions: tuple[Expectation, ...]) -> None:
    for condition in conditions:
        if condition.node is not None:
            validate_node_path(condition.node)
        options = condition.options or {}
        for key in ("skeleton", "target"):
            if key in options:
                validate_node_path(options[key])
        if condition.kind in {"count", "dimensions"}:
            if "min" not in options and "max" not in options:
                raise ValueError("range checks require min or max")
            lower, upper = options.get("min"), options.get("max")
            values = [v for v in (lower, upper) if v is not None]
            if condition.kind == "dimensions":
                values = [number for vector in values for number in vector]
            if any(not math.isfinite(v) or v < 0 for v in values):
                raise ValueError("range bounds must be finite and nonnegative")
            if lower is not None and upper is not None:
                if condition.kind == "dimensions":
                    ordered = all(low <= high for low, high in zip(lower, upper))
                else:
                    ordered = lower <= upper
                if not ordered:
                    raise ValueError("min must not exceed max")


def _missing(facts: ModelFacts, node: str, section: str, detail: str):
    return (
        "insufficient" if facts.incomplete(section, node) else "fail",
        None,
        f"Required {detail} was not observed"
        + (
            f"; {section} records were omitted"
            if facts.incomplete(section, node)
            else ""
        ),
    )


def _check_detail(
    kind: str, expected: dict[str, Any], node: NodeFacts, facts: ModelFacts
) -> tuple[Verdict, Any, str]:
    if kind == "material":
        surface = next(
            (s for s in node.surfaces if s.index == expected["surface"]), None
        )
        if surface is None:
            return _missing(facts, node.path, "surfaces", "surface")
        material = surface.material
        if material is None:
            return "fail", None, "Surface has no effective material"
        actual = {"name": material.name, "path": material.path, "type": material.type}
        if "name" in expected and expected["name"] != material.name:
            return "fail", actual, "Material name differs"
        if "path" in expected:
            if material.path is None:
                return "insufficient", actual, "Material resource path is unavailable"
            if expected["path"] != material.path:
                return "fail", actual, "Material path differs"
        return (
            "pass",
            actual,
            "Required effective material occupies the selected surface",
        )
    if kind == "bone":
        bone = next((b for b in node.bones if b.name == expected["name"]), None)
        if bone is None:
            return _missing(facts, node.path, "bones", "bone")
        return (
            "pass",
            {"index": bone.index, "name": bone.name},
            "Required skeleton bone exists",
        )
    if kind == "skin_bind":
        if node.skin_unavailable:
            return "insufficient", None, node.skin_unavailable
        if not node.skin_present:
            return "fail", None, "Mesh has no explicit skin"
        bind = next((b for b in node.binds if b.index == expected["bind"]), None)
        if bind is None:
            return _missing(facts, node.path, "skin_binds", "skin bind")
        actual = {
            "skeleton": node.skeleton,
            "bone_index": bind.bone_index,
            "reason": bind.reason,
        }
        if bind.reason or node.skeleton != expected["skeleton"]:
            return (
                "fail",
                actual,
                "Skin bind is unresolved or targets a different skeleton",
            )
        skeleton = next((n for n in facts.nodes if n.path == node.skeleton), None)
        bone = (
            next((b for b in skeleton.bones if b.index == bind.bone_index), None)
            if skeleton
            else None
        )
        if bone is None:
            return (
                "insufficient",
                actual,
                "Resolved bone name is outside observed skeleton detail",
            )
        actual["bone"] = bone.name
        return (
            ("pass" if bone.name == expected["bone"] else "fail"),
            actual,
            "Explicit skin bind target; no pose sampling",
        )
    animation = next(
        (a for a in node.animations if a.name == expected["animation"]), None
    )
    if animation is None:
        return _missing(facts, node.path, "animations", "animation")
    track = next((t for t in animation.tracks if t.index == expected["track"]), None)
    if track is None:
        return _missing(facts, node.path, "animation_tracks", "animation track")
    actual = asdict(track)
    if track.status == "unavailable":
        return "insufficient", actual, track.reason or "Track resolution unavailable"
    matches = (
        track.status == "resolved"
        and track.target == expected["target"]
        and ("bone" not in expected or track.bone == expected["bone"])
    )
    return (
        ("pass" if matches else "fail"),
        actual,
        "Static animation target binding; successful playback is not established",
    )
