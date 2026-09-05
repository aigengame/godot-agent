"""Cross-revision harness identity guard."""

import pytest

import harness_version_guard


def _install(version: str) -> bytes:
    return f'HARNESS_VERSION = "{version}"\n'.encode()


def test_unchanged_harness_needs_no_version_bump():
    harness_version_guard.check_change(
        b"same body", _install("10"), b"same body", _install("10")
    )


def test_changed_harness_with_a_higher_version_passes():
    harness_version_guard.check_change(
        b"old body", _install("10"), b"new body", _install("11")
    )


def test_changed_harness_with_the_same_version_fails():
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match="changed.*HARNESS_VERSION.*10",
    ):
        harness_version_guard.check_change(
            b"old body", _install("10"), b"new body", _install("10")
        )


def test_changed_harness_with_a_lower_version_fails():
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match="must increase.*10.*9",
    ):
        harness_version_guard.check_change(
            b"old body", _install("10"), b"new body", _install("9")
        )


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b'HARNESS_VERSION = "not-an-integer"\n',
        b'HARNESS_VERSION = "1"\nHARNESS_VERSION = "2"\n',
    ],
)
def test_version_declaration_must_be_one_numeric_assignment(source):
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match="exactly one numeric HARNESS_VERSION",
    ):
        harness_version_guard.check_change(
            b"old body", source, b"new body", _install("11")
        )
