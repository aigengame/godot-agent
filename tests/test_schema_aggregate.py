"""`gda schema` aggregate-surface manifest (issue #192, ADR-0012, ADR-0004).

`gda schema` is a meta command (ADR-0005): top-level and ungrouped, a sibling of
`gda info`. In a single process — no Godot spawned — it emits the whole command
surface as one JSON document, one entry per command carrying
`{name, description, input, output, error}`. It is the whole-surface
generalisation of per-command `--schema` (ADR-0004): the machine-readable
manifest gda-mcp introspects once at startup to generate its tool surface
(ADR-0012). These are unit tests; one e2e test runs the real binary.
"""

import json

import typer
from typer.testing import CliRunner

from gda.cli import app


def _manifest() -> dict:
    result = CliRunner().invoke(app, ["schema"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _live_command_names() -> set[str]:
    """Independently walk the live Typer tree into ``<group> <command>`` names.

    Mirrors the manifest's enumeration via a separate traversal so the coverage
    assertion is a real cross-check, not a tautology against the production walker.
    """
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


def test_schema_emits_a_commands_manifest_with_a_known_command():
    result = CliRunner().invoke(app, ["schema"])

    assert result.exit_code == 0, result.stdout
    doc = json.loads(result.stdout)
    # The manifest is a single object holding a non-empty list of commands.
    assert isinstance(doc["commands"], list) and doc["commands"]
    # A known command appears, carrying the full per-command contract.
    by_name = {entry["name"]: entry for entry in doc["commands"]}
    assert "info" in by_name
    assert set(by_name["info"]) >= {"name", "description", "input", "output", "error"}


def test_name_is_the_group_command_mcp_mapping_basis():
    # ADR-0005: a grouped command's name is the `<group> <command>` basis the
    # MCP tool name derives from; a meta command (ungrouped) is bare.
    names = {entry["name"] for entry in _manifest()["commands"]}
    assert "scene create" in names
    assert "info" in names


def test_manifest_covers_every_command_reachable_from_the_cli():
    # The manifest is a faithful mirror of the live command tree (ADR-0012):
    # nothing dropped, filtered, or deduped away.
    names = {entry["name"] for entry in _manifest()["commands"]}
    assert names == _live_command_names()


def test_each_entry_matches_the_commands_own_schema():
    # Each entry's {input, output, error} is byte-for-byte the same contract the
    # command emits under its own `--schema` (ADR-0004): one source of truth,
    # derived through the same CommandSchema.of, not a parallel projection.
    for entry in _manifest()["commands"]:
        result = CliRunner().invoke(app, [*entry["name"].split(" "), "--schema"])
        assert result.exit_code == 0, result.stdout
        own = json.loads(result.stdout)
        assert entry["input"] == own["input"]
        assert entry["output"] == own["output"]
        assert entry["error"] == own["error"]


def test_schema_spawns_no_godot(monkeypatch):
    # Pure schema emission (ADR-0012), like per-command `--schema`: make both
    # binary resolution and the runner explode, then assert it still emits.
    def boom(*args, **kwargs):
        raise AssertionError("gda schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    result = CliRunner().invoke(app, ["schema"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["commands"]


def test_every_command_has_a_non_empty_description():
    # ADR-0012: a command's description becomes its MCP tool description, so the
    # surface is only fully self-describing if none is blank.
    blank = [e["name"] for e in _manifest()["commands"] if not e["description"].strip()]
    assert not blank, f"commands missing a description: {blank}"


def test_every_input_field_has_a_non_empty_description():
    # ADR-0012: each input field's description becomes the MCP parameter
    # description, so every parameter an agent sees must carry one. Field
    # descriptions come from the Pydantic `Field(description=...)` on the params
    # model (not the Typer `help=`), so this gate drives that backfill.
    missing: list[str] = []
    for entry in _manifest()["commands"]:
        for field, spec in entry["input"].get("properties", {}).items():
            if not str(spec.get("description", "")).strip():
                missing.append(f"{entry['name']}: {field}")
    assert not missing, "input fields missing a description:\n" + "\n".join(missing)


def test_schema_command_is_itself_self_describing():
    # The meta command is under the same ADR-0004 gate as every other command:
    # `gda schema --schema` emits its own {input, output, error} contract, with
    # `output` the manifest's own model schema.
    from gda.models import GdaErrorEnvelope, SchemaAllParams, SurfaceManifest

    result = CliRunner().invoke(app, ["schema", "--schema"])

    assert result.exit_code == 0, result.stdout
    doc = json.loads(result.stdout)
    assert doc["input"] == SchemaAllParams.model_json_schema()
    assert doc["output"] == SurfaceManifest.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
