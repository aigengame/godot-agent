"""The ``game`` command group: the RUNNING game's runtime scene graph (ADR-0019).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023) and its Typer command bodies, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``, which defaults a
LIVE descriptor's classifier to the ``classify_live`` every live group shares),
the cross-command contract core (``gda.models``) and the shared render helpers
(``gda.render``) — and is imported by nothing but the composition root
(``gda.cli``).

The whole group is LIVE (``kind = LIVE``): it is served through ``gda-daemon``
against the engine session it holds, reading the runtime ``SceneTree`` after
``_ready`` rather than an on-disk ``.tscn`` — a different domain object from
``scene`` / ``node``, not a different phase (ADR-0017/0019).
"""

import json
import math
from typing import Any, Optional

import typer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gda.dispatch import dispatch_domain, params_or_bad_parameter
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.live_numbers import MAX_EXACT_JSON_INT, wire_flattens_to_zero
from gda.models import (
    NodeProperty,
    RUNTIME_NODE_DESC,
    projected_value_schema_extra,
)
from gda.render import format_value, render_node_tree, render_property_lines

# The live set-echo variant of the shared value-projection description
# (``gda.models.SET_ECHO_VALUE_DESC``): ``game set`` echoes what it OBSERVED on
# the running node after the write, not the value it coerced, so it names the
# read-back explicitly. Lives here — this group is its only consumer (ADR-0040 §5).
LIVE_SET_READ_BACK_VALUE_DESC = (
    "The observed read-back value as JSON, in the same recursive value projection "
    "that game get reports (ADR-0035)."
)


# The ``SceneNode`` the docstring contrasts with is the ``scene`` group's on-disk
# shape (``gda.commands.scene``). It is named, not imported: the two are different
# objects (ADR-0019), so there is no group dependency here.
class GameNode(BaseModel):
    """One node of the RUNNING game's runtime scene tree (Phase 2, ADR-0019).

    The runtime counterpart of :class:`SceneNode`: ``gda game tree`` reports the
    live ``SceneTree`` after ``_ready`` and dynamic instantiation, so it carries
    the runtime node ``path`` alongside ``name``/``type``/``children``. Distinct
    from the on-disk ``.tscn`` read by ``scene get`` (a different object, ADR-0019).
    """

    name: str
    type: str
    path: str
    children: list["GameNode"] = []


class GameTreeParams(BaseModel):
    """The params of ``gda game tree``: read the running game's runtime scene tree.

    Empty — it reads the whole runtime tree of the engine session held by
    ``gda-daemon`` (a subtree root may be added by a later slice).
    """


class GameTreeResult(BaseModel):
    """The result of ``gda game tree``: the running game's runtime scene tree."""

    root: GameNode


class GameGetParams(BaseModel):
    """The params of ``gda game get``: read a running node's runtime properties (#220, #422).

    The live counterpart of :class:`NodeGetParams`, addressed by the runtime
    (absolute) node path rather than a ``.tscn`` file + root-relative node path:
    there is no file, only the live SceneTree of the engine session. ``property``
    optionally narrows the read to one property. When explicitly named, a plain
    attached-script variable is addressable after storage properties are checked;
    unfiltered reads still list only the storage-property surface.
    """

    node: str = Field(description=RUNTIME_NODE_DESC)
    property: str | None = Field(
        default=None,
        description=(
            "If set, read only this one property. Explicit names first match the "
            "storage surface, then attached-script variables; unset keeps the "
            "default storage-property listing."
        ),
    )
    texture_digest: bool = Field(
        default=False,
        description=(
            "Compute the content digest for each PATH-LESS Texture2D value in "
            "this read (#666): its TextureProjection's `digest` field becomes "
            "'sha256:' + the hex digest over the image's dimensions, format, "
            "and raw bytes, so two same-class textures with different content "
            "are distinguishable. Opt-in because it needs Texture2D.get_image(), "
            "a GPU-to-CPU readback; without it the digest field stays null."
        ),
    )


class GameGetResult(BaseModel):
    """The result of ``gda game get``: a running node's runtime properties (#220, #422).

    The live counterpart of :class:`NodeGetResult` (no ``scene_path`` — there is
    no file): echoes the addressed node (runtime ``path``/``name``/``type``) and
    its storage properties, each a typed :class:`NodeProperty`; an explicitly named
    plain attached-script variable can also appear as the single returned property.
    Each value goes through the same recursive value projection the headless reads
    use (ADR-0035): compound values arrive structured; a ``res://``-pathed Resource
    is a :class:`ReferenceProjection`, a path-less ``Texture2D`` a
    :class:`TextureProjection` (#666), a whitelisted value Object
    (an ``InputEvent`` subclass) an :class:`InlineValueProjection` — while any
    other runtime Object (e.g. a live ``Node``-valued property) stays the
    ``str()`` fallback. The whitelist bounds the Object classes whose storage
    properties the inline kind emits; the texture kind is safe by construction
    (a fixed getter shape, its one expensive readback behind
    ``--texture-digest``).
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    name: str
    type: str = Field(description="The node's engine class (e.g. CharacterBody2D).")
    properties: list[NodeProperty]


class GameRectParams(BaseModel):
    """The params of ``gda game rect``: read a running Control's rendered rect (#419).

    Addressed by the same runtime (absolute) node path as ``game get``. The
    command is intentionally Control-specific: layout-dependent geometry is not
    a storage-property read and must come from ``Control.get_global_rect()`` in
    the running SceneTree.
    """

    node: str = Field(description=RUNTIME_NODE_DESC)


class GameRectResult(BaseModel):
    """The result of ``gda game rect``: a Control's rendered viewport-space rect.

    ``position`` and ``size`` are the two Vector2 projections from
    ``Control.get_global_rect()``; no Rect2 projection is added to the shared
    value projection surface.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    name: str
    type: str = Field(description="The node's engine class (e.g. VBoxContainer).")
    position: list[float] = Field(
        description="The rendered viewport-space top-left point, as [x, y]."
    )
    size: list[float] = Field(
        description="The rendered viewport-space size, as [width, height]."
    )


class GameSetParams(BaseModel):
    """The params of ``gda game set``: mutate a running node's runtime property (#220, #422).

    The live counterpart of :class:`NodeSetParams`, addressed by the runtime
    (absolute) node path. ``property`` names the property; ``value`` is the CLI
    string value, coerced to the property's declared or inferred target Godot type
    by the gda harness (the SAME coercion table headless ``node set`` uses) and
    applied at a frame boundary (ADR-0020). Explicit names first target storage
    properties, then plain attached-script variables; script-variable mutations
    are bound to the session, not persisted.
    """

    node: str = Field(description=RUNTIME_NODE_DESC)
    property: str = Field(
        description=(
            "The property to set (e.g. position, visible). Explicit names first "
            "target storage properties, then attached-script variables."
        )
    )
    value: str = Field(
        description=(
            "The value to set, as a string. The gda harness coerces it to the "
            "property's declared or inferred target Godot type (the same coercion "
            "the node group established, including JSON objects for Dictionary and "
            "JSON arrays for Array; see the command catalog's 'Property value "
            "coercion'). For Dictionary/Array JSON values, JSON integer literals "
            "stay int and JSON float literals stay float; typed containers assign "
            "entries through their declared container type. An uncoercible value "
            "is a clean error."
        )
    )


class GameSetResult(BaseModel):
    """The result of ``gda game set``: the one runtime property it set (#220).

    The live counterpart of :class:`NodeSetResult` (no ``scene_path``): echoes the
    addressed node's runtime ``path``, the ``property`` set, the declared ``type``
    the CLI value was coerced to, and the observed read-back ``value`` as JSON —
    the projection ``game get`` reports. ``verified`` reports whether that
    observed value equals the coerced value requested by this command.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    property: str
    type: str = Field(
        description="The property's declared or inferred target Godot type the value was coerced to."
    )
    value: Any = Field(
        description=(
            "The observed read-back value as JSON, as the running node now holds it. "
            + LIVE_SET_READ_BACK_VALUE_DESC
        ),
        json_schema_extra=projected_value_schema_extra,
    )
    verified: bool = Field(
        description=(
            "True when the observed read-back value equals the coerced value requested "
            "by this command; false when the live set completed but the observed "
            "read-back value differs."
        )
    )


# The NAME of the script constant an opted-in inheritance chain declares its
# gda-callable methods in (ADR-0041). The runtime authority is the harness's own
# ``GDA_CALLABLE_CONST``; this is the agent-facing copy the schema, help and
# error prose quote, and a mirror test pins the two together (PR #749 review) —
# the same cross-language idiom the op names and live error codes use.
GDA_CALLABLE_CONST = "GDA_CALLABLE"


# The live wire's number domain — the safe-integer bound and the small-float
# underflow predicate — lives in ``gda.live_numbers``, the one authority this
# group's guard, help and schema all read (#752). Re-exported by the import above
# so ``gda.commands.game.MAX_EXACT_JSON_INT`` keeps naming it.


def _game_call_params_schema(schema: dict[str, Any]) -> None:
    """Publish the recursive live-argument numeric domain (#749 third review).

    ``args`` remains ``list[Any]`` at runtime because a method may accept any JSON
    shape. Attach one recursive JSON-value definition so schema-driven callers can
    discover that structure and its wire limits.

    Standard JSON Schema has no numeric lexical types: it treats ``1e17`` and the
    equal integer value as the same mathematical integer. The Python decoder does
    retain the useful distinction — an exponent or fractional token becomes float,
    while a bare integer becomes int. Constraining the schema's ``integer`` type
    would therefore reject valid high-range binary64 float arguments. Keep the
    machine number branch broad, disclose the distinction and the live wire's
    decided float contract (``gda.live_numbers``) in its description, and let the
    same params model that accepts input enforce the int-only bound.
    """
    # `$dynamicRef` keeps the recursive definition standard Draft 2020-12 while
    # avoiding a Pydantic-internal `$ref` lookup: this definition is attached by
    # the schema projection rather than generated from a core model type.
    value_ref = {"$dynamicRef": "#liveCallArgument"}
    schema.setdefault("$defs", {})["LiveCallArgument"] = {
        "$dynamicAnchor": "liveCallArgument",
        "anyOf": [
            {"type": "null"},
            {"type": "boolean"},
            {
                "type": "number",
                "description": (
                    "An RFC JSON number transported through Godot's binary64 "
                    "parser. RFC JSON excludes NaN and Infinity; some in-memory "
                    "JSON Schema validators accept those extensions, but the params "
                    "model rejects them. JSON integer tokens decoded as int must "
                    f"stay within +/-{MAX_EXACT_JSON_INT}; standard JSON Schema "
                    "cannot distinguish those tokens from equal high-range float "
                    "values, so the params model enforces that integer-token limit "
                    "at execution. A float whose wire literal Godot's parser reads "
                    "as 0.0 is refused for the same reason (no decimal literal can "
                    "deliver it, so the call would succeed on a value you never "
                    "sent). A float it CAN read still arrives changed in its "
                    "low-order bits: 1 ULP at ordinary magnitudes, and far more "
                    "for a full-precision literal between 1e-4 and 1e-2, where "
                    "the parser truncates past 18 mantissa digits. Every float a "
                    "live reply RETURNS is exact (#752)."
                ),
            },
            {"type": "string"},
            {"type": "array", "items": value_ref},
            {"type": "object", "additionalProperties": value_ref},
        ],
    }
    args_schema = schema["properties"]["args"]
    array_schema = next(
        candidate
        for candidate in args_schema["anyOf"]
        if candidate.get("type") == "array"
    )
    array_schema["items"] = value_ref


def _reject_unrepresentable(value: Any, path: str = "args") -> None:
    """Refuse three reproduced unsafe argument classes before the wire (PR #749, #752).

    Three classes, each reproduced end to end, each refused recursively (a nested
    value is as harmful as a top-level one):

    - **Non-finite floats.** JSON has no ``NaN``/``Infinity`` literals, but
      Python's ``json.loads`` accepts them by extension and pydantic keeps them
      in an ``Any`` field — and the daemon then writes a frame the harness's
      ``JSON.parse_string`` cannot read, so the call never arrives: the caller
      waits out the 30 s relay bound, gets ``live_timeout``, and the daemon
      retires the channel, LOSING the engine session's runtime state.
    - **Python ints outside the exact-integer range** guaranteed by the live
      parser's binary64 number domain: those may arrive as a different number and
      make the call SUCCEED on a value the caller never sent (PR #749 re-review).
      Python floats already are binary64 values and do not inherit the integer
      safe-range bound; the reproduced high-range values such as ``1e300`` cross
      unchanged.
    - **Floats the engine's parser reads as** ``0.0`` (#752). Godot's
      ``built_in_strtod`` applies a power of ten it computes as a double, so an
      applied exponent of −309 or below divides by ``inf``: ``5e-324``,
      ``2.2250738585072014e-308`` (``DBL_MIN``) and even the ordinary normal
      ``1.2345678901234567e-300`` all arrive as ``0.0``, and the call SUCCEEDS on a
      number the caller never sent. Refused rather than re-spelled because no
      decimal literal at all can deliver such a value through that parser — the
      corpus behind :mod:`gda.live_numbers` establishes both facts.

    This function still does not reject every float that Godot can change: a value
    the parser CAN construct arrives changed in its low-order bits — 1 ULP at
    ordinary magnitudes, and 31 to 105 doubles away for a full-precision literal
    between 1e-4 and 1e-2, where the parser drops everything past its 18th
    mantissa digit. ``tests/live_number_corpus.py`` records a named row per band.
    That residual is disclosed rather than refused — refusing it would reject
    ordinary game values, and removing it would mean not sending a JSON number at
    all, the bespoke daemon↔harness representation ADR-0021 rejected. The result
    direction has no such residual: the harness stringifies with full precision,
    exact on every corpus value.

    The params model is the one authority both the argv and ``--params-json``
    paths pass through (ADR-0015), so all three refusals belong here —
    structurally, before the wire.
    """
    if isinstance(value, bool):
        pass  # bool is not an int argument here, despite subclassing it
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            f"{path} must be finite JSON values; NaN and Infinity are not "
            "representable on the live wire."
        )
    elif isinstance(value, float) and wire_flattens_to_zero(value):
        raise ValueError(
            f"{path} float value {value!r} cannot cross the live wire: Godot's "
            "JSON parser scales it by a power of ten it cannot hold in a double, "
            "so it would arrive as 0.0 and the call would SUCCEED on a value you "
            "never sent. No decimal spelling avoids it — the value needs fewer "
            "significant digits or a larger magnitude."
        )
    elif isinstance(value, int) and abs(value) > MAX_EXACT_JSON_INT:
        raise ValueError(
            f"{path} integer values must be within +/-{MAX_EXACT_JSON_INT} (the "
            "live wire reads JSON numbers as binary64, so a larger integer may "
            f"arrive as a DIFFERENT value); got {value}."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_unrepresentable(item, f"{path}[{key!r}]")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_unrepresentable(item, f"{path}[{index}]")


class GameCallParams(BaseModel):
    """The params of ``gda game call``: invoke one DECLARED read-only method (#673).

    The live read that ``game get`` cannot serve: a debug/state contract exposed
    as a METHOD rather than a stored property (GDA-DF-033). ``method`` must be
    named by the ``GDA_CALLABLE`` declaration resolved from the addressed node's
    attached script along its base chain (ADR-0041) — gda calls nothing the chain
    did not declare. ``args`` are JSON values passed to the method as their live
    Variant forms; the harness's JSON parser materializes every number as float.
    """

    model_config = ConfigDict(json_schema_extra=_game_call_params_schema)

    node: str = Field(description=RUNTIME_NODE_DESC)
    method: str = Field(
        min_length=1,
        description=(
            "The method to invoke. It must be named by the "
            f"`{GDA_CALLABLE_CONST}` script constant declaration resolved along the node's "
            "attached-script base chain (ADR-0041); an undeclared "
            "method is `live_method_not_allowlisted`, one the node does not have "
            "at all is `live_unknown_method`."
        ),
    )
    args: list[Any] | None = Field(
        default=None,
        description=(
            "The call's arguments as a JSON array, passed to the method as the "
            "live parser's Variant forms (JSON objects become Dictionary, arrays "
            "Array, and every number becomes float); null or omitted calls it "
            "with none. Values must be finite "
            "JSON (NaN/Infinity are refused here — they cannot cross the live "
            "wire; some in-memory validators still accept them as numbers). Finite "
            "float values are not subject to the integer safe-range bound; "
            "real-engine tests pin 1e17, 2.5e17, and 1e300 unchanged. This is not a "
            "full-range preservation guarantee. A small-magnitude float whose "
            "literal Godot's parser reads as 0.0 — 1.2345678901234567e-300, "
            "DBL_MIN, every subnormal — is REFUSED here, because no decimal "
            "spelling delivers it and the call would otherwise succeed on a value "
            "you never sent; a float the parser does read still arrives changed "
            "in its low-order bits (1 ULP at ordinary magnitudes, far more for a "
            "full-precision literal between 1e-4 and 1e-2, where the parser "
            "truncates past 18 mantissa digits), while every float a live reply "
            "RETURNS is exact (issue #752). "
            "JSON "
            f"integer tokens must stay within +/-{MAX_EXACT_JSON_INT} recursively; "
            "standard JSON Schema cannot distinguish those tokens from equal "
            "high-range float values, so the params model enforces this limit. "
            "An argument count outside "
            "the method's accepted range, or a "
            "value the declared parameter cannot take, is "
            "`live_invalid_call_args`, refused before the call."
        ),
    )

    @model_validator(mode="after")
    def _check_args(self) -> "GameCallParams":
        if self.args is not None:
            _reject_unrepresentable(self.args)
        return self


class GameCallResult(BaseModel):
    """The result of ``gda game call``: the declared method's projected return (#673).

    Echoes the addressed node (runtime ``path``/``name``/``type``) and the
    ``method`` invoked, plus its return ``value`` through the SAME recursive
    value projection every gda read uses (ADR-0035), so a returned Dictionary
    arrives structured rather than as a ``str()`` dump. A method returning
    nothing projects as null.
    """

    path: str = Field(description="The addressed node's runtime (absolute) path.")
    name: str
    type: str = Field(description="The node's engine class (e.g. Node2D).")
    method: str = Field(description="The declared method this call invoked.")
    value: Any = Field(
        description=(
            "The method's return value as JSON, in the same recursive value "
            "projection game get reports (ADR-0035); null when it returns "
            "nothing."
        ),
        json_schema_extra=projected_value_schema_extra,
    )


def render_game_tree(game: "GameTreeResult") -> str:
    """Render the running game's runtime scene tree (ADR-0019).

    The runtime counterpart of ``render_scene_tree``: ``render_node_tree`` reads
    only ``name``/``type``/``children``, which a ``GameNode`` carries, so the
    runtime tree flows through the same indented outline as the on-disk scene.
    """
    return render_node_tree(game.root)


def render_game_get(got: "GameGetResult") -> str:
    """Render a running node's runtime properties (the live `render_node_properties`).

    The runtime counterpart of ``render_node_properties``: same ``path (Type)``
    header + ``name (Type) = value`` lines, addressed by the runtime path.
    """
    return render_property_lines(got.path, got.type, got.properties)


def render_game_rect(rect: "GameRectResult") -> str:
    """Render a Control's runtime rendered rect as one viewport-space line."""
    return (
        f"{rect.path} ({rect.type}) "
        f"position={format_value(rect.position)} size={format_value(rect.size)}"
    )


def render_game_set(was_set: "GameSetResult") -> str:
    """Render a set runtime property as ``set <path>.<prop> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)} verified={format_value(was_set.verified)}"
    )


def render_game_call(called: "GameCallResult") -> str:
    """Render a declared method call as ``call <path>.<method>() -> <value>`` (#673)."""
    return f"call {called.path}.{called.method}() -> {format_value(called.value)}"


GAME_TREE_COMMAND: HeadlessCommand[GameTreeResult] = HeadlessCommand(
    operation="game-tree",
    input_model=GameTreeParams,
    output_model=GameTreeResult,
    render=render_game_tree,
    kind=ExecutionKind.LIVE,
)


GAME_GET_COMMAND: HeadlessCommand[GameGetResult] = HeadlessCommand(
    operation="game-get",
    input_model=GameGetParams,
    output_model=GameGetResult,
    render=render_game_get,
    kind=ExecutionKind.LIVE,
)


GAME_RECT_COMMAND: HeadlessCommand[GameRectResult] = HeadlessCommand(
    operation="game-rect",
    input_model=GameRectParams,
    output_model=GameRectResult,
    render=render_game_rect,
    kind=ExecutionKind.LIVE,
)


GAME_SET_COMMAND: HeadlessCommand[GameSetResult] = HeadlessCommand(
    operation="game-set",
    input_model=GameSetParams,
    output_model=GameSetResult,
    render=render_game_set,
    kind=ExecutionKind.LIVE,
)

GAME_CALL_COMMAND: HeadlessCommand[GameCallResult] = HeadlessCommand(
    operation="game-call",
    input_model=GameCallParams,
    output_model=GameCallResult,
    render=render_game_call,
    kind=ExecutionKind.LIVE,
)


# The game command group (Phase 2, ADR-0019): the RUNNING game's runtime scene
# graph, served LIVE through gda-daemon (`kind = LIVE`). `game tree` reads the
# runtime SceneTree after _ready; the on-disk counterparts stay under `scene` /
# `node`. It is a domain-object group named after the running game, not a phase
# group — the headless/live split is carried by `kind`, never by the tree.
_app = typer.Typer(
    help="Act on the running game (live; needs `gda daemon start`).",
    no_args_is_help=True,
)


@_app.command(name="tree", cls=GAME_TREE_COMMAND.command_class())
def game_tree(
    json_output: bool = json_option(),
    schema: bool = GAME_TREE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read the running game's runtime scene tree (live).

    Routes through gda-daemon to the engine session it holds (kind = LIVE,
    ADR-0017): the runtime SceneTree after _ready and dynamic instantiation,
    distinct from the on-disk .tscn read by `scene get` (ADR-0019). Live ops need
    a running daemon: with none, it reports the typed `daemon_not_running` error
    naming the remediation (`gda daemon start`); on an unsupported platform,
    `live_unsupported_platform`. The platform/Godot-version precondition is the
    structured `constraints` field of `--schema` (ADR-0021), not restated here.
    """
    dispatch_domain(
        GAME_TREE_COMMAND,
        GameTreeParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get", cls=GAME_GET_COMMAND.command_class())
def game_get(
    node: str = typer.Argument(
        ...,
        help="Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player).",
    ),
    property: Optional[str] = typer.Option(
        None,
        "--property",
        help=(
            "If set, read only this property: storage first, then an attached "
            "script variable. Without it, list only the storage surface."
        ),
    ),
    texture_digest: bool = typer.Option(
        False,
        "--texture-digest",
        help=(
            "Compute the sha256 content digest for each path-less Texture2D "
            "value in this read (a GPU-to-CPU readback; without it the "
            "TextureProjection's digest stays null)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a running node's runtime properties (live).

    The live counterpart of `node get`: routes through gda-daemon to the engine
    session's runtime SceneTree (kind = LIVE, ADR-0017), addressed by the runtime
    (absolute) node path `game tree` reports — not a `.tscn` file. With no daemon
    it reports `daemon_not_running`; a path that resolves to no running node is
    `live_node_not_found`; `--property` naming an absent property is
    `live_unknown_property`. A named plain script variable on the node's attached
    script is addressable explicitly after storage properties are checked; unfiltered
    reads keep the storage-property listing and do not dump script variables.
    A path-less Texture2D value projects as a TextureProjection ({type, width,
    height, object_string, digest}, ADR-0035 amendment #666); `--texture-digest`
    opts into its content digest.

    Float values cross the live wire at full binary64 precision — the reply is
    serialized with Godot's full-precision JSON writer, so a small or many-digit
    value reads back exactly (#752). The one residual: a NEGATIVE ZERO reads back
    as 0.0, which the engine's writer decides before gda sees the value.
    """
    dispatch_domain(
        GAME_GET_COMMAND,
        GameGetParams(node=node, property=property, texture_digest=texture_digest),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="rect", cls=GAME_RECT_COMMAND.command_class())
def game_rect(
    node: str = typer.Argument(
        ...,
        help="Runtime Control path as `game tree` reports it (absolute, e.g. /root/Main/HUD).",
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_RECT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a running Control's rendered viewport rect (live).

    Routes through gda-daemon to the engine session's runtime SceneTree
    (kind = LIVE, ADR-0017), addressed by the runtime node path `game tree`
    reports. The returned rect is Control.get_global_rect(): viewport-space
    top-left position and laid-out size. With no daemon it reports
    `daemon_not_running`; a path that resolves to no running node is
    `live_node_not_found`; a non-Control node is `live_not_control`.
    """
    dispatch_domain(
        GAME_RECT_COMMAND,
        GameRectParams(node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="set", cls=GAME_SET_COMMAND.command_class())
def game_set(
    node: str = typer.Argument(
        ...,
        help="Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player).",
    ),
    property: str = typer.Option(
        ...,
        "--property",
        help=(
            "The property to set (e.g. position, visible): storage first, then an "
            "attached script variable."
        ),
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "or inferred target Godot type (the same coercion `node set` uses, "
            "including JSON objects for Dictionary and JSON arrays for Array); "
            "an uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a running node's runtime property, coercing the value to its type (live).

    The live counterpart of `node set`: routes through gda-daemon to the engine
    session (kind = LIVE, ADR-0017), addressed by the runtime (absolute) node path.
    The gda harness coerces `--value` to the property's declared or inferred target
    Godot type — the SAME coercion table `node set` uses — and applies it at a frame
    boundary (ADR-0020); the mutation is bound to the session, not persisted to disk.
    A named plain script variable on the node's attached script is settable explicitly
    after storage properties are checked. The success result includes `verified`:
    true when the observed read-back value equals the coerced requested value,
    false when the set completed but the observed value differs (for example a
    getter-only/no-op variable or an edge-triggered variable). With no daemon it
    reports `daemon_not_running`; an absent node is `live_node_not_found`, an absent
    property `live_unknown_property`, an uncoercible input value `live_uncoercible_value`.
    """
    dispatch_domain(
        GAME_SET_COMMAND,
        GameSetParams(node=node, property=property, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="call", cls=GAME_CALL_COMMAND.command_class())
def game_call(
    node: str = typer.Argument(
        ...,
        help="Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/QA).",
    ),
    method: str = typer.Option(
        ...,
        "--method",
        help=(
            "The method to invoke. The node's attached-script base chain must "
            f"name it in its `{GDA_CALLABLE_CONST}` script constant declaration; "
            "gda calls nothing "
            "undeclared."
        ),
    ),
    args: Optional[str] = typer.Option(
        None,
        "--args",
        help=(
            "JSON array of arguments, passed as the live parser's Variant forms "
            "(every number becomes float; e.g. '[1, \"idle\"]'). Values are "
            "checked recursively: NaN and Infinity are refused; finite floats are "
            "not subject to the integer bound, but a float whose literal Godot's "
            "parser reads as 0.0 is refused too (1.2345678901234567e-300, DBL_MIN, "
            "any subnormal — no decimal spelling delivers them; #752), and a float "
            "it does read arrives changed in its low-order bits, by more than "
            "one ULP between 1e-4 and 1e-2; "
            "JSON integer values must stay within +/-"
            f"{MAX_EXACT_JSON_INT}. Omit to call with none."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_CALL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Invoke one DECLARED read-only method on a running node (live).

    The live read `game get` cannot serve: a debug or state contract the project
    exposes as a METHOD rather than a stored property (#673). The method must be
    named by the `GDA_CALLABLE` declaration resolved from the addressed node's
    attached script along its base chain — which gda reads
    STATICALLY from the script's constant map, so learning what may be called
    runs no project code (ADR-0041).

    The allowlist is NOT a trust boundary: the target project is trusted
    (ADR-0009), and gda cannot verify that a declared method has no side
    effects. The declaration records the project's own read-only assertion; what
    gda guarantees is that no UNDECLARED method is callable, keeping the live
    READ surface free of side effects gda did not ask for.

    The return value goes through the same recursive value projection every gda
    read uses (ADR-0035). Failures are distinguishable: a method the node does
    not have is `live_unknown_method`, one it has but never declared is
    `live_method_not_allowlisted` (its message names the declared set), an
    argument the declared parameters cannot take — wrong count, a value the
    parameter type cannot convert from, or a typed `Array[int]` parameter no
    JSON value can satisfy — is `live_invalid_call_args`, refused BEFORE the
    call (a `callv` the engine cannot convert for returns null, which would
    otherwise read as a successful null). An unresolvable path is
    `live_node_not_found`, and with no daemon it reports `daemon_not_running`.
    """
    # The argv value is JSON, parsed here so argv and --params-json build the
    # SAME model (ADR-0015); a non-JSON string reaches the model, which refuses
    # it structurally rather than passing prose to the harness.
    parsed: Any = None
    if args is not None:
        try:
            parsed = json.loads(args)
        except ValueError:
            parsed = args
    dispatch_domain(
        GAME_CALL_COMMAND,
        params_or_bad_parameter(GameCallParams, node=node, method=method, args=parsed),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``game`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="game")
