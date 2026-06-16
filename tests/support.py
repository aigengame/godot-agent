"""Shared test support for driving gda commands without a real engine (S3).

``FakeRunner`` satisfies the ``GodotRunner`` protocol with a canned raw
``RunResult`` and records dispatched ``(operation, params)`` calls, so command
tests exercise the full Typer→classify→JSON pipeline engine-free. ``sentinel``
wraps a payload in the ADR-0002 result sentinels the way ``operations.gd``
emits it.
"""

import json

from gda.export_runner import ExportRunOutput
from gda.runner import RunResult


class FakeRunner:
    """A fakeable GodotRunner that records its calls and returns a canned result."""

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    def run(self, operation: str, params: dict) -> RunResult:
        self.calls.append((operation, params))
        return self.result


class FakeExportRunner:
    """A fakeable ExportRunner for ``export run`` (issue #121).

    Records each ``(preset, mode, output_path)`` it is asked to export and returns
    a canned :class:`~gda.export_runner.ExportRunOutput`, so the native-export
    pipeline is exercised without a real engine, mirroring :class:`FakeRunner` for
    the sentinel channel.
    """

    def __init__(self, output: ExportRunOutput) -> None:
        self.output = output
        self.calls: list[tuple[str, str, str]] = []

    def run(self, preset: str, mode: str, output_path: str) -> ExportRunOutput:
        self.calls.append((preset, mode, output_path))
        return self.output


def sentinel(payload: dict) -> str:
    """Wrap ``payload`` in the ADR-0002 result sentinels, as operations.gd emits."""
    return f"<<<GDA:RESULT>>>{json.dumps(payload)}<<<GDA:END>>>\n"


def error_sentinel(code: str, message: str) -> str:
    """Wrap a minimal ADR-0002 operation error envelope in result sentinels."""
    return sentinel({"error": {"code": code, "message": message}})


def inject_runner(monkeypatch, result: RunResult) -> FakeRunner:
    """Swap the CLI's runner seam for a ``FakeRunner`` returning ``result``."""
    fake = FakeRunner(result)
    monkeypatch.setattr("gda.cli._make_runner", lambda binary, project=None: fake)
    return fake
