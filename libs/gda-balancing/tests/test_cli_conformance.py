"""The bADR-0011 conformance harness — walks the registry, asserts every
applicable bADR-0008 row per registered command, plus the cross-walk laws
(reserved names, envelope byte-identity) and the true-subprocess smoke that
proves both installed entry points end to end.
"""

import dataclasses
import json
import shutil
import subprocess
import sys

import jsonschema
import pytest

from gda_balancing.commands import REGISTRY
from gda_balancing.descriptors import (
    RESERVED_GROUPS,
    RESERVED_META,
    CommandDescriptor,
    build_registry,
)
from gda_balancing.emit import canonical_json
from gda_balancing.envelope import (
    ERROR_ENVELOPE_SCHEMA,
    USAGE_CODES,
    Refusal,
    RefusalReport,
)


def _command_path(descriptor: CommandDescriptor) -> list[str]:
    return ([descriptor.group] if descriptor.group else []) + [descriptor.command]


def _valid_invocation(descriptor: CommandDescriptor) -> list[str]:
    """Every row derives the command path from the descriptor itself — the
    fixture contributes only the argument tail, so identity cannot drift."""
    return [*_command_path(descriptor), *descriptor.fixtures.valid_args]


def _assert_envelope(stderr_text: str, category: str) -> dict:
    """stderr parses as exactly one schema-valid envelope of ``category``."""
    payload = json.loads(stderr_text)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == category
    return payload["error"]


_IDS = [" ".join(_command_path(d)) for d in REGISTRY]


@pytest.mark.parametrize("descriptor", REGISTRY, ids=_IDS)
class TestPerDescriptorRows:
    def test_success_row(self, descriptor, run_cli):
        exit_code, stdout, stderr = run_cli(_valid_invocation(descriptor))
        assert (exit_code, stderr) == (0, "")
        payload = json.loads(stdout)
        jsonschema.validate(payload, descriptor.output_model.model_json_schema())
        # Canonical emission (bADR-0005): re-rendering the parsed document
        # reproduces the bytes — sorted keys, LF, defaults materialized.
        assert stdout == canonical_json(payload)

    def test_usage_row(self, descriptor, run_cli):
        argv = [*_valid_invocation(descriptor), "--no-such-argument"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        error = _assert_envelope(stderr, "usage")
        assert error["code"] in USAGE_CODES

    def test_internal_row(self, descriptor, run_cli, fault_registry):
        argv = _valid_invocation(descriptor)
        exit_code, stdout, stderr = run_cli(argv, fault_registry)
        assert (exit_code, stdout) == (4, "")
        error = _assert_envelope(stderr, "internal")
        assert error["code"] == "internal_error"
        assert "diagnostics" not in error  # only under --debug
        assert "Traceback" not in stderr  # sanitized by default

    def test_internal_row_debug_diagnostics(self, descriptor, run_cli, fault_registry):
        argv = [*_valid_invocation(descriptor), "--debug"]
        exit_code, stdout, stderr = run_cli(argv, fault_registry)
        assert (exit_code, stdout) == (4, "")
        error = _assert_envelope(stderr, "internal")
        assert "injected fault" in error["diagnostics"]

    def test_schema_row(self, descriptor, run_cli):
        argv = [*_command_path(descriptor), "--schema"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stderr) == (0, "")
        payload = json.loads(stdout)
        assert sorted(payload) == ["error", "input", "output"]

    def test_schema_wins_over_any_other_argument(self, descriptor, run_cli):
        argv = [*_command_path(descriptor), "--no-such-argument", "--schema"]
        exit_code, _stdout, stderr = run_cli(argv)
        assert (exit_code, stderr) == (0, "")

    def test_seed_row_deterministic_refuses_seed(self, descriptor, run_cli):
        assert not descriptor.stochastic  # no v1 command is stochastic
        argv = [*_valid_invocation(descriptor), "--seed", "1"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "unknown_argument"


class TestSurfaceLaws:
    def test_error_schema_byte_identical_across_the_walk(self, run_cli):
        renderings = set()
        for descriptor in REGISTRY:
            _, stdout, _ = run_cli([*_command_path(descriptor), "--schema"])
            renderings.add(canonical_json(json.loads(stdout)["error"]))
        assert len(renderings) == 1
        assert renderings == {canonical_json(ERROR_ENVELOPE_SCHEMA)}

    def test_reserved_names_unoccupied(self):
        for descriptor in REGISTRY:
            assert descriptor.group not in RESERVED_GROUPS
            if descriptor.group is None:
                assert descriptor.command not in RESERVED_GROUPS | RESERVED_META

    def test_invoking_a_reserved_name_is_unknown_command(self, run_cli):
        for reserved in sorted(RESERVED_GROUPS | RESERVED_META):
            exit_code, stdout, stderr = run_cli([reserved])
            assert (exit_code, stdout) == (3, "")
            assert _assert_envelope(stderr, "usage")["code"] == "unknown_command"

    def test_refusal_outcome_maps_to_refusal_envelope_exit_2(self, run_cli):
        # No v1 command produces refusals (#504 lands the funnel); the seam
        # is proven by injection, like the internal row: a handler returning
        # a RefusalReport must yield the refusal envelope on STDOUT, exit 2.
        report = RefusalReport(
            refusals=(
                Refusal(code="some_refusal", path="/attributes/0", detail="why"),
            ),
            truncated=False,
        )
        registry = tuple(
            dataclasses.replace(d, handler=lambda _i, _r=report: _r) for d in REGISTRY
        )
        for descriptor in registry:
            exit_code, stdout, stderr = run_cli(_valid_invocation(descriptor), registry)
            assert (exit_code, stderr) == (2, "")
            payload = json.loads(stdout)
            jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
            assert payload["error"]["category"] == "refusal"
            assert payload["error"]["truncated"] is False

    def test_duplicate_command_registration_is_rejected(self):
        with pytest.raises(ValueError, match="duplicate command registration"):
            build_registry(REGISTRY[0], REGISTRY[0])

    def test_bare_invocation_is_missing_command_never_help(self, run_cli):
        exit_code, stdout, stderr = run_cli([])
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "missing_command"

    def test_help_is_the_one_human_exemption(self, run_cli):
        for argv in (["help"], ["--help"]):
            exit_code, stdout, stderr = run_cli(argv)
            assert (exit_code, stderr) == (0, "")
            assert "usage:" in stdout


class TestEntryPointSmoke:
    """True subprocesses: the packaging claim #502 exists to prove."""

    def _console_script(self) -> str:
        script = shutil.which("gda-balancing")
        assert script is not None, (
            "console script `gda-balancing` not on PATH — run the suite via "
            "`uv run pytest` after `uv sync --all-packages` (the entry point "
            "is what this smoke test exists to prove)"
        )
        return script

    def test_both_entry_points_agree_on_the_valid_row(self):
        console = subprocess.run(
            [self._console_script(), "version"], capture_output=True, text=True
        )
        module = subprocess.run(
            [sys.executable, "-m", "gda_balancing", "version"],
            capture_output=True,
            text=True,
        )
        assert (console.returncode, console.stderr) == (0, "")
        assert (module.returncode, module.stderr) == (0, "")
        assert console.stdout == module.stdout
        json.loads(console.stdout)

    def test_stream_separation_end_to_end(self):
        result = subprocess.run(
            [self._console_script()], capture_output=True, text=True
        )
        assert (result.returncode, result.stdout) == (3, "")
        assert _assert_envelope(result.stderr, "usage")["code"] == "missing_command"
