"""Bounded local file observations for host-published resource paths."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from gda_assets.application.ports import PortFailure
from gda_assets.domain.observations import ContentObservations, FileDigest


MAX_DISTINCT_PATHS = 128
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
READ_BYTES = 64 * 1024


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


class LocalObservationFiles:
    def __init__(self, project: Path):
        self.project = project.resolve()
        self._paths: set[str] = set()
        self._bytes_read = 0

    def _resolve(self, resource: str) -> tuple[Path, Path]:
        if not resource.startswith("res://"):
            raise ValueError("Resource path must start with res://")
        relative = resource[6:]
        parts = relative.split("/")
        if (
            not relative
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative
            or ":" in relative
            or PurePosixPath(relative).is_absolute()
        ):
            raise ValueError("Resource path must be a normalized res:// file path")
        resource_path = self.project / Path(*parts)
        path = resource_path.resolve()
        if not path.is_relative_to(self.project):
            raise ValueError("Resource path resolves outside the selected project")
        return path, resource_path

    def digest(self, resource: str) -> FileDigest:
        try:
            path, resource_path = self._resolve(resource)
        except (OSError, ValueError) as exc:
            return FileDigest(resource, "unavailable", reason=str(exc))

        key = str(path)
        if key not in self._paths:
            if len(self._paths) >= MAX_DISTINCT_PATHS:
                return FileDigest(
                    resource,
                    "unavailable",
                    reason=f"Observation exceeds {MAX_DISTINCT_PATHS} distinct resource paths",
                )
            self._paths.add(key)

        try:
            path_before = resource_path.stat()
            if not stat.S_ISREG(path_before.st_mode):
                return FileDigest(
                    resource,
                    "unavailable",
                    reason="Resource path is not a regular file",
                )
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or _identity(
                    path_before
                ) != _identity(before):
                    return FileDigest(
                        resource, "changed", reason="File changed before observation"
                    )
                if before.st_size > MAX_FILE_BYTES:
                    return FileDigest(
                        resource,
                        "unavailable",
                        reason=f"File exceeds the {MAX_FILE_BYTES} byte observation limit",
                    )
                if self._bytes_read + before.st_size > MAX_TOTAL_BYTES:
                    return FileDigest(
                        resource,
                        "unavailable",
                        reason=f"Observation exceeds the {MAX_TOTAL_BYTES} byte total read limit",
                    )
                digest = hashlib.sha256()
                size = 0
                while chunk := stream.read(READ_BYTES):
                    size += len(chunk)
                    self._bytes_read += len(chunk)
                    if size > MAX_FILE_BYTES or self._bytes_read > MAX_TOTAL_BYTES:
                        return FileDigest(
                            resource,
                            "unavailable",
                            reason="File changed while reading and exceeded an observation limit",
                        )
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            current_path = resource_path.resolve()
            current = resource_path.stat()
            if (
                _identity(before) != _identity(after)
                or _identity(after) != _identity(current)
                or size != after.st_size
                or current_path != path
            ):
                return FileDigest(
                    resource,
                    "changed",
                    reason="File identity or metadata changed during observation",
                )
            return FileDigest(resource, "observed", digest.hexdigest(), size)
        except FileNotFoundError:
            return FileDigest(resource, "missing", reason="File does not exist")
        except OSError as exc:
            return FileDigest(
                resource,
                "unavailable",
                reason=f"File cannot be observed: {exc.strerror or type(exc).__name__}",
            )

    def validate_output(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            raise PortFailure(
                "invalid_collection", f"Observation output already exists: {path}"
            )

    def save(self, observations: ContentObservations, path: Path) -> None:
        self.validate_output(path)
        saved_to = str(path.resolve())
        payload = asdict(observations)
        payload["saved_to"] = saved_to
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        descriptor: int | None = None
        created = False
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            observations.saved_to = saved_to
        except (OSError, TypeError, ValueError) as exc:
            if descriptor is not None:
                os.close(descriptor)
            if created:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise PortFailure(
                "observation_save_failed",
                f"Cannot save content observations: {exc}",
            ) from exc
