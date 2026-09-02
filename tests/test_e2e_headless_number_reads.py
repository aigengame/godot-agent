"""S1 (e2e): the HEADLESS read direction, measured on a real engine (#771).

The live counterpart is ``tests/test_e2e_live_number_transport.py``. This module
asks the same question of the other channel: does a headless reply report the
float the project holds, or a rounded — sometimes zeroed — approximation of it?

Both tiers read ONE table, ``tests/live_number_corpus.py``. That is not tidiness:
the writer under test here is the same engine function #752 measured, so a second
corpus would be a second opinion about one function. What differs is how the value
is PLACED: the live tier sends it over the wire, while a headless read must find it
already in the project. So the probe scene carries every corpus value as its
IEEE-754 BYTES and reconstructs it in ``_init`` — the only placement that is not
itself a decimal literal, which is exactly the lossy thing under test. Values such
as ``DBL_MIN`` and ``5e-324`` cannot be spelled at all for this engine's parser
(``gda.live_numbers``), so no literal-authored scene could hold them to be read.

What the write path does to a ``--value`` STRING is the other question, answered by
#772 and measured in ``tests/test_e2e_write_value_fidelity.py``; nothing here
claims anything about it.
"""

import json
import math
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from tests.live_number_corpus import (
    LIVE_NUMBER_CORPUS,
    PARTITIONS,
    Partition,
    tally_outcome,
    value_bits,
)
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# One exported float per corpus row plus the whole corpus as a packed array, so
# the scalar arm of the value projection and its element-wise arm are both read
# through the reply under test. `_init` assigns them: an @export's declared
# default would have to be a decimal literal.
_PROBE_BODY = """\
func _from_hex(h: String) -> float:
\tvar b := PackedByteArray()
\tb.resize(8)
\tfor i in range(8):
\t\tb[i] = ("0x" + h.substr(i * 2, 2)).hex_to_int()
\treturn b.decode_double(0)


func _init() -> void:
\tvar packed := PackedFloat64Array()
\tfor i in range(BITS.size()):
\t\tvar value := _from_hex(BITS[i])
\t\tset("v%d" % i, value)
\t\tpacked.append(value)
\tall_values = packed
"""


def _probe_source() -> str:
    """The probe script: the corpus as bit patterns, restored into real exports."""
    bits = ",\n".join(f'\t"{value_bits(case.value)}"' for case in LIVE_NUMBER_CORPUS)
    exports = "\n".join(
        f"@export var v{index}: float = 0.0" for index in range(len(LIVE_NUMBER_CORPUS))
    )
    return (
        "extends Node2D\n\n"
        f"const BITS := [\n{bits},\n]\n\n"
        f"{exports}\n"
        "@export var all_values: PackedFloat64Array = PackedFloat64Array()\n\n\n"
        f"{_PROBE_BODY}"
    )


PROBE_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://numbers.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)


def _gda(project):
    """A bound ``gda <args> --project <p> --godot <g> --json`` runner."""

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

    return run


def _probe_project(project):
    """Write the probe scene into ``project`` and return its bound runner."""
    (project / "numbers.gd").write_text(_probe_source(), encoding="utf-8")
    (project / "numbers.tscn").write_text(PROBE_TSCN, encoding="utf-8")
    return _gda(project)


def _exports_by_name(run) -> dict:
    """`scene get-exports` on the probe scene, indexed by export name."""
    read = run("scene", "get-exports", "numbers.tscn")
    assert read.returncode == 0, read.stdout + read.stderr
    nodes = json.loads(read.stdout)["nodes"]
    assert len(nodes) == 1, nodes
    return {export["name"]: export["value"] for export in nodes[0]["exports"]}


@pytest.mark.e2e
def test_a_headless_read_reports_every_corpus_value_exactly(godot_project):
    """The whole corpus, read back through a headless reply, bit for bit.

    Before #771 this reply was framed with Godot's DEFAULT ``JSON.stringify``, so
    40 of these rows came back as ``0.0`` and 15 more as a different double — the
    caller was handed a number the project does not hold, unmarked.
    """
    run = _probe_project(godot_project)
    values = _exports_by_name(run)

    measured = [0, 0, 0]
    for index, case in enumerate(LIVE_NUMBER_CORPUS):
        arrived = values[f"v{index}"]
        assert isinstance(arrived, float), (case.label, arrived)
        tally_outcome(measured, case.value, arrived)
        if value_bits(case.value) != value_bits(-0.0):
            assert value_bits(arrived) == value_bits(case.value), (
                f"{case.label}: the headless reply changed the value the project holds"
            )

    # The SAME partition the live result direction is measured against, because it
    # is the same engine writer — derived from the corpus, never transcribed.
    assert Partition(*measured) == PARTITIONS["full_precision"]

    # The element-wise arm of the value projection reads through the same writer:
    # a packed array's floats are not a separate spelling.
    packed = values["all_values"]
    assert [value_bits(item) for item in packed] == [
        value_bits(0.0 if value_bits(case.value) == value_bits(-0.0) else case.value)
        for case in LIVE_NUMBER_CORPUS
    ]


@pytest.mark.e2e
def test_the_same_values_read_the_same_through_node_get(godot_project):
    """`node get` and `scene get-exports` report one value, not two.

    The fix is the REPLY's, not one operation's, so two commands that project the
    same node's properties must agree — including on the rows the default writer
    used to flatten.
    """
    run = _probe_project(godot_project)
    exported = _exports_by_name(run)

    read = run("node", "get", "numbers.tscn", "--node", ".")
    assert read.returncode == 0, read.stdout + read.stderr
    properties = {
        entry["name"]: entry["value"] for entry in json.loads(read.stdout)["properties"]
    }

    checked = 0
    for index, case in enumerate(LIVE_NUMBER_CORPUS):
        name = f"v{index}"
        if name not in properties:
            continue
        assert value_bits(properties[name]) == value_bits(exported[name]), case.label
        checked += 1
    assert checked == len(LIVE_NUMBER_CORPUS), checked


@pytest.mark.e2e
def test_negative_zero_is_the_one_disclosed_headless_residual(godot_project):
    """`-0.0` reads back as `0.0` — the residual the contract states, not hides.

    Not a gda choice and not fixable by the writer argument: ``JSON::_stringify``
    returns ``"0.0"`` for anything equal to zero before the precision argument is
    consulted. The live side discloses the same residual for the same reason.
    """
    run = _probe_project(godot_project)
    values = _exports_by_name(run)
    index = next(
        i
        for i, case in enumerate(LIVE_NUMBER_CORPUS)
        if value_bits(case.value) == value_bits(-0.0)
    )

    arrived = values[f"v{index}"]
    assert arrived == 0.0
    assert math.copysign(1.0, arrived) > 0

    # And it really is the ONLY row the reply changes.
    changed = [
        case.label
        for i, case in enumerate(LIVE_NUMBER_CORPUS)
        if value_bits(values[f"v{i}"]) != value_bits(case.value)
    ]
    assert changed == ["-zero"], changed


@pytest.mark.e2e
def test_a_project_setting_round_trips_through_set_and_get(godot_project):
    """The issue's own reproduction: `project set` → `project get`, both exact.

    `project set --value 3.141592653589793` used to answer `3.14159265358979` from
    the `set` itself and again from the `get`, and `--value 1e-300` answered `0.0`
    from both — while `project.godot` held the value the caller sent. These are the
    two literals #771 quotes, and they are the round-trip the catalog promises.
    """
    run = _gda(godot_project)
    setting = "physics/2d/default_gravity"

    for literal, expected in (
        ("3.141592653589793", 3.141592653589793),
        ("1e-300", 1e-300),
    ):
        was_set = run("project", "set", setting, "--value", literal)
        assert was_set.returncode == 0, was_set.stdout + was_set.stderr
        assert value_bits(json.loads(was_set.stdout)["value"]) == value_bits(
            expected
        ), literal

        got = run("project", "get", setting)
        assert got.returncode == 0, got.stdout + got.stderr
        assert value_bits(json.loads(got.stdout)["value"]) == value_bits(expected), (
            literal
        )

        # ...and the setting the enumeration reports is the same value again.
        listed = run("project", "list", "--section", "physics/")
        assert listed.returncode == 0, listed.stdout + listed.stderr
        entry = next(
            item
            for item in json.loads(listed.stdout)["settings"]
            if item["setting"] == setting
        )
        assert value_bits(entry["value"]) == value_bits(expected), literal
