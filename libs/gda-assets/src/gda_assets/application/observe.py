"""Collect optional selected source/configuration facts around the import window."""

from dataclasses import replace

from gda_assets.application.ports import (
    GodotImportObservationPort,
    ObservationFilesPort,
    PortFailure,
)
from gda_assets.domain.artifacts import LoadObservation, PipelineFailure, PipelineResult
from gda_assets.domain.observations import (
    AssetDiskObservation,
    ContentObservations,
    CollectionRequest,
    ImportAssetFacts,
    compare_file,
    require_digest,
    declared_hash_mismatches,
)
from gda_assets.domain.recipe import AssetRecipe


def _read_facts(
    godot: GodotImportObservationPort, paths: list[str]
) -> dict[str, ImportAssetFacts]:
    published = godot.observe_import(paths)
    remaining = 128
    result = {}
    for item in published:
        if item.path not in paths or item.path in result:
            raise PortFailure(
                "invalid_observation",
                "Import observations must identify each selected path once",
            )
        artifacts = item.artifacts[:remaining]
        remaining -= len(artifacts)
        result[item.path] = replace(
            item,
            artifacts=artifacts,
            artifacts_omitted=item.artifacts_omitted
            + len(item.artifacts)
            - len(artifacts),
        )
    missing = set(paths) - result.keys()
    if missing:
        raise PortFailure(
            "invalid_observation",
            f"Import observations omitted selected paths: {', '.join(sorted(missing))}",
        )
    return result


def observe_before(
    result: ContentObservations,
    recipe: AssetRecipe,
    godot: GodotImportObservationPort,
    files: ObservationFilesPort,
) -> None:
    facts = _read_facts(godot, [f.target for f in recipe.files])
    for item in recipe.files:
        asset = AssetDiskObservation(item.target, item.references)
        result.assets.append(asset)
        asset.import_before = facts.get(item.target)
        asset.source_before = files.digest(item.target)
        require_digest(result, asset.source_before, item.target)
        if asset.import_before and asset.import_before.configuration:
            asset.configuration_before = files.digest(asset.import_before.configuration)
            require_digest(
                result, asset.configuration_before, asset.import_before.configuration
            )
    mismatches = declared_hash_mismatches(result)
    if mismatches:
        result.issues.extend(mismatches)
        raise PortFailure("declared_hash_mismatch", "; ".join(mismatches))
    _raise_incomplete(result)


def observe_after(
    result: ContentObservations,
    godot: GodotImportObservationPort,
    files: ObservationFilesPort,
    loads: list[LoadObservation],
) -> None:
    facts = _read_facts(godot, [a.path for a in result.assets])
    for asset in result.assets:
        asset.import_after = facts.get(asset.path)
        asset.source_after = files.digest(asset.path)
        if asset.import_after:
            if asset.import_after.artifacts_omitted:
                result.issues.append(
                    f"{asset.path}: {asset.import_after.artifacts_omitted} artifact paths omitted at the 128-path report limit"
                )
            if asset.import_after.configuration:
                asset.configuration_after = files.digest(
                    asset.import_after.configuration
                )
            asset.artifacts = [
                files.digest(path) for path in asset.import_after.artifacts
            ]
        asset.engine = next(
            (load.engine for load in loads if load.path == asset.path), None
        )
        if asset.engine is None:
            asset.unavailable.append(
                "Engine identity was not returned by a completed load operation"
            )
        if asset.import_after is None or asset.import_after.declared_importer is None:
            asset.unavailable.append("Importer declaration was not published")
        if (
            asset.import_after is None
            or asset.import_after.declared_source_file is None
        ):
            asset.unavailable.append("Source-file declaration was not published")
        require_digest(result, asset.source_after, asset.path)
        require_digest(result, asset.configuration_after, f"{asset.path} configuration")
        if not asset.artifacts:
            result.issues.append(
                f"{asset.path}: no import artifact paths were published"
            )
        for artifact in asset.artifacts:
            require_digest(result, artifact, artifact.path)
        compare_file(result, asset.source_before, asset.source_after)
        compare_file(result, asset.configuration_before, asset.configuration_after)
    # Re-read the covered set after all artifact reads. This detects movement
    # while a different selected file was being hashed, without claiming a
    # filesystem transaction or protection against unobserved ABA changes.
    covered = {
        digest.path: digest
        for asset in result.assets
        for digest in (asset.source_after, asset.configuration_after, *asset.artifacts)
        if digest is not None and digest.state == "observed"
    }
    for path, before in covered.items():
        after = files.digest(path)
        require_digest(result, after, path)
        compare_file(result, before, after)
    _raise_incomplete(result)
    result.status = "stable"


def _raise_incomplete(result: ContentObservations) -> None:
    if result.status == "changed":
        raise PortFailure(
            "observation_changed",
            "Selected input bytes changed during collection; see content_observations.changes",
        )
    if result.issues:
        raise PortFailure(
            "observation_incomplete",
            "Some selected disk/import facts could not be collected; see content_observations.issues",
        )


def finish_collection(
    pipeline: PipelineResult,
    request: CollectionRequest,
    godot: GodotImportObservationPort,
    files: ObservationFilesPort,
    *,
    import_attempted: bool,
) -> None:
    """Retain partial observations and preserve the original workflow failure."""
    result = pipeline.content_observations
    assert result is not None
    if import_attempted:
        try:
            observe_after(result, godot, files, pipeline.observations)
            if pipeline.failure is not None:
                result.status = "incomplete"
            else:
                pipeline.completed.append("observe")
        except (PortFailure, OSError) as exc:
            result.issues.append(str(exc))
            if pipeline.failure is None:
                pipeline.failure = PipelineFailure(
                    "observe",
                    exc.code if isinstance(exc, PortFailure) else "file_io_failed",
                    str(exc),
                    exc.cause if isinstance(exc, PortFailure) else None,
                )
    if pipeline.failure is not None and pipeline.failure.message not in result.issues:
        result.issues.append(pipeline.failure.message)
    if request.save_to is not None:
        try:
            files.save(result, request.save_to)
        except (PortFailure, OSError) as exc:
            if result.status == "stable":
                result.status = "incomplete"
            result.issues.append(str(exc))
            if pipeline.failure is None:
                pipeline.failure = PipelineFailure(
                    "save_observations", "observation_save_failed", str(exc)
                )
