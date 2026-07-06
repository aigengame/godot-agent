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
Independent of Faction and Tier. All three run the SAME Steering-Band rule on their own data —
Melee and Ranged since S4 (gADR-0003), Tank since S8 (gADR-0009 lifted the deferral with no
Tank-specific branch); delivery is contact for Melee/Tank, a bolt for Ranged.
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

### Boss abilities

**Warp**:
The Boss's signature spacetime-distortion ability family — ONE narrative hook with two
expressions: the space-warping Warp Blink and the time-warping Time Dilation Field (S8).
Grounded in the black-hole-edge setting: the Boss bends spacetime, the Player bends gravity.
_Avoid_: portal (implies a persistent traversable gate); time-warp as the umbrella (that names
only the field half)

**Warp Blink**:
The Boss's space-warp translocation — after a charge-up tell it instantly relocates to a
configured offset from the Player's position at cast time (clamped to the arena), then stands
in a brief no-attack recovery window. The Tank Boss's engage tool against kiting; deterministic,
never random.
_Avoid_: portal, teleport (generic), dash (it does not traverse the space between)

**Time Dilation Field**:
The Boss's time-warp expression — a static, duration-bound circular zone cast at a point
(typically the Warp Blink landing) that slows time for the Player's whole body simulation
(movement, jump, AND gravity — full slow motion) and for the Player's laser Projectiles inside
it, by a config time factor. Input registration, the Gravity Gun and its Gravity Fields, the
Boss, and everything else run at full speed — the counterplay is spatial (leave the zone), and
the Gravity Gun stays the full-speed answer. The mirror of the Gravity Field: the Player bends
gravity, the Boss bends time.
_Avoid_: slow zone (generic), stun/root/freeze (input still registers — the body is slowed,
not locked), aura (it does not follow the Boss)

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
death/reward story. Instant and guaranteed — contrast the Drop table's Pickups, which
must be collected (gADR-0006).
_Avoid_: drop (that is the Drop-table story, S6b), loot, bounty

**Level**:
The Player's progression grade, derived PURELY from the accumulated EXP total against the
Leveling curve (GrowthSystem — level 1 at start, one level per threshold reached, gADR-0006).
Readout-only in Phase 1: a level-up changes no stat yet, it logs, flashes, and ticks the HUD's
LV line.
_Avoid_: rank; tier (that is the enemy axis); using "level" for the demo's stage (that stage
is the proper noun Level 1)

**Leveling curve**:
The data-driven, strictly increasing array of cumulative EXP thresholds the Player levels up
along — entry k is the total EXP that reaches level k+2, so the max level is the array's
length + 1: config, never code (gADR-0006, the waves.size() idiom). Authored in
`progression_config.json` and derived to the `ProgressionConfig` Resource.
_Avoid_: XP table, growth formula (it is authored data, not a formula)

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
controllers (gADR-0001). For the Balancing pipeline it is the parity fixtures' ground-truth
oracle — no longer the sim engine (gADR-0011). Controllers orchestrate (clock, mutation,
tween, log); decisions live only here.
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

### Pipelines

**Tool Script**:
A reusable Python pipeline script that produces or processes project content — the
asset pipelines (preprocess → acquire → postprocess) and the Balancing pipeline
alike. Designed game-agnostic — a reusable, input-driven core with per-game
configuration, with pluggable output emitters (JSON/XML/Resource/…) for reuse
beyond this demo. In this project its structured output always lands in the JSON
authority (config numbers or asset references) and flows through the JSON →
Resource derivation — never bypassing JSON to write `.tres` directly; generated
asset files land under the assets tree and are referenced from config, never
hardcoded.
_Avoid_: build script (that names the JSON→Resource builder), helper script, tool
(too generic)

**Asset pipeline**:
The Tool Script family that produces the game's binary assets — textures, sprite
frames, audio, fonts. Preprocess builds a style-and-size **asset spec** (the shared
style descriptor plus the Scale spec's target dimensions and format/licensing
constraints); the acquire stage fulfills it in one of two modes — online
search-and-download from open-asset sites, or generation (built-in model or
external MCP backend); postprocess conforms the result (crop/transform/normalize
to the spec) and records provenance and license in the asset manifest. Artifacts
are asset files PLUS their JSON references — asset references are data
(gADR-0000); the view resolves assets from config, never hardcoded paths.
_Avoid_: art pipeline (audio and fonts too), downloader / generator (each names
only one acquire mode)

**Scale spec**:
The unified size/scale standard every visual element conforms to — the anchor
dimensions and inter-element proportion rules that asset generation, post-processing,
and wiring all target. Two layers: the qualitative proportion rules and anchor
rationale live in the GDD (extending its blockout scale-ratio rules); the
authoritative numeric table is data (JSON), consumed by the pipelines and the game
alike (gADR-0000: numbers are not in the GDD). An early Phase 2 deliverable — not
yet authored.
_Avoid_: art bible (broader), size chart, blockout ratios (the Phase 1 subset)

**VFX**:
The view-layer presentation effects — hit flashes, explosions, pickup glints, Warp
telegraphs and the like — produced as assets by the visual pipeline (sprite-frame
animations, particle textures) and fired from the view-integration hooks. Never a
mechanic: a VFX carries no gameplay or damage semantics of its own.
_Avoid_: particles (an implementation), juice (broader — includes camera/audio
feel), effects system

**Derived-Resource loader**:
The single seam every controller loads a derived `.tres` config through — one canonical
loud guard that returns the loaded Resource or, on a null load, emits the one
pipeline-pointing `push_error` (naming the missing path) and returns null. The read-side
home of gADR-0000's "Resource is a derived artifact" contract: a committed `.tres` is
expected present, so a null load means a half-checkout or a skipped build, not a gameplay
condition. Centralizing it leaves one remediation string to update when the builder moves
(gADR-0011), not one copy per controller.
_Avoid_: config loader (generic), resource manager

### Tooling

**Panda Adventure Editor**:
The in-game visual editing-and-debugging tool — a separate entry scene of the same
Godot project that a human (HITL) launches to edit Level 1's content, tune numbers,
and playtest in place; agents keep driving `gda` instead. It writes only the JSON
authority — spatial content (platform segments, Arena, backdrop, Wave/Spawn
rosters) by direct manipulation, numbers by structured forms as the hand-tune
channel — and re-derives Resources through the one Python builder, never a second
derivation path. Ships with instant edit↔play switching and a minimal debug
palette (wave jump, god-mode, spawn-on-demand).
_Avoid_: level editor (it also debugs and tunes), editor plugin (the rejected
form), the editor (ambiguous with the Godot editor)

### Balancing

**Balancing pipeline**:
The numeric-design pipeline that computes and sets the game's tuning numbers — Stat
Blocks, wave frequency/density, TTK/TTD targets, difficulty and Leveling curves —
against design intent: built and first-tuned in Phase 2, re-tuned against playtest
feedback in Phase 3. Twin engines, both Python inside the Tool Script framework —
Monte-Carlo encounter simulation validates encounter-level numbers; a
system-dynamics model (first-order nonlinear ODEs over the growth/economy stocks
and flows) predicts long-term balance trajectories. Deliberately isolated from the
game's GDScript (reusable across games): it reads and writes the same JSON
authority the game derives from, and never imports game code.
_Avoid_: balance patch, number tweaking; balancing sim (that names only the
Monte-Carlo half)

### Items

**Consumable**:
An item used up on use. The demo's consumables are the Bun and the Wine. Since S7
(gADR-0008) a Consumable's use verb is supply-gated: it consumes one from the Item count
hook (a refused, empty-handed use logs `consumable_blocked`), applies the capped restore,
and plays the consume flash. Using at full HP/MP still consumes — the gate is supply,
not need; the cap bounds the effect.
_Avoid_: potion, drug

**Bun**:
A Consumable that restores HP (capped at max HP), used by the `eat_bun` action.
_Avoid_: mantou, steamed bun, bread

**Wine**:
A Consumable that restores MP (capped at max MP), used by the `drink_wine` action.
_Avoid_: jiu, sake, alcohol

**Wine hook**:
S3's minimal MP-restore path that stood in for the S7 Consumable system: the
`drink_wine` action restored a config amount of MP with no inventory and no item count.
CLOSED by S7 (gADR-0008): the action and its capped effect remain, now supply-gated on
the Item count hook, and the restore amount reads from the items authority
(`items_config.json` — migrated out of the gravity config). A historical term.
_Avoid_: inventory, consumable system (that is the S7 whole)

**Items authority**:
The single authoritative source for every item number (gADR-0008):
`items_config.json` → the derived `ItemsConfig` — the Consumable restore amounts, the
consume-flash juice, and the Spacesuit's defense bonus. No item effect reads from any
other config source.
_Avoid_: item config scattering, per-slice item keys

**Equipment**:
An item the Player wields or wears persistently — the Laser Gun, the Gravity Gun, and the
Spacesuit. Contrast with Consumable.
_Avoid_: gear, loadout

### Drops

**Drop table**:
A Tier's data-driven list of what a kill may leave behind: `{item, amount, chance}` entries,
each rolled independently, authored per Tier in the same reward table as the Kill reward and
resolved to a per-kind derived `drop_table` field by the builder (gADR-0006, extending
gADR-0004's per-Tier authority). The item vocabulary is closed for Phase 1: gold, Bun, Wine.
_Avoid_: loot table, drop rates (those are the entries' `chance` fields, not the table)

**Pickup**:
The world block one resolved drop becomes — spawned on a deterministic row centered on the
death position, touchable ONLY by the Player (its own collision layer masks nothing else),
collected by walking into it: gold accumulates onto the Player's Gold, an item lands in the
Item count hook (gADR-0006). A Pickup persists until collected.
_Avoid_: drop (the table entry / the event), power-up, collectible

**Item count hook**:
S6b's per-item count Dictionary on the Player where collected Consumable drops land — the
supply side of the Consumable story. Since S7 (gADR-0008) both ends are live: S6b's
collection fills the counts, S7's use verbs consume them (and the HUD BUN/WINE lines
surface them). Still not a full inventory — no menu, no selector (a later story).
_Avoid_: inventory, bag (both are menu-story concepts)

**Spacesuit**:
The Player's armor — the only piece of defensive Equipment in the demo. Worn from spawn
(persistent); its config defense bonus is composed onto the Player's base stat block
(`ItemSystem.effective_defender`) to feed the damage formula's mitigation term — the
formula itself is untouched (S7, gADR-0008).
_Avoid_: armor (generic), suit

### Level

**Level 1**:
The demo's single playable level as a product — the same Great-Wall arc as the
Phase 1 blockout (same layout, Wave schedule, and Boss finale), productionized by
the Phase 2 pipelines: real visuals/audio/UI wired in and numbers initial-tuned.
A proper noun in the map sense; the Player's progression grade stays **Level**.
The numbering anticipates architecture-level multi-level extensibility only (one
`Level authority` config per level) — additional levels stay out of scope.
_Avoid_: the demo level (its pre-name), stage, map; level (lowercase — collides
with the Player grade)

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
(a reconfigured schedule need not end on a Boss); the Boss's behavior — Tank band AI plus
the Warp kit — is S8's (gADR-0009).
_Avoid_: final boss wave (as a system rule), boss fight (that is the S8 behavior)

**View skin**:
The derived rendering layer that dresses the data-authored level geometry: tile
placements and backdrop layers computed as a pure function of the `Level authority`'s
segments — never a second, hand-authored terrain source (gADR-0010 untouched:
collision and geometry stay the segments'). The Phase 2 upgrade path of the
`Great-Wall blockout`: its tile vocabulary must compose the wall's presentation —
spans, parapets, corners, towers — AND the background efficiently, in one consistent
style.
_Avoid_: tilemap (an implementation node, not the concept), decoration layer,
second terrain authority

**Obstacle**:
A gravity-affectable environment block on the terrain layer that a Gravity Field can
lift, slam, or redirect — the level-as-a-weapon half of the change-gravity pillar. A
prop, not an actor: it never attacks, damages, or moves on its own.
_Avoid_: crate (flavor), prop (generic), hazard

**Great-Wall blockout**:
The demo level's data-composed platform geometry: the ordered, named segments —
one long rampart span, two flank towers, two parapet steps — of the level
authority's `platforms` list, runtime-instanced by the level (gADR-0010). The
GDD's rampart motif realized as blocks; segments are data, never scene-baked.
_Avoid_: map, tilemap, terrain (the physics layer name, not the geometry)

**Level authority**:
The single authoritative source for the level's own numbers (gADR-0010):
`level_config.json` → the derived `LevelConfig` — the Great-Wall blockout, the
backdrop color, the Arena, and the End screen's blockout numbers. The platform
fields migrated here out of the player config (the gADR-0008 one-authority
pattern).
_Avoid_: level data scattering, player config (its old home)

**Arena**:
The authored open span of the Great-Wall rampart where combat lives — the
explicit `arena_min_x`/`arena_max_x` interval in the `Level authority` that
clamps the Warp Blink's landing (gADR-0010, replacing S8's platform-extent
derivation). Authored data, not a derived extent.
_Avoid_: platform extent (the rejected derivation), level bounds

### Game flow

**End state**:
The terminal state of one run — won (the Wave schedule cleared) or lost (the
Player's HP reached 0) — resolved from `playing` by the pure GameStateSystem;
the first transition latches (gADR-0010). Winning keys to the SCHEDULE, not the
Boss: the Boss slot stays a property of the demo composition (gADR-0005).
_Avoid_: game over (only the lost half), victory (only the won half)

**World freeze**:
The End-state halt of gameplay: every non-CanvasLayer child of the level gets
its processing disabled at a frame boundary — never a tree pause, which would
sever the gda harness's live channel (gADR-0010). The HUD keeps the final
readout; the frozen bolts and fields are the finale's tableau.
_Avoid_: pause (the rejected mechanism), slow-mo (that is the Time Dilation
Field), stop

**End screen**:
The level-owned overlay announcing the End state — a dimmed blockout with the
verdict title and the retry hint, faded in by tween; its numbers live in the
`Level authority`, its copy is structural (gADR-0010). Not part of the HUD —
gADR-0004's LINES contract is untouched.
_Avoid_: HUD (a different surface), menu, game-over screen (it also announces
the win)

**Retry**:
The restart verb that closes the GDD's one-more-try loop: the `retry` action
(Enter), live only in an End state, reloads the level scene so the whole run
re-derives from config — a fresh run, never an in-place respawn (gADR-0010).
_Avoid_: respawn (the rejected in-place variant), restart level (the demo is a
single level)

<!-- Format reminder — **Term**: one/two-sentence definition (what it IS, not what it does);
     _Avoid_: rejected synonyms. Group natural clusters under ### subheadings. -->

