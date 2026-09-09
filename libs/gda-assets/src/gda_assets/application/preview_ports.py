"""Capabilities required by the isolated preview use case."""

from pathlib import Path
from typing import Protocol

from gda_assets.domain.artifacts import ImportOutcome
from gda_assets.domain.preview import PreviewCamera, PreviewSettings
from gda_assets.domain.preview_result import (
    PreviewCapture,
    PreviewDiagnostics,
    PreviewInspection,
    PreviewPerformance,
    PreviewResult,
    PreviewState,
)
from gda_assets.domain.refresh import (
    ReadyObservation,
    SessionState,
    StartObservation,
    StopObservation,
)


class GodotPreviewPort(Protocol):
    def import_assets(self, paths: list[str]) -> ImportOutcome: ...

    def inspect_preview(self, max_nodes: int) -> PreviewInspection: ...

    def start(self, scene: str, *, windowed: bool) -> StartObservation: ...

    def wait_ready(self, timeout: float) -> ReadyObservation: ...

    def status(self) -> SessionState: ...

    def select_view(self, index: int) -> None: ...

    def capture_view(self, index: int, output: Path) -> PreviewCapture: ...

    def observe_view(self) -> PreviewState: ...

    def warmup(self, seconds: float) -> None: ...

    def performance(self, frames: int, *, budget: bool) -> PreviewPerformance: ...

    def diagnostics(self) -> PreviewDiagnostics: ...

    def stop(self) -> StopObservation: ...


class PreviewHost(Protocol):
    def __call__(self, project: Path, /) -> GodotPreviewPort: ...


class PreviewFilesPort(Protocol):
    def read_baseline(self, path: Path) -> PreviewResult: ...

    def prepare(
        self, source: Path, output_dir: Path, budget: Path | None
    ) -> tuple[Path, str]: ...

    def configure(
        self,
        project: Path,
        settings: PreviewSettings,
        cameras: tuple[PreviewCamera, ...],
    ) -> None: ...

    def remove_project(self, project: Path) -> None: ...
