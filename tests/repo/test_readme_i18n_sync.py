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

import re
import unicodedata
from pathlib import Path

from scripts.update_readme_i18n import _normalized_hash

ROOT = Path(__file__).resolve().parents[2]
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
    return _normalized_hash(README)


def _recorded_hash(text: str) -> str | None:
    # `.match` anchors at the start of the file: the marker must be the *leading*
    # content, not buried somewhere in the body.
    match = MARKER_RE.match(text)
    return match.group(1) if match else None


def test_marker_is_the_leading_line():
    misplaced = sorted(
        lang
        for lang, path in TRANSLATIONS.items()
        if path.exists() and not MARKER_RE.match(path.read_text(encoding="utf-8"))
    )

    assert not misplaced, (
        f"the gda-readme-i18n marker must be the leading content in: {misplaced}. "
        "Run `uv run python scripts/update_readme_i18n.py` to normalize it to the top."
    )


def test_all_translations_present():
    missing = sorted(lang for lang, path in TRANSLATIONS.items() if not path.exists())

    assert not missing, (
        f"missing translated READMEs for: {missing}. "
        "Create docs/README.<lang>.md for each, then run "
        "`uv run python scripts/update_readme_i18n.py`."
    )


def test_readme_hash_is_independent_of_platform_line_endings(tmp_path: Path):
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    lf.write_bytes(b"first\nsecond\n")
    crlf.write_bytes(b"first\r\nsecond\r\n")

    assert _normalized_hash(lf) == _normalized_hash(crlf)


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


# --- In-page anchor integrity (Table of Contents and other "](#...)" links) ---

_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
_ANCHOR_ID_RE = re.compile(r'<a id="([^"]+)">')
_INPAGE_LINK_RE = re.compile(r"\]\(#([^)]+)\)")


def _outside_code_fences(text: str) -> str:
    """Drop fenced code blocks so their `# comment` lines aren't read as headings."""
    lines, in_fence = [], False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def _github_heading_slug(heading: str) -> str:
    """Approximate GitHub's heading-anchor slug (exact for ASCII headings).

    Lowercase, drop everything that is not a letter/number/mark/space/hyphen
    (so backticks, `?`, `¿`, … go), then spaces -> hyphens. Translated headings
    rely on explicit <a id> anchors instead, so CJK edge cases don't gate links.
    """
    kept = [
        ch
        for ch in heading.strip().lower()
        if ch in " -" or unicodedata.category(ch)[0] in ("L", "N", "M")
    ]
    return "".join(kept).replace(" ", "-")


def _anchor_targets(text: str) -> set[str]:
    body = _outside_code_fences(text)
    targets = set(_ANCHOR_ID_RE.findall(body))
    targets.update(_github_heading_slug(h) for h in _HEADING_RE.findall(body))
    return targets


def test_in_page_anchor_links_resolve():
    files = {"README.md": README} | {
        f"docs/README.{lang}.md": path for lang, path in TRANSLATIONS.items()
    }
    broken = {}
    for name, path in files.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        body = _outside_code_fences(text)
        targets = _anchor_targets(text)
        unresolved = sorted(
            {slug for slug in _INPAGE_LINK_RE.findall(body) if slug not in targets}
        )
        if unresolved:
            broken[name] = unresolved

    assert not broken, (
        "In-page anchor links with no matching heading slug or <a id> anchor:\n"
        + "\n".join(f"  {name}: {slugs}" for name, slugs in sorted(broken.items()))
        + "\nFix the link, the heading, or add an <a id> anchor (translated "
        "headings link to stable English ids via explicit anchors)."
    )
