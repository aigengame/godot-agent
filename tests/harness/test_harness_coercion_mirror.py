"""Drift checks for headless/live duplicated policy: property writes, and the reply writer.

``operations.gd`` (the headless op dispatcher, run via ``godot --headless
--script <abs-fs-path>``) and ``gda_harness.gd`` (the live res:// autoload) need
the SAME property-introspection / value-coercion helpers so ``game set`` coerces
exactly as headless ``node set`` does. No single ``preload()`` reaches both
runtime contexts and ``install.py`` copies one file, so the block is DUPLICATED
verbatim rather than extracted into a shared module (keystone decision, #220).

These tests are the drift guard: they extract duplicated shared helpers from both
files and assert they are byte-identical (modulo leading tabs, which differ only
if a copy is re-indented). Modeled on the registry drift checks in
``tests/cli/test_error_registry.py``. An edit to one copy that is not mirrored in the
other fails here.
"""

import re
from pathlib import Path

from tests.support import gd_function, payload_source

ROOT = Path(__file__).resolve().parents[2]
GDA_HARNESS_GD = ROOT / "src" / "gda" / "harness" / "gda_harness.gd"

# The mirrored block is in the entry until the shared value module exists
# (ADR-0043 §7); the name below then changes to that module.
MIRRORED_PAYLOAD_FILE = "operations.gd"

# The block both files delimit with these matching marker comments.
BLOCK = re.compile(
    r"^# --- BEGIN shared coercion .*?$\n(?P<body>.*?)^# --- END shared coercion ---$",
    re.MULTILINE | re.DOTALL,
)
CONTROL_POSITION_POLICY_HELPERS = (
    "_is_control_position_write",
    "_has_container_parent",
    "_control_layout_inputs",
    "_control_position_unavailable_message",
)


def _payload_text() -> str:
    return payload_source(MIRRORED_PAYLOAD_FILE)


def _harness_text() -> str:
    return GDA_HARNESS_GD.read_text(encoding="utf-8")


def _shared_block(text: str, label: str) -> str:
    """The marker-delimited shared block, with each line's leading tabs stripped.

    Leading tabs are normalized so an accidental re-indent of one copy is not
    flagged as content drift — only the helper LOGIC must match.
    """
    matches = BLOCK.findall(text)
    assert len(matches) == 1, (
        f"expected exactly one shared-coercion block in {label}, found {len(matches)}"
    )
    body = matches[0]
    return "\n".join(line.lstrip("\t") for line in body.splitlines())


def _top_level_function(text: str, name: str) -> str:
    return "\n".join(line.lstrip("\t") for line in gd_function(text, name))


def _control_position_policy(text: str) -> str:
    return "\n\n".join(
        _top_level_function(text, name) for name in CONTROL_POSITION_POLICY_HELPERS
    )


def test_shared_coercion_block_is_byte_identical_across_the_two_gd_files():
    operations_block = _shared_block(_payload_text(), MIRRORED_PAYLOAD_FILE)
    harness_block = _shared_block(_harness_text(), GDA_HARNESS_GD.name)

    assert operations_block, "the operations.gd shared block must be non-empty"
    assert operations_block == harness_block


def test_control_position_policy_is_byte_identical_across_the_two_gd_files():
    operations_policy = _control_position_policy(_payload_text())
    harness_policy = _control_position_policy(_harness_text())

    assert operations_policy, "the operations.gd Control-position policy must exist"
    assert operations_policy == harness_policy


def test_the_reply_json_writer_is_byte_identical_across_the_two_gd_files():
    """One writer choice, two payloads (#752 for the harness, #771 for the ops).

    Each file frames its reply with Godot's FULL-PRECISION JSON writer, and that
    one argument is the whole difference between reporting the float the project
    holds and reporting a rounded — or, below ~1e-32.6, zeroed — approximation of
    it. The copies are separate for the same reason the coercion block is, so an
    edit to one that is not mirrored has a caller-visible cost: the same value
    read back differently depending on the channel.
    """
    operations_writer = _top_level_function(_payload_text(), "_json")
    harness_writer = _top_level_function(_harness_text(), "_json")

    assert 'JSON.stringify(value, "", true, true)' in operations_writer
    assert operations_writer == harness_writer
