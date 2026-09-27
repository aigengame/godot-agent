"""Cross-revision harness identity guard."""

import pytest

import harness_version_guard

HARNESS, MODULE = harness_version_guard.HARNESS_PATHS


def _install(version: str) -> bytes:
    return f'HARNESS_VERSION = "{version}"\n'.encode()


def _files(harness: bytes, module: bytes | None = b"module body") -> dict:
    return {HARNESS: harness, MODULE: module}


def test_unchanged_harness_needs_no_version_bump():
    harness_version_guard.check_change(
        _files(b"same body"), _install("10"), _files(b"same body"), _install("10")
    )


def test_changed_harness_with_a_higher_version_passes():
    harness_version_guard.check_change(
        _files(b"old body"), _install("10"), _files(b"new body"), _install("11")
    )


def test_changed_harness_with_the_same_version_fails():
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match="changed.*HARNESS_VERSION.*10",
    ):
        harness_version_guard.check_change(
            _files(b"old body"), _install("10"), _files(b"new body"), _install("10")
        )


def test_changed_harness_with_a_lower_version_fails():
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match="must increase.*10.*9",
    ):
        harness_version_guard.check_change(
            _files(b"old body"), _install("10"), _files(b"new body"), _install("9")
        )


def test_a_module_change_alone_needs_a_version_bump():
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match=r"changed \(src/gda/ops/lib/value\.gd\).*HARNESS_VERSION.*10",
    ):
        harness_version_guard.check_change(
            _files(b"same body", b"old module"),
            _install("10"),
            _files(b"same body", b"new module"),
            _install("10"),
        )


def test_a_module_the_base_does_not_have_counts_as_a_change():
    with pytest.raises(
        harness_version_guard.HarnessVersionGuardError,
        match=r"changed \(src/gda/ops/lib/value\.gd\)",
    ):
        harness_version_guard.check_change(
            _files(b"same body", None),
            _install("10"),
            _files(b"same body"),
            _install("10"),
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
            _files(b"old body"), source, _files(b"new body"), _install("11")
        )
