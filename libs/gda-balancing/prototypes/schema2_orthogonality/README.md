# Standard Schema 2.0 orthogonality/extensibility probe

This is a disposable, runnable design probe for PRD #534. It lives outside packaged `src/`,
changes no Standard Schema 1.x behavior, and is not a production Schema 2.0 implementation.

The repaired probe exercises one vertical path:

`LDB + content-addressed Domain-package releases + vectors → Model Source Package/use sites → Authoring AST → Typed HIR → selected-content Package Lock + exact-LDB-bound RIR → independently authored, exact-RIR-bound Experiment inputs/event sequence → evaluator/platform-bound Runtime profile → generic Event interpreter → executed Metric selectors/acceptance → Evaluation → descriptor-validated anchored publication`

It runs two design experiments:

1. add `focus` through a Model-Source-only symbol declaration using the already admitted
   `game.stat.generic` Quantity kind, `game:point` unit, and `exact-int-v1` Numeric profile; and
2. add resource reservation outcomes, interruption/refund, and effect apply/reapply/removal through
   one complete content-addressed, versioned `domain-package-release` authority per extension,
   plus Model Source use sites and independent Experiment event selection.

Each selected package operation is statically checked before RIR for closed node shapes, kind/unit
rules, permitted Numeric profiles, the complete state/signal/event/random effect surface, resource
bounds, and complete result-tag/payload coverage. All package/type/capability/profile/operation/
vector projections are generated and reverse-conformance checked. Runtime revalidates every RIR
use-site field against the exact selected release and requires a Resolved Runtime profile whose
evaluator and platform equal the actual executor before dispatch. Experiment Quantity inputs must
also satisfy the exact RIR symbol type and support.

## Run

From the repository root:

```console
UV_CACHE_DIR=/tmp/caw-uv-cache uv run --project libs/gda-balancing \
  python libs/gda-balancing/prototypes/schema2_orthogonality/e2e.py
```

The file is also pytest-compatible:

```console
UV_CACHE_DIR=/tmp/caw-uv-cache uv run --project libs/gda-balancing \
  pytest libs/gda-balancing/prototypes/schema2_orthogonality/e2e.py -q
```

Structured CLI example:

```console
UV_CACHE_DIR=/tmp/caw-uv-cache uv run --project libs/gda-balancing \
  python libs/gda-balancing/prototypes/schema2_orthogonality/cli.py \
  '{"command":"probe run","invocation_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","params":{"scenario":"effect_lifecycle"},"store":"/tmp/schema2-orthogonality-store"}'
```

## Defensible conclusion

The selected slice passes the repaired **Orthogonality/extensibility mechanism** question:

- one admitted generic Quantity attribute can be added only in Model Source and is observed in
  AST/HIR/RIR/runtime/Metrics/public artifacts without changing language/package/compiler/runtime
  authority;
- one complete package-release authority per selected mechanic generates every secondary surface;
- package programs cannot add unknown node fields, drift from declared signatures/kind/unit/
  Numeric/effects/results, or use unknown Kernel nodes;
- an independent Experiment owns inputs, event order, selectors, and acceptance, all of which are
  executed rather than bypassed by a host scenario branch, and it cannot be reused against a
  different RIR;
- an unselected LDB operation cannot execute through RIR;
- pre-dispatch refusal is distinct from post-dispatch rollback/audit, whose prototype-authorized
  Diagnostic has a stable code/message/tagged event location; and
- descriptor-owned closed outcome envelopes and artifact contracts plus a trusted prototype-local
  anchor detect malformed outcomes, incomplete/inconsistent sets, and coherently rewritten
  committed sets under the tested local-store model.

This remains **not** a complete Schema 2.0 PASS, Semantic-authority PASS, RPG completeness claim,
or Genre coverage result. Kernel-node, compiler-judgment, selector, acceptance, and prototype
Diagnostic semantics remain handwritten; package-history/semver uniqueness requires an external
release index; the current RIR still binds the exact whole LDB; general solving and portable
publication remain unvalidated; and no normative Replay or Evidence is issued. See
`DOGFOODING.md`.
