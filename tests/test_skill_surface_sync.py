"""The bundled `SKILL.md` command tables must match the live command surface (issue #293).

`src/gda/skill/SKILL.md` lists `gda`'s command groups and their commands in two markdown
tables (headless + live). Those tables are **hand-maintained prose**, not a projection of
the command descriptors the way `--schema` / `gda schema` are (ADR-0023) — so they can drift
when a command is added, removed, or renamed and the doc is not updated. ADR-0024's
version-lock guarantees the file ships at the package version, but NOT that its prose matches
the surface. This gate closes that gap: it parses the SKILL.md tables and asserts they are
exactly the grouped command surface that `gda schema` projects from
(`build_surface_manifest`), so a future surface change without a SKILL.md edit fails CI.

Scope: the per-group command tables (where drift happened and where the risk is). Top-level
meta commands (`info` / `schema` / `skill`) live in prose, not the tables, and are out of scope.
"""

import re

from gda.cli import app
from gda.skill_ops import read_skill_text
from gda.surface import build_surface_manifest

BUNDLED = read_skill_text()

# A command-table row: a single backticked group token in the first cell, then a cell of
# backticked commands. `[a-z][a-z-]*` excludes the exit-code table (`0`, `127`, …) and the
# `| Group | Commands |` / `| ----- |` header/separator rows.
_GROUP_ROW = re.compile(r"^\|\s*`([a-z][a-z-]*)`\s*\|\s*(.*?)\s*\|\s*$")
_BACKTICKED = re.compile(r"`([^`]+)`")


def parse_skill_groups(text: str) -> dict[str, set[str]]:
    """Extract `group -> {commands}` from SKILL.md's command tables.

    Commands are the backticked tokens BEFORE the first parenthetical note in the commands
    cell; the note may carry backticked option flags (`--mode`, `--windowed`) or file
    extensions (`.tscn`) that are NOT commands, so they are excluded by splitting on `(`.
    """
    groups: dict[str, set[str]] = {}
    for line in text.splitlines():
        m = _GROUP_ROW.match(line)
        if not m:
            continue
        group, cell = m.group(1), m.group(2)
        prefix = cell.split("(", 1)[0]
        groups[group] = set(_BACKTICKED.findall(prefix))
    return groups


def surface_groups() -> dict[str, set[str]]:
    """The authoritative `group -> {commands}` from the live command surface.

    `build_surface_manifest(app)` is the same source `gda schema` emits (ADR-0012). A
    grouped command's name is `"<group> <command>"`; single-token names are top-level meta
    commands (`info` / `skill`), which the tables do not list, so they are skipped.
    """
    manifest = build_surface_manifest(app).model_dump()
    groups: dict[str, set[str]] = {}
    for cmd in manifest["commands"]:
        parts = cmd["name"].split()
        if len(parts) < 2:
            continue
        groups.setdefault(parts[0], set()).add(" ".join(parts[1:]))
    return groups


def test_skill_md_tables_match_the_command_surface():
    actual = parse_skill_groups(BUNDLED)
    expected = surface_groups()

    # A readable diff when they drift: per-group missing/extra commands, and whole groups
    # present in one but not the other.
    diffs = []
    for group in sorted(set(actual) | set(expected)):
        have, want = actual.get(group, set()), expected.get(group, set())
        if have != want:
            diffs.append(
                f"  [{group}] SKILL.md missing {sorted(want - have)} / "
                f"stale {sorted(have - want)}"
            )
    assert not diffs, "SKILL.md command tables have drifted from the surface:\n" + "\n".join(
        diffs
    )


def test_parser_reads_only_command_tokens_not_option_flags_or_extensions():
    # The parser must take commands from the cell prefix and ignore backticked option flags
    # and file extensions inside the parenthetical note — otherwise `--mode`/`.tscn` would
    # be miscounted as commands and the gate would compare garbage.
    sample = "\n".join(
        [
            "| Group | Commands |",
            "| ----- | -------- |",
            "| `scene` | `create`, `get`, `list` (`.tscn` files) |",
            "| `export` | `list`, `get`, `run` (a preset; `--mode` release/debug/pack) |",
            "| `input` | `key`, `action`, `sequence` |",
        ]
    )
    assert parse_skill_groups(sample) == {
        "scene": {"create", "get", "list"},
        "export": {"list", "get", "run"},
        "input": {"key", "action", "sequence"},
    }


def test_gate_catches_a_dropped_command():
    # Proof the gate detects real drift: drop one command from a stable table row and the
    # parsed surface no longer matches the live one. `scene delete` exists in every revision.
    assert "delete" in parse_skill_groups(BUNDLED).get("scene", set())
    doctored = BUNDLED.replace("`get-exports`, `delete`", "`get-exports`")
    assert parse_skill_groups(doctored).get("scene") != surface_groups().get("scene")
