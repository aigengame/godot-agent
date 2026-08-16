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

import pytest

from gda.cli import app
from gda.commands.meta import read_skill_text
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
    assert not diffs, (
        "SKILL.md command tables have drifted from the surface:\n" + "\n".join(diffs)
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


# The Scene-authoring paragraph documenting the Control-root zero-size pitfall
# (GDA-DF-006, #672), anchored on its stable opening line.
_SCENE_CREATE_ROOT_NOTE_ANCHOR = "`scene create` with a `Control-derived`"


def _extract_scene_create_root_note(text: str) -> str:
    """Extract just the Control-root zero-size paragraph from the bundled skill.

    Scoped to this one paragraph, not a search across the whole file: SKILL.md
    mentions `game rect` and `node set` elsewhere for unrelated reasons, so an
    unscoped token search can stay green even if THIS paragraph's semantic
    content regresses (PR #676 review round 2 recheck). If the anchor line is
    ever reworded away, this fails loudly with a clear message rather than
    silently matching an empty or wrong span.
    """
    start = text.find(_SCENE_CREATE_ROOT_NOTE_ANCHOR)
    assert start != -1, (
        "SKILL.md's Control-root zero-size paragraph anchor "
        f"{_SCENE_CREATE_ROOT_NOTE_ANCHOR!r} was not found in the bundled skill — "
        "the paragraph was reworded or removed; update this anchor to match."
    )
    end = text.find("\n\n", start)
    assert end != -1, (
        "the Control-root paragraph starting at the anchor never reaches a "
        "blank-line paragraph break"
    )
    return text[start:end]


def _normalize_prose(text: str) -> str:
    # Both surfaces hand-wrap their prose at ~88 columns, so a load-bearing phrase
    # can straddle a line break (e.g. "...no intrinsic\nminimum size..."). Collapsing
    # whitespace runs to a single space keeps matching robust to rewrapping; stripping
    # backticks lets one clause pattern cover both voices (SKILL.md backticks class
    # names and commands, the help text does not).
    return re.sub(r"\s+", " ", text.replace("`", ""))


# The conditional this guard exists for, as ORDERED clauses rather than vocabulary:
# review round 2's recheck showed a one-word mutation ("no intrinsic minimum" ->
# "an intrinsic minimum") reverses the meaning while keeping every token present.
# `[^;]*` confines each pattern to one semicolon-delimited clause, so pairing the
# wrong condition with the wrong consequence cannot match across the clause break.
_SEMANTIC_CLAUSES = [
    (
        "a root with NO intrinsic minimum renders zero-size",
        r"no intrinsic minimum[^;]*zero-size rect",
    ),
    (
        "a root WITH an intrinsic minimum renders at that minimum",
        r"an intrinsic minimum[^;]*renders at that minimum instead",
    ),
]


def _assert_control_root_semantics(normalized: str, surface: str) -> None:
    """Assert one surface carries the Control-root facts, conditional included."""
    for label, pattern in _SEMANTIC_CLAUSES:
        assert re.search(pattern, normalized), (
            f"{surface} lost the clause [{label}] (pattern {pattern!r}): {normalized!r}"
        )
    for token in [
        "zero anchors",
        "zero offsets",
        "anchor_right",
        "anchor_bottom",
        "node set",
        "game rect",
        "Control-derived",
    ]:
        assert token in normalized, f"{surface} missing {token!r}: {normalized!r}"


def test_scene_create_control_root_note_agrees_with_skill():
    # `gda scene create --help` (the command docstring, projected verbatim into
    # `gda schema`'s "scene create" description) and the SKILL.md Scene-authoring
    # paragraph independently document the same Control-derived zero-size root
    # pitfall (GDA-DF-006, #672) in two hand-maintained prose surfaces. They have
    # already diverged twice: a scope fix (Control -> Control-derived) landed in
    # SKILL.md without the matching help-text edit (PR #676 review round 1); and an
    # earlier version of this test searched tokens across the whole bundled skill,
    # so it could stay green even if the zero-size-is-conditional fact regressed,
    # since `game rect` / `node set` also occur elsewhere in SKILL.md for unrelated
    # reasons (PR #676 review round 2 recheck). This guards the SPECIFIC paragraph
    # for the SPECIFIC semantic facts the round corrected — the zero anchors/offsets
    # behavior, the intrinsic-minimum-size conditional AS A RELATIONSHIP (ordered
    # clause patterns, not vocabulary: the second recheck showed a one-word mutation
    # keeps every token while reversing the conditional), the fix properties, and
    # the check command — never full prose equality (the two surfaces deliberately
    # differ in voice).
    by_name = {
        c["name"]: c["description"]
        for c in build_surface_manifest(app).model_dump()["commands"]
    }
    _assert_control_root_semantics(
        _normalize_prose(by_name["scene create"]), "'scene create' help text"
    )
    _assert_control_root_semantics(
        _normalize_prose(_extract_scene_create_root_note(BUNDLED)),
        "SKILL.md's Control-root paragraph",
    )


def test_control_root_guard_catches_a_reversed_conditional():
    # The negative sentinel from PR #676's second recheck: flipping "no intrinsic
    # minimum" to "an intrinsic minimum" preserves every vocabulary token while
    # claiming a root WITH a minimum renders zero-size. The clause guard must go
    # red on exactly that mutation — vocabulary checks alone stayed green on it.
    paragraph = _extract_scene_create_root_note(BUNDLED)
    mutated = paragraph.replace(
        "no intrinsic minimum size", "an intrinsic minimum size"
    )
    assert mutated != paragraph, "mutation site missing — paragraph reworded?"
    with pytest.raises(AssertionError, match="NO intrinsic minimum"):
        _assert_control_root_semantics(
            _normalize_prose(mutated), "mutated SKILL.md paragraph"
        )
