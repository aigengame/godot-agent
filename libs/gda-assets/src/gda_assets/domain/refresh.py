"""One controlled refresh and its bounded, host-observed content comparison."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import math

from gda_assets.domain.recipe import target_relative


@dataclass(frozen=True)
class RefreshRequest:
    path: str
    scene: str
    node: str
    windowed: bool = False
    timeout: float = 25.0
    max_nodes: int = 256
    max_vertices: int = 200000
    capture_output: Path | None = None


def validate_refresh(request: RefreshRequest, targets: list[str]) -> None:
    target_relative(request.path)
    target_relative(request.scene)
    if request.path not in targets or not request.path.lower().endswith(".glb"):
        raise ValueError("Refresh must select one GLB output from this handoff")
    if not request.scene.lower().endswith((".tscn", ".scn")):
        raise ValueError("Refresh requires an explicit res:// test scene")
    if (
        not request.node.startswith("/root/")
        or any(part in {"", ".", ".."} for part in request.node[1:].split("/"))
        or any(token in request.node for token in (":", "\\"))
    ):
        raise ValueError("Refresh requires an absolute /root/... model instance path")
    if not math.isfinite(request.timeout) or not 0 < request.timeout <= 50:
        raise ValueError(
            "Refresh readiness timeout must be finite, positive, and at most 50 seconds"
        )
    if type(request.max_nodes) is not int or not 1 <= request.max_nodes <= 1024:
        raise ValueError("Refresh max_nodes must be between 1 and 1024")
    if (
        type(request.max_vertices) is not int
        or not 1 <= request.max_vertices <= 1000000
    ):
        raise ValueError("Refresh max_vertices must be between 1 and 1000000")
    if request.capture_output is not None:
        if not request.windowed:
            raise ValueError("Refresh capture requires windowed mode")
        if request.capture_output.suffix.lower() != ".png":
            raise ValueError("Refresh capture output must be a PNG filesystem path")


@dataclass(frozen=True)
class ModelContent:
    measurement: str
    engine: str
    complete: bool
    digest: str | None
    nodes: int = 0
    surfaces: int = 0
    vertices: int = 0
    unsupported: tuple[str, ...] = ()
    omitted: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportedContent:
    path: str
    content: ModelContent


@dataclass(frozen=True)
class InstanceContent:
    node: str
    instance_id: int
    scene_file_path: str
    session_id: str
    engine_frame: int
    content: ModelContent


@dataclass(frozen=True)
class SessionState:
    running: bool
    pid: int | None
    windowed: bool | None
    session_id: str | None


@dataclass(frozen=True)
class CaptureObservation:
    path: str
    session_id: str
    launched_scene: str
    engine_frame: int
    sha256: str


@dataclass(frozen=True)
class StopObservation:
    stopped: bool
    pid: int | None


@dataclass(frozen=True)
class StartObservation:
    installed_harness: bool
    harness_synced: bool
    harness_version: str
    created_paths: tuple[str, ...]
    created_sections: tuple[str, ...]
    pid: int
    windowed: bool | None
    already_running: bool


@dataclass(frozen=True)
class ReadyObservation:
    pid: int
    launched: bool


@dataclass(frozen=True)
class ContentComparison:
    status: Literal["match", "mismatch", "incomplete"]
    reasons: tuple[str, ...] = ()


def compare_instance(
    request: RefreshRequest,
    imported: ImportedContent,
    instance: InstanceContent,
    before: SessionState,
    ready: SessionState,
) -> ContentComparison:
    """Compare complete host facts, never infer live content from disk hashes."""
    if (
        not ready.running
        or not ready.session_id
        or ready.session_id == before.session_id
        or instance.session_id != ready.session_id
        or ready.windowed != request.windowed
    ):
        return ContentComparison(
            "incomplete",
            ("The observation is not bound to the requested new, ready session.",),
        )
    if (
        imported.path != request.path
        or instance.node != request.node
        or instance.scene_file_path != request.path
    ):
        return ContentComparison(
            "mismatch",
            (
                "The imported resource or selected instance does not match the requested paths.",
            ),
        )
    expected, actual = imported.content, instance.content
    if any(
        not content.complete
        or not content.digest
        or content.unsupported
        or content.omitted
        for content in (expected, actual)
    ):
        return ContentComparison(
            "incomplete",
            ("The imported or runtime content has unsupported or unobserved parts.",),
        )
    if (
        not expected.measurement
        or expected.measurement != actual.measurement
        or not expected.engine
        or expected.engine != actual.engine
    ):
        return ContentComparison(
            "incomplete",
            (
                "The measurement or reported engine version differs between observations.",
            ),
        )
    if expected.digest != actual.digest:
        return ContentComparison(
            "mismatch",
            ("The selected instance content differs from the imported result.",),
        )
    return ContentComparison("match")


@dataclass
class RefreshResult:
    request: RefreshRequest
    status: Literal["verified", "mismatch", "incomplete"] = "incomplete"
    completed: list[str] = field(default_factory=list)
    before: SessionState | None = None
    after: SessionState | None = None
    ready_session: SessionState | None = None
    stop: StopObservation | None = None
    start: StartObservation | None = None
    ready: ReadyObservation | None = None
    imported: ImportedContent | None = None
    instance: InstanceContent | None = None
    comparison: ContentComparison | None = None
    capture: CaptureObservation | None = None
    runtime_state_preserved: Literal[False] = False
    issues: list[str] = field(default_factory=list)
    limitations: tuple[str, ...] = (
        "Comparison covers only the engine sampler's supported static content at the observation frame.",
        "Runtime state is not preserved across the requested session reset.",
        "A later capture is associated by session and frame order, not proof that the selected instance stayed unchanged until those pixels.",
        "The capture's launched_scene remains a launch fact, not the selected asset or current scene.",
    )
