"""The bADR-0011 conformance harness — walks the registry, asserts every
applicable bADR-0008 row per registered command, plus the cross-walk laws
(reserved names, envelope byte-identity). The true-subprocess tier lives in
test_e2e_cli.py per the family's e2e naming convention.
"""

import dataclasses
import json
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
        registry = None
        if descriptor.execution_lifecycle == "foreground-service":
            readiness = descriptor.fixtures.foreground_readiness
            assert readiness is not None

            def emit_fixture(_input, emit_ready, _stderr):
                emit_ready(descriptor.output_model.model_validate(readiness))
                return 0

            registry = tuple(
                dataclasses.replace(item, foreground_runner=emit_fixture)
                if item is descriptor
                else item
                for item in REGISTRY
            )
        exit_code, stdout, stderr = run_cli(invocation(descriptor), registry)
        assert (exit_code, stderr) == (0, "")
        payload = json.loads(stdout)
        jsonschema.validate(payload, descriptor.output_model.model_json_schema())
        # Canonical emission (bADR-0005): re-rendering the parsed document
        # reproduces the bytes — sorted keys, LF, defaults materialized.
        assert stdout == canonical_json(payload)

    def test_verdict_row(self, descriptor, run_cli, invocation, request):
        has_verdict_model = descriptor.verdict_model is not None
        has_verdict_fixture = descriptor.fixtures.prepare_verdict_document is not None
        projector = descriptor.fixtures.project_verdict_for_conformance
        assert has_verdict_model == (has_verdict_fixture or projector is not None)
        assert not (has_verdict_fixture and projector is not None)
        if not has_verdict_model:
            _record_not_applicable(request, "descriptor declares no Verdict outcome")
            return
        registry = None
        if projector is not None:
            assert descriptor.handler is not None

            def project_verdict(value, *, source=descriptor, project=projector):
                assert source.handler is not None
                return project(source.handler(value))

            registry = tuple(
                dataclasses.replace(item, handler=project_verdict)
                if item is descriptor
                else item
                for item in REGISTRY
            )
        exit_code, stdout, stderr = run_cli(
            invocation(descriptor, verdicting=has_verdict_fixture), registry
        )
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

        def emit_bogus(_input, emit_ready, _stderr):
            emit_ready(Bogus())
            return 0

        registry = tuple(
            (
                dataclasses.replace(d, foreground_runner=emit_bogus)
                if d.execution_lifecycle == "foreground-service"
                else dataclasses.replace(d, handler=lambda _i: Bogus())
            )
            if d is descriptor
            else d
            for d in REGISTRY
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

        def emit_extended(_input, emit_ready, _stderr):
            emit_ready(extended.model_construct(unexpected=7))
            return 0

        def extended_one_shot(value, *, source=descriptor, model=extended):
            assert source.handler is not None
            return model.model_validate(
                {**source.handler(value).model_dump(), "unexpected": 7}
            )

        registry = tuple(
            (
                dataclasses.replace(d, foreground_runner=emit_extended)
                if d.execution_lifecycle == "foreground-service"
                else dataclasses.replace(d, handler=extended_one_shot)
            )
            if d is descriptor
            else d
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
            and descriptor.fixtures.prepare_args is None
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
        # A document-taking command never rewrites any input file (bADR-0011).
        if (
            not descriptor.fixtures.has_valid_document
            and descriptor.fixtures.prepare_args is None
        ):
            pytest.skip("no input document: not a document-taking command")
        argv = invocation(descriptor)
        document_paths = (
            tuple(Path(value) for value in argv if Path(value).is_file())
            if descriptor.fixtures.prepare_args is not None
            else (Path(argv[-1]),)  # the positional path is appended last
        )
        assert document_paths
        before = {path: path.read_bytes() for path in document_paths}
        run_cli(argv)
        assert {path: path.read_bytes() for path in document_paths} == before

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

    def test_non_sink_rejects_out(self, descriptor, run_cli, invocation, request):
        # Artifact-set producers accept `--out`; other commands reject it.
        if descriptor.artifact_set:
            _record_not_applicable(request, "artifact-producing command accepts --out")
            return
        argv = [*invocation(descriptor), "--out", "x"]
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stdout) == (3, "")
        assert _assert_envelope(stderr, "usage")["code"] == "unknown_argument"


class TestSurfaceLaws:
    def test_foreground_fault_after_readiness_preserves_the_two_stream_contract(
        self,
        run_cli,
    ):
        descriptor = next(
            item
            for item in REGISTRY
            if item.execution_lifecycle == "foreground-service"
        )
        readiness = descriptor.fixtures.foreground_readiness
        assert readiness is not None

        def emit_then_fail(_input, emit_ready, _stderr):
            emit_ready(descriptor.output_model.model_validate(readiness))
            raise RuntimeError("injected post-readiness fault")

        registry = tuple(
            dataclasses.replace(item, foreground_runner=emit_then_fail)
            if item is descriptor
            else item
            for item in REGISTRY
        )

        exit_code, stdout, stderr = run_cli(_command_path(descriptor), registry)

        assert exit_code == 4
        assert json.loads(stdout) == readiness
        error = _assert_envelope(stderr, "internal")
        assert error["code"] == "internal_error"
        assert error["message"] == "the toolkit failed unexpectedly (RuntimeError)"
        assert "Traceback" not in stderr

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
        prepared_invocations = [
            (descriptor, invocation(descriptor)) for descriptor in REGISTRY
        ]
        for report in (minimal, at_bound):
            for descriptor, argv in prepared_invocations:

                def emit_legacy(_input, emit_ready, _stderr, *, value=report):
                    emit_ready(value)
                    return 0

                registry = tuple(
                    (
                        dataclasses.replace(item, foreground_runner=emit_legacy)
                        if item.execution_lifecycle == "foreground-service"
                        else dataclasses.replace(item, handler=lambda _i, _r=report: _r)
                    )
                    if item is descriptor
                    else item
                    for item in REGISTRY
                )
                exit_code, stdout, stderr = run_cli(argv, registry)
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
