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
from gda_balancing.descriptors import CommandDescriptor
from gda_balancing.dispatch import dispatch

RunResult = tuple[int, str, str]

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_schema2_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test one explicit local-store trust boundary."""
    monkeypatch.setenv(
        "GDA_BALANCING_STORE_DIR", str(tmp_path / ".gda-balancing-store-v2")
    )


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

    def _build(descriptor: CommandDescriptor, *, refusing: bool = False) -> list[str]:
        fixtures = descriptor.fixtures
        content = fixtures.refusing_document if refusing else fixtures.valid_document
        tail = list(fixtures.valid_args)
        if descriptor.artifact_set:
            token = next(sequence)
            tail.extend(
                [
                    "--out",
                    str(tmp_path / f"artifact-set-{token}"),
                    "--invocation-key",
                    f"{token:064x}",
                ]
            )
        if content is not None:
            label = "refusing" if refusing else "valid"
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
