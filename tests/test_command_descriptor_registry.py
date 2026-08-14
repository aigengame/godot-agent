"""Command descriptor registration invariants (ADR-0023).

ADR-0023 makes the ``HeadlessCommand`` descriptor the single per-command
registration: its ``render`` is the command's human renderer, replacing the old
type-keyed dispatch table in :mod:`gda.render`. These tests walk the LIVE Typer
command tree — the same authority :mod:`gda.surface` uses for the schema manifest
— and assert every dispatchable command carries a renderer, and that no renderer
in :mod:`gda.render` is orphaned. This turns the former first-invocation
``KeyError`` ("command wired without a renderer") into a test-time guarantee.
"""

import importlib
import pkgutil

import typer

import gda.commands
import gda.render as render_mod
from gda.cli import app


def _leaf_commands(command, path):
    """Yield ``(name, command_obj)`` for every leaf of the Typer tree (cf. gda.surface).

    A group is identified by its ``commands`` mapping (the same Click duck-type the
    surface walker uses); a leaf has none.
    """
    subcommands = getattr(command, "commands", None)
    if subcommands is not None:
        for name, sub in subcommands.items():
            yield from _leaf_commands(sub, [*path, name])
        return
    yield " ".join(path), command


def _dispatchable():
    """The dispatchable leaf commands — those with a backing ``HeadlessCommand``.

    Mirrors the surface manifest's dispatchable-operation surface: a leaf whose
    ``gda_command`` is ``None`` (the bare ``gda schema`` meta command) is not a
    dispatchable operation and carries no renderer.
    """
    root = typer.main.get_command(app)
    for name, command in _leaf_commands(root, []):
        gda_command = getattr(command, "gda_command", None)
        if gda_command is not None:
            yield name, gda_command


def test_every_dispatchable_command_carries_a_renderer():
    # The KeyError replacement: a command wired without a renderer is caught here at
    # test time, not on its first human-output invocation.
    dispatchable = list(_dispatchable())
    assert dispatchable, "the Typer tree walk found no dispatchable commands"
    missing = [name for name, cmd in dispatchable if cmd.render is None]
    assert not missing, f"commands missing render= (ADR-0023): {missing}"
    not_callable = [name for name, cmd in dispatchable if not callable(cmd.render)]
    assert not not_callable, f"commands with a non-callable render: {not_callable}"


# Renderers that are internal helpers — composed by other renderers, never bound to
# a command result type, so legitimately absent from every descriptor.
_HELPER_RENDERERS = {
    "render_node_tree",  # the indented tree walk reused by scene-get / node-list
    "render_script_metadata",  # the shared path/class_name/extends script surface
    "render_shader_metadata",  # the shared shader-metadata surface
}


def _renderer_modules():
    """Every module a renderer can live in: the shared helpers plus each group.

    Since ADR-0040 a group's renderers live in its own ``gda.commands.<group>``
    module, next to the descriptors that bind them; ``gda.render`` keeps only the
    helpers shared across groups. The package is walked rather than listed, so a
    group moved in a later slice is covered without editing this test.
    """
    modules = [render_mod]
    for info in pkgutil.iter_modules(gda.commands.__path__):
        modules.append(importlib.import_module(f"gda.commands.{info.name}"))
    return modules


def test_no_renderer_is_orphaned():
    # Every ``render_*`` in gda.render or a group module is either bound to a command
    # (reachable via a descriptor) or a known internal helper — no dead renderer
    # survives the move off the type-keyed table.
    defined = {
        name
        for module in _renderer_modules()
        for name in dir(module)
        if name.startswith("render_") and callable(getattr(module, name))
    }
    bound = {cmd.render.__name__ for _, cmd in _dispatchable()}
    orphaned = defined - bound - _HELPER_RENDERERS
    assert not orphaned, (
        f"render_* functions defined but bound to no command and not a known helper: "
        f"{sorted(orphaned)}"
    )
    # And nothing claims to be bound that the module does not define (a stale import).
    assert not (bound - defined), (
        f"descriptors bind undefined renderers: {sorted(bound - defined)}"
    )


# The recipe-bearing commands — those fulfilled by a CLI-side recipe (export run /
# the daemon lifecycle / screen) instead of the sentinel `cmd.emit` (ADR-0023). This
# set is the modern, descriptor-driven replacement for the old `_DAEMON_COMMANDS` /
# `_SCREEN_COMMANDS` identity frozensets + the export `kind` special-case: now it is
# an asserted INVARIANT over the descriptors, not a dispatch mechanism.
_RECIPE_OPERATIONS = {
    "export-run",
    # `script run` is the third execution shape (ADR-0031): a user-script passthrough
    # run, fulfilled by a CLI-side recipe (it emits no ADR-0002 sentinel) like export
    # run, so it carries a recipe rather than routing to `cmd.emit`.
    "script-run",
    "daemon-start",
    "daemon-stop",
    "daemon-status",
    "daemon-uninstall",
    "screen-capture",
    "screen-frames",
    # `gda skill` is a pure local emitter meta command (ADR-0024): it reads the
    # in-package SKILL.md and emits/installs it, spawning no Godot, so it is
    # fulfilled by a CLI-side recipe like export run / the daemon lifecycle.
    "skill",
}


def test_recipe_commands_are_exactly_the_known_recipe_set():
    # Guards both regressions the frozensets used to risk: a recipe command silently
    # losing its recipe (→ routed to the sentinel runner) or a sentinel command
    # gaining one. The dispatch reads `cmd.recipe`; this pins which commands have it.
    have_recipe = {
        cmd.operation for _, cmd in _dispatchable() if cmd.recipe is not None
    }
    assert have_recipe == _RECIPE_OPERATIONS


def test_every_dispatchable_command_resolves_to_exactly_one_channel():
    # The single-channel invariant (ADR-0023): a command is dispatched EITHER by its
    # recipe OR by `cmd.emit` with its kind-selected runner — never both, never
    # neither. The two are mutually exclusive by `recipe is None`; both paths emit
    # through `cmd.render`, so every command (recipe or not) still needs a renderer.
    for name, cmd in _dispatchable():
        if cmd.recipe is not None:
            assert callable(cmd.recipe), f"{name}: recipe is set but not callable"
        # render is the shared emission tail for BOTH channels (asserted non-None by
        # test_every_dispatchable_command_carries_a_renderer); restated here as the
        # reason a recipe command needs no separate emission path.
        assert cmd.render is not None, f"{name}: no renderer for its emission tail"
