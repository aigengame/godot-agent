"""Drift checks for headless/live duplicated property-write policy.

``operations.gd`` (the headless op dispatcher, run via ``godot --headless
--script <abs-fs-path>``) and ``gda_harness.gd`` (the live res:// autoload) need
the SAME property-introspection / value-coercion helpers so ``game set`` coerces
exactly as headless ``node set`` does. No single ``preload()`` reaches both
runtime contexts and ``install.py`` copies one file, so the block is DUPLICATED
verbatim rather than extracted into a shared module (keystone decision, #220).

These tests are the drift guard: they extract duplicated shared helpers from both
files and assert they are byte-identical (modulo leading tabs, which differ only
if a copy is re-indented). Modeled on the registry drift checks in
``tests/test_error_registry.py``. An edit to one copy that is not mirrored in the
other fails here.
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
CONTROL_POSITION_POLICY_HELPERS = (
    "_is_control_position_write",
    "_has_container_parent",
    "_control_position_unavailable_message",
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


def _top_level_function(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith(f"func {name}(")),
        None,
    )
    assert start is not None, f"expected function {name} in {path.name}"

    block: list[str] = []
    for index in range(start, len(lines)):
        line = lines[index]
        if index > start and line and not line.startswith("\t"):
            break
        block.append(line.lstrip("\t"))
    while block and block[-1] == "":
        block.pop()
    return "\n".join(block)


def _control_position_policy(path: Path) -> str:
    return "\n\n".join(
        _top_level_function(path, name) for name in CONTROL_POSITION_POLICY_HELPERS
    )


def test_shared_coercion_block_is_byte_identical_across_the_two_gd_files():
    operations_block = _shared_block(OPERATIONS_GD)
    harness_block = _shared_block(GDA_HARNESS_GD)

    assert operations_block, "the operations.gd shared block must be non-empty"
    assert operations_block == harness_block


def test_control_position_policy_is_byte_identical_across_the_two_gd_files():
    operations_policy = _control_position_policy(OPERATIONS_GD)
    harness_policy = _control_position_policy(GDA_HARNESS_GD)

    assert operations_policy, "the operations.gd Control-position policy must exist"
    assert operations_policy == harness_policy
