"""Length-prefixed framing for the daemon's IPC legs (ADR-0021).

A frame is a 4-byte big-endian length prefix followed by that many payload bytes,
so messages sent back-to-back on one connection stay distinct. The CLI↔daemon leg
and the daemon→harness *request* carry JSON (``write_message`` / ``read_message``);
the harness→daemon *response* carries the raw ADR-0002 sentinel string as bytes
(``write_frame`` / ``read_frame``), so the existing parser is reused unchanged.
"""

import json
import socket
import struct
from typing import Any

_LENGTH = struct.Struct(">I")  # 4-byte big-endian frame length


def write_frame(sock: socket.socket, payload: bytes) -> None:
    """Send ``payload`` as one length-prefixed frame."""
    sock.sendall(_LENGTH.pack(len(payload)) + payload)


def read_frame(sock: socket.socket) -> bytes | None:
    """Read one length-prefixed frame's payload, or ``None`` if the peer closed."""
    header = _recv_exactly(sock, _LENGTH.size)
    if header is None:
        return None
    (length,) = _LENGTH.unpack(header)
    return _recv_exactly(sock, length)


def write_message(sock: socket.socket, obj: Any) -> None:
    """Send ``obj`` as one length-prefixed JSON frame."""
    write_frame(sock, json.dumps(obj).encode("utf-8"))


def read_message(sock: socket.socket) -> Any | None:
    """Read one length-prefixed JSON frame, or ``None`` if the peer closed."""
    body = read_frame(sock)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def _recv_exactly(sock: socket.socket, count: int) -> bytes | None:
    """Read exactly ``count`` bytes, or ``None`` if the peer closed mid-frame."""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
