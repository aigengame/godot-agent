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

import functools
import json
import subprocess

import typer
from typer.testing import CliRunner

from gda.cli import app
from tests.support import GDA_CMD


@functools.cache
def _manifest_json() -> str:
    """The ``gda schema`` emission, produced ONCE per process (#815).

    The surface is immutable for the process lifetime — the product asserts as
    much for gda-mcp's cache hint — so every test reads the same emission
    instead of walking the whole command tree again. ``_manifest`` hands each
    caller its own parse, so no test can mutate what another reads.
    """
    result = CliRunner().invoke(app, ["schema"])
    assert result.exit_code == 0, result.stdout
    return result.stdout


def _manifest() -> dict:
    return json.loads(_manifest_json())


@functools.cache
def _own_schema_json(name: str) -> str:
    """A command's own ``--schema`` emission, produced ONCE per command (#815).

    The four aggregate-versus-own comparisons below read the same table rather
    than each re-dispatching every command.
    """
    result = CliRunner().invoke(app, [*name.split(" "), "--schema"])
    assert result.exit_code == 0, result.stdout
    return result.stdout


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
        own = json.loads(_own_schema_json(entry["name"]))
        assert entry["input"] == own["input"]
        assert entry["output"] == own["output"]
        assert entry["error"] == own["error"]


def test_schema_spawns_no_godot(monkeypatch):
    # Pure schema emission (ADR-0012), like per-command `--schema`: make both
    # binary resolution and the runner explode, then assert it still emits.
    def boom(*args, **kwargs):
        raise AssertionError("gda schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

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
    # value (ADR-0031); `import` the fifth (#668, the native --import pass).
    entries = _manifest()["commands"]
    assert entries
    for entry in entries:
        assert entry["kind"] in {
            "headless",
            "export",
            "live",
            "script_run",
            "import",
        }, entry["name"]


def test_entry_kind_matches_the_commands_own_schema_kind():
    # Each entry's `kind` is the same single source of truth the command emits
    # under its own `--schema` (ADR-0004 / ADR-0012): one descriptor field, not a
    # parallel projection — so the aggregate and per-command forms must agree.
    for entry in _manifest()["commands"]:
        own = json.loads(_own_schema_json(entry["name"]))
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
    assert by_name["resource import"]["kind"] == "import"
    # All five kinds are represented in the aggregate as a whole.
    kinds = {entry["kind"] for entry in by_name.values()}
    assert {"headless", "export", "live", "script_run", "import"} <= kinds


def test_entry_constraints_match_the_commands_own_schema_constraints():
    # issue #233: each entry's `constraints` is the same single source of truth
    # the command emits under its own `--schema` — one predicate, not a parallel
    # projection — so the aggregate and per-command forms must agree exactly,
    # including the null case.
    for entry in _manifest()["commands"]:
        own = json.loads(_own_schema_json(entry["name"]))
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
        "import",
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


# --- argv binding in the manifest (issue #669) --------------------------------


# A property the caller cannot supply directly says so in its own description:
# the CLI derives it from other flags and ignores anything passed in. That phrase
# is the mechanical exclusion below — no command names are matched.
_IGNORED_VALUE_MARKER = "a value passed in is ignored"

# …and the properties it excuses today. Pinned so the phrase cannot become a
# quiet escape hatch: a new computed property has to be acknowledged here.
_COMPUTED_PROPERTIES = {
    "script set: mode",
    "shader set: mode",
    # #840: the host data directory the export-templates check compares against.
    # gda resolves it from its own environment — the one thing a caller inside a
    # redirected run cannot know — so it is stamped model-side like the two modes.
    "export get: host_data_path",
}


def test_every_directly_supplyable_input_property_has_an_argv_binding():
    # issue #669: an agent reads `input`, then needs `argv` to write what it
    # found. Every property it can actually supply must therefore have a binding
    # — not just the required ones, since an optional property with no binding is
    # equally unreachable from the contract. The only exemption is a property the
    # CLI COMPUTES (`script set` / `shader set` derive `mode` from `--replace` /
    # `--search`), which its description already declares.
    unreachable: list[str] = []
    computed: set[str] = set()
    for entry in _manifest()["commands"]:
        linked = {b["input_property"] for b in entry["argv"] if b["input_property"]}
        for name, spec in entry["input"].get("properties", {}).items():
            if name in linked:
                continue
            where = f"{entry['name']}: {name}"
            if _IGNORED_VALUE_MARKER in str(spec.get("description", "")):
                computed.add(where)
                continue
            unreachable.append(where)

    assert not unreachable, (
        "input properties a caller can supply but cannot write on a command line:\n"
        + "\n".join(unreachable)
    )
    # The exemption stays the narrow, declared one it claims to be.
    assert computed == _COMPUTED_PROPERTIES, computed


def test_entry_argv_matches_the_commands_own_schema_argv():
    # Both schema sites derive the binding from the SAME live Click parameters
    # (ADR-0012's live-tree walk, ADR-0023 §2's "projections, not parallel
    # registries"), so the aggregate and per-command forms cannot drift.
    for entry in _manifest()["commands"]:
        own = json.loads(_own_schema_json(entry["name"]))
        assert entry["argv"] == own["argv"], entry["name"]


def test_every_argv_binding_is_constructible_into_a_command_line():
    # The acceptance property: for EVERY command, each binding says either where
    # the value goes positionally or exactly how to spell its option — never
    # neither, never both — and the positions are a contiguous 0..n-1 run.
    for entry in _manifest()["commands"]:
        positions = []
        for binding in entry["argv"]:
            where = f"{entry['name']}: {binding['name']}"
            if binding["kind"] == "argument":
                assert binding["option"] is None, where
                assert isinstance(binding["position"], int), where
                positions.append(binding["position"])
            else:
                assert binding["kind"] == "option", where
                assert binding["position"] is None, where
                assert str(binding["option"]).startswith("-"), where
        assert positions == list(range(len(positions))), entry["name"]


def test_argv_metadata_cannot_reach_the_two_schema_halves_gda_mcp_maps():
    # The gda-mcp wire-schema answer (#669): gda-mcp maps `input` →
    # `input_schema` and `output` → `output_schema` and ignores every other entry
    # key (ADR-0012). Asserting `argv` is absent from the halves would be
    # tautological — it is not a JSON Schema keyword — so assert the property that
    # actually matters: emitting a schema WITH bindings leaves both halves
    # byte-identical to emitting it WITHOUT them. That is what keeps every
    # registered tool's wire schema unchanged by this addition.
    from gda.headless import command_argv_bindings
    from gda.models import CommandSchema

    root = typer.main.get_command(app)
    checked = 0
    with_bindings = 0

    def walk(command, path):
        nonlocal checked, with_bindings
        subcommands = getattr(command, "commands", None)
        if subcommands is not None:
            for name, subcommand in subcommands.items():
                walk(subcommand, [*path, name])
            return
        input_model = getattr(command, "gda_input_model", None)
        output_model = getattr(command, "gda_output_model", None)
        if input_model is None or output_model is None:
            return
        bare = CommandSchema.of(input_model, output_model)
        bound = CommandSchema.of(
            input_model,
            output_model,
            argv=command_argv_bindings(command, input_model),
        )
        assert bound.input == bare.input, path
        assert bound.output == bare.output, path
        assert bound.error == bare.error, path
        checked += 1
        with_bindings += 1 if bound.argv else 0

    walk(root, [])
    assert checked > 60, checked
    # …and the comparison is not vacuous: most of those commands really do carry
    # bindings, so the halves matched DESPITE the bindings being emitted, not
    # because there were none to leak.
    assert with_bindings > 40, with_bindings


def test_self_described_manifest_describes_the_argv_binding_list():
    # issue #669: the aggregate entry's `argv` is a HARD part of the
    # self-described surface schema — the key is required (every entry is a real
    # command whose signature can be walked) and its items are the named
    # ArgvBinding shape, so a consumer validating `gda schema --schema`'s manifest
    # schema can rely on the binding's fields rather than discovering them.
    result = CliRunner().invoke(app, ["schema", "--schema"])
    assert result.exit_code == 0, result.stdout
    manifest_schema = json.loads(result.stdout)["output"]

    entry = manifest_schema["$defs"]["CommandManifestEntry"]
    assert "argv" in entry["required"], entry["required"]
    assert entry["properties"]["argv"]["items"] == {"$ref": "#/$defs/ArgvBinding"}

    binding = manifest_schema["$defs"]["ArgvBinding"]
    # Every field is a required KEY, so a consumer reads them unconditionally;
    # the optional ones are nullable VALUES (`option` on a positional, `position`
    # on an option, `input_property` where there is no 1:1 property).
    assert set(binding["required"]) == {
        "name",
        "input_property",
        "kind",
        "option",
        "position",
        "required",
        "flag",
        "multiple",
        "json_value",
    }
    assert binding["properties"]["kind"]["$ref"] == "#/$defs/ArgvKind"
    assert manifest_schema["$defs"]["ArgvKind"]["enum"] == ["argument", "option"]


# Every pairing of the two spelling keys against each `kind`, valid and not. The
# point is not any single verdict but that ONE corpus gets the SAME verdict from
# the published rule and from the model — the two engines disagree readily (a
# pydantic Rust validator versus Python `jsonschema`), so agreement has to be
# tested rather than assumed.
_SPELLING_CORPUS = [
    {"kind": "argument", "option": None, "position": 0, "flag": False},
    {"kind": "option", "option": "--out", "position": None, "flag": False},
    {"kind": "option", "option": "--all", "position": None, "flag": True},
    # …and the states no caller could write.
    {"kind": "argument", "option": "--out", "position": 0, "flag": False},
    {"kind": "argument", "option": None, "position": None, "flag": False},
    {"kind": "argument", "option": None, "position": 0, "flag": True},
    {"kind": "option", "option": None, "position": None, "flag": False},
    {"kind": "option", "option": "--out", "position": 1, "flag": False},
    {"kind": "option", "option": None, "position": 0, "flag": False},
]


def test_the_published_spelling_rule_matches_the_model():
    # #669 review: a binding that claims both a position and an option spelling —
    # or neither — is unwritable, and a consumer reading one cannot tell which key
    # to believe. The model rejects those states; this pins the PUBLISHED rule to
    # the model so a client checking the manifest schema reaches the same verdict.
    import jsonschema
    import pydantic

    from gda.models import ArgvBinding

    result = CliRunner().invoke(app, ["schema", "--schema"])
    assert result.exit_code == 0, result.stdout
    defs = json.loads(result.stdout)["output"]["$defs"]
    published = {"allOf": [{"$ref": "#/$defs/ArgvBinding"}], "$defs": defs}

    for spelling in _SPELLING_CORPUS:
        binding = {
            "name": "x",
            "input_property": "x",
            "required": False,
            "multiple": False,
            "json_value": False,
            **spelling,
        }
        try:
            jsonschema.validate(instance=binding, schema=published)
            by_schema = True
        except jsonschema.ValidationError:
            by_schema = False
        try:
            ArgvBinding.model_validate(binding)
            by_model = True
        except pydantic.ValidationError:
            by_model = False
        assert by_schema == by_model, (spelling, by_schema, by_model)

    # …and the corpus spans both verdicts, so agreement is not vacuous.
    verdicts = set()
    for spelling in _SPELLING_CORPUS:
        try:
            ArgvBinding.model_validate(
                {
                    "name": "x",
                    "input_property": "x",
                    "required": False,
                    "multiple": False,
                    "json_value": False,
                    **spelling,
                }
            )
            verdicts.add(True)
        except pydantic.ValidationError:
            verdicts.add(False)
    assert verdicts == {True, False}
