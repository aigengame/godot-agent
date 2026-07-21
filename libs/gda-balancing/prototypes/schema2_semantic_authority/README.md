# Standard Schema 2.0 semantic-authority probe

This disposable probe asks a deliberately narrower question than its original name suggested:
given one shared, handwritten interpretation of a small kernel-node vocabulary, can two separately
implemented evaluator paths execute an LDB-composed RPG slice without RPG/domain branches in host
code? The answer for this fixture is yes. That does **not** prove that the Kernel Specification is
itself a complete executable semantic authority, Standard Schema 2.0 conformance, or Genre
coverage.

The probe is outside packaged `src/`, imports no 1.x code, and is intended to be discarded after its
feedback is absorbed.

## Run

From this directory:

```sh
python3 e2e.py
```

The subprocess adapter accepts one structured JSON request. Every artifact-producing command
requires a caller-supplied Invocation key of exactly 64 lowercase hexadecimal digits:

```sh
python3 cli.py '{"command":"build","invocation_key":"0000000000000000000000000000000000000000000000000000000000000000","params":{},"store":"/tmp/schema2-authority-store"}'
python3 cli.py '{"command":"inspect","invocation_key":"0000000000000000000000000000000000000000000000000000000000000000","params":{"target_command":"build"},"store":"/tmp/schema2-authority-store"}'
```

The content-addressed Command descriptor is the sole per-command authority for input/defaults,
handler binding, declared outcomes, channels/exits, and allowed artifact-set kinds. The canonical
command-input identity binds descriptor + command + bound params and deliberately excludes the
Invocation key and store/output locator.

## What the slice reaches

The direct harness traverses:

1. an identified Kernel Specification data record;
2. LDB admission by two independent bootstrap implementations;
3. equivalent Model Source Package forms;
4. two Authoring AST and Typed HIR paths;
5. byte-identical semantic RIR with separate Debug Maps and Build receipts;
6. canonical Package Lock plus Resolution receipt;
7. one LDB-owned Runtime profile definition plus concrete budgets;
8. evaluator A over compiler B's RIR and evaluator B over compiler A's RIR;
9. LDB-composed `Reserved | Insufficient`, exact Int/RNG, buffered event writes, Metric emission,
   Evaluation runs, and Metric datasets; and
10. the Replay eligibility gate.

The gate stops there. bADR-0014 requires an identical Resolved Runtime profile for independent
evaluator comparison, while that artifact is also required to bind evaluator/platform identity.
The two honest profiles therefore differ. The probe emits an `evaluation` decision-required gate
report and issues neither a Replay comparison nor a `reproducible` Evidence assertion. It does not
silently replace the accepted rule with “same semantic profile”.

Successful `build` and `run` commands publish complete invocation-level artifact sets. A runtime
refusal first atomically publishes a prototype-local, referentially closed dependency set around
the terminal audit, then emits typed refusal on stdout with exit 2 and a retrievable
receipt/locator. That set is not proof of the full terminal-audit schema or semantics: trace-prefix,
last-snapshot, refusing-event, rollback-fact, reproduction-id, and diagnostic-location contracts
remain unvalidated. Usage and key conflicts use stderr/exit 3; publication or internal failures use
stderr/exit 4. Exact retry after commit replays the stored original outcome without dispatch.

The `compare` descriptor is deliberately gate-only and non-artifact-producing. Its only reachable
result is the typed `evaluation` refusal described above; it declares no success outcome variant,
accepts no parameters, and cannot issue Evidence.

## Independence boundary

- The bootstrap files independently implement selection, premise execution, binding, expression
  admission, judgment construction, and malformed-container diagnostics.
- The compilers independently parse/bind/lower the fixture and exclude provenance from RIR.
- The evaluators share canonical wire helpers and CPython's SHA-256 primitive, but no semantic
  implementation. Both contain zero RPG operation ids. They independently validate the exact
  Kernel/LDB/Package Lock/RIR/profile chain, implement exact Int/RNG, enforce closed outcome tags,
  read the pre-event snapshot, buffer writes, reject duplicate slot writes, and commit once.
- Both bootstraps and both evaluators independently recompute the Kernel artifact identity before
  using its declared laws. A changed law retaining the old identity is therefore rejected on all
  four paths.

The actual node laws are still coordinated handwritten code. The `KERNEL_SPEC` record mostly names
nodes and selected laws; it does not supply an executable formal semantics from which either
evaluator is generated. This proves removal of RPG host dispatch and cross-path connectivity only,
not independent implementability of the kernel laws.

## Executable vectors

The 23 groups cover bootstrap unknown/ill-typed/malformed inputs; ambiguous/removed/changed rules;
four-path Kernel rehash; equivalent and semantic source mutations; crossed compiler/evaluator
execution; exact RNG and budget boundaries; runtime profile/identity tampering; closed outcome
tag/payload failures; pre-event reads, buffered writes, duplicate-write rollback; no
unknown-primitive fallback; Replay profile conflict/no Evidence issuance; descriptor reverse
conformance; 64-hex key binding; canonical-input exclusion; pre-dispatch conflict; exact outcome
replay; channel/exit algebra; atomic fault visibility; and member/receipt/commit-marker rehash,
coherent-rewrite, and forged-identity rejection.

The prototype maps identity, Kernel/LDB binding, and safe-admission failures to `ingress`; admitted
rule/fact container, structural, and semantic failures map to `static`; evaluator failures map to
`runtime`. This is an executable local policy, not yet a Standard Schema diagnostic-stage
authority.

## Non-claims

The probe does not validate executable kernel laws, complete LDB Source → HIR → RIR judgments,
static variant exhaustiveness/payload typing, general package solving, the multi-event scheduler,
signals/cycles, distributed publication adapters, a positive independent-evaluator Replay policy,
full terminal-audit conformance, LDB-owned diagnostic-code/stage semantics, or independent Evidence
validators. The local commit marker anchors the original receipt against coherent member/record
rewrites only while the local index/filesystem trust boundary holds; full-index compromise and
distributed stores remain non-claims. Passing all groups must not close a Standard Schema or Genre
coverage gate. See `DOGFOODING.md` for the design consequences.
