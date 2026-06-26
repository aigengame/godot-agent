"""S2 (fast): gda-mcp tool-registration coverage (issue #193, ADR-0012).

On startup gda-mcp introspects the aggregate schema dump and registers one MCP
tool per command — a *faithful mirror* of the installed gda. These tests drive
the real surface through a fake seam (no gda subprocess, no Godot) over an
in-memory MCP client, asserting full coverage, the ``<group>_<command>`` name
map, and that each tool's description / input / output come straight from the
dump.
"""

import json
import re

from gda.mcp.server import build_server, tool_name
from tests.mcp_support import (
    FakeGdaRunner,
    list_tools,
    real_manifest_json,
    schema_then,
)


# The fake seam never dispatches in these tests (registration only); a dispatch
# attempt is a loud failure so a stray call cannot pass silently.
def _no_dispatch(args, stdin):
    raise AssertionError(f"unexpected dispatch in a registration test: {args}")


def _server():
    return build_server(FakeGdaRunner(schema_then(_no_dispatch)))


def _manifest_entries():
    return json.loads(real_manifest_json())["commands"]


def test_registers_one_tool_per_command_full_coverage():
    # Faithful mirror (ADR-0012): the tool set is exactly the dump's commands,
    # one-to-one, nothing dropped/filtered/deduped.
    tools = list_tools(_server()).tools
    expected = {tool_name(e["name"]) for e in _manifest_entries()}
    got = {t.name for t in tools}
    assert got == expected
    assert len(tools) == len(_manifest_entries())  # no collisions collapsed a pair


def test_tool_names_are_group_command_with_separators_underscored():
    # ADR-0005 name map: `<group> <command>` → `<group>_<command>`, with both the
    # space and any in-command hyphen turned to `_`. Spot-check the tricky ones…
    names = {t.name for t in list_tools(_server()).tools}
    assert {"info", "scene_create", "scene_get_exports", "node_connect_signal"} <= names
    # …and the global invariant: no tool name carries a space or hyphen.
    assert all(re.fullmatch(r"[a-z0-9_]+", n) for n in names), names


def test_each_tool_mirrors_its_commands_description_and_schemas():
    # description ← command help; inputSchema ← input; outputSchema ← output —
    # passed through verbatim from the dump (ADR-0012's per-field fidelity).
    by_name = {tool_name(e["name"]): e for e in _manifest_entries()}
    for tool in list_tools(_server()).tools:
        entry = by_name[tool.name]
        assert tool.description == entry["description"]
        assert tool.inputSchema == entry["input"]
        assert tool.outputSchema == entry["output"]


def test_known_tool_has_a_nonempty_output_schema():
    # info's outputSchema is the EngineVersion contract — present so the SDK can
    # validate a successful call's structuredContent against it (Design dec. 5).
    info = next(t for t in list_tools(_server()).tools if t.name == "info")
    assert info.outputSchema and info.outputSchema.get("type") == "object"


def test_non_dispatchable_meta_commands_are_not_registered():
    # Plan A, proven at the MCP layer (PR #203 review): `gda schema` is
    # non-dispatchable (no --params-json), so gda-mcp must NOT advertise it as a
    # tool it cannot fulfil. The dump excludes it at the source, so it never
    # reaches registration — no per-command exclusion logic in gda-mcp.
    names = {t.name for t in list_tools(_server()).tools}
    assert "schema" not in names


def test_live_command_game_tree_appears_as_a_tool_mirroring_the_dump():
    # ADR-0011 verification (#227): a LIVE command reaches the tool surface with
    # NO per-phase code — it goes through the exact same generic schema→tool
    # transform as a headless command. `game tree` (the #7 tracer) must register
    # as the `game_tree` tool, and its description/input/output must mirror the
    # dump entry field-for-field, indistinguishably from any headless tool.
    by_name = {tool_name(e["name"]): e for e in _manifest_entries()}
    assert "game_tree" in by_name  # the aggregate dump (ADR-0012) carries the live cmd
    tools = {t.name: t for t in list_tools(_server()).tools}
    assert "game_tree" in tools, "the live `game tree` command was not registered"
    tool = tools["game_tree"]
    entry = by_name["game_tree"]
    assert tool.description == entry["description"]
    assert tool.inputSchema == entry["input"]
    assert tool.outputSchema == entry["output"]


def test_startup_introspects_the_dump_through_the_seam_once():
    # The surface comes from one `gda schema` run through the shared seam
    # (ADR-0012's single startup subprocess), not a per-command fan-out.
    runner = FakeGdaRunner(schema_then(_no_dispatch))
    build_server(runner)
    # The startup introspection call carries no project (the schema meta command
    # is projectless); per-tool dispatch is what injects the resolved project.
    assert runner.calls == [(["schema"], None, None)]
