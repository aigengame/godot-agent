# Slay the Spire research sources

Accessed: **2026-07-21**

## Pinned instance

- **Game:** *Slay the Spire* (the 2019 original, Steam App ID `646570`), not *Slay the
  Spire 2*.
- **Platform:** unmodded Steam PC release on Windows 10 x86-64.
- **Version:** game-reported `V2.3.4`, the public PC update announced by Mega Crit on
  2022-12-19.
- **Content exercised:** standard unseeded/seeded Ironclad runs at Ascension 0, using only the
  official base-game content present in `V2.3.4`. The corpus selects a few minimal cards, relics,
  enemies, and unlocks; it is not a copy of the game's content database.
- **Excluded:** *Slay the Spire 2*, the board game, Daily/Custom/Endless modes, Workshop mods,
  Downfall, console/mobile ports, beta branches, localization differences, and leaderboard or
  achievement behavior.

The Steam announcement pins the named release, but this research pass did not capture a Steam
depot manifest, executable digest, save file, or runtime trace. A later normative oracle must also
record those identities and reproduce the observation on a licensed local copy. Until then, the
mechanism syntheses below are corroborated research, not primary runtime observations.

## Source hierarchy

### Primary release identity

#### `official-steam-store`

- Kind/confidence: official documentation / **primary**.
- Locator: <https://store.steampowered.com/app/646570/Slay_the_Spire/>
- Relevant facts: App ID `646570`; title, developer/publisher, 2019 release; official description
  of the original as a single-player deckbuilding roguelike with cards, relics, variable runs, and
  four characters.
- Limit: the storefront does not specify operation order or numeric rules.

#### `official-steam-v2.3.4`

- Kind/confidence: official documentation / **primary**.
- Locator:
  <https://steamcommunity.com/ogg/646570/announcements/detail/5201125680698695379>
- Relevant facts: Mega Crit's `V2.3.4` PC release announcement dated 2022-12-19; the linked
  developer discussion also identifies `2.3.3` as the prior selectable branch.
- Limit: this is a release/version pin, not a semantic rules reference.

### Corroborated mechanic syntheses

Each id below is a local research synthesis. It is marked corroborated only for the narrow facts
listed. The references are community-maintained and may share historical material, so the
remaining primary-runtime gap is explicit rather than hidden.

#### `sts-turn-zones-crosscheck`

- Kind/confidence: research / **corroborated**.
- Locators:
  - <https://slay-the-spire.fandom.com/wiki/Combat_Mechanics>
  - <https://slay-the-spire.fandom.com/wiki/Gameplay>
  - <https://slaythespire.wiki.gg/wiki/Keywords>
- Corroborated facts: the player starts a normal turn with 3 Energy and draws 5 cards; card play
  consumes Energy; ordinary played cards go to the discard pile after resolving; remaining hand
  cards and Energy are cleared at end of turn; drawing from an empty draw pile shuffles the discard
  pile before drawing continues; Exhaust removes a card for the rest of combat.
- Uncertainty: exact internal action-queue timing, RNG algorithm, and draw consumption require a
  `V2.3.4` runtime trace.

#### `sts-card-combat-crosscheck`

- Kind/confidence: research / **corroborated**.
- Locators:
  - <https://slay-the-spire.fandom.com/wiki/Ironclad_Cards>
  - <https://slay-the-spire.fandom.com/wiki/Block>
  - <https://slaythespire.wiki.gg/wiki/Block>
  - <https://slay-the-spire.fandom.com/wiki/Keywords>
- Corroborated facts used by the corpus: unupgraded Strike costs 1 and deals 6 attack damage;
  unupgraded Defend costs 1 and grants 5 Block; unupgraded Bash costs 2, deals 8 attack damage,
  and applies 2 Vulnerable; Block absorbs attack damage before HP and is normally removed at the
  next turn boundary; Block is capped at 999; a Power persists for the combat while a Status card
  is combat-scoped.
- Uncertainty: special-case ordering, modifier rounding, and direct HP-loss exceptions are outside
  this slice unless a vector names them.

#### `sts-runic-cube-crosscheck`

- Kind/confidence: research / **corroborated**.
- Locators:
  - <https://slaythespire.wiki.gg/wiki/Runic_Cube>
  - <https://slay-the-spire.fandom.com/wiki/Runic_Cube>
  - <https://slay-the-spire.fandom.com/wiki/Offering>
- Corroborated facts: Runic Cube draws one card immediately after actual HP loss; Offering loses
  6 HP, gains 2 Energy, draws 3 cards, and Exhausts; the Runic Cube draw caused by Offering's HP
  loss precedes Offering's own draw; fully prevented HP loss does not trigger the relic.
- Uncertainty: the exact host queue representation is not asserted—only the observable order is.

#### `sts-reward-crosscheck`

- Kind/confidence: research / **corroborated**.
- Locators:
  - <https://slay-the-spire.fandom.com/wiki/Card_Rewards>
  - <https://slay-the-spire.fandom.com/wiki/Gameplay>
  - <https://slaythespire.wiki.gg/wiki/Relics>
  - <https://slaythespire.wiki.gg/wiki/Mechanics>
- Corroborated facts used by the corpus: a normal combat card reward offers 3 distinct choices and
  may be skipped; normal-combat base rarity weights are 60% common, 37% uncommon, and 3% rare;
  the rare offset begins at -5 percentage points, rises by 1 after a common roll, resets after a
  rare, and is capped at +40; ordinary relic rarity proportions are 50% common, 33% uncommon, and
  17% rare; relics have eligibility restrictions and are normally encountered at most once per
  run.
- Uncertainty: the exact Java RNG algorithm, named stream partition, rejection sampling, and draw
  count were not independently observed. The corpus therefore records deterministic policy inputs
  and required observations, not a fabricated seed-to-item table.

#### `sts-intent-crosscheck`

- Kind/confidence: research / **corroborated**.
- Locators:
  - <https://slaythespire.wiki.gg/wiki/Intent>
  - <https://slay-the-spire.fandom.com/wiki/Combat_Mechanics>
  - <https://en.wikipedia.org/wiki/Slay_the_Spire>
- Corroborated facts: an enemy Intent telegraphs its upcoming action and, for attacks, the damage;
  enemies act after the player's turn; Runic Dome hides the plan as an Unknown intent without
  removing the enemy's action.
- Uncertainty: individual monster move-selection probabilities are intentionally not copied or
  claimed.

#### `sts-meta-crosscheck`

- Kind/confidence: research / **corroborated**.
- Locators:
  - <https://slaythespire.wiki.gg/wiki/Ironclad>
  - <https://slay-the-spire.fandom.com/wiki/Ironclad>
  - <https://slay-the-spire.fandom.com/wiki/Ascension>
  - <https://slaythespire.wiki.gg/wiki/Keywords>
- Corroborated facts: a run ends independently of the next run; run-local deck, relic, combat, and
  encounter state do not carry over; Ironclad unlock group 1 adds Heavy Blade, Spot Weakness, and
  Limit Break to future availability; Ascension unlocks are character-scoped Meta progression.
- Uncertainty: the precise XP thresholds and save-file layout are not used by this corpus.

### Provisional lead

#### `sts-seed-order-provisional`

- Kind/confidence: community reference / **provisional**.
- Locators:
  - <https://www.reddit.com/r/slaythespire/comments/1039zmy/information_on_how_rng_with_rewards_work/>
  - <https://www.reddit.com/r/slaythespire/comments/1dsuo4b/how_to_work_with_relic_rng/>
- Lead only: reward results depend on the run seed and on which prior random-consuming actions
  occurred; relic pools appear to be ordered per rarity.
- Use restriction: this source may motivate RNG-state and action-trace fields, but it is not the
  sole source for any oracle and cannot close a conformance claim.

## Copyright and evidence boundary

This instance records only a handful of numeric constants and behavior relations needed to test
the architecture. It does not reproduce card text, art, localization, encounter tables, or a bulk
game database. The game's shipped files remain the primary evidence to capture during the future
licensed runtime-observation pass.
