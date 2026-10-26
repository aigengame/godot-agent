# Copied from aigengame/godot-agent#1225, the reporter's probe of 2026-10-25, with the
# formatter applied and nothing else changed. Temporary: it goes with the probe job.
"""Stand-in for gda's windows_worker: report our pid, then spawn a child the way it does."""

import json
import os
import subprocess
import sys
import time

print(json.dumps({"worker_pid": os.getpid(), "exe": sys.executable}), flush=True)
sys.stdin.readline()
child = subprocess.Popen(
    ["ping", "-n", "30", "127.0.0.1"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
print(json.dumps({"child_pid": child.pid}), flush=True)
time.sleep(30)
