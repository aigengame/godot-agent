"""The joypad name tables of ``project add-input-action``, against the engine (#842).

``--joy-button`` and ``--joy-axis`` accept NAMES that mirror two engine enums,
``JoyButton`` and ``JoyAxis``. The engine has no name resolver for them (unlike
``OS.find_keycode_from_string`` for keys), so gda carries its own table — and a
hand-typed table is exactly the kind of mirror that rots silently when the engine
adds a button. **The engine is the oracle**, and the chain is pinned end to end
by the two tests here:

1. ``operations.gd`` maps each gda name to the engine's own global constant
   (``"DPadLeft": JOY_BUTTON_DPAD_LEFT``), so gda hand-types no enum VALUE: the
   GDScript compiler resolves it. What gda does own is the NAME and the
   normalization between the two spellings — and that is what the e2e test below
   diffs against the enum the engine itself enumerates, via
   ``godot --headless --dump-extension-api`` (the engine's own JSON dump of its
   API, ``global_enums``).
2. The Python tuples that build the ``--help`` / ``--schema`` prose are a second
   copy of the names, so a unit test pins them to the same GDScript table. That
   copy exists because the CLI must document the accepted set without reading
   GDScript at import time; it is a copy under a guard, not a second authority.

**Which tier runs what.** Only the enum COVERAGE diff (and the sentinel check it
rests on) needs a real engine, so only that is ``e2e``-marked. The fold identity
between a gda name and the engine constant it maps to reads both sides out of
gda's own sources, so it runs on the unit tier — on PR CI — where a mis-mapped
constant (``"DPadLeft": JOY_BUTTON_DPAD_RIGHT``) belongs, rather than waiting for
a nightly run.

The sentinels are excluded EXPLICITLY (asserted present, then dropped) rather
than filtered by a value bound: ``INVALID``/``SDL_MAX``/``MAX`` are enum
bookkeeping, not bindable buttons, and naming them here means a rename shows up
as a failure instead of silently widening the accepted set.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from gda.commands.project import JOY_AXIS_NAMES, JOY_BUTTON_NAMES

from tests.support import GODOT

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"

# The enum bookkeeping entries that are not bindable inputs. Excluded by NAME so
# the exclusion is visible and a rename fails loudly.
SENTINELS = ("INVALID", "SDL_MAX", "MAX")

_ENTRY = re.compile(r'^\t"([A-Za-z0-9]+)":\s*([A-Z0-9_]+),$', re.M)


def _gd_table(const_name: str) -> dict[str, str]:
    """Read one ``const <NAME> := { "Gda": ENGINE_CONST, ... }`` table from operations.gd."""
    source = OPERATIONS_GD.read_text(encoding="utf-8")
    block = re.search(
        r"^const " + const_name + r" := \{\n(.*?)^\}$", source, re.M | re.S
    )
    assert block is not None, f"{const_name} table not found in {OPERATIONS_GD}"
    entries = _ENTRY.findall(block.group(1))
    assert entries, f"{const_name} table is empty"
    return dict(entries)


def _fold(name: str) -> str:
    """The declared normalization: case- and separator-insensitive."""
    return name.replace("_", "").replace("-", "").replace(" ", "").upper()


@pytest.fixture(scope="module")
def engine_enums(tmp_path_factory) -> dict[str, dict[str, int]]:
    """``{enum: {CONSTANT: value}}`` as the ENGINE enumerates its own global enums.

    ``--dump-extension-api`` writes ``extension_api.json`` into the working
    directory — the engine's own machine-readable API description, which is where
    a global enum (not a class enum) is enumerable at all: ``@GlobalScope`` is not
    a ClassDB class, so ``ClassDB.class_get_enum_constants`` answers nothing for
    ``JoyButton`` (verified against 4.6.3).
    """
    work = tmp_path_factory.mktemp("extension-api")
    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--dump-extension-api",
            "--log-file",
            str(work / "godot.log"),
        ],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=180,
    )
    dump = work / "extension_api.json"
    assert dump.exists(), proc.stdout + proc.stderr
    api = json.loads(dump.read_text(encoding="utf-8"))
    return {
        enum["name"]: {value["name"]: value["value"] for value in enum["values"]}
        for enum in api["global_enums"]
    }


@pytest.mark.parametrize(
    ("const_name", "python_names", "enum_name", "prefix"),
    [
        ("JOY_BUTTON_BY_NAME", JOY_BUTTON_NAMES, "JoyButton", "JOY_BUTTON_"),
        ("JOY_AXIS_BY_NAME", JOY_AXIS_NAMES, "JoyAxis", "JOY_AXIS_"),
    ],
)
def test_joy_names_fold_to_their_engine_constants_and_match_the_help_tuples(
    const_name, python_names, enum_name, prefix
):
    # ENGINE-FREE, so it runs on PR CI rather than only in the nightly e2e tier:
    # both sides of every assertion here are read from gda's own sources. A
    # mis-mapped constant ("DPadLeft": JOY_BUTTON_DPAD_RIGHT) is a fold mismatch,
    # and catching that needs no engine — only the coverage diff below does.
    table = _gd_table(const_name)

    # The doc-facing tuple and the resolver's table are the same names, in the
    # same order: the help/schema prose cannot drift from what gda accepts.
    assert tuple(table) == tuple(python_names)

    # The normalization IS the thing under test: gda's CamelCase name and the
    # engine's SCREAMING_SNAKE key are the same token, case- and
    # separator-folded (DPadLeft <-> JOY_BUTTON_DPAD_LEFT, LeftX <-> LEFT_X).
    for gda_name, constant in table.items():
        assert _fold(gda_name) == _fold(constant.removeprefix(prefix)), (
            f"{gda_name} is not the folded form of {constant}"
        )

    # Folded names stay unique, so the case-insensitive resolver cannot be
    # ambiguous.
    assert len({_fold(name) for name in table}) == len(table)


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("const_name", "python_names", "enum_name", "prefix"),
    [
        ("JOY_BUTTON_BY_NAME", JOY_BUTTON_NAMES, "JoyButton", "JOY_BUTTON_"),
        ("JOY_AXIS_BY_NAME", JOY_AXIS_NAMES, "JoyAxis", "JOY_AXIS_"),
    ],
)
def test_joy_name_table_matches_the_engine_enum(
    engine_enums, const_name, python_names, enum_name, prefix
):
    engine = engine_enums[enum_name]
    for sentinel in SENTINELS:
        # Asserted present before it is dropped: a renamed sentinel must fail
        # here, not quietly become a bindable name.
        assert prefix + sentinel in engine, (
            f"{prefix}{sentinel} vanished from {enum_name}"
        )
    bindable = {
        constant
        for constant in engine
        if constant.removeprefix(prefix) not in SENTINELS
    }

    # Coverage both ways: every bindable engine constant has a gda name, and gda
    # names nothing the engine does not declare. This is the half that genuinely
    # needs the engine — the fold identity between a gda name and the constant it
    # maps to is checked engine-free, on the unit tier, above.
    assert set(_gd_table(const_name).values()) == bindable
