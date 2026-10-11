"""Guard decision-critical skill guidance against the installed CLI surface.

The skill points to `gda schema` for the full command inventory. It does not
maintain a second command table or error-code registry.
"""

import re

import pytest

from gda.cli import app
from gda.commands.meta import read_skill_text
from gda.surface.manifest import build_surface_manifest

BUNDLED = read_skill_text()

# The Control-root pitfall is decision-relevant even with command discovery.
_SCENE_CREATE_ROOT_NOTE_ANCHOR = "`scene create` uses a `Control-derived`"


def _extract_scene_create_root_note(text: str) -> str:
    """Extract just the Control-root zero-size paragraph from the bundled skill.

    A scoped check cannot pass on unrelated mentions of `game rect` or
    `node set` elsewhere in the skill.
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
        "--root-type",
    ]:
        assert token in normalized, f"{surface} missing {token!r}: {normalized!r}"


def test_scene_create_control_root_note_agrees_with_skill():
    # This pitfall appears in both command help and the skill. Check the
    # conditional, fix, and verification action in each without requiring
    # identical prose.
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
    # A reversed condition preserves the vocabulary but changes the advice.
    paragraph = _extract_scene_create_root_note(BUNDLED)
    mutated = paragraph.replace(
        "no intrinsic minimum size", "an intrinsic minimum size"
    )
    assert mutated != paragraph, "mutation site missing — paragraph reworded?"
    with pytest.raises(AssertionError, match="NO intrinsic minimum"):
        _assert_control_root_semantics(
            _normalize_prose(mutated), "mutated SKILL.md paragraph"
        )
