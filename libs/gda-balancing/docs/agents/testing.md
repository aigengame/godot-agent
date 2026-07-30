# Schema 2.0 authority and feedback-latency verification

This document is the operational contract for issue
[#597](https://github.com/aigengame/godot-agent/issues/597). It explains what is
shared, what must remain independent, how required CI selects and partitions
tests, and how latency evidence is measured. It does not change Schema 2.0
semantics.

## Admitted authority lifecycle

Production has one process-scoped `AdmittedAuthorityContext`. Its lifecycle
module loads the exact packaged Kernel and sealed LDB graph, admits the complete
trust boundary, derives the language index, deeply freezes all reachable
objects, and only then publishes the context. Concurrent first use is
single-flight. A failed packaged admission publishes one deterministic refusal,
never a partial context.

All authority-dependent commands and model, migration, experiment, template,
projection, lowering, and Resolved-Model paths borrow this exact context.
Injected providers are separate lifecycles: a supplied Kernel/LDB pair is
admitted into an independently owned context and cannot update the packaged
cache.

Production JSON-Schema meta-validation has one cache domain. Its key is the
tuple of actual canonical schema bytes and actual canonical Kernel
schema-profile bytes. Claimed content identities are not cache keys.

## Test ownership and Consumer B

Read-only tests use the session-scoped `pristine_authority_context` fixture.
Mutation tests use `authority_candidate` or the bootstrap suite's equivalent
helper, which makes one deep mutable copy for the test's isolation boundary.
No mutation helper reloads or re-admits the packaged graph.

Consumer B remains an independent interpreter. It does not call the production
admission or schema-cache implementation. Its optional schema
meta-validation cache is separately implemented and separately keyed by
Consumer B's own canonical bytes. Tests compare both consumers on all positive,
negative, mutation, ordering, and resource-boundary vectors.

The former `test_schema2_bootstrap_conformance.py` is split by semantic
ownership:

- `test_schema2_bootstrap_authority.py`: graph, binding, identity, and package
  authority;
- `test_schema2_bootstrap_language.py`: language definitions, rules, reasons,
  diagnostics, and Wire Schemas;
- `test_schema2_bootstrap_composition.py`: Model, Operation, Runtime, and
  Template composition;
- `test_schema2_bootstrap_resources.py`: resource and adversarial boundaries.

Shared Consumer B implementation remains single-source in
`schema2_bootstrap_conformance_support.py`, which imports no production
admission or authority-cache module. Consumer A and mutable-fixture adapters
live separately in `schema2_bootstrap_production_support.py`.

## Inventory closure

`schema2-test-inventory-v1.json` records the 1,030 logical tests, 92 packaged
conformance vectors, and 90 accepted skip outcomes present before the final
#597 root-CI cutover. Logical identifiers preserve classes and parameter/vector
cases. `schema2-bootstrap-migration-map.json` maps every bootstrap test moved
to one of the four semantic files; normalization applies only to those
declared moves.

Run the closure check from the repository root:

```bash
uv run --frozen --project libs/gda-balancing \
  python libs/gda-balancing/tools/ci.py verify-inventory \
  --report /tmp/gda-balancing-inventory.json
```

The check fails if a baseline test or vector disappears, two shards overlap, a
current test is uncovered, or a shard selects a test outside the unfiltered
collection. New regression tests are allowed and increase the current count.
After execution, `verify-outcomes` reads each JUnit result and fails if a test
outside the recorded set is skipped or if any test is xfailed. Member pytest
also uses strict xfail behavior, and its collection hook rejects an explicit
`xfail(strict=False)` override, so an XPASS cannot conceal a newly introduced
xfail marker.

## Required, nightly, and release policy

`tools/ci.py` is the reviewed path and shard authority.
`libs/gda-balancing/**`, its lock, the shared Python setup action, CI/release
workflows, the root balancing-CI wiring regression, and shared
release/tag/scope tooling run the complete matrix. Only explicitly enumerated
root-product and documentation paths are unrelated. Every unknown path fails
closed to the complete matrix.

The shared Python setup action owns one exact uv version for every CI and
Release consumer; individual jobs do not restate or override that version.
The stdlib-only scope classifier is the exception to using uv: it pins Python
3.13 directly with `actions/setup-python` so an unrelated PR does not install a
package manager merely to classify paths.

An affecting PR runs:

1. inventory closure;
2. four pairwise-disjoint test shards: `fast`, `authority`, `language`, and
   `composition`;
3. a separate wheel and real-subprocess smoke shard;
4. the stable `gda-balancing required` aggregator.

Each executable shard has a hard eight-minute process bound and a fifteen-minute
job timeout. JUnit, raw logs, per-file totals, the 50 slowest tests, and the
outcome-closure report are uploaded even after a test failure. A known
unrelated PR runs only scope classification and the successful stable
aggregator. The one-minute unrelated target is measured from scope-job start to
aggregator completion; it is not the aggregator's job timeout.

Nightly and release validation run the complete unfiltered suite under a
separate fifteen-minute process bound. The nightly job has a twenty-minute job
timeout; the release build job has thirty minutes for inventory, tests, tag
validation, and build. Release also checks inventory closure and uploads the
inventory, JUnit, duration, outcome, and raw-log evidence. Maintainers can run
the exact nightly path against a PR head with **Run workflow** and
`run-balancing-unfiltered=true`; scheduled and manual evidence runs use unique,
non-cancelling concurrency groups, so a later `main` push cannot discard them.

Member release PRs may contain only `libs/gda-balancing/**`, so the member-owned
policy, inventory, and tests land separately from the root-owned workflow
wiring. That wiring must be reviewed as a non-releasing root change stacked
after the member change; it must not be folded into a releasing member PR.
The required-check cutover is complete: repository protection requires
`gda-balancing required`, and the duplicate serial member test/build path was
removed only after that protection was active.

To reproduce a shard:

```bash
uv run --no-project --python 3.13 python \
  libs/gda-balancing/tools/ci.py shard-paths authority |
  xargs uv run --frozen --project libs/gda-balancing pytest -q --durations=50
```

## Baseline and current evidence

The accepted pre-change exact head was `84e3212`. GitHub CI collected 1,030
tests and reported 940 passed, 90 skipped in 2,697.07 seconds. The critical
path was:

| File | Pre-change duration |
| --- | ---: |
| bootstrap conformance | 20:21 |
| model CLI | 5:48 |
| experiment CLI | 4:34 |
| authority CLI | 4:21 |
| template CLI | 4:11 |
| CLI conformance | 2:41 |
| independent model lowerer | 2:03 |

A cold `model check` process performed six full packaged-authority admissions
and 190 JSON-Schema meta-validations. The lifecycle regression suite now proves
one full packaged admission for every authority-dependent public command and
one meta-validation per unique canonical schema/profile key in the production
cache domain.

Local command latency was measured with dependencies already installed, one new
OS process per command, and `/usr/bin/time -p`:

| Command | `84e3212` | #597 worktree |
| --- | ---: | ---: |
| `version` | 1.34 s | 0.75 s |
| `model check examples/schema2/rpg-combat-cast/model-source.json` | 2.56 s | 0.83 s |
| `template list` | 2.33 s | 0.73 s |

The post-review PR #598 verification collects 1,085 tests and retains the same
92 packaged vectors. The four semantic matrix shards contain 990 passing tests
and the same 90 accepted skips; the separate required smoke shard contains five
passing tests. Across required execution, 995 tests pass, and outcome closure
reports zero new skips and zero xfails.
Exact-head manual-unfiltered evidence and individual-run wall clocks are kept
with the PR rather than frozen here. Command timings and individual-run timings
are diagnostic evidence; the rolling CI service-level measurement below is the
operational gate.

## CI latency measurement protocol

Measure from the earliest required balancing job's GitHub `startedAt` to the
stable aggregator's `completedAt`. This includes setup, collection, execution,
summary generation, and artifact upload. Exclude runner queue time and
cancelled superseded runs.

For balancing-affecting runs on the same runner class:

1. retain a rolling window of at least the latest 20 successful runs;
2. publish every raw GitHub run URL and elapsed value;
3. sort elapsed values ascending and select rank `ceil(0.95 * n)` (nearest-rank
   p95);
4. require p95 at or below ten minutes and target five minutes;
5. enforce the eight-minute shard bound on every run, independent of sample
   size.

Until 20 post-change samples exist, report every available sample and their
maximum; do not label that provisional maximum as p95. For explicitly
unrelated changes, measure the scope job `startedAt` through aggregator
`completedAt` and require less than one minute. Queue time is excluded in both
cases.
