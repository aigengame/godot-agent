"""Length-prefixed framing for the daemon's IPC legs (ADR-0021).

A frame is a 4-byte big-endian length prefix followed by that many payload bytes,
so messages sent back-to-back on one connection stay distinct. The CLI↔daemon leg
and the daemon→harness *request* carry JSON (``write_message`` / ``read_message``);
the harness→daemon *response* carries the raw ADR-0002 sentinel string as bytes
(``write_frame`` / ``read_frame``), so the existing parser is reused unchanged.

It also provides the standard daemon→CLI reply-content builders (``result_reply`` /
``error_reply``) — the one place the daemon and the live client shape a reply dict
around a sentinel payload, so a relayed, daemon-served, or synthesized reply is
classified exactly like a headless engine run's.
"""

import json
import socket
import struct
from typing import Any

from gda.exit_codes import EXIT_LIVE
from gda.parser import build_result, error_envelope

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


def result_reply(payload: Any) -> dict:
    """A daemon→CLI reply carrying a SUCCESS ``payload`` as the ADR-0002 sentinel (exit 0).

    The reply dict the CLI socket leg sends back for a daemon-served or relayed
    success: the sentinel-wrapped payload in ``stdout`` (built once by
    :func:`gda.parser.build_result`), empty ``stderr``, and exit ``0`` — so
    ``classify_run`` / ``parse_result`` handle it exactly like a headless engine run's.
    """
    return _reply(payload, 0)


def error_reply(code: str, message: str, diagnostics: str = "") -> dict:
    """A daemon→CLI reply carrying a LIVE error envelope (exit ``EXIT_LIVE``).

    The single builder for a daemon- or client-synthesized live failure (no session,
    dropped connection, timeout, op error): the same ADR-0002 envelope a real op
    error uses, so ``classify_live`` maps the ``code`` through the normal pipeline.

    ``diagnostics`` is optional best-effort advisory detail (e.g. why an engine
    session failed to launch, #345). It rides the reply's EXISTING ``stderr`` field
    — the wire envelope shape ``{stdout, stderr, exit_code}`` is unchanged — so it
    flows the established ``stderr`` → ``RunResult.stderr`` → ``GdaError.diagnostics``
    path, staying within ADR-0002's advisory-stderr carve-out.
    """
    return _reply(error_envelope(code, message), EXIT_LIVE, stderr=diagnostics)


def _reply(payload: Any, exit_code: int, stderr: str = "") -> dict:
    """The shared reply-dict shape: a sentinel-wrapped ``payload`` + ``exit_code``.

    Private so the two public builders own the ADR-0002 exit invariant —
    :func:`result_reply` is exit ``0`` (success), :func:`error_reply` is ``EXIT_LIVE``
    (live error) — and no caller can pair a success payload with a non-zero exit.
    ``stderr`` defaults to empty (a success carries none); ``error_reply`` uses it to
    carry optional advisory diagnostics without changing the wire shape (#345).
    """
    return {"stdout": build_result(payload), "stderr": stderr, "exit_code": exit_code}
