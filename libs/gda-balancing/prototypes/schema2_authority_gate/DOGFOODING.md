# Dogfooding: Executable Kernel/LDB Authority Gate

## Conclusion

**Executable Kernel/LDB Authority Gate: PASS for the bounded architecture claim.**

The probe closes the semantic-authority uncertainty left by the earlier disposable prototypes:
two cross-language stacks can independently admit the same Kernel/LDB, execute machine law bodies,
derive Source → AST → Typed HIR → RIR from LDB judgments, emit byte-identical RIR, consume each
other's artifacts, execute deterministic atomic events, and make the Replay/Cross-evaluator split
without sharing semantic code.

This is strong evidence that bADR-0012/0013/0014/0015/0016/0018/0022 form a feasible and internally
consistent architecture. It is not evidence that every permanent 2.0 rule, type, package,
Diagnostic, vector, or RPG coverage row has already been authored.

## What changed or sharpened the design

### 1. The bootstrap boundary must be smaller and more explicit than the old probes

The viable boundary is a closed, non-self-hosted meta-VM. Higher-level Numeric, RNG, scheduler,
transition, and comparison laws are executable Kernel programs with declared parameters, results,
effects, refusals, and resource units. Both implementations now reject inconsistent declarations,
and runtime invocation enforces parameters, result type, and per-law resource accounting. The host
implements only the irreducible meta-opcodes, wire-type recognizers, and effect boundary. The old
`node-name + prose law` shape cannot pass a mutation witness and remains invalid.

This also sharpens the extension boundary: adding domain attributes, operations, rules, and
diagnostics remains LDB-driven; adding a new primitive wire type or meta-opcode is a Schema-major
Kernel change that requires every conforming host to implement and vector-test the new primitive.

No accepted bADR needs reversal. This result confirms bADR-0022's Kernel/LDB split and makes the
permanent Kernel deliverable concrete.

### 2. The LDB must own the compiler pipeline as data

The first implementation draft still named compiler phases and a default Runtime profile in host
code. Moving the ordered phase list, rule selection inputs, Runtime-profile selection, rules,
operation bodies, effects, Diagnostics, and comparison policy into the LDB removed those semantic
peers. Deleting or changing any consulted rule then either changes canonical RIR/behavior or causes
the same typed refusal in both implementations.

This confirms rather than changes bADR-0013/0022: an LDB that only admits operations is
insufficient; it must execute the judgments that construct HIR and RIR.

### 3. Identity-only tamper tests are necessary but not sufficient

Retaining an old identity after changing bytes proves rehashing, not semantic authority. The gate
therefore records every dynamically consulted law/rule and applies three witnesses:

- changed bytes under the old identity are refused before semantic use;
- a reidentified deletion is refused with no host fallback;
- a reidentified behavior mutation changes RIR/trace/observation or causes the same typed refusal.

All 19 required and dynamically consulted Kernel laws and all 7 dynamically selected LDB rules
passed the witnesses. Every consulted law also received an incompatible result-contract mutation;
representative mutations covered parameter, effect, refusal, and resource contracts. Renaming every
package Operation id, rule id, Diagnostic code, and the tested state symbol in authority/source data
also passed without changing either engine.

This should become a permanent conformance pattern, not a one-off prototype test.

The final review also exposed that mutation coverage is meaningful only after bundle-graph closure.
An unknown Source package, a package entry naming a missing Operation, or a missing default Runtime
profile initially escaped into host lookup errors. Package selection is now an executable LDB
judgment, package-to-Operation and default-profile closure are checked at admission, and each case
has a typed negative vector.

### 4. Cross-language exactness exposes wire decisions early

JavaScript cannot represent every Int64 value exactly as a JSON number. The probe therefore uses a
canonical decimal-string form at the unsafe boundary while keeping the checked-Int64 law in the
Kernel program. Both implementations agree on the exact upper-bound overflow refusal.

The architecture already requires the Kernel to fix integer encoding, numeric boundaries, and
canonical identity. The permanent specification must choose and vector-test one exact wire form;
it must not leave “JSON number” or a host numeric type as the decision. This is a specification
detail still to author, not an architecture reversal.

The same applies to Unicode: composed and decomposed strings are preserved as distinct code-point
sequences in this probe and hash identically across the two implementations. The permanent Kernel
must explicitly choose preservation or normalization and publish malleability vectors.

### 5. RIR embedding plus runtime reverse validation is workable

RIR embeds the complete selected Operation bodies/effects and Runtime/Diagnostic projections.
Evaluators independently rehash the RIR and Resolved Model, then compare the Operation table to the
exact LDB package release. A coherently reidentified but inconsistent Operation projection is still
refused. This confirms bADR-0013's canonical embedded-projection decision and avoids dynamic LDB
reinterpretation during execution.

### 6. Replay and independent-evaluator agreement must remain different artifacts

Each evaluator repeats successfully only under its own identical evaluator-bound Resolved Runtime
profile and produces a matching `ReplayComparison`. Python and JavaScript profiles are necessarily
different; they produce a matching `CrossEvaluatorComparison`, and attempting Replay is an
`evaluation` refusal. Neither comparison claims an Evidence assertion: it is a typed, bound input
to the later bADR-0018 Evidence-eligibility judgment, which must also prove resolved/evaluable and
publication prerequisites.

This confirms bADR-0014/0018 with no change.

The comparison artifacts now carry their own canonical identity and bind both Run identities, both
Resolved Runtime profiles, both Resolved Models, exact Kernel/LDB, Experiment, Scenario, portable
field policy, and comparison-policy identity. A bare identity pair is likewise insufficient as a
bootstrap handoff: the lowerers consume a complete content-addressed admission receipt. These
seals provide deterministic integrity inside this probe; durable publication anchors and issuer
authentication remain separate permanent storage/governance work.

### 7. Runtime-profile authority must close at every projection

Rehashing a modified RIR or Resolved Runtime profile is not enough to make it authoritative. Runtime
admission now compares the embedded profile, Diagnostic, and comparison-policy projections to the
exact admitted LDB; it also recomputes the selected Runtime-profile-definition identity. Replay and
Cross-evaluator comparison repeat that definition check before issuing a judgment.

### 8. Type/effect closure must be transitive across Kernel calls

The first effect checker saw explicit effect nodes but not effects declared by a nested Kernel-law
call, and its argument matcher implemented only a subset of admitted wire types. The two hosts now
derive transitive effects through validated law contracts and use the same closed wire-type root for
law invocation and Operation argument matching. Dedicated vectors cover all admitted wire types and
reject a hidden state read behind `call_kernel`.

### 9. Atomic refusal needs evidence about discarded buffers, not only final state

The runtime refusal vector commits one event, then makes the next event buffer an RNG draw, state
write, Signal, and child event before a duplicate write refuses. Both evaluators preserve the prior
commit, discard every current-event buffer, and produce equivalent terminal-audit content bound to
the exact model/profile identities. This confirms the bADR-0014/0015 split between prior committed
state and current-event rollback.

The prototype does not test durable multi-artifact publication or crash recovery; those remain a
permanent storage/conformance concern rather than a semantic-authority uncertainty.

### 10. Diagnostic authority needs reverse closure and behavior coverage

Checking only that rule and law refusal names resolve to Diagnostic definitions missed direct host
refusal exits. The corrected admission contract derives the complete reachable reason set from
Kernel laws, LDB rules and Operations, plus the closed host boundary; that set must equal the LDB
reason map, whose values must equal the Diagnostic catalog. Deleting any one of the 20
post-admission reason/Diagnostic pairs now prevents both implementations from admitting the LDB.
Behavior vectors also trigger all 28 Kernel- and LDB-owned Diagnostic codes at least once and check
the authoritative refusal stage.

This confirms the reverse-enumeration requirements already accepted in bADR-0015/0022. It also
sharpens their permanent conformance implication: catalog membership, static exit enumeration,
reverse-deletion tests, and behavioral code/stage coverage are separate gates; none substitutes for
the others.

### 11. An evidence digest must bind member names and boundaries

The first evidence index hashed a raw concatenation of source-file bytes. That proved the combined
byte stream but not which relative path owned each byte, so moving a boundary between adjacent
files could preserve the digest. The index now records a canonical map from every source-relative
path to the hash of that file and hashes the canonical manifest itself. It also binds the committed
prototype-source revision separately from the generated evidence refresh.

This does not add a new authority decision; it applies the already accepted content-addressed
artifact-set model. Permanent manifests must bind typed member names to member identities rather
than hash an unframed byte concatenation.

## Evidence summary

- full `2 × 2 × 2` exchange matrix: 8 successful paths;
- two textually different, alias-using Sources: byte-identical Package Lock, RIR, and Resolved
  Model across lowerers;
- consulted mutation coverage: 19 Kernel laws + 7 LDB rules, each with
  tamper/deletion/behavior witnesses, plus result-contract mutation for every consulted law;
- typed negative vectors: unknown opcode, bootstrap resource limit, ambiguous rule selection,
  Bool-as-Int, unknown Operation, effect mismatch, profile effect refusal, invalid RNG bound, draw
  budget, event/queue/rule-step budgets, backward scheduling, duplicate write rollback, Int64
  overflow, RIR tamper, inconsistent reidentified Operation projection, forged Run/Profile input,
  Kernel contract-surface mutations, missing package/profile closure, unsealed admission receipts,
  Runtime-profile projection drift, transitive effect drift, missing Kernel/LDB Diagnostic
  authority, Source rule/parse refusal, and invalid Cross-evaluator authority pairing;
- Diagnostic closure: deletion of every one of 20 post-admission reason/Diagnostic pairs is refused,
  and behavior vectors observe all 28 authoritative Kernel/LDB Diagnostic codes;
- deterministic vectors: phase/priority/FIFO order, Named-stream multi-draw isolation,
  pre-event-snapshot reads, prior-commit preservation, exact Replay, and Cross-evaluator comparison;
- static isolation: no A↔B/shared semantic import, no LDB Operation/rule/Diagnostic token in either
  engine, and no ambient random/time/UUID or dynamic evaluation escape.

Canonical evidence, evidence-member digests, the path-bound prototype-source manifest, and its
digest are in `evidence/evidence-index.json`.

## Remaining permanent work

The authority gate itself no longer justifies another disposable architecture prototype. The next
work should be the permanent Schema 2.0 specification and conformance implementation:

- author the complete Kernel opcode/law schemas and canonical wire rules, including exact integer
  and Unicode decisions;
- author the complete LDB fact/term/rule ontology, type/effect judgments, package/profile catalog,
  and normative vectors;
- expand from this discriminating slice to every RPG/Roguelike coverage row and every required
  negative/resource boundary, including Fixed/rounding, unbiased RNG/counter behavior,
  cancellation, subscriber ordering, reducers, exhaustive matching, and hostile Source shapes;
- implement durable artifact-set publication, crash recovery, and full terminal-audit retrieval;
- preserve the used-authority mutation gate and independent-evaluator matrix in permanent CI.

Another disposable prototype is warranted only if a later permanent-spec decision introduces a new
semantic root, open host extension, or cross-artifact authority boundary not exercised here.
