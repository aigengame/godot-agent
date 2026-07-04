---
status: accepted
---

# Gravity Field: data-driven effect and the gravity-response contract

S3 (issue #332) introduces the change-gravity pillar: the Gravity Gun spends MP
and spawns a local Gravity Field that lifts/slams/redirects gravity-affectable
obstacles and in-range enemies — never the Player. Two decisions fix HOW the
field's effect is expressed and HOW bodies respond, because S4's Archetype
enemies (which rewrite `EnemyController`) and every future obstacle/prop kind
must keep interoperating with the field without touching it.

## Decision 1 — the field's effect is data: velocity × radius × duration

A Gravity Field's effect is fully described by config (`GravityConfig`, a
derived Resource from `gravity_config.json`, gADR-0000): a **velocity vector**
— `field_direction` (normalized, so strength stays the single magnitude
authority) × `field_strength` (px/s) — applied within a circular
`field_radius` for a bounded `field_duration`. **Lift** (upward, `[0, -1]`) is
the shipped fire default; **slam** (`[0, 1]`) and **redirect**
(horizontal/diagonal) are different DATA values of the same params, not extra
code paths. This is the deliberate reading of the GDD's "lifting, slamming, or
redirecting": one mechanism, three tunings — the pure decision is
`GravitySystem.compute_field_velocity`.

## Decision 2 — the gravity-response contract

Any body a Gravity Field can act on:

- joins the **`"gravity_affectable"`** group, and
- implements **`func apply_gravity_field(field_velocity: Vector2, delta: float) -> void`**.

The field calls the method **each physics frame** for every overlapping body
that satisfies **both** requirements (the pure filter
`GravityFieldController.should_affect` — a same-named method on a non-member
is NOT driven); the body integrates the velocity **its own way**. The field knows
no body kinds; bodies know no fields. S3 ships two responders, both static
bodies integrating by **clamped position displacement** (the accumulated
offset's length never exceeds a per-kind config max — pure decision:
`GravitySystem.compute_clamped_offset`, so a field can move a block but never
fling it off-level): `EnemyController` (S4's rewrite must preserve the group
join in `_ready` plus the one method — kept as one self-contained block) and
`ObstacleController`. A future `CharacterBody2D`/`RigidBody2D` responder
integrates into its own velocity instead — same contract, different
integration.

**Never the Player — by mask, not code.** The field is an `Area2D` on layer 5
`gravity_field`, masking `terrain|enemy` only: the Player's layer is invisible
to it (the Projectile's mask-guarantee pattern). The gravity-affectable
Obstacle lives on `terrain`, so plain terrain (the Platform) overlaps too and
is filtered out by the group + method contract check.

**MP economy.** Firing routes through `StatsSystem.spend_mp` — an
all-or-nothing gate (at insufficient MP nothing is spent, no field spawns, so
at 0 MP the Gravity Gun cannot fire). Wine restores through
`StatsSystem.restore_mp`, capped at the stat block's `max_mp` — the cap is a
parameter passed by the caller from its immutable `StatsConfig`, keeping
config outside the runtime holder (gADR-0001). The S3 Wine hook is
inventory-less (`drink_wine` restores directly); S7 owns the Consumable
system's supply side.

**Weapon switch.** `fire` fires the CURRENT weapon; `switch_weapon` toggles
between the Laser Gun and the Gravity Gun (pure decision:
`PlayerController.compute_next_weapon`; the spawn default is the Laser Gun, so
pre-S3 combat flows are unchanged).

## Considered options

- **Group + duck-typed method (chosen).** Mirrors S2's `take_hit` duck-typing;
  no base class or interface script to inherit, so S4 can rewrite
  `EnemyController`'s hierarchy freely; new responder kinds are a group join +
  one method + a config row, with zero field changes.
- **A shared gravity-body base class (rejected).** GDScript single inheritance
  would force Enemy and Obstacle under one parent and fight S4's Archetype
  hierarchy; the contract is one method — a class is more coupling than
  content.
- **The field displaces bodies directly (rejected).** The field would need to
  know each body kind's clamp and physics; response belongs to the body
  (tell-don't-ask), and a per-kind integration is exactly what S4's moving
  enemies will need.
- **A global gravity toggle (rejected).** The GDD explicitly makes the field
  LOCAL and the Player exempt; world-gravity flips are a different (rejected)
  game.

## Consequences

- S4's enemy rewrite carries the self-contained gravity block over verbatim;
  its moving enemies may re-integrate (velocity instead of displacement)
  without touching the field or this contract.
- Field tuning (including switching the default from lift to slam/redirect) is
  a JSON edit; the logic seam pins the velocity/clamp math, the e2e pins the
  live loop (spend → spawn → lift → clamp → block at 0 MP → Wine).
- The collision-layer story completes: layer 5 `gravity_field` is the field's
  own layer; what the field can act on is its mask (`terrain|enemy`), and the
  Player's exemption is topology, not a code check.
