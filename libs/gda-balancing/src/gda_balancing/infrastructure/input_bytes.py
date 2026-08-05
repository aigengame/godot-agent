"""Bounded byte input from a filesystem path."""

import hashlib
from pathlib import Path

_HASH_CHUNK_BYTES = 64 * 1024


class InputReadError(OSError):
    """The requested input path could not be read."""


class InputTooLargeError(ValueError):
    """The requested input exceeded its explicit byte bound."""

    def __init__(self, *, sha256: str | None = None) -> None:
        super().__init__("input exceeds its explicit byte bound")
        self.sha256 = sha256


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


def read_bounded_input_with_sha256(path: str, max_bytes: int) -> tuple[bytes, str]:
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
    if too_large:
        raise InputTooLargeError(sha256=sha256)
    return bytes(buffered), sha256
