"""Measure actual bounded-fold CLI commands under unchanged system budgets."""

import argparse
import hashlib
from importlib import import_module
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import time


def _support(package_root: Path):
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(package_root / "src"), str(package_root / "tests")]
    return import_module("test_bounded_fold_public")


PROFILE_RUNNER = r"""
import cProfile,json,runpy,sys,tracemalloc
from pathlib import Path
destination=Path(sys.argv[1]);sys.argv=['gda-balancing',*sys.argv[2:]]
profiler=cProfile.Profile();tracemalloc.start();profiler.enable();code=0
try:runpy.run_module('gda_balancing',run_name='__main__')
except SystemExit as error:code=error.code
finally:
 profiler.disable();current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
 profiler.dump_stats(str(destination.with_suffix('.prof')))
 import pstats
 rows=[]
 for (file,line,name),(primitive,total,own,cumulative,callers) in pstats.Stats(profiler).stats.items():
  if name in {'append_typed_value','_validate','admit_typed_value','_execute_value_instruction'}:
   rows.append({'file':file,'line':line,'name':name,'primitive_calls':primitive,'total_calls':total,'own_seconds':own,'cumulative_seconds':cumulative,'callers':[{'file':key[0],'line':key[1],'name':key[2],'counters':value} for key,value in callers.items()]})
 destination.write_text(json.dumps({'traced_current_bytes':current,'traced_peak_bytes':peak,'calls':rows,'scope':'Instrumented full public run including ingress, admission, execution, artifact validation and publication. Not bare-run latency.'},indent=2)+'\n')
raise SystemExit(code)
"""


def execute(candidate, arguments, label, *, instrument=False):
    directory = candidate.directory
    command = [sys.executable, "-m", "gda_balancing", *arguments]
    if instrument:
        command = [
            sys.executable,
            "-c",
            PROFILE_RUNNER,
            str(directory / (label + "-profile.json")),
            *arguments,
        ]
    env = {
        **candidate.env,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.perf_counter()
    with (
        (directory / (label + "-stdout.json")).open("wb") as stdout,
        (directory / (label + "-stderr.txt")).open("wb") as stderr,
    ):
        process = subprocess.Popen(
            command, cwd=directory, env=env, stdout=stdout, stderr=stderr
        )
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    elapsed = time.perf_counter() - started
    out = (directory / (label + "-stdout.json")).read_bytes()
    err = (directory / (label + "-stderr.txt")).read_bytes()
    assert not err, (label, err)
    return {
        "arguments": arguments,
        "exit": process.returncode,
        "wall_seconds": elapsed,
        "direct_child_peak_rss": usage.ru_maxrss,
        "peak_rss_unit": "bytes" if sys.platform == "darwin" else "KiB",
        "stdout_sha256": hashlib.sha256(out).hexdigest(),
        "instrumented": instrument,
    }, json.loads(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capacities", nargs="+", type=int, default=[4, 8, 16, 22, 23])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["all-selected", "last-rejected"],
        default=["all-selected", "last-rejected"],
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.output = args.output.resolve()
    args.output.mkdir()
    package_root = Path(__file__).resolve().parents[5]
    support = _support(package_root)
    records = []
    environment = {
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=package_root, text=True
        ).strip(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "source_files_sha256": {
            str(path.relative_to(package_root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted((package_root / "src/gda_balancing").rglob("*.py"))
        },
    }

    def save():
        (args.output / "receipt.json").write_text(
            json.dumps(
                {
                    "environment": environment,
                    "records": records,
                    "scope": "Fresh subprocess CLI runs with unchanged system budgets; private nominal capacity/derived Operation bound variants. Bare wall/RSS observations are separate from cProfile/tracemalloc runs. Shared development host, no controlled benchmark environment.",
                },
                indent=2,
            )
            + "\n"
        )

    for capacity in args.capacities:
        for mode in args.modes:
            if capacity == 23 and mode == "last-rejected":
                continue
            directory = args.output / f"n{capacity}-{mode}"
            directory.mkdir()
            candidate = support._PublicCandidate(
                directory, authorities=support._capacity_authorities(capacity)
            )
            source = support._source()
            source["entrypoints"][0]["arguments"][-1]["operand"]["value"] = 1
            candidate.write_source(source)
            build_args = [
                "model",
                "build",
                str(candidate.source),
                "--out",
                str(directory / "build"),
                "--invocation-key",
                "01" * 32,
            ]
            build, receipt = execute(candidate, build_args, "build")
            record = {
                "capacity": capacity,
                "mode": mode,
                "declared_operation_bound": 8 + 11 * capacity,
                "unchanged_event_budget": 256,
                "build": build,
            }
            records.append(record)
            if build["exit"]:
                record["build_refusal"] = receipt
                save()
                continue
            rir_path = next(
                row["locator"]
                for row in receipt["member_locators"]
                if row["logical_name"] == "rir-semantic-payload"
            )
            rir = support._members(receipt)["rir-semantic-payload"]
            record["kernel_identity"] = candidate.kernel["content_identity"]
            record["ldb_identity"] = candidate.ldb["content_identity"]
            record["rir_semantic_identity"] = rir["semantic_identity"]
            items = [0] * capacity
            if mode == "last-rejected":
                items[-1] = 2
            specification = support._specification(
                rir,
                items,
                count=capacity if mode == "all-selected" else capacity - 1,
                order=0 if mode == "all-selected" else 2,
            )
            spec_path = directory / "experiment.json"
            spec_path.write_text(json.dumps(specification))
            check, _ = execute(
                candidate,
                ["experiment", "check", str(spec_path), "--rir", rir_path],
                "check",
            )
            assert check["exit"] == 0, check
            record["check"] = check
            runs = []
            original = None
            for index in range(args.repeats + 1 if capacity <= 22 else 1):
                instrument = index == args.repeats
                run_args = [
                    "experiment",
                    "run",
                    str(spec_path),
                    "--rir",
                    rir_path,
                    "--out",
                    str(directory / f"run-{index}"),
                    "--invocation-key",
                    f"{index + 2:02x}" * 32,
                ]
                observed, outcome = execute(
                    candidate, run_args, f"run-{index}", instrument=instrument
                )
                runs.append(observed)
                if capacity == 23:
                    assert observed["exit"] == 2, outcome
                    record["runtime_refusal"] = outcome
                    break
                assert observed["exit"] == 0, outcome
                members = support._members(outcome)
                observed["member_sha256"] = {
                    row["logical_name"]: hashlib.sha256(
                        Path(row["locator"]).read_bytes()
                    ).hexdigest()
                    for row in outcome["member_locators"]
                }
                if len(runs) > 1:
                    assert observed["member_sha256"] == runs[0]["member_sha256"]
                if original is None:
                    original = members
                else:
                    assert members == original, (
                        "Profiling or fresh invocation changed actual artifact members"
                    )
            record["runs"] = runs
            if original is not None:
                snapshots = original["snapshot-series"]["snapshots"]
                record["actual_node_steps"] = snapshots[-1]["continuation"][
                    "resource_ledger"
                ]["node_steps"]
                record["actual_metrics"] = [
                    {"metric": r["metric"], "value": r["value"]}
                    for r in original["metric-dataset"]["samples"]
                ]
                record["all_member_bytes_equal_between_fresh_runs"] = True
                record["append_construction_prior_cells_derived"] = (
                    capacity * (capacity - 1) // 2
                )
                record["append_construction_slots_derived"] = (
                    capacity * (capacity + 1) // 2
                )
                record["copy_limit"] = (
                    "These two counts describe append-result construction for these known growth prefixes, including the eager discarded final construction. Input typed admission additionally traverses and constructs canonical copies; profile callers measure validation activity across the complete public command. No constant-time or optimized-copy claim."
                )
            save()
    save()


if __name__ == "__main__":
    main()
