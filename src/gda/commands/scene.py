"""The ``scene`` command group: Godot scene files (.tscn) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023), and its Typer command bodies, and mounts them on the root app
through :func:`register`. It imports the shared machinery downward — the
dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the cross-command contract core (``gda.models``) and the shared render helpers
(``gda.render``) — and is imported by nothing but the composition root
(``gda.cli``) and its one sanctioned sibling, ``gda.commands.node`` (which
reuses ``SceneNode`` / ``derive_scene_root_name``, ADR-0040 §5).
"""

import sys
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import BaseModel, Field, model_validator

from gda import dispatch
from gda.binary import resolve_godot_binary
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import (
    Failure,
    classify_run,
    make_failure,
    unresolvable_binary_failure,
)
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import (
    CREATED_DIRS_DESC,
    NormalizedPath,
    ProjectRootedResult,
    projected_value_schema_extra,
    VALUE_PROJECTION_DESC,
)
from gda.parser import result_sentinel_start
from gda.render import (
    format_value,
    render_node_tree,
    render_script_error_location,
)
from gda.runner import LaunchFailure, LaunchFn, RunResult, launch, sentinel_args
from gda.script_errors import ScriptError, parse_script_errors


def derive_scene_root_name(path: str) -> str:
    """Derive the default scene root name from the target file name."""
    filename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if "." in filename:
        return filename.rsplit(".", 1)[0]
    return filename


class SceneCreateParams(BaseModel):
    """The operation params of ``gda scene create`` (issue #18).

    ``path`` is the target ``.tscn`` file; ``root_type`` the Godot node class
    of the new scene's root (e.g. ``Node2D``). ``root_name`` is explicit so the
    operation never silently derives a name Godot later sanitizes; when omitted,
    it is derived from the target filename without the final extension. Path
    normalization and that derivation live in the model (ADR-0015), so the argv
    and ``--params-json`` paths produce identical params.
    """

    path: NormalizedPath = Field(description="Target .tscn path to write.")
    root_type: str = Field(
        description="Godot node class of the new scene's root (e.g. Node2D)."
    )
    root_name: str | None = Field(
        default=None,
        description=(
            "Root node name to write. If omitted, it is derived from the target "
            "filename without its final extension. Must be non-empty and must not "
            "contain '.', ':', '@', '/', '\"', or '%'."
        ),
    )

    @model_validator(mode="after")
    def _default_root_name(self) -> "SceneCreateParams":
        if self.root_name is None:
            self.root_name = derive_scene_root_name(self.path)
        return self


class SceneCreateResult(BaseModel):
    """The result of ``gda scene create``: what was written where.

    Echoes the saved path and the root node the operation actually created, so
    an agent can assert the effect without a second call. ``created_dirs`` lists
    parent directories the operation created before saving, from outermost to
    innermost.
    """

    path: str
    root_name: str
    root_type: str
    created_dirs: list[str] = Field(description=CREATED_DIRS_DESC)


class SceneInstanceStatus(str, Enum):
    """Whether a statically-read instanced scene reference resolved."""

    RESOLVED = "resolved"
    MISSING = "missing"


class SceneNode(BaseModel):
    """One node of a scene's structured tree: name, type, instance marker, children.

    Recursive on purpose — the tree IS the contract: ``gda scene get`` reports
    arbitrarily nested scenes through this one shape.
    """

    name: str
    type: str = Field(
        description=(
            "Godot node class. For an instanced scene node, this is the "
            "instanced scene's root class when it can be resolved statically."
        )
    )
    instance_path: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "The referenced PackedScene path when this node is an instanced "
            "scene; null for a plain typed node."
        ),
    )
    instance_status: SceneInstanceStatus | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Whether the instanced scene reference resolved. Null for a plain "
            "typed node; 'missing' means instance_path is visible but could not "
            "be loaded as a PackedScene."
        ),
    )
    children: list["SceneNode"] = []


class SceneGetParams(BaseModel):
    """The operation params of ``gda scene get``: the ``.tscn`` file to read."""

    path: NormalizedPath = Field(description="The .tscn scene file to read.")


class SceneGetResult(BaseModel):
    """The result of ``gda scene get``: the scene file's structured node tree."""

    path: str
    root: SceneNode


class SceneExport(BaseModel):
    """One ``@export`` property a node's attached script declares (issue #58).

    ``type`` is the property's declared Godot type name (``float``, ``String``,
    ``Vector2``, …), the same spelling :class:`NodeProperty` uses. ``hint`` is the
    Godot ``PropertyHint`` enum value the ``@export`` annotation produced (e.g. a
    ``@export_range`` yields ``PROPERTY_HINT_RANGE``); ``hint_string`` is its
    companion string (the range bounds, the enum members, the file filter, …) —
    together they capture HOW the export is meant to be edited. ``value`` is the
    property's current value in the same recursive JSON value projection
    ``node get`` reports (ADR-0035), which on a freshly-instantiated node is
    the export's default.
    """

    name: str
    type: str = Field(
        description="The export's declared Godot type name (e.g. float, String, Vector2)."
    )
    hint: int = Field(
        description=(
            "The Godot PropertyHint enum value the @export annotation produced "
            "(0 = PROPERTY_HINT_NONE)."
        )
    )
    hint_string: str = Field(
        description="The PropertyHint's companion string (range bounds, enum members, …); empty when none."
    )
    value: Any = Field(
        description=(
            "The export's current value as JSON (its default on a freshly-loaded "
            "node). " + VALUE_PROJECTION_DESC
        ),
        json_schema_extra=projected_value_schema_extra,
    )


class ExportingNode(BaseModel):
    """One node of ``gda scene get-exports``: the exports its script declares (issue #58).

    A node appears only when its attached script declares at least one ``@export``
    property. ``path`` is the node's node path relative to the scene root ('.' for
    the root), the same addressing ``node get`` uses, so an agent can read or set
    any export with ``node get``/``node set``. ``script`` is the attached script's
    ``res://`` path, naming where the exports came from. ``exports`` lists them in
    declaration order.
    """

    path: str = Field(
        description=(
            "The node's node path relative to the scene root: '.' for the root "
            "itself, 'Player/Arm' for a nested node."
        )
    )
    name: str
    type: str = Field(description="The node's engine class (e.g. Node2D).")
    script: str | None = Field(
        default=None,
        description=(
            "The res:// path of the script that declares these exports, or null "
            "when the attached script has no resource path (an embedded script)."
        ),
    )
    exports: list[SceneExport]


class SceneGetExportsParams(BaseModel):
    """The operation params of ``gda scene get-exports``: the ``.tscn`` file to read (issue #58)."""

    path: NormalizedPath = Field(description="The .tscn scene file to read.")


class SceneGetExportsResult(BaseModel):
    """The result of ``gda scene get-exports``: each node's declared ``@export``s (issue #58).

    Echoes the scene ``path`` and, per node that declares them, the ``@export``
    properties its attached script exposes — name, type, hint/hint_string, and
    current value — as typed JSON. Reuses ``node get``'s property-value
    projection, so an export's ``value`` reads exactly as ``node get`` would
    report it. Nodes without an export-declaring script are omitted; a scene with
    no exported variables anywhere is a valid, empty listing (``nodes == []``).
    """

    path: str
    nodes: list[ExportingNode]


class SceneListParams(BaseModel):
    """The operation params of ``gda scene list`` — none (ADR-0004).

    ``scene list`` enumerates the ``.tscn`` scenes in the resolved project's
    ``res://`` tree; the project is process context (``--project``), not an
    operation param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ListedScene(BaseModel):
    """One enumerated scene of ``gda scene list``: its path and root summary.

    ``path`` is the scene's ``res://`` path — the address an agent feeds back
    into other scene commands. ``root_name``/``root_type`` are read cheaply from
    the scene's stored state (no instantiation, issue #30); both are null when
    the ``.tscn`` could not be loaded as a scene, so the entry still names a file
    the listing found rather than dropping it.
    """

    path: str
    root_name: str | None = Field(
        default=None,
        description="The scene root node's name, or null if the file could not be loaded as a scene.",
    )
    root_type: str | None = Field(
        default=None,
        description=(
            "The scene root node's type, resolving an inherited/instanced root "
            "to the referenced scene's root type when possible; null if the "
            "file could not be loaded as a scene."
        ),
    )
    root_instance_path: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "The referenced PackedScene path when the scene root inherits or "
            "instances another scene; null for a plain typed root or an "
            "unloadable scene."
        ),
    )
    root_instance_status: SceneInstanceStatus | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Whether the root instance reference resolved. Null for a plain "
            "typed root or an unloadable scene; 'missing' means "
            "root_instance_path is visible but could not be loaded as a "
            "PackedScene."
        ),
    )


class SceneListResult(BaseModel):
    """The result of ``gda scene list``: the project's enumerated ``.tscn`` scenes.

    An empty project is a valid, empty listing — ``scenes == []`` — not a
    failure.
    """

    scenes: list[ListedScene]


class SceneProblemKind(str, Enum):
    """What ``gda scene validate`` found wrong with a scene, per problem file (#664).

    Covers the problem classes the verdict reports: a DEPENDENCY that did not
    resolve, a BOUND SCRIPT (referenced or embedded) that could not serve its
    node, and — since the verdict became composed (#721) — two findings about the
    sub-scene graph itself: a COMPOSITION the engine would refuse to load, and the
    one entry that reports a LIMIT OF GDA rather than a defect of the project
    (``instance_depth_exceeded``). A closed, public enum projected into
    ``--schema``, so an agent branches on the kind instead of matching the message
    prose. The values are kept apart because the REMEDY differs: a missing file
    has to be restored or the reference fixed, an unloadable asset has to be
    imported, a broken script has to be edited, an incompatible script has to move
    to a matching node or change its ``extends``, a cycle has to be broken, and a
    subtree past the depth bound has to be validated on its own.
    """

    #: The referenced ``res://`` file does not exist.
    MISSING_RESOURCE = "missing_resource"
    #: The file is on disk, but no ``ResourceLoader`` can open it — typically an
    #: asset that was never imported, which a non-editor engine cannot load at all
    #: (so the running game would lose it exactly as the scene does here).
    UNLOADABLE_RESOURCE = "unloadable_resource"
    #: A script the scene binds does not compile — the same verdict ``gda script
    #: validate`` reports, reached from the scene side. Covers a referenced
    #: ``.gd`` file and an embedded ``[sub_resource type="GDScript"]``, which the
    #: dependency walk never sees (its ``path`` is the ``::id`` sub-resource form).
    SCRIPT_COMPILE_FAILED = "script_compile_failed"
    #: A script binding the engine would refuse at runtime, leaving the node
    #: script-less: a script that compiles but whose native base cannot bind the
    #: node that carries it (an ``extends Resource`` script on a ``Node2D`` — the
    #: same rule ``node script attach`` enforces, asked statically), or a value
    #: in the ``script`` slot that is not a Script at all (a plain resource
    #: declared ``type="Script"``, #709 review).
    INCOMPATIBLE_SCRIPT = "incompatible_script"
    #: A scene instances one that already instances it (#721). Godot refuses a
    #: cyclic scene inclusion, so the composition cannot load; the problem is
    #: reported against the file that declares the closing edge, and its ``path``
    #: names the ancestor being re-instanced. The walk stops at that edge, so the
    #: scenes beyond it are unreported until the cycle is broken.
    CYCLIC_INSTANCE = "cyclic_instance"
    #: The one kind that is NOT a defect in the project: gda bounds how deep it
    #: follows instanced sub-scenes (16 levels below the validated scene), and this
    #: edge is past that bound, so the scene it names and everything below it were
    #: UNCHECKED. Reported rather than skipped because a gate must not answer
    #: "sound" about what it did not look at — the verdict is ``valid: false``
    #: meaning "not established", and validating the named scene directly gives it
    #: a verdict of its own. The bound is on gda's walk only and does not make an
    #: extremely deep chain safe: the engine loads the whole chain itself and its
    #: own loader overflows past roughly a thousand levels, killing the run before
    #: any verdict, with or without this bound (#721 review).
    INSTANCE_DEPTH_EXCEEDED = "instance_depth_exceeded"


class SceneProblem(BaseModel):
    """One thing statically wrong with a scene (#664).

    Either a dependency that did not resolve, a script the scene binds that could
    not serve its node — an embedded or referenced script that does not compile,
    or one whose native base the engine would refuse to bind — a cyclic sub-scene
    composition, or a subtree the walk stopped short of (``kind`` tells them
    apart). File-centric, one entry per
    problem file rather than per reference: a path the scene declares twice is one
    broken file, and both referencing nodes appear under ``nodes``.

    Since the verdict became composed (#721) a problem is not necessarily about
    the scene that was validated: ``scene`` names the file it was found in, and
    ``path``/``nodes`` are both read against THAT file.
    """

    kind: SceneProblemKind
    scene: str = Field(
        description=(
            "The scene file this problem was found in. The validated scene itself "
            "for its own problems, or an instanced sub-scene reached from it "
            "(#721) — always present, so a composed verdict never has to be "
            "inferred. Read 'path' and 'nodes' against this file, not against the "
            "scene the command was given."
        )
    )
    path: str = Field(
        description=(
            "The path of the problem resource. For a dependency: as the "
            "[ext_resource] of the scene named by 'scene' declares it, a relative "
            "reference resolved against that scene's own directory — res:// under "
            "a project, a filesystem path for a projectless scene addressed by "
            "filesystem path. For an embedded script: the ::id sub-resource form "
            "(res://scene.tscn::GDScript_1). For 'cyclic_instance': the ancestor "
            "scene that 'scene' re-instances. For 'instance_depth_exceeded': the "
            "sub-scene below the depth bound that was not checked."
        )
    )
    type: str | None = Field(
        default=None,
        description=(
            "The class the scene DECLARED for this reference (e.g. 'Script', "
            "'Texture2D', 'PackedScene'), or null when the declaration names none. "
            "It says what was expected at the path, which a missing file cannot."
        ),
    )
    nodes: list[str] = Field(
        default_factory=list,
        description=(
            "The node paths, relative to the root of the scene named by 'scene' "
            "('.' for that root), whose properties reference this dependency — the "
            "same addressing 'node get' takes. Empty when only a sub-resource (not "
            "a node) references it."
        ),
    )
    message: str = Field(
        description="What gda found, in one line; advisory prose, never a stable code."
    )


class SceneValidateParams(BaseModel):
    """The operation params of ``gda scene validate``: the ``.tscn`` file to check (#664)."""

    path: NormalizedPath = Field(description="The .tscn scene file to validate.")


class SceneValidateResult(ProjectRootedResult):
    """The result of ``gda scene validate``: the scene's static validity verdict (#664).

    Validating an INVALID scene is a SUCCESSFUL operation — the command exits 0 and
    reports ``valid=false`` with the problems, exactly as ``script validate`` does
    for a script that does not compile. Read the verdict from this field, never from
    the process status; the process only fails for an addressing error (a missing
    file, a file that does not load as a scene at all), which refuses the whole call
    rather than becoming a verdict.

    The verdict is COMPOSED (#721): the scenes this one instances are validated
    with it, because a parent whose child is broken is broken too — and the
    parent's own dependency walk can never see that, since ``res://child.tscn``
    resolves and loads whatever is missing inside it. Every problem names the file
    it was found in (``SceneProblem.scene``). The walk is BOUNDED: 16 levels of
    sub-scenes below the validated scene, with an edge past the bound reported as
    ``instance_depth_exceeded`` instead of followed. That bound is on gda's own
    work and does not make an extremely deep chain safe — the engine loads the
    chain itself and its loader overflows past roughly a thousand levels, which
    ends the run with no verdict at all and did so before the verdict was composed.

    The verdict is STATIC: each scene is loaded but never INSTANTIATED, so none of
    the scenes' own node scripts run — no ``_init``, no ``_ready``, no frames (the
    read boundary of issue #30). It is not a claim that nothing at all executes:
    the project's autoloads start, as they do for every ``--project`` op, and
    compiling a script executes its static initializers. What it cannot speak for is
    what happens once the SCENE runs — that is ``gda scene preflight``.
    """

    path: str
    valid: bool = Field(
        description=(
            "True when every dependency resolves, every bound script (referenced "
            "or embedded) compiles, and each script's native base can bind the "
            "node that carries it — across this scene AND every sub-scene it "
            "instances. False when any does not — the command still exits 0, so "
            "read this field, not the exit code. False also when the walk could "
            "not establish the verdict at all ('cyclic_instance', "
            "'instance_depth_exceeded'): a gate must not answer 'sound' about "
            "what it did not check, so 'not established' is reported as invalid "
            "rather than as valid."
        )
    )
    problems: list[SceneProblem] = Field(
        description=(
            "One entry per problem file, depth-first from the validated scene "
            "through the sub-scenes it instances (#721): each scene's unresolved "
            "dependencies in declaration order, or — when every dependency "
            "resolves — its script-binding problems in tree order, plus an entry "
            "at any edge the walk declined to follow: 'cyclic_instance' where an "
            "edge closes an instancing cycle, 'instance_depth_exceeded' where one "
            "goes past the 16-level depth bound. Read each entry's 'scene' for "
            "the file it belongs to. Empty when the composed scene is valid."
        )
    )
    project_root: str | None = Field(
        description=(
            "The Godot project the scene's res:// dependencies were resolved "
            "against, as an absolute path (ADR-0006: --project, then $GDA_PROJECT, "
            "then the current directory). Always present; null when gda ran "
            "projectless — a projectless scene's dependency paths are then plain "
            "filesystem paths, not res:// addresses. Read it before trusting an "
            "invalid verdict: a scene checked against the wrong root reports "
            "every dependency as missing (the #658 lesson, which applies here "
            "for the same reason — each problem's path is resolved against it)."
        ),
    )

    # The key the ENGINE never sends is supplied by ProjectRootedResult above, so
    # the field can stay required in the published contract; the recipe stamps the
    # resolved project immediately after the parse.


# The DEFAULT observation window of one preflight, in idle frames. Readiness itself
# is settled before the first frame (the engine propagates it as the tree finishes
# initializing, measured against Godot 4.6.3), so the window is NOT a bound on
# coming up — it is what lets startup work that lands AFTER _ready run and print: a
# deferred call, the first _process ticks, a signal awaited on a timer. Ten frames
# cost about 65ms of a ~350ms process (measured), which buys that margin without
# making a gate noticeably slower.
DEFAULT_PREFLIGHT_FRAMES = 10

# The DEFAULT wall-clock ceiling on one preflight launch. Deliberately far below
# `script run`'s 120s: this is not an arbitrary user script but one scene coming up,
# and the ceiling IS the verdict's bound — a scene that hangs should be reported as
# hung in seconds, not minutes. Raise it for a project whose autoloads do real work
# at startup.
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 30.0


class SceneStartupStatus(str, Enum):
    """How far ``gda scene preflight`` got booting a scene (#664).

    A closed, public enum projected into ``--schema``. Two values are the engine's
    own answer and one is gda's, which is not a seam in the contract but a fact
    about where each can be known: an engine blocked inside a scene's ``_ready``
    never reaches the frame that would report anything, so only the CLI's bound can
    end it.
    """

    #: The scene instantiated, entered the tree, and the engine reported it ready
    #: within the observation window. This says the scene came up — NOT that it came
    #: up cleanly; ``diagnostics`` is the other half of that question.
    READY = "ready"
    #: The scene instantiated and entered the tree, but the engine never reported it
    #: ready. Readiness is settled before the first observed frame, so this is not
    #: "needs more time" and raising ``--frames`` will not change it: it means the
    #: propagation never reached this scene at all.
    NOT_READY = "not_ready"
    #: gda ended the launch at ``--timeout``: the engine never reported a verdict,
    #: which is what a ``_ready`` that does not return looks like from outside. The
    #: captured ``diagnostics`` are whatever the engine had already printed.
    TIMEOUT = "timeout"


class ScenePreflightParams(BaseModel):
    """The operation params of ``gda scene preflight``: the scene and its bounds (#664).

    ``path`` is the ``.tscn`` to boot. The two bounds measure different things and
    both are needed: ``frames`` is how long gda OBSERVES a scene that came up,
    counted in the engine's own idle frames, while ``timeout`` is the wall-clock
    ceiling on the whole launch — the one that answers a scene that never comes up
    at all. They are not independent, and the relationship is stated on both fields:
    frames cost wall clock, so a window that outruns the ceiling ends as a
    ``timeout`` verdict for a scene that was starting perfectly well.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to boot.")
    frames: int = Field(
        default=DEFAULT_PREFLIGHT_FRAMES,
        ge=1,
        description=(
            "How many idle frames to keep the booted scene alive before reporting. "
            "NOT a bound on coming up — readiness is settled before the first of "
            "them — but the window that lets startup work landing after _ready (a "
            "deferred call, the first _process ticks, an awaited signal) run and "
            "print its errors. Frames are the engine's own unit and not wall clock: "
            "a scene awaiting a one-second timer will not have finished waiting "
            "whatever this is set to. They do COST wall clock (a few milliseconds "
            "each), so a window large enough to outrun 'timeout' reports the timeout "
            f"verdict for a healthy scene. Defaults to {DEFAULT_PREFLIGHT_FRAMES}."
        ),
    )
    timeout: float = Field(
        default=DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
        gt=0,
        allow_inf_nan=False,
        description=(
            "How many seconds to let the launch take before gda ends it and reports "
            "the 'timeout' verdict with whatever the engine had already printed. "
            "Must be a FINITE positive number: JSON Schema cannot express "
            "finiteness, so a non-finite value is refused by validation rather than "
            "by the schema — an infinite ceiling would never be reached, and this "
            "ceiling IS the bound the timeout verdict is promised within. It must "
            "also leave room for 'frames': the two are not cross-checked, because "
            "the per-frame cost depends on the machine and on what the scene does, "
            "so a false precision here would be worse than the stated relationship. "
            f"Defaults to {DEFAULT_PREFLIGHT_TIMEOUT_SECONDS}s."
        ),
    )


class ScenePreflightResult(BaseModel):
    """The result of ``gda scene preflight``: the scene's startup verdict (#664).

    A scene that does not start is a SUCCESSFUL operation — the command exits 0 and
    reports the verdict, including the ``timeout`` one, because "it did not come up"
    is the answer this command was asked for, not a gda failure. Only what is NOT
    about the scene stays an error envelope: an unlaunchable binary, an unusable
    user-data placement, a signal death, and the op's own structured refusals (a
    missing file, a scene that cannot be instantiated at all).

    ``status`` and ``diagnostics`` answer two different questions, which is exactly
    the distinction the dogfooding note asks for (GDA-DF-030): the first says how far
    the boot got, the second what the engine complained about while it did. A scene
    can reach ``ready`` and still be broken — that is the case static validation
    misses and this command exists for — so ``started`` requires both.
    """

    path: str
    started: bool = Field(
        description=(
            "The single verdict: true only when status is 'ready' AND no script "
            "error was recognized. Derived from the two fields below, carried so a "
            "gate reads one boolean; branch on 'status' when the reason matters."
        )
    )
    status: SceneStartupStatus = Field(
        description="How far the boot got — the engine's own answer, or gda's bound."
    )
    diagnostics: list[ScriptError] = Field(
        default_factory=list,
        description=(
            "The script errors gda recognized in the engine's error stream during "
            "startup, in emission order; empty when it printed none it recognizes. "
            "Advisory and best-effort: recognition is a closed set of the engine's "
            "own failure sentences (a runtime error, a failed assertion, a script "
            "that could not be loaded), so project prose written with push_error() "
            "is NOT among them. The verbatim stream is still forwarded to gda's "
            "stderr."
        ),
    )
    project_root: str | None = Field(
        description=(
            "The Godot project the scene was booted against, as an absolute path "
            "(ADR-0006: --project, then $GDA_PROJECT, then the current directory). "
            "Always present; null when gda ran projectless — which for a preflight "
            "usually explains a failure by itself, since a scene's res:// "
            "dependencies and the project's autoloads both need the right root."
        ),
    )


class _ScenePreflightPayload(BaseModel):
    """What ``operations.gd`` reports for ``scene-preflight`` — the engine's half (#664).

    Internal, never published: the sentinel carries only what the engine can know
    (which path it booted, and how far it got), and the public
    :class:`ScenePreflightResult` is BUILT from it by adding what only gda knows —
    the script errors read off stderr and the CLI-resolved project. Parsing into
    this model rather than leniently into the public one keeps the published shape
    free of optional-key validators that exist purely for an internal parse.
    """

    path: str
    status: SceneStartupStatus


class SceneDeleteParams(BaseModel):
    """The operation params of ``gda scene delete``: the ``.tscn`` file to remove."""

    path: NormalizedPath = Field(description="The .tscn scene file to delete.")


class SceneDeleteResult(BaseModel):
    """The result of ``gda scene delete``: what was removed.

    Echoes the deleted scene's path and its root node's name/type (read from the
    scene's stored state before deletion), so the result names the content
    removed, not just the file path.
    """

    path: str
    root_name: str
    root_type: str


def render_scene_metadata(scene: "SceneCreateResult") -> str:
    """Render a created scene as ``created <path> (root <type>)``."""
    return f"created {scene.path} (root {scene.root_type})"


def render_scene_tree(scene: "SceneGetResult") -> str:
    """Render a read scene's node tree."""
    return render_node_tree(scene.root)


def render_scene_exports(scene: "SceneGetExportsResult") -> str:
    """Render a scene's per-node @export properties for humans.

    One ``path (Type)`` header per node that declares exports, then a
    ``name (Type) = value`` line per export — reusing :func:`format_value` for
    the value, the same projection ``node get`` renders. An empty listing (no
    exported variables anywhere) reads as ``(no exports)``.
    """
    if not scene.nodes:
        return "(no exports)"
    lines = []
    for node in scene.nodes:
        lines.append(f"{node.path} ({node.type})")
        for export in node.exports:
            lines.append(
                f"  {export.name} ({export.type}) = {format_value(export.value)}"
            )
    return "\n".join(lines)


def render_scene_list(listed: "SceneListResult") -> str:
    """Render the enumerated scenes as ``path (root_name: root_type)`` lines."""
    if not listed.scenes:
        return "(no scenes)"
    lines = []
    for scene in listed.scenes:
        if scene.root_name is not None and scene.root_type is not None:
            lines.append(f"{scene.path} ({scene.root_name}: {scene.root_type})")
        else:
            lines.append(f"{scene.path} (unreadable)")
    return "\n".join(lines)


def render_scene_delete(removed: "SceneDeleteResult") -> str:
    """Render a deleted scene as ``deleted <path> (root <name>: <type>)``."""
    return f"deleted {removed.path} (root {removed.root_name}: {removed.root_type})"


def render_scene_validate(validated: "SceneValidateResult") -> str:
    """Render a scene's validity verdict: the answer, then its evidence (#664).

    Conclusion first — one line an agent or a human reads without scanning. An
    INVALID verdict then leads with the project the dependencies were resolved
    against, before the problems rather than after them: when the root is the wrong
    one, every problem below it is an artefact of that single mistake and the reader
    needs the cause before the cascade (the shape ``script validate`` uses, #658).

    A problem found in an instanced SUB-scene names that file on its own line
    (#721) — otherwise a missing script inside ``child.tscn`` reads as one of
    ``parent.tscn``'s, and its ``nodes`` resolve against the wrong tree. Only when
    it differs: the ordinary single-file verdict stays as short as it was.
    """
    if validated.valid:
        return f"valid {validated.path}"
    total = len(validated.problems)
    noun = "problem" if total == 1 else "problems"
    lines = [
        f"invalid {validated.path} ({total} {noun})",
        f"  project: {validated.project_root or '(none resolved: projectless)'}",
    ]
    for problem in validated.problems:
        declared = f" ({problem.type})" if problem.type is not None else ""
        lines.append(f"  {problem.kind.value}: {problem.path}{declared}")
        if problem.scene != validated.path:
            lines.append(f"    in {problem.scene}")
        lines.append(f"    {problem.message}")
        if problem.nodes:
            lines.append(f"    nodes: {', '.join(problem.nodes)}")
    return "\n".join(lines)


SCENE_CREATE_COMMAND: HeadlessCommand[SceneCreateResult] = HeadlessCommand(
    operation="scene-create",
    input_model=SceneCreateParams,
    output_model=SceneCreateResult,
    render=render_scene_metadata,
)

SCENE_GET_COMMAND: HeadlessCommand[SceneGetResult] = HeadlessCommand(
    operation="scene-get",
    input_model=SceneGetParams,
    output_model=SceneGetResult,
    render=render_scene_tree,
)

SCENE_GET_EXPORTS_COMMAND: HeadlessCommand[SceneGetExportsResult] = HeadlessCommand(
    operation="scene-get-exports",
    input_model=SceneGetExportsParams,
    output_model=SceneGetExportsResult,
    render=render_scene_exports,
)

SCENE_LIST_COMMAND: HeadlessCommand[SceneListResult] = HeadlessCommand(
    operation="scene-list",
    input_model=SceneListParams,
    output_model=SceneListResult,
    render=render_scene_list,
)

SCENE_DELETE_COMMAND: HeadlessCommand[SceneDeleteResult] = HeadlessCommand(
    operation="scene-delete",
    input_model=SceneDeleteParams,
    output_model=SceneDeleteResult,
    render=render_scene_delete,
)


def _scene_validate_recipe(
    params: SceneValidateParams,
    *,
    project: Optional[Path],
    godot: Optional[str],
) -> "SceneValidateResult | Failure":
    """Check → report the root: ``scene validate``'s recipe (#664).

    The sentinel op still does the checking (``cmd.execute``); this wraps it in the
    one decision only the CLI can make, because ADR-0006 keeps project resolution
    CLI-side and the engine is TOLD the project through ``--path``, never asked
    about it: the resolved root is stamped onto the verdict as ``project_root``, so
    a caller reading ``valid=false`` sees which root the ``res://`` dependencies
    resolved against instead of inferring it (#658's rule, which lands here for the
    same reason — every problem this command reports is a res:// resolution
    outcome). The root is reported RESOLVED: ``--project game`` in a result tells
    the reader nothing about which directory was meant.

    ``project`` arrives ALREADY resolved from ``dispatch_recipe`` (an invalid
    ``--project``/``$GDA_PROJECT`` became a structured ``project_not_found`` before
    this runs, #353); ``None`` means projectless, which is a legitimate context here
    (a self-contained scene addressed by filesystem path), not a refusal.
    """
    root = project.expanduser().resolve() if project is not None else None
    # The runner seam is read off the module at call time — never imported by name —
    # so a test monkeypatch on ``gda.dispatch.make_runner`` still binds. Naming the
    # HEADLESS factory directly is correct only while this command is HEADLESS (the
    # same pairing note as ``script validate``'s recipe).
    outcome = SCENE_VALIDATE_COMMAND.execute(
        params,
        godot=godot,
        project=project,
        make_runner=dispatch.make_runner,
    )
    if isinstance(outcome, Failure):
        return outcome
    # A copy, not an in-place set: the classified result is the engine's answer, and
    # ``project_root`` is gda's addition to it.
    return outcome.model_copy(
        update={"project_root": str(root) if root is not None else None}
    )


def render_scene_preflight(preflight: "ScenePreflightResult") -> str:
    """Render a startup verdict: the answer, then — when it is not clean — the evidence.

    Conclusion first, and the headline distinguishes the case this command exists
    for: a scene that came up but complained on the way reads as ``ready with
    errors``, not as ``ready``. A clean start stays the one short line; the project
    only ever explains a failure, so it appears only with one (the shape ``script
    validate`` uses).
    """
    if preflight.started:
        return f"{preflight.status.value} {preflight.path}"
    # ``.get`` with the raw value as the fallback: a renderer must not be the thing
    # that kills a command, so a status added later without a phrase here degrades to
    # its own spelling instead of raising a KeyError on the presentation path.
    headline = {
        SceneStartupStatus.READY: "ready with errors",
        SceneStartupStatus.NOT_READY: "not ready",
        SceneStartupStatus.TIMEOUT: "timeout",
    }.get(preflight.status, preflight.status.value)
    lines = [
        f"{headline} {preflight.path}",
        f"  project: {preflight.project_root or '(none resolved: projectless)'}",
    ]
    for diagnostic in preflight.diagnostics:
        lines.append(
            f"  {diagnostic.kind.value}: {render_script_error_location(diagnostic)}"
        )
    return "\n".join(lines)


class _CaptureOnlyWatch:
    """``scene preflight``'s :class:`~gda.runner.LaunchWatch`: stream, never abort (#664).

    Passing a watch is what switches the launch primitive from BUFFERED capture to
    STREAMING (see :class:`gda.runner.LaunchWatch`), and streaming is what this
    channel needs: a buffered timeout DISCARDS everything the child wrote, and for a
    scene that never came up that discarded text is the entire evidence — the
    verdict would say "timeout" and carry nothing.

    It observes and never ends a run, which is deliberate rather than unfinished.
    ``script run``'s watch can end one because its caller DECLARED what finishing
    looks like (``--completion-marker``); nobody declares that for a booting scene,
    and a scene that prints an error is very often still coming up. So the only
    bound here is the caller's ``--timeout``, and what the watch buys is the capture.
    """

    def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
        return False


def run_scene_preflight_operation(
    params: ScenePreflightParams,
    *,
    godot: Optional[str],
    project: Optional[Path],
    make_launch: Optional[LaunchFn] = None,
) -> "ScenePreflightResult | Failure":
    """Boot → observe → classify: ``scene preflight``'s recipe (#664).

    Returns its outcome instead of emitting or exiting (the ``export run`` /
    ``script run`` recipe shape), so the bifurcation below has its own engine-free
    test surface.

    It dispatches an ordinary ADR-0002 sentinel op — the entry script is gda's own
    ``operations.gd``, so the engine can and does report a structured verdict — but
    it calls :func:`gda.runner.launch` directly instead of going through the runner
    seam, for ONE reason: the seam's buffered capture throws the child's output away
    at a timeout, and a scene that never came up leaves nothing else behind. The argv
    is still the shared :func:`gda.runner.sentinel_args` spelling, so the two
    channels cannot drift on how an op is dispatched.

    The outcome bifurcates by WHOSE failure it is, which is where this command
    departs from every other launch-backed channel:

    - **gda ended the run at the bound** → the ``timeout`` VERDICT, not an error
      envelope. ``launch_timeout`` is the right answer when a timeout means "gda
      could not get you an answer"; here it IS the answer — the question was whether
      this scene comes up within the bound, and it did not. The captured stderr is
      still read for diagnostics, so the verdict carries what the engine printed
      before it stopped.
    - **an environment or engine-level failure** (unlaunchable binary, unusable
      user-data placement, signal death) → the shared error envelope, because none
      of those are about the scene.
    - **the op reported a structured refusal** (missing file, not a scene, a scene
      that cannot be instantiated at all) → its registered code, classified by the
      same ``classify_run`` every sentinel command uses.
    - **the op reported a verdict** → the public result, with the script errors gda
      read off stderr (#651's parser, the single home of that reading) and the
      CLI-resolved project added to the engine's answer.
    """
    run_launch = make_launch or launch
    try:
        binary = resolve_godot_binary(godot)
    except ValueError as exc:
        # An empty ``--godot ""`` (a natural $GDA_GODOT mistake): the same
        # environment failure as a missing binary, mapped to the structured envelope
        # so it never escapes as a traceback (mirrors gda.headless.execute).
        return unresolvable_binary_failure(str(exc))

    root = project.expanduser().resolve() if project is not None else None
    raw = run_launch(
        binary,
        # The op reads `path` and `frames`; `timeout` is gda's own bound, enforced
        # by the launch primitive, so it is kept off the wire rather than shipped as
        # a field the payload would have to ignore.
        sentinel_args(
            "scene-preflight",
            params.model_dump(exclude={"timeout"}),
            project=project,
        ),
        cwd=None,
        timeout=params.timeout,
        timeout_label="Godot scene preflight",
        watch=_CaptureOnlyWatch(),
    )
    # Forward the engine's own stream, exactly as the sentinel channel does
    # (``HeadlessCommand.execute``): a preflight's stderr is where the booted scene's
    # verbatim complaints are, and this command must not be the one that swallows
    # them.
    if raw.stderr:
        print(raw.stderr, end="", file=sys.stderr)

    diagnostics = parse_script_errors(raw.stderr)
    if raw.launch_failure is LaunchFailure.TIMEOUT:
        return ScenePreflightResult(
            path=params.path,
            started=False,
            status=SceneStartupStatus.TIMEOUT,
            diagnostics=diagnostics,
            project_root=str(root) if root is not None else None,
        )
    ended_early = _ended_before_the_verdict(raw, params, diagnostics, root)
    if ended_early is not None:
        return ended_early
    outcome = classify_run(raw, binary, _ScenePreflightPayload)
    if isinstance(outcome, Failure):
        return outcome
    return ScenePreflightResult(
        path=outcome.path,
        # BOTH halves, which is the contract: the engine's readiness and gda's
        # reading of the error stream. Either one alone reports a broken scene as
        # started.
        started=outcome.status is SceneStartupStatus.READY and not diagnostics,
        status=outcome.status,
        diagnostics=diagnostics,
        project_root=str(root) if root is not None else None,
    )


# The op's readiness evidence line, mirrored from operations.gd
# (PREFLIGHT_READY_EVIDENCE) in the same way the result sentinel is mirrored into
# gda.parser: a cross-language constant each side spells once. It is NOT part of
# the ADR-0002 result sentinel — it is a single bare marker line the op prints the
# moment the scene reports ready, so the readiness fact survives a project that
# ends the run before the result can be emitted (#709 review).
_PREFLIGHT_READY_EVIDENCE = "<<<GDA:PREFLIGHT-READY>>>"


def _ended_before_the_verdict(
    raw: RunResult,
    params: ScenePreflightParams,
    diagnostics: list[ScriptError],
    root: "Path | None",
) -> "ScenePreflightResult | Failure | None":
    """The verdict for a run the PROJECT ended before the op could report (#664).

    A booting scene — or one of the autoloads that start beside it — may call
    ``get_tree().quit()``; a splash scene that hands off does exactly that. The
    engine then exits cleanly with no sentinel, and the shared classifier reads that
    as gda's own structured-output contract being violated (``contract_violation``,
    a PARSE failure). That sends the reader to debug gda for something the project
    did.

    The discriminator is exact rather than a guess, and it is worth stating why. The
    payload's single exit point (:issue:`31`) quits with an exit code that DEFAULTS
    TO FAILURE, so every way gda's own op can end without emitting — an uncaught
    error, an abandoned pending tail — exits non-zero and is classified as
    ``operation_failed`` exactly as before. A clean ``0`` with no sentinel can
    therefore only be someone else's ``quit(0)``.

    Whether gda still HAS a verdict depends on one more fact (#709 review): the op
    prints readiness as its own evidence line the moment the scene reports ready,
    ahead of the result sentinel. A quit that lands AFTER that line — a ``_ready``
    calling ``get_tree().quit()``, the splash-scene shape — ended a run whose
    startup verdict already exists, so it is reported as ``status=ready``, with
    ``started`` still combining the captured diagnostics as everywhere else. A
    quit with no evidence line means gda saw the scene neither reach ready nor
    fail to; inventing a verdict there would be the phantom success this command
    exists to prevent, so that stays an operation failure.
    """
    if raw.launch_failure is not None or raw.exit_code != 0:
        return None
    # Asked through the parser, which owns the sentinel's BEGIN/END discipline
    # (ADR-0002), rather than by testing for the marker here: a second, looser rule
    # about the same bytes could disagree with the one that actually parses them. It
    # answers "did the payload START a result", so a begun-but-unterminated sentinel
    # is NOT this case — it falls through to the parse, which rejects it as the
    # broken payload it is.
    if result_sentinel_start(raw.stdout) != -1:
        return None
    if _PREFLIGHT_READY_EVIDENCE in raw.stdout:
        return ScenePreflightResult(
            path=params.path,
            # The same two halves as the ordinary result: readiness is proven by
            # the evidence line, so only the captured diagnostics can gate it.
            started=not diagnostics,
            status=SceneStartupStatus.READY,
            diagnostics=diagnostics,
            project_root=str(root) if root is not None else None,
        )
    return make_failure(
        "operation_failed",
        "the engine exited before the preflight could report: the scene, or an "
        "autoload starting beside it, ended the run (get_tree().quit()) before the "
        "scene reported ready. gda's own payload always exits non-zero when it "
        "cannot report, so a clean exit with no result is the project's own.",
        raw.stderr,
    )


def _scene_preflight_recipe(
    params: ScenePreflightParams,
    *,
    project: Optional[Path],
    godot: Optional[str],
) -> "ScenePreflightResult | Failure":
    # ``project`` arrives ALREADY resolved by dispatch_recipe (#353). Projectless is
    # not refused here: a self-contained scene addressed by filesystem path can be
    # booted without one, and the result reports the null root so a reader can tell.
    return run_scene_preflight_operation(params, godot=godot, project=project)


# ``scene preflight`` is a sentinel op dispatched through the launch primitive
# rather than the runner seam (see the recipe): it carries a ``recipe`` (ADR-0023)
# because that dispatch, the timeout verdict, the stderr diagnostics and the
# ``project_root`` are all decided CLI-side. Its ``kind`` stays HEADLESS, which is
# what it is — a one-shot ``godot --headless`` run of gda's own payload, no daemon
# and no Engine session (ADR-0017's live channel is a different thing entirely).
SCENE_PREFLIGHT_COMMAND: HeadlessCommand[ScenePreflightResult] = HeadlessCommand(
    operation="scene-preflight",
    input_model=ScenePreflightParams,
    output_model=ScenePreflightResult,
    render=render_scene_preflight,
    recipe=_scene_preflight_recipe,
)


# ``scene validate`` stays a HEADLESS sentinel op — the engine resolves the
# dependencies — but carries a ``recipe`` (ADR-0023) because one part of its
# contract is decided at the CLI, where ADR-0006's resolved project lives: the
# ``project_root`` on the result. The recipe channel is the ONE descriptor-driven
# hook both input paths share, so argv and ``--params-json`` get the same behaviour
# (ADR-0015) without the shared dispatch tail learning anything about this command.
SCENE_VALIDATE_COMMAND: HeadlessCommand[SceneValidateResult] = HeadlessCommand(
    operation="scene-validate",
    input_model=SceneValidateParams,
    output_model=SceneValidateResult,
    render=render_scene_validate,
    recipe=_scene_validate_recipe,
)

# The first domain command group (ADR-0005): commands acting on scene files.
_app = typer.Typer(help="Act on Godot scene files (.tscn).", no_args_is_help=True)


@_app.command(cls=SCENE_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .tscn path to write."),
    root_type: str = typer.Option(
        ...,
        "--root-type",
        help="Godot node class of the new scene's root (e.g. Node2D).",
    ),
    root_name: Optional[str] = typer.Option(
        None,
        "--root-name",
        help=(
            "Root node name to write. Defaults to the target filename without "
            "its final extension."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCENE_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tscn scene file with the given root node type.

    A Control-derived root is created with zero anchors and zero offsets,
    so it does not fill the viewport. A root class with no intrinsic
    minimum size (plain Control, Panel, an empty container) renders as a
    zero-size rect at the origin; a class with an intrinsic minimum (e.g.
    Button, Label) renders at that minimum instead, still not the
    viewport. Container minimum sizes can keep descendants visible and
    mask this. Fill the viewport by setting the root's anchor_right and
    anchor_bottom to 1 with 'gda node set' (offsets stay 0); confirm with
    'gda game rect', which reports the root's rendered rect at runtime.
    """
    # Normalization + root-name derivation live in SceneCreateParams (ADR-0015),
    # so this body is a thin argv→model adapter and the --params-json path agrees.
    dispatch_domain(
        SCENE_CREATE_COMMAND,
        SceneCreateParams(path=path, root_type=root_type, root_name=root_name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(cls=SCENE_GET_COMMAND.command_class())
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a scene file and report its structured node tree."""
    dispatch_domain(
        SCENE_GET_COMMAND,
        SceneGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get-exports", cls=SCENE_GET_EXPORTS_COMMAND.command_class())
def get_exports(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_EXPORTS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List the @export properties a scene's nodes' scripts declare, per node path."""
    dispatch_domain(
        SCENE_GET_EXPORTS_COMMAND,
        SceneGetExportsParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="list", cls=SCENE_LIST_COMMAND.command_class())
def list_scenes(
    json_output: bool = json_option(),
    schema: bool = SCENE_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .tscn scenes in the resolved project."""
    dispatch_domain(
        SCENE_LIST_COMMAND,
        SceneListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="validate", cls=SCENE_VALIDATE_COMMAND.command_class())
def validate_scene(
    path: str = typer.Argument(..., help="The .tscn scene file to validate."),
    json_output: bool = json_option(),
    schema: bool = SCENE_VALIDATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Check a scene's dependencies and scripts statically; invalid exits 0 with valid=false.

    Answers what 'scene get' cannot: loading a scene survives most breakage — the
    engine substitutes null for a node's reference it could not resolve and still
    hands back a usable tree — so a scene whose script and texture are both gone
    reads as perfectly healthy. This command resolves every dependency the scene
    declares, compiles every script it binds (the referenced '.gd' files and the
    embedded GDScript sub-resources the dependency walk never sees), and checks
    each script's native base against the node that carries it, reporting one
    problem per file: 'missing_resource' (the file is gone), 'unloadable_resource'
    (it is there but no loader can open it — typically an asset that was never
    imported), 'script_compile_failed' (run 'gda script validate' on it for the
    line and message; an embedded script is named by its ::id sub-resource path) or
    'incompatible_script' (it compiles, but the engine would refuse to bind it and
    the node would run script-less). Each problem names the declared type and the
    node paths that reference it.

    COMPOSED: the scenes this one instances are checked with it, because a parent
    whose child is broken is broken too and its own walk cannot see that —
    res://child.tscn resolves and loads whatever is missing inside it. Every
    problem carries 'scene', the file it was found in, and its 'path' and 'nodes'
    are read against THAT file. The walk descends into instanced '.tscn' files
    only (a binary '.scn' carries no dependency text, as at the top level),
    reports each file once however many times it is instanced, and declines two
    kinds of edge instead of following them: 'cyclic_instance', a composition
    Godot refuses to load, and 'instance_depth_exceeded' past 16 levels of
    sub-scenes, which says the named subtree is UNCHECKED rather than sound.
    That depth bound covers gda's own walk only — the engine loads the whole
    chain regardless, and an extremely deep one overflows its loader and ends the
    run with no verdict, which no bound here changes.

    STATIC: each scene is loaded but never instantiated, so none of its own node
    scripts run — no _init, no _ready, no frames (issue #30). The project's autoloads
    still start, as they do for every --project op. It therefore says nothing about
    what happens once the scene RUNS — a scene can pass this and still fail on its
    first frame; 'gda scene preflight' is the command that boots it.

    Takes a .tscn: the dependency set is read from the scene's own text, which a
    binary .scn does not carry, so one is refused ('invalid_path') rather than
    answered about.

    An invalid scene is a SUCCESSFUL operation: exit 0 with 'valid': false. Only an
    addressing error fails — a missing file is 'path_not_found', a non-.tscn path
    'invalid_path', and 'not_a_scene' refuses a file that is not a scene document:
    no complete \\[gd_scene] header, or a header whose file then does not load as a
    scene. A scene that FAILS TO LOAD because of a dependency gda found is still a
    verdict, not a refusal: an unresolvable \\[ext_resource] referenced from a
    \\[sub_resource] (an AtlasTexture's atlas, a script-backed Resource) makes the
    whole load fail, and that is the broken dependency this command reports. The result carries 'project_root', the root the res://
    dependencies resolved against; read it before trusting an invalid verdict,
    because the wrong project reports every dependency as missing.
    """
    dispatch_recipe(
        SCENE_VALIDATE_COMMAND,
        SceneValidateParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="preflight", cls=SCENE_PREFLIGHT_COMMAND.command_class())
def preflight_scene(
    path: str = typer.Argument(..., help="The .tscn scene file to boot."),
    frames: int = typer.Option(
        DEFAULT_PREFLIGHT_FRAMES,
        "--frames",
        help=(
            "Idle frames to keep the booted scene alive before reporting, so "
            "startup work landing after _ready (a deferred call, the first _process "
            "ticks, an awaited signal) runs and prints. Not a bound on coming up: "
            "readiness is settled before the first frame. Engine frames, NOT wall "
            "clock — a scene awaiting a one-second timer will still be waiting — but "
            "they do cost a few ms each, so keep the window inside --timeout."
        ),
    ),
    timeout: float = typer.Option(
        DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
        "--timeout",
        help=(
            "Seconds before gda ends the launch and reports the 'timeout' verdict "
            "with the captured diagnostics. Raise it for a project whose autoloads "
            "do real work at startup, or for a large --frames window."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCENE_PREFLIGHT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Boot a scene headless and report how far it got: its startup verdict.

    Static checks cannot answer this. A scene whose dependencies all resolve and
    whose scripts all compile can still fail the moment it runs — 'gda scene
    validate' passing is not 'the scene works'. This command instantiates the scene,
    puts it under the tree root (which runs its _ready and the project's autoloads),
    keeps it alive for --frames idle frames, and reports 'status': 'ready',
    'not_ready' or 'timeout', plus the script errors gda recognized in the engine's
    error stream while it started. Read 'started' for the one-boolean gate: it is
    true only when the scene reached _ready AND nothing was recognized on stderr.

    A scene that does not start is a SUCCESSFUL operation — exit 0 with the verdict,
    the 'timeout' one included, because "it did not come up within the bound" is the
    answer this command was asked for. Only what is not about the scene fails: an
    unlaunchable binary, a signal death, a missing file ('path_not_found'), a file
    that does not load as a scene ('not_a_scene'), or a scene the engine cannot
    instantiate at all ('missing_dependency').

    It RUNS the project's code by construction — every script in the scene plus the
    autoloads — which stays inside gda's trusted-project assumption (ADR-0009) but
    is the widest such surface in the scene group. This is a one-shot headless
    launch, not a live session: it needs no daemon, and observes the scene coming
    up rather than driving it (that is 'gda game', behind 'gda daemon start').

    The engine's error stream is forwarded to gda's stderr, so what the scene
    complained about is visible verbatim as well as parsed into 'diagnostics'. Its
    STDOUT is not: gda's own stdout carries only the result object, so a scene's
    print() output is consumed with the rest of the engine's stdout. Use printerr()
    for anything a preflight should surface.
    """
    # The params model is the single authority for the bounds (ADR-0015): the
    # finite positive ceiling and the ≥1 frame budget are its field constraints,
    # enforced identically for --params-json — this argv body only translates a
    # model refusal into the Click usage error (#709 review).
    dispatch_recipe(
        SCENE_PREFLIGHT_COMMAND,
        params_or_bad_parameter(
            ScenePreflightParams, path=path, frames=frames, timeout=timeout
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(cls=SCENE_DELETE_COMMAND.command_class())
def delete(
    path: str = typer.Argument(..., help="The .tscn scene file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCENE_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a scene file and report what was removed."""
    dispatch_domain(
        SCENE_DELETE_COMMAND,
        SceneDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``scene`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="scene")
