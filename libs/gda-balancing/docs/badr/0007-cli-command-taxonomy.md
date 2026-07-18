---
status: proposed
---

# CLI command taxonomy: domain-object groups under one agent-facing binary

PRD #501 US19 requires a CLI agents can drive in automation, and the PRD addendum
(2026-07-15) adjudicates that the CLI's interface style follows `gda`. This bADR fixes
the command taxonomy — the tree shape and its naming law — for design gate #518. The
semantics of individual commands stay with their owning issues (#504, #505/#506,
#509/#510); no command may be named outside this tree.

## Decision

- **One binary, full family name: `gda-balancing`** *(new ground)*. The console script
  is `gda-balancing`; `python -m gda_balancing` is its equivalent module invocation
  (#502 registers both). No abbreviation: the `gda-` prefix is the product-family
  brand (BALANCING-CONTEXT), agents do not economize keystrokes, and an abbreviated
  second name would be a second identity to keep consistent.

- **Grouped invocation `gda-balancing <group> <command>`; groups are domain objects**
  *(adopted-from-gda: ADR-0005)*. Every group names a noun from the toolkit's shared
  language, all tokens kebab-case. Delivery phase never appears in the tree
  *(adopted-from-gda: ADR-0005/0019 — a command's phase is metadata, not position)*.

- **v1 groups:**
  - **`design`** — operations on a `Design document`: `design validate`,
    `design format` (canonical round-trip emission, bADR-0005). Owned by #504.
  - **`template`** — operations on `Genre template`s: `template list`, `template get`.
    The instantiation command's shape is owned by #505/#506 within this tree and the
    verb law below.
  - **`schema`** — the Standard Schema's self-description artifacts (bADR-0009).
    **Recorded deviation from gda**: in `gda`, `schema` names the aggregate
    command-surface manifest (ADR-0012); here the word belongs to the toolkit's
    central domain object — the `Standard Schema` — and the surface manifest takes the
    reserved name `manifest` instead (bADR-0009). One word, one owner.

- **Reserved Phase-2 groups: `evaluation` and `tuning`** *(recorded deviation from
  gda ADR-0005, which enumerates no future surface up front; the reservation
  pattern mirrors bADR-0001's reserved sections)*. Noun groups after the glossary's
  `Evaluation method` / `Tuning method` — not verb names (`simulate`, `tune`),
  which would break the groups-are-nouns law. Reserved means: the names are fixed
  now so no later surface squats on them, they are **absent** from the v1 surface
  (invoking one is an unknown-command usage error, bADR-0008), and #509/#510 fill
  them at delivery. Why deviate: this surface has already had one name contention
  (`schema` vs `manifest`, above) and the Phase-2 surfaces are certain per PRD
  #501 — only their shapes are open. Reserving the two nouns costs nothing
  publicly (a reserved name has no surface to break, and can still be renamed by
  amending this record before delivery), while an accidental squat *would* force a
  breaking rename later.

- **Meta commands stay ungrouped: `version`, `help`** *(adopted-from-gda: ADR-0005)*.
  `version` reports the toolkit package version and the supported Standard Schema
  line as **distinct fields** — the two versions are independent authorities and are
  never conflated (bADR-0001); it is a registered, `--schema`-bearing command like
  any other (bADR-0011). **`help` (and `--help`) is the surface's one human-facing
  exemption**: it emits framework help text on stdout at exit 0, is not
  descriptor-registered, and is excluded from `--schema` and the future `manifest`
  (bADR-0009/0011) — the JSON result contract governs every *registered* command,
  and this exemption is decided here rather than left to framework accident. A
  third meta name is **reserved**: `manifest`, the deferred aggregate surface
  manifest (bADR-0009) — reserved on the same terms as the Phase-2 groups above.

- **Verb vocabulary adopted verbatim** *(adopted-from-gda: ADR-0005)*: `create`/
  `delete` for standalone entities vs `add`/`remove` for sub-entities in a container;
  `get` (one entity), `list` (enumerate), `set` (mutate a property); constant meaning
  across groups, no synonyms (`read`, `edit`, `update` are banned). Domain verbs
  (`validate`, `format`) are sanctioned where the family precedent sanctions them.

## Considered options

- **Domain-object groups + reserved Phase-2 nouns** (chosen) — the family's law,
  extensible across phases without renames.
- **Flat command list** (rejected) — the surface spans four functional areas plus
  Phase-2 growth; a flat namespace forces prefix-encoding the group into command
  names, which is the tree again but unenforced.
- **Verb-named Phase-2 groups (`simulate`, `tune`)** (rejected) — groups are nouns;
  a verb group collapses the group/command distinction and drifts from ADR-0005's
  discipline the family adjudication points at.
- **Abbreviated binary (e.g. `gdab`)** (rejected) — a second identity with no agent
  benefit; search and docs anchor on the product name.

## Consequences

- #502 registers the console script + module entry and the first meta command
  (`version`); every subsequent CLI-surface issue names its commands inside this tree.
- The `schema`-vs-`manifest` naming deviation is load-bearing for bADR-0009; changing
  it later renames a public surface (breaking), so it is decided here, once.
- Reserved group names are enforceable by the conformance harness (bADR-0011): the
  registry must not contain `evaluation`/`tuning` commands until their owning issues
  land.

## References

- gda ADR-0005 (taxonomy), ADR-0019 (placement by domain object) — reference input
  per the PRD #501 addendum; this bADR is the binding authority for this toolkit.
- Research provenance (non-normative): issue #518 comment (2026-07-18).
