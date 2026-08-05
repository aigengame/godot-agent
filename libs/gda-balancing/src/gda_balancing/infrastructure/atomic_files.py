"""Concrete atomic-file and process-lock mechanisms."""

import fcntl
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


def normalized_absolute_path(value: str) -> Path:
    """Expand one path and normalize platform-level temporary-directory aliases."""
    path = Path(os.path.abspath(os.path.expanduser(value)))
    for alias in (Path("/tmp"), Path("/var")):
        if not alias.is_symlink():
            continue
        try:
            relative = path.relative_to(alias)
        except ValueError:
            continue
        return Path(os.path.realpath(alias)) / relative
    return path


class PathKind(Enum):
    MISSING = "missing"
    SYMLINK = "symlink"
    REGULAR = "regular"
    DIRECTORY = "directory"
    OTHER = "other"


@dataclass(frozen=True)
class PathInspection:
    kind: PathKind
    writable: bool = False


class SymlinkPathError(OSError):
    """A filesystem operation reached a forbidden symbolic link."""


class NonRegularPathError(OSError):
    """A required regular file had another filesystem kind."""


class NonDirectoryPathError(OSError):
    """A required directory had another filesystem kind."""


def environment_value(name: str) -> str | None:
    """Read one process environment value without interpreting it."""
    return os.environ.get(name)


def inspect_path(path: Path) -> PathInspection:
    """Inspect one path without following a final symbolic link."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return PathInspection(PathKind.MISSING)
    mode = metadata.st_mode
    if stat.S_ISLNK(mode):
        kind = PathKind.SYMLINK
    elif stat.S_ISREG(mode):
        kind = PathKind.REGULAR
    elif stat.S_ISDIR(mode):
        kind = PathKind.DIRECTORY
    else:
        kind = PathKind.OTHER
    return PathInspection(kind, bool(stat.S_IMODE(mode) & 0o222))


def regular_files(root: Path, pattern: str) -> tuple[Path, ...]:
    """List regular, non-symlink files matching one concrete pattern."""
    if inspect_path(root).kind is not PathKind.DIRECTORY:
        return ()
    return tuple(
        path
        for path in sorted(root.glob(pattern))
        if inspect_path(path).kind is PathKind.REGULAR
    )


def read_regular_bytes(path: Path) -> bytes:
    """Read one regular file without following a final symbolic link."""
    inspection = inspect_path(path)
    if inspection.kind is PathKind.SYMLINK:
        raise SymlinkPathError(path)
    if inspection.kind is not PathKind.REGULAR:
        raise NonRegularPathError(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read()


def read_regular_bytes_following_symlink(path: Path) -> bytes:
    """Read one path whose resolved target must be a regular file."""
    try:
        metadata = path.stat()
    except OSError:
        raise
    if not stat.S_ISREG(metadata.st_mode):
        raise NonRegularPathError(path)
    return path.read_bytes()


def assert_no_symlink_ancestors(path: Path) -> None:
    """Reject symbolic links anywhere in one existing ancestor chain."""
    for candidate in reversed((path, *path.parents)):
        if inspect_path(candidate).kind is PathKind.SYMLINK:
            raise SymlinkPathError(candidate)


def ensure_directory_chain(path: Path) -> tuple[Path, ...]:
    """Create missing directories without accepting symlink ancestors."""
    assert_no_symlink_ancestors(path)
    missing = [
        candidate
        for candidate in reversed((path, *path.parents))
        if inspect_path(candidate).kind is PathKind.MISSING
    ]
    created: list[Path] = []
    for directory in missing:
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        else:
            created.append(directory)
            fsync_directory(directory.parent)
    inspection = inspect_path(path)
    if inspection.kind is PathKind.SYMLINK:
        raise SymlinkPathError(path)
    if inspection.kind is not PathKind.DIRECTORY:
        raise NonDirectoryPathError(path)
    return tuple(created)


def make_stage_directory(parent: Path, prefix: str) -> Path:
    """Create one private staging directory under an admitted parent."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def commit_directory(stage: Path, destination: Path) -> None:
    """Atomically rename one staged directory into its committed location."""
    os.replace(stage, destination)


def remove_tree(path: Path) -> None:
    """Remove one concrete directory tree."""
    shutil.rmtree(path)


def remove_file_if_present(path: Path) -> None:
    """Remove one temporary file when it still exists."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def remove_empty_directory(path: Path) -> None:
    """Remove one empty directory."""
    path.rmdir()


def write_immutable_link(
    path: Path,
    data: bytes,
    *,
    before_commit: bool = False,
) -> None:
    """Persist immutable bytes and publish them through an exclusive hard link."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        if before_commit:
            raise RuntimeError("injected publication fault before anchor commit")
        os.link(temporary, path)
        fsync_directory(path.parent)
    finally:
        remove_file_if_present(temporary)


def materialize_bytes(path: Path, data: bytes) -> None:
    """Atomically materialize bytes, accepting an identical regular file."""
    inspection = inspect_path(path)
    if inspection.kind is PathKind.SYMLINK:
        raise SymlinkPathError(path)
    if inspection.kind is not PathKind.MISSING:
        if inspection.kind is not PathKind.REGULAR:
            raise NonRegularPathError(path)
        if read_regular_bytes(path) == data:
            return
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if inspect_path(path).kind is not PathKind.MISSING:
            raise FileExistsError(path)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        remove_file_if_present(temporary)


def write_exclusive_bytes(path: Path, data: bytes) -> None:
    """Create one file exclusively, persist its bytes, and refuse symlink following."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def fsync_directory(path: Path) -> None:
    """Persist directory-entry changes for one concrete directory."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Hold one advisory exclusive lock on a regular lock file."""
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("invocation-key lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
