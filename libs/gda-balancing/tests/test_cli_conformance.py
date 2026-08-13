"""The bADR-0011 conformance harness — walks the registry, asserts every
applicable bADR-0008 row per registered command, plus the cross-walk laws
(reserved names, envelope byte-identity). The true-subprocess tier lives in
test_e2e_cli.py per the family's e2e naming convention.
"""

import dataclasses
import json
import os
from pathlib import Path

import jsonschema
import pytest
from pydantic import BaseModel, create_model

from gda_balancing.interfaces.cli.registry import REGISTRY
from gda_balancing.interfaces.cli.descriptors import (
    RESERVED_GROUPS,
    RESERVED_META,
    CommandDescriptor,
    build_registry,
)
from gda_balancing.interfaces.cli.rendering import canonical_json
from gda_balancing.interfaces.cli.envelope import (
    ERROR_ENVELOPE_SCHEMA,
    USAGE_CODES,
)
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.schema.refusal import REFUSAL_BOUND, Refusal, RefusalReport
from gda_balancing.interfaces.cli.surface import schema2_error_envelope_schema


def _command_path(descriptor: CommandDescriptor) -> list[str]:
    return ([descriptor.group] if descriptor.group else []) + [descriptor.command]


def _assert_envelope(stderr_text: str, category: str) -> dict:
    """stderr parses as exactly one schema-valid envelope of ``category``."""
    payload = json.loads(stderr_text)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == category
    return payload["error"]


def _record_not_applicable(request: pytest.FixtureRequest, reason: str) -> None:
    """Keep capability-inapplicable matrix rows visible without counting a skip."""
    request.node.user_properties.extend(
        (
            ("gda-balancing.applicability", "not-applicable"),
            ("gda-balancing.applicability-reason", reason),
        )
    )


_IDS = [" ".join(_command_path(descriptor)) for descriptor in REGISTRY]


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

    def test_verdict_row(self, descriptor, run_cli, invocation, request):
        has_verdict_model = descriptor.verdict_model is not None
        has_verdict_fixture = descriptor.fixtures.prepare_verdict_document is not None
        assert has_verdict_model == has_verdict_fixture
        if not has_verdict_model:
            _record_not_applicable(request, "descriptor declares no Verdict outcome")
            return
        exit_code, stdout, stderr = run_cli(invocation(descriptor, verdicting=True))
        assert (exit_code, stderr) == (1, "")
        payload = json.loads(stdout)
        jsonschema.validate(payload, descriptor.verdict_model.model_json_schema())
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
        assert "debug" not in error
        if descriptor.schema_major == 2:
            jsonschema.validate(
                json.loads(stderr), schema2_error_envelope_schema(descriptor)
            )
        assert "Traceback" not in stderr  # sanitized by default

    def test_internal_row_debug_diagnostics(
        self, descriptor, run_cli, fault_registry, invocation
    ):
        argv = [*invocation(descriptor), "--debug"]
        exit_code, stdout, stderr = run_cli(argv, fault_registry)
        assert (exit_code, stdout) == (4, "")
        if descriptor.schema_major == 2:
            payload = json.loads(stderr)
            jsonschema.validate(payload, schema2_error_envelope_schema(descriptor))
            error = payload["error"]
            assert error["category"] == "internal"
            assert "diagnostics" not in error
            assert "injected fault" in error["debug"]
        else:
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
        if descriptor.output_model.__pydantic_root_model__:
            pytest.skip(
                "RootModel output: pydantic forbids a subclass carrying an extra "
                "field, so the closed-schema subclass risk this row guards is "
                "structurally unreachable (the artifact IS the bare result)"
            )
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
        # A descriptor-owned refusing document or argument tail must yield the
        # command's declared stable refusal envelope on stdout / exit 2.
        if (
            descriptor.fixtures.refusing_document is None
            and not descriptor.fixtures.refusing_args
        ):
            pytest.skip("no descriptor-owned refusing fixture")
        exit_code, stdout, stderr = run_cli(invocation(descriptor, refusing=True))
        assert (exit_code, stderr) == (2, "")
        payload = json.loads(stdout)
        assert payload["error"]["category"] == "refusal"
        jsonschema.validate(payload, schema2_error_envelope_schema(descriptor))
        catalog = {code for code, _stage in descriptor.resolved_refusal_catalog()}
        for entry in payload["error"]["diagnostics"]:
            assert entry["code"] in catalog

    def test_input_immutability_row(self, descriptor, run_cli, invocation):
        # A document-taking command never rewrites its input (bADR-0011).
        if not descriptor.fixtures.has_valid_document:
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
        if descriptor.schema_major == 2:
            expected = [
                "artifact_kind",
                "content_identity",
                "descriptor_identity",
                "error",
                "input",
                "profile_identity",
                "success",
            ]
            if descriptor.verdict_model is not None:
                expected.append("verdict")
            assert sorted(payload) == sorted(expected)
        else:
            assert sorted(payload) == ["error", "input", "output"]

    def test_schema_wins_over_any_other_argument(self, descriptor, run_cli):
        argv = [*_command_path(descriptor), "--no-such-argument", "--schema"]
        exit_code, _stdout, stderr = run_cli(argv)
        assert (exit_code, stderr) == (0, "")

    def test_seed_row_deterministic_refuses_seed(self, descriptor, run_cli, invocation):
        # RNG ownership is descriptor input, never a dispatch-level override.
        argv = [*invocation(descriptor), "--seed", "1"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "unknown_argument"

    # --- Artifact-sink rows (bADR-0009), keyed on `descriptor.artifact_sink` ---

    def test_artifact_sink_row(
        self, descriptor, run_cli, invocation, tmp_path, request
    ):
        # `--out <path>` moves the artifact body to the sink and puts the receipt
        # on stdout; the sink's bytes equal the no-`--out` stdout of the same
        # invocation, and the receipt names the resolved sink and its byte size.
        if not descriptor.artifact_sink:
            _record_not_applicable(request, "descriptor is not an artifact sink")
            return
        argv = invocation(descriptor)
        _, body, _ = run_cli(argv)
        sink = tmp_path / "artifact.json"
        exit_code, stdout, stderr = run_cli([*argv, "--out", str(sink)])
        assert (exit_code, stderr) == (0, "")
        assert sink.read_bytes() == body.encode("utf-8")
        payload = json.loads(stdout)
        jsonschema.validate(payload, descriptor.output_model.model_json_schema())
        assert payload["artifact"]["path"] == os.path.realpath(str(sink))
        assert payload["artifact"]["bytes"] == sink.stat().st_size
        # Atomic write-then-rename leaves the sink's directory with no temp litter.
        assert [p.name for p in tmp_path.iterdir()] == ["artifact.json"]

    def test_receipt_forbidden_without_out(
        self, descriptor, run_cli, invocation, request
    ):
        # bADR-0009: the receipt member is present exactly when `--out` was used,
        # forbidden otherwise — so a no-`--out` object body carries no `artifact`.
        if not descriptor.artifact_sink:
            _record_not_applicable(request, "descriptor is not an artifact sink")
            return
        _, stdout, _ = run_cli(invocation(descriptor))
        parsed = json.loads(stdout)
        if isinstance(parsed, dict):
            assert "artifact" not in parsed

    def test_out_aliasing_input_is_argument_conflict(
        self, descriptor, run_cli, invocation, request
    ):
        # No command writes to its input path (bADR-0009): `--out <the input
        # path>` is a usage `argument_conflict`, and the input file is untouched.
        if not descriptor.artifact_sink or not descriptor.fixtures.has_valid_document:
            _record_not_applicable(
                request,
                "descriptor has no artifact-sink document input",
            )
            return
        argv = invocation(descriptor)
        input_path = argv[-1]  # the positional path is appended last
        before = Path(input_path).read_bytes()
        exit_code, stdout, stderr = run_cli([*argv, "--out", input_path])
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "argument_conflict"
        assert Path(input_path).read_bytes() == before

    def test_unwritable_sink_is_usage_error(
        self, descriptor, run_cli, invocation, request
    ):
        # An unwritable sink is a usage `unwritable_output` (bADR-0008/0009); the
        # write precedes stdout, so exit 3 keeps stdout empty.
        if not descriptor.artifact_sink:
            _record_not_applicable(request, "descriptor is not an artifact sink")
            return
        argv = [*invocation(descriptor), "--out", "/nonexistent-dir/x.json"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "unwritable_output"

    def test_non_sink_rejects_out(self, descriptor, run_cli, invocation):
        # Only artifact-sink commands accept `--out`; anywhere else it is an
        # unknown argument (bADR-0009).
        if descriptor.artifact_sink or descriptor.artifact_set:
            pytest.skip("artifact-producing command accepts --out")
        argv = [*invocation(descriptor), "--out", "x"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "unknown_argument"


class TestSurfaceLaws:
    def test_error_schema_is_line_or_descriptor_owned(self, run_cli):
        for descriptor in REGISTRY:
            _, stdout, _ = run_cli([*_command_path(descriptor), "--schema"])
            actual = canonical_json(json.loads(stdout)["error"])
            assert actual == canonical_json(schema2_error_envelope_schema(descriptor))
        assert all(descriptor.schema_major == 2 for descriptor in REGISTRY)

    def test_schema2_runtime_rejects_usage_outside_descriptor_catalog(self, run_cli):
        descriptor = next(item for item in REGISTRY if item.schema_major == 2)
        registry = tuple(
            dataclasses.replace(item, usage_codes=()) if item is descriptor else item
            for item in REGISTRY
        )

        exit_code, stdout, stderr = run_cli(
            [*_command_path(descriptor), "--no-such-argument"], registry
        )

        assert (exit_code, stdout) == (4, "")
        assert _assert_envelope(stderr, "internal")["code"] == "internal_error"

    def test_schema2_runtime_rejects_handler_usage_outside_descriptor_catalog(
        self, run_cli, invocation
    ):
        descriptor = next(item for item in REGISTRY if item.schema_major == 2)

        def unreadable(_input):
            raise UnreadableInputError("injected unreadable input")

        registry = tuple(
            dataclasses.replace(item, usage_codes=(), handler=unreadable)
            if item is descriptor
            else item
            for item in REGISTRY
        )

        exit_code, stdout, stderr = run_cli(invocation(descriptor), registry)

        assert (exit_code, stdout) == (4, "")
        assert _assert_envelope(stderr, "internal")["code"] == "internal_error"

    def test_schema2_runtime_rejects_sink_usage_outside_descriptor_catalog(
        self, run_cli, invocation
    ):
        descriptor = next(item for item in REGISTRY if item.schema_major == 2)
        registry = tuple(
            dataclasses.replace(item, usage_codes=(), artifact_sink=True)
            if item is descriptor
            else item
            for item in REGISTRY
        )

        exit_code, stdout, stderr = run_cli(
            [*invocation(descriptor), "--out", "/nonexistent-dir/result.json"],
            registry,
        )

        assert (exit_code, stdout) == (4, "")
        assert _assert_envelope(stderr, "internal")["code"] == "internal_error"

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

    def test_legacy_refusal_cannot_enter_the_schema2_dispatch_path(
        self, run_cli, invocation
    ):
        # Standard Schema 1.x exists only behind the source-migration boundary.
        # Returning its refusal type from any active 2.x descriptor is a host
        # bug and must not serialize as a public Schema 2.x refusal.
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
                assert (exit_code, stdout) == (4, "")
                assert _assert_envelope(stderr, "internal")["code"] == "internal_error"

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
