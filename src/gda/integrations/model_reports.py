"""Translate Godot's imported-resource report into Asset Pipeline model facts."""

from pathlib import Path

from gda_assets.api import (
    AnimationFacts,
    BindFacts,
    BoneFacts,
    MaterialFacts,
    ModelFacts,
    NodeFacts,
    PortFailure,
    SurfaceFacts,
    TrackFacts,
)

from gda.commands.resource import ModelTransform, ResourceInspectModelResult
from gda.integrations.model_report_validation import validate_model_report


def _transform(value: ModelTransform | None) -> tuple[float, ...] | None:
    if value is None:
        return None
    return tuple(value.origin) + tuple(
        component for column in value.basis for component in column
    )


def project_model_report(report: ResourceInspectModelResult) -> ModelFacts:
    """Preserve fact scope and coverage while removing native model dependencies."""
    validate_model_report(report)
    nodes = []
    for node in report.nodes:
        mesh, skeleton, player = node.mesh, node.skeleton, node.animation_player
        skin = mesh.skin if mesh else None
        surfaces = []
        for surface in mesh.surfaces if mesh else []:
            material = surface.material
            surfaces.append(
                SurfaceFacts(
                    surface.index,
                    surface.model_dump(exclude={"index", "material"}),
                    MaterialFacts(
                        material.resource.type,
                        material.resource.name,
                        material.resource.path,
                        material.source,
                        tuple(
                            (t.role, t.resource.type, t.resource.path)
                            for t in material.textures
                        ),
                        material.textures_unavailable_reason is None,
                    )
                    if material
                    else None,
                )
            )
        nodes.append(
            NodeFacts(
                path=node.path,
                type=node.type,
                transform=_transform(node.resource_transform),
                surface_count=mesh.surface_count if mesh else None,
                surfaces=tuple(surfaces),
                bone_count=skeleton.bone_count if skeleton else None,
                bones=tuple(
                    BoneFacts(b.index, b.name, b.parent, _transform(b.rest) or ())
                    for b in skeleton.bones
                )
                if skeleton
                else (),
                skin_present=skin is not None,
                skin_unavailable=mesh.skin_unavailable_reason if mesh else None,
                skeleton=skin.resolved_skeleton_path if skin else None,
                bind_count=skin.bind_count if skin else None,
                binds=tuple(
                    BindFacts(b.index, b.resolved_bone_index, b.unresolved_reason)
                    for b in skin.binds
                )
                if skin
                else (),
                animation_count=player.animation_count if player else None,
                animations=tuple(
                    AnimationFacts(
                        a.name,
                        a.length,
                        a.loop_mode,
                        a.track_count,
                        tuple(
                            TrackFacts(
                                t.index,
                                t.type,
                                t.path,
                                t.enabled,
                                t.target_node_path,
                                t.bone_name,
                                t.status,
                                t.resolution_scope,
                                t.reason,
                            )
                            for t in a.tracks
                        ),
                    )
                    for a in player.animations
                )
                if player
                else (),
            )
        )
    return ModelFacts(
        resource=report.path,
        subtree=report.subtree,
        engine=(report.engine_version.major, report.engine_version.minor),
        measurement=(report.measurement.coordinate_space, report.measurement.geometry),
        nodes=tuple(nodes),
        counts=report.summary.model_dump(),
        bounds=report.bounds.model_dump(mode="json") if report.bounds else None,
        omissions=tuple((o.node_path, o.section) for o in report.omissions),
    )


def read_model_report(path: Path) -> ModelFacts:
    """A saved report is caller-supplied data, not a fresh engine observation."""
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("model report exceeds 16 MiB")
        raw = path.read_text(encoding="utf-8")
        # Validate JSON types before Python tuples represent engine vectors.
        report = ResourceInspectModelResult.model_validate_json(raw, strict=True)
        return project_model_report(report)
    except (OSError, ValueError) as exc:
        raise PortFailure("invalid_report", f"{path}: {exc}") from exc
