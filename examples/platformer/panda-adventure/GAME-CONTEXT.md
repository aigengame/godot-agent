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
Independent of Faction and Tier.
_Avoid_: class, role; using 流派 loosely

### Weapons

**Laser Gun**:
The player's primary weapon — a hitscan/projectile gun that deals damage to enemies.
_Avoid_: blaster, rifle

**Gravity Gun**:
The player's utility weapon. Fired at the environment, it creates a Gravity Field rather than
dealing direct damage. The player's own gravity is never affected by it.
_Avoid_: gravity flip (the player is never flipped); grav tool

**Gravity Field**:
A localized region of altered gravity produced by the Gravity Gun. It acts only on
gravity-affectable obstacles and on enemies within its range (lifting, slamming, or
redirecting them) — never on the player. The basis of the "改变重力" core-loop pillar.
_Avoid_: global gravity, gravity flip, zero-g (it is a local field, not a world toggle)

### Stats

**MP**:
The player's resource for the Gravity Gun: firing it (creating a Gravity Field) spends MP, and
the Gravity Gun is the only thing that spends MP. Restored by drinking Wine. (HP, EXP, and Gold
keep their conventional meanings and are not glossed here.)
_Avoid_: mana, energy

### Combat

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

**Equipment**:
An item the Player wields or wears persistently — the Laser Gun, the Gravity Gun, and the
Spacesuit. Contrast with Consumable.
_Avoid_: gear, loadout

**Spacesuit**:
The Player's armor — the only piece of defensive Equipment in the demo.
_Avoid_: armor (generic), suit

### Level

**Wave**:
A timed segment of the demo level that spawns a specific composition of enemies
(Faction × Tier × Archetype). The demo has four.
_Avoid_: round, stage; level (the demo is a single level)

<!-- Format reminder — **Term**: one/two-sentence definition (what it IS, not what it does);
     _Avoid_: rejected synonyms. Group natural clusters under ### subheadings. -->

