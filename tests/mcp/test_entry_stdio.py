"""Real gda-mcp startup diagnostics and Unicode stdio round trips (#1110)."""

import os
import shutil
import subprocess
import sysconfig

import pytest


@pytest.fixture
def mcp_entry():
    console = shutil.which("gda-mcp", path=sysconfig.get_path("scripts"))
    assert console, "gda-mcp console script missing from this environment"
    return console


@pytest.fixture(params=["native", "legacy"])
def entry_env(request):
    env = {**os.environ, "PYTHONUTF8": "0"}
    env.pop("PYTHONIOENCODING", None)
    if request.param == "legacy":
        env["PYTHONIOENCODING"] = "cp1252"
    return env


def test_startup_failure_reports_unicode_on_stderr(mcp_entry, entry_env, tmp_path):
    # Introspection cannot launch this override. The real entry must still
    # report the Unicode command on stderr before a server session exists.
    missing = (tmp_path / "missing_中文_😀").as_posix()
    entry_env["GDA_BIN"] = f'"{missing}"'
    proc = subprocess.run([mcp_entry], capture_output=True, env=entry_env, timeout=30)
    assert proc.returncode != 0
    assert not proc.stdout
    assert missing in proc.stderr.decode("utf-8")
