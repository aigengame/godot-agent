"""The ``project`` command group: the Godot project as a whole as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the cross-command contract core (``gda.models``) and the shared render helpers
(``gda.render``) — and is imported by nothing but the composition root
(``gda.cli``).

Distinct from ``gda.project``, the core module that resolves the project
DIRECTORY (ADR-0006): that one stays in the shared core below this layer, and
the absolute imports keep the two names apart.
"""

from typing import Annotated, Any, Literal, Optional, Union

import typer
from pydantic import BaseModel, Field, model_validator

from gda.dispatch import dispatch_domain, params_or_bad_parameter
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import (
    EngineVersion,
    NormalizedPath,
    projected_value_schema_extra,
    SET_ECHO_VALUE_DESC,
    VALUE_PROJECTION_DESC,
)
from gda.render import format_value


# --- project static-analysis reads (issue #116) -----------------------------
#
# Four read-only, project-wide analysis commands, all backed by a single static
# project scan: find-references, dependencies, find-unused-resources, statistics.
# The scan parses files as TEXT (.tscn/.tres ext_resource paths, .gd
# preload/load/class_name references) — it never instantiates a scene or loads a
# script, so it honors the read trust boundary (issue #30). The only residual
# project-code execution is the engine constructing the project's autoloads at
# startup, inherent to any ``--project`` op (issue #61), documented on the params.


class ProjectFindReferencesParams(BaseModel):
    """The operation params of ``gda project find-references`` (issue #116).

    ``target`` is what to find references TO: a resource's ``res://`` path (a
    scene, script, image, ``.tres`` resource — anything addressable by path), or
    a script ``class_name``. The scan reads project files as TEXT and never
    instantiates a scene or loads a script (issue #30); the only project code that
    runs is the project's autoloads, constructed by the engine at startup on any
    ``--project`` op (issue #61).
    """

    target: NormalizedPath = Field(
        description=(
            "What to find references to: a resource's res:// path (scene, script, "
            "image, .tres, …) or a script class_name."
        )
    )


class ResourceReference(BaseModel):
    """One referencing site found by ``gda project find-references`` (issue #116).

    ``path`` is the ``res://`` path of the file that references the target — or
    ``project.godot`` for a project-level reference (an autoload or the main
    scene). ``kind`` names how it references it: ``ext_resource`` (a
    scene/resource ext_resource entry), ``preload``/``load`` (a script load
    call), ``class_extends`` (a script extending a base-class-by-path),
    ``class_reference`` (a ``.gd`` file using the target ``class_name`` as a bare
    identifier — best-effort, whole-word), or ``autoload``/``main_scene`` (a
    project-level reference in ``project.godot``). ``context`` is the matched
    line/snippet, best-effort, so an agent can locate the reference without
    re-reading the file.
    """

    path: str = Field(
        description=(
            "The res:// path of the referencing file, or 'project.godot' for a "
            "project-level reference."
        )
    )
    kind: str = Field(
        description=(
            "How the file references the target: ext_resource, preload, load, "
            "class_extends, class_reference, autoload, or main_scene."
        )
    )
    context: str = Field(
        description="The matched line or snippet that holds the reference."
    )


class ProjectFindReferencesResult(BaseModel):
    """The result of ``gda project find-references``: every site referencing the target.

    Echoes the ``target`` and the list of referencing sites. A target nothing
    references is a valid, empty result (``references == []``), not a failure —
    that emptiness is exactly what ``find-unused-resources`` keys on, so the two
    stay consistent (same reference graph).
    """

    target: str
    references: list[ResourceReference]


class ProjectDependenciesParams(BaseModel):
    """The operation params of ``gda project dependencies`` — none (ADR-0004).

    ``dependencies`` maps every scene/resource in the resolved project to the
    resources it references (its ``[ext_resource]`` entries). The project is
    process context (``--project``), not an operation param (ADR-0006), so the
    ``input`` schema is trivially empty.
    """


class Dependency(BaseModel):
    """One outgoing reference of a scene/resource (issue #116).

    ``path`` is the referenced resource's ``res://`` path; ``kind`` names how it
    is referenced (``ext_resource`` for a ``[ext_resource]`` entry).
    """

    path: str = Field(description="The res:// path of the referenced resource.")
    kind: str = Field(description="How the resource is referenced (ext_resource).")


class ResourceDependencies(BaseModel):
    """One scene/resource and the resources it references (issue #116).

    ``path`` is the scene/resource's own ``res://`` path; ``depends_on`` lists the
    resources it references. A scene with no external references is reported with
    an empty ``depends_on``, not dropped.
    """

    path: str = Field(description="The res:// path of the scene/resource.")
    depends_on: list[Dependency]


class ProjectDependenciesResult(BaseModel):
    """The result of ``gda project dependencies``: the scene/resource → resource map.

    An empty project is a valid, empty map (``dependencies == []``), not a
    failure. Built from the same ext_resource parse as ``find-references``, so the
    two views of the reference graph stay consistent.
    """

    dependencies: list[ResourceDependencies]


class ProjectFindUnusedResourcesParams(BaseModel):
    """The operation params of ``gda project find-unused-resources`` — none (ADR-0004).

    Reports resource files that nothing references, built on the SAME reference
    graph as ``find-references``/``dependencies`` (acceptance criterion: the three
    must agree). The project is process context (``--project``), not an operation
    param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ProjectFindUnusedResourcesResult(BaseModel):
    """The result of ``gda project find-unused-resources``: the unreferenced resources.

    ``unused`` lists the ``res://`` paths of resource files that no other file
    references AND that are not project entry points (the main scene, an autoload
    script). A resource is unused exactly when ``find-references`` for it would
    return an empty list — the consistency the issue requires. An empty list means
    every resource is referenced (or an entry point).
    """

    unused: list[str]


class ProjectStatisticsParams(BaseModel):
    """The operation params of ``gda project statistics`` — none (ADR-0004).

    Reports file/line counts, autoloads and plugins for the resolved project. The
    project is process context (``--project``), not an operation param (ADR-0006),
    so the ``input`` schema is trivially empty.
    """


class ExtensionCount(BaseModel):
    """File/line counts for one file extension (issue #116).

    ``extension`` is the lowercased extension without the dot (``gd``, ``tscn``);
    ``files`` is how many files carry it; ``lines`` is their summed line count.
    """

    extension: str = Field(
        description="The lowercased file extension without the dot (e.g. gd, tscn)."
    )
    files: int
    lines: int


class Autoload(BaseModel):
    """One project autoload singleton (issue #116).

    ``name`` is the singleton name; ``path`` its ``res://`` script/scene path
    (with any leading ``*`` enable marker stripped). Read from ProjectSettings,
    not by executing the autoload.
    """

    name: str
    path: str = Field(
        description="The autoload's res:// path (enable marker stripped)."
    )


class ProjectStatisticsResult(BaseModel):
    """The result of ``gda project statistics``: file/line counts, autoloads, plugins.

    ``total_files``/``total_lines`` are the project-wide totals; ``by_extension``
    breaks them down per extension. ``autoloads`` lists the project's autoload
    singletons (name + path, read from ProjectSettings); ``plugins`` lists the
    enabled editor plugins' ``plugin.cfg`` ``res://`` paths. ``scene_count`` /
    ``script_count`` / ``resource_count`` are convenience counts of ``.tscn`` /
    ``.gd`` / other-resource files. Line counts cover text files only; binary
    assets contribute to file counts but not line counts.
    """

    total_files: int
    total_lines: int
    by_extension: list[ExtensionCount]
    autoloads: list[Autoload]
    plugins: list[str] = Field(
        description="The res:// paths of the enabled editor plugins' plugin.cfg files."
    )
    scene_count: int
    script_count: int
    resource_count: int


class ProjectInfoParams(BaseModel):
    """The operation params of ``gda project info`` — none (ADR-0004).

    ``project info`` reports the resolved project's metadata from its
    ``ProjectSettings``; the project is process context (``--project``), not an
    operation param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ProjectInfoResult(BaseModel):
    """The result of ``gda project info``: core project metadata (issue #111).

    Reports the project's ``name`` and ``main_scene`` from ``ProjectSettings``,
    its configured ``viewport_width``/``viewport_height``, and the ``engine_version``
    the project runs on (the same shape ``gda info`` reports). ``main_scene`` is the
    empty string for a project that has not set a main scene, and the viewport
    fields fall back to the engine's built-in defaults when the project never set
    them, so a brand-new project still reports a complete, valid result.
    """

    name: str = Field(
        description="The project name (ProjectSettings application/config/name)."
    )
    main_scene: str = Field(
        description=(
            "The project's main scene path (application/run/main_scene), or the "
            "empty string when none is set."
        )
    )
    viewport_width: int = Field(
        description="The configured viewport width (display/window/size/viewport_width)."
    )
    viewport_height: int = Field(
        description="The configured viewport height (display/window/size/viewport_height)."
    )
    engine_version: EngineVersion = Field(
        description="The Godot engine version the project runs on."
    )


class ProjectGetParams(BaseModel):
    """The operation params of ``gda project get`` (issue #111).

    ``setting`` is the project setting's full ``section/key`` name (e.g.
    ``application/config/name``). The project is process context (``--project``),
    not an operation param (ADR-0006), so only ``setting`` is an input.
    """

    setting: str = Field(
        description=(
            "The project setting's full section/key name, e.g. application/config/name."
        )
    )


class ProjectGetResult(BaseModel):
    """The result of ``gda project get``: one setting as typed JSON (issue #111).

    Echoes the addressed ``setting``, its declared Godot ``type`` name, and its
    ``value`` in the same JSON projection ``node get`` reports for a node property
    (a scalar stays a scalar, a Vector2 becomes ``[x, y]``) — the projection
    ``project set`` accepts back, so a ``set`` round-trips through a ``get``.
    """

    setting: str
    type: str = Field(
        description="The setting's declared Godot type name (e.g. String, int, Vector2)."
    )
    value: Any = Field(
        description="The setting's value as JSON. " + VALUE_PROJECTION_DESC,
        json_schema_extra=projected_value_schema_extra,
    )


class ProjectListParams(BaseModel):
    """The operation params of ``gda project list`` (issue #312).

    Enumerates the project's ``ProjectSettings`` keys so an agent can DISCOVER
    which settings exist — the list half of the ``list → get → set`` workflow
    (``get``/``set`` both require you to already know the ``section/key``).
    ``include_defaults`` (the CLI ``--all`` flag) widens the listing from only the
    project's customized (non-default) settings to the engine's built-in defaults
    too; ``section`` restricts it to keys whose name begins with that ``section/``
    prefix (e.g. ``application/``, ``display/``), and the two compose. The project
    is process context (``--project``), not an operation param (ADR-0006).
    """

    include_defaults: bool = Field(
        default=False,
        description=(
            "Also list the engine's built-in default settings, not just the "
            "project's customized (non-default) ones. The CLI --all flag."
        ),
    )
    section: str | None = Field(
        default=None,
        description=(
            "Restrict the listing to keys whose name begins with this section/ "
            "prefix, e.g. application/ or display/. Null lists every section."
        ),
    )


class ListedProjectSetting(BaseModel):
    """One enumerated project setting of ``gda project list`` (issue #312).

    Reuses the same ``{setting, type, value}`` projection ``project get`` reports
    for a single setting — so a listed entry round-trips through ``project get`` —
    plus ``is_default``: ``false`` when the key is customized (written in
    ``project.godot``), ``true`` when it is at the engine's built-in default.
    """

    setting: str
    type: str = Field(
        description="The setting's declared Godot type name (e.g. String, int, Vector2)."
    )
    value: Any = Field(
        description="The setting's value as JSON. " + VALUE_PROJECTION_DESC,
        json_schema_extra=projected_value_schema_extra,
    )
    is_default: bool = Field(
        description=(
            "True when the setting is at the engine's built-in default; false when "
            "it is customized in project.godot."
        )
    )


class ProjectListResult(BaseModel):
    """The result of ``gda project list``: the project's enumerated settings (#312).

    ``settings`` is the discovered keys, each a ``{setting, type, value,
    is_default}`` entry sorted by name. A project with no customized settings and
    no ``include_defaults`` is a valid, EMPTY listing — ``settings == []`` — not a
    failure. Internal engine-bookkeeping and non-setting properties are filtered
    out, so only real ``ProjectSettings`` keys appear.
    """

    settings: list[ListedProjectSetting]


class ProjectSetParams(BaseModel):
    """The operation params of ``gda project set`` (issue #111).

    ``setting`` is the project setting's full ``section/key`` name; ``value`` is
    the CLI string value, coerced to the setting's declared Godot type by the
    operation (the same coercion rules as ``node set``, #55) before
    ``project.godot`` is saved. ``set`` edits an EXISTING setting — an unknown key
    is a clean error, never a silent create — so the declared type to coerce to is
    always known (read off the setting's current value).
    """

    setting: str = Field(
        description=(
            "The project setting's full section/key name, e.g. application/config/name."
        )
    )
    value: str = Field(
        description=(
            "The value to set, as a string. The operation coerces it to the "
            "setting's declared Godot type (see the command catalog's 'Property "
            "value coercion'). For Dictionary/Array JSON values, JSON integer "
            "literals stay int and JSON float literals stay float; typed "
            "containers assign entries through their declared container type. An "
            "uncoercible value is a clean error."
        )
    )


class ProjectSetResult(BaseModel):
    """The result of ``gda project set``: the one setting it set (issue #111).

    Echoes the ``setting`` set, the declared ``type`` the CLI value was coerced
    to, and the coerced ``value`` as JSON — the same projection ``project get``
    reports, so a ``set`` round-trips through a ``get`` without re-reading
    ``project.godot``.
    """

    setting: str
    type: str = Field(
        description="The setting's declared Godot type the value was coerced to."
    )
    value: Any = Field(
        description=(
            "The coerced value as JSON, as ProjectSettings now holds it. "
            + SET_ECHO_VALUE_DESC
        ),
        json_schema_extra=projected_value_schema_extra,
    )


class ProjectAddAutoloadParams(BaseModel):
    """The operation params of ``gda project add-autoload`` (issue #119).

    Registers an autoload singleton: ``name`` is the global accessor name (the key
    under the ``autoload/`` section of ``project.godot``); ``path`` is the res://
    path to the script or scene to autoload. The operation stores it in the
    enabled-singleton form (a leading ``*`` prefix) and saves ``project.godot``.
    The project is process context (``--project``), not an operation param
    (ADR-0006), so only ``name`` and ``path`` are inputs.
    """

    name: str = Field(
        description=(
            "The autoload singleton's global name — the accessor it is reached by "
            "and the key under the project's autoload/ section."
        )
    )
    path: NormalizedPath = Field(
        description=(
            "The res:// path to the script or scene to autoload, e.g. res://global.gd."
        )
    )


class ProjectAddAutoloadResult(BaseModel):
    """The result of ``gda project add-autoload``: the autoload it registered.

    Echoes the autoload's ``name`` and the ``path`` exactly as it was persisted to
    ``project.godot`` — the enabled-singleton form with the leading ``*`` prefix
    (e.g. ``*res://global.gd``), the same value a ``project get`` of
    ``autoload/<name>`` reads back, so an add round-trips through a get.
    """

    name: str = Field(description="The registered autoload's global name.")
    path: str = Field(
        description=(
            "The autoload value as persisted to project.godot, in enabled-singleton "
            "form with the leading * prefix (e.g. *res://global.gd)."
        )
    )


class ProjectRemoveAutoloadParams(BaseModel):
    """The operation params of ``gda project remove-autoload`` (issue #119).

    Unregisters an autoload singleton by its global ``name`` (the key under the
    ``autoload/`` section), then saves ``project.godot``. The project is process
    context (``--project``), not an operation param (ADR-0006), so only ``name``
    is an input.
    """

    name: str = Field(
        description="The global name of the autoload singleton to unregister."
    )


class ProjectRemoveAutoloadResult(BaseModel):
    """The result of ``gda project remove-autoload``: the autoload it removed.

    Echoes the ``name`` of the autoload that was unregistered, so an agent can
    confirm which singleton was removed; a subsequent ``project get`` of
    ``autoload/<name>`` reports ``unknown_setting``.
    """

    name: str = Field(description="The unregistered autoload's global name.")


# The joypad binding NAMES `--joy-button` / `--joy-axis` accept, for the help and
# schema prose. The RESOLVER's table lives in `operations.gd`, mapping each name
# to the engine's own JoyButton/JoyAxis constant (issue #842); these tuples are a
# doc-facing copy, pinned to that table by
# tests/project/test_input_action_joy_names.py, which in turn diffs it against
# the enum the engine itself dumps. The copy exists because the CLI has to
# document the accepted set without reading GDScript at import time.
JOY_BUTTON_NAMES: tuple[str, ...] = (
    "A",
    "B",
    "X",
    "Y",
    "Back",
    "Guide",
    "Start",
    "LeftStick",
    "RightStick",
    "LeftShoulder",
    "RightShoulder",
    "DPadUp",
    "DPadDown",
    "DPadLeft",
    "DPadRight",
    "Misc1",
    "Paddle1",
    "Paddle2",
    "Paddle3",
    "Paddle4",
    "Touchpad",
)

JOY_AXIS_NAMES: tuple[str, ...] = (
    "LeftX",
    "LeftY",
    "RightX",
    "RightY",
    "TriggerLeft",
    "TriggerRight",
)

JOY_BUTTON_DESC = (
    "A joypad button to bind (repeatable): a JoyButton NAME — "
    + ", ".join(JOY_BUTTON_NAMES)
    + " (case- and separator-insensitive, so DPadLeft, dpad_left and DPAD_LEFT "
    "are one button) — or a base-10 button index."
)

JOY_AXIS_DESC = (
    "A joypad axis DIRECTION to bind (repeatable), spelled <axis>[:<sign>]: a "
    "JoyAxis name — "
    + ", ".join(JOY_AXIS_NAMES)
    + " (case- and separator-insensitive) — or a base-10 axis index, with the "
    "sign + (the default) or - selecting the direction, e.g. LeftX:- for stick "
    "left. One direction is one binding."
)

DEVICE_DESC = (
    "The joypad device this call's joypad bindings match: -1 (the default) is "
    "InputMap.ALL_DEVICES and matches every joypad, 0 and up name one specific "
    "joypad. Key bindings are always -1 and are unaffected."
)


class ProjectAddInputActionParams(BaseModel):
    """The operation params of ``gda project add-input-action`` (issues #380, #842).

    Registers an InputMap action: ``name`` is the action name (the key under the
    ``input/`` section of ``project.godot``), bound to keyboard keys, joypad
    buttons and joypad axis directions — at least one binding of any kind. The
    operation builds real ``InputEventKey`` / ``InputEventJoypadButton`` /
    ``InputEventJoypadMotion`` events and persists the action via
    ``ProjectSettings`` — never a hand-built string — so the serialization is
    exactly the engine's own ``var_to_str`` form. The project is process context
    (``--project``), not an operation param (ADR-0006).
    """

    name: str = Field(
        description=(
            "The input action's name — the key under the project's input/ section "
            "and the name gda input action drives it by."
        )
    )
    keys: list[str] = Field(
        default_factory=list,
        description=(
            "The keys to bind: each item is a Godot key NAME "
            "(e.g. J, Space, Escape) or a base-10 keycode integer string."
        ),
    )
    joy_buttons: list[str] = Field(
        default_factory=list,
        description=JOY_BUTTON_DESC,
    )
    joy_axes: list[str] = Field(
        default_factory=list,
        description=JOY_AXIS_DESC,
    )
    device: int = Field(
        default=-1,
        ge=-1,
        description=DEVICE_DESC,
    )
    deadzone: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "The action's deadzone, 0..1 (the editor slider's bounds); "
            "Godot's default is 0.5."
        ),
    )
    physical: bool = Field(
        default=False,
        description=(
            "Bind physical_keycode (keyboard position, layout-independent) "
            "instead of keycode."
        ),
    )

    @model_validator(mode="after")
    def _check_at_least_one_binding(self) -> "ProjectAddInputActionParams":
        """Refuse an action that would match nothing.

        The rule spans the three binding lists, so it cannot be a ``minItems``
        on one of them: ``--key`` stopped being individually required when the
        joypad kinds landed (#842), and an action registered with an empty event
        list is a dead entry no input can ever trigger.
        """
        if not self.keys and not self.joy_buttons and not self.joy_axes:
            raise ValueError(
                "at least one binding is required: pass --key, --joy-button "
                "or --joy-axis."
            )
        return self


class InputActionKeyEvent(BaseModel):
    """One KEY binding of a registered InputMap action (issue #380).

    ``key`` echoes the raw ``--key`` token, ``keycode`` the Godot keycode it
    resolved to, and ``physical`` whether it was bound as ``physical_keycode``.
    A key event is always bound at device -1 (``InputMap.ALL_DEVICES``), so it
    carries no ``device`` of its own.
    """

    kind: Literal["key"] = Field(default="key", description="The event kind.")
    key: str = Field(description="The raw --key token as given (name or keycode).")
    keycode: int = Field(description="The Godot keycode the token resolved to.")
    physical: bool = Field(
        description="True when bound as physical_keycode instead of keycode."
    )


class InputActionJoyButtonEvent(BaseModel):
    """One joypad BUTTON binding of a registered InputMap action (issue #842).

    ``button`` echoes the raw ``--joy-button`` token, ``button_index`` the
    ``JoyButton`` value it resolved to, and ``device`` the joypad the binding
    matches (-1 = every joypad).
    """

    kind: Literal["joy_button"] = Field(
        default="joy_button", description="The event kind."
    )
    button: str = Field(
        description="The raw --joy-button token as given (name or index)."
    )
    button_index: int = Field(
        description="The Godot JoyButton value the token resolved to."
    )
    device: int = Field(
        description="The joypad device the binding matches (-1 = every joypad)."
    )


class InputActionJoyAxisEvent(BaseModel):
    """One joypad AXIS DIRECTION binding of a registered action (issue #842).

    ``axis`` echoes the raw ``--joy-axis`` token (sign included),
    ``axis_index`` the ``JoyAxis`` value it resolved to, ``axis_value`` the
    direction the sign selected (+1.0 or -1.0), and ``device`` the joypad the
    binding matches (-1 = every joypad).
    """

    kind: Literal["joy_axis"] = Field(default="joy_axis", description="The event kind.")
    axis: str = Field(description="The raw --joy-axis token as given, sign included.")
    axis_index: int = Field(
        description="The Godot JoyAxis value the token resolved to."
    )
    axis_value: float = Field(
        description="The direction the token's sign selected: +1.0 or -1.0."
    )
    device: int = Field(
        description="The joypad device the binding matches (-1 = every joypad)."
    )


# One bound event, as a DISCRIMINATED union on `kind` (#842). #380 shipped `kind`
# on the key event precisely so the joypad kinds could extend the shape without
# breaking it; making the extension a discriminated union publishes each kind's
# own field set in the schema, so a client reads what a joypad event carries from
# the contract rather than from a sample payload.
InputActionEvent = Annotated[
    Union[InputActionKeyEvent, InputActionJoyButtonEvent, InputActionJoyAxisEvent],
    Field(discriminator="kind"),
]


class ProjectAddInputActionResult(BaseModel):
    """The result of ``gda project add-input-action``: the action it registered.

    Echoes the action's ``name``, the ``deadzone`` persisted, and the resolved
    ``events`` exactly as they were bound — so an agent can confirm each token
    mapped to the intended keycode, button or axis direction without re-reading
    ``project.godot``. The events are reported (and persisted) in kind order:
    keys, then joypad buttons, then joypad axis directions.
    """

    name: str = Field(description="The registered input action's name.")
    deadzone: float = Field(description="The deadzone persisted with the action.")
    events: list[InputActionEvent] = Field(
        description=(
            "The events bound to the action: the --key ones first, then the "
            "--joy-button ones, then the --joy-axis ones, each in argv order."
        )
    )


class ProjectRemoveInputActionParams(BaseModel):
    """The operation params of ``gda project remove-input-action`` (issue #380).

    Unregisters an InputMap action by its ``name`` (the key under the ``input/``
    section), then saves ``project.godot``. The project is process context
    (``--project``), not an operation param (ADR-0006), so only ``name`` is an
    input.
    """

    name: str = Field(description="The name of the input action to unregister.")


class ProjectRemoveInputActionResult(BaseModel):
    """The result of ``gda project remove-input-action``: the action it removed.

    Echoes the ``name`` of the input action that was unregistered, so an agent
    can confirm which action was removed; a subsequent ``project get`` of
    ``input/<name>`` reports ``unknown_setting``.
    """

    name: str = Field(description="The unregistered input action's name.")


def render_project_info(info: "ProjectInfoResult") -> str:
    """Render project metadata as a small ``key: value`` block for humans."""
    main_scene = info.main_scene if info.main_scene else "(none)"
    return "\n".join(
        [
            f"name: {info.name}",
            f"main_scene: {main_scene}",
            f"viewport: {info.viewport_width}x{info.viewport_height}",
            f"engine: {info.engine_version.string}",
        ]
    )


def render_project_get(got: "ProjectGetResult") -> str:
    """Render a read setting as ``<setting> (<type>) = <value>``."""
    return f"{got.setting} ({got.type}) = {format_value(got.value)}"


def render_project_set(was_set: "ProjectSetResult") -> str:
    """Render a set setting as ``set <setting> (<type>) = <value>``."""
    return f"set {was_set.setting} ({was_set.type}) = {format_value(was_set.value)}"


def render_project_list(listed: "ProjectListResult") -> str:
    """Render enumerated settings as ``<setting> (<type>) = <value>`` lines.

    An engine-default entry is tagged ``[default]`` so customized vs default reads
    at a glance; the same ``<setting> (<type>) = <value>`` shape ``project get``
    renders. An empty listing is named explicitly rather than printing nothing.
    """
    if not listed.settings:
        return "(no settings)"
    lines = []
    for entry in listed.settings:
        default_marker = " [default]" if entry.is_default else ""
        lines.append(
            f"{entry.setting} ({entry.type}) = {format_value(entry.value)}"
            f"{default_marker}"
        )
    return "\n".join(lines)


def render_project_add_autoload(added: "ProjectAddAutoloadResult") -> str:
    """Render a registered autoload as ``added autoload <name> = <path>``."""
    return f"added autoload {added.name} = {added.path}"


def render_project_remove_autoload(removed: "ProjectRemoveAutoloadResult") -> str:
    """Render an unregistered autoload as ``removed autoload <name>``."""
    return f"removed autoload {removed.name}"


def _render_input_action_binding(event: "InputActionEvent") -> str:
    """Render one bound event as ``<token> -> <resolved>``, per kind."""
    if isinstance(event, InputActionKeyEvent):
        physical = " (physical)" if event.physical else ""
        return f"{event.key} -> {event.keycode}{physical}"
    if isinstance(event, InputActionJoyButtonEvent):
        return f"joy button {event.button} -> {event.button_index}"
    return f"joy axis {event.axis} -> {event.axis_index} ({event.axis_value})"


def render_project_add_input_action(added: "ProjectAddInputActionResult") -> str:
    """Render a registered input action with its resolved bindings.

    e.g. ``added input action jump (deadzone 0.5): J -> 74, joy button A -> 0
    [device -1]``; a physical key binding is marked ``(physical)`` after its
    keycode, and an axis direction shows the ``axis_value`` its sign selected.
    The device is stated ONCE at the end, and only when the action has a joypad
    binding: ``--device`` is a property of the call, not of a single binding, and
    it never applies to a key event.
    """
    bindings = ", ".join(_render_input_action_binding(event) for event in added.events)
    line = f"added input action {added.name} (deadzone {added.deadzone}): {bindings}"
    joypad = [
        event
        for event in added.events
        if isinstance(event, (InputActionJoyButtonEvent, InputActionJoyAxisEvent))
    ]
    if joypad:
        line += f" [device {joypad[0].device}]"
    return line


def render_project_remove_input_action(
    removed: "ProjectRemoveInputActionResult",
) -> str:
    """Render an unregistered input action as ``removed input action <name>``."""
    return f"removed input action {removed.name}"


def render_project_find_references(found: "ProjectFindReferencesResult") -> str:
    """Render find-references as ``<target>`` then one ``path (kind)`` line each."""
    if not found.references:
        return f"{found.target} (no references)"
    lines = [found.target]
    lines += [f"  {ref.path} ({ref.kind})" for ref in found.references]
    return "\n".join(lines)


def render_project_dependencies(deps: "ProjectDependenciesResult") -> str:
    """Render the dependency map as ``<scene>`` then indented ``-> <dep>`` lines."""
    if not deps.dependencies:
        return "(no scenes or resources)"
    lines = []
    for resource in deps.dependencies:
        lines.append(resource.path)
        lines += [f"  -> {dep.path} ({dep.kind})" for dep in resource.depends_on]
    return "\n".join(lines)


def render_project_find_unused_resources(
    unused: "ProjectFindUnusedResourcesResult",
) -> str:
    """Render the unreferenced resources, one path per line."""
    if not unused.unused:
        return "(no unused resources)"
    return "\n".join(unused.unused)


def render_project_statistics(stats: "ProjectStatisticsResult") -> str:
    """Render the project statistics as a human-readable summary."""
    lines = [
        f"{stats.total_files} files, {stats.total_lines} lines",
        (
            f"  scenes: {stats.scene_count}, scripts: {stats.script_count}, "
            f"resources: {stats.resource_count}"
        ),
    ]
    for ext in stats.by_extension:
        lines.append(f"  .{ext.extension}: {ext.files} files, {ext.lines} lines")
    if stats.autoloads:
        lines.append("autoloads:")
        lines += [f"  {a.name} = {a.path}" for a in stats.autoloads]
    if stats.plugins:
        lines.append("plugins:")
        lines += [f"  {p}" for p in stats.plugins]
    return "\n".join(lines)


PROJECT_INFO_COMMAND: HeadlessCommand[ProjectInfoResult] = HeadlessCommand(
    operation="project-info",
    input_model=ProjectInfoParams,
    output_model=ProjectInfoResult,
    render=render_project_info,
)

PROJECT_GET_COMMAND: HeadlessCommand[ProjectGetResult] = HeadlessCommand(
    operation="project-get",
    input_model=ProjectGetParams,
    output_model=ProjectGetResult,
    render=render_project_get,
)

PROJECT_LIST_COMMAND: HeadlessCommand[ProjectListResult] = HeadlessCommand(
    operation="project-list",
    input_model=ProjectListParams,
    output_model=ProjectListResult,
    render=render_project_list,
)

PROJECT_SET_COMMAND: HeadlessCommand[ProjectSetResult] = HeadlessCommand(
    operation="project-set",
    input_model=ProjectSetParams,
    output_model=ProjectSetResult,
    render=render_project_set,
)

PROJECT_ADD_AUTOLOAD_COMMAND: HeadlessCommand[ProjectAddAutoloadResult] = (
    HeadlessCommand(
        operation="project-add-autoload",
        input_model=ProjectAddAutoloadParams,
        output_model=ProjectAddAutoloadResult,
        render=render_project_add_autoload,
    )
)

PROJECT_REMOVE_AUTOLOAD_COMMAND: HeadlessCommand[ProjectRemoveAutoloadResult] = (
    HeadlessCommand(
        operation="project-remove-autoload",
        input_model=ProjectRemoveAutoloadParams,
        output_model=ProjectRemoveAutoloadResult,
        render=render_project_remove_autoload,
    )
)

PROJECT_ADD_INPUT_ACTION_COMMAND: HeadlessCommand[ProjectAddInputActionResult] = (
    HeadlessCommand(
        operation="project-add-input-action",
        input_model=ProjectAddInputActionParams,
        output_model=ProjectAddInputActionResult,
        render=render_project_add_input_action,
    )
)

PROJECT_REMOVE_INPUT_ACTION_COMMAND: HeadlessCommand[ProjectRemoveInputActionResult] = (
    HeadlessCommand(
        operation="project-remove-input-action",
        input_model=ProjectRemoveInputActionParams,
        output_model=ProjectRemoveInputActionResult,
        render=render_project_remove_input_action,
    )
)

PROJECT_FIND_REFERENCES_COMMAND: HeadlessCommand[ProjectFindReferencesResult] = (
    HeadlessCommand(
        operation="project-find-references",
        input_model=ProjectFindReferencesParams,
        output_model=ProjectFindReferencesResult,
        render=render_project_find_references,
    )
)

PROJECT_DEPENDENCIES_COMMAND: HeadlessCommand[ProjectDependenciesResult] = (
    HeadlessCommand(
        operation="project-dependencies",
        input_model=ProjectDependenciesParams,
        output_model=ProjectDependenciesResult,
        render=render_project_dependencies,
    )
)

PROJECT_FIND_UNUSED_RESOURCES_COMMAND: HeadlessCommand[
    ProjectFindUnusedResourcesResult
] = HeadlessCommand(
    operation="project-find-unused-resources",
    input_model=ProjectFindUnusedResourcesParams,
    output_model=ProjectFindUnusedResourcesResult,
    render=render_project_find_unused_resources,
)

PROJECT_STATISTICS_COMMAND: HeadlessCommand[ProjectStatisticsResult] = HeadlessCommand(
    operation="project-statistics",
    input_model=ProjectStatisticsParams,
    output_model=ProjectStatisticsResult,
    render=render_project_statistics,
)


# The project command group: commands acting on the Godot project as a whole.
# The project-settings read/write commands (info/get/set, issue #111) read and
# write the resolved project's project.godot / ProjectSettings headlessly. Issue
# #116 adds the read-only, project-wide static-analysis reads (find-references,
# dependencies, find-unused-resources, statistics), all backed by a single static
# project scan that parses files as text — never instantiating a scene or loading
# a script (issue #30). Every project command runs against an explicit project
# context (--project), so — like any --project op — it runs the project's
# autoloads at engine startup (#61, ADR-0009).
_app = typer.Typer(help="Act on the Godot project as a whole.", no_args_is_help=True)


@_app.command(name="info", cls=PROJECT_INFO_COMMAND.command_class())
def project_info(
    json_output: bool = json_option(),
    schema: bool = PROJECT_INFO_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report the resolved project's metadata (name, main scene, viewport, engine)."""
    dispatch_domain(
        PROJECT_INFO_COMMAND,
        ProjectInfoParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get", cls=PROJECT_GET_COMMAND.command_class())
def project_get(
    setting: str = typer.Argument(
        ...,
        help="The project setting's full section/key name (e.g. application/config/name).",
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a single project setting by section/key as typed JSON."""
    dispatch_domain(
        PROJECT_GET_COMMAND,
        ProjectGetParams(setting=setting),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="list", cls=PROJECT_LIST_COMMAND.command_class())
def project_list(
    include_defaults: bool = typer.Option(
        False,
        "--all",
        help=(
            "Also list the engine's built-in default settings, not just the "
            "project's customized ones."
        ),
    ),
    section: Optional[str] = typer.Option(
        None,
        "--section",
        help=(
            "Restrict to keys whose name begins with this section/ prefix "
            "(e.g. application/, display/)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List the project's settings keys (customized only by default; --all adds defaults)."""
    dispatch_domain(
        PROJECT_LIST_COMMAND,
        ProjectListParams(include_defaults=include_defaults, section=section),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="find-references", cls=PROJECT_FIND_REFERENCES_COMMAND.command_class()
)
def find_references(
    target: str = typer.Argument(
        ...,
        help=(
            "What to find references to: a resource's res:// path (scene, "
            "script, image, .tres, …) or a script class_name."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_FIND_REFERENCES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Find every project file that references a given resource path or class_name."""
    dispatch_domain(
        PROJECT_FIND_REFERENCES_COMMAND,
        ProjectFindReferencesParams(target=target),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="dependencies", cls=PROJECT_DEPENDENCIES_COMMAND.command_class())
def dependencies(
    json_output: bool = json_option(),
    schema: bool = PROJECT_DEPENDENCIES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Map each scene/resource in the project to the resources it references."""
    dispatch_domain(
        PROJECT_DEPENDENCIES_COMMAND,
        ProjectDependenciesParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="find-unused-resources",
    cls=PROJECT_FIND_UNUSED_RESOURCES_COMMAND.command_class(),
)
def find_unused_resources(
    json_output: bool = json_option(),
    schema: bool = PROJECT_FIND_UNUSED_RESOURCES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Find resource files that nothing references (built on the reference graph)."""
    dispatch_domain(
        PROJECT_FIND_UNUSED_RESOURCES_COMMAND,
        ProjectFindUnusedResourcesParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="set", cls=PROJECT_SET_COMMAND.command_class())
def project_set(
    setting: str = typer.Argument(
        ...,
        help="The project setting's full section/key name (e.g. application/config/name).",
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the setting's declared "
            "Godot type; an uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a project setting, coercing the value to its declared Godot type, then save."""
    dispatch_domain(
        PROJECT_SET_COMMAND,
        ProjectSetParams(setting=setting, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="add-autoload", cls=PROJECT_ADD_AUTOLOAD_COMMAND.command_class())
def project_add_autoload(
    name: str = typer.Argument(
        ..., help="The autoload singleton's global name (the autoload/<name> key)."
    ),
    path: str = typer.Argument(
        ...,
        help="The res:// path to the script or scene to autoload (e.g. res://global.gd).",
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_ADD_AUTOLOAD_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Register an autoload singleton (name → script/scene path), then save project.godot."""
    dispatch_domain(
        PROJECT_ADD_AUTOLOAD_COMMAND,
        ProjectAddAutoloadParams(name=name, path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="remove-autoload", cls=PROJECT_REMOVE_AUTOLOAD_COMMAND.command_class()
)
def project_remove_autoload(
    name: str = typer.Argument(
        ..., help="The global name of the autoload singleton to unregister."
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_REMOVE_AUTOLOAD_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unregister an autoload singleton by name, then save project.godot."""
    dispatch_domain(
        PROJECT_REMOVE_AUTOLOAD_COMMAND,
        ProjectRemoveAutoloadParams(name=name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="add-input-action", cls=PROJECT_ADD_INPUT_ACTION_COMMAND.command_class()
)
def project_add_input_action(
    name: str = typer.Argument(
        ..., help="The input action's name (the input/<name> key)."
    ),
    keys: list[str] = typer.Option(
        [],
        "--key",
        help=(
            "A key to bind (repeatable): a Godot key name "
            "(e.g. J, Space, Escape) or a base-10 keycode integer. At least one "
            "binding of any kind is required."
        ),
    ),
    joy_buttons: list[str] = typer.Option(
        [],
        "--joy-button",
        help=JOY_BUTTON_DESC,
    ),
    joy_axes: list[str] = typer.Option(
        [],
        "--joy-axis",
        help=JOY_AXIS_DESC,
    ),
    device: int = typer.Option(
        -1,
        "--device",
        help=DEVICE_DESC,
    ),
    deadzone: float = typer.Option(
        0.5,
        "--deadzone",
        help="The action's deadzone, 0..1 (Godot's default is 0.5).",
    ),
    physical: bool = typer.Option(
        False,
        "--physical",
        help=(
            "Bind physical keycodes (keyboard position, layout-independent) "
            "instead of layout keycodes."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_ADD_INPUT_ACTION_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Register an InputMap action bound to keys and/or joypad inputs, then save project.godot."""
    params = params_or_bad_parameter(
        ProjectAddInputActionParams,
        name=name,
        keys=keys,
        joy_buttons=joy_buttons,
        joy_axes=joy_axes,
        device=device,
        deadzone=deadzone,
        physical=physical,
    )
    dispatch_domain(
        PROJECT_ADD_INPUT_ACTION_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(
    name="remove-input-action", cls=PROJECT_REMOVE_INPUT_ACTION_COMMAND.command_class()
)
def project_remove_input_action(
    name: str = typer.Argument(..., help="The name of the input action to unregister."),
    json_output: bool = json_option(),
    schema: bool = PROJECT_REMOVE_INPUT_ACTION_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unregister an InputMap action by name, then save project.godot."""
    dispatch_domain(
        PROJECT_REMOVE_INPUT_ACTION_COMMAND,
        ProjectRemoveInputActionParams(name=name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="statistics", cls=PROJECT_STATISTICS_COMMAND.command_class())
def statistics(
    json_output: bool = json_option(),
    schema: bool = PROJECT_STATISTICS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report the project's file/line counts, autoloads and plugins."""
    dispatch_domain(
        PROJECT_STATISTICS_COMMAND,
        ProjectStatisticsParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``project`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="project")
