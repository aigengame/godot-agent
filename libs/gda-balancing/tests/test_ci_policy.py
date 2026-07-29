"""Regression tests for the gda-balancing CI selection authority."""

import importlib.util
import json
from pathlib import Path

_MEMBER_ROOT = Path(__file__).parents[1]
_ROOT = Path(__file__).parents[3]
_SCRIPT = _MEMBER_ROOT / "tools" / "ci.py"
_SPEC = importlib.util.spec_from_file_location("gda_balancing_ci", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
ci = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ci)


def test_balancing_paths_and_shared_release_surfaces_are_affecting():
    assert ci.balancing_required(
        [
            "libs/gda-balancing/src/gda_balancing/schema2/authority.py",
            "libs/gda-balancing/uv.lock",
            ".github/actions/setup-python-env/action.yml",
            ".github/workflows/release.yml",
            "scripts/release_tags.py",
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
