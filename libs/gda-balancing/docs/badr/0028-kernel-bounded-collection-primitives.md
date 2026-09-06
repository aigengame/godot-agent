---
status: proposed
---

# Admit bounded collection primitives in the Kernel

Issue #547 delivers the `RPG-TARGET-01` and `RPG-CHECK-01` tracer rows. `RPG-TARGET-01` requires a
Target query: a deterministic, typed selection over a dynamic entity set with declared filtering,
stable ordering, cardinality, tie-breaking, and empty-result behavior (bADR-0017). The provisional
Kernel runtime profile `standard.exact-int64-event-v1` admits these Runtime nodes:

- expression: `add`, `constant`, `copy`, `equal`, `floor-divide`, `greater-than-or-equal`, `if`,
  `less-than`, `less-than-or-equal`, `lookup`, `is-empty`, `maximum`, `multiply`, `subtract`,
  `value`;
- effect: `subtract-state`, `write-state`, `schedule`, `cancel`;
- control: `draw`, `precondition-greater-than-or-equal`, `require`, `guard-block`, `invoke`.

None of them can filter, order, truncate, or count an admitted `List`. `lookup` reads one element
by an exact index or one Record field by name. `is-empty` observes emptiness. No node constructs a
`List` or an element. A package Operation body is a composition of these nodes, so `game.query`
cannot express target selection with the current vocabulary.

bADR-0022 already places "statically bounded aggregates" inside the pure-expression judgment and
requires that "aggregate evaluation order and bounds are explicit rules, never host-container
order". The judgment names the capability; the provisional Kernel has no node for it. Under
bADR-0022's provisional-baseline rule, a demonstrated gap may reopen the architecture gate and
replace the exact Kernel identity before a maintainer records `Kernel baseline frozen` in PRD #534.
Issues #640 (`is-empty`, `require`, `guard-block`) and #546 (`integer-floor-divide`) used this rule.

## Decision

### Four orthogonal expression nodes

The Kernel adds four nodes to the `expression` family. Each node reads one admitted bounded `List`
from a local or a port, produces one local, writes no state, consumes no random stream, and cannot
contain a body.

| Node | Required members | Result | Semantics |
| --- | --- | --- | --- |
| `where-equal` | `node`, `target`, `value`, `key`, `operand` | `List` with the input element type and maximum length | Keeps every element whose Record field `key` is canonically equal to `operand`; input order is preserved. `operand` is a local reference or a typed literal with the same value contract as the field. |
| `order-by` | `node`, `target`, `value`, `key`, `direction`, `tie_key` | `List` with the input element type and maximum length | Stable sort. Elements are ordered by field `key` in `direction` (`ascending` or `descending`), then by field `tie_key` in the same direction, then by input order. Both fields must be exact-int64 scalar Quantities. |
| `take` | `node`, `target`, `value`, `count` | `List` with the input element type and maximum length | Keeps the first `count` elements in input order. `count` is a local reference or an integer literal. A literal must select exactly one reachable integer Literal Typing Profile that the selected Runtime profile admits (bADR-0022); a local must carry only value contracts that match such a profile, the law that already types a `lookup` local index. A `count` larger than the length keeps every element. A negative `count` raises the `structured-take-negative` refusal. |
| `count` | `node`, `target`, `value` | exact-int64 scalar with unit `1`, typed like an integer `constant` | The element count of the input `List`. |

Common rules:

- **Static typing.** Lowering refuses a `key` or `tie_key` that is not a field of the element
  Record, an `operand` whose value contract differs from the field, an `order-by` field that is not
  an exact-int64 scalar Quantity, a `value` that is not an admitted bounded `List`, and a `count`
  whose value contract matches no integer Literal Typing Profile admitted by the selected Runtime
  profile: a Kernel Boolean, a local or literal with a different kind, unit, representation, or
  Numeric policy, and a literal with zero or several matching profiles are all refused. These are
  `static`-stage refusals under the existing `language.structured_value_type_mismatch` diagnostic
  family owned by `standard.schema`; Runtime never guesses a type from a same-name local.
- **Deterministic charge.** Each node charges `1 + n` `event-steps`, where `n` is the input element
  count at evaluation time. The charge is replayable and bounded by the `List` type's static
  `maximum_length`. Sorting work is not metered separately; the static bound caps it.
- **Explicit element order.** `where-equal` and `take` preserve input order. `order-by` defines its
  complete order, including ties. Host-container order never decides a result.
- **No growth.** No node constructs elements, mutates a `List`, joins two `List`s, evaluates a
  nested body, or iterates beyond the static maximum length.

### Exposure through `standard.schema@2.5.0`

- `standard.schema@2.5.0` exposes the nodes as the structured Operations
  `standard.schema.list-where-equal-v1`, `standard.schema.list-order-by-v1`,
  `standard.schema.list-take-v1`, and `standard.schema.list-count-v1` under the existing
  `structured.lower` rule, beside `list-at-v1` and `list-empty-v1`. It adds the diagnostic
  `runtime.structured_take_negative` and the reason `structured.reason.take-negative`.
  `standard.schema@2.4.0` remains available unchanged.
- The runtime profile `standard.exact-int64-event-v1` lists the four nodes in `value_nodes`. An
  Evaluator Capability Manifest must advertise them; Runtime admission refuses an evaluator that
  does not.
- The Kernel adds one `runtime.node.<name>` contract-probe vector per node. `standard.schema@2.5.0`
  binds package vectors for positive, boundary, and refusal cases. The production evaluator and the
  independent reference evaluator implement the nodes separately and must agree on every vector.

### Identity consequence

This decision replaces the provisional Kernel content identity. It is the third reopening after
#640 and #546. Every LDB, Package Release, Package Lock, RIR wrapper, Resolved Runtime profile,
receipt, and maintained example binding is rebuilt against the replacement identity, and the
independent consumer's pinned identity moves with it. Evidence bound to the #546 identity does not
carry forward. Maintained examples that do not select `standard.schema@2.5.0` keep byte-identical
Package Lock and RIR semantic payloads; only their wrapper and downstream identities change.

### Non-goals

The following bounded operations are not admitted by this decision. Each is a later minor addition
when a consumer demonstrates the need before the freeze, and a Schema-major change after it:

- a `where` node with a parametric comparison operator;
- ordering over `Enum` or `Ref` fields, or over a nested key path;
- `map`, `fold`, `join`, `distinct`, or any node that constructs or updates elements.

Unbounded iteration, recursion, and host callbacks remain architectural exclusions under bADR-0022.
They are not deferred additions: a provisional reopening revises the bounded primitive set, and a
decision that admitted one of them would have to reopen bADR-0022 and its termination and effect
guarantees explicitly.

## Theory and external references

These are design inputs with explicit provenance. None is normative for Standard Schema 2.0.

- SQL query operators separate selection, ordering, and truncation into composable clauses over an
  ordered result: `WHERE`, `ORDER BY`, and `FETCH FIRST` (`LIMIT` in common dialects). SQL leaves
  tie order unspecified unless the query states it. The decision keeps the separation and removes
  the unspecified case by defining tie order. Codd's relational model is the ancestor of these
  operators, but its relations are sets in which row order is immaterial (§1.3), so it does not
  establish this ordered-`List` contract; the analogy is to the SQL query pipeline, not to
  relational algebra. Source: ISO/IEC 9075 (SQL) general concepts; Codd, "A Relational Model of
  Data for Large Shared Data Banks" (1970), §1.3.
- Total functional programming admits structural recursion over finite data and rejects general
  recursion so that every program terminates. Statically bounded `List` types plus the four nodes
  give the same guarantee without a recursion construct. Source: Turner, "Total Functional
  Programming" (2004).
- Stable sorting is the standard contract when equal keys must keep a defined order. The decision
  goes further and names the secondary key and the final input-order rule so that two independent
  evaluators cannot disagree on ties. Source: Knuth, *The Art of Computer Programming*, vol. 3,
  §5 (stability definition).

## Considered options

- **One composite `select` node** (rejected). A single node that filters, orders, and truncates in
  one step would freeze the shape of a target policy inside the Kernel. Encounter composition
  (#563), wave spawning (#569), and deck zones (#572) need the parts separately.
- **Unrolled package bodies** (rejected). A body could read elements `0..maximum_length - 1` with
  `lookup`, but no node builds an output `List`, ordering would require an unrolled sorting network,
  and every body would be bound to one maximum length.
- **Host-implemented target query** (rejected). bADR-0017 states that no package may hide target
  selection inside evaluator code. It would also break Core Extension Invariance by adding a
  genre-specific evaluator path.
- **Parametric `where` now** (deferred). Equality covers every consumer in the tracer: faction,
  life state, and `Ref` matching. A comparison member without a consumer would be an untested
  extension point.
- **Comparison-count charge for `order-by`** (rejected). Metering comparisons would make the charge
  depend on the sorting algorithm. `1 + n` is deterministic, evaluator-independent, and bounded by
  the static maximum length.

## Consequences

- Package authors gain a closed, reusable vocabulary for bounded selection over any admitted Record
  `List`. `game.query` can express filtering, stable ordering, cardinality, and tie-breaking as
  data, and later genre packages reuse the same nodes.
- The Kernel primitive set grows by four generic nodes with no reward, target, entity, or genre
  dispatch. Core Extension Invariance is preserved: later genres add packages, not nodes.
- The Kernel identity churns again before the freeze. Every dependent identity and every example
  README pin is rebuilt in the implementation, and independent-consumer evidence must be reissued.
- Both evaluators grow by four node implementations and their vectors. A divergence between them is
  caught by the shared vector inventory, not by a shared helper.

## Validation

- Kernel contract-probe vectors `runtime.node.where-equal`, `runtime.node.order-by`,
  `runtime.node.take`, and `runtime.node.count` fix member sets, typing, charge, and refusals.
- `standard.schema@2.5.0` package vectors cover: an empty input; every element filtered out; equal
  primary keys resolved by `tie_key`; equal primary and tie keys resolved by input order after an
  input permutation; `descending` order; `take` larger than the length; `take` of zero; a negative
  `take` refusal that leaves state unchanged; a `take` whose `count` is a Kernel Boolean, has a unit
  other than `1`, is not a scalar, or selects a Numeric policy the Runtime profile does not admit,
  each refused at the `static` stage; `count` of an empty and a full `List`; and the exact `1 + n`
  charge for each node.
- The production evaluator and the independent reference evaluator each compare their observations
  with every shipped vector expectation. Agreement between the two consumers alone is not evidence.
- Maintained examples that select `standard.schema@2.4.0` keep byte-identical Package Lock and RIR
  semantic payloads after the Kernel replacement.
- Ruff, Pyright, sealed-LDB verification, inventory closure, and the complete gda-balancing suite
  pass on the implementation head.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- Issue #547 — Deliver dynamic targeting and named-random check coverage.
- Issues #640 and #546 — earlier provisional-baseline reopenings.
- bADR-0016 — closed type core and versioned package extensions.
- bADR-0017 — genre templates and coverage contract (Target query ownership).
- bADR-0022 — machine-readable language rules and the provisional-baseline rule.
- bADR-0023 — sealed multi-member Language Definition Bundle.
- `docs/standard-schema-2.0/genre-coverage.md` — `RPG-TARGET-01` and `RPG-CHECK-01` rows.
