"""gda projections for editor inspection of an isolated PCK resource view."""

from pathlib import Path
from typing import NoReturn

from gda.commands.resource import (
    PackageResourcePresenceParams,
    ResourceInspectModelParams,
    run_package_inspect_model_operation,
    run_package_resource_presence_operation,
)
from gda.errors import Failure, make_failure
from gda.integrations.model_reports import project_model_report
from gda.models import EngineVersion
from gda_assets.api import (
    PackageEngine,
    PackageInspection,
    PackagePresence,
    PackageResource,
    PortFailure,
)


class GdaGodotPackagePort:
    """Use returning package operations without exposing gda models to assets."""

    def __init__(self, godot: str | None = None) -> None:
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

    @staticmethod
    def _engine(version: EngineVersion) -> PackageEngine:
        return PackageEngine(version=version.string, build_hash=version.hash)

    def resource_presence(
        self, package: Path, paths: tuple[str, ...]
    ) -> PackagePresence:
        outcome = run_package_resource_presence_operation(
            package,
            PackageResourcePresenceParams(paths=list(paths)),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return PackagePresence(
            engine=self._engine(outcome.engine_version),
            resources=tuple(
                PackageResource(path=item.path, present=item.present)
                for item in outcome.resources
            ),
        )

    def inspect_model(
        self,
        package: Path,
        path: str,
        *,
        subtree: str,
        max_nodes: int,
        max_items: int,
    ) -> PackageInspection:
        outcome = run_package_inspect_model_operation(
            package,
            ResourceInspectModelParams(
                path=path,
                subtree=subtree,
                max_nodes=max_nodes,
                max_items=max_items,
            ),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        try:
            model = project_model_report(outcome)
        except ValueError as exc:
            self._raise(make_failure("contract_violation", str(exc), ""))
        return PackageInspection(
            engine=self._engine(outcome.engine_version), model=model
        )
