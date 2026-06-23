"""Command descriptor registration invariants (ADR-0023).

ADR-0023 makes the ``HeadlessCommand`` descriptor the single per-command
registration: its ``render`` is the command's human renderer, replacing the old
type-keyed dispatch table in :mod:`gda.render`. These tests walk the LIVE Typer
command tree — the same authority :mod:`gda.surface` uses for the schema manifest
— and assert every dispatchable command carries a renderer, and that no renderer
in :mod:`gda.render` is orphaned. This turns the former first-invocation
``KeyError`` ("command wired without a renderer") into a test-time guarantee.
"""

import typer

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


def test_no_renderer_is_orphaned():
    # Every ``render_*`` in gda.render is either bound to a command (reachable via a
    # descriptor) or a known internal helper — no dead renderer survives the move off
    # the type-keyed table.
    defined = {
        name
        for name in dir(render_mod)
        if name.startswith("render_") and callable(getattr(render_mod, name))
    }
    bound = {cmd.render.__name__ for _, cmd in _dispatchable()}
    orphaned = defined - bound - _HELPER_RENDERERS
    assert not orphaned, (
        f"render_* functions defined but bound to no command and not a known helper: "
        f"{sorted(orphaned)}"
    )
    # And nothing claims to be bound that the module does not define (a stale import).
    assert not (bound - defined), f"descriptors bind undefined renderers: {sorted(bound - defined)}"
