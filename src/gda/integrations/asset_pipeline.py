"""Asset Pipeline host adapter backed by returning gda resource operations."""

from pathlib import Path
from typing import NoReturn

from gda_assets.api import (
    ImportOutcome,
    LoadObservation,
    PortFailure,
    ModelFacts,
    ImportAssetFacts,
    CaptureObservation,
    ImportedContent,
    InstanceContent,
    ModelContent,
    SessionState,
    StopObservation,
    StartObservation,
    ReadyObservation,
)

from gda.commands.daemon import (
    run_daemon_start_operation,
    run_daemon_status_operation,
    run_daemon_stop_operation,
    run_daemon_wait_ready_operation,
)
from gda.commands.game import (
    GameInspectModelContentParams,
    run_game_inspect_model_content_operation,
)
from gda.commands.resource import (
    ResourceImportParams,
    ResourceInspectModelContentParams,
    ResourceInspectModelParams,
    run_resource_inspect_model_content_operation,
    run_resource_inspect_model_operation,
    run_resource_import_operation,
    run_resource_load_operation,
)
from gda.commands.screen import ScreenCaptureParams, run_screen_capture_operation
from gda.errors import Failure, containment_refusal
from gda.model_content import ModelContent as NativeModelContent


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
        if self.last_failure is None:
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

    def observe_import(self, paths: list[str]) -> list[ImportAssetFacts]:
        outcome = run_resource_import_operation(
            self._project,
            ResourceImportParams(assets=paths, dry_run=True),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            # A best-effort post-failure observation must not replace the native
            # import/load failure already retained for the caller.
            if self.last_failure is None:
                self._raise(outcome)
            raise PortFailure(outcome.error.code, outcome.error.message)
        return [
            ImportAssetFacts(
                path=item.path,
                cache_status=item.status,
                configuration=item.sidecar,
                artifacts=tuple(item.dest_files),
                declared_importer=item.declared_importer,
                declared_source_file=item.declared_source_file,
            )
            for item in outcome.assets
        ]

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

    def inspect_model(
        self, path: str, *, subtree: str, max_nodes: int, max_items: int
    ) -> ModelFacts:
        from gda.integrations.model_reports import project_model_report

        outcome = run_resource_inspect_model_operation(
            self._project,
            ResourceInspectModelParams(
                path=path, subtree=subtree, max_nodes=max_nodes, max_items=max_items
            ),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        try:
            return project_model_report(outcome)
        except ValueError as exc:
            raise PortFailure("invalid_observation", str(exc)) from exc

    @staticmethod
    def _content(content: NativeModelContent) -> ModelContent:
        return ModelContent(
            measurement=content.measurement,
            engine=content.engine_version.string,
            complete=content.complete,
            digest=content.digest,
            nodes=content.nodes,
            surfaces=content.surfaces,
            vertices=content.vertices,
            unsupported=tuple(content.unsupported),
            omitted=tuple(content.omitted),
        )

    def inspect_content(
        self, path: str, *, max_nodes: int, max_vertices: int
    ) -> ImportedContent:
        outcome = run_resource_inspect_model_content_operation(
            self._project,
            ResourceInspectModelContentParams(
                path=path, max_nodes=max_nodes, max_vertices=max_vertices
            ),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return ImportedContent(outcome.path, self._content(outcome.content))

    def status(self) -> SessionState:
        outcome = run_daemon_status_operation(self._project)
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return SessionState(
            outcome.running, outcome.pid, outcome.windowed, outcome.session_id
        )

    def stop(self) -> StopObservation:
        outcome = run_daemon_stop_operation(self._project)
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return StopObservation(stopped=outcome.stopped, pid=outcome.pid)

    def start(self, scene: str, *, windowed: bool) -> StartObservation:
        outcome = run_daemon_start_operation(
            self._project, self._godot, scene=scene, windowed=windowed
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return StartObservation(
            installed_harness=outcome.installed_harness,
            harness_synced=outcome.harness_synced,
            harness_version=outcome.harness_version,
            created_paths=tuple(outcome.created_paths),
            created_sections=tuple(outcome.created_sections),
            pid=outcome.pid,
            windowed=outcome.windowed,
            already_running=outcome.already_running,
        )

    def wait_ready(self, timeout: float) -> ReadyObservation:
        outcome = run_daemon_wait_ready_operation(self._project, timeout=timeout)
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return ReadyObservation(pid=outcome.pid, launched=outcome.launched)

    def observe_content(
        self, node: str, *, max_nodes: int, max_vertices: int
    ) -> InstanceContent:
        outcome = run_game_inspect_model_content_operation(
            self._project,
            GameInspectModelContentParams(
                node=node, max_nodes=max_nodes, max_vertices=max_vertices
            ),
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return InstanceContent(
            node=outcome.node,
            instance_id=outcome.instance_id,
            scene_file_path=outcome.scene_file_path,
            session_id=outcome.session_id,
            engine_frame=outcome.engine_frame,
            content=self._content(outcome.content),
        )

    def capture(self, output: Path) -> CaptureObservation:
        outcome = run_screen_capture_operation(
            self._project, ScreenCaptureParams(output=str(output))
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return CaptureObservation(
            path=outcome.path,
            session_id=outcome.receipt.session_id,
            launched_scene=outcome.receipt.scene_path,
            engine_frame=outcome.receipt.engine_frame,
            sha256=outcome.receipt.sha256,
        )
