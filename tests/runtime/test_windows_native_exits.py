"""Native status capture/classification through real processes (#1114).

These are Windows helper results, not Godot crashes: ExitProcess deliberately
sets a status without causing an exception. Actual Godot evidence is #1136's.
"""

import json
import sys
from pathlib import Path

import pytest

from gda.core.engine.launch import launch
from gda.core.failure.catalog import Failure
from gda.core.failure.classify import classify_launch_or_crash
from gda.exit_codes import EXIT_OPERATION
from tests.support import Gda

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="requires native Windows 32-bit process statuses"
)


@pytest.fixture
def native_exit_helper(tmp_path):
    helper = tmp_path / "native_exit.py"
    helper.write_text(
        "import ctypes, os, sys\n"
        "os.write(1, b'native-helper-stdout\\r\\n')\n"
        "os.write(2, b'native-helper-stderr\\r\\n')\n"
        "exit_process = ctypes.WinDLL('kernel32').ExitProcess\n"
        "exit_process.argtypes = [ctypes.c_uint]\n"
        "exit_process.restype = None\n"
        "exit_process(int(sys.argv[1]))\n",
        encoding="utf-8",
    )

    def make(status: int) -> Path:
        # The batch entry accepts the runner's Godot arguments without feeding
        # them to Python. cmd preserves the helper's full last-process status.
        wrapper = tmp_path / "native_exit.cmd"
        wrapper.write_text(
            f'@echo off\n"{sys.executable}" "{helper}" {status}\n',
            encoding="utf-8",
        )
        return wrapper

    return make


@pytest.mark.parametrize("status", [3221225477, 3221226356, 3221226505])
def test_native_helper_status_is_preserved_and_classified(native_exit_helper, status):
    binary = native_exit_helper(status)

    raw = launch(binary, [], cwd=None, timeout=10.0)

    assert raw.launch_failure is None
    assert raw.exit_code == status
    assert raw.stdout == "native-helper-stdout\r\n"
    assert raw.stderr == "native-helper-stderr\r\n"
    failure = classify_launch_or_crash(raw, binary)
    assert isinstance(failure, Failure)
    assert failure.error.code == "engine_crashed"
    assert failure.exit_code == EXIT_OPERATION
    assert failure.error.diagnostics == raw.stderr


def test_native_helper_fault_status_reaches_the_public_cli(native_exit_helper):
    proc = Gda(godot=native_exit_helper(3221225477))("info", "--json")

    assert proc.returncode == EXIT_OPERATION, proc.stdout + proc.stderr
    emitted = json.loads(proc.stdout)
    assert set(emitted) == {"error"}
    assert set(emitted["error"]) == {"category", "code", "message", "diagnostics"}
    assert emitted["error"]["category"] == "operation"
    assert emitted["error"]["code"] == "engine_crashed"
    assert "0xC0000005" in emitted["error"]["message"]
    assert emitted["error"]["diagnostics"] == "native-helper-stderr\r\n"
