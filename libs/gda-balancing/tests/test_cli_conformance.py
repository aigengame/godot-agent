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
from pathlib import Path

import jsonschema
import pytest
from pydantic import BaseModel, create_model

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
    REFUSAL_BOUND,
    USAGE_CODES,
    Refusal,
    RefusalReport,
)
from gda_balancing.schema.funnel import refusal_code_namespace


def _command_path(descriptor: CommandDescriptor) -> list[str]:
    return ([descriptor.group] if descriptor.group else []) + [descriptor.command]


def _assert_envelope(stderr_text: str, category: str) -> dict:
    """stderr parses as exactly one schema-valid envelope of ``category``."""
    payload = json.loads(stderr_text)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == category
    return payload["error"]


_IDS = [" ".join(_command_path(d)) for d in REGISTRY]


@pytest.mark.parametrize("descriptor", REGISTRY, ids=_IDS)
class TestPerDescriptorRows:
    def test_success_row(self, descriptor, run_cli, invocation):
        exit_code, stdout, stderr = run_cli(invocation(descriptor))
        assert (exit_code, stderr) == (0, "")
        payload = json.loads(stdout)
        jsonschema.validate(payload, descriptor.output_model.model_json_schema())
        # Canonical emission (bADR-0005): re-rendering the parsed document
        # reproduces the bytes — sorted keys, LF, defaults materialized.
        assert stdout == canonical_json(payload)

    def test_usage_row(self, descriptor, run_cli, invocation):
        argv = [*invocation(descriptor), "--no-such-argument"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        error = _assert_envelope(stderr, "usage")
        assert error["code"] in USAGE_CODES

    def test_internal_row(self, descriptor, run_cli, fault_registry, invocation):
        argv = invocation(descriptor)
        exit_code, stdout, stderr = run_cli(argv, fault_registry)
        assert (exit_code, stdout) == (4, "")
        error = _assert_envelope(stderr, "internal")
        assert error["code"] == "internal_error"
        assert "diagnostics" not in error  # only under --debug
        assert "Traceback" not in stderr  # sanitized by default

    def test_internal_row_debug_diagnostics(
        self, descriptor, run_cli, fault_registry, invocation
    ):
        argv = [*invocation(descriptor), "--debug"]
        exit_code, stdout, stderr = run_cli(argv, fault_registry)
        assert (exit_code, stdout) == (4, "")
        error = _assert_envelope(stderr, "internal")
        assert "injected fault" in error["diagnostics"]

    def test_wrong_success_model_row(self, descriptor, run_cli, invocation):
        # The declared output model is authoritative at runtime: a handler
        # returning any other model must take the internal path, never emit
        # exit-0 stdout that contradicts the descriptor's own --schema.
        class Bogus(BaseModel):
            unexpected: int = 7

        registry = tuple(
            dataclasses.replace(d, handler=lambda _i: Bogus()) for d in REGISTRY
        )
        exit_code, stdout, stderr = run_cli(invocation(descriptor), registry)
        assert (exit_code, stdout) == (4, "")
        assert _assert_envelope(stderr, "internal")["code"] == "internal_error"

    def test_subclass_success_model_row(self, descriptor, run_cli, invocation):
        # The identity check is EXACT: an output-model SUBCLASS with an extra
        # field would pass isinstance yet serialize past the closed output
        # schema — it must take the internal path like any wrong model.
        extended = create_model(
            "Extended", __base__=descriptor.output_model, unexpected=(int, 7)
        )
        registry = tuple(
            dataclasses.replace(
                d,
                handler=lambda i, _d=d, _e=extended: _e.model_validate(
                    {**_d.handler(i).model_dump(), "unexpected": 7}
                ),
            )
            for d in REGISTRY
        )
        exit_code, stdout, stderr = run_cli(invocation(descriptor), registry)
        assert (exit_code, stdout) == (4, "")
        assert _assert_envelope(stderr, "internal")["code"] == "internal_error"

    def test_refusal_row(self, descriptor, run_cli, invocation):
        # Document-taking commands only: the registered refusing document must
        # yield a `refusal` envelope on stdout / exit 2, and every entry code
        # must resolve against the funnel's namespace — the CLI can never grow
        # a second refusal-code registry (bADR-0011).
        if descriptor.fixtures.refusing_document is None:
            pytest.skip("no refusing document: not a document-taking command")
        exit_code, stdout, stderr = run_cli(invocation(descriptor, refusing=True))
        assert (exit_code, stderr) == (2, "")
        payload = json.loads(stdout)
        jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
        assert payload["error"]["category"] == "refusal"
        namespace = refusal_code_namespace()
        for entry in payload["error"]["refusals"]:
            assert entry["code"] in namespace

    def test_input_immutability_row(self, descriptor, run_cli, invocation):
        # A document-taking command never rewrites its input (bADR-0011).
        if descriptor.fixtures.valid_document is None:
            pytest.skip("no input document: not a document-taking command")
        argv = invocation(descriptor)
        document_path = Path(argv[-1])  # the positional path is appended last
        before = document_path.read_bytes()
        run_cli(argv)
        assert document_path.read_bytes() == before

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

    def test_seed_row_deterministic_refuses_seed(self, descriptor, run_cli, invocation):
        assert not descriptor.stochastic  # no v1 command is stochastic
        argv = [*invocation(descriptor), "--seed", "1"]
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

    def test_refusal_outcome_maps_to_refusal_envelope_exit_2(self, run_cli, invocation):
        # No v1 command produces refusals (#504 lands the funnel); the seam
        # is proven by injection, like the internal row: a handler returning
        # a RefusalReport must yield the refusal envelope on STDOUT, exit 2.
        # Driven at both constructible edges — the outcome models bound what
        # a handler can build (bADR-0011's outcome→invocation-result
        # invariant: whatever constructs emits schema-valid stdout).
        minimal = RefusalReport(
            refusals=(Refusal(code="some_refusal", path="", detail="why"),),
            truncated=False,
        )
        at_bound = RefusalReport(
            refusals=tuple(
                Refusal(code="some_refusal", path=f"/attributes/{i}", detail="why")
                for i in range(REFUSAL_BOUND)
            ),
            truncated=True,
        )
        for report in (minimal, at_bound):
            registry = tuple(
                dataclasses.replace(d, handler=lambda _i, _r=report: _r)
                for d in REGISTRY
            )
            for descriptor in registry:
                exit_code, stdout, stderr = run_cli(invocation(descriptor), registry)
                assert (exit_code, stderr) == (2, "")
                payload = json.loads(stdout)
                jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
                assert payload["error"]["category"] == "refusal"
                assert payload["error"]["truncated"] is report.truncated
                assert len(payload["error"]["refusals"]) == len(report.refusals)

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
