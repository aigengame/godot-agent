"""Real CLI entry points own UTF-8, even with Python UTF-8 mode off (#1110).

The legacy override makes the regression falsifiable on Unix hosts too. The
native case removes that override and exercises the Windows caller's locale.
Neither case enables Python UTF-8 mode or changes the parent test process.
"""

import json
import os
import shutil
import subprocess
import sys
import sysconfig

import pytest


@pytest.fixture(params=["console", "module"])
def cli_entry(request):
    if request.param == "module":
        return [sys.executable, "-m", "gda"]
    console = shutil.which("gda", path=sysconfig.get_path("scripts"))
    assert console, "gda console script missing from this interpreter's environment"
    return [console]


@pytest.fixture(params=["native", "legacy"])
def entry_env(request):
    env = {**os.environ, "PYTHONUTF8": "0"}
    env.pop("PYTHONIOENCODING", None)
    if request.param == "legacy":
        env["PYTHONIOENCODING"] = "cp1252"
    return env


def test_entry_emits_utf8_schema(cli_entry, entry_env):
    proc = subprocess.run(
        [*cli_entry, "schema"], capture_output=True, env=entry_env, timeout=30
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    manifest = json.loads(proc.stdout.decode("utf-8"))
    assert "scene create" in {entry["name"] for entry in manifest["commands"]}


def test_help_and_early_errors_use_utf8(cli_entry, entry_env):
    help_result = subprocess.run(
        [*cli_entry, "--help"], capture_output=True, env=entry_env, timeout=30
    )
    assert help_result.returncode == 0
    assert "schema" in help_result.stdout.decode("utf-8")
    assert not help_result.stderr

    unknown = "unknown_中文_😀"
    error_result = subprocess.run(
        [*cli_entry, "--json", unknown],
        capture_output=True,
        env=entry_env,
        timeout=30,
    )
    assert error_result.returncode == 2
    error = json.loads(error_result.stdout.decode("utf-8"))["error"]
    assert error["code"] == "unknown_command"
    assert unknown in error["message"]
    assert not error_result.stderr

    human_error = subprocess.run(
        [*cli_entry, unknown], capture_output=True, env=entry_env, timeout=30
    )
    assert human_error.returncode == 2
    assert unknown in human_error.stderr.decode("utf-8")


def test_importing_entry_modules_does_not_reconfigure_stdio():
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "before = [(s.encoding, s.errors) for s in "
            "(sys.stdin, sys.stdout, sys.stderr)]; "
            "import gda.cli, gda.__main__, gda.mcp; "
            "assert sys.flags.utf8_mode == 0; "
            "assert before == [(s.encoding, s.errors) for s in "
            "(sys.stdin, sys.stdout, sys.stderr)]",
        ],
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
