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
real out-of-process `gda` CLI (`python -m gda`, the same `app` the console script
wraps) as a subprocess, so the manifest is exercised through a real process, not
only in-process. That one is deliberately NOT marked `e2e`: this repo's `e2e` marker means
"spawns a real Godot process" and gates a schedule/manual-only CI job, whereas
this check is cheap and deterministic and belongs in the default PR gate.
"""

import json
import subprocess

import typer
from typer.testing import CliRunner

from gda.cli import app
from tests.support import GDA_CMD


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
    monkeypatch.setattr("gda.dispatch._make_runner", boom)

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
    # (HEADLESS / EXPORT / LIVE / SCRIPT_RUN) so gda-mcp / an agent can branch on a
    # command's channel without inferring it. The enum subclasses `str`, so the value
    # is the lowercase string, never the Python enum repr. `script_run` is the fourth
    # value (ADR-0031).
    entries = _manifest()["commands"]
    assert entries
    for entry in entries:
        assert entry["kind"] in {"headless", "export", "live", "script_run"}, entry[
            "name"
        ]


def test_entry_kind_matches_the_commands_own_schema_kind():
    # Each entry's `kind` is the same single source of truth the command emits
    # under its own `--schema` (ADR-0004 / ADR-0012): one descriptor field, not a
    # parallel projection — so the aggregate and per-command forms must agree.
    for entry in _manifest()["commands"]:
        result = CliRunner().invoke(app, [*entry["name"].split(" "), "--schema"])
        assert result.exit_code == 0, result.stdout
        own = json.loads(result.stdout)
        assert entry["kind"] == own["kind"], entry["name"]


def test_all_execution_kinds_appear_in_the_aggregate():
    # The surface spans all four channels: the default HEADLESS commands, the one
    # EXPORT command (`export run`), the LIVE commands (`game tree`), and the one
    # SCRIPT_RUN command (`script run`, the user-script passthrough, ADR-0031).
    by_name = {entry["name"]: entry for entry in _manifest()["commands"]}
    assert by_name["scene get"]["kind"] == "headless"
    assert by_name["export run"]["kind"] == "export"
    assert by_name["game tree"]["kind"] == "live"
    assert by_name["script run"]["kind"] == "script_run"
    # All four kinds are represented in the aggregate as a whole.
    kinds = {entry["kind"] for entry in by_name.values()}
    assert {"headless", "export", "live", "script_run"} <= kinds


def test_entry_constraints_match_the_commands_own_schema_constraints():
    # issue #233: each entry's `constraints` is the same single source of truth
    # the command emits under its own `--schema` — one predicate, not a parallel
    # projection — so the aggregate and per-command forms must agree exactly,
    # including the null case.
    for entry in _manifest()["commands"]:
        result = CliRunner().invoke(app, [*entry["name"].split(" "), "--schema"])
        assert result.exit_code == 0, result.stdout
        own = json.loads(result.stdout)
        assert entry["constraints"] == own["constraints"], entry["name"]


def test_live_stack_entries_carry_constraints_and_others_are_null():
    # The live-stack set carries structured `constraints`; everything else is
    # null (#233). `game tree` (LIVE) and `daemon start` launch the engine → the
    # 4.6 floor; `daemon stop`/`status` are UDS-only → null version; `scene get`
    # and `export run` have no live-stack dependence → null entirely.
    by_name = {entry["name"]: entry for entry in _manifest()["commands"]}

    full = {"platforms": ["linux", "macos"], "min_godot_version": "4.6"}
    version_null = {"platforms": ["linux", "macos"], "min_godot_version": None}
    assert by_name["game tree"]["constraints"] == full
    assert by_name["daemon start"]["constraints"] == full
    assert by_name["daemon stop"]["constraints"] == version_null
    assert by_name["daemon status"]["constraints"] == version_null
    assert by_name["scene get"]["constraints"] is None
    assert by_name["export run"]["constraints"] is None


def test_live_command_descriptions_do_not_restate_the_structured_constraint():
    # issue #233 / PR #245 review: the live-stack precondition is the structured
    # `constraints` field's job — the single source. The help/manifest description
    # prose must NOT independently restate the platform set or the Godot floor, or
    # it becomes the very drift source #233 set out to remove (a LIVE command's
    # prose once said "macOS/Linux only" yet omitted the 4.6 floor its structured
    # field carried). Guard a representative slice of the live-stack surface: the
    # constraint is discoverable structurally, never duplicated in prose.
    by_name = {entry["name"]: entry for entry in _manifest()["commands"]}
    for name in ("game tree", "perf monitors", "daemon start", "daemon stop"):
        description = by_name[name]["description"]
        assert "macOS" not in description, (name, description)
        assert "Linux" not in description, (name, description)
        assert "4.6" not in description, (name, description)
        # …yet the precondition is still discoverable, structurally.
        assert by_name[name]["constraints"] is not None, name


def test_schema_command_is_itself_self_describing():
    # The meta command is under the same ADR-0004 gate as every other command:
    # `gda schema --schema` emits its own {input, output, error} contract, with
    # `output` the manifest's own model schema.
    from gda.commands.meta import SchemaAllParams
    from gda.models import GdaErrorEnvelope, SurfaceManifest

    result = CliRunner().invoke(app, ["schema", "--schema"])

    assert result.exit_code == 0, result.stdout
    doc = json.loads(result.stdout)
    assert doc["input"] == SchemaAllParams.model_json_schema()
    assert doc["output"] == SurfaceManifest.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()


def test_self_described_manifest_guarantees_a_constrained_entry_kind():
    # issue #230 / PR #232 review: the aggregate entry's `kind` must be a HARD
    # part of the self-described surface schema, not optional — a consumer
    # validating `gda schema --schema`'s manifest schema can rely on every
    # dispatchable entry carrying an execution-kind from a fixed set. Assert it
    # against the actual `gda schema --schema` self-description, not just the model.
    result = CliRunner().invoke(app, ["schema", "--schema"])
    assert result.exit_code == 0, result.stdout
    manifest_schema = json.loads(result.stdout)["output"]

    entry = manifest_schema["$defs"]["CommandManifestEntry"]
    # Required, not nullable/defaulted.
    assert "kind" in entry["required"], entry["required"]
    # Constrained to the execution-kind enum (via a $ref to ExecutionKind).
    assert entry["properties"]["kind"] == {"$ref": "#/$defs/ExecutionKind"}
    assert manifest_schema["$defs"]["ExecutionKind"]["enum"] == [
        "headless",
        "export",
        "live",
        "script_run",
    ]


def test_self_described_manifest_describes_the_nullable_constraints_field():
    # issue #233: the aggregate entry's `constraints` is a HARD part of the
    # self-described surface schema — the KEY is required (every dispatchable
    # entry carries it) while the VALUE is nullable (a $ref to LiveStackConstraints
    # or null for non-live-stack commands). Assert against the actual `gda schema
    # --schema` self-description, not just the model, so a consumer validating the
    # manifest schema can rely on the field's type/shape.
    result = CliRunner().invoke(app, ["schema", "--schema"])
    assert result.exit_code == 0, result.stdout
    manifest_schema = json.loads(result.stdout)["output"]

    entry = manifest_schema["$defs"]["CommandManifestEntry"]
    # The key is required, not optional/defaulted.
    assert "constraints" in entry["required"], entry["required"]
    # The value is nullable: a $ref to LiveStackConstraints OR null.
    assert entry["properties"]["constraints"] == {
        "anyOf": [
            {"$ref": "#/$defs/LiveStackConstraints"},
            {"type": "null"},
        ]
    }
    # The referenced model carries the two facets, with min_godot_version itself
    # nullable (the daemon stop/status case).
    lsc = manifest_schema["$defs"]["LiveStackConstraints"]
    assert "platforms" in lsc["required"]
    # Both facets are required KEYS (the emitted object always carries them);
    # min_godot_version's VALUE is nullable for the daemon stop/status case
    # (issue #233, PR #245 review — key always present, value nullable).
    assert "min_godot_version" in lsc["required"]
    assert lsc["properties"]["min_godot_version"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]


def test_real_out_of_process_cli_manifest_covers_the_live_command_tree():
    # The real out-of-process `gda` CLI (invoked as `python -m gda`) — not the
    # in-process CliRunner — emits the manifest and covers the whole live command
    # tree (issue #192). Under `uv run` (how CI runs the fast suite) `sys.executable`
    # is the project venv, so `-m gda` runs the current checkout's gda.
    proc = subprocess.run([*GDA_CMD, "schema"], capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr
    names = {entry["name"] for entry in json.loads(proc.stdout)["commands"]}
    assert names == _live_dispatchable_command_names()
    assert {"info", "scene create"} <= names
    # The non-dispatchable `schema` meta command is excluded (Plan A).
    assert "schema" not in names
