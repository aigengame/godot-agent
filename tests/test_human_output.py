"""End-to-end human-mode CLI output for every command (issue #140 follow-up).

PR #143 extracted human rendering into ``gda.render`` and pinned the renderers
in isolation (``test_render.py``); since ADR-0040 the renderers live in their
command-group modules. But the command-level *human* output path — invoking a
command WITHOUT ``--json`` through the real Typer CLI and asserting the exact
``stdout`` text — was only covered for ``script validate/attach/set``. This
closes that gap: one parameterized test drives every command in human mode
against a fake runner and pins the exact bytes the CLI prints, so the
descriptor-bound renderers are behavior-pinned end-to-end, not just unit-tested
in isolation.

The canned success payloads mirror the per-command ``--json`` tests
(``test_scene_commands.py``, ``test_node_commands.py``, ``test_script_commands.py``,
``test_info_command.py``) so the faked results match each command's result-model
shape. The expected strings are transcribed directly from the group modules'
renderers: a renderer produces a newline-free string and the CLI's ``typer.echo``
appends exactly one trailing newline, so each case asserts
``stdout == expected + "\n"``.

These run engine-free (FakeRunner) under ``-m "not e2e"``.
"""

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import inject_runner, sentinel

# Each case: (id, argv-without-`--json`, success-payload, expected-stdout-text).
# The payload is wrapped in the result sentinel as operations.gd emits it; the
# expected text is what the matching renderer in gda.render produces (the CLI
# adds the trailing newline). Every NEW-coverage command is here; the already
# human-pinned script validate/attach/set are included for uniformity.
HUMAN_CASES = [
    # --- scene group --------------------------------------------------------
    (
        "scene-create",
        ["scene", "create", "/tmp/proj/main.tscn", "--root-type", "Node2D"],
        {
            "path": "/tmp/proj/main.tscn",
            "root_name": "main",
            "root_type": "Node2D",
            "created_dirs": [],
        },
        "created /tmp/proj/main.tscn (root Node2D)",
    ),
    (
        "scene-get",
        ["scene", "get", "/tmp/proj/main.tscn"],
        {
            "path": "/tmp/proj/main.tscn",
            "root": {
                "name": "main",
                "type": "Node2D",
                "children": [
                    {
                        "name": "Hero",
                        "type": "Sprite2D",
                        "children": [
                            {"name": "Hitbox", "type": "Area2D", "children": []}
                        ],
                    }
                ],
            },
        },
        # render_node_tree: an indented `name (Type)` outline, two-space depth.
        "main (Node2D)\n  Hero (Sprite2D)\n    Hitbox (Area2D)",
    ),
    (
        "scene-list",
        ["scene", "list"],
        {
            "scenes": [
                {
                    "path": "res://main.tscn",
                    "root_name": "main",
                    "root_type": "Node2D",
                },
                {
                    "path": "res://ui/menu.tscn",
                    "root_name": "Menu",
                    "root_type": "Control",
                },
                # both root fields null -> the `(unreadable)` branch.
                {"path": "res://broken.tscn", "root_name": None, "root_type": None},
            ]
        },
        "res://main.tscn (main: Node2D)\n"
        "res://ui/menu.tscn (Menu: Control)\n"
        "res://broken.tscn (unreadable)",
    ),
    (
        "scene-list-empty",
        ["scene", "list"],
        {"scenes": []},
        "(no scenes)",
    ),
    (
        "scene-delete",
        ["scene", "delete", "/tmp/proj/old.tscn"],
        {"path": "/tmp/proj/old.tscn", "root_name": "old", "root_type": "Node2D"},
        "deleted /tmp/proj/old.tscn (root old: Node2D)",
    ),
    (
        # scene get-exports: a `path (Type)` header per node, then each export as
        # `name (Type) = value` — the value via format_value (float scalar, and
        # a Vector2 -> [x, y]).
        "scene-get-exports",
        ["scene", "get-exports", "/tmp/proj/main.tscn"],
        {
            "path": "/tmp/proj/main.tscn",
            "nodes": [
                {
                    "path": ".",
                    "name": "main",
                    "type": "Node2D",
                    "script": "res://main.gd",
                    "exports": [
                        {
                            "name": "speed",
                            "type": "float",
                            "hint": 0,
                            "hint_string": "",
                            "value": 3.5,
                        },
                        {
                            "name": "start",
                            "type": "Vector2",
                            "hint": 0,
                            "hint_string": "",
                            "value": [1.0, 2.0],
                        },
                    ],
                }
            ],
        },
        ". (Node2D)\n  speed (float) = 3.5\n  start (Vector2) = [1.0, 2.0]",
    ),
    (
        "scene-get-exports-empty",
        ["scene", "get-exports", "/tmp/proj/bare.tscn"],
        {"path": "/tmp/proj/bare.tscn", "nodes": []},
        "(no exports)",
    ),
    # --- node group ---------------------------------------------------------
    (
        "node-add",
        ["node", "add", "/tmp/proj/main.tscn", "--type", "Sprite2D", "--name", "Hero"],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "path": "Hero",
            "name": "Hero",
            "type": "Sprite2D",
            "script_class": None,
        },
        "added Hero (Sprite2D) to /tmp/proj/main.tscn",
    ),
    (
        "node-add-instance",
        ["node", "add", "/tmp/proj/main.tscn", "--instance", "res://hud.tscn"],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "path": "hud",
            "name": "hud",
            "type": "CanvasLayer",
            "script_class": None,
            "instance": "res://hud.tscn",
        },
        "added hud (CanvasLayer, instance of res://hud.tscn) to /tmp/proj/main.tscn",
    ),
    (
        "node-list",
        ["node", "list", "/tmp/proj/main.tscn"],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "root": {
                "name": "main",
                "type": "Node2D",
                "path": ".",
                "children": [
                    {
                        "name": "Hero",
                        "type": "Sprite2D",
                        "path": "Hero",
                        "children": [
                            {
                                "name": "Hitbox",
                                "type": "Area2D",
                                "path": "Hero/Hitbox",
                                "children": [],
                            }
                        ],
                    }
                ],
            },
        },
        # render_node_tree renders name (Type), NOT the node path.
        "main (Node2D)\n  Hero (Sprite2D)\n    Hitbox (Area2D)",
    ),
    (
        # node get whose Vector2 value exercises format_value (-> [x, y]); the
        # bool property pins the JSON `true` projection too.
        "node-get",
        ["node", "get", "/tmp/proj/main.tscn", "--node", "Hero"],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "path": "Hero",
            "name": "Hero",
            "type": "Sprite2D",
            "properties": [
                {"name": "position", "type": "Vector2", "value": [10.0, 20.0]},
                {"name": "visible", "type": "bool", "value": True},
            ],
        },
        "Hero (Sprite2D)\n  position (Vector2) = [10.0, 20.0]\n  visible (bool) = true",
    ),
    (
        # node set whose Vector2 value exercises format_value (-> [x, y]).
        "node-set",
        [
            "node",
            "set",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--property",
            "position",
            "--value",
            "3,4",
        ],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "path": "Hero",
            "property": "position",
            "type": "Vector2",
            "value": [3.0, 4.0],
        },
        "set Hero.position (Vector2) = [3.0, 4.0]",
    ),
    (
        "node-connect-signal",
        [
            "node",
            "connect-signal",
            "/tmp/proj/main.tscn",
            "--from",
            "Emitter",
            "--signal",
            "timeout",
            "--to",
            "Receiver",
            "--method",
            "on_timeout",
        ],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "from": "Emitter",
            "signal": "timeout",
            "to": "Receiver",
            "method": "on_timeout",
        },
        "connected Emitter.timeout -> Receiver.on_timeout",
    ),
    (
        "node-disconnect-signal",
        [
            "node",
            "disconnect-signal",
            "/tmp/proj/main.tscn",
            "--from",
            "Emitter",
            "--signal",
            "timeout",
            "--to",
            "Receiver",
            "--method",
            "on_timeout",
        ],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "from": "Emitter",
            "signal": "timeout",
            "to": "Receiver",
            "method": "on_timeout",
        },
        "disconnected Emitter.timeout -> Receiver.on_timeout",
    ),
    # --- script group -------------------------------------------------------
    (
        # script create WITH class_name + extends -> both metadata fragments,
        # extends first then class_name (render_script_metadata ordering).
        "script-create",
        ["script", "create", "/tmp/proj/hero.gd", "--extends", "Node2D"],
        {
            "path": "/tmp/proj/hero.gd",
            "class_name": "Hero",
            "extends": "Node2D",
            "created_dirs": [],
        },
        "created /tmp/proj/hero.gd (extends Node2D, class_name Hero)",
    ),
    (
        # script create with NO metadata -> bare path (the no-meta branch).
        "script-create-bare",
        ["script", "create", "/tmp/proj/util.gd", "--content", "extends RefCounted\n"],
        {
            "path": "/tmp/proj/util.gd",
            "class_name": None,
            "extends": None,
            "created_dirs": [],
        },
        "created /tmp/proj/util.gd",
    ),
    (
        "script-get",
        ["script", "get", "/tmp/proj/hero.gd"],
        {
            "path": "/tmp/proj/hero.gd",
            "source": "class_name Hero\nextends Node2D\n",
            "class_name": "Hero",
            "extends": "Node2D",
        },
        # render_script_get: the metadata line then the raw source.
        "/tmp/proj/hero.gd (extends Node2D, class_name Hero)\n"
        "class_name Hero\nextends Node2D\n",
    ),
    (
        "script-list",
        ["script", "list"],
        {
            "scripts": [
                {"path": "res://hero.gd", "class_name": "Hero", "extends": "Node2D"},
                # extends only, no class_name.
                {
                    "path": "res://util.gd",
                    "class_name": None,
                    "extends": "RefCounted",
                },
                # neither -> bare path.
                {"path": "res://empty.gd", "class_name": None, "extends": None},
            ]
        },
        "res://hero.gd (extends Node2D, class_name Hero)\n"
        "res://util.gd (extends RefCounted)\n"
        "res://empty.gd",
    ),
    (
        "script-list-empty",
        ["script", "list"],
        {"scripts": []},
        "(no scripts)",
    ),
    (
        "script-delete",
        ["script", "delete", "/tmp/proj/hero.gd"],
        {"path": "/tmp/proj/hero.gd", "class_name": "Hero", "extends": "Node2D"},
        "deleted /tmp/proj/hero.gd (extends Node2D, class_name Hero)",
    ),
    (
        # script set (already human-pinned elsewhere; included for uniformity).
        "script-set",
        ["script", "set", "/tmp/proj/hero.gd", "--content", "x"],
        {"path": "/tmp/proj/hero.gd", "class_name": "Hero", "extends": "Node2D"},
        "set /tmp/proj/hero.gd (extends Node2D, class_name Hero)",
    ),
    (
        # script attach (already human-pinned elsewhere; included for uniformity).
        "script-attach",
        [
            "script",
            "attach",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--script",
            "/tmp/proj/hero.gd",
        ],
        {
            "scene_path": "/tmp/proj/main.tscn",
            "node": "Hero",
            "script": "/tmp/proj/hero.gd",
            "class_name": "Hero",
        },
        "attached /tmp/proj/hero.gd to Hero in /tmp/proj/main.tscn",
    ),
    (
        # script validate valid (already human-pinned elsewhere; for uniformity).
        "script-validate-valid",
        ["script", "validate", "/tmp/proj/ok.gd"],
        {
            "valid": True,
            "scripts": [
                {"path": "/tmp/proj/ok.gd", "valid": True, "error_string": None}
            ],
        },
        "valid /tmp/proj/ok.gd",
    ),
    # --- export group -------------------------------------------------------
    (
        "export-list",
        ["export", "list"],
        {
            "presets": [
                {
                    "index": 0,
                    "name": "Linux/X11",
                    "platform": "Linux/X11",
                    "runnable": True,
                },
                # not runnable -> no [runnable] suffix.
                {"index": 1, "name": "Web", "platform": "Web", "runnable": False},
            ]
        },
        "Linux/X11 (Linux/X11) [runnable]\nWeb (Web)",
    ),
    (
        "export-list-empty",
        ["export", "list"],
        {"presets": []},
        "(no presets)",
    ),
    (
        "export-get",
        ["export", "get", "--preset", "Web"],
        {
            "index": 1,
            "name": "Web",
            "platform": "Web",
            "runnable": False,
            "export_path": "build/index.html",
            "templates_installed": True,
            "templates_version": "4.6.3.stable",
        },
        "Web (Web)\n"
        "  export_path: build/index.html\n"
        "  templates installed (4.6.3.stable)",
    ),
    (
        # templates missing branch + runnable suffix.
        "export-get-missing-templates",
        ["export", "get", "--preset", "Linux/X11"],
        {
            "index": 0,
            "name": "Linux/X11",
            "platform": "Linux/X11",
            "runnable": True,
            "export_path": "",
            "templates_installed": False,
            "templates_version": "4.6.3.stable",
        },
        "Linux/X11 (Linux/X11) [runnable]\n"
        "  export_path: \n"
        "  templates missing (4.6.3.stable)",
    ),
    # --- meta ---------------------------------------------------------------
    (
        "info",
        ["info"],
        {
            "major": 4,
            "minor": 6,
            "patch": 3,
            "hex": 0x040603,
            "status": "stable",
            "build": "official",
            "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
            "string": "4.6.3-stable (official)",
            "timestamp": 0,
        },
        # render_engine_version: the one-line version string.
        "4.6.3-stable (official)",
    ),
]


@pytest.mark.parametrize(
    ("argv", "payload", "expected"),
    [(argv, payload, expected) for _id, argv, payload, expected in HUMAN_CASES],
    ids=[case[0] for case in HUMAN_CASES],
)
def test_human_mode_cli_output_is_exactly_the_rendered_text(
    monkeypatch, argv, payload, expected
):
    # Invoke the command in HUMAN mode (no --json) through the real Typer CLI
    # with a fake runner, and assert the exact stdout: the renderer's text plus
    # the single trailing newline typer.echo adds. This pins #139's render
    # dispatch + #140's gda.render end-to-end, per command.
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, argv)

    assert result.exit_code == 0
    assert result.stdout == expected + "\n"
