"""Bounded byte input from a filesystem path."""

from pathlib import Path


class InputReadError(OSError):
    """The requested input path could not be read."""


class InputTooLargeError(ValueError):
    """The requested input exceeded its explicit byte bound."""


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
