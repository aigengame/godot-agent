"""e2e: a mutating op that refuses after the load leaks nothing at exit (#1064).

A mutating op loads its scene through the scene store, and the store owns the
tree it instantiates (ADR-0043): the save tail frees the tree on every path, and
the store frees a tree that is still alive when the store itself is freed. A
failure path in a group therefore frees nothing itself. Without that release
the engine reports the tree at exit: ``ObjectDB instances leaked at exit``,
``<n> resources still in use at exit`` and leaked RIDs, on stderr and in the
envelope's ``diagnostics``.

The entry drops the group, and with it the store, on the idle frame that quits,
while the project's autoloads are still in the tree. The engine frees the
autoloads before it frees the entry's script, so a store freed only then would
run the tree's project code after the autoloads are gone: a root script that
calls an autoload from its predelete crashes the engine (signal 11), and the
refusal comes back as ``engine_crashed``.

The scene is the shared editable-instance fixture, with a root script that
calls an autoload when the tree is freed. The entry prints the result on that
same frame, after the release, so what the release prints lands before the
result on stdout, where the parser ignores it (ADR-0002).
"""

import json

import pytest

from tests.conftest import project_godot
from tests.support import Gda, assert_operation_error, write_instance_fixture

# What the engine prints at exit for an object or resource still alive.
LEAK_RECORDS = ("leaked", "still in use at exit")

REGISTRY_GD = """\
extends Node


func record(what: String) -> void:
	print("registry: ", what)
"""

NOISY_ROOT_GD = """\
extends Node2D


func _notification(what: int) -> void:
	if what == NOTIFICATION_PREDELETE:
		Registry.record("freed " + name)
"""


def _noisy_project(tmp_path, registry_gd: str) -> tuple[Gda, object]:
    """The instance fixture with a root script that calls the ``Registry`` autoload
    from its predelete; ``registry_gd`` decides what the autoload prints."""
    (tmp_path / "project.godot").write_text(
        project_godot(extra='[autoload]\n\nRegistry="*res://registry.gd"\n'),
        encoding="utf-8",
    )
    (tmp_path / "registry.gd").write_text(registry_gd, encoding="utf-8")
    scene = write_instance_fixture(tmp_path)
    (tmp_path / "noisy_root.gd").write_text(NOISY_ROOT_GD, encoding="utf-8")
    gda = Gda(tmp_path)
    gda.json(
        "script",
        "attach",
        "res://parent.tscn",
        "--node",
        ".",
        "--script",
        "res://noisy_root.gd",
    )
    return gda, scene


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (
            ("node", "remove", "res://parent.tscn", "--node", "ChildInstance/Inner"),
            "cannot_target_foreign",
        ),
        (
            (
                "script",
                "attach",
                "res://parent.tscn",
                "--node",
                "ChildInstance",
                "--script",
                "res://missing.gd",
            ),
            "path_not_found",
        ),
    ],
    ids=["node-group", "script-group"],
)
def test_a_refused_mutating_op_leaks_nothing_at_exit(tmp_path, argv, code):
    gda, scene = _noisy_project(tmp_path, REGISTRY_GD)
    before = scene.read_bytes()

    proc = gda(*argv, "--json")

    err = assert_operation_error(proc, code)
    assert scene.read_bytes() == before
    for record in LEAK_RECORDS:
        assert record not in proc.stderr, proc.stderr
        assert record not in err["diagnostics"], err["diagnostics"]


# The worst case of "project code prints during the release": a line that carries
# the end sentinel. The parser keys on the LAST end sentinel after the begin
# sentinel (ADR-0002, #34), so such a line printed after the result would extend
# the result past its real end, and the CLI would report a contract violation
# where the op succeeded, or `operation_failed` where it refused with a code.
MARKER_REGISTRY_GD = """\
extends Node


func record(what: String) -> void:
	print("release: <<<GDA:END>>>")
"""


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (
            (
                "node",
                "move",
                "res://parent.tscn",
                "--node",
                "ChildInstance",
                "--to",
                ".",
            ),
            None,
        ),
        (("node", "remove", "res://parent.tscn", "--node", "."), "cannot_target_root"),
    ],
    ids=["no-save-success", "structured-refusal"],
)
def test_a_release_time_print_of_the_end_sentinel_does_not_reach_the_result(
    tmp_path, argv, code
):
    gda, scene = _noisy_project(tmp_path, MARKER_REGISTRY_GD)
    before = scene.read_bytes()

    proc = gda(*argv, "--json")

    if code is None:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "error" not in json.loads(proc.stdout)
    else:
        assert_operation_error(proc, code)
    assert scene.read_bytes() == before
    for record in LEAK_RECORDS:
        assert record not in proc.stderr, proc.stderr
