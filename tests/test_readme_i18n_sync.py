"""README translation freshness gate.

The English ``README.md`` is the single authoritative source; the translated
READMEs under ``docs/README.<lang>.md`` must be re-translated whenever it changes.
Each translation records, in a leading HTML-comment marker, the sha256 of the
English ``README.md`` it was translated from:

    <!-- gda-readme-i18n: source=README.md sha256=<64-hex> -->

This test recomputes that hash and asserts every translation's recorded hash
matches, so a stale translation fails CI. After updating a translation, re-stamp
the markers with ``uv run python scripts/update_readme_i18n.py``.

Note: this gate guarantees a translation was *reviewed against the current
English*, not that the translation is *accurate* — natural-language correctness
cannot be machine-verified.

The marker format is mirrored in ``scripts/update_readme_i18n.py``; keep them in
sync if it ever changes.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

# Language code -> translated README path. The codes double as the switcher link
# targets asserted by test_english_readme_links_to_all_translations.
TRANSLATIONS = {
    lang: ROOT / "docs" / f"README.{lang}.md" for lang in ("zh-CN", "es", "ja")
}

MARKER_RE = re.compile(
    r"<!--\s*gda-readme-i18n:\s*source=README\.md\s+sha256=([0-9a-f]{64})\s*-->"
)


def _english_hash() -> str:
    return hashlib.sha256(README.read_bytes()).hexdigest()


def _recorded_hash(text: str) -> str | None:
    match = MARKER_RE.search(text)
    return match.group(1) if match else None


def test_all_translations_present():
    missing = sorted(lang for lang, path in TRANSLATIONS.items() if not path.exists())

    assert not missing, (
        f"missing translated READMEs for: {missing}. "
        "Create docs/README.<lang>.md for each, then run "
        "`uv run python scripts/update_readme_i18n.py`."
    )


def test_translations_are_in_sync_with_english_readme():
    expected = _english_hash()
    stale = {
        lang: _recorded_hash(path.read_text(encoding="utf-8"))
        for lang, path in TRANSLATIONS.items()
        if path.exists()
        and _recorded_hash(path.read_text(encoding="utf-8")) != expected
    }

    assert not stale, (
        "Translated READMEs are out of sync with README.md.\n"
        f"  expected sha256={expected}\n"
        + "\n".join(
            f"  {lang}: recorded={recorded}" for lang, recorded in sorted(stale.items())
        )
        + "\nRe-translate each stale file, then run "
        "`uv run python scripts/update_readme_i18n.py` to re-stamp the markers."
    )


def test_english_readme_links_to_all_translations():
    text = README.read_text(encoding="utf-8")
    missing = sorted(
        f"docs/README.{lang}.md"
        for lang in TRANSLATIONS
        if f"docs/README.{lang}.md" not in text
    )

    assert not missing, (
        f"README.md is missing language-switcher links to: {missing}. "
        "Keep the switcher complete so every translation is discoverable."
    )
