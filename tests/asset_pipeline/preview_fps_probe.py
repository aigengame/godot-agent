"""Opt-in fixed-fixture FPS investigation; no performance pass/fail threshold.

Run: uv run python -m tests.asset_pipeline.preview_fps_probe --output-dir /tmp/fps-probe
"""

import argparse
import json
import os
import time
from pathlib import Path

from tests.asset_pipeline.test_e2e_preview import _asymmetric_glb
from tests.support import Gda


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    root = parser.parse_args().output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ["GDA_USER_DATA_ROOT"] = str(root / "user-data")
    source = root / "model.glb"
    _asymmetric_glb(source, textured=False)
    run = Gda(None, json_output=True, timeout=180)
    baselines: dict[float, Path] = {}
    records = []
    cases = [(delay, 320) for _ in range(3) for delay in (0.0, 1.25, 2.5)]
    cases.append((0.0, 400))
    for index, (delay, width) in enumerate(cases):
        settings = root / f"settings-{index}.json"
        settings.write_text(json.dumps({"width": width, "height": 180, "padding": 1.2}))
        args = [
            "asset-pipeline",
            "preview",
            "--path",
            str(source),
            "--output-dir",
            str(root / f"captures-{index}"),
            "--settings",
            str(settings),
            "--frames",
            "12",
            "--warmup-seconds",
            str(delay),
        ]
        if delay in baselines:
            args.extend(["--baseline", str(baselines[delay])])
        start = time.monotonic()
        result = run.json(*args, timeout=180)
        elapsed = time.monotonic() - start
        path = root / f"result-{index}.json"
        path.write_text(json.dumps(result, indent=2))
        baselines.setdefault(delay, path)
        preview = result["preview"]
        cleanup = preview["cleanup"]
        if (
            not cleanup["session_stopped"]
            or not cleanup["project_removed"]
            or cleanup["issues"]
            or Path(preview["project"]).exists()
        ):
            raise RuntimeError(f"Preview cleanup incomplete; inspect {path}")
        record = {
            "case": index,
            "width": width,
            "warmup_seconds": delay,
            "elapsed_seconds": elapsed,
            "performance": preview["performance"],
            "comparison": preview["comparison"],
            "cleanup": cleanup,
        }
        records.append(record)
        (root / "evidence.json").write_text(json.dumps(records, indent=2))
        print(
            json.dumps(
                {
                    "case": index,
                    "warmup_seconds": delay,
                    "width": width,
                    "fps_mean": preview["performance"]["stats"]["fps"]["mean"],
                    "elapsed_seconds": elapsed,
                    "result": str(path),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
