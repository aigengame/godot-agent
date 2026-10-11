"""The worker default behind the one pytest entry (#1173).

``uv run pytest`` passes ``-n auto`` through pyproject's ``addopts``; the test
conftest's ``pytest_xdist_auto_num_workers`` resolves it. Three branches: the
project default capped at the CPU count, a positive-integer override from
``$PYTEST_XDIST_AUTO_NUM_WORKERS``, and a refused value that names the variable.
"""

import pytest

from tests.conftest import DEFAULT_WORKERS, WORKERS_VAR, pytest_xdist_auto_num_workers


@pytest.mark.parametrize(
    ("cpus", "expected"),
    [(8, DEFAULT_WORKERS), (2, 2), (None, 1)],
    ids=["above-the-default", "capped-at-the-cpu-count", "unknown-cpu-count"],
)
def test_an_unset_variable_means_the_default_capped_at_the_cpu_count(
    monkeypatch, pytestconfig, cpus, expected
):
    monkeypatch.delenv(WORKERS_VAR, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: cpus)
    assert pytest_xdist_auto_num_workers(pytestconfig) == expected


def test_an_empty_variable_reads_as_unset(monkeypatch, pytestconfig):
    # CI maps a repository variable into it, and an unset variable arrives as "".
    monkeypatch.setenv(WORKERS_VAR, "")
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    assert pytest_xdist_auto_num_workers(pytestconfig) == DEFAULT_WORKERS


@pytest.mark.parametrize("value", ["1", "2", "8"])
def test_a_positive_integer_wins_over_the_default_uncapped(
    monkeypatch, pytestconfig, value
):
    monkeypatch.setenv(WORKERS_VAR, value)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    assert pytest_xdist_auto_num_workers(pytestconfig) == int(value)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "four", " 2", "²"])
def test_any_other_value_stops_the_run_naming_the_variable(
    monkeypatch, pytestconfig, value
):
    monkeypatch.setenv(WORKERS_VAR, value)
    with pytest.raises(pytest.UsageError, match=WORKERS_VAR):
        pytest_xdist_auto_num_workers(pytestconfig)
