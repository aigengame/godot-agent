"""Windows control authentication at the existing framed socket boundary."""

import secrets
import socket
import time

from gda.daemon.discovery import DaemonPaths
from gda.daemon.windows_discovery import read_endpoint


CONTROL_TIMEOUT = 2.0


def connect_control(paths: DaemonPaths, deadline: float) -> socket.socket:
    """Connect to the privately published Windows owner and send its secret."""
    endpoint = read_endpoint(paths)
    if endpoint is None:
        raise ConnectionError("no native daemon endpoint is published")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the control deadline has expired")
        sock.settimeout(left)
        sock.connect(endpoint.address)
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the control deadline has expired")
        sock.settimeout(left)
        sock.sendall(bytes.fromhex(endpoint.token))
        return sock
    except BaseException:
        sock.close()
        raise


def authenticate_control(sock: socket.socket, token: str, deadline: float) -> bool:
    """Read exactly one fixed-size secret within the original request deadline."""
    expected = bytes.fromhex(token)
    received = bytearray()
    while len(received) < len(expected):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the control deadline has expired")
        sock.settimeout(left)
        chunk = sock.recv(len(expected) - len(received))
        if not chunk:
            return False
        received.extend(chunk)
    return secrets.compare_digest(received, expected)
