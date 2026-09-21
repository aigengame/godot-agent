# Bounded priority-window falsifier

- Issue: [#878](https://github.com/aigengame/godot-agent/issues/878)
- Parent: [#865](https://github.com/aigengame/godot-agent/issues/865)
- Replacement baseline: `1596e77ea6807d4b91b8709da52c72eed346b0de`
- Replacement branch: `codex/gda-878-minimal-rebuild`

## Purpose and status

This record defines the finite S6b implementation and its acceptance boundary. It
replaces PR #1000 as the implementation candidate. PR #1000 and its branch remain
read-only exploration evidence because they contain an origin/main merge and
accumulated infrastructure outside the amended #878 acceptance criteria.

The replacement branch starts exactly at the shared development baseline. It must
not merge origin/main, release, or another integration line. Before review, its
history must contain one implementation commit, no merge commit, and changes only
under `libs/gda-balancing/`.

## Finite implementation boundary

The maintained witness is one `example.priority-window` Source with two Experiment
inputs: the full counter chain and a consecutive-pass variant. Both execute admitted
reusable Operations through the public Model and Experiment path. Neither fixture
prescribes Event Trace or Runtime result bytes.

The only extension rename table is a literal bijection for these twelve coordinates:

- four `game.action` Types: `Counter`, `Counters`, `Outcome`, `PendingIds`;
- five `game.action` Operations: `append-counter`, `cancel-reverse-step`,
  `count-match`, `propose`, `resolve`;
- three `game.turn` Operations: `open`, `pass`, `respond`.

Ordinary JSON strings, Source entrypoint names, unrelated packages, conformance
vectors and artifact families are not inventory candidates. The witness must not
grow a recursive scanner, arbitrary string rewrite, registry, compatibility mode,
fallback, new scheduler, new host callback, genre branch or formal claim pipeline.

The selected-dependency binding is derived independently from each actual eight
member Model result. It binds:

- the canonical SHA-256 identity of the complete admitted `selected_semantics`;
- the RIR semantic identity;
- the content identity of every Model artifact member;
- the four Type and eight Operation coordinates explicitly renamed above.

The coordinate list supports the rename comparison; it is not a second taxonomy of
all execution dependencies. Omitted or stale selected semantics and Model identities
must refuse locally before an exchange is accepted.

## Fixed builds and observable acceptance

Build A is the production checker/compiler/evaluator at the replacement commit.
Build B is the independent test consumer whose identity is fixed from its source
files before the binding is derived. For both original and renamed authority:

1. A and B independently check and compile the Source into exactly eight Model
   members.
2. A admits B's exact Model members and B admits A's exact Model members without
   rebuilding or adding capabilities.
3. A and B run both Experiment inputs into exactly six Runtime members.
4. A admits B's exact Runtime members and B admits A's exact Runtime members.
5. After inverse coordinate mapping, both builds agree on declared input-boundary
   state, priority, pending identities, cancellation and final result. The baseline
   metric is `7`; the consecutive-pass variant metric is `0`.

Direct negative cases cover omitted/stale selected binding, unbounded collection
nesting and illegal callback, phase and bounded response-depth use. Build B admits
only the exact original/renamed Source pair and exact baseline/variant Experiment
matrix instead of becoming a general second compiler or Runtime.

## Product change

The witness reproduced one product contract defect: scheduled argument values in
Event Trace and Runtime Terminal Audit allowed integer values but excluded the
already-defined closed typed-value carrier. The product change admits exactly the
existing integer-or-typed-value union in those two wire locations and reseals the
Standard Schema package and Language Definition Bundle identities. No production
Python control flow, primitive, constructor, phase or dispatch changes.

## Validation and review gates

The replacement is acceptable only when all of the following are true:

- the public priority suite and fixed A/B exchange suite pass;
- affected authority rebuild and existing independent-operation regressions pass;
- required CI inventory assigns the two test modules to an existing shard, with no
  new shard, scheduler or timing database;
- Ruff, formatting and Pyright pass for changed Python;
- static scope review confirms a literal twelve-entry rename map, no recursive file
  scan or arbitrary replacement, no production priority names, and no inventory or
  rewrite platform files or mechanisms;
- independent Standards/Spec and DDMA/entropy reviews have no unresolved finding;
- the following exact history gates pass from the repository root:

  ```sh
  test "$(git merge-base 1596e77ea6807d4b91b8709da52c72eed346b0de HEAD)" = "1596e77ea6807d4b91b8709da52c72eed346b0de"
  test -z "$(git rev-list --min-parents=2 1596e77ea6807d4b91b8709da52c72eed346b0de..HEAD)"
  test "$(git rev-list --count 1596e77ea6807d4b91b8709da52c72eed346b0de..HEAD)" -eq 1
  test -z "$(git diff --name-only 1596e77ea6807d4b91b8709da52c72eed346b0de...HEAD | awk '$0 !~ /^libs\/gda-balancing\//')"
  ```

These checks establish only the bounded functional candidate. #575 retains the
complete scenario family and extension evidence. #542-#544 retain application and
trust activation. #879 retains the required physical deletion of obsolete RIR
`domain_kind`, the obsolete `maximum` wire-union branch, and every compatibility or
fallback binding after the real execution dependency set is closed.

Local candidate verification on 2026-09-21:

| Check | Result |
| --- | --- |
| Public witness plus fixed A/B exchange | 18 passed |
| Existing composition shard | 184 passed in 313.88 seconds |
| Existing bounded-fold and selected Operation-consumer regressions | 44 passed |
| Logical CI inventory | 1,985 tests and 347 package vectors; no missing, overlap, uncovered or unexpected rows |
| Packaged authority rebuild | exact fixed point |
| Ruff check/format and package Pyright | passed |
| Static scope gate | twelve literal rename entries; no traversal/arbitrary replacement or inventory/rewrite platform mechanism; no priority identifiers in production Python |

These are local pre-PR results. Required remote CI and exact-head independent review
remain acceptance evidence; this record must not be read as a merge or issue-closure
claim.

## Rollback

Revert the single replacement commit. This restores both resealed authorities and
the previous integer-only scheduled-value wire contract as one coherent baseline;
it also removes the finite witness and its CI inventory rows. Do not restore PR
#1000, merge its history, preserve its general inventory/reference infrastructure,
or keep compatibility readers for the reverted contract.
