"""Asset Pipeline host adapter backed by returning gda resource operations."""

from pathlib import Path
from typing import NoReturn

from gda_assets.api import ImportOutcome, LoadObservation, PortFailure

from gda.commands.resource import (
    ResourceImportParams,
    run_resource_import_operation,
    run_resource_load_operation,
)
from gda.errors import Failure, containment_refusal


def validate_asset_targets(project: Path, targets: list[str]) -> Failure | None:
    """Apply gda's project ownership gate before the workflow installs files."""
    for target in targets:
        refusal = containment_refusal(target, project)
        if refusal is not None:
            return refusal
    return None


class GdaGodotAssetPort:
    """Implement the gda-assets Godot port without nested CLI invocation."""

    def __init__(self, project: Path, godot: str | None = None) -> None:
        self._project = project
        self._godot = godot
        self.last_failure: Failure | None = None

    def _raise(self, failure: Failure) -> NoReturn:
        self.last_failure = failure
        if not failure.child_stderr and failure.error.diagnostics:
            failure.child_stderr = failure.error.diagnostics
        raise PortFailure(
            failure.error.code,
            failure.error.message,
            cause=failure.error.model_dump(mode="json", exclude_none=True),
        )

    def import_assets(self, paths: list[str]) -> ImportOutcome:
        outcome = run_resource_import_operation(
            self._project,
            ResourceImportParams(assets=paths),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        facts = outcome.model_dump(mode="json")
        if outcome.summary.failed:
            raise PortFailure(
                "operation_failed",
                f"Godot failed to import {outcome.summary.failed} requested asset(s)",
                cause=facts,
            )
        return ImportOutcome(facts=facts)

    def check_load(self, path: str) -> LoadObservation:
        outcome = run_resource_load_operation(self._project, path, godot=self._godot)
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return LoadObservation(
            path=outcome.path,
            resource_type=outcome.resource_type,
            texture_size=(
                (outcome.texture_size[0], outcome.texture_size[1])
                if outcome.texture_size is not None
                else None
            ),
            scene_node_count=outcome.scene_node_count,
            engine=outcome.engine_version.model_dump(mode="json"),
        )
