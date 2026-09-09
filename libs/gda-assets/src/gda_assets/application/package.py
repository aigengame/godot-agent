"""Apply project expectations to resources in one isolated package snapshot."""

from gda_assets.application.check import check_model
from gda_assets.application.package_ports import GodotPackagePort, PackageFilesPort
from gda_assets.application.ports import PortFailure
from gda_assets.domain.artifacts import PipelineFailure
from gda_assets.domain.expectations import Expectation
from gda_assets.domain.package import (
    PackageCheckRequest,
    PackageCheckResult,
    evaluate_exclusions,
    package_verdict,
    validate_package_request,
)


def check_package(
    request: PackageCheckRequest,
    conditions: tuple[Expectation, ...],
    *,
    godot: GodotPackagePort,
    files: PackageFilesPort,
) -> PackageCheckResult:
    result = PackageCheckResult(request)
    stage = "validate"
    try:
        try:
            validate_package_request(request)
        except ValueError as exc:
            raise PortFailure("invalid_package", str(exc)) from exc
        result.completed.append(stage)
        stage = "stage"
        result.package = files.snapshot(request.package)
        result.completed.append(stage)
        stage = "presence"
        # Observe the engine even when no exclusions were requested. This also
        # retains the inspecting engine if the subsequent model load fails.
        selected = request.exclude or (request.path,)
        result.presence = godot.resource_presence(result.package.path, selected)
        observed = result.presence.resources
        if len(observed) != len(selected) or {r.path for r in observed} != set(
            selected
        ):
            raise PortFailure(
                "invalid_package_observation",
                "Package presence did not cover the selected paths",
            )
        result.exclusions = evaluate_exclusions(request.exclude, observed)
        result.completed.append(stage)
        stage = "inspect"
        result.inspection = godot.inspect_model(
            result.package.path,
            request.path,
            subtree=request.subtree,
            max_nodes=request.max_nodes,
            max_items=request.max_items,
        )
        facts = result.inspection.model
        if (
            result.inspection.engine != result.presence.engine
            or facts.resource != request.path
            or facts.subtree != request.subtree
        ):
            raise PortFailure(
                "invalid_package_observation",
                "Model inspection differs from the selected package scope or engine",
            )
        result.completed.append(stage)
        stage = "evaluate"
        # The existing workflow owns expectation semantics and verdict precedence.
        # Its supplied_report origin describes this in-process handoff; the outer
        # result records that the facts came from editor-based PCK inspection.
        result.check = check_model(conditions, report=facts)
        if result.check.failure is not None:
            failure = result.check.failure
            raise PortFailure(failure.code, failure.message, cause=failure.cause)
        if result.check.verdict is None:
            raise PortFailure(
                "invalid_package_observation", "Model evaluation returned no verdict"
            )
        result.verdict = package_verdict(result.check.verdict, result.exclusions)
        result.completed.append(stage)
    except PortFailure as exc:
        result.failure = PipelineFailure(stage, exc.code, str(exc), exc.cause)
    finally:
        if result.package is not None:
            try:
                files.remove(result.package)
                result.cleanup.staging_removed = True
                result.completed.append("cleanup")
            except (PortFailure, OSError) as exc:
                result.cleanup.issues.append(str(exc))
                if result.failure is None:
                    result.failure = PipelineFailure(
                        "cleanup", "package_cleanup_failed", str(exc)
                    )
    return result
