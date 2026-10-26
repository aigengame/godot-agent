"""S0(b) of #1228: the windowed display verdict of the hosted runner.

Prints the verdict the windowed e2e gates and ``gda daemon start --windowed`` read,
as JSON on stdout: ``code`` is null when a windowed session can launch here, else the
registered error code (``live_windowed_unavailable`` or
``live_windowed_permission_denied``) with the OS call that decided it and the reason.
It is a temporary probe: it goes with the probe job that runs it.
"""

import json
import sys

from gda.daemon.display import windowed_unavailable


def main() -> int:
    verdict = windowed_unavailable()
    report: dict = {"probe": "display", "platform": sys.platform}
    if verdict is None:
        report["code"] = None
    else:
        report["code"] = verdict.code
        report["os_call"] = verdict.probe.name
        report["reason"] = verdict.reason
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
