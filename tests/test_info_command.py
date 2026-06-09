"""S3: gda info with a fake Godot runner maps success to JSON output / exit 0."""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult

VERSION_INFO = {
    "major": 4,
    "minor": 6,
    "patch": 3,
    "hex": 0x040603,
    "status": "stable",
    "build": "official",
    "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
    "string": "4.6.3-stable (official)",
    "timestamp": 0,
}


class FakeRunner:
    """A fakeable GodotRunner that records its calls and returns a canned result."""

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    def run(self, operation: str, params: dict) -> RunResult:
        self.calls.append((operation, params))
        return self.result


def test_info_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner / warnings around the sentinel, plus diagnostics on stderr.
    stdout = (
        "Godot Engine v4.6.3.stable.official\n"
        "WARNING: benign\n"
        "<<<GDA:RESULT>>>" + json.dumps(VERSION_INFO) + "<<<GDA:END>>>\n"
    )
    fake = FakeRunner(RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0))
    monkeypatch.setattr("gda.cli._make_runner", lambda binary: fake)

    result = CliRunner().invoke(app, ["info", "--json"])

    assert result.exit_code == 0
    # stdout carries ONLY the result payload — a single valid JSON object.
    data = json.loads(result.stdout)
    assert data["major"] == 4
    assert data["minor"] == 6
    assert data["string"] == "4.6.3-stable (official)"
    # The info operation was dispatched by name.
    assert fake.calls == [("info", {})]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr
