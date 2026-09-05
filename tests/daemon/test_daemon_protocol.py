"""Length-prefixed JSON framing for the daemon's IPC legs (#7, ADR-0021)."""

import socket

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
