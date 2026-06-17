"""S1 (e2e): gda schema against the real installed console script.

Runs the installed `gda` console script as a subprocess and asserts its
aggregate manifest covers the live command tree — every command reachable from
the CLI appears (issue #192, ADR-0012). `gda schema` is pure schema emission, so
no Godot engine is spawned; this exercises the real entry point and argv path
(not the in-process CliRunner) that the fast tests use.
"""

import json
import shutil
import subprocess

import pytest
import typer

from gda.cli import app


def _live_command_names() -> set[str]:
    """Walk the in-process Typer tree into `<group> <command>` leaf names."""
    names: set[str] = set()

    def walk(command, path: list[str]) -> None:
        subcommands = getattr(command, "commands", None)
        if subcommands is not None:
            for name, subcommand in subcommands.items():
                walk(subcommand, [*path, name])
            return
        names.add(" ".join(path))

    walk(typer.main.get_command(app), [])
    return names


@pytest.mark.e2e
def test_gda_schema_manifest_covers_the_live_command_tree():
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    proc = subprocess.run([gda_bin, "schema"], capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr
    manifest = json.loads(proc.stdout)
    names = {entry["name"] for entry in manifest["commands"]}
    # The real binary's manifest is the whole live surface — nothing dropped.
    assert names == _live_command_names()
    # And it is genuinely the full surface, not a stub.
    assert {"info", "schema", "scene create"} <= names
    # Every entry carries the full per-command contract.
    for entry in manifest["commands"]:
        assert set(entry) >= {"name", "description", "input", "output", "error"}
        assert entry["description"].strip()
