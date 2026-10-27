"""The Windows adapter's endpoint-record removal waits out a transient hold (#1236).

Windows refuses the deletion of a file that another handle holds open without
delete sharing, however short the hold, and the stop command's own 50 ms poll
opens the record that way. The removal retries for a bounded time, so the order
ADR-0047 fixes, the record removed before the slot is released, holds against
such a hold. The subject is the native delete refusal, so the hold test runs on
Windows only.
"""

import os
import sys
from pathlib import Path

import pytest

from gda.commands.daemon import _STOP_TIMEOUT
from gda.daemon import win32
from gda.daemon.discovery import daemon_paths
from gda.daemon.windows import WindowsPlatform
from gda.daemon.windows_discovery import REMOVAL_RETRY_BOUND, publish_endpoint


@pytest.mark.skipif(sys.platform != "win32", reason="Windows delete sharing")
def test_the_removal_waits_out_a_transient_hold_on_the_record(
    daemon_runtime_dir, tmp_path, monkeypatch
):
    project = tmp_path / "game"
    project.mkdir()
    platform = WindowsPlatform()
    paths = daemon_paths(project, platform=platform)
    platform.prepare_runtime(paths)
    publish_endpoint(paths, os.getpid(), 40001, 40002, "0123456789abcdef" * 4)
    record = paths.endpoint_file
    assert record.exists()

    # Python's open shares reads and writes, not deletion: the record is held
    # the way the stop command's poll holds it.
    hold = open(record, "rb")
    refused: list[int | None] = []
    unlink = Path.unlink

    def release_on_refusal(path: Path, missing_ok: bool = False) -> None:
        # The hold ends when it has refused a delete, so the test does not
        # depend on how long the checks before the first delete take.
        try:
            unlink(path, missing_ok)
        except PermissionError as error:
            refused.append(getattr(error, "winerror", None))
            hold.close()
            raise

    monkeypatch.setattr(Path, "unlink", release_on_refusal)
    try:
        platform.unpublish(paths)
    finally:
        hold.close()

    assert refused == [win32.ERROR_SHARING_VIOLATION]
    assert not record.exists()


def test_the_removal_bound_is_inside_the_stop_wait():
    # A stop whose daemon waits out a hold still returns its stop result.
    assert REMOVAL_RETRY_BOUND < _STOP_TIMEOUT
