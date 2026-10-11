"""Private startup gate: launch Godot only after the daemon owns this worker."""

import json
import os
import subprocess
import sys
import time


def _reply(value: dict) -> None:
    sys.stdout.buffer.write(json.dumps(value).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
    if sys.platform != "win32":
        raise OSError("the private engine worker requires Windows")
    _reply({"worker_pid": os.getpid()})
    command = sys.stdin.buffer.readline()
    if not command:
        return  # the parent died before assigning the Job; start no engine
    request = json.loads(command)
    try:
        if time.monotonic() >= request["deadline"]:
            raise TimeoutError("the engine startup deadline expired at the worker gate")
        engine = subprocess.Popen(
            request["argv"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as error:
        _reply(
            {
                "error": {
                    "errno": error.errno,
                    "message": error.strerror or str(error),
                    "filename": error.filename,
                    "winerror": getattr(error, "winerror", None),
                }
            }
        )
        return
    _reply({"engine_pid": engine.pid})
    # Keep the Popen object/handle until the daemon has acquired its own durable
    # engine handle, even when Godot exits immediately. It supplies no status:
    # poll/wait in the daemon read the actual engine handle, not this worker.
    sys.stdin.buffer.read()
    engine.poll()


if __name__ == "__main__":
    main()
