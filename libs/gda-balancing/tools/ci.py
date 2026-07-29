#!/usr/bin/env python3
"""One authority for gda-balancing CI selection, shards, and inventory closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Final

MEMBER_ROOT: Final = Path(__file__).resolve().parents[1]
REPO_ROOT: Final = Path(__file__).resolve().parents[3]
TEST_ROOT: Final = MEMBER_ROOT / "tests"
BASELINE_PATH: Final = TEST_ROOT / "schema2-test-inventory-v1.json"
MIGRATION_PATH: Final = TEST_ROOT / "schema2-bootstrap-migration-map.json"

SHARDS: Final[dict[str, tuple[str, ...]]] = {
    "fast": (
        "test_ci_policy.py",
        "test_dependency_graph.py",
        "test_emit.py",
        "test_engine_parity.py",
        "test_envelope_schema.py",
        "test_format_roundtrip.py",
        "test_formula_seam.py",
        "test_isolation.py",
        "test_schema2_authority_lifecycle.py",
        "test_schema2_canonical.py",
        "test_schema2_migration_cli.py",
        "test_schema_command.py",
        "test_semantic_catalog.py",
        "test_validate_vectors.py",
        "test_version_bundle.py",
        "test_version_command.py",
    ),
    "authority": (
        "test_schema2_authority_cli.py",
        "test_schema2_bootstrap_authority.py",
        "test_schema2_bootstrap_resources.py",
    ),
    "language": (
        "test_schema2_bootstrap_language.py",
        "test_schema2_model_cli.py",
    ),
    "composition": (
        "test_cli_conformance.py",
        "test_schema2_bootstrap_composition.py",
        "test_schema2_experiment_cli.py",
        "test_schema2_model_lowerer_conformance.py",
        "test_schema2_template_cli.py",
    ),
    "smoke": ("test_e2e_cli.py",),
}

_AFFECTING_EXACT: Final = {
    ".github/workflows/ci.yml",
    ".github/workflows/release-scope-guard.yml",
    ".github/workflows/release.yml",
    ".release-please-manifest.json",
    "pyproject.toml",
    "release-please-config.json",
    "scripts/release_tags.py",
    "tests/test_release_tags.py",
    "uv.lock",
}
_AFFECTING_PREFIXES: Final = (
    ".github/actions/setup-python-env/",
    "libs/gda-balancing/",
)
_UNRELATED_EXACT: Final = {
    "AGENTS.md",
    "CONTEXT-MAP.md",
    "CONTEXT.md",
    "README.md",
    "RULES.md",
    "STATE.md",
}
_UNRELATED_PREFIXES: Final = (
    ".agents/",
    ".codex/",
    "docs/",
    "examples/",
    "src/",
    "tests/",
)


def classify_path(path: str) -> str:
    """Classify one repository-relative path; unknown fails closed to affecting."""
    normalized = path.strip().removeprefix("./")
    if normalized in _AFFECTING_EXACT or normalized.startswith(_AFFECTING_PREFIXES):
        return "affecting"
    if normalized in _UNRELATED_EXACT or normalized.startswith(_UNRELATED_PREFIXES):
        return "unrelated"
    return "unknown"


def balancing_required(paths: list[str]) -> bool:
    """Run the full matrix unless every changed path is explicitly unrelated."""
    return not paths or any(classify_path(path) != "unrelated" for path in paths)


def shard_paths(shard: str) -> tuple[Path, ...]:
    return tuple(TEST_ROOT / name for name in SHARDS[shard])


def normalized_node_id(node_id: str, migration: dict[str, object]) -> str:
    """Normalize only declared file moves while preserving parameters and classes."""
    path, separator, test = node_id.partition("::")
    if not separator:
        return node_id
    filename = Path(path).name
    moved_tests = migration["tests"]
    if not isinstance(moved_tests, dict):
        raise ValueError("migration map tests must be an object")
    function = test.rsplit("::", 1)[-1].split("[", 1)[0]
    if moved_tests.get(function) == filename:
        source = migration["source"]
        if not isinstance(source, str):
            raise ValueError("migration map source must be a string")
        path = str(Path(path).with_name(source))
    return f"{path}::{test}"


def collect_node_ids(paths: tuple[Path, ...] | None = None) -> set[str]:
    selected = paths or (TEST_ROOT,)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *(str(path) for path in selected),
        "--collect-only",
        "-q",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT / "libs/gda-balancing",
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    }


def package_vector_ids() -> set[str]:
    authority_root = (
        REPO_ROOT / "libs/gda-balancing/src/gda_balancing/schema2/authorities/packages"
    )
    rows: set[str] = set()
    for path in sorted(authority_root.rglob("*.conformance-vectors.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        coordinate = f"{value['package_id']}@{value['package_version']}"
        for vector in value["vector_definitions"]:
            rows.add(f"{coordinate}:{vector['id']}")
    return rows


def digest(rows: set[str]) -> str:
    encoded = ("\n".join(sorted(rows)) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_inventory(report_path: Path) -> dict[str, object]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    migration = json.loads(MIGRATION_PATH.read_text(encoding="utf-8"))
    full_raw = collect_node_ids()
    full = {normalized_node_id(row, migration) for row in full_raw}
    shard_rows = {
        name: {
            normalized_node_id(row, migration)
            for row in collect_node_ids(shard_paths(name))
        }
        for name in SHARDS
    }
    union: set[str] = set()
    overlaps: set[str] = set()
    for rows in shard_rows.values():
        overlaps.update(union & rows)
        union.update(rows)

    baseline_tests = set(baseline["test_ids"])
    baseline_vectors = set(baseline["package_vector_ids"])
    current_vectors = package_vector_ids()
    missing_tests = baseline_tests - full
    missing_vectors = baseline_vectors - current_vectors
    uncovered = full - union
    unexpected = union - full
    report: dict[str, object] = {
        "baseline_test_count": len(baseline_tests),
        "baseline_test_digest": digest(baseline_tests),
        "current_test_count": len(full),
        "current_test_digest": digest(full),
        "baseline_package_vector_count": len(baseline_vectors),
        "current_package_vector_count": len(current_vectors),
        "shards": {
            name: {"count": len(rows), "digest": digest(rows)}
            for name, rows in shard_rows.items()
        },
        "missing_tests": sorted(missing_tests),
        "missing_package_vectors": sorted(missing_vectors),
        "overlapping_tests": sorted(overlaps),
        "uncovered_tests": sorted(uncovered),
        "unexpected_shard_tests": sorted(unexpected),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if any(
        (
            missing_tests,
            missing_vectors,
            overlaps,
            uncovered,
            unexpected,
        )
    ):
        raise SystemExit("gda-balancing logical inventory closure failed")
    return report


def summarize_junit(junit_path: Path, report_path: Path) -> dict[str, object]:
    """Publish stable per-file and slow-test timing from one shard's JUnit."""
    root = ElementTree.parse(junit_path).getroot()
    per_file: dict[str, dict[str, float | int]] = {}
    tests: list[dict[str, str | float]] = []
    for testcase in root.iter("testcase"):
        classname = testcase.attrib.get("classname", "unknown")
        module_parts: list[str] = []
        for part in classname.split("."):
            module_parts.append(part)
            if part.startswith("test_"):
                break
        filename = "/".join(module_parts) + ".py"
        duration = float(testcase.attrib.get("time", "0"))
        row = per_file.setdefault(filename, {"count": 0, "seconds": 0.0})
        row["count"] = int(row["count"]) + 1
        row["seconds"] = round(float(row["seconds"]) + duration, 6)
        tests.append(
            {
                "node": f"{classname}::{testcase.attrib.get('name', 'unknown')}",
                "seconds": duration,
            }
        )
    report: dict[str, object] = {
        "per_file": dict(sorted(per_file.items())),
        "slow_tests": sorted(
            tests,
            key=lambda row: float(row["seconds"]),
            reverse=True,
        )[:50],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    classify = subcommands.add_parser("classify")
    classify.add_argument("paths", nargs="*")
    shard = subcommands.add_parser("shard-paths")
    shard.add_argument("shard", choices=tuple(SHARDS))
    verify = subcommands.add_parser("verify-inventory")
    verify.add_argument("--report", type=Path, required=True)
    summarize = subcommands.add_parser("summarize-junit")
    summarize.add_argument("--junit", type=Path, required=True)
    summarize.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "classify":
        paths = args.paths or [line.strip() for line in sys.stdin if line.strip()]
        required = balancing_required(paths)
        print(json.dumps({"required": required, "paths": paths}, sort_keys=True))
        return 0
    if args.command == "shard-paths":
        print(" ".join(str(path) for path in shard_paths(args.shard)))
        return 0
    if args.command == "summarize-junit":
        report = summarize_junit(args.junit, args.report)
        print(json.dumps(report, sort_keys=True))
        return 0
    report = verify_inventory(args.report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
