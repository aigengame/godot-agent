"""Shared drivers for the gda-balancing suite.

``run_cli`` drives :func:`gda_balancing.dispatch.dispatch` in-process (fast
rows); the subprocess smoke in test_cli_conformance.py separately proves the
installed entry points. ``fault_registry`` is bADR-0011's fault-injection
seam: a registry copy whose handlers raise, driving the `internal` row —
production has no fault path.

``doc_dir`` + ``invocation`` are the document-taking-command drivers: a
descriptor's ``valid_document`` / ``refusing_document`` fixtures are JSON
*content*, so the harness materializes them to real files under ``doc_dir``
and appends the path as the positional argument. Content (never a committed
``.json`` path) keeps fixtures cwd-independent and off the isolation gate's
per-game-config scan.

``minimal_design_path`` is the one committed golden of the V1 minimal Design
document (``tests/fixtures/minimal_design.json``) — the single source the
boundary tests point at instead of each re-inlining the same minimal literal.
A test needing the text (to mutate it) reads it off the path; a test needing a
dict loads it. It lives under ``tests/`` so the isolation gate's per-game-config
scan (``src/`` only) never sees it, and it names no game identity.
"""

import io
import itertools
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from gda_balancing.commands import REGISTRY
from _legacy_design_adapters import DESIGN_FORMAT, DESIGN_VALIDATE
from gda_balancing.descriptors import CommandDescriptor
from gda_balancing.dispatch import dispatch
from gda_balancing.schema2.authority import (
    AdmittedAuthorityContext,
    packaged_authority_context,
)

RunResult = tuple[int, str, str]

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def pristine_authority_context() -> AdmittedAuthorityContext:
    """One deeply immutable admitted baseline shared by read-only consumers."""
    return packaged_authority_context()


@pytest.fixture
def authority_candidate(
    pristine_authority_context: AdmittedAuthorityContext,
) -> dict[str, object]:
    """One independently owned mutable authority candidate for a test boundary."""
    kernel, language_bundle = pristine_authority_context.mutable_pair()
    admission = pristine_authority_context.admission
    return {
        "kernel": kernel,
        "language_bundle": language_bundle,
        "admission": {
            "admitted": admission.admitted,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }


@pytest.fixture(autouse=True)
def isolated_schema2_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test one explicit local-store trust boundary."""
    monkeypatch.setenv(
        "GDA_BALANCING_STORE_DIR", str(tmp_path / ".gda-balancing-store-v2")
    )
    monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a5" * 32)


@pytest.fixture
def minimal_design_path() -> Path:
    """The committed V1 minimal Design document — the one golden the boundary
    tests point at instead of re-inlining the minimal literal."""
    return _FIXTURES_DIR / "minimal_design.json"


def _run(
    argv: list[str],
    registry: tuple[CommandDescriptor, ...] | None = None,
    *,
    stdin: str = "",
) -> RunResult:
    stdout, stderr, input_stream = io.StringIO(), io.StringIO(), io.StringIO(stdin)
    if registry is None:
        exit_code = dispatch(argv, stdout, stderr, stdin=input_stream)
    else:
        exit_code = dispatch(
            argv, stdout, stderr, registry=registry, stdin=input_stream
        )
    return exit_code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def run_cli() -> Callable[..., RunResult]:
    return _run


@pytest.fixture
def run_legacy_cli() -> Callable[..., RunResult]:
    """Drive the unregistered 1.x source-input adapters for migration regression."""

    def _run_legacy(argv: list[str]) -> RunResult:
        return _run(argv, registry=(DESIGN_VALIDATE, DESIGN_FORMAT))

    return _run_legacy


def _command_path(descriptor: CommandDescriptor) -> list[str]:
    return ([descriptor.group] if descriptor.group else []) + [descriptor.command]


@pytest.fixture(scope="session")
def doc_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One shared directory the materialized document fixtures live in."""
    return tmp_path_factory.mktemp("documents")


@pytest.fixture
def invocation(doc_dir: Path, tmp_path: Path) -> Callable[..., list[str]]:
    """Build a descriptor's full invocation argv.

    The command path is derived from the descriptor (identity cannot drift);
    for a document-taking command the registered ``valid_document`` (or, with
    ``refusing=True``, ``refusing_document``) is written to a stable-named file
    under ``doc_dir`` and its path appended after ``valid_args``.
    """

    sequence = itertools.count(1)

    def _build(
        descriptor: CommandDescriptor,
        *,
        refusing: bool = False,
        verdicting: bool = False,
    ) -> list[str]:
        fixtures = descriptor.fixtures
        token = next(sequence)
        content = (
            fixtures.refusing_document
            if refusing
            else (
                fixtures.prepare_verdict_document(tmp_path, token)
                if verdicting and fixtures.prepare_verdict_document is not None
                else (
                    fixtures.prepare_valid_document(tmp_path, token)
                    if fixtures.prepare_valid_document is not None
                    else fixtures.valid_document
                )
            )
        )
        tail = list(
            fixtures.refusing_args
            if refusing and fixtures.refusing_args
            else fixtures.valid_args
        )
        if descriptor.artifact_set:
            tail.extend(
                [
                    "--out",
                    str(tmp_path / f"artifact-set-{token}"),
                    "--invocation-key",
                    f"{token:064x}",
                ]
            )
        if content is not None:
            label = (
                "refusing" if refusing else ("verdicting" if verdicting else "valid")
            )
            name = "-".join([*_command_path(descriptor), label]) + ".json"
            path = doc_dir / name
            path.write_text(content, encoding="utf-8")
            tail.append(str(path))
        return [*_command_path(descriptor), *tail]

    return _build


def _raise_injected_fault(_input: object) -> object:
    raise RuntimeError("injected fault (conformance harness)")


@pytest.fixture
def fault_registry() -> tuple[CommandDescriptor, ...]:
    return tuple(replace(d, handler=_raise_injected_fault) for d in REGISTRY)
