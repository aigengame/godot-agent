"""ADR-0002 error-code registry drift checks."""

import re
from pathlib import Path

import pytest

from gda.error_codes import (
    ERROR_CODE_BY_CODE,
    ERROR_CODES,
    OPERATION_ERROR_CODES,
    ErrorCodeSource,
)
from gda.errors import _failure

ROOT = Path(__file__).resolve().parents[1]
ADR_0002 = ROOT / "docs" / "adr" / "0002-headless-structured-output-contract.md"
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"

ADR_REGISTRY_ROW = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| `(\d+)` \|")
GDSCRIPT_OPERATION_CODE = re.compile(r'^const OP_ERROR_[A-Z_]+ := "([a-z_]+)"$', re.MULTILINE)
BARE_FAIL_CODE = re.compile(r'_fail\(\s*"[a-z_]+"')


def _adr_registry() -> dict[str, tuple[str, str, int]]:
    rows: dict[str, tuple[str, str, int]] = {}
    for line in ADR_0002.read_text(encoding="utf-8").splitlines():
        match = ADR_REGISTRY_ROW.match(line)
        if match:
            code, category, source, exit_code = match.groups()
            rows[code] = (category, source, int(exit_code))
    return rows


def _python_registry() -> dict[str, tuple[str, str, int]]:
    return {
        spec.code: (spec.category.value, spec.source.value, spec.exit_code)
        for spec in ERROR_CODES
    }


def test_python_error_registry_has_no_duplicate_codes():
    assert len(ERROR_CODES) == len(ERROR_CODE_BY_CODE)


def test_failure_derives_exit_code_from_registry():
    for spec in ERROR_CODES:
        failure = _failure(spec.code, "message", "")
        assert failure.exit_code == spec.exit_code
        assert failure.error.category is spec.category
        assert failure.error.code == spec.code


def test_failure_builder_rejects_unregistered_public_codes():
    with pytest.raises(RuntimeError, match="unregistered GdaError.code"):
        _failure(
            "not_registered",
            "message",
            "",
        )


def test_adr_registry_matches_python_authoritative_registry():
    assert _adr_registry() == _python_registry()


def test_gdscript_operation_error_codes_mirror_python_operation_subset():
    gdscript = OPERATIONS_GD.read_text(encoding="utf-8")
    mirrored_codes = set(GDSCRIPT_OPERATION_CODE.findall(gdscript))

    python_operation_codes = {
        spec.code for spec in ERROR_CODES if spec.source is ErrorCodeSource.OPERATION
    }

    assert mirrored_codes == python_operation_codes
    assert mirrored_codes == set(OPERATION_ERROR_CODES)


def test_gdscript_fail_calls_do_not_use_literal_error_codes():
    gdscript = OPERATIONS_GD.read_text(encoding="utf-8")

    assert not BARE_FAIL_CODE.search(gdscript)
