"""Drift check: the shared coercion block is byte-identical in both .gd files.

``operations.gd`` (the headless op dispatcher, run via ``godot --headless
--script <abs-fs-path>``) and ``gda_harness.gd`` (the live res:// autoload) need
the SAME property-introspection / value-coercion helpers so ``game set`` coerces
exactly as headless ``node set`` does. No single ``preload()`` reaches both
runtime contexts and ``install.py`` copies one file, so the block is DUPLICATED
verbatim rather than extracted into a shared module (keystone decision, #220).

This test is the drift guard: it extracts the marker-delimited block from both
files and asserts they are byte-identical (modulo leading tabs, which differ only
if a copy is re-indented). Modeled on the registry drift checks in
``tests/test_error_registry.py``. An edit to one block that is not mirrored in
the other fails here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"
GDA_HARNESS_GD = ROOT / "src" / "gda" / "harness" / "gda_harness.gd"

# The block both files delimit with these matching marker comments.
BLOCK = re.compile(
    r"^# --- BEGIN shared coercion .*?$\n(?P<body>.*?)^# --- END shared coercion ---$",
    re.MULTILINE | re.DOTALL,
)


def _shared_block(path: Path) -> str:
    """The marker-delimited shared block, with each line's leading tabs stripped.

    Leading tabs are normalized so an accidental re-indent of one copy is not
    flagged as content drift — only the helper LOGIC must match.
    """
    text = path.read_text(encoding="utf-8")
    matches = BLOCK.findall(text)
    assert len(matches) == 1, (
        f"expected exactly one shared-coercion block in {path.name}, found {len(matches)}"
    )
    body = matches[0]
    return "\n".join(line.lstrip("\t") for line in body.splitlines())


def test_shared_coercion_block_is_byte_identical_across_the_two_gd_files():
    operations_block = _shared_block(OPERATIONS_GD)
    harness_block = _shared_block(GDA_HARNESS_GD)

    assert operations_block, "the operations.gd shared block must be non-empty"
    assert operations_block == harness_block
