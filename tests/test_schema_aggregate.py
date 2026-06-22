"""`gda schema` aggregate-surface manifest (issue #192, ADR-0012, ADR-0004).

`gda schema` is a meta command (ADR-0005): top-level and ungrouped, a sibling of
`gda info`. In a single process — no Godot spawned — it emits the **dispatchable**
command surface as one JSON document, one entry per dispatchable command carrying
`{name, description, input, output, error}`. It is the whole-surface
generalisation of per-command `--schema` (ADR-0004): the machine-readable
manifest gda-mcp introspects once at startup to generate its tool surface
(ADR-0012). A non-dispatchable meta command — one with no backing operation, so
no `--params-json` (e.g. `gda schema` itself) — is excluded from the surface it
describes (Plan A); `gda schema --schema` still self-describes as any command.

These are fast tests — `gda schema` spawns no Godot, so none of them need the
engine. Most drive the command in-process via `CliRunner`; the last drives the
real installed `gda` console script as a subprocess to protect the public entry
point. That one is deliberately NOT marked `e2e`: this repo's `e2e` marker means
"spawns a real Godot process" and gates a schedule/manual-only CI job, whereas
this check is cheap and deterministic and belongs in the default PR gate.
"""

import json
import shutil
import subprocess

import typer
from typer.testing import CliRunner

from gda.cli import app


def _manifest() -> dict:
    result = CliRunner().invoke(app, ["schema"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _live_dispatchable_command_names() -> set[str]:
    """Independently walk the live Typer tree into ``<group> <command>`` names.

    Mirrors the manifest's enumeration via a separate traversal so the coverage
    assertion is a real cross-check, not a tautology against the production
    walker. Restricted to *dispatchable* commands — the manifest excludes
    non-dispatchable meta commands (Plan A) — but keyed on a signal INDEPENDENT
    of production's ``gda_command``: whether the command exposes a
    ``--params-json`` option. The two signals are 1:1, so requiring them to agree
    keeps this an honest cross-check rather than a mirror of the production rule.
    """
    names: set[str] = set()

    def walk(command, path: list[str]) -> None:
        subcommands = getattr(command, "commands", None)
        if subcommands is not None:
            for name, subcommand in subcommands.items():
                walk(subcommand, [*path, name])
            return
        dispatchable = any(
            getattr(p, "name", None) == "params_json" for p in command.params
        )
        if dispatchable:
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


def test_manifest_covers_every_dispatchable_command_reachable_from_the_cli():
    # The manifest is a faithful mirror of the live command tree's dispatchable
    # commands (ADR-0012, Plan A): every dispatchable command present, nothing
    # else dropped or deduped, and only non-dispatchable meta commands excluded.
    names = {entry["name"] for entry in _manifest()["commands"]}
    assert names == _live_dispatchable_command_names()


def test_non_dispatchable_meta_commands_are_excluded():
    # Plan A (ADR-0012): the manifest is the dispatchable-operation surface. `gda
    # schema` is a live, reachable command but a pure self-describer with no
    # backing operation (no --params-json), so it is NOT a manifest entry —
    # re-listing the describer inside the surface it describes would be circular.
    names = {entry["name"] for entry in _manifest()["commands"]}
    assert "schema" not in names
    # …yet it remains a real command that self-describes under its own --schema.
    assert CliRunner().invoke(app, ["schema", "--schema"]).exit_code == 0


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


def test_every_entry_carries_an_execution_kind():
    # issue #230: each manifest entry advertises its static execution `kind`
    # (HEADLESS / EXPORT / LIVE) so gda-mcp / an agent can branch on a command's
    # channel without inferring it. The enum subclasses `str`, so the value is the
    # lowercase string, never the Python enum repr.
    entries = _manifest()["commands"]
    assert entries
    for entry in entries:
        assert entry["kind"] in {"headless", "export", "live"}, entry["name"]


def test_entry_kind_matches_the_commands_own_schema_kind():
    # Each entry's `kind` is the same single source of truth the command emits
    # under its own `--schema` (ADR-0004 / ADR-0012): one descriptor field, not a
    # parallel projection — so the aggregate and per-command forms must agree.
    for entry in _manifest()["commands"]:
        result = CliRunner().invoke(app, [*entry["name"].split(" "), "--schema"])
        assert result.exit_code == 0, result.stdout
        own = json.loads(result.stdout)
        assert entry["kind"] == own["kind"], entry["name"]


def test_all_three_execution_kinds_appear_in_the_aggregate():
    # The surface spans all three channels: the default HEADLESS commands, the
    # one EXPORT command (`export run`), and the LIVE commands (`game tree`).
    by_name = {entry["name"]: entry for entry in _manifest()["commands"]}
    assert by_name["scene get"]["kind"] == "headless"
    assert by_name["export run"]["kind"] == "export"
    assert by_name["game tree"]["kind"] == "live"
    # All three kinds are represented in the aggregate as a whole.
    kinds = {entry["kind"] for entry in by_name.values()}
    assert {"headless", "export", "live"} <= kinds


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


def test_real_console_script_manifest_covers_the_live_command_tree():
    # The real installed `gda` entry point — not the in-process CliRunner —
    # emits the manifest and covers the whole live command tree (issue #192).
    # Under `uv run` (how CI runs the fast suite) this resolves to the project
    # venv's console script, so it tracks the current checkout.
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    proc = subprocess.run([gda_bin, "schema"], capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr
    names = {entry["name"] for entry in json.loads(proc.stdout)["commands"]}
    assert names == _live_dispatchable_command_names()
    assert {"info", "scene create"} <= names
    # The non-dispatchable `schema` meta command is excluded (Plan A).
    assert "schema" not in names
