"""S3: gda info with a fake Godot runner maps success to JSON output / exit 0."""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import VERSION_INFO, inject_runner, sentinel


def test_info_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner / warnings around the sentinel, plus diagnostics on stderr.
    stdout = "Godot Engine v4.6.3.stable.official\nWARNING: benign\n" + sentinel(
        VERSION_INFO
    )
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

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
