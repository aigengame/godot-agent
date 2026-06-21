"""Length-prefixed JSON framing for the daemon's IPC legs (ADR-0021).

Both the CLI↔daemon and (in a later slice) daemon↔harness legs exchange JSON
objects over a stream socket. A message is a 4-byte big-endian length prefix
followed by that many UTF-8 JSON bytes, so two messages sent back-to-back on one
connection stay distinct. The daemon↔harness *response* body carries the raw
ADR-0002 sentinel string, so the existing parser is reused unchanged.
"""

import json
import socket
import struct
from typing import Any

_LENGTH = struct.Struct(">I")  # 4-byte big-endian frame length


def write_message(sock: socket.socket, obj: Any) -> None:
    """Send ``obj`` as one length-prefixed JSON frame."""
    body = json.dumps(obj).encode("utf-8")
    sock.sendall(_LENGTH.pack(len(body)) + body)


def read_message(sock: socket.socket) -> Any | None:
    """Read one length-prefixed JSON frame, or ``None`` if the peer closed."""
    header = _recv_exactly(sock, _LENGTH.size)
    if header is None:
        return None
    (length,) = _LENGTH.unpack(header)
    body = _recv_exactly(sock, length)
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
