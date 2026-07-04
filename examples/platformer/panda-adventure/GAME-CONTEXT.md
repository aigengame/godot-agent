# Panda Adventure — Game Context

The shared language of **Panda Adventure**: the game-domain glossary for this demo.

This is the subproject-local analogue of the repo-root `CONTEXT.md`, scoped to this directory
so game-domain terms never pollute the parent `gda` project. Terms are added lazily as they
get resolved (via `grill-with-docs`, remapped to this file).

See `docs/agents/domain.md` for the local domain-doc convention and the skill remap.

## Language

### Actors

**Player**:
The single protagonist the user controls — a spacesuit-wearing panda warrior fighting for the
Animal Federation.
_Avoid_: hero, character; Panda (flavor, not the canonical term)

**NPC**:
A non-combatant animal citizen of the Animal Federation (owl, elephant, rabbit, and the like) who
populates the setting but takes no part in combat in this demo.
_Avoid_: villager, friendly, ally

### Enemies

**Enemy**:
A hostile actor the player fights. Every enemy is characterized by three orthogonal axes —
Faction, Tier, and Archetype — plus a stat block. A wave is a composition of specific values
of each.
_Avoid_: mob; Monster as the category name (Monster is one Faction)

**Faction**:
An enemy's visual-and-lore family: Monster, Xenomorph, Alien, or Robot. Cosmetic and narrative
only — Faction by itself implies neither difficulty nor behavior.
_Avoid_: race, type; using 形象 as a difficulty word

**Tier**:
An enemy's power-and-reward grade: Minion, Elite, or Boss. Drives the stat budget and the
EXP/Gold reward. Independent of Faction and Archetype.
_Avoid_: 小怪 as a synonym for the Monster Faction; "level" (collides with the player's level)

**Archetype**:
An enemy's combat style: Melee, Ranged, or Tank. Drives AI behavior and attack pattern.
Independent of Faction and Tier. Melee and Ranged behave since S4; Tank is representable in
the data model but its AI behavior is deferred (gADR-0003).
_Avoid_: class, role; using 流派 loosely

**Enemy Kind**:
One concrete enemy definition — a named point in Faction × Tier × Archetype plus its Stat
Block, blockout, and Archetype-AI params — keyed by name in the authoritative enemies config
and derived to one `EnemyConfig` Resource per kind (gADR-0003). What a Spawn Roster entry
references and what the spawner injects into an enemy instance.
_Avoid_: enemy type, enemy class, variant

**Spawn Roster**:
The data-driven which-kind-spawns-where list: ordered entries of (Enemy Kind, node name,
position) — since S5 the composition of ONE Wave, spawned when that Wave starts
(gADR-0003, gADR-0005). Spawn names are unique across the whole Wave schedule for
addressability.
_Avoid_: spawn table, wave list

**Aggro Range**:
The distance within which an enemy notices the Player and its Archetype AI activates —
beyond it the enemy stands dormant, neither steering nor attacking.
_Avoid_: detection radius, sight range, leash

**Steering Band**:
The per-kind distance band `[keep_range_min, keep_range_max]` the Archetype AI steers to
hold: close in beyond it, back off inside it, hold within it. Closing distance (Melee — a
band ending point-blank, min 0) and keeping distance (Ranged — a standoff band) are the SAME
rule with different data (gADR-0003).
_Avoid_: comfort zone, preferred range

### Weapons

**Laser Gun**:
The player's primary weapon — a hitscan/projectile gun that deals damage to enemies.
_Avoid_: blaster, rifle

**Projectile**:
The bolt the Laser Gun fires — a block that flies straight, damages the first Enemy it
overlaps (via the damage formula), and despawns on any contact or after its config
lifetime. The only thing that damages an Enemy in S2.
_Avoid_: bullet, laser (that names the weapon), missile

**Gravity Gun**:
The player's utility weapon. Fired at the environment, it creates a Gravity Field rather than
dealing direct damage. The player's own gravity is never affected by it.
_Avoid_: gravity flip (the player is never flipped); grav tool

**Gravity Field**:
A localized region of altered gravity produced by the Gravity Gun. It acts only on
gravity-affectable obstacles and on enemies within its range (lifting, slamming, or
redirecting them) — never on the player. The basis of the "改变重力" core-loop pillar.
_Avoid_: global gravity, gravity flip, zero-g (it is a local field, not a world toggle)

**Gravity Field params**:
The data-driven description of one field's effect (gADR-0002): a velocity vector —
direction (normalized) × strength — applied within a radius for a duration. Lift
(upward) is the shipped fire default; slam and redirect are other data values of the
SAME params, never separate mechanics.
_Avoid_: field modes, gravity types, effect kinds

**Gravity-affectable**:
The opt-in response contract for any body a Gravity Field can act on: it joins the
`gravity_affectable` group and implements `apply_gravity_field(field_velocity, delta)`,
integrating the field velocity its own way (gADR-0002). The Enemy and the Obstacle are
the S3 members; the Player never is (excluded by collision mask, not code).
_Avoid_: pushable, liftable, physics-enabled

**Current weapon**:
The Player's weapon-switch state: which Equipment gun `fire` fires. Toggled between
the Laser Gun and the Gravity Gun by the `switch_weapon` action; the spawn default is
the Laser Gun.
_Avoid_: active gun, weapon slot, loadout state

### Stats

**MP**:
The player's resource for the Gravity Gun: firing it (creating a Gravity Field) spends MP, and
the Gravity Gun is the only thing that spends MP. Restored by drinking Wine. (HP, EXP, and Gold
keep their conventional meanings and are not glossed here.)
_Avoid_: mana, energy

**Stat Block**:
The per-actor-kind data-driven combat config — max HP/MP, attack, defense — carried as the
`StatsConfig` Resource derived from JSON (gADR-0001). Player and every Enemy kind carry the
SAME shape: the symmetric attacker/defender contract of the damage formula.
_Avoid_: attribute sheet, stat table

**StatsSystem**:
The runtime holder of one actor's live HP/MP/EXP/Gold, instantiated per actor from its Stat
Block and mutated only in memory — never persisted back to config (gADR-0001).
_Avoid_: stats manager, game state

**Kill reward**:
The EXP and Gold awarded to the Player when an Enemy dies, keyed by the enemy's Tier in the
authoritative per-Tier reward table and resolved to per-kind derived fields by the builder
(gADR-0004). Accumulated onto the Player's StatsSystem; the risk→reward half of the
death/reward story.
_Avoid_: drop (that is the S7 item story), loot, bounty

### UI

**HUD**:
The always-on screen-space overlay surfacing the Player's live HP, MP, EXP, Gold, and Current
weapon at a glance (GDD "HUD & UI"), reading the Player's public snapshot each frame rather
than the Player's internals (gADR-0004). Diegetic-light and unobtrusive; a blockout of Labels
until the asset pass.
_Avoid_: status bar, overlay UI, GUI (the HUD is one specific surface, not all UI)

### Combat

**CombatSystem**:
The pure decision functions of combat — the damage formula, the i-frame window check, and
the death rule — static, deterministic, and clock-free, shared unchanged by the runtime
controllers and the offline Monte-Carlo balancing sim (gADR-0001). Controllers orchestrate
(clock, mutation, tween, log); decisions live only here.
_Avoid_: damage manager, battle system

**EnemyAI**:
The pure Archetype-AI decision functions — Steering-Band steering and aggro/range/cooldown
attack gating — static, deterministic, and clock-free like CombatSystem (positions and time
are parameters, gADR-0003). Controllers orchestrate (clock, velocity integration, attack
delivery, tween, log); AI decisions live only here.
_Avoid_: ai manager, behavior tree, brain

**TTK** (Time To Kill):
How long it takes the player to kill a given enemy. Paired with TTD to tune combat pacing.
_Avoid_: DPS (a rate, not a time)

**TTD** (Time To Die):
How long it takes an enemy or a wave to kill the player — the player's survival time. The
symmetric counterpart of TTK.
_Avoid_: TDD (reserved repo-wide for Test-Driven Development); time-to-down

### Items

**Consumable**:
An item used up on use. The demo's consumables are the Bun and the Wine.
_Avoid_: potion, drug

**Bun**:
A Consumable that restores HP.
_Avoid_: mantou, steamed bun, bread

**Wine**:
A Consumable that restores MP.
_Avoid_: jiu, sake, alcohol

**Wine hook**:
S3's minimal MP-restore path standing in for the S7 Consumable system: the
`drink_wine` action restores a config amount of MP (capped at max MP) with no
inventory and no item count. S7 replaces the hook's supply side, not its effect.
_Avoid_: inventory, consumable system (that is S7)

**Equipment**:
An item the Player wields or wears persistently — the Laser Gun, the Gravity Gun, and the
Spacesuit. Contrast with Consumable.
_Avoid_: gear, loadout

**Spacesuit**:
The Player's armor — the only piece of defensive Equipment in the demo.
_Avoid_: armor (generic), suit

### Level

**Wave**:
A segment of the demo level that spawns a specific composition of enemies
(Faction × Tier × Archetype) — one Spawn Roster in the Wave schedule. Waves advance in
sequence as each is cleared (gADR-0005). The demo defaults to four; the count is
data-driven, not hardcoded.
_Avoid_: round, stage; level (the demo is a single level)

**Wave schedule**:
The ordered, data-driven list of Waves the level plays through: the `waves` array of the
authoritative enemies config, derived to the `WaveScheduleConfig` Resource the level
consumes (gADR-0005). The wave count is the array's length — config, never code. It
replaced the S4 top-level boot roster (whose single entry became Wave 1).
_Avoid_: wave list, spawn table, roster (that names one Wave's composition)

**Boss slot**:
The final Wave of the demo's default schedule, composing the boss-Tier kind — the Boss's
data-driven arrival point. A property of the demo composition, not a schedule invariant
(a reconfigured schedule need not end on a Boss); the Boss's behavior itself is S8
(Tank AI deferred, gADR-0003).
_Avoid_: final boss wave (as a system rule), boss fight (that is the S8 behavior)

**Obstacle**:
A gravity-affectable environment block on the terrain layer that a Gravity Field can
lift, slam, or redirect — the level-as-a-weapon half of the change-gravity pillar. A
prop, not an actor: it never attacks, damages, or moves on its own.
_Avoid_: crate (flavor), prop (generic), hazard

<!-- Format reminder — **Term**: one/two-sentence definition (what it IS, not what it does);
     _Avoid_: rejected synonyms. Group natural clusters under ### subheadings. -->

