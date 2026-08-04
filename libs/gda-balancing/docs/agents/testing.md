# Test coverage and feedback-latency contract

This is the operational contract for
[#597](https://github.com/aigengame/godot-agent/issues/597). Test-runtime work
may change witnesses and execution topology, but it must not remove a behavior
claim, sample an exhaustive vector set, add a skip/xfail, or weaken a public
process boundary.

## Authority reuse in tests

Production publishes one deeply immutable, process-scoped
`AdmittedAuthorityContext`. Loader-conformance tests still call the uncached
loader so raw bytes, IO failures, canonical transport, admission order, and
failure publication remain independently exercised.

Tests that only need an owned mutation candidate use
`schema2_test_authority.mutable_authorities()`. It deep-copies the already
admitted context, so every caller owns its Kernel/LDB pair without repeating
the roughly one-second packaged admission. The lifecycle regression proves
that two candidates do not alias and that the packaged admission count stays
at one.

Consumer B remains an independent interpreter. It imports neither production
admission nor the production schema-cache implementation. Consumer A/B
agreement, mutation refusal, ordering, and resource-boundary claims remain
separate witnesses in the coverage ledger.

## Executable coverage closure

Three versioned files make “coverage unchanged” executable:

- `schema2-test-inventory-v1.json` is the accepted pre-optimization snapshot at
  commit `2b81e2e`: 1,409 normalized test ids, 194 packaged
  conformance-vector ids, and 27 accepted skips. It is not regenerated from the
  optimized suite;
- `schema2-bootstrap-migration-map.json` binds that snapshot's test/vector
  digests, records declared file moves, and executes the one-to-many migration
  of the former reason loop into 98 stable `<reason>-<mutation>` test ids;
- `schema2-coverage-claims-v1.json` adds 15 high-risk cross-boundary claim
  families and 305 current machine-authority subjects. Every subject names its
  witness coverage and closes its own independent-domain minimum. Fixed
  package vectors, Kernel laws, Language rules, diagnostic reasons, and model
  vectors are resolved from the live admitted authority rather than copied
  into the ledger.

`verify-inventory` requires every accepted baseline test to remain represented
directly or through a fully closed declared expansion. It also requires the
current shard union to equal the current unfiltered collection with no overlap,
missing test, unexpected test, or missing packaged vector. `verify-claims`
requires every subject's declared witnesses and independent domains, rejects a
single test relabelled as multiple domains, closes live authority inventories,
and binds each expansion back to its claim. `verify-outcomes` rejects every
non-baseline skip and every xfail. Pytest also uses strict xfail and rejects
`xfail(strict=False)` during collection.

From this package directory:

```bash
uv run python tools/ci.py verify-inventory \
  --report /tmp/gda-balancing-inventory.json
uv run python tools/ci.py verify-claims \
  --report /tmp/gda-balancing-claims.json
```

## Shards and aggregate verdict

`tools/ci.py` is the single shard authority. The measured partition is:

| Shard | Ownership |
| --- | --- |
| `fast` | policy, schema, canonical, isolation, and small command tests |
| `authority-cli` | public authority/package CLI and built wheel |
| `authority-bootstrap` | authority graph and resource admission |
| `language-bootstrap` | language, reason, rule, and Formula bootstrap |
| `model` | public Model compiler |
| `experiment` | public Experiment evaluator |
| `composition` | CLI conformance, composition, lowerer, and Template |
| `smoke` | real console/module subprocess key paths |

Each shard has an eight-minute process bound and a fifteen-minute job bound.
Every job uploads JUnit, raw logs, a measured wall-time report, per-file
duration totals, slow tests, and outcome closure. `aggregate-junit` then
requires exactly one JUnit and wall report for every shard and exactly one
executed row for every current test id. Its unified JSON rejects failures,
unexpected skips, every xfail, duplicate/missing tests, and incomplete shards;
it also publishes per-file totals, the 50 slowest nodes, the critical shard,
parallel critical-path wall time, and cumulative test seconds.

An affecting PR runs inventory/claims, seven semantic runners, one smoke
runner, and the stable `gda-balancing required` aggregate. Scheduled and
manually dispatched evidence runs use the same exact matrix instead of a
duplicate serial suite. This preserves the complete inventory while moving
parallelism to independent GitHub runners.

Release uses the same matrix. Prepare, every shard, aggregate, and build each
check out `needs.cut-release.outputs.balancing_sha`. The aggregate runs under
`always()` and publishes its failed verdict even when a shard fails, times out,
or omits an artifact. Distribution build cannot start until the exact aggregate
closes; PyPI publication depends on that verified build. Release artifacts
include inventory, claim, shard, outcome, duration, wall, and aggregate reports.

## Supported local runner

Use the local runner instead of xdist:

```bash
uv run python tools/run_test_shards.py \
  --output-dir /tmp/gda-balancing-tests
```

The default is one semantic shard at a time and an exclusive smoke shard. A
developer may request `--jobs 2`, but only after measuring the machine: the
2026-08-04 pre-final two-worker trial passed the then-current 1,516 tests with
exact closure, yet CPU contention increased cumulative test time to 2,173.365
seconds and wall time to 1,222.917 seconds. It is therefore evidence against
two workers as the default on the measured machine. Four-way xdist remains
unsupported because it caused two migration subprocess watchdog failures and
took 18:15.

`--repeat 3` publishes median/max wall time and cumulative test seconds. Smoke
always runs alone so wheel and subprocess watchdog claims are not weakened by
local contention.

## Optimization evidence

The accepted pre-optimization snapshot had 1,409 tests: 1,382 passed and 27
skipped. Cumulative test time was 1,186.764 seconds. The dominant files were
authority CLI (221.713 s), experiment CLI (207.769 s), E2E subprocess paths
(173.198 s), Model CLI (128.938 s), and language bootstrap (120.635 s).

Two optimizations are admitted:

1. Non-loader tests copy the admitted immutable authority instead of repeating
   loader IO and admission. Fresh load measured roughly 0.95-1.46 seconds;
   `mutable_pair()` measured roughly 0.16 seconds.
2. The built-wheel test still compares every packaged authority JSON member
   byte-for-byte and still executes the installed wheel through `python -m`.
   Exhaustive package `list/get` behavior remains in its independent public
   command test. The installed wheel now executes every root-declared
   `package get` through one isolated batched dispatch process, while a separate
   real `python -m ... package list` retains cold entry-point evidence. This
   reduced the exhaustive wheel test from 108.76 seconds to 17.28 seconds
   without substituting a source-tree witness for installed-artifact behavior.

The earlier 671.369-second single run was useful for selecting the approach but
is not final evidence: review strengthened the wheel and aggregate boundaries
afterward. Only the post-review three-run same-SHA results recorded with the
protocol below are acceptance evidence; a single run is never presented as a
p95.

Rejected optimizations stay rejected: vector sampling, new skips/xfails,
shared relocatable artifact stores (anchors correctly bind their publication
location), four-way xdist, and a reused `Draft202012Validator` prototype that
was slower than the current path.

## CI latency protocol

For the same runner class and exact commit:

1. compare median cumulative test seconds across three complete runs and
   require at least 10% improvement;
2. measure required-path wall time from the earliest balancing job start to the
   stable aggregate completion and require at least 25% improvement;
3. require every shard below eight minutes with at least 25% measured headroom;
4. retain every run URL and raw duration artifact;
5. until 20 post-change samples exist, report all samples and their maximum;
   only then report nearest-rank p95, which must remain at or below ten minutes
   and targets five minutes.

Queue time is excluded. Setup, collection, execution, reporting, and artifact
upload are included. An unrelated change is measured from scope-job start to
stable aggregate completion and must remain below one minute.
