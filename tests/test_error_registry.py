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
from gda.exit_codes import (
    EXIT_NOT_FOUND,
    EXIT_OPERATION,
    EXIT_PARSE,
    EXIT_TIMEOUT,
    EXIT_VERSION,
)
from gda.models import ErrorCategory

# The exit code each registered code must carry, mirroring what the failure
# call sites passed before exit codes moved onto the registry. Asserted here so
# the registry — not a call site — is the checked source of truth (ADR-0002).
EXPECTED_EXIT_CODE: dict[str, int] = {
    "binary_not_found": EXIT_NOT_FOUND,
    "launch_timeout": EXIT_TIMEOUT,
    "unsupported_version": EXIT_VERSION,
    "engine_crashed": EXIT_OPERATION,
    "operation_failed": EXIT_OPERATION,
    "usage_error": EXIT_OPERATION,
    "unknown_operation": EXIT_OPERATION,
    "invalid_params": EXIT_OPERATION,
    "invalid_path": EXIT_OPERATION,
    "invalid_root_type": EXIT_OPERATION,
    "invalid_root_name": EXIT_OPERATION,
    "already_exists": EXIT_OPERATION,
    "save_failed": EXIT_OPERATION,
    "delete_failed": EXIT_OPERATION,
    "project_not_found": EXIT_OPERATION,
    "path_not_found": EXIT_OPERATION,
    "not_a_scene": EXIT_OPERATION,
    "parent_not_found": EXIT_OPERATION,
    "invalid_node_type": EXIT_OPERATION,
    "invalid_node_name": EXIT_OPERATION,
    "duplicate_node_name": EXIT_OPERATION,
    "missing_dependency": EXIT_OPERATION,
    "uninstantiable_script": EXIT_OPERATION,
    "node_not_found": EXIT_OPERATION,
    "unknown_property": EXIT_OPERATION,
    "uncoercible_value": EXIT_OPERATION,
    "no_search_match": EXIT_OPERATION,
    "invalid_line_range": EXIT_OPERATION,
    "script_compile_failed": EXIT_OPERATION,
    "incompatible_script_type": EXIT_OPERATION,
    "contract_violation": EXIT_PARSE,
}

ROOT = Path(__file__).resolve().parents[1]
ADR_0002 = ROOT / "docs" / "adr" / "0002-headless-structured-output-contract.md"
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"

ADR_REGISTRY_ROW = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|")
GDSCRIPT_OPERATION_CODE = re.compile(r'^const OP_ERROR_[A-Z_]+ := "([a-z_]+)"$', re.MULTILINE)
BARE_FAIL_CODE = re.compile(r'_fail\(\s*"[a-z_]+"')


def _adr_registry() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in ADR_0002.read_text(encoding="utf-8").splitlines():
        match = ADR_REGISTRY_ROW.match(line)
        if match:
            code, category, source = match.groups()
            rows[code] = (category, source)
    return rows


def _python_registry() -> dict[str, tuple[str, str]]:
    return {
        spec.code: (spec.category.value, spec.source.value)
        for spec in ERROR_CODES
    }


def test_python_error_registry_has_no_duplicate_codes():
    assert len(ERROR_CODES) == len(ERROR_CODE_BY_CODE)


def test_every_code_carries_its_expected_exit_code():
    registry_exit_codes = {spec.code: spec.exit_code for spec in ERROR_CODES}
    assert registry_exit_codes == EXPECTED_EXIT_CODE


def test_failure_derives_exit_code_from_registry():
    for spec in ERROR_CODES:
        failure = _failure(spec.code, "message", "")
        assert failure.exit_code == EXPECTED_EXIT_CODE[spec.code]
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
