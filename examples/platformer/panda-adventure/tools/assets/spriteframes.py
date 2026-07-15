"""SpriteFrames deriver — a packed sheet + its layout into a Godot resource.

The read-side counterpart of the :mod:`packer`: given the committed
spritesheet's ``res://`` path and its :class:`~assets.model.FrameLayout`, this
emits a Godot ``SpriteFrames`` ``.tres`` — one ``AtlasTexture`` sub-resource per
frame (its ``region`` the frame's box in the sheet) and one animation that
sequences them. So a sprite slice turns a loose-frame acquisition into a
ready animation resource without re-deriving the geometry by hand.

Pure text emission: byte-stable output (deterministic sub-resource ids, no
``uid`` — a committed derived artifact must re-derive identically), no Godot,
no IO, so it runs in the fast CI tier. That the emitted text really loads as a
Godot resource is proven by an engine-tier test.
"""

from __future__ import annotations

from .model import FrameLayout, SpriteAnimation

# The default playback speed (fps) an emitted animation carries; a caller retunes
# per state. Frame durations are uniform (1.0 each) — the committed unit is one
# sheet per animation state, not per-frame timing.
_DEFAULT_SPEED = 8.0
# The ext_resource id the sheet texture is referenced by. A stable literal (not a
# random suffix like the editor's) so the derived .tres is byte-identical per run.
_SHEET_EXT_ID = "1_sheet"


def _atlas_id(anim_name: str, index: int) -> str:
    """The deterministic sub-resource id for frame ``index`` of ``anim_name``."""
    return f"AtlasTexture_{anim_name}_{index}"


def _fps(speed: float) -> str:
    """Render a playback speed as a float literal (always with a decimal point)."""
    return repr(float(speed))


def derive_spriteframes(
    sheet_res_path: str,
    layout: FrameLayout,
    anim_name: str,
    *,
    speed: float = _DEFAULT_SPEED,
    loop: bool = True,
) -> str:
    """Derive a ``SpriteFrames`` ``.tres`` for one packed sheet + its layout.

    ``sheet_res_path`` is the committed sheet's ``res://`` path; ``layout`` its
    :class:`~assets.model.FrameLayout`; ``anim_name`` the animation state the
    sheet holds (e.g. ``"run"``). Each frame becomes an ``AtlasTexture`` whose
    ``region`` is its box in the sheet (row-major: frame ``k`` at column
    ``k % columns``, row ``k // columns``), and the animation sequences them in
    order. Returns byte-stable ``.tres`` text.
    """
    width, height = layout.frame_dims
    frame_ids = [_atlas_id(anim_name, i) for i in range(layout.count)]

    header = (
        '[gd_resource type="SpriteFrames" format=3]\n\n'
        f'[ext_resource type="Texture2D" path="{sheet_res_path}" '
        f'id="{_SHEET_EXT_ID}"]\n\n'
    )

    atlases = ""
    for index, frame_id in enumerate(frame_ids):
        col, row = index % layout.columns, index // layout.columns
        x, y = col * width, row * height
        atlases += (
            f'[sub_resource type="AtlasTexture" id="{frame_id}"]\n'
            f'atlas = ExtResource("{_SHEET_EXT_ID}")\n'
            f"region = Rect2({x}, {y}, {width}, {height})\n\n"
        )

    frames_lit = ", ".join(
        '{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % frame_id
        for frame_id in frame_ids
    )
    resource = (
        "[resource]\n"
        "animations = [{\n"
        f'"frames": [{frames_lit}],\n'
        f'"loop": {"true" if loop else "false"},\n'
        f'"name": &"{anim_name}",\n'
        f'"speed": {_fps(speed)}\n'
        "}]\n"
    )
    return header + atlases + resource


def _animation_dict(state: SpriteAnimation, ext_id: str) -> tuple[str, str]:
    """Render one state's ``AtlasTexture`` sub-resources + its ``animations`` dict.

    Returns ``(sub_resource_text, animation_dict_text)`` for ``state``: one
    ``AtlasTexture`` block per frame (its ``region`` the frame's box in ``state``'s
    sheet, row-major) referencing ``ext_id`` (the sheet's ext_resource), and the
    ``{frames, loop, name, speed}`` dictionary the SpriteFrames ``animations`` array
    carries. Byte-stable (deterministic sub-resource ids, no ``uid``), matching the
    single-animation deriver's formatting.
    """
    width, height = state.layout.frame_dims
    frame_ids = [_atlas_id(state.name, i) for i in range(state.layout.count)]
    subs = ""
    for index, frame_id in enumerate(frame_ids):
        col, row = index % state.layout.columns, index // state.layout.columns
        x, y = col * width, row * height
        subs += (
            f'[sub_resource type="AtlasTexture" id="{frame_id}"]\n'
            f'atlas = ExtResource("{ext_id}")\n'
            f"region = Rect2({x}, {y}, {width}, {height})\n\n"
        )
    frames_lit = ", ".join(
        '{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % frame_id
        for frame_id in frame_ids
    )
    anim = (
        "{\n"
        f'"frames": [{frames_lit}],\n'
        f'"loop": {"true" if state.loop else "false"},\n'
        f'"name": &"{state.name}",\n'
        f'"speed": {_fps(state.speed)}\n'
        "}"
    )
    return subs, anim


def derive_spriteframes_set(states: list[SpriteAnimation]) -> str:
    """Derive one ``SpriteFrames`` ``.tres`` holding SEVERAL named animations.

    The multi-state counterpart of :func:`derive_spriteframes`: a
    character's animated look is ONE ``SpriteFrames`` an ``AnimatedSprite2D`` plays
    by name, composed from several per-state sheets (idle/run/jump/fire/…), one
    ``ext_resource`` per sheet (deterministic id ``"{i+1}_{name}"``) and one
    ``AtlasTexture`` per frame. ``states`` order fixes the serialization order, so
    the output is byte-stable and uid-free. That it really loads as a Godot
    resource is proven by an engine-tier test.
    """
    if not states:
        raise ValueError("cannot derive a SpriteFrames set with no animation states")
    ext = ""
    atlases = ""
    anim_dicts: list[str] = []
    for index, state in enumerate(states):
        ext_id = f"{index + 1}_{state.name}"
        ext += (
            f'[ext_resource type="Texture2D" path="{state.sheet_res_path}" '
            f'id="{ext_id}"]\n'
        )
        subs, anim = _animation_dict(state, ext_id)
        atlases += subs
        anim_dicts.append(anim)
    header = '[gd_resource type="SpriteFrames" format=3]\n\n'
    resource = "[resource]\nanimations = [" + ", ".join(anim_dicts) + "]\n"
    return header + ext + "\n" + atlases + resource
