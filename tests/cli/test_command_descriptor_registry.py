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
import typing

import typer
from pydantic import BaseModel

import gda.commands
import gda.render as render_mod
from gda.cli import app
from gda.runner import UserDataReport


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


# The one non-domain group module (ADR-0005/0040): its commands are top-level and
# ungrouped, so it mounts no sub-app — these names must exist on the root. `version`
# and `help` are the two ADR-0005 named from the start and #670 delivered.
_META_MODULE = "meta"
_META_TOP_LEVEL_COMMANDS = {"info", "skill", "schema", "version", "help"}


def test_every_group_module_is_registered_on_the_root_app():
    # The mount invariant (ADR-0040): a group module that is never `register`ed on
    # the composition root would silently vanish from the CLI — every other test
    # here walks the LIVE Typer tree, so it would simply not see the group and stay
    # green. This walks the PACKAGE instead and asserts each module reaches the tree.
    root = typer.main.get_command(app)
    mounted = getattr(root, "commands", {})
    for info in pkgutil.iter_modules(gda.commands.__path__):
        module = importlib.import_module(f"gda.commands.{info.name}")
        assert callable(getattr(module, "register", None)), (
            f"group module '{info.name}' exposes no register(root) — "
            f"add one to gda/commands/{info.name}.py (ADR-0040)"
        )
        if info.name == _META_MODULE:
            continue
        group = mounted.get(info.name)
        assert group is not None, (
            f"group module '{info.name}' is not mounted — "
            f"add {info.name}.register(app) to gda/cli.py"
        )
        assert getattr(group, "commands", None) is not None, (
            f"'{info.name}' is mounted as a leaf command, not a command group — "
            f"its register() should add_typer its sub-app"
        )
    missing_meta = sorted(_META_TOP_LEVEL_COMMANDS - set(mounted))
    assert not missing_meta, (
        f"meta commands absent from the root app: {missing_meta} — "
        f"add meta.register(app) to gda/cli.py (ADR-0005/0040)"
    )


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
    "render_property_lines",  # the shared node/resource/game properties read
    "render_set_echo",  # the shared node/resource property-set echo line
    "render_script_metadata",  # the shared path/class_name/extends script surface
    "render_shader_metadata",  # the shared shader-metadata surface
    # The root `--version` one-liner (gda.provenance), imported into the meta module
    # and composed by `render_version` so the flag and the `gda version` command print
    # the same line (#670). Bound to no descriptor of its own.
    "render_version_line",
    # The human layout of the shared FAILURE envelope (#685). Bound to no descriptor
    # by construction: a descriptor's `render` takes that command's own RESULT model,
    # while the error half is one schema identical for every command (ADR-0004), so
    # its rendering is one function the failure channel calls — not a per-command one.
    "render_failure",
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
    # `script validate` is the one recipe that still RUNS the sentinel op (via
    # `cmd.execute`, as the export recipe does for its preflight): it carries a
    # recipe because the outside-the-project refusal and the `project_root` on its
    # result are decided from ADR-0006's CLI-resolved project, which `cmd.emit`
    # does not expose to a command (#658).
    "script-validate",
    # `scene validate` carries a recipe for the same one reason (#664): its
    # `project_root` comes from ADR-0006's CLI-resolved project, and every problem it
    # reports is a res:// resolution outcome, so the verdict is unreadable without it.
    "scene-validate",
    # `scene preflight` dispatches a sentinel op through the launch primitive rather
    # than the runner seam (#664): it needs the streaming capture, so that a run gda
    # ends at its bound still carries what the engine printed — the whole evidence of
    # a scene that never came up. That dispatch is the recipe.
    "scene-preflight",
    "daemon-start",
    "daemon-stop",
    "daemon-status",
    "daemon-uninstall",
    "screen-capture",
    "screen-frames",
    # `perf monitors` carries both the snapshot and the #662 window mode on one
    # surface (the issue's triage decision); the window statistics and budget
    # verdicts are computed CLI-side from the harness's raw samples (the
    # `screen` pattern), so the command carries a recipe that still runs the
    # sentinel ops.
    "perf-monitors",
    # `gda skill` is a pure local emitter meta command (ADR-0024): it reads the
    # in-package SKILL.md and emits/installs it, spawning no Godot, so it is
    # fulfilled by a CLI-side recipe like export run / the daemon lifecycle.
    "skill",
    # The other two pure emitter meta commands (ADR-0005, #670): `version` renders this
    # install's provenance and `help` renders a command's own help text — neither
    # spawns Godot, so both are recipes for the same reason `skill` is.
    "version",
    "help",
    # `daemon install` is the fifth daemon lifecycle recipe (ADR-0018, #670): the
    # idempotent harness install `daemon start` folds in, runnable on its own.
    "daemon-install",
    # `resource import` (#668) decides per-asset cache verdicts CLI-side and
    # calls the shared launch primitive with the engine's project-wide
    # `--import` argv — not a sentinel op, like `export run`'s native channel.
    "resource-import",
    # `input sequence` (#838) names the injection route of each phase it applied,
    # and the harness reply counts the events without enumerating them: only the
    # request holds the per-event kinds, so the recipe completes the sentinel op's
    # result the way `perf monitors` correlates its reply.
    "input-sequence",
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


# The user-data placement `gda script run` publishes (#850). Every launch-backed
# channel gets the same facts from the ONE launch primitive, so nothing but a
# result-model field stops the disclosure leaking into the others' `--json`.
_PLACEMENT_FIELDS = {"user_data_root", "engine_data_path", "log_file"}


def _annotation_classes(annotation) -> list:
    """Every class an annotation mentions, its type ARGUMENTS included.

    `str | None`, `list[Thing]` and `Optional[Thing]` all hide their real subject
    inside `get_args`, so a check that only looked at the annotation itself would
    miss a nested carrier declared in any of those shapes.
    """
    found = []
    stack = [annotation]
    while stack:
        current = stack.pop()
        if isinstance(current, type):
            found.append(current)
        stack.extend(typing.get_args(current))
    return found


def _carries_the_placement(model, seen: set | None = None) -> bool:
    """Whether this result model publishes the launch's user-data placement, at ANY depth.

    Three ways it can, and the test below has to see all three: one of the three
    public key names on the model itself; a field typed as the runner's own
    `UserDataReport`; or a NESTED model that does either. Checking only top-level
    field names — which this guard did at first — would let a future channel smuggle
    the placement in as a sub-object and still pass.
    """
    seen = set() if seen is None else seen
    if model in seen:
        return False
    seen.add(model)
    # Resolve string/forward annotations before reading them: a nested model
    # declared AFTER its user leaves the field annotation a bare `ForwardRef`, which
    # names no class and would walk straight past a smuggled carrier. Rebuilding is
    # a no-op for an already-complete model, and the completeness assertion below
    # turns an annotation this guard cannot see into a loud failure rather than a
    # silent pass.
    model.model_rebuild(raise_errors=False)
    assert model.__pydantic_complete__, (
        f"{model.__name__} has unresolved annotations; this guard cannot read them"
    )
    for name, field in model.model_fields.items():
        if name in _PLACEMENT_FIELDS:
            return True
        for cls in _annotation_classes(field.annotation):
            if cls is UserDataReport:
                return True
            if issubclass(cls, BaseModel) and _carries_the_placement(cls, seen):
                return True
    return False


def test_only_script_run_publishes_the_launch_user_data_placement():
    # #850 disclosed the placement on `script run` alone. `scene preflight`,
    # `export run`, `resource import` and every sentinel command share the primitive
    # that now carries those facts on its Raw run, so their results must stay
    # byte-identical: this fails the moment another output model grows one of the
    # three keys — or a nested object carrying them — without its own issue deciding
    # it should.
    carriers = {
        name
        for name, cmd in _dispatchable()
        if _carries_the_placement(cmd.output_model)
    }

    assert carriers == {"script run"}
    from gda.commands.script import ScriptRunResult

    assert _PLACEMENT_FIELDS <= set(ScriptRunResult.model_fields)
