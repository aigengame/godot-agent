# Schema 2.0 genre conformance research corpus

This directory holds version-pinned research instances used to challenge the permanent Standard
Schema 2.0 conformance implementation. It deliberately combines empirical game-model research with
development feedback, but it is not a fourth semantic authority.

The authority boundaries are:

- game records under `games/` are research evidence about an external game version;
- `docs/standard-schema-2.0/genre-coverage.md` owns the declared RPG/Roguelike coverage contract;
- the Kernel Specification and admitted Language Definition Bundle own Schema semantics;
- permanent Golden scenarios and conformance vectors own executable support evidence;
- generated reports may summarize those sources but cannot close a coverage row by themselves.

## Instance contract

Each game instance owns one directory:

```text
games/<game-id>/
├── SOURCES.md
├── corpus.json
├── quantities.csv
└── findings.json
```

`corpus.json` must validate against `corpus.schema.json`. It records a pinned game/platform/content
scope, source provenance, selected mechanics, explicit state and Operation boundaries, RNG or
scheduling behavior, and executable oracle cases. `quantities.csv` is the human-auditable numeric
projection; it must use this exact header and must not become a parallel source of facts that
disagree with `corpus.json`:

```csv
mechanic_id,id,representation,kind,unit,role,domain,rounding,cap,source_refs
```

Rows are sorted by `(mechanic_id, id)`. Nullable values are empty strings; `source_refs` is the
sorted semicolon-joined source-id set. The JSON remains the research authority and the CSV is a
checked projection.

`findings.json` must validate against `findings.schema.json`. A finding records the actual edit
surface required to express a mechanic:

- `model_source`: ordinary game data only;
- `template_release`: starter/example/coverage distribution only;
- `domain_package`: a reusable game-domain type, capability, Operation, Diagnostic, or vector;
- `ldb`: a language judgment or post-admission language contract;
- `kernel`: a Schema-major primitive or bootstrap law;
- `host`: compiler/runtime behavior not derived from admitted authority;
- `out_of_scope`: deliberately outside the declared Schema claim.

A `kernel` or `host` requirement is an architecture stop signal, not a convenient implementation
shortcut. The finding must be reconciled into PRD #534, the Architecture, affected bADRs, and the
coverage matrix before implementation continues.

## Source policy

Every fact names one or more source ids and one confidence level:

1. `primary`: versioned shipped data, open-source code/data, official rules, or a reproducible
   runtime observation;
2. `corroborated`: two independent references or one reference plus a runtime oracle;
3. `provisional`: a community reference or inference not yet independently confirmed.

Provisional facts may discover a requirement but cannot serve as the sole oracle for a conformance
claim. Copyrighted assets, text, and bulk game data are not copied into this repository; record only
the minimal numeric/behavioral facts required by the selected mechanics and cite their provenance.

## Research acceptance

A game instance is research-complete only when:

- its exact game, platform, version, and content/DLC scope are pinned;
- every selected mechanic maps to one or more existing coverage rows or an explicit gap finding;
- each mechanic has at least one positive and one outcome/refusal/boundary oracle where applicable;
- quantities distinguish representation, nominal kind, unit, role, domain, rounding, and cap;
- hidden ordering, RNG consumption, live/snapshot reads, and state scope are recorded rather than
  compressed into prose;
- uncertainty remains visible and no provisional fact is reported as authoritative.

Research completeness is not Schema conformance. A coverage row closes only after its permanent
Source → HIR → RIR → runtime → public-artifact path and normative vectors pass.

## Cross-instance abstraction test

After instances are mapped into permanent fixtures:

- an ordinary attribute may require only a Model Source edit;
- a reusable mechanic may require only a complete Domain package/LDB/vector change;
- compiler/runtime code must contain no game id, package id, Operation id, or research token
  dispatch;
- authority-token renames must not require host edits;
- adding one instance must leave unrelated closed rows byte- and behavior-stable where their exact
  authority inputs did not change.

Failure of any rule is dogfooding evidence against the current architecture, not a reason to weaken
the conformance test.
