#!/usr/bin/env python3
"""Re-stamp the README translation sync markers with the current English hash.

The English ``README.md`` is the authoritative source; each translated README
under ``docs/README.<lang>.md`` carries a leading marker recording the sha256 of
the English README it was translated from (see ``tests/test_readme_i18n_sync.py``):

    <!-- gda-readme-i18n: source=README.md sha256=<64-hex> -->

Run this after re-translating the affected files to "re-bless" them:

    uv run python scripts/update_readme_i18n.py

The marker format is mirrored in ``tests/test_readme_i18n_sync.py``; keep them in
sync if it ever changes.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
TRANSLATIONS = [ROOT / "docs" / f"README.{lang}.md" for lang in ("zh-CN", "es", "ja")]

MARKER_RE = re.compile(r"<!--\s*gda-readme-i18n:.*?-->", re.DOTALL)


def main() -> None:
    digest = hashlib.sha256(README.read_bytes()).hexdigest()
    marker = f"<!-- gda-readme-i18n: source=README.md sha256={digest} -->"

    for path in TRANSLATIONS:
        if not path.exists():
            print(f"skipped (missing): {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        if MARKER_RE.search(text):
            text = MARKER_RE.sub(marker, text, count=1)
        else:
            text = f"{marker}\n\n{text}"
        path.write_text(text, encoding="utf-8")
        print(f"stamped {path.relative_to(ROOT)} -> {digest[:12]}…")


if __name__ == "__main__":
    main()
