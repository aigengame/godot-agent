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
CLAIM_LEDGER_PATH: Final = TEST_ROOT / "schema2-coverage-claims-v1.json"

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
    "authority-cli": ("test_schema2_authority_cli.py",),
    "authority-bootstrap": (
        "test_schema2_bootstrap_authority.py",
        "test_schema2_bootstrap_resources.py",
    ),
    "language-bootstrap": (
        "test_schema2_bootstrap_language.py",
        "test_schema2_formula_cli.py",
    ),
    "model": ("test_schema2_model_cli.py",),
    "experiment": ("test_schema2_experiment_cli.py",),
    "composition": (
        "test_cli_conformance.py",
        "test_schema2_bootstrap_composition.py",
        "test_schema2_model_lowerer_conformance.py",
        "test_schema2_template_cli.py",
    ),
    "smoke": ("test_e2e_cli.py",),
}
REQUIRED_TEST_SHARDS: Final = tuple(name for name in SHARDS if name != "smoke")
PROCESS_TIMEOUT_SECONDS: Final = {
    "required": 480,
    "unfiltered": 900,
}

_AFFECTING_EXACT: Final = {
    ".github/workflows/ci.yml",
    ".github/workflows/release-scope-guard.yml",
    ".github/workflows/release.yml",
    ".release-please-manifest.json",
    "pyproject.toml",
    "release-please-config.json",
    "scripts/release_scope_guard.py",
    "scripts/release_tags.py",
    "tests/test_balancing_ci_wiring.py",
    "tests/test_release_scope_guard.py",
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


def all_test_shards() -> tuple[str, ...]:
    """Return the exact release/nightly matrix, with smoke last."""
    return (*REQUIRED_TEST_SHARDS, "smoke")


def local_parallel_shards() -> tuple[str, ...]:
    """Shards safe to overlap on one developer machine."""
    return REQUIRED_TEST_SHARDS


def local_serial_shards() -> tuple[str, ...]:
    """Process-heavy shards kept exclusive to avoid watchdog contention."""
    return ("smoke",)


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


def verify_claims(
    report_path: Path,
    *,
    ledger_path: Path = CLAIM_LEDGER_PATH,
    baseline_path: Path = BASELINE_PATH,
    current_test_ids: set[str] | None = None,
    current_package_vector_ids: set[str] | None = None,
) -> dict[str, object]:
    """Prove that every declared behavior claim retains its required witnesses."""
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    migration = json.loads(MIGRATION_PATH.read_text(encoding="utf-8"))
    tests = (
        {normalized_node_id(row, migration) for row in collect_node_ids()}
        if current_test_ids is None
        else current_test_ids
    )
    vectors = (
        package_vector_ids()
        if current_package_vector_ids is None
        else current_package_vector_ids
    )
    rows: list[dict[str, object]] = []
    seen_claim_ids: set[str] = set()
    duplicate_claim_ids: set[str] = set()
    for claim in ledger["claims"]:
        claim_id = claim["id"]
        if claim_id in seen_claim_ids:
            duplicate_claim_ids.add(claim_id)
        seen_claim_ids.add(claim_id)
        subject_declaration = claim.get("subjects", [])
        if isinstance(subject_declaration, list):
            subjects = subject_declaration
            subject_source = None
        elif subject_declaration == {"source": "baseline.package_vector_ids"}:
            subjects = baseline["package_vector_ids"]
            subject_source = "package_vector_ids"
        else:
            raise ValueError(
                f"unknown claim subject declaration: {subject_declaration!r}"
            )
        witnesses: list[dict[str, str]] = []
        for declaration in claim["witnesses"]:
            if "test_id" in declaration:
                witnesses.append(declaration)
                continue
            template = declaration["test_id_template"]
            witnesses.extend(
                {
                    "test_id": template.format(subject=subject, variant=variant),
                    "independence_domain": declaration["independence_domain"],
                }
                for subject in subjects
                for variant in declaration["variants"]
            )
        missing_witnesses = sorted(
            witness["test_id"]
            for witness in witnesses
            if normalized_node_id(witness["test_id"], migration) not in tests
        )
        live_domains = {
            witness["independence_domain"]
            for witness in witnesses
            if normalized_node_id(witness["test_id"], migration) in tests
        }
        minimum = claim["minimum_independent_witnesses"]
        missing_subjects = sorted(
            subject
            for subject in subjects
            if subject_source == "package_vector_ids" and subject not in vectors
        )
        closed = (
            not missing_witnesses
            and not missing_subjects
            and len(live_domains) >= minimum
        )
        rows.append(
            {
                "claim_id": claim_id,
                "boundary": claim["boundary"],
                "subject_count": len(subjects),
                "witness_count": len(witnesses),
                "missing_subjects": missing_subjects,
                "missing_witnesses": missing_witnesses,
                "independent_witness_count": len(live_domains),
                "minimum_independent_witnesses": minimum,
                "closed": closed,
            }
        )
    report: dict[str, object] = {
        "claim_count": len(rows),
        "subject_claim_count": sum(int(row["subject_count"]) for row in rows),
        "closed_claim_count": sum(bool(row["closed"]) for row in rows),
        "duplicate_claim_ids": sorted(duplicate_claim_ids),
        "claims": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if duplicate_claim_ids or any(not row["closed"] for row in rows):
        raise SystemExit("gda-balancing coverage claim closure failed")
    return report


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
        node_id = junit_node_id(testcase)
        filename = node_id.partition("::")[0]
        duration = float(testcase.attrib.get("time", "0"))
        row = per_file.setdefault(filename, {"count": 0, "seconds": 0.0})
        row["count"] = int(row["count"]) + 1
        row["seconds"] = round(float(row["seconds"]) + duration, 6)
        tests.append(
            {
                "node": node_id,
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


def aggregate_junit(
    junit_dir: Path,
    report_path: Path,
    *,
    expected_shards: tuple[str, ...] = tuple(SHARDS),
    expected_test_ids: set[str] | None = None,
) -> dict[str, object]:
    """Close the exact shard union and publish cumulative executed-test time."""
    migration = json.loads(MIGRATION_PATH.read_text(encoding="utf-8"))
    expected_tests = (
        {normalized_node_id(row, migration) for row in collect_node_ids()}
        if expected_test_ids is None
        else expected_test_ids
    )
    paths_by_shard: dict[str, list[Path]] = {}
    for path in junit_dir.rglob("junit-*.xml"):
        shard = path.stem.removeprefix("junit-")
        paths_by_shard.setdefault(shard, []).append(path)
    missing_shards = sorted(set(expected_shards) - set(paths_by_shard))
    unexpected_shards = sorted(set(paths_by_shard) - set(expected_shards))
    duplicate_shard_reports = sorted(
        shard for shard, paths in paths_by_shard.items() if len(paths) != 1
    )
    seen: set[str] = set()
    duplicate_tests: set[str] = set()
    failed_tests: set[str] = set()
    shard_rows: dict[str, dict[str, float | int]] = {}
    for shard in expected_shards:
        paths = paths_by_shard.get(shard, [])
        if len(paths) != 1:
            continue
        test_count = 0
        test_seconds = 0.0
        for testcase in ElementTree.parse(paths[0]).getroot().iter("testcase"):
            node_id = normalized_node_id(junit_node_id(testcase), migration)
            if node_id in seen:
                duplicate_tests.add(node_id)
            seen.add(node_id)
            test_count += 1
            test_seconds += float(testcase.attrib.get("time", "0"))
            if (
                testcase.find("failure") is not None
                or testcase.find("error") is not None
            ):
                failed_tests.add(node_id)
        shard_rows[shard] = {
            "test_count": test_count,
            "test_seconds": round(test_seconds, 6),
        }
    missing_tests = expected_tests - seen
    unexpected_tests = seen - expected_tests
    closed = not any(
        (
            missing_shards,
            unexpected_shards,
            duplicate_shard_reports,
            duplicate_tests,
            failed_tests,
            missing_tests,
            unexpected_tests,
        )
    )
    report: dict[str, object] = {
        "closed": closed,
        "test_count": len(seen),
        "test_seconds": round(
            sum(float(row["test_seconds"]) for row in shard_rows.values()), 6
        ),
        "shards": shard_rows,
        "missing_shards": missing_shards,
        "unexpected_shards": unexpected_shards,
        "duplicate_shard_reports": duplicate_shard_reports,
        "duplicate_tests": sorted(duplicate_tests),
        "failed_tests": sorted(failed_tests),
        "missing_tests": sorted(missing_tests),
        "unexpected_tests": sorted(unexpected_tests),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not closed:
        raise SystemExit("gda-balancing aggregate test closure failed")
    return report


def junit_node_id(testcase: ElementTree.Element) -> str:
    """Reconstruct pytest's node id from one xunit2 testcase."""
    classname = testcase.attrib.get("classname", "")
    name = testcase.attrib.get("name")
    if not name:
        raise ValueError(f"JUnit testcase has no name: {classname!r}")
    if not classname:
        module_parts = name.split(".")
        if any(not part for part in module_parts) or not module_parts[-1].startswith(
            "test_"
        ):
            raise ValueError(
                f"JUnit collection testcase has no pytest test module: {name!r}"
            )
        return "/".join(module_parts) + ".py"
    parts = classname.split(".")
    module_index = next(
        (index for index, part in enumerate(parts) if part.startswith("test_")),
        None,
    )
    if module_index is None:
        raise ValueError(f"JUnit testcase has no pytest test module: {classname!r}")
    path = "/".join(parts[: module_index + 1]) + ".py"
    tail = parts[module_index + 1 :]
    return "::".join((path, *tail, name))


def verify_outcomes(
    junit_path: Path,
    report_path: Path,
    baseline_path: Path = BASELINE_PATH,
) -> dict[str, object]:
    """Reject new skips/xfails and report explicit capability-inapplicable passes."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    migration = json.loads(MIGRATION_PATH.read_text(encoding="utf-8"))
    allowed_skips = set(baseline["allowed_skipped_test_ids"])
    skipped: set[str] = set()
    xfailed: set[str] = set()
    not_applicable: dict[str, str] = {}
    root = ElementTree.parse(junit_path).getroot()
    for testcase in root.iter("testcase"):
        node_id = normalized_node_id(junit_node_id(testcase), migration)
        properties = {
            row.attrib.get("name"): row.attrib.get("value", "")
            for row in testcase.findall("./properties/property")
        }
        if properties.get("gda-balancing.applicability") == "not-applicable":
            not_applicable[node_id] = properties.get(
                "gda-balancing.applicability-reason", ""
            )
        outcome = testcase.find("skipped")
        if outcome is None:
            continue
        if outcome.attrib.get("type") == "pytest.xfail":
            xfailed.add(node_id)
        else:
            skipped.add(node_id)
    unexpected_skips = skipped - allowed_skips
    report: dict[str, object] = {
        "allowed_baseline_skip_count": len(allowed_skips),
        "not_applicable_tests": dict(sorted(not_applicable.items())),
        "skipped_tests": sorted(skipped),
        "xfailed_tests": sorted(xfailed),
        "unexpected_skipped_tests": sorted(unexpected_skips),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if unexpected_skips or xfailed:
        raise SystemExit("gda-balancing test outcome closure failed")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    classify = subcommands.add_parser("classify")
    classify.add_argument("paths", nargs="*")
    classify.add_argument(
        "--all",
        action="store_true",
        help="select the full matrix without reading changed paths from stdin",
    )
    shard = subcommands.add_parser("shard-paths")
    shard.add_argument("shard", choices=tuple(SHARDS))
    subcommands.add_parser("required-test-shards")
    subcommands.add_parser("all-test-shards")
    budget = subcommands.add_parser("process-timeout")
    budget.add_argument("suite", choices=tuple(PROCESS_TIMEOUT_SECONDS))
    verify = subcommands.add_parser("verify-inventory")
    verify.add_argument("--report", type=Path, required=True)
    claims = subcommands.add_parser("verify-claims")
    claims.add_argument("--report", type=Path, required=True)
    outcomes = subcommands.add_parser("verify-outcomes")
    outcomes.add_argument("--junit", type=Path, required=True)
    outcomes.add_argument("--report", type=Path, required=True)
    summarize = subcommands.add_parser("summarize-junit")
    summarize.add_argument("--junit", type=Path, required=True)
    summarize.add_argument("--report", type=Path, required=True)
    aggregate = subcommands.add_parser("aggregate-junit")
    aggregate.add_argument("--junit-dir", type=Path, required=True)
    aggregate.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "classify":
        if args.all and args.paths:
            raise SystemExit("classify --all does not accept paths")
        paths = (
            []
            if args.all
            else args.paths or [line.strip() for line in sys.stdin if line.strip()]
        )
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
    if args.command == "aggregate-junit":
        report = aggregate_junit(args.junit_dir, args.report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.command == "required-test-shards":
        print(json.dumps(REQUIRED_TEST_SHARDS))
        return 0
    if args.command == "all-test-shards":
        print(json.dumps(all_test_shards()))
        return 0
    if args.command == "process-timeout":
        print(PROCESS_TIMEOUT_SECONDS[args.suite])
        return 0
    if args.command == "verify-outcomes":
        report = verify_outcomes(args.junit, args.report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.command == "verify-inventory":
        report = verify_inventory(args.report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.command == "verify-claims":
        report = verify_claims(args.report)
        print(json.dumps(report, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled CI policy command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
