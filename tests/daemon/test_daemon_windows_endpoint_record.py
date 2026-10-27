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
import threading
import time

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.windows import WindowsPlatform
from gda.daemon.windows_discovery import publish_endpoint


@pytest.mark.skipif(sys.platform != "win32", reason="Windows delete sharing")
def test_the_removal_waits_out_a_transient_hold_on_the_record(
    daemon_runtime_dir, tmp_path
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
    # the way the stop command's poll holds it, for longer than one poll.
    hold = open(record, "rb")
    released_at: list[float] = []

    def release() -> None:
        hold.close()
        released_at.append(time.monotonic())

    timer = threading.Timer(0.3, release)
    timer.start()
    try:
        platform.unpublish(paths)
        returned_at = time.monotonic()
    finally:
        timer.cancel()
        timer.join()
        hold.close()

    assert not record.exists()
    # The removal returned once the hold had ended, not before it by chance:
    # a delete the hold did not refuse would return first, and prove nothing.
    assert released_at and returned_at >= released_at[0]
