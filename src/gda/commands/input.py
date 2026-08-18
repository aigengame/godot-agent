"""The ``input`` command group: runtime input simulation into the running game (#221).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023) and its Typer command bodies, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``, which defaults a
LIVE descriptor's classifier to the shared ``classify_live``) and
the cross-command contract core (``gda.models``, which keeps the multi-group
``MAX_WINDOW_FRAMES`` ceiling) — and is imported by nothing but the composition
root (``gda.cli``).

Live input injection into the RUNNING game's engine session via the gda harness
(ADR-0017, ADR-0019). Key/mouse events ride the game's real input flow via the
root viewport's push_input; actions go through Input.action_press/release. Mouse
event.position is the reliable injected coordinate; Godot does not expose a
reliable daemon-session seam for updating Viewport.get_mouse_position() /
Node2D.get_global_mouse_position(), so those tracked positions may stay stale. Every
rule that bounds a request — the modifier set, the mouse button enum, the action
strength range, and the well-formedness of a sequence event — is enforced
MODEL-SIDE (ADR-0015), so the argv path and the --params-json path reject the
same malformed request with one source of truth, before it ever reaches the
harness. Only two failures are deferred to the harness because they need the
live engine to decide: a key name the engine cannot resolve to a keycode
(live_invalid_key) and an action the running InputMap does not declare
(live_unknown_action). A sequence event whose type the harness does not
recognize is live_invalid_event_spec — the defensive arm for a request that
reached the harness without passing the model (a direct daemon caller).
"""

import json
from enum import Enum
from typing import Annotated, Literal, Optional, get_args

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
from gda.models import MAX_WINDOW_FRAMES

# The keyboard modifier names a key/sequence event may carry, mapped to the
# InputEventKey modifier flag the harness sets. Bounding the set model-side means a
# typo'd modifier ("control" for "ctrl") is a clean usage/invalid_params error, not
# a silently-dropped flag.
INPUT_MODIFIERS = ("shift", "ctrl", "alt", "meta")


class MouseButton(str, Enum):
    """The mouse button a ``gda input mouse-click`` targets (#221).

    The CLI-facing names map to Godot's ``MOUSE_BUTTON_*`` indices harness-side;
    bounding them as an enum makes an unknown button a usage/invalid_params error
    rather than a silently-ignored value.
    """

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


def _validate_modifiers(modifiers: list[str]) -> list[str]:
    """Reject any modifier outside the known set (the single home of the rule).

    Shared by ``InputKeyParams`` and a sequence key event so the argv and
    ``--params-json`` paths — and a sequence event nested in a JSON object —
    validate modifiers identically (ADR-0015).
    """
    unknown = [m for m in modifiers if m not in INPUT_MODIFIERS]
    if unknown:
        raise ValueError(
            f"unknown modifier(s) {unknown}; allowed: {list(INPUT_MODIFIERS)}."
        )
    return modifiers


class InputKeyParams(BaseModel):
    """The params of ``gda input key``: inject one key event (#221).

    Pushes an ``InputEventKey`` for ``key`` (with any ``modifiers``) into the
    running game's root viewport, so it rides the game's real input flow. ``key``
    is a Godot key name (e.g. ``Right``, ``A``, ``Space``, ``Escape``) the harness
    resolves with ``OS.find_keycode_from_string``; an unresolvable name is the
    typed ``live_invalid_key`` error. By default the event is a press; ``released``
    makes it a release. The modifier set is bounded model-side (ADR-0015).
    """

    key: str = Field(
        min_length=1,
        description="A Godot key name to inject (e.g. Right, A, Space, Escape).",
    )
    modifiers: list[str] = Field(
        default_factory=list,
        description=(
            "Modifier keys held with the key, any of: shift, ctrl, alt, meta."
        ),
    )
    released: bool = Field(
        default=False,
        description="Inject a key RELEASE instead of a press (default: press).",
    )

    @model_validator(mode="after")
    def _check_modifiers(self) -> "InputKeyParams":
        _validate_modifiers(self.modifiers)
        return self


class InputKeyResult(BaseModel):
    """The result of ``gda input key``: the key event the harness injected (#221).

    Echoes the resolved ``keycode`` (so an agent can confirm the name mapped as
    intended), the ``key`` name, the ``modifiers`` applied, and whether it was a
    ``pressed`` event — the live counterpart's confirmation that the event was
    pushed at a frame boundary (ADR-0020).
    """

    kind: str = Field(default="key", description="The injected event kind ('key').")
    key: str = Field(description="The key name that was injected.")
    keycode: int = Field(description="The Godot keycode the name resolved to.")
    modifiers: list[str] = Field(
        default_factory=list, description="The modifier keys held with the key."
    )
    pressed: bool = Field(description="True for a press event, false for a release.")


class InputMouseClickParams(BaseModel):
    """The params of ``gda input mouse-click``: inject a mouse button click (#221).

    Pushes an ``InputEventMouseButton`` at viewport position ``(x, y)`` into the
    running game's root viewport. ``button`` selects which button (left/right/
    middle); ``double`` marks the event a double click. A single-frame op (the
    press is injected at one frame boundary, ADR-0020). The injected coordinate is
    reliable as ``InputEventMouseButton.position``. Godot does not reliably update
    the engine-tracked mouse position in daemon sessions, so
    ``Viewport.get_mouse_position()`` / ``Node2D.get_global_mouse_position()`` may
    remain stale; read the mouse event position for the injected coordinate.
    """

    x: float = Field(
        description=(
            "The click's x position in the viewport. Read it from the mouse event; "
            "engine-tracked mouse positions may remain stale."
        )
    )
    y: float = Field(
        description=(
            "The click's y position in the viewport. Read it from the mouse event; "
            "engine-tracked mouse positions may remain stale."
        )
    )
    button: MouseButton = Field(
        default=MouseButton.LEFT,
        description="Which mouse button to click: left, right, or middle.",
    )
    double: bool = Field(default=False, description="Mark the event a double click.")


class InputMouseMoveParams(BaseModel):
    """The params of ``gda input mouse-move``: inject a mouse motion event (#221).

    Pushes an ``InputEventMouseMotion`` to viewport position ``(x, y)`` into the
    running game's root viewport — the runtime counterpart of moving the cursor
    over the game. A single-frame op. The injected coordinate is reliable as
    ``InputEventMouseMotion.position``. Godot does not reliably update the
    engine-tracked mouse position in daemon sessions, so
    ``Viewport.get_mouse_position()`` / ``Node2D.get_global_mouse_position()`` may
    remain stale; read the mouse event position for the injected coordinate.
    """

    x: float = Field(
        description=(
            "The motion's target x position in the viewport. Read it from the "
            "mouse event; engine-tracked mouse positions may remain stale."
        )
    )
    y: float = Field(
        description=(
            "The motion's target y position in the viewport. Read it from the "
            "mouse event; engine-tracked mouse positions may remain stale."
        )
    )


class InputMouseResult(BaseModel):
    """The result of a ``gda input mouse-click`` / ``mouse-move`` op: the mouse event injected (#221).

    Echoes the event ``kind`` (``mouse_click`` or ``mouse_move``), the viewport
    ``position`` it was pushed at as ``[x, y]``, and — for a click — the ``button``
    and whether it was a ``double`` click (both null for a move). This echoed
    position mirrors the mouse event's position; engine-tracked mouse positions may
    remain stale.
    """

    kind: str = Field(
        description="The injected event kind: 'mouse_click' or 'mouse_move'."
    )
    position: list[float] = Field(
        description=(
            "The viewport position the event was injected at, as [x, y]. This "
            "mirrors event.position; engine-tracked mouse positions may remain stale."
        )
    )
    button: str | None = Field(
        default=None, description="The clicked button (a click only); null for a move."
    )
    double: bool | None = Field(
        default=None,
        description="Whether the click was a double click; null for a move.",
    )


class InputActionParams(BaseModel):
    """The params of ``gda input action``: press or release an input action (#221).

    Drives ``Input.action_press`` / ``Input.action_release`` for the named action,
    so the running game observes it through its ``InputMap`` exactly as a real
    binding would fire. ``action`` MUST be declared in the running ``InputMap`` —
    an unknown action is the typed ``live_unknown_action`` error (validated
    harness-side via ``InputMap.has_action``). By default the action is pressed;
    ``release`` releases it instead. ``strength`` is the analog strength of a press,
    0..1; it is ignored on a release.
    """

    action: str = Field(
        min_length=1, description="The input action name (must be in the InputMap)."
    )
    release: bool = Field(
        default=False, description="Release the action instead of pressing it."
    )
    strength: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="The analog press strength, 0..1 (ignored on a release).",
    )


class InputActionResult(BaseModel):
    """The result of ``gda input action``: the action event the harness applied (#221).

    Echoes the ``action`` driven, whether it was a ``pressed`` event, and the
    ``strength`` applied (the press strength; 0.0 on a release) — confirmation the
    action fired against the running ``InputMap`` at a frame boundary (ADR-0020).
    """

    kind: str = Field(
        default="action", description="The injected event kind ('action')."
    )
    action: str = Field(description="The action name that was driven.")
    pressed: bool = Field(description="True for a press, false for a release.")
    strength: float = Field(
        description="The press strength applied (0.0 on a release)."
    )


# The event types a `gda input sequence` may carry. A sequence event reuses the
# single-frame ops' shapes (key / mouse click / mouse move / action), plus a
# sequence-only mouse-button phase for press-drag-release gestures, and either a
# process-clock `frame` offset (the original #221 behavior) or a physics-clock
# `physics_frame` offset (#391). Bounding the type model-side keeps an unknown type
# a usage/invalid_params error rather than a request the harness must defend
# against (it still does, as live_invalid_event_spec).
class InputEventType(str, Enum):
    """The kind of one event in a ``gda input sequence`` (#221)."""

    KEY = "key"
    MOUSE_CLICK = "mouse_click"
    MOUSE_BUTTON = "mouse_button"
    MOUSE_MOVE = "mouse_move"
    ACTION = "action"


# The press/release synonyms a sequence event may spell its phase with. Each kind
# uses exactly the one its single-frame op uses (`released` for a key, `release`
# for an action, `pressed`/`release` for the sequence-only mouse-button phase),
# and the flat shape they used to share made a foreign one silently inert — a
# `release` on a key event PRESSED the key. Declared once here so the rejection
# can NAME the kind's own spelling instead of only refusing the wrong one; which
# kind uses which is read off the variant models themselves, never restated.
_PHASE_FIELDS = ("pressed", "released", "release")

# The shared field descriptions, written once for the whole union: each variant
# repeats only the fields it accepts, and the manifest repeats every variant per
# command, so a per-class copy would multiply the same sentence.
_FRAME_DESC = (
    "The 0-based relative harness/process-frame offset to apply this event at. "
    "This is the original `input sequence` clock, driven by the harness "
    "`_process` loop; it is not Godot's fixed physics clock. Omit both `frame` "
    "and `physics_frame` to use process frame 0."
)
_PHYSICS_FRAME_DESC = (
    "The 0-based relative physics-frame offset to apply this event at, driven by "
    "Godot `_physics_process` ticks. Use this instead of `frame` when an input "
    "hold must map to a deterministic physics simulation duration."
)
_MOUSE_X_DESC = (
    "The event's x position in the viewport. Read it from the event; "
    "engine-tracked mouse positions may remain stale."
)
_MOUSE_Y_DESC = (
    "The event's y position in the viewport. Read it from the event; "
    "engine-tracked mouse positions may remain stale."
)


def _event_kind(model: type[BaseModel]) -> str:
    """The ``type`` value that selects ``model`` from the union.

    Read off the variant's own ``Literal`` discriminator annotation, so the kind
    name has ONE source — the class that declares it — and a new variant needs no
    entry anywhere else.
    """
    members = get_args(model.model_fields["type"].annotation)
    return str(members[0].value) if members else ""


def _kinds_accepting(field: str, exclude: type[BaseModel]) -> list[str]:
    """The other event kinds that DO accept ``field`` (derived from the union)."""
    return [
        _event_kind(model)
        for model in SEQUENCE_EVENT_MODELS
        if model is not exclude and field in model.model_fields
    ]


def _foreign_field_message(model: type[BaseModel], field: str) -> str:
    """Explain a field that belongs to another event kind, naming what to use here.

    The rejection itself is not the gap — a foreign field was already refused —
    the gap is that refusing ``pressed`` on an action event never mentioned
    ``release`` (dogfooding GDA-DF-037). Every part of the sentence is derived
    from the variant models, so it cannot drift from what they accept.
    """
    kind = _event_kind(model)
    # "an 'action' event", not "a 'action' event": the kind names come from the
    # union, so the article is computed rather than written into a sentence.
    article = "an" if kind[:1] in "aeiou" else "a"
    if field in _PHASE_FIELDS:
        own = [name for name in _PHASE_FIELDS if name in model.model_fields]
        advice = (
            f"{article} {kind!r} event spells its press/release phase "
            + " or ".join(repr(name) for name in own)
            if own
            else f"{article} {kind!r} event has no press/release phase"
        )
    else:
        accepted = ", ".join(repr(name) for name in model.model_fields)
        advice = f"{article} {kind!r} event accepts {accepted}"
    elsewhere = _kinds_accepting(field, model)
    seen = f"; {field!r} is accepted on: {', '.join(elsewhere)}" if elsewhere else ""
    return (
        f"{field!r} is not valid on {article} {kind!r} sequence event: {advice}{seen}."
    )


class _SequenceEvent(BaseModel):
    """The clock half every ``gda input sequence`` event shares (#221, #391).

    The union's base: it owns the two relative-offset fields and the one-clock
    rule, so each kind below declares only the fields it actually accepts. That
    is what makes the emitted contract machine-checkable — a kind's variant
    schema lists exactly its required fields and forbids the rest — where one
    flat shape could only describe the per-kind rules in prose (GDA-DF-037).
    """

    model_config = ConfigDict(extra="forbid")

    frame: int | None = Field(default=None, ge=0, description=_FRAME_DESC)
    physics_frame: int | None = Field(
        default=None, ge=0, description=_PHYSICS_FRAME_DESC
    )

    @model_validator(mode="before")
    @classmethod
    def _explain_foreign_fields(cls, data: object) -> object:
        # Runs BEFORE pydantic's own extra="forbid" refusal, which reports only
        # "Extra inputs are not permitted" and so leaves the caller to guess this
        # kind's spelling. Non-dict input (an already-built model) passes through.
        if not isinstance(data, dict):
            return data
        foreign = [key for key in data if key not in cls.model_fields]
        if foreign:
            raise ValueError(
                " ".join(_foreign_field_message(cls, key) for key in foreign)
            )
        return data

    @model_validator(mode="after")
    def _check_clock(self) -> "_SequenceEvent":
        # Each event uses exactly one clock. No supplied clock keeps the original
        # shorthand: process frame 0. Enforced model-side (ADR-0015) so argv JSON
        # and --params-json reject the same malformed event before the harness.
        if self.frame is not None and self.physics_frame is not None:
            raise ValueError(
                "a sequence event cannot set both 'frame' and 'physics_frame'."
            )
        if self.frame is None and self.physics_frame is None:
            self.frame = 0
        return self


class KeySequenceEvent(_SequenceEvent):
    """A key event in a sequence: the ``gda input key`` shape at a clock offset.

    Pushes an ``InputEventKey`` for ``key`` (with any ``modifiers``) into the
    running game's root viewport. It presses by default and releases with
    ``released`` — the action kind's ``release`` is NOT accepted here.
    """

    type: Literal[InputEventType.KEY] = Field(description="The event kind.")
    key: str = Field(min_length=1, description="The key name to inject (e.g. Right).")
    modifiers: list[str] = Field(
        default_factory=list,
        description="Modifier keys held with the key, any of: shift, ctrl, alt, meta.",
    )
    released: bool = Field(
        default=False, description="Inject a key RELEASE instead of a press."
    )

    @model_validator(mode="after")
    def _check_modifiers(self) -> "KeySequenceEvent":
        _validate_modifiers(self.modifiers)
        return self


class MouseClickSequenceEvent(_SequenceEvent):
    """A whole mouse click in a sequence: press and release at one clock offset.

    Use :class:`MouseButtonSequenceEvent` instead when the press and the release
    must sit at different offsets (a drag).
    """

    type: Literal[InputEventType.MOUSE_CLICK] = Field(description="The event kind.")
    x: float = Field(description=_MOUSE_X_DESC)
    y: float = Field(description=_MOUSE_Y_DESC)
    button: MouseButton = Field(
        default=MouseButton.LEFT, description="Which button: left, right, or middle."
    )
    double: bool = Field(default=False, description="Mark the event a double click.")


class MouseButtonSequenceEvent(_SequenceEvent):
    """One PHASE of a mouse button in a sequence: the press or the release alone.

    The sequence-only kind, for press-drag-release gestures: it carries the held
    button mask onto the motion events in between. It is the ONE kind that spells
    a phase with ``pressed``; exactly one of ``pressed: true`` / ``release: true``
    is required.
    """

    type: Literal[InputEventType.MOUSE_BUTTON] = Field(description="The event kind.")
    x: float = Field(description=_MOUSE_X_DESC)
    y: float = Field(description=_MOUSE_Y_DESC)
    button: MouseButton = Field(
        default=MouseButton.LEFT, description="Which button: left, right, or middle."
    )
    double: bool = Field(default=False, description="Mark the event a double click.")
    pressed: bool | None = Field(
        default=None,
        description="Press the button. Use exactly one of `pressed` or `release`.",
    )
    release: bool = Field(
        default=False,
        description="Release the button. Use exactly one of `pressed` or `release`.",
    )

    @model_validator(mode="after")
    def _check_phase(self) -> "MouseButtonSequenceEvent":
        if self.pressed is None and not self.release:
            raise ValueError(
                "a 'mouse_button' sequence event requires 'pressed' or 'release'."
            )
        if self.pressed is False:
            raise ValueError(
                "a 'mouse_button' sequence event uses 'pressed: true' to press; "
                "use 'release: true' to release."
            )
        if self.pressed is True and self.release:
            raise ValueError(
                "a 'mouse_button' sequence event cannot set both 'pressed' and "
                "'release'."
            )
        if self.release:
            self.pressed = False
        return self


class MouseMoveSequenceEvent(_SequenceEvent):
    """A mouse motion event in a sequence: the ``gda input mouse-move`` shape."""

    type: Literal[InputEventType.MOUSE_MOVE] = Field(description="The event kind.")
    x: float = Field(description=_MOUSE_X_DESC)
    y: float = Field(description=_MOUSE_Y_DESC)


class ActionSequenceEvent(_SequenceEvent):
    """An input action in a sequence: the ``gda input action`` shape.

    Drives ``Input.action_press`` / ``action_release`` for ``action``, which must
    be declared in the running ``InputMap``. It presses by default and releases
    with ``release`` — the mouse-button kind's ``pressed`` is NOT accepted here,
    so a hold is a press event and a later ``release: true`` event.
    """

    type: Literal[InputEventType.ACTION] = Field(description="The event kind.")
    action: str = Field(
        min_length=1, description="The action name (must be in the InputMap)."
    )
    release: bool = Field(
        default=False, description="Release the action instead of pressing it."
    )
    strength: float = Field(
        default=1.0, ge=0.0, le=1.0, description="The analog press strength, 0..1."
    )


# The union's members, in the order they appear in the emitted `oneOf`. Also the
# one place the per-kind rejection reads which kinds accept a given field, so the
# message and the contract come from the same declarations.
SEQUENCE_EVENT_MODELS: tuple[type[_SequenceEvent], ...] = (
    KeySequenceEvent,
    MouseClickSequenceEvent,
    MouseButtonSequenceEvent,
    MouseMoveSequenceEvent,
    ActionSequenceEvent,
)

# One event of a `gda input sequence`, as a DISCRIMINATED union on `type` (#669).
# The emitted schema is a `oneOf` with a `type` discriminator mapping, so each
# kind's required and forbidden fields are machine-checkable: a client validates a
# candidate event against the published contract instead of learning the per-kind
# rules from prose or from a failed invocation (GDA-DF-037/GDA-DF-032).
InputSequenceEvent = Annotated[
    KeySequenceEvent
    | MouseClickSequenceEvent
    | MouseButtonSequenceEvent
    | MouseMoveSequenceEvent
    | ActionSequenceEvent,
    Field(discriminator="type"),
]


class InputSequenceParams(BaseModel):
    """The params of ``gda input sequence``: inject events across process or physics frames.

    A multi-frame op (the time-windowed harness base, #223): ``events`` is a list of
    :class:`InputSequenceEvent`, each applied at either its relative ``frame`` index
    (the original harness/process-frame clock) or its relative ``physics_frame``
    index (the explicit Godot physics clock added for #391), and the whole sequence
    returns as ONE blocking result (ADR-0017 one-shot RPC). A sequence must use one
    clock throughout; mixing ``frame`` and ``physics_frame`` in the same request is
    rejected. The window runs for as many selected-clock frames as the largest event
    offset requires (at least one). ``events`` must be non-empty; each event is
    validated model-side (ADR-0015).

    The window the sequence requests — ``max(offset) + 1`` frames on the selected
    clock — is bounded model-side to ``MAX_WINDOW_FRAMES`` (#223). The time-windowed
    harness base has no harness-side timeout (it relies on its driver's model
    bounds, as ``PerfMonitorParams`` enforces via ``frames``), so an unbounded event
    offset would let a single valid request monopolise the serialised live session
    until ``live_timeout``. Rejecting it here makes it a structured
    ``invalid_params`` on ``--params-json`` and a usage error (exit 2) on argv, never
    a live stall (ADR-0015).
    """

    events: list[InputSequenceEvent] = Field(
        min_length=1,
        description=(
            "The events to inject, each at its relative process-clock `frame` "
            "offset or physics-clock `physics_frame` offset."
        ),
    )

    @model_validator(mode="after")
    def _check_window(self) -> "InputSequenceParams":
        # The window spans one past the largest event offset on exactly one clock
        # (mirrors the harness's `max_offset + 1`). Bounding it to MAX_WINDOW_FRAMES
        # — the same per-window ceiling perf enforces — keeps a sequence from
        # holding the single-writer live session for an unbounded number of frames.
        uses_physics = [event.physics_frame is not None for event in self.events]
        if any(uses_physics) and not all(uses_physics):
            raise ValueError(
                "a sequence cannot mix process-clock 'frame' events with "
                "physics-clock 'physics_frame' events."
            )
        selected_clock = "physics_frame" if all(uses_physics) else "frame"
        window = (
            max(
                (
                    event.physics_frame
                    if selected_clock == "physics_frame"
                    else event.frame
                )
                or 0
                for event in self.events
            )
            + 1
        )
        if window > MAX_WINDOW_FRAMES:
            raise ValueError(
                f"the sequence requests a {window}-frame window (one past its "
                f"largest {selected_clock} offset), exceeding the maximum of "
                f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). "
                "Use smaller relative offsets."
            )
        return self


class InputSequenceResult(BaseModel):
    """The result of ``gda input sequence``: what the harness injected (#221).

    Echoes the ``clock`` used (``process`` for the original harness/process-frame
    clock, ``physics`` for the explicit Godot physics clock), the number of
    ``events`` applied, and the number of ``frames`` the window spanned on that
    clock (one past the largest selected offset), confirming the whole sequence was
    injected over the window at frame boundaries (ADR-0020).
    """

    kind: str = Field(default="sequence", description="The op kind ('sequence').")
    clock: str = Field(
        default="process",
        description=(
            "The sequence clock: 'process' for harness/process-frame offsets, or "
            "'physics' for Godot physics-frame offsets."
        ),
    )
    events: int = Field(description="The number of events injected.")
    frames: int = Field(
        description="The number of selected-clock frames the window spanned."
    )


def render_input_key(injected: "InputKeyResult") -> str:
    """Render an injected key event as ``key <name> [+ mods] <pressed|released>`` (#221)."""
    mods = ("+" + "+".join(injected.modifiers)) if injected.modifiers else ""
    state = "pressed" if injected.pressed else "released"
    return f"key {injected.key}{mods} {state} (keycode {injected.keycode})"


def render_input_mouse(injected: "InputMouseResult") -> str:
    """Render an injected mouse event as a click or a move at its position (#221)."""
    x, y = injected.position
    if injected.kind == "mouse_click":
        double = " double" if injected.double else ""
        return f"{injected.button} click{double} at ({x}, {y})"
    return f"mouse move to ({x}, {y})"


def render_input_action(injected: "InputActionResult") -> str:
    """Render an injected action event as ``action <name> <pressed|released>`` (#221)."""
    if injected.pressed:
        return f"action {injected.action} pressed (strength {injected.strength})"
    return f"action {injected.action} released"


def render_input_sequence(injected: "InputSequenceResult") -> str:
    """Render an injected sequence as ``sequence: N events over M frames`` (#221)."""
    return f"sequence: {injected.events} events over {injected.frames} frames"


INPUT_KEY_COMMAND: HeadlessCommand[InputKeyResult] = HeadlessCommand(
    operation="input-key",
    input_model=InputKeyParams,
    output_model=InputKeyResult,
    render=render_input_key,
    kind=ExecutionKind.LIVE,
)


INPUT_MOUSE_CLICK_COMMAND: HeadlessCommand[InputMouseResult] = HeadlessCommand(
    operation="input-mouse-click",
    input_model=InputMouseClickParams,
    output_model=InputMouseResult,
    render=render_input_mouse,
    kind=ExecutionKind.LIVE,
)


INPUT_MOUSE_MOVE_COMMAND: HeadlessCommand[InputMouseResult] = HeadlessCommand(
    operation="input-mouse-move",
    input_model=InputMouseMoveParams,
    output_model=InputMouseResult,
    render=render_input_mouse,
    kind=ExecutionKind.LIVE,
)


INPUT_ACTION_COMMAND: HeadlessCommand[InputActionResult] = HeadlessCommand(
    operation="input-action",
    input_model=InputActionParams,
    output_model=InputActionResult,
    render=render_input_action,
    kind=ExecutionKind.LIVE,
)


INPUT_SEQUENCE_COMMAND: HeadlessCommand[InputSequenceResult] = HeadlessCommand(
    operation="input-sequence",
    input_model=InputSequenceParams,
    output_model=InputSequenceResult,
    render=render_input_sequence,
    kind=ExecutionKind.LIVE,
)


# The input command group (Phase 2, ADR-0019, #221): runtime input simulation into
# the RUNNING game, served LIVE through gda-daemon (`kind = LIVE`). Single-frame
# ops (`input key`, `input mouse-click/mouse-move`, `input action`) inject one event
# at a frame boundary; `input sequence` reuses #223's time-windowed multi-frame base
# to apply events across frames in one blocking call. Like `game` / `perf`, a domain-
# object group marked live by `kind`, not by the tree (ADR-0019). The mouse ops are
# flat two-token commands (`mouse-click` / `mouse-move`) directly under `input`, not a
# nested `mouse` sub-group: a 3-token name would break the mechanical
# `gda <group> <command>` → `<group>_<command>` dispatch + gda-mcp tool-name mapping
# (ADR-0005/0011/0012).
_app = typer.Typer(
    help="Inject input into the running game (live).",
    no_args_is_help=True,
)


@_app.command(name="key", cls=INPUT_KEY_COMMAND.command_class())
def input_key(
    key: str = typer.Argument(
        ..., help="A Godot key name to inject (e.g. Right, A, Space, Escape)."
    ),
    modifiers: list[str] = typer.Option(
        [],
        "--modifiers",
        help="Modifier keys held with the key (repeatable): shift, ctrl, alt, meta.",
    ),
    released: bool = typer.Option(
        False, "--released", help="Inject a key RELEASE instead of a press."
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_KEY_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject one key event into the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    pushes an InputEventKey into the running game's root viewport, so it rides the
    game's real input flow. The harness resolves the key name to a keycode; an
    unresolvable name is `live_invalid_key`. With no daemon it reports
    `daemon_not_running`.
    """
    params = params_or_bad_parameter(
        InputKeyParams, key=key, modifiers=modifiers, released=released
    )
    dispatch_domain(
        INPUT_KEY_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="mouse-click", cls=INPUT_MOUSE_CLICK_COMMAND.command_class())
def input_mouse_click(
    x: float = typer.Argument(..., help="The click's x position in the viewport."),
    y: float = typer.Argument(..., help="The click's y position in the viewport."),
    button: MouseButton = typer.Option(
        MouseButton.LEFT,
        "--button",
        help="Which mouse button to click: left, right, or middle.",
    ),
    double: bool = typer.Option(
        False, "--double", help="Mark the event a double click."
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_MOUSE_CLICK_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject a mouse button click into the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    pushes an InputEventMouseButton at the viewport position into the running
    game's root viewport. Read the injected coordinate from the mouse event's
    position; Godot may leave Viewport.get_mouse_position() /
    Node2D.get_global_mouse_position() stale in daemon sessions. With no daemon it
    reports `daemon_not_running`.
    """
    dispatch_domain(
        INPUT_MOUSE_CLICK_COMMAND,
        InputMouseClickParams(x=x, y=y, button=button, double=double),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="mouse-move", cls=INPUT_MOUSE_MOVE_COMMAND.command_class())
def input_mouse_move(
    x: float = typer.Argument(
        ..., help="The motion's target x position in the viewport."
    ),
    y: float = typer.Argument(
        ..., help="The motion's target y position in the viewport."
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_MOUSE_MOVE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject a mouse motion event into the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    pushes an InputEventMouseMotion to the viewport position into the running
    game's root viewport. Read the injected coordinate from the mouse event's
    position; Godot may leave Viewport.get_mouse_position() /
    Node2D.get_global_mouse_position() stale in daemon sessions. With no daemon it
    reports `daemon_not_running`.
    """
    dispatch_domain(
        INPUT_MOUSE_MOVE_COMMAND,
        InputMouseMoveParams(x=x, y=y),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="action", cls=INPUT_ACTION_COMMAND.command_class())
def input_action(
    action: str = typer.Argument(
        ..., help="The input action name (must be in the running InputMap)."
    ),
    release: bool = typer.Option(
        False, "--release", help="Release the action instead of pressing it."
    ),
    strength: float = typer.Option(
        1.0,
        "--strength",
        min=0.0,
        max=1.0,
        help="The analog press strength, 0..1 (ignored on a release).",
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_ACTION_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Press or release a named input action in the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    drives Input.action_press / action_release against the running InputMap, so the
    game observes the action exactly as a real binding would fire. An action absent
    from the InputMap is `live_unknown_action`. With no daemon it reports
    `daemon_not_running`.
    """
    params = params_or_bad_parameter(
        InputActionParams, action=action, release=release, strength=strength
    )
    dispatch_domain(
        INPUT_ACTION_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="sequence", cls=INPUT_SEQUENCE_COMMAND.command_class())
def input_sequence(
    events: str = typer.Option(
        ...,
        "--events",
        help=(
            # Both examples are spelled with a space after each ':' and ',' so the
            # help renderer WRAPS them instead of ellipsizing an unbreakable
            # word: the one-line form used to be cut off mid-example, which is
            # not copyable. JSON ignores the extra whitespace.
            "The events to inject, as a JSON array of event objects, each with a "
            "'type' (key, mouse_click, mouse_button, mouse_move or action), "
            "either a "
            "relative 'frame' harness/process-frame offset or a 'physics_frame' "
            "physics-clock offset, and that type's own fields (--schema publishes "
            "each type's required and forbidden fields). "
            "Drag: "
            '\'[{"type": "mouse_button", "x": 10, "y": 10, "pressed": true}, '
            '{"type": "mouse_move", "x": 40, "y": 20, "frame": 1}, '
            '{"type": "mouse_button", "x": 40, "y": 20, "release": true, '
            '"frame": 2}]\'. '
            # The action pair the mouse-only example left an agent to infer: an
            # action presses by default and releases with 'release', never with
            # the mouse-button kind's 'pressed' (GDA-DF-032).
            "Action held for 10 process frames: "
            '\'[{"type": "action", "action": "jump", "frame": 0}, '
            '{"type": "action", "action": "jump", "release": true, '
            '"frame": 10}]\'.'
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_SEQUENCE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject a sequence of events across frames in one blocking call (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    applies the `--events` across one selected clock, returned as one blocking
    result (reuses #223's time-windowed multi-frame base). Existing `frame` offsets
    are harness/process-frame ticks from the `_process` loop, not Godot physics
    frames. Use `physics_frame` offsets instead when a press/release window must map
    deterministically to physics simulation ticks, e.g. press an action at
    `physics_frame: 0` and release it at `physics_frame: 30` for a 30-physics-frame
    hold. A `mouse_button` press followed by `mouse_move` events and a matching
    `mouse_button` release carries the held-button mask on the motion events for
    drag handlers. For sequence mouse events, read the injected coordinate from the
    mouse event's position; Godot may leave Viewport.get_mouse_position() /
    Node2D.get_global_mouse_position() stale in daemon sessions. A malformed
    `--events` (not a JSON array, an empty list, an
    ill-formed event, or mixed `frame`/`physics_frame` clocks) is a usage error; with
    no daemon it reports `daemon_not_running`. An event's action absent from the
    InputMap is `live_unknown_action`, an unresolvable key `live_invalid_key`.
    """
    # --events is a JSON array on the argv path; the model is the source of truth for
    # the per-event shape (ADR-0015), so a parse or validation failure is a usage
    # error (exit 2), while --params-json surfaces the same model rule as a
    # structured invalid_params.
    try:
        decoded = json.loads(events)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--events is not valid JSON: {exc}") from exc
    params = params_or_bad_parameter(InputSequenceParams, events=decoded)
    dispatch_domain(
        INPUT_SEQUENCE_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``input`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="input")
