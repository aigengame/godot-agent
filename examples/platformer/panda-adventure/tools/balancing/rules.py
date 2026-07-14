"""The pipeline's reference ruleset: the pure decision functions both engines run on.

Damage, i-frames, death, steering, attack gating, the warp kit's decisions,
slow-field membership, equipment defense composition, and level resolution —
every function is pure, deterministic, and clock-free: time and positions are
parameters. Positions are passed as bare ``(x, y)`` floats rather than a vector
type so this module depends on nothing but ``math``.

A game that implements the same rules in its own engine code is expected to pin
the correspondence with golden parity fixtures generated FROM its engine-side
implementation (the host project's test suite owns that gate); the pipeline
itself never imports game code. A rule change on either side then breaks parity
until both co-evolve — the price the pipeline pays for isolation.
"""

from __future__ import annotations

import math

# The sentinel a never-hit / never-attacked actor uses: ``now - (-inf) == inf``,
# so an i-frame window is never active and an attack cooldown is always ready.
NEVER = float("-inf")


def _signf(value: float) -> float:
    """Sign as -1.0 / 0.0 / 1.0, with an exact 0.0 for a 0.0 input."""
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def _distance(self_x: float, self_y: float, player_x: float, player_y: float) -> float:
    """The full 2D Euclidean distance between the two positions."""
    return math.hypot(player_x - self_x, player_y - self_y)


# --- Combat ------------------------------------------------------------------ #


def compute_damage(
    attacker_attack: float,
    defender_defense: float,
    attack_scale: float,
    defense_scale: float,
    min_damage: float,
) -> float:
    """The data-driven damage formula: scaled attack minus scaled mitigation,
    floored at ``min_damage``. Symmetric — the same call serves player->enemy
    and enemy->player with the roles swapped."""
    return max(
        min_damage,
        attacker_attack * attack_scale - defender_defense * defense_scale,
    )


def is_invulnerable(last_hit_time: float, now: float, iframe_duration: float) -> bool:
    """True while the defender is inside its post-hit i-frame window. The
    ``NEVER`` sentinel is never invulnerable."""
    return (now - last_hit_time) < iframe_duration


def is_dead(hp: float) -> bool:
    """The death rule: an actor dies at exactly 0 HP."""
    return hp <= 0.0


# --- Enemy AI ----------------------------------------------------------------- #


def compute_move_dir(
    self_x: float,
    self_y: float,
    player_x: float,
    player_y: float,
    aggro_range: float,
    keep_range_min: float,
    keep_range_max: float,
) -> float:
    """Horizontal steering: -1 / 0 / 1. Dormant beyond the aggro range; close
    in beyond ``keep_range_max``, back off inside ``keep_range_min``, hold
    within the steering band. A player directly above (dx == 0) yields 0 —
    nowhere to steer horizontally."""
    distance = _distance(self_x, self_y, player_x, player_y)
    if distance > aggro_range:
        return 0.0
    toward = _signf(player_x - self_x)
    if distance > keep_range_max:
        return toward
    if distance < keep_range_min:
        return -toward
    return 0.0


def is_attack_ready(last_attack_time: float, now: float, cooldown: float) -> bool:
    """The attack-cooldown gate: ready once ``cooldown`` has elapsed. The
    ``NEVER`` sentinel is always ready."""
    return (now - last_attack_time) >= cooldown


def can_attack(
    self_x: float,
    self_y: float,
    player_x: float,
    player_y: float,
    aggro_range: float,
    attack_range: float,
    attack_cooldown: float,
    last_attack_time: float,
    now: float,
) -> bool:
    """The full attack decision: the player must be inside BOTH the aggro range
    and the attack range, and the cooldown must have elapsed."""
    distance = _distance(self_x, self_y, player_x, player_y)
    if distance > aggro_range or distance > attack_range:
        return False
    return is_attack_ready(last_attack_time, now, attack_cooldown)


# --- The warp kit (a blink-engage rotation) ----------------------------------- #


def has_warp(warp_cooldown: float) -> bool:
    """The has-warp predicate: the presence-gated kit floors ``warp_cooldown``
    strictly above 0 at the data seam, so a kind without the kit reads the type
    default 0.0."""
    return warp_cooldown > 0.0


def should_warp(
    self_x: float,
    self_y: float,
    player_x: float,
    player_y: float,
    aggro_range: float,
    warp_trigger_range: float,
    warp_cooldown: float,
    last_warp_time: float,
    now: float,
) -> bool:
    """The warp gate: cast only when the kind HAS the kit, the player is inside
    the aggro range but FARTHER than the trigger range (the blink is an
    anti-kite engage tool — never cast inside a brawl), and the cooldown has
    elapsed. The ``NEVER`` sentinel gates the first warp by distance alone."""
    if not has_warp(warp_cooldown):
        return False
    distance = _distance(self_x, self_y, player_x, player_y)
    if distance > aggro_range:
        return False
    if distance <= warp_trigger_range:
        return False
    return (now - last_warp_time) >= warp_cooldown


def warp_landing(
    self_x: float,
    self_y: float,
    player_x: float,
    player_y: float,
    warp_offset_x: float,
    warp_offset_y: float,
    arena_min_x: float,
    arena_max_x: float,
) -> tuple[float, float]:
    """The deterministic blink landing: x lands the configured offset on the
    player's FAR side from the caster (cutting off the retreat), clamped to the
    arena's x range; y is the player's y plus the offset's y. A player exactly
    overhead (dx == 0) resolves to the +x side — never random."""
    side = _signf(player_x - self_x)
    if side == 0.0:
        side = 1.0
    x = min(max(player_x + side * warp_offset_x, arena_min_x), arena_max_x)
    return (x, player_y + warp_offset_y)


def is_inside_field(
    pos_x: float,
    pos_y: float,
    field_center_x: float,
    field_center_y: float,
    radius: float,
) -> bool:
    """Slow-field membership: inside the zone at (or within) its radius."""
    return _distance(pos_x, pos_y, field_center_x, field_center_y) <= radius


# --- Equipment mitigation ------------------------------------------------------ #


def effective_defense(base_defense: float, defense_bonus: float) -> float:
    """The worn-equipment defense composition: the defender's defense is the
    base stat block's defense raised by the equipment's bonus — the formula's
    mitigation term changes, the formula itself is untouched."""
    return base_defense + defense_bonus


# --- Progression: the level readout -------------------------------------------- #


def resolve_level(exp_points: float, level_curve: list[float]) -> int:
    """The level implied by a cumulative EXP total against the leveling curve:
    level 1 at the start, +1 per threshold reached, so the level is ``1 + the
    thresholds crossed`` and the max level is ``len(level_curve) + 1`` (the
    curve is always a parameter — no hardcoded count). Deriving from the TOTAL
    makes a multi-threshold reward a multi-level-up and re-resolution
    idempotent."""
    level = 1
    for threshold in level_curve:
        if exp_points >= threshold:
            level += 1
    return level
