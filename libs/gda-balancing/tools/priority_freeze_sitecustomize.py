"""Record actual public A subprocess imports for the fixed-build probe.

The orchestrator copies this file as sitecustomize.py into its frozen harness.
It writes only to a path outside the frozen trees after the CLI exits.
"""

import atexit
import json
import os
from pathlib import Path
import sys


def _record() -> None:
    target = os.environ.get("GDA_FREEZE_IMPORT_LOG")
    if not target:
        return
    package = sys.modules.get("gda_balancing")
    Path(target).write_text(
        json.dumps(
            {
                "executable": str(Path(sys.executable).resolve()),
                "sys_path": sys.path,
                "package_origin": str(Path(package.__file__).resolve())
                if package
                else None,
                "import_origins": sorted(
                    {
                        str(Path(module.__file__).resolve())
                        for module in tuple(sys.modules.values())
                        if getattr(module, "__file__", None)
                        and Path(module.__file__).exists()
                    }
                ),
            },
            sort_keys=True,
        )
        + "\n"
    )


atexit.register(_record)
