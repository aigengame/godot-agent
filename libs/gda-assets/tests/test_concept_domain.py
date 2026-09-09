from dataclasses import replace

import pytest

from gda_assets.domain.concept import (
    ConceptBrief,
    SpriteSheetLayout,
    concept_prompt,
    validate_brief,
    validate_layout,
)


def test_brief_builds_one_deterministic_plain_prompt():
    brief = ConceptBrief(
        "model",
        "red fox courier",
        "ink wash",
        views=("front", "side"),
        poses=("standing",),
        instructions="Readable silhouette.",
    )
    assert concept_prompt(brief) == (
        "Intended use: model\n"
        "Subject: red fox courier\n"
        "Style: ink wash\n"
        "Requested views: front, side\n"
        "Requested poses: standing\n"
        "Project instructions: Readable silhouette."
    )


def test_brief_rejects_missing_direction_and_duplicate_views():
    brief = ConceptBrief("sprite", "fox", "pixels")
    with pytest.raises(ValueError, match="view or pose"):
        validate_brief(brief)
    with pytest.raises(ValueError, match="unique"):
        validate_brief(replace(brief, views=("front", "front")))


def test_sprite_layout_requires_a_bounded_complete_cell_grid():
    validate_layout(SpriteSheetLayout(64, 32, 16, 16, 8))
    with pytest.raises(ValueError, match="divide"):
        validate_layout(SpriteSheetLayout(65, 32, 16, 16, 8))
    with pytest.raises(ValueError, match="frame count"):
        validate_layout(SpriteSheetLayout(32, 32, 16, 16, 5))
