"""Run the adapted historical probes against their pinned source baseline.

Use a disposable output directory. This is research tooling, not a CI gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASELINE = "3f68bf3fb26df2ab54351a8ef4e3e167269bdc16"
HERE = Path(__file__).resolve().parent
SEQUENCES = {
    "collections": [("probe.py",)],
    "primitives": [("probe.py",), ("probe_empty.py",)],
    "compiler": [
        ("prepare.py",),
        ("fix_freeze.py",),
        ("run.py", "baseline"),
        ("run.py", "prepared"),
        ("boundary.py", "baseline"),
        ("boundary.py", "prepared"),
        ("alias_witness.py",),
    ],
    "identity": [("probe.py",), ("runtime_probe.py",)],
    "unified": [("probe.py",), ("graph_mutation.py",), ("verify_results.py",)],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--groups", nargs="+", choices=SEQUENCES, default=list(SEQUENCES)
    )
    args = parser.parse_args()
    root, output = args.package_root.resolve(), args.output.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != BASELINE:
        parser.error(f"Expected historical baseline {BASELINE}; got {head}")
    # Do not permit tracked outputs or accidentally use a source directory as scratch.
    if (
        output == root
        or root in output.parents
        or output == HERE
        or HERE in output.parents
    ):
        parser.error("Output must be outside the source and evidence directories")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"baseline": head, "harness": "adapted-paths-only", "runs": []}
    for group in args.groups:
        destination = output / group
        destination.mkdir()
        harness_directory = destination / "harness"
        harness_directory.mkdir()
        for archived in (HERE / group).glob("*.py.txt"):
            (harness_directory / archived.name.removesuffix(".txt")).write_bytes(
                archived.read_bytes()
            )
        env = dict(
            os.environ,
            GDA_PROBE_ROOT=str(root),
            GDA_PROBE_OUT=str(destination),
            PYTHONDONTWRITEBYTECODE="1",
        )
        for index, command in enumerate(SEQUENCES[group]):
            script = harness_directory / command[0]
            log = destination / f"{index:02d}-{script.stem}.log"
            with log.open("w") as stream:
                result = subprocess.run(
                    [sys.executable, str(script), *command[1:]],
                    cwd=root,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            receipt["runs"].append(
                {
                    "group": group,
                    "script": command[0],
                    "arguments": list(command[1:]),
                    "exit_code": result.returncode,
                    "harness_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                }
            )
            (output / "reproduction-receipt.json").write_text(
                json.dumps(receipt, indent=2) + "\n"
            )
            print(group, *command, "exit", result.returncode, flush=True)
            if result.returncode:
                raise SystemExit(f"Probe failed; inspect {log}")
        if group == "compiler":
            baseline = json.loads((destination / "baseline-results.json").read_text())
            prepared = json.loads((destination / "prepared-results.json").read_text())
            assert baseline["examples"].keys() == prepared["examples"].keys()
            for name, value in baseline["examples"].items():
                assert value["sha256"] == prepared["examples"][name]["sha256"]
            for name, value in baseline["negative"].items():
                assert value["refusal"] == prepared["negative"][name]["refusal"]
            assert (
                baseline["projection_budget_1"]["refusal"]
                == prepared["projection_budget_1"]["refusal"]
            )
            a = json.loads((destination / "baseline-boundary.json").read_text())
            b = json.loads((destination / "prepared-boundary.json").read_text())
            assert a["boundaries"] == b["boundaries"]
    receipt["completed"] = True
    (output / "reproduction-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
