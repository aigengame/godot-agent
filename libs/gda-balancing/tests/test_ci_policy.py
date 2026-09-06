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
            "libs/gda-balancing/src/gda_balancing/domain/authority/context.py",
            "libs/gda-balancing/uv.lock",
            ".github/actions/setup-python-env/action.yml",
            ".github/workflows/release.yml",
            "scripts/release_scope_guard.py",
            "scripts/release_tags.py",
            "tests/repo/test_balancing_ci_wiring.py",
            "tests/repo/test_release_scope_guard.py",
            "tests/repo/test_release_tags.py",
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
    assert {selector.partition("::")[0] for selector in union} == expected
    assert ci.REQUIRED_TEST_SHARDS == (
        "fast",
        "authority",
        "language",
        "model",
        "experiment",
        "experiment-continuation",
        "composition",
    )
    assert ci.PROCESS_TIMEOUT_SECONDS == {
        "required": 480,
        "unfiltered": 900,
    }


def test_experiment_shards_preserve_every_collected_case_exactly_once():
    full = ci.collect_node_ids((ci.TEST_ROOT / "test_schema2_experiment_cli.py",))
    first = ci.collect_node_ids(ci.shard_paths("experiment"))
    second = ci.collect_node_ids(ci.shard_paths("experiment-continuation"))

    assert first and second
    assert not first & second
    assert first | second == full
    # Parameterized cases keep their common fixture lifecycle in one process.
    first_definitions = {node.split("[", 1)[0] for node in first}
    second_definitions = {node.split("[", 1)[0] for node in second}
    assert not first_definitions & second_definitions


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
