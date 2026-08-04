"""Regression tests for the gda-balancing CI selection authority."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import cast
from xml.etree import ElementTree

import pytest

_MEMBER_ROOT = Path(__file__).parents[1]
_ROOT = Path(__file__).parents[3]
_SCRIPT = _MEMBER_ROOT / "tools" / "ci.py"
_SPEC = importlib.util.spec_from_file_location("gda_balancing_ci", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
ci = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ci)
_CONFTEST_PATH = _MEMBER_ROOT / "tests" / "conftest.py"
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "gda_balancing_suite_conftest",
    _CONFTEST_PATH,
)
assert _CONFTEST_SPEC is not None and _CONFTEST_SPEC.loader is not None
suite_conftest = importlib.util.module_from_spec(_CONFTEST_SPEC)
_CONFTEST_SPEC.loader.exec_module(suite_conftest)


def test_balancing_paths_and_shared_release_surfaces_are_affecting():
    assert ci.balancing_required(
        [
            "libs/gda-balancing/src/gda_balancing/schema2/authority.py",
            "libs/gda-balancing/uv.lock",
            ".github/actions/setup-python-env/action.yml",
            ".github/workflows/release.yml",
            "scripts/release_scope_guard.py",
            "scripts/release_tags.py",
            "tests/test_balancing_ci_wiring.py",
            "tests/test_release_scope_guard.py",
            "tests/test_release_tags.py",
        ]
    )


def test_known_root_product_change_is_unrelated():
    assert not ci.balancing_required(
        [
            "src/gda/cli.py",
            "tests/test_cli.py",
            "examples/sandbox/README.md",
            "docs/adr/0001-example.md",
        ]
    )


def test_unknown_path_defaults_to_the_full_balancing_matrix():
    assert ci.classify_path("future-shared-tool/config.toml") == "unknown"
    assert ci.balancing_required(["future-shared-tool/config.toml"])


def test_shards_pairwise_partition_every_balancing_test_file():
    groups = [set(paths) for paths in ci.SHARDS.values()]
    union: set[str] = set()
    for group in groups:
        assert not union & group
        union.update(group)
    expected = {
        path.name for path in (_ROOT / "libs/gda-balancing/tests").glob("test_*.py")
    }
    assert union == expected
    assert ci.REQUIRED_TEST_SHARDS == (
        "fast",
        "authority-cli",
        "authority-bootstrap",
        "language-bootstrap",
        "model",
        "experiment",
        "composition",
    )
    assert ci.PROCESS_TIMEOUT_SECONDS == {
        "required": 480,
        "unfiltered": 900,
    }


def test_declared_bootstrap_migration_normalizes_only_the_moved_test():
    migration = {
        "source": "test_schema2_bootstrap_conformance.py",
        "tests": {
            "test_example": "test_schema2_bootstrap_authority.py",
        },
    }
    assert (
        ci.normalized_node_id(
            "tests/test_schema2_bootstrap_authority.py::test_example[value]", migration
        )
        == "tests/test_schema2_bootstrap_conformance.py::test_example[value]"
    )
    assert (
        ci.normalized_node_id(
            "tests/test_schema2_bootstrap_authority.py::test_other", migration
        )
        == "tests/test_schema2_bootstrap_authority.py::test_other"
    )


def test_one_to_many_inventory_migration_requires_every_subject_variant():
    migration = {
        "source": "old.py",
        "tests": {"test_matrix": "new.py"},
        "expansions": {
            "test_matrix": {
                "target": "new.py",
                "subject_source": "authority.example_ids",
                "test_id_template": "tests/{target}::{test}[{subject}-{variant}]",
                "variants": ["delete", "mutate"],
            }
        },
    }
    current = {
        "tests/old.py::test_matrix[a-delete]",
        "tests/old.py::test_matrix[a-mutate]",
        "tests/old.py::test_matrix[b-delete]",
    }

    report = ci.inventory_migration_closure(
        migration,
        current,
        subject_resolver=lambda _source: ["a", "b"],
    )

    assert report["represented_baseline_tests"] == []
    assert report["expansions"][0]["missing_current_tests"] == [
        "tests/old.py::test_matrix[b-mutate]"
    ]


def test_claim_ledger_rejects_a_claim_after_its_last_independent_witness_is_lost(
    tmp_path,
):
    ledger = tmp_path / "claims.json"
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "claims": [
                    {
                        "id": "authority.consumer-agreement",
                        "boundary": "bootstrap admission",
                        "subjects": [
                            "exact packaged authority",
                            "reidentified mutation",
                        ],
                        "witnesses": [
                            {
                                "test_id": "tests/test_authority.py::test_consumers_agree",
                                "independence_domain": "consumer-a-vs-consumer-b",
                                "covers": ["exact packaged authority"],
                            }
                        ],
                        "minimum_independent_witnesses": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "claim-report.json"

    with pytest.raises(SystemExit, match="coverage claim closure failed"):
        ci.verify_claims(
            report_path,
            ledger_path=ledger,
            current_test_ids={"tests/test_authority.py::test_consumers_agree"},
            current_package_vector_ids=set(),
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["claims"][0]["claim_id"] == "authority.consumer-agreement"
    assert report["claims"][0]["missing_witnesses"] == []
    assert report["claims"][0]["uncovered_subjects"] == ["reidentified mutation"]
    assert report["claims"][0]["closed"] is False


def test_claim_ledger_expands_and_closes_every_live_package_vector(tmp_path):
    ledger = tmp_path / "claims.json"
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "claims": [
                    {
                        "id": "package-vector",
                        "boundary": "packaged conformance vectors",
                        "subjects": {"source": "authority.package_vector_ids"},
                        "witnesses": [
                            {
                                "test_id": "tests/test_vectors.py::test_execute_all",
                                "independence_domain": "public-vector-runner",
                                "covers": "*",
                            }
                        ],
                        "minimum_independent_witnesses": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"package_vector_ids": ["package@1.0.0:vector-a"]}),
        encoding="utf-8",
    )

    report = ci.verify_claims(
        tmp_path / "report.json",
        ledger_path=ledger,
        baseline_path=baseline,
        current_test_ids={"tests/test_vectors.py::test_execute_all"},
        current_package_vector_ids={"package@1.0.0:vector-a"},
    )

    assert report["claim_count"] == 1
    assert report["subject_claim_count"] == 1
    assert report["claims"][0]["subject_count"] == 1
    assert report["claims"][0]["closed"] is True


def test_claim_ledger_rejects_one_test_relabeled_as_two_independent_domains(tmp_path):
    test_id = "tests/test_authority.py::test_one_consumer"
    ledger = tmp_path / "claims.json"
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "claims": [
                    {
                        "id": "authority.consumer-agreement",
                        "boundary": "bootstrap admission",
                        "subjects": ["exact packaged authority"],
                        "witnesses": [
                            {
                                "test_id": test_id,
                                "independence_domain": "consumer-a",
                                "covers": "*",
                            },
                            {
                                "test_id": test_id,
                                "independence_domain": "consumer-b",
                                "covers": "*",
                            },
                        ],
                        "minimum_independent_witnesses": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="coverage claim closure failed"):
        ci.verify_claims(
            tmp_path / "report.json",
            ledger_path=ledger,
            current_test_ids={test_id},
            current_package_vector_ids=set(),
        )


def test_repository_coverage_claim_ledger_closes_the_current_suite(tmp_path):
    report = ci.verify_claims(tmp_path / "coverage-claims.json")

    assert report["claim_count"] >= 6
    assert report["closed_claim_count"] == report["claim_count"]
    assert report["subject_claim_count"] >= 100
    assert report["migration_expansions_closed"] is True


def test_ci_policy_exposes_coverage_claim_verification_command(tmp_path):
    args = ci._parser().parse_args(
        ["verify-claims", "--report", str(tmp_path / "claims.json")]
    )

    assert args.command == "verify-claims"


def test_junit_aggregate_proves_exact_execution_and_reports_total_duration(tmp_path):
    junit_dir = tmp_path / "junit"
    junit_dir.mkdir()
    (junit_dir / "junit-fast.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one" '
        'name="test_fast" time="0.25"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    (junit_dir / "junit-smoke.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.test_two" '
        'name="test_boundary" time="1.75"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    (junit_dir / "wall-fast.json").write_text(
        json.dumps({"wall_seconds": 0.5}), encoding="utf-8"
    )
    (junit_dir / "wall-smoke.json").write_text(
        json.dumps({"wall_seconds": 2.5}), encoding="utf-8"
    )

    report = ci.aggregate_junit(
        junit_dir,
        tmp_path / "aggregate.json",
        expected_shards=("fast", "smoke"),
        expected_test_ids={
            "tests/test_one.py::test_fast",
            "tests/test_two.py::test_boundary",
        },
    )

    assert report["closed"] is True
    assert report["test_count"] == 2
    assert report["test_seconds"] == 2.0
    assert report["shards"]["smoke"] == {
        "test_count": 1,
        "test_seconds": 1.75,
        "wall_seconds": 2.5,
    }
    assert report["parallel_critical_path_wall_seconds"] == 2.5
    assert report["critical_shard"] == {
        "name": "smoke",
        "test_seconds": 1.75,
        "wall_seconds": 2.5,
    }
    assert report["per_file"]["tests/test_two.py"] == {
        "test_count": 1,
        "test_seconds": 1.75,
    }
    assert report["slow_tests"][0] == {
        "test_id": "tests/test_two.py::test_boundary",
        "test_seconds": 1.75,
    }


def test_junit_aggregate_rejects_a_missing_shard_wall_report(tmp_path):
    junit_dir = tmp_path / "junit"
    junit_dir.mkdir()
    (junit_dir / "junit-fast.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one" '
        'name="test_fast"/></testsuite></testsuites>',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="aggregate test closure failed"):
        ci.aggregate_junit(
            junit_dir,
            tmp_path / "aggregate.json",
            expected_shards=("fast",),
            expected_test_ids={"tests/test_one.py::test_fast"},
        )


@pytest.mark.parametrize("outcome_type", ["pytest.skip", "pytest.xfail"])
def test_junit_aggregate_rejects_unaccepted_nonexecuted_outcomes(
    tmp_path, outcome_type
):
    junit_dir = tmp_path / "junit"
    junit_dir.mkdir()
    (junit_dir / "junit-fast.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one" '
        f'name="test_fast"><skipped type="{outcome_type}"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="aggregate test closure failed"):
        ci.aggregate_junit(
            junit_dir,
            tmp_path / "aggregate.json",
            expected_shards=("fast",),
            expected_test_ids={"tests/test_one.py::test_fast"},
        )


def test_ci_policy_exposes_junit_aggregate_command(tmp_path):
    args = ci._parser().parse_args(
        [
            "aggregate-junit",
            "--junit-dir",
            str(tmp_path / "junit"),
            "--report",
            str(tmp_path / "aggregate.json"),
        ]
    )

    assert args.command == "aggregate-junit"


def test_ci_timer_publishes_reproducible_shard_wall_seconds(tmp_path):
    started = tmp_path / "started.json"
    report_path = tmp_path / "wall-fast.json"

    ci.start_timer(started, now_ns=1_000_000_000)
    report = ci.finish_timer(started, report_path, now_ns=3_500_000_000)

    assert report == {"wall_seconds": 2.5}
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_ci_policy_exports_all_shards_for_exact_release_execution():
    assert ci.all_test_shards() == (*ci.REQUIRED_TEST_SHARDS, "smoke")


def test_local_parallel_policy_keeps_process_heavy_smoke_exclusive():
    assert ci.local_parallel_shards() == ci.REQUIRED_TEST_SHARDS
    assert ci.local_serial_shards() == ("smoke",)


@pytest.mark.parametrize(
    ("captured", "expected"),
    (
        (b"partial output\n", "partial output\n"),
        ("text output\n", "text output\n"),
        (None, ""),
    ),
)
def test_timeout_output_normalizes_subprocess_bytes(captured, expected):
    assert ci.subprocess_text(captured) == expected


def test_every_reason_mutation_has_a_stable_independent_test_id():
    migration = json.loads(ci.MIGRATION_PATH.read_text(encoding="utf-8"))
    expansion = migration["expansions"][
        "test_reidentified_deletion_and_behavior_mutation_of_every_reason_refuse"
    ]
    ledger = json.loads(ci.CLAIM_LEDGER_PATH.read_text(encoding="utf-8"))
    claim = next(row for row in ledger["claims"] if row["id"] == expansion["claim_id"])
    subjects = ci.authority_claim_subjects(
        claim["subjects"]["source"],
        current_package_vector_ids=ci.package_vector_ids(),
    )
    rows = {
        row
        for row in ci.collect_node_ids((ci.TEST_ROOT / expansion["target"],))
        if "test_reidentified_deletion_and_behavior_mutation_of_every_reason_refuse["
        in row
    }

    assert len(rows) == len(subjects) * len(expansion["variants"])
    assert any("quantity.reason.invalid-domain-delete" in row for row in rows)
    assert any(
        "migration.reason.target-limit-exceeded-operation" in row for row in rows
    )


def test_junit_summary_reports_per_file_and_slowest_tests(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one.TestRows" '
        'name="test_fast" time="0.1"/><testcase classname="tests.test_one" '
        'name="test_slow" time="1.2"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    report_path = tmp_path / "durations.json"

    report = ci.summarize_junit(junit, report_path)

    assert report["per_file"] == {"tests/test_one.py": {"count": 2, "seconds": 1.3}}
    assert report["slow_tests"][0]["node"].endswith("::test_slow")
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_outcome_closure_allows_only_declared_skips(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {"allowed_skipped_test_ids": ["tests/test_one.py::TestRows::test_allowed"]}
        ),
        encoding="utf-8",
    )
    allowed_junit = tmp_path / "allowed.xml"
    allowed_junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one.TestRows" '
        'name="test_allowed"><skipped type="pytest.skip"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )

    report = ci.verify_outcomes(
        allowed_junit,
        tmp_path / "allowed-report.json",
        baseline,
    )

    assert report["unexpected_skipped_tests"] == []
    assert report["xfailed_tests"] == []


def test_outcome_closure_reports_capability_inapplicable_passes(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"allowed_skipped_test_ids": []}),
        encoding="utf-8",
    )
    junit = tmp_path / "not-applicable.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one.TestRows" '
        'name="test_sink[formula parse]"><properties>'
        '<property name="gda-balancing.applicability" value="not-applicable"/>'
        '<property name="gda-balancing.applicability-reason" '
        'value="descriptor is not an artifact sink"/>'
        "</properties></testcase></testsuite></testsuites>",
        encoding="utf-8",
    )

    report = ci.verify_outcomes(
        junit,
        tmp_path / "not-applicable-report.json",
        baseline,
    )

    assert report["not_applicable_tests"] == {
        "tests/test_one.py::TestRows::test_sink[formula parse]": (
            "descriptor is not an artifact sink"
        )
    }
    assert report["skipped_tests"] == []
    assert report["unexpected_skipped_tests"] == []


def test_outcome_closure_reports_a_real_module_level_collection_skip(tmp_path):
    probe_root = tmp_path / "probe"
    probe = probe_root / "tests" / "test_zz_module_skip_probe.py"
    probe.parent.mkdir(parents=True)
    probe.write_text(
        'import pytest\n\npytest.skip("collection skipped", allow_module_level=True)\n',
        encoding="utf-8",
    )
    junit = probe_root / "module-skip.xml"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_zz_module_skip_probe.py",
            f"--junitxml={junit}",
        ],
        cwd=probe_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, (
        completed.stdout + completed.stderr
    )
    testcase = next(ElementTree.parse(junit).getroot().iter("testcase"))
    assert testcase.attrib["classname"] == ""
    assert testcase.attrib["name"] == "tests.test_zz_module_skip_probe"

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"allowed_skipped_test_ids": []}),
        encoding="utf-8",
    )
    report_path = tmp_path / "module-skip-report.json"

    with pytest.raises(SystemExit, match="outcome closure failed"):
        ci.verify_outcomes(
            junit,
            report_path,
            baseline,
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["unexpected_skipped_tests"] == ["tests/test_zz_module_skip_probe.py"]
    assert report["xfailed_tests"] == []

    summary = ci.summarize_junit(junit, tmp_path / "module-skip-durations.json")
    assert list(summary["per_file"]) == ["tests/test_zz_module_skip_probe.py"]
    assert summary["slow_tests"][0]["node"] == "tests/test_zz_module_skip_probe.py"


def test_outcome_closure_independently_rejects_xfail(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"allowed_skipped_test_ids": []}),
        encoding="utf-8",
    )
    junit = tmp_path / "xfail.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_one" '
        'name="test_xfail"><skipped type="pytest.xfail"/>'
        "</testcase></testsuite></testsuites>",
        encoding="utf-8",
    )
    report_path = tmp_path / "xfail-report.json"

    with pytest.raises(SystemExit, match="outcome closure failed"):
        ci.verify_outcomes(junit, report_path, baseline)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["unexpected_skipped_tests"] == []
    assert report["xfailed_tests"] == ["tests/test_one.py::test_xfail"]


def test_pytest_treats_xpass_as_a_failure():
    configuration = tomllib.loads(
        (_MEMBER_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert configuration["tool"]["pytest"]["ini_options"]["xfail_strict"] is True

    class NonStrictXfailItem:
        nodeid = "tests/test_example.py::test_example"

        @staticmethod
        def iter_markers(name: str):
            assert name == "xfail"
            return [pytest.mark.xfail(strict=False).mark]

    with pytest.raises(pytest.UsageError, match=r"xfail\(strict=False\)"):
        suite_conftest.reject_non_strict_xfails(
            [cast(pytest.Item, NonStrictXfailItem())]
        )
