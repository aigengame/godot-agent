#!/usr/bin/env python3
"""Run the exact gda-balancing suite with bounded local shard parallelism."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ci import (
    MEMBER_ROOT,
    PROCESS_TIMEOUT_SECONDS,
    aggregate_junit_verdict,
    local_parallel_shards,
    local_serial_shards,
    shard_paths,
    summarize_local_measurements,
    subprocess_text,
    summarize_junit,
    verify_outcomes,
)


@dataclass(frozen=True)
class ShardResult:
    name: str
    returncode: int
    wall_seconds: float


def _run_shard(name: str, output_dir: Path) -> ShardResult:
    started = time.monotonic()
    junit_path = output_dir / f"junit-{name}.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        *(str(path) for path in shard_paths(name)),
        "-q",
        "--durations=50",
        f"--junitxml={junit_path}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=MEMBER_ROOT,
            capture_output=True,
            text=True,
            timeout=PROCESS_TIMEOUT_SECONDS["required"],
        )
        output = completed.stdout + completed.stderr
        returncode = completed.returncode
    except subprocess.TimeoutExpired as error:
        output = subprocess_text(error.stdout) + subprocess_text(error.stderr)
        output += "\nlocal shard exceeded the required process timeout\n"
        returncode = 124
    (output_dir / f"{name}.log").write_text(output, encoding="utf-8")
    if junit_path.is_file():
        summarize_junit(junit_path, output_dir / f"{name}-durations.json")
        try:
            verify_outcomes(junit_path, output_dir / f"{name}-outcomes.json")
        except SystemExit:
            returncode = returncode or 1
    wall_seconds = round(time.monotonic() - started, 6)
    (output_dir / f"wall-{name}.json").write_text(
        json.dumps({"wall_seconds": wall_seconds}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ShardResult(
        name=name,
        returncode=returncode,
        wall_seconds=wall_seconds,
    )


def _run_once(output_dir: Path, jobs: int) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        parallel = list(
            executor.map(
                lambda shard: _run_shard(shard, output_dir),
                local_parallel_shards(),
            )
        )
    serial = [_run_shard(shard, output_dir) for shard in local_serial_shards()]
    results = [*parallel, *serial]
    failures = [row.name for row in results if row.returncode != 0]
    row: dict[str, object] = {
        "wall_seconds": round(time.monotonic() - started, 6),
        "jobs": jobs,
        "shards": {
            result.name: {
                "returncode": result.returncode,
                "wall_seconds": result.wall_seconds,
            }
            for result in results
        },
        "failed_shards": failures,
    }
    aggregate, aggregate_exit = aggregate_junit_verdict(
        output_dir, output_dir / "aggregate.json"
    )
    row["aggregate_closed"] = aggregate["closed"]
    if aggregate_exit:
        failures.append("aggregate")
    else:
        row["test_count"] = aggregate["test_count"]
        row["test_seconds"] = aggregate["test_seconds"]
    return row


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="local semantic shard concurrency; use >1 only after measuring contention",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not 1 <= args.jobs <= len(local_parallel_shards()):
        raise SystemExit("--jobs must be between 1 and the semantic shard count")
    if args.repeat < 1:
        raise SystemExit("--repeat must be positive")
    rows = [
        _run_once(args.output_dir / f"run-{index:02d}", args.jobs)
        for index in range(1, args.repeat + 1)
    ]
    report = summarize_local_measurements(rows, jobs=args.jobs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "measurement.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return int(any(row["failed_shards"] for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
