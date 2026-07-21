# Dark Souls Remastered research sources

Accessed: **2026-07-21**

This instance pins **Dark Souls Remastered for Steam/Windows, App Version 1.03, Regulation
Version 1.04, offline single-player mechanics, including the bundled Artorias of the Abyss
content**. Patch 1.03 and the bundled DLC scope are official facts. The Regulation 1.04 title-screen
label is retained as a provisional pin until a legally owned Steam installation is captured in a
reproducible runtime-observation record.

The corpus is a deliberately small mechanism sample, not a dump of game parameters or copyrighted
assets. Community-derived numbers are recorded only where two independent references agree or an
open parameter definition corroborates the field structure. They remain research oracles, not
Standard Schema authority and not proof that a Genre coverage row is closed.

## Source hierarchy

### Primary

- `official.patch-1.03` — Bandai Namco, *Dark Souls: Remastered - Patch note 1.03*.
  <https://en.bandainamcoent.eu/dark-souls/news/dark-souls-remastered-patch-note-103>
  The official notice dates the Steam/PC App Version 1.03 update to 2018-07-11. It establishes the
  application version, not balance-formula values or the later Regulation label.
- `official.steam-product` — Steam product page for app `570940`.
  <https://store.steampowered.com/app/570940/DARK_SOULS_REMASTERED/>
  The publisher page identifies the Windows release and states that Artorias of the Abyss is
  included.
- `official.web-manual-actions` — FromSoftware, *Dark Souls Remastered Web Manual*, PS4,
  “Action 1”. <https://www.fromsoftware.jp/manual/darksoulsremastered/ps4/action1.html>
  The manual states that sprinting consumes stamina, rolling/backstepping are distinct actions,
  lock-on is explicit, and the player may switch the locked target.
- `official.web-manual-equipment` — FromSoftware, *Dark Souls Remastered Web Manual*, PS4,
  “Menu 2”. <https://www.fromsoftware.jp/manual/darksoulsremastered/ps4/menu2.html>
  The manual states that equipped weapon/armor weight constrains the character and unmet required
  stats prevent equipment from delivering its intended performance.
- `paramdex.ds1r-defs` — `soulsmods/Paramdex` commit
  `ff7245e524329bc3eab00036723d2bd53384cedf`, directory `DS1R/Defs`.
  <https://github.com/soulsmods/Paramdex/tree/ff7245e524329bc3eab00036723d2bd53384cedf/DS1R/Defs>
  The open definitions expose the shipped/reverse-documented parameter shapes used by the sample:
  `EquipParamWeapon`, `ReinforceParamWeapon`, `AtkParam`, `SpEffect`, `ShopLineupParam`,
  `LockCamParam`, and `CharaInitParam`. The `LockCamParam` definition declares a default maximum
  character lock radius of 15 metres. A PARAMDEF describes fields and domains; it does not provide
  the copyrighted row data needed to assert every concrete game value.
- `dsmapstudio.tool` — `soulsmods/DSMapStudio` commit
  `97bc264cbc3e82a783eb017f57edf651f8ba000b`.
  <https://github.com/soulsmods/DSMapStudio/tree/97bc264cbc3e82a783eb017f57edf651f8ba000b>
  The tool documents a parameter editor and direct support for an unpacked-by-default Dark Souls
  Remastered installation. It is the proposed extraction path for a future local shipped-data
  observation; the repository contains no copied game rows used here.

### Corroborated community research

- `community.endurance-stamina` — Dark Souls Wikidot, “Endurance” and “Stamina”, cross-checked
  against the independent Fextralife stamina-regeneration measurement sheet.
  <https://darksouls.wikidot.com/endurance>, <https://darksouls.wikidot.com/stamina>,
  <https://darksouls.wiki.fextralife.com/file/Dark-Souls/Dark%20Souls%20Stamina%20Regeneration%20Data.pdf>.
  The tables report 160 maximum stamina and 80.0 equip burden at Endurance 40, plus a default
  45-stamina-per-second recovery rate below 50% equip burden. The cap is also independently listed
  by the site’s “Stats” page; exact recovery timing still needs a pinned runtime capture.
- `community.damage-function` — Dark Souls Wikidot, “Damage Calculation”, revision 6
  (2022-02-14), cross-checked against Thomas Amory’s independent 2012 analysis.
  <https://darksouls.wikidot.com/damage-calculation>,
  <https://tl.net/blogs/396507-dark-souls-stats-i-damage-formula-and-analysis>.
  These sources agree on the nonlinear attack/defense function and on calculating each physical or
  elemental component before summing. The corpus uses only exact branch points whose arithmetic is
  unambiguous; a runtime trace remains required before promotion to a normative oracle.
- `community.longsword` — Dark Souls Wikidot, “Longsword”, cross-checked against the independently
  maintained Dark Souls Fandom “Longsword” table.
  <https://darksouls.wikidot.com/longsword>,
  <https://darksouls.fandom.com/wiki/Longsword>.
  Both report 80 base physical attack, 3.0 weight, 10 Strength/10 Dexterity requirements, and a
  1,000-soul Andre purchase. Wikidot additionally reports the normal +5 base attack as 120 and the
  first five Titanite Shard costs as `1,1,2,2,3` (nine total). The sources describe the shared
  Dark Souls data rather than a captured Remastered row, so the Remastered equality is corroborated
  rather than primary.
- `community.poison` — Dark Souls Wikidot, “Poison” and “Poison Mist”, cross-checked against the
  independently maintained Dark Souls Fandom “Poison (Dark Souls)” table.
  <https://darksouls.wikidot.com/poison>, <https://darksouls.wikidot.com/poison-mist>,
  <https://darksouls.fandom.com/wiki/Poison_(Dark_Souls)>.
  The Remastered entries report Poison Mist buildup of 20 per 0.2 seconds and, once triggered,
  3 HP per 0.8-second tick for 180 seconds (675 total). The sources also distinguish buildup,
  activation, immunity/cure, scheduled damage, and expiry.

### Provisional

- `community.regulation-1.04` — player title-screen reports for current Steam installations.
  <https://www.reddit.com/r/darksouls/comments/oz56g8/app_ver_103_regulation_ver_104/>
  This supports the Regulation 1.04 label only. It is not used as the sole source of an oracle.

### Schema contract

- `schema2-coverage-contract` —
  [`genre-coverage.md`](../../../../docs/standard-schema-2.0/genre-coverage.md).
  This source belongs to the `schema_contract` authority domain. It supports only the nominal-kind
  mismatch boundary required by Standard Schema; it does not corroborate Dark Souls behavior or
  raise the confidence of any external-game fact.

## Uncertainty and promotion requirements

1. The exact Steam depot/build identity and a title-screen capture are absent. Before any permanent
   conformance fixture is claimed to reproduce Dark Souls Remastered, capture the installed depot,
   executable identity, App/Regulation labels, and offline settings.
2. PARAMDEF files prove the existence and shape of fields, not the concrete values of a specific
   shipped row. Extract only the named rows from a legally owned installation, hash the source
   bundle locally, and publish a derived observation record rather than copyrighted bulk data.
3. The nonlinear defense formula, stamina recovery rate, Longsword values, and poison timing are
   corroborated community research. Each needs an instrumented or frame-counted runtime oracle
   before becoming normative Schema evidence.
4. Target switching is official, and the open `LockCamParam` shape exposes a 15-metre default, but
   visibility, angle, occlusion, tie order, and exact inclusive boundary behavior are not established
   here. The corpus therefore tests only a singleton eligible target and an unambiguous out-of-range
   empty outcome.
5. Scenario-supplied values such as a 20-stamina action cost are probe inputs, not claims that the
   Longsword consumes that amount. The research oracle checks resource atomicity around a declared
   cost; a future shipped-data observation must supply the actual action-specific cost.
