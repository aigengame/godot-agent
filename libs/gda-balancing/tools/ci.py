#!/usr/bin/env python3
"""One authority for gda-balancing CI selection, shards, and inventory closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path
from typing import Final

MEMBER_ROOT: Final = Path(__file__).resolve().parents[1]
REPO_ROOT: Final = Path(__file__).resolve().parents[3]
TEST_ROOT: Final = MEMBER_ROOT / "tests"
BASELINE_PATH: Final = TEST_ROOT / "schema2-test-inventory-v1.json"
MIGRATION_PATH: Final = TEST_ROOT / "schema2-bootstrap-migration-map.json"
CLAIM_LEDGER_PATH: Final = TEST_ROOT / "schema2-coverage-claims-v1.json"
ACCEPTED_CLAIM_MANIFEST_PATH: Final = (
    TEST_ROOT / "schema2-coverage-claims-accepted-v1.json"
)

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


def subprocess_text(output: str | bytes | None) -> str:
    """Normalize captured output, including TimeoutExpired's byte payloads."""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


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


def canonical_json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def claim_contract_digest(ledger: dict[str, object]) -> str:
    """Hash the complete versioned claim contract, excluding prose metadata."""
    return canonical_json_digest(
        {
            "version": ledger.get("version"),
            "claims": ledger.get("claims"),
        }
    )


def claim_contract_migration_closure(
    *,
    accepted_digest: object,
    current_digest: str,
    migrations: object,
) -> dict[str, object]:
    """Require each claim-contract change to traverse an explicit review record."""
    problems: list[str] = []
    if not isinstance(accepted_digest, str) or len(accepted_digest) != 64:
        problems.append("accepted_claim_contract_digest must be a SHA-256 digest")
        pointer = ""
    else:
        pointer = accepted_digest
    if not isinstance(migrations, list):
        problems.append("claim_contract_migrations must be a list")
        migrations = []
    rows: list[dict[str, object]] = []
    for index, declaration in enumerate(migrations):
        row_problems: list[str] = []
        if not isinstance(declaration, dict):
            row_problems.append("migration must be an object")
            declaration = {}
        from_digest = declaration.get("from_digest")
        to_digest = declaration.get("to_digest")
        issue = declaration.get("issue")
        reason = declaration.get("reason")
        if from_digest != pointer:
            row_problems.append("from_digest does not continue the accepted chain")
        if not isinstance(to_digest, str) or len(to_digest) != 64:
            row_problems.append("to_digest must be a SHA-256 digest")
        if not isinstance(issue, str) or not issue.strip():
            row_problems.append("issue must be non-empty")
        if not isinstance(reason, str) or not reason.strip():
            row_problems.append("reason must be non-empty")
        if not row_problems:
            pointer = to_digest
        rows.append(
            {
                "index": index,
                "from_digest": from_digest,
                "to_digest": to_digest,
                "issue": issue,
                "reason": reason,
                "problems": row_problems,
                "closed": not row_problems,
            }
        )
        problems.extend(f"migration {index}: {problem}" for problem in row_problems)
    if pointer != current_digest:
        problems.append("migration chain does not end at the current claim contract")
    return {
        "accepted_digest": accepted_digest,
        "current_digest": current_digest,
        "migrations": rows,
        "problems": problems,
        "closed": not problems,
    }


def mapped_independence_domain(domain: str, mapping: object) -> str | None:
    if mapping == "identity":
        return domain
    if isinstance(mapping, dict):
        target = mapping.get(domain)
        return target if isinstance(target, str) else None
    return None


def accepted_claim_mapping_closure(
    *,
    accepted_manifest: dict[str, object],
    current_claims: list[dict[str, object]],
    mappings: object,
    baseline_package_vector_ids: set[str],
    current_package_vector_ids: set[str],
) -> dict[str, object]:
    """Prove every accepted claim subject maps to an equal-or-stronger witness."""
    problems: list[str] = []
    accepted_claims = accepted_manifest.get("claims")
    if not isinstance(accepted_claims, list):
        return {
            "claims": [],
            "problems": ["accepted claims must be a list"],
            "closed": False,
        }
    if not isinstance(mappings, list):
        return {
            "claims": [],
            "problems": ["accepted_claim_mappings must be a list"],
            "closed": False,
        }
    current_by_id = {
        str(claim["claim_id"]): claim
        for claim in current_claims
        if isinstance(claim.get("claim_id"), str)
    }
    mappings_by_id: dict[str, dict[str, object]] = {}
    duplicate_mapping_ids: set[str] = set()
    for declaration in mappings:
        if not isinstance(declaration, dict) or not isinstance(
            declaration.get("from_claim_id"), str
        ):
            problems.append("each accepted claim mapping needs from_claim_id")
            continue
        from_claim_id = declaration["from_claim_id"]
        if from_claim_id in mappings_by_id:
            duplicate_mapping_ids.add(from_claim_id)
        mappings_by_id[from_claim_id] = declaration
    if duplicate_mapping_ids:
        problems.append(
            "duplicate accepted claim mappings: "
            + ", ".join(sorted(duplicate_mapping_ids))
        )

    rows: list[dict[str, object]] = []
    accepted_ids: set[str] = set()
    for accepted in accepted_claims:
        if not isinstance(accepted, dict) or not isinstance(accepted.get("id"), str):
            problems.append("each accepted claim needs an id")
            continue
        claim_id = accepted["id"]
        accepted_ids.add(claim_id)
        row_problems: list[str] = []
        subject_declaration = accepted.get("subjects")
        if isinstance(subject_declaration, list) and all(
            isinstance(subject, str) for subject in subject_declaration
        ):
            accepted_subjects = list(subject_declaration)
        elif isinstance(subject_declaration, dict) and isinstance(
            subject_declaration.get("source"), str
        ):
            source = subject_declaration["source"]
            if source == "baseline.package_vector_ids":
                accepted_subjects = sorted(baseline_package_vector_ids)
            else:
                accepted_subjects = authority_claim_subjects(
                    source,
                    current_package_vector_ids=current_package_vector_ids,
                )
            if subject_declaration.get("accepted_count") != len(accepted_subjects):
                row_problems.append("accepted subject count drifted")
            if subject_declaration.get("accepted_digest") != digest(
                set(accepted_subjects)
            ):
                row_problems.append("accepted subject digest drifted")
        else:
            accepted_subjects = []
            row_problems.append("accepted subjects have an invalid shape")

        mapping = mappings_by_id.get(claim_id)
        target_claim: dict[str, object] | None = None
        if mapping is None:
            row_problems.append("accepted claim has no explicit mapping")
        else:
            target_id = mapping.get("to_claim_id")
            if not isinstance(target_id, str):
                row_problems.append("mapping needs to_claim_id")
            else:
                target_claim = current_by_id.get(target_id)
                if target_claim is None:
                    row_problems.append("mapped current claim does not exist")

        subject_targets: dict[str, str] = {}
        if mapping is not None:
            subject_mapping = mapping.get("subject_mapping")
            if subject_mapping == "identity":
                subject_targets = {subject: subject for subject in accepted_subjects}
            elif isinstance(subject_mapping, list):
                for subject_row in subject_mapping:
                    if not isinstance(subject_row, dict):
                        row_problems.append("subject mapping must contain objects")
                        continue
                    from_subject = subject_row.get("from_subject")
                    to_subject = subject_row.get("to_subject")
                    if not isinstance(from_subject, str) or not isinstance(
                        to_subject, str
                    ):
                        row_problems.append(
                            "subject mapping needs from_subject and to_subject"
                        )
                        continue
                    if from_subject in subject_targets:
                        row_problems.append(
                            f"accepted subject mapped more than once: {from_subject}"
                        )
                    subject_targets[from_subject] = to_subject
            else:
                row_problems.append("subject_mapping must be identity or a list")
        unmapped_subjects = set(accepted_subjects) - set(subject_targets)
        extra_subjects = set(subject_targets) - set(accepted_subjects)
        if unmapped_subjects:
            row_problems.append(
                "unmapped accepted subjects: " + ", ".join(sorted(unmapped_subjects))
            )
        if extra_subjects:
            row_problems.append(
                "unknown accepted subjects in mapping: "
                + ", ".join(sorted(extra_subjects))
            )

        accepted_minimum = accepted.get("minimum_independent_witnesses")
        if target_claim is not None:
            current_minimum = target_claim.get("minimum_independent_witnesses")
            if (
                isinstance(accepted_minimum, bool)
                or not isinstance(accepted_minimum, int)
                or isinstance(current_minimum, bool)
                or not isinstance(current_minimum, int)
                or current_minimum < accepted_minimum
            ):
                row_problems.append("mapped minimum is weaker than accepted")
            current_subjects = {
                str(subject["subject"]): subject
                for subject in target_claim.get("subjects", [])
                if isinstance(subject, dict) and "subject" in subject
            }
        else:
            current_subjects = {}

        domain_mapping = mapping.get("independence_domain_mapping") if mapping else None
        if domain_mapping != "identity" and not (
            isinstance(domain_mapping, dict)
            and all(
                isinstance(source, str) and isinstance(target, str)
                for source, target in domain_mapping.items()
            )
        ):
            row_problems.append(
                "independence_domain_mapping must be identity or a string map"
            )
        required_domains = accepted.get("required_independence_domains")
        if not isinstance(required_domains, dict):
            row_problems.append("accepted independence domains must be an object")
            required_domains = {}
        for accepted_subject in accepted_subjects:
            target_subject = subject_targets.get(accepted_subject)
            current_subject = current_subjects.get(str(target_subject))
            if current_subject is None:
                row_problems.append(
                    f"mapped subject does not exist: {accepted_subject}"
                )
                continue
            domains = required_domains.get(
                accepted_subject, required_domains.get("*", [])
            )
            if not isinstance(domains, list) or not all(
                isinstance(domain, str) for domain in domains
            ):
                row_problems.append(
                    f"accepted domains have an invalid shape: {accepted_subject}"
                )
                continue
            expected_domains = {
                mapped_independence_domain(domain, domain_mapping) for domain in domains
            }
            if None in expected_domains:
                row_problems.append(
                    f"accepted domain has no mapping: {accepted_subject}"
                )
                continue
            observed_domains = set(current_subject.get("independence_domains", []))
            if not expected_domains <= observed_domains:
                row_problems.append(
                    f"mapped independence domains are weaker: {accepted_subject}"
                )
        rows.append(
            {
                "accepted_claim_id": claim_id,
                "mapped_claim_id": mapping.get("to_claim_id") if mapping else None,
                "accepted_subject_count": len(accepted_subjects),
                "problems": sorted(set(row_problems)),
                "closed": not row_problems,
            }
        )
        problems.extend(f"{claim_id}: {problem}" for problem in row_problems)

    unknown_mapping_ids = set(mappings_by_id) - accepted_ids
    if unknown_mapping_ids:
        problems.append(
            "mappings reference unknown accepted claims: "
            + ", ".join(sorted(unknown_mapping_ids))
        )
    return {
        "claims": rows,
        "problems": sorted(set(problems)),
        "closed": not problems,
    }


def authority_claim_subjects(
    source: str, *, current_package_vector_ids: set[str]
) -> list[str]:
    """Resolve claim subjects from the current admitted machine authority."""
    if source == "authority.package_vector_ids":
        return sorted(current_package_vector_ids)
    if source == "surface.public_authority_command_names":
        from gda_balancing.commands import REGISTRY

        return sorted(
            " ".join(part for part in (descriptor.group, descriptor.command) if part)
            for descriptor in REGISTRY
            if (descriptor.group, descriptor.command) != (None, "manifest")
        )

    from gda_balancing.schema2.authority import packaged_authority_context

    kernel, language_bundle = packaged_authority_context().mutable_pair()
    if source == "authority.kernel_law_ids":
        return sorted(law["id"] for law in kernel["admission"]["laws"])
    if source == "authority.language_rule_ids":
        return sorted(rule["id"] for rule in language_bundle["language"]["rules"])
    if source == "authority.diagnostic_reason_ids":
        return sorted(reason["id"] for reason in language_bundle["language"]["reasons"])
    if source == "authority.model_program_vector_ids":
        return sorted(
            vector["id"]
            for vector in language_bundle["vectors"]
            if "source_fixture" in vector
        )
    raise ValueError(f"unknown authority claim subject source: {source!r}")


def inventory_migration_closure(
    migration: dict[str, object],
    current_test_ids: set[str],
    *,
    subject_resolver: Callable[[str], list[str]],
) -> dict[str, object]:
    """Prove each declared one-to-many baseline-test migration exactly."""
    source = migration["source"]
    expansions = migration.get("expansions", {})
    if not isinstance(source, str) or not isinstance(expansions, dict):
        raise ValueError("inventory migration source/expansions have invalid shapes")
    represented: set[str] = set()
    rows: list[dict[str, object]] = []
    for test_name, declaration in expansions.items():
        if not isinstance(test_name, str) or not isinstance(declaration, dict):
            raise ValueError("inventory expansion must map test names to objects")
        target = declaration["target"]
        subject_source = declaration["subject_source"]
        template = declaration["test_id_template"]
        variants = declaration["variants"]
        if (
            not isinstance(target, str)
            or not isinstance(subject_source, str)
            or not isinstance(template, str)
            or not isinstance(variants, list)
            or not all(isinstance(variant, str) for variant in variants)
        ):
            raise ValueError(f"invalid inventory expansion: {declaration!r}")
        subjects = subject_resolver(subject_source)
        expected = {
            normalized_node_id(
                template.format(
                    target=target,
                    test=test_name,
                    subject=subject,
                    variant=variant,
                ),
                migration,
            )
            for subject in subjects
            for variant in variants
        }
        prefix = f"tests/{source}::{test_name}["
        actual = {row for row in current_test_ids if row.startswith(prefix)}
        missing = expected - actual
        unexpected = actual - expected
        closed = bool(expected) and not missing and not unexpected
        baseline_test_id = f"tests/{source}::{test_name}"
        if closed:
            represented.add(baseline_test_id)
        rows.append(
            {
                "baseline_test_id": baseline_test_id,
                "expected_current_test_count": len(expected),
                "missing_current_tests": sorted(missing),
                "unexpected_current_tests": sorted(unexpected),
                "closed": closed,
            }
        )
    return {
        "represented_baseline_tests": sorted(represented),
        "expansions": rows,
        "closed": all(bool(row["closed"]) for row in rows),
    }


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
    invalid_claim_structures: list[dict[str, object]] = []
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
            subject_source = "baseline.package_vector_ids"
        elif (
            isinstance(subject_declaration, dict)
            and isinstance(subject_declaration.get("source"), str)
            and subject_declaration["source"].startswith(("authority.", "surface."))
        ):
            subject_source = subject_declaration["source"]
            subjects = authority_claim_subjects(
                subject_source,
                current_package_vector_ids=vectors,
            )
        else:
            raise ValueError(
                f"unknown claim subject declaration: {subject_declaration!r}"
            )
        declarations = claim.get("witnesses")
        minimum = claim.get("minimum_independent_witnesses")
        structure_problems: list[str] = []
        if not subjects or not all(
            isinstance(subject, str) and subject for subject in subjects
        ):
            structure_problems.append("subjects must resolve to at least one string")
        if not isinstance(declarations, list) or not declarations:
            structure_problems.append("witnesses must contain at least one declaration")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            structure_problems.append(
                "minimum_independent_witnesses must be an integer >= 1"
            )
        if structure_problems:
            invalid_claim_structures.append(
                {
                    "claim_id": claim_id,
                    "problems": sorted(structure_problems),
                }
            )
            rows.append(
                {
                    "claim_id": claim_id,
                    "boundary": claim["boundary"],
                    "subject_count": len(subjects),
                    "witness_count": 0,
                    "missing_subjects": [],
                    "missing_witnesses": [],
                    "uncovered_subjects": sorted(str(subject) for subject in subjects),
                    "invalid_covered_subjects": [],
                    "conflicting_witness_domains": [],
                    "subjects": [],
                    "minimum_independent_witnesses": minimum,
                    "closed": False,
                }
            )
            continue
        witnesses: list[dict[str, object]] = []
        invalid_covered_subjects: set[str] = set()
        for declaration in declarations:
            if "test_id" in declaration:
                coverage = declaration.get("covers")
                if coverage == "*":
                    covered_subjects = set(subjects)
                elif isinstance(coverage, list) and all(
                    isinstance(subject, str) for subject in coverage
                ):
                    covered_subjects = set(coverage)
                else:
                    raise ValueError(
                        f"fixed claim witness must declare covers: {declaration!r}"
                    )
                invalid_covered_subjects.update(covered_subjects - set(subjects))
                witnesses.append(
                    {
                        "test_id": declaration["test_id"],
                        "independence_domain": declaration["independence_domain"],
                        "covers": covered_subjects,
                    }
                )
                continue
            template = declaration["test_id_template"]
            variants = declaration.get("variants", [None])
            witnesses.extend(
                {
                    "test_id": template.format(
                        subject=subject,
                        variant="" if variant is None else variant,
                    ),
                    "independence_domain": declaration["independence_domain"],
                    "covers": {subject},
                }
                for subject in subjects
                for variant in variants
            )
        witness_domains: dict[str, str] = {}
        conflicting_witness_domains: set[str] = set()
        for witness in witnesses:
            test_id = str(witness["test_id"])
            domain = str(witness["independence_domain"])
            previous = witness_domains.setdefault(test_id, domain)
            if previous != domain:
                conflicting_witness_domains.add(test_id)
        missing_witnesses = sorted(
            str(witness["test_id"])
            for witness in witnesses
            if normalized_node_id(str(witness["test_id"]), migration) not in tests
        )
        subject_rows = []
        for subject in subjects:
            live_domains = {
                str(witness["independence_domain"])
                for witness in witnesses
                if subject in witness["covers"]
                and normalized_node_id(str(witness["test_id"]), migration) in tests
            }
            subject_rows.append(
                {
                    "subject": subject,
                    "independence_domains": sorted(live_domains),
                    "independent_witness_count": len(live_domains),
                    "minimum_independent_witnesses": minimum,
                    "closed": len(live_domains) >= minimum,
                }
            )
        uncovered_subjects = sorted(
            str(row["subject"]) for row in subject_rows if not row["closed"]
        )
        missing_subjects = sorted(
            subject
            for subject in subjects
            if subject_source == "baseline.package_vector_ids"
            and subject not in vectors
        )
        closed = (
            not missing_witnesses
            and not missing_subjects
            and not uncovered_subjects
            and not invalid_covered_subjects
            and not conflicting_witness_domains
        )
        rows.append(
            {
                "claim_id": claim_id,
                "boundary": claim["boundary"],
                "subject_count": len(subjects),
                "witness_count": len(witnesses),
                "missing_subjects": missing_subjects,
                "missing_witnesses": missing_witnesses,
                "uncovered_subjects": uncovered_subjects,
                "invalid_covered_subjects": sorted(invalid_covered_subjects),
                "conflicting_witness_domains": sorted(conflicting_witness_domains),
                "subjects": subject_rows,
                "minimum_independent_witnesses": minimum,
                "closed": closed,
            }
        )
    report: dict[str, object] = {
        "claim_count": len(rows),
        "subject_claim_count": sum(int(row["subject_count"]) for row in rows),
        "closed_claim_count": sum(bool(row["closed"]) for row in rows),
        "duplicate_claim_ids": sorted(duplicate_claim_ids),
        "invalid_claim_structures": invalid_claim_structures,
        "claims": rows,
    }
    enforce_repository_contract = (
        ledger_path.resolve() == CLAIM_LEDGER_PATH.resolve()
        and baseline_path.resolve() == BASELINE_PATH.resolve()
    )
    claims_by_id = {claim["id"]: claim for claim in ledger["claims"]}
    invalid_migration_expansions: list[str] = []
    expansions = migration.get("expansions", {}) if enforce_repository_contract else {}
    if not isinstance(expansions, dict):
        raise ValueError("inventory migration expansions must be an object")
    for test_name, expansion in expansions.items():
        claim = claims_by_id.get(expansion.get("claim_id"))
        if claim is None:
            invalid_migration_expansions.append(str(test_name))
            continue
        source = claim.get("subjects")
        if source != {"source": expansion.get("subject_source")}:
            invalid_migration_expansions.append(str(test_name))
            continue
        template = str(expansion["test_id_template"])
        expected_template = template.replace(
            "{target}", str(expansion["target"])
        ).replace("{test}", str(test_name))
        matching_witness = next(
            (
                witness
                for witness in claim["witnesses"]
                if witness.get("test_id_template") == expected_template
            ),
            None,
        )
        if matching_witness is None or matching_witness.get(
            "variants"
        ) != expansion.get("variants"):
            invalid_migration_expansions.append(str(test_name))
    report["invalid_migration_expansions"] = sorted(invalid_migration_expansions)
    report["migration_expansions_closed"] = not invalid_migration_expansions
    baseline_tests = set(baseline.get("test_ids", []))
    baseline_vectors = set(baseline["package_vector_ids"])
    report["accepted_baseline_test_digest_matches"] = (
        not enforce_repository_contract
        or migration.get("accepted_baseline_test_digest") == digest(baseline_tests)
    )
    report["accepted_baseline_package_vector_digest_matches"] = (
        not enforce_repository_contract
        or migration.get("accepted_baseline_package_vector_digest")
        == digest(baseline_vectors)
    )
    if enforce_repository_contract:
        contract_migration = claim_contract_migration_closure(
            accepted_digest=migration.get("accepted_claim_contract_digest"),
            current_digest=claim_contract_digest(ledger),
            migrations=migration.get("claim_contract_migrations"),
        )
    else:
        contract_migration = {
            "accepted_digest": None,
            "current_digest": claim_contract_digest(ledger),
            "migrations": [],
            "problems": [],
            "closed": True,
        }
    report["claim_contract_migration"] = contract_migration
    report["claim_contract_migration_closed"] = contract_migration["closed"]
    if enforce_repository_contract:
        accepted_manifest = json.loads(
            ACCEPTED_CLAIM_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        accepted_mapping = accepted_claim_mapping_closure(
            accepted_manifest=accepted_manifest,
            current_claims=rows,
            mappings=migration.get("accepted_claim_mappings"),
            baseline_package_vector_ids=baseline_vectors,
            current_package_vector_ids=vectors,
        )
        accepted_mapping["source_claim_contract_digest_matches"] = (
            accepted_manifest.get("source_claim_contract_digest")
            == migration.get("accepted_claim_contract_digest")
        )
        accepted_mapping["manifest_digest_matches"] = canonical_json_digest(
            accepted_manifest
        ) == migration.get("accepted_claim_manifest_digest")
        accepted_mapping["closed"] = (
            bool(accepted_mapping["closed"])
            and bool(accepted_mapping["source_claim_contract_digest_matches"])
            and bool(accepted_mapping["manifest_digest_matches"])
        )
    else:
        accepted_mapping = {
            "claims": [],
            "problems": [],
            "source_claim_contract_digest_matches": True,
            "manifest_digest_matches": True,
            "closed": True,
        }
    report["accepted_claim_mapping"] = accepted_mapping
    report["accepted_claim_mapping_closed"] = accepted_mapping["closed"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if (
        duplicate_claim_ids
        or invalid_claim_structures
        or invalid_migration_expansions
        or not report["claim_contract_migration_closed"]
        or not report["accepted_claim_mapping_closed"]
        or not report["accepted_baseline_test_digest_matches"]
        or not report["accepted_baseline_package_vector_digest_matches"]
        or any(not row["closed"] for row in rows)
    ):
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
    migration_closure = inventory_migration_closure(
        migration,
        full,
        subject_resolver=lambda source: authority_claim_subjects(
            source,
            current_package_vector_ids=current_vectors,
        ),
    )
    represented_baseline_tests = set(migration_closure["represented_baseline_tests"])
    missing_tests = baseline_tests - full - represented_baseline_tests
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
        "accepted_baseline_test_digest_matches": (
            migration.get("accepted_baseline_test_digest") == digest(baseline_tests)
        ),
        "accepted_baseline_package_vector_digest_matches": (
            migration.get("accepted_baseline_package_vector_digest")
            == digest(baseline_vectors)
        ),
        "migration_closure": migration_closure,
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
            not report["accepted_baseline_test_digest_matches"],
            not report["accepted_baseline_package_vector_digest_matches"],
            not migration_closure["closed"],
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


def start_timer(report_path: Path, *, now_ns: int | None = None) -> dict[str, int]:
    """Persist one wall-clock start usable by a later always-run step."""
    report = {"started_unix_ns": time.time_ns() if now_ns is None else now_ns}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    return report


def finish_timer(
    started_path: Path,
    report_path: Path,
    *,
    now_ns: int | None = None,
) -> dict[str, float]:
    """Publish elapsed shard wall time even after the test step failed."""
    started = json.loads(started_path.read_text(encoding="utf-8"))["started_unix_ns"]
    finished = time.time_ns() if now_ns is None else now_ns
    if not isinstance(started, int) or finished < started:
        raise ValueError("invalid shard timer interval")
    report = {"wall_seconds": round((finished - started) / 1_000_000_000, 6)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
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
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    allowed_skips = set(baseline["allowed_skipped_test_ids"])
    expected_tests = (
        {normalized_node_id(row, migration) for row in collect_node_ids()}
        if expected_test_ids is None
        else expected_test_ids
    )
    paths_by_shard: dict[str, list[Path]] = {}
    for path in junit_dir.rglob("junit-*.xml"):
        shard = path.stem.removeprefix("junit-")
        paths_by_shard.setdefault(shard, []).append(path)
    wall_paths_by_shard: dict[str, list[Path]] = {}
    for path in junit_dir.rglob("wall-*.json"):
        shard = path.stem.removeprefix("wall-")
        wall_paths_by_shard.setdefault(shard, []).append(path)
    missing_shards = sorted(set(expected_shards) - set(paths_by_shard))
    unexpected_shards = sorted(set(paths_by_shard) - set(expected_shards))
    duplicate_shard_reports = sorted(
        shard for shard, paths in paths_by_shard.items() if len(paths) != 1
    )
    missing_wall_reports = sorted(set(expected_shards) - set(wall_paths_by_shard))
    unexpected_wall_reports = sorted(set(wall_paths_by_shard) - set(expected_shards))
    duplicate_wall_reports = sorted(
        shard for shard, paths in wall_paths_by_shard.items() if len(paths) != 1
    )
    invalid_wall_reports: set[str] = set()
    seen: set[str] = set()
    duplicate_tests: set[str] = set()
    failed_tests: set[str] = set()
    skipped_tests: set[str] = set()
    xfailed_tests: set[str] = set()
    not_applicable_tests: dict[str, str] = {}
    per_file: dict[str, dict[str, float | int]] = {}
    duration_rows: list[dict[str, str | float]] = []
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
            duration = float(testcase.attrib.get("time", "0"))
            test_seconds += duration
            filename = node_id.partition("::")[0]
            file_row = per_file.setdefault(
                filename,
                {"test_count": 0, "test_seconds": 0.0},
            )
            file_row["test_count"] = int(file_row["test_count"]) + 1
            file_row["test_seconds"] = round(
                float(file_row["test_seconds"]) + duration,
                6,
            )
            duration_rows.append({"test_id": node_id, "test_seconds": duration})
            properties = {
                row.attrib.get("name"): row.attrib.get("value", "")
                for row in testcase.findall("./properties/property")
            }
            if properties.get("gda-balancing.applicability") == "not-applicable":
                not_applicable_tests[node_id] = properties.get(
                    "gda-balancing.applicability-reason", ""
                )
            outcome = testcase.find("skipped")
            if outcome is not None:
                if outcome.attrib.get("type") == "pytest.xfail":
                    xfailed_tests.add(node_id)
                else:
                    skipped_tests.add(node_id)
            if (
                testcase.find("failure") is not None
                or testcase.find("error") is not None
            ):
                failed_tests.add(node_id)
        shard_rows[shard] = {
            "test_count": test_count,
            "test_seconds": round(test_seconds, 6),
        }
        wall_paths = wall_paths_by_shard.get(shard, [])
        if len(wall_paths) == 1:
            try:
                wall_seconds = float(
                    json.loads(wall_paths[0].read_text(encoding="utf-8"))[
                        "wall_seconds"
                    ]
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                invalid_wall_reports.add(shard)
            else:
                if wall_seconds < 0 or not math.isfinite(wall_seconds):
                    invalid_wall_reports.add(shard)
                else:
                    shard_rows[shard]["wall_seconds"] = round(wall_seconds, 6)
    missing_tests = expected_tests - seen
    unexpected_tests = seen - expected_tests
    unexpected_skipped_tests = skipped_tests - allowed_skips
    closed = not any(
        (
            missing_shards,
            unexpected_shards,
            duplicate_shard_reports,
            missing_wall_reports,
            unexpected_wall_reports,
            duplicate_wall_reports,
            invalid_wall_reports,
            duplicate_tests,
            failed_tests,
            unexpected_skipped_tests,
            xfailed_tests,
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
        "per_file": dict(sorted(per_file.items())),
        "slow_tests": sorted(
            duration_rows,
            key=lambda row: float(row["test_seconds"]),
            reverse=True,
        )[:50],
        "skipped_tests": sorted(skipped_tests),
        "unexpected_skipped_tests": sorted(unexpected_skipped_tests),
        "xfailed_tests": sorted(xfailed_tests),
        "not_applicable_tests": dict(sorted(not_applicable_tests.items())),
        "missing_shards": missing_shards,
        "unexpected_shards": unexpected_shards,
        "duplicate_shard_reports": duplicate_shard_reports,
        "missing_wall_reports": missing_wall_reports,
        "unexpected_wall_reports": unexpected_wall_reports,
        "duplicate_wall_reports": duplicate_wall_reports,
        "invalid_wall_reports": sorted(invalid_wall_reports),
        "duplicate_tests": sorted(duplicate_tests),
        "failed_tests": sorted(failed_tests),
        "missing_tests": sorted(missing_tests),
        "unexpected_tests": sorted(unexpected_tests),
    }
    timed_shards = {
        name: row for name, row in shard_rows.items() if "wall_seconds" in row
    }
    if timed_shards:
        critical_name, critical_row = max(
            timed_shards.items(),
            key=lambda item: float(item[1]["wall_seconds"]),
        )
        report["parallel_shard_execution_critical_path_seconds"] = critical_row[
            "wall_seconds"
        ]
        report["critical_shard_execution"] = {
            "name": critical_name,
            "test_seconds": critical_row["test_seconds"],
            "wall_seconds": critical_row["wall_seconds"],
        }
    else:
        report["parallel_shard_execution_critical_path_seconds"] = None
        report["critical_shard_execution"] = None
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not closed:
        raise SystemExit("gda-balancing aggregate test closure failed")
    return report


def aggregate_junit_verdict(
    junit_dir: Path,
    report_path: Path,
    *,
    expected_shards: tuple[str, ...] | None = None,
    expected_test_ids: set[str] | None = None,
) -> tuple[dict[str, object], int]:
    """Return the same aggregate report on success, failure, or timeout evidence."""
    try:
        report = aggregate_junit(
            junit_dir,
            report_path,
            expected_shards=expected_shards,
            expected_test_ids=expected_test_ids,
        )
    except SystemExit:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return report, 1
    return report, 0


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
    start = subcommands.add_parser("start-timer")
    start.add_argument("--report", type=Path, required=True)
    finish = subcommands.add_parser("finish-timer")
    finish.add_argument("--started", type=Path, required=True)
    finish.add_argument("--report", type=Path, required=True)
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
    if args.command == "start-timer":
        report = start_timer(args.report)
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.command == "finish-timer":
        report = finish_timer(args.started, args.report)
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
