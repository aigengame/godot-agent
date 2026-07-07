"""Pure Python reimplementation of the game's combat/AI logic seams (gADR-0011).

These functions mirror the shipped GDScript statics —
``src/systems/combat_system.gd`` (``CombatSystem``), ``src/systems/enemy_ai.gd``
(``EnemyAI``), ``src/systems/warp_system.gd`` (``WarpSystem``, the Boss Warp
kit's pure decisions, gADR-0009), and ``src/systems/item_system.gd``
(``ItemSystem.effective_defender``'s defense composition, gADR-0008) —
one-for-one. gADR-0011 forbids the balancing pipeline from importing the game's
GDScript, so the rules are reimplemented here and pinned against the GDScript
ground truth by golden parity fixtures
(``tests/fixtures/balancing/seams.json``, generated FROM the seams via
``gda script run``). A rule change on either side breaks parity until both
co-evolve — the price gADR-0011 pays for isolation.

Every function is pure, deterministic, and clock-free: time and positions are
parameters, exactly as in the GDScript. Positions are passed as bare ``(x, y)``
floats rather than a Vector2 so this module depends on nothing but ``math``.
"""

from __future__ import annotations

import math

# The sentinel a never-hit / never-attacked actor uses (mirrors the GDScript's
# -INF): ``now - (-inf) == inf``, so an i-frame window is never active and an
# attack cooldown is always ready.
NEVER = float("-inf")


def _signf(value: float) -> float:
    """Godot ``signf``: -1.0 / 0.0 / 1.0, with an exact 0.0 for a 0.0 input."""
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def _distance(self_x: float, self_y: float, player_x: float, player_y: float) -> float:
    """The full 2D Euclidean distance — Godot ``Vector2.distance_to``."""
    return math.hypot(player_x - self_x, player_y - self_y)


# --- CombatSystem (src/systems/combat_system.gd) ---------------------------- #


def compute_damage(
    attacker_attack: float,
    defender_defense: float,
    attack_scale: float,
    defense_scale: float,
    min_damage: float,
) -> float:
    """The data-driven damage formula: scaled attack minus scaled mitigation,
    floored at ``min_damage``. Symmetric — the same call serves player->enemy
    and enemy->player with the roles swapped (``CombatSystem.compute_damage``)."""
    return max(
        min_damage,
        attacker_attack * attack_scale - defender_defense * defense_scale,
    )


def is_invulnerable(last_hit_time: float, now: float, iframe_duration: float) -> bool:
    """True while the defender is inside its post-hit i-frame window
    (``CombatSystem.is_invulnerable``). The ``NEVER`` sentinel is never invuln."""
    return (now - last_hit_time) < iframe_duration


def is_dead(hp: float) -> bool:
    """The death rule: an actor dies at exactly 0 HP (``CombatSystem.is_dead``)."""
    return hp <= 0.0


# --- EnemyAI (src/systems/enemy_ai.gd) -------------------------------------- #


def compute_move_dir(
    self_x: float,
    self_y: float,
    player_x: float,
    player_y: float,
    aggro_range: float,
    keep_range_min: float,
    keep_range_max: float,
) -> float:
    """Horizontal steering: -1 / 0 / 1 (``EnemyAI.compute_move_dir``). Dormant
    beyond the Aggro Range; close in beyond ``keep_range_max``, back off inside
    ``keep_range_min``, hold within the Steering Band. A Player directly above
    (dx == 0) yields 0 — nowhere to steer horizontally."""
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
    """The attack-cooldown gate: ready once ``cooldown`` has elapsed
    (``EnemyAI.is_attack_ready``). The ``NEVER`` sentinel is always ready."""
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
    """The full attack decision: the Player must be inside BOTH the Aggro Range
    and the attack range, and the cooldown must have elapsed
    (``EnemyAI.can_attack``)."""
    distance = _distance(self_x, self_y, player_x, player_y)
    if distance > aggro_range or distance > attack_range:
        return False
    return is_attack_ready(last_attack_time, now, attack_cooldown)


# --- WarpSystem (src/systems/warp_system.gd), the Boss Warp kit (gADR-0009) -- #


def has_warp(warp_cooldown: float) -> bool:
    """The has-Warp predicate (``WarpSystem.has_warp``): the presence-gated
    block floors ``warp_cooldown`` strictly above 0 at the data seam, so a kind
    without the kit reads the type default 0.0."""
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
    """The warp gate (``WarpSystem.should_warp``): cast only when the kind HAS
    the kit, the Player is inside the Aggro Range but FARTHER than the trigger
    range (the Blink is an anti-kite engage tool — the Boss never warps inside a
    brawl), and the cooldown has elapsed. The ``NEVER`` sentinel gates the first
    warp by distance alone."""
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
    """The deterministic blink landing (``WarpSystem.warp_landing``): x lands
    the configured offset on the Player's FAR side from the caster (cutting off
    the retreat), clamped to the arena's x range; y is the Player's y plus the
    offset's y. A Player exactly overhead (dx == 0) resolves to the +x side —
    never random."""
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
    """Time Dilation Field membership (``WarpSystem.is_inside_field``): inside
    the zone at (or within) its radius."""
    return _distance(pos_x, pos_y, field_center_x, field_center_y) <= radius


# --- ItemSystem (src/systems/item_system.gd), Spacesuit mitigation (gADR-0008) #


def effective_defense(base_defense: float, defense_bonus: float) -> float:
    """The worn-Equipment defense composition (``ItemSystem.effective_defender``,
    gADR-0008): the defender's defense is the base stat block's defense raised by
    the Spacesuit's bonus — the formula's mitigation term changes, the formula
    itself is untouched. (The GDScript composes a fresh full stat block; only the
    defense differs, which is what this mirrors.)"""
    return base_defense + defense_bonus
