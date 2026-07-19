"""Shared drivers for the gda-balancing suite.

``run_cli`` drives :func:`gda_balancing.dispatch.dispatch` in-process (fast
rows); the subprocess smoke in test_cli_conformance.py separately proves the
installed entry points. ``fault_registry`` is bADR-0011's fault-injection
seam: a registry copy whose handlers raise, driving the `internal` row —
production has no fault path.
"""

import io
from collections.abc import Callable
from dataclasses import replace

import pytest

from gda_balancing.commands import REGISTRY
from gda_balancing.descriptors import CommandDescriptor
from gda_balancing.dispatch import dispatch

RunResult = tuple[int, str, str]


def _run(
    argv: list[str], registry: tuple[CommandDescriptor, ...] | None = None
) -> RunResult:
    stdout, stderr = io.StringIO(), io.StringIO()
    if registry is None:
        exit_code = dispatch(argv, stdout, stderr)
    else:
        exit_code = dispatch(argv, stdout, stderr, registry=registry)
    return exit_code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def run_cli() -> Callable[..., RunResult]:
    return _run


def _raise_injected_fault(_input: object) -> object:
    raise RuntimeError("injected fault (conformance harness)")


@pytest.fixture
def fault_registry() -> tuple[CommandDescriptor, ...]:
    return tuple(replace(d, handler=_raise_injected_fault) for d in REGISTRY)
