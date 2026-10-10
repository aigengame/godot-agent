"""Length-prefixed JSON framing for the daemon's IPC legs (#7, ADR-0021)."""

import socket

import pytest

from gda.daemon.protocol import read_message, write_message


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


def test_the_windows_control_handshake_spends_the_frame_deadline_helper():
    # The Windows control handshake (#1162) reads its secret under the same
    # deadline rule a frame read uses, so an expired deadline refuses before any
    # recv instead of waiting on a peer that sends nothing.
    import time

    from gda.daemon.windows_discovery import authenticate_control

    a, b = socket.socketpair()
    try:
        with pytest.raises(TimeoutError, match="deadline has expired"):
            authenticate_control(b, "ab" * 32, time.monotonic() - 1)
    finally:
        a.close()
        b.close()
