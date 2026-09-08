"""Copy one stable regular file while hashing the bytes written."""

import hashlib
import os
from pathlib import Path
import stat


_READ_SIZE = 1024 * 1024


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def copy_with_sha256(
    source: Path, destination: Path, *, max_bytes: int | None = None
) -> tuple[str, int]:
    """Copy a stable regular source, optionally enforcing a streaming size bound."""
    before_path = source.stat()
    if not stat.S_ISREG(before_path.st_mode):
        raise OSError(f"source is not a regular file: {source}")
    if max_bytes is not None and before_path.st_size > max_bytes:
        raise OSError(f"source exceeds the {max_bytes}-byte limit: {source}")
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        before = os.fstat(reader.fileno())
        if _identity(before_path) != _identity(before):
            raise OSError(f"source changed before copy: {source}")
        while chunk := reader.read(_READ_SIZE):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise OSError(
                    f"source grew beyond the {max_bytes}-byte limit: {source}"
                )
            writer.write(chunk)
            digest.update(chunk)
        writer.flush()
        os.fsync(writer.fileno())
        after = os.fstat(reader.fileno())
    current = source.stat()
    if _identity(before) != _identity(after) or _identity(after) != _identity(current):
        destination.unlink(missing_ok=True)
        raise OSError(f"source changed while copying: {source}")
    return digest.hexdigest(), size
