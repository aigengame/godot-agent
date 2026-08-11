"""Bounded byte input from a filesystem path."""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

_HASH_CHUNK_BYTES = 64 * 1024


class InputReadError(OSError):
    """The requested input path could not be read."""


class InputTooLargeError(ValueError):
    """The requested input exceeded its explicit byte bound."""


class InputGrewTooLargeError(InputTooLargeError):
    """The requested regular file grew beyond its bound while being read."""


class InputNotRegularError(ValueError):
    """The requested input is not a regular file."""


@dataclass(frozen=True)
class BoundedInputObservation:
    """The complete stream identity and its bytes when within the bound."""

    data: bytes | None
    sha256: str


@dataclass(frozen=True)
class RegularFileObservation:
    """A bounded parse prefix and the identity of one complete regular file."""

    prefix: bytes
    sha256: str


def read_bounded_input(path: str, max_bytes: int) -> bytes:
    """Read at most one byte beyond a caller-owned size limit."""
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError as err:
        raise InputReadError from err
    if len(data) > max_bytes:
        raise InputTooLargeError
    return data


def read_bounded_input_with_sha256(
    path: str,
    max_bytes: int,
) -> BoundedInputObservation:
    """Read bounded content while hashing the complete stream for diagnostics."""
    digest = hashlib.sha256()
    buffered = bytearray()
    too_large = False
    try:
        with Path(path).open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
                if too_large:
                    continue
                remaining = max_bytes + 1 - len(buffered)
                buffered.extend(chunk[:remaining])
                if len(buffered) > max_bytes:
                    too_large = True
                    buffered.clear()
    except OSError as err:
        raise InputReadError from err
    sha256 = digest.hexdigest()
    return BoundedInputObservation(
        data=None if too_large else bytes(buffered),
        sha256=sha256,
    )


def read_bounded_regular_input_with_sha256(
    path: str,
    *,
    max_bytes: int,
    prefix_bytes: int,
    digest_prefix: bytes = b"",
) -> RegularFileObservation:
    """Read one regular file within a bound while retaining a parse prefix."""
    digest = hashlib.sha256()
    digest.update(digest_prefix)
    prefix = bytearray()
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise InputNotRegularError
        if metadata.st_size > max_bytes:
            raise InputTooLargeError
        observed = 0
        while observed <= max_bytes:
            chunk = os.read(
                descriptor,
                min(_HASH_CHUNK_BYTES, max_bytes + 1 - observed),
            )
            if not chunk:
                break
            observed += len(chunk)
            if observed > max_bytes:
                raise InputGrewTooLargeError
            digest.update(chunk)
            remaining = prefix_bytes - len(prefix)
            if remaining > 0:
                prefix.extend(chunk[:remaining])
    except (InputNotRegularError, InputTooLargeError):
        raise
    except OSError as err:
        raise InputReadError from err
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return RegularFileObservation(prefix=bytes(prefix), sha256=digest.hexdigest())
