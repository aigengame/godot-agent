"""One package inspection and the project intent applied to its resource view."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from gda_assets.domain.artifacts import PipelineFailure
from gda_assets.domain.model import ModelCheckResult, ModelFacts, Verdict


@dataclass(frozen=True)
class PackageCheckRequest:
    package: Path
    path: str
    expectations: Path
    exclude: tuple[str, ...] = ()
    subtree: str = "."
    max_nodes: int = 256
    max_items: int = 1024


@dataclass(frozen=True)
class PackageSnapshot:
    source: str
    path: Path
    root: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class PackageEngine:
    version: str
    build_hash: str


@dataclass(frozen=True)
class PackageResource:
    path: str
    present: bool


@dataclass(frozen=True)
class PackagePresence:
    engine: PackageEngine
    resources: tuple[PackageResource, ...]


@dataclass(frozen=True)
class PackageInspection:
    engine: PackageEngine
    model: ModelFacts


@dataclass(frozen=True)
class PackageExclusion:
    path: str
    present: bool
    verdict: Literal["pass", "fail"]


@dataclass
class PackageCleanup:
    staging_removed: bool = False
    issues: list[str] = field(default_factory=list)


@dataclass
class PackageCheckResult:
    request: PackageCheckRequest
    origin: Literal["package_editor_inspection"] = "package_editor_inspection"
    package: PackageSnapshot | None = None
    presence: PackagePresence | None = None
    inspection: PackageInspection | None = None
    check: ModelCheckResult | None = None
    exclusions: tuple[PackageExclusion, ...] = ()
    verdict: Verdict | None = None
    completed: list[str] = field(default_factory=list)
    cleanup: PackageCleanup = field(default_factory=PackageCleanup)
    failure: PipelineFailure | None = None
    limitations: tuple[str, ...] = (
        "Editor-based PCK inspection does not validate native release execution, input, or rendering.",
        "Exclusions check exact selected resource paths, not directory trees or a complete package inventory.",
        "Model checks retain the inspection scope and omissions; success does not establish unrequested requirements.",
    )


def _resource_path(path: str) -> None:
    if (
        not path.startswith("res://")
        or any(part in {"", ".", ".."} for part in path[6:].split("/"))
        or any(char in path[6:] for char in ("\\", ":", "\x00"))
    ):
        raise ValueError(
            f"Package resources require exact normalized res:// paths: {path}"
        )


def validate_package_request(request: PackageCheckRequest) -> None:
    _resource_path(request.path)
    if len(request.exclude) > 64:
        raise ValueError("Select at most 64 exact exclusion paths")
    if len(set(request.exclude)) != len(request.exclude):
        raise ValueError("Exclusion paths must be unique")
    for path in request.exclude:
        _resource_path(path)
        if path == request.path:
            raise ValueError("The inspected model cannot also be an exclusion")
    if request.subtree != "." and (
        any(part in {"", ".", ".."} for part in request.subtree.split("/"))
        or any(char in request.subtree for char in ("\\", ":", "\x00"))
    ):
        raise ValueError("subtree must be . or a resource-relative node path")
    if type(request.max_nodes) is not int or not 1 <= request.max_nodes <= 4096:
        raise ValueError("max_nodes must be an integer from 1 to 4096")
    if type(request.max_items) is not int or not 1 <= request.max_items <= 16384:
        raise ValueError("max_items must be an integer from 1 to 16384")


def evaluate_exclusions(
    paths: tuple[str, ...], resources: tuple[PackageResource, ...]
) -> tuple[PackageExclusion, ...]:
    """Absence is a project requirement only for the explicitly selected paths."""
    observed = {item.path: item.present for item in resources}
    return tuple(
        PackageExclusion(path, observed[path], "fail" if observed[path] else "pass")
        for path in paths
    )


def package_verdict(
    model: Verdict, exclusions: tuple[PackageExclusion, ...]
) -> Verdict:
    return "fail" if any(item.verdict == "fail" for item in exclusions) else model
