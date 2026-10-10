"""Length-prefixed JSON framing for the daemon's IPC legs (#7, ADR-0021), and the
deadline rule the Windows control handshake shares with it (#1162)."""

import socket
import time

import pytest

from gda.daemon.protocol import read_message, write_message
from gda.daemon.windows_discovery import authenticate_control


def test_protocol_roundtrips_and_frames_back_to_back_messages():
    a, b = socket.socketpair()
    try:
        write_message(a, {"op": "game-tree", "params": {}})
        assert read_message(b) == {"op": "game-tree", "params": {}}

        # Framing keeps two messages sent back-to-back distinct (no run-together).
        write_message(a, {"n": 1})
        write_message(a, {"n": 2})
        assert read_message(b) == {"n": 1}
        assert read_message(b) == {"n": 2}

        # A closed peer reads as None rather than hanging or erroring.
        a.close()
        assert read_message(b) is None
    finally:
        b.close()


def test_the_control_handshake_refuses_an_expired_deadline_before_it_reads():
    # The Windows control handshake (#1162) reads its secret under the same
    # deadline rule a frame read uses, so an expired deadline refuses before any
    # recv instead of waiting on a peer that sends nothing. The socket timeout
    # is the mutant guard: a handshake that reads anyway hits the peer that
    # sends nothing and fails on the message, instead of hanging the test.
    a, b = socket.socketpair()
    b.settimeout(1.0)
    try:
        with pytest.raises(TimeoutError, match="deadline has expired"):
            authenticate_control(b, "ab" * 32, time.monotonic() - 1)
    finally:
        a.close()
        b.close()
