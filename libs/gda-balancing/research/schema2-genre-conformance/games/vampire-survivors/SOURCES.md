# Vampire Survivors research sources

## Pinned research scope

- **Game:** Vampire Survivors — First Survivaton
- **Platform:** PC, Windows, Steam public branch
- **Pinned release:** Update 1.15 ("The Wet One"), initial public content build
  `23569632`, built 2026-06-05 and announced 2026-06-06
- **Content:** base game only; every paid or free DLC depot is excluded
- **Scenario switches:** single-player, regular Mad Forest, Hyper/Hurry/Endless/Limit Break,
  Arcanas, Random Events, Random LevelUp, Golden Eggs, and DLC content disabled unless an oracle
  explicitly supplies a switch as an input
- **Recorded/accessed:** 2026-07-21

The build id fixes the binary/content reference more precisely than the marketing version alone.
It is the initial 1.15 Steam build, not a claim about the current Steam public or public-beta branch.
The public branch and the live game continue to change, so a future executable oracle must retain an
archived, legally obtained build receipt or repeat these observations against a newly pinned build.

This corpus records only small facts needed to challenge Schema 2.0 package boundaries. It does not
copy game assets, strings, complete wave tables, complete item pools, or other bulk copyrighted data.

## Source register

| Source id | Classification | Locator | What it supports and limits |
| --- | --- | --- | --- |
| `poncle-steam-1.15-release` | primary | [Official Steam announcement](https://store.steampowered.com/news/app/1794680/view/693137145499484494) | Officially identifies Update 1.15 as the Steam release and documents continued live updates, Random LevelUp, and spawn/performance changes. It does not publish the detailed numeric model. |
| `steamdb-build-23569632` | corroborated | [SteamDB build 23569632](https://steamdb.info/patchnotes/23569632/) | Third-party Steam metadata fixes the initial 1.15 content build and date; it is corroborated by the official release announcement, but is not a shipped-data dump. |
| `vswiki-magic-wand` | provisional | [Magic Wand](https://vampire-survivors.fandom.com/wiki/Magic_Wand) | Community-maintained targeting, level, projectile, and stat values. No local 1.15 runtime capture was available. |
| `vswiki-king-bible` | provisional | [King Bible](https://vampire-survivors.fandom.com/wiki/King_Bible) | Community-maintained duration/cooldown, orbit, hitbox-delay, and level values. |
| `vswiki-weapons` | provisional | [Weapons](https://vampire-survivors.fandom.com/wiki/Weapons) | Community explanation of rarity, upgrade activation, replacement-style evolution, cooldown reset, and six-slot behavior. |
| `vswiki-level-up` | provisional | [Level up](https://vampire-survivors.fandom.com/wiki/Level_up) | Community explanation of weighted eligible pools, distinct three/four-option draws, full-slot filtering, and fallback rewards. |
| `vswiki-passive-items` | provisional | [Passive items](https://vampire-survivors.fandom.com/wiki/Passive_items) | Community list of passive slots, Empty Tome rarity/effect, and stage-pickup exceptions. |
| `vswiki-mad-forest` | provisional | [Mad Forest](https://vampire-survivors.fandom.com/wiki/Mad_Forest) | Community reconstruction of the minute wave table. Internal enemy names and detailed spawn entries may drift. |
| `vswiki-powerups` | provisional | [PowerUps](https://vampire-survivors.fandom.com/wiki/PowerUps) | Community meta-progression values, including the first Growth rank and persistent gold purchases. |
| `gamespot-evolution` | provisional | [GameSpot evolution guide](https://www.gamespot.com/articles/vampire-survivors-how-to-evolve-weapons/1100-6508815/) | Independent description of six weapon/passive slots and Magic Wand + Empty Tome evolution. It predates 1.15. |
| `pcgamer-evolution` | provisional | [PC Gamer evolution guide](https://www.pcgamer.com/vampire-survivors-evolve-weapons-evolutions-guide/) | Independent description of max-level, passive, chest, and elapsed-time evolution requirements. It predates 1.15. |
| `wikipedia-gameplay` | provisional | [Vampire Survivors gameplay](https://en.wikipedia.org/wiki/Vampire_Survivors#Gameplay) | Independent high-level account of automatic attacks, waves, run time, six-slot builds, gold retention, and persistent upgrades; not a numeric authority. |
| `hagenberg-resource-analysis` | provisional | [Hagenberg game analysis](https://hagenberg.games/wiki/Vampire_Survivors) | Independent analysis distinguishing Run XP from retained gold and Meta upgrades. |
| `schema2-coverage-contract` | primary | [`genre-coverage.md`](../../../../docs/standard-schema-2.0/genre-coverage.md) | Project authority for the modeling obligation and refusal/boundary shape only. It never corroborates an external game fact. |

## Corroborated research syntheses

The following `research` source ids denote the narrow synthesis recorded in `corpus.json`. They are
not new external authorities; each is reproducible from the cited independent references.

- `research-auto-target-triangulation`: Magic Wand's nearest-target behavior and representative
  stats agree between `vswiki-magic-wand`, the overview in `vswiki-weapons`, and the high-level
  automatic-attack descriptions in `wikipedia-gameplay`. Exact equal-distance tie behavior remains
  unknown.
- `research-weapon-timing-triangulation`: King Bible's base values and active-duration-before-
  cooldown behavior agree within two independently maintained wiki tables/pages, but have not been
  verified against build `23569632`; detailed timing remains provisional despite the synthesis.
- `research-offering-triangulation`: weighted/distinct level-up offers, six-slot filtering, and
  fallback behavior agree across `vswiki-level-up`, `vswiki-weapons`, `vswiki-passive-items`, and
  `wikipedia-gameplay`. The exact game RNG algorithm and draw consumption are not public here.
- `research-evolution-triangulation`: max-level Magic Wand plus Empty Tome and an eligible chest
  replacing the base weapon agrees across `vswiki-weapons`, `gamespot-evolution`, and
  `pcgamer-evolution`. Patch-specific chest variants still need runtime capture.
- `research-run-reset-triangulation`: Run-local inventory/levels and retained gold/PowerUps agree
  across `vswiki-powerups`, `wikipedia-gameplay`, and `hagenberg-resource-analysis`.

## Confidence and oracle use

The corpus separates two kinds of expected observation:

1. **Game-mapping candidates** use the minimal external values above. Those that depend only on
   community data remain explicitly marked `candidate_only` and cannot close a coverage row.
2. **Schema boundary oracles** state what the existing coverage contract requires when the mapped
   source omits a tie policy, exceeds a declared budget, attempts an undeclared Meta transfer, or
   compares different replay identities. These are authoritative Schema expectations, not claims
   about how the proprietary game reports errors.

No local copy of build `23569632`, shipped data export, or instrumented runtime trace was available
to this research pass. Before any of these facts becomes a permanent Golden oracle, capture the
exact build/runtime observation and promote only the confirmed fields to `primary` confidence.
